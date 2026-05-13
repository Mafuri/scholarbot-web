"""Profile router — /api/profile/* and /api/readiness"""
import uuid
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, User
from app.dependencies import get_current_user
from app.services.cache import invalidate_user_cache
from app.config import UPLOAD_DIR, ALLOWED_EXTENSIONS

router = APIRouter(prefix="/api", tags=["profile"])
logger = logging.getLogger(__name__)


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    major: Optional[str] = None
    school: Optional[str] = None
    gpa: Optional[float] = None
    gpa_original: Optional[float] = None
    gpa_scale: Optional[float] = None
    financial_need: Optional[bool] = None
    nationality: Optional[str] = None
    languages: Optional[list] = None
    skills: Optional[list] = None
    extracurriculars: Optional[list] = None
    personal_statement: Optional[str] = None
    demographic_tags: Optional[list] = None


@router.patch("/profile")
async def update_profile(
    upd: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    for field, value in upd.dict(exclude_none=True).items():
        if field in ('gpa_original', 'gpa_scale'): continue
        if field == 'gpa' and value is not None:
            from app.services.gpa import normalise_gpa
            info = normalise_gpa(value, country=upd.nationality or user.nationality or '')
            user.gpa = info['gpa_4']
            continue
        setattr(user, field, value)
    user.updated_at = datetime.utcnow()
    db.commit(); db.refresh(user)
    invalidate_user_cache(user.id)
    return user.to_dict()


@router.get("/readiness")
async def readiness(user: User = Depends(get_current_user)):
    from engine.scholarship_engine import compute_readiness_score
    return compute_readiness_score(user.to_dict())


def _validate_upload(filename: str, content: bytes) -> str:
    """Validate file by magic bytes — blocks executables renamed as docs."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400,
            f"Unsupported type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "File exceeds 10MB limit.")
    head = content[:8]
    pdf_magic  = bytes([0x25, 0x50, 0x44, 0x46])          # %PDF
    zip_magic  = bytes([0x50, 0x4B, 0x03, 0x04])          # PK.. (docx)
    jpg_magic  = bytes([0xFF, 0xD8, 0xFF])                 # JPEG
    png_magic  = bytes([0x89, 0x50, 0x4E, 0x47])           # PNG
    tif_le     = bytes([0x49, 0x49, 0x2A, 0x00])          # TIFF LE
    tif_be     = bytes([0x4D, 0x4D, 0x00, 0x2A])          # TIFF BE
    if ext == ".pdf" and head[:4] == pdf_magic:
        return ext
    if ext in (".docx", ".doc") and head[:4] == zip_magic:
        return ext
    if ext in (".jpg", ".jpeg") and head[:3] == jpg_magic:
        return ext
    if ext == ".png" and head[:4] == png_magic:
        return ext
    if ext in (".tiff", ".tif") and (head[:4] == tif_le or head[:4] == tif_be):
        return ext
    if ext in (".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"):
        # Allow images without strict magic check (various formats)
        return ext
    raise HTTPException(400,
        "File content does not match its extension. Upload a valid document.")


@router.post("/profile/upload-doc")
async def upload_doc(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content_bytes = await file.read()
    ext = _validate_upload(file.filename or "upload.bin", content_bytes)
    d = Path(f"{UPLOAD_DIR}/{user.id}")
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{uuid.uuid4().hex[:8]}_{file.filename}"
    p.write_bytes(content_bytes)

    text = _extract_text(p, ext, content_bytes)
    if not text.strip():
        return {"message": "Uploaded. Add text content to your CV for auto-matching.",
                "extracted": {}, "user": user.to_dict()}

    extracted = _extract_profile(text, content_bytes, ext)
    updated_fields = _apply_extracted(user, extracted, db)
    invalidate_user_cache(user.id)

    from engine.opportunity_db import match_opportunities
    matched = match_opportunities(user.to_dict())[:10]

    return {
        "message": "Document scanned and profile updated",
        "extracted": extracted,
        "updated_fields": updated_fields,
        "matched_count": len(matched),
        "top_matches": [
            {"name": o["name"], "amount_usd": o["amount_usd"],
             "deadline": o.get("deadline", "")}
            for o in matched[:5]
        ],
        "user": user.to_dict(),
    }


def _extract_text(p: Path, ext: str, raw: bytes) -> str:
    try:
        if ext == ".pdf":
            import fitz
            doc = fitz.open(str(p))
            text = " ".join(pg.get_text() for pg in doc)
            doc.close()
            if len(text.strip()) > 50:
                return text
            # Scanned PDF → Claude OCR
            return _ocr_vision(raw, "pdf")
        elif ext in (".docx", ".doc"):
            import docx as _docx
            d = _docx.Document(str(p))
            return " ".join(para.text for para in d.paragraphs)
        else:
            return _ocr_vision(raw, ext.lstrip("."))
    except Exception as e:
        logger.warning("Text extraction failed: %s", e)
        return ""


def _ocr_vision(raw: bytes, media_type: str) -> str:
    from app.config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY:
        return ""
    import base64, requests as req
    mime = "image/png" if media_type in ("png","jpg","jpeg","tiff","bmp","webp") \
        else "application/pdf"
    b64 = base64.b64encode(raw).decode()
    try:
        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 2000,
                  "messages": [{"role": "user", "content": [
                      {"type": "image",
                       "source": {"type": "base64", "media_type": mime, "data": b64}},
                      {"type": "text", "text":
                       "Extract ALL text from this document. Include names, grades, GPA, "
                       "courses, dates, institutions. Return only the extracted text."}
                  ]}]},
            timeout=60,
        )
        return r.json()["content"][0]["text"]
    except Exception as e:
        logger.warning("OCR failed: %s", e)
        return ""


def _extract_profile(text: str, raw: bytes, ext: str) -> dict:
    import re
    extracted: dict = {}
    text_lower = text.lower()

    # GPA
    m = re.search(r"(?:gpa|cgpa|grade point)[:\s]+(\d+\.?\d*)", text_lower)
    if m:
        gpa_raw = float(m.group(1))
        extracted["gpa_raw"] = gpa_raw

    # Degree level
    if any(w in text_lower for w in ["phd", "ph.d", "doctorate", "doctoral"]):
        extracted["degree_level"] = "Postgraduate"
    elif any(w in text_lower for w in ["master", "msc", "mba", "m.sc", "postgrad"]):
        extracted["degree_level"] = "Graduate"
    elif any(w in text_lower for w in ["bachelor", "bsc", "undergraduate", "b.sc"]):
        extracted["degree_level"] = "Undergraduate"

    # AI extraction of structured fields
    from app.config import ANTHROPIC_API_KEY
    if ANTHROPIC_API_KEY:
        from app.services.llm import get_llm
        llm = get_llm()
        try:
            import json as _json
            raw_resp = llm(
                "Extract CV information. Return ONLY a JSON object, no other text.",
                f"Extract from this CV text:\n{text[:3000]}\n\n"
                "Return JSON with: name, major, school, nationality, "
                "skills (list of 10), extracurriculars (list of 5), "
                "personal_statement (2-sentence summary). "
                "Use empty string/list if not found."
            )
            start = raw_resp.find("{"); end = raw_resp.rfind("}") + 1
            if start >= 0 and end > start:
                ai_data = _json.loads(raw_resp[start:end])
                for key in ["name", "major", "school", "nationality",
                             "skills", "extracurriculars", "personal_statement"]:
                    if ai_data.get(key):
                        extracted[key] = ai_data[key]
        except Exception as e:
            logger.warning("AI extraction failed: %s", e)
    return extracted


def _apply_extracted(user: User, extracted: dict, db: Session) -> list:
    from app.services.gpa import normalise_gpa
    updatable = ["name", "major", "school", "nationality", "degree_level",
                 "skills", "extracurriculars", "personal_statement"]
    updated = []

    # Handle GPA with normalisation
    if "gpa_raw" in extracted:
        info = normalise_gpa(
            extracted["gpa_raw"], country=user.nationality or ""
        )
        user.gpa = info["gpa_4"]
        user.gpa_original = extracted["gpa_raw"]
        user.gpa_scale = info["scale"]
        updated.append("gpa")

    for f in updatable:
        v = extracted.get(f)
        if v and v != "" and v != []:
            setattr(user, f, v)
            updated.append(f)

    if updated:
        user.updated_at = datetime.utcnow()
        db.commit(); db.refresh(user)
    return updated
