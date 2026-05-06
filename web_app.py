"""
web_app.py — ScholarBot Web Platform
=====================================
Full-stack FastAPI backend serving the React SPA.
Handles: auth, profiles, scholarship matching, essay generation,
         application packages, email monitoring, interview coach.

Deploy: render.com / railway.app / any VPS
"""

from __future__ import annotations
import json, logging, os, secrets, time, uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger(__name__)

# ── App ──────────────────────────────────────────────────────
app = FastAPI(
    title="ScholarBot API",
    description="AI-powered scholarship application platform",
    version="1.0.0",
)

app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"])

# ── Simple in-memory store (swap for PostgreSQL in production) ──
USERS: dict[str, dict] = {}       # user_id → user data
SESSIONS: dict[str, str] = {}     # token → user_id
APPLICATIONS: dict[str, list] = {}  # user_id → [applications]
JOBS: dict[str, dict] = {}         # job_id → {status, result}

Path("data/uploads").mkdir(parents=True, exist_ok=True)
Path("data/packages").mkdir(parents=True, exist_ok=True)
Path("static").mkdir(parents=True, exist_ok=True)

security = HTTPBearer(auto_error=False)

# ── Auth helpers ─────────────────────────────────────────────

def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not creds:
        raise HTTPException(401, "Not authenticated")
    user_id = SESSIONS.get(creds.credentials)
    if not user_id or user_id not in USERS:
        raise HTTPException(401, "Invalid or expired token")
    return USERS[user_id]

def optional_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not creds:
        return None
    user_id = SESSIONS.get(creds.credentials)
    return USERS.get(user_id) if user_id else None

# ── Pydantic models ──────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    degree_level: str  # "Undergraduate" | "Graduate" | "Postgraduate"
    major: str
    school: str
    nationality: str = "Kenya"
    gpa: float = 0.0
    financial_need: bool = False

class LoginRequest(BaseModel):
    email: str
    password: str

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    major: Optional[str] = None
    school: Optional[str] = None
    gpa: Optional[float] = None
    graduation_year: Optional[int] = None
    financial_need: Optional[bool] = None
    nationality: Optional[str] = None
    languages: Optional[list[str]] = None
    skills: Optional[list[str]] = None
    extracurriculars: Optional[list[str]] = None
    personal_statement: Optional[str] = None
    demographic_tags: Optional[list[str]] = None

class EssayRequest(BaseModel):
    scholarship_id: str
    tone: str = "personal-narrative"
    max_words: int = 400

class PrepareRequest(BaseModel):
    scholarship_ids: Optional[list[str]] = None
    top_n: int = 5

# ── Routes: Auth ─────────────────────────────────────────────

@app.post("/api/auth/register")
async def register(req: RegisterRequest):
    # Check email not taken
    for u in USERS.values():
        if u["email"] == req.email:
            raise HTTPException(400, "Email already registered")

    user_id = f"user_{uuid.uuid4().hex[:10]}"
    hashed = _hash_password(req.password)
    user = {
        "id": user_id,
        "name": req.name,
        "email": req.email,
        "password_hash": hashed,
        "degree_level": req.degree_level,
        "major": req.major,
        "school": req.school,
        "nationality": req.nationality,
        "gpa": req.gpa,
        "financial_need": req.financial_need,
        "languages": ["English"],
        "skills": [],
        "extracurriculars": [],
        "demographic_tags": [],
        "personal_statement": "",
        "created_at": datetime.now().isoformat(),
        "plan": "free",
        "applications_this_month": 0,
    }
    USERS[user_id] = user
    APPLICATIONS[user_id] = []
    token = _create_token(user_id)
    logger.info("New user registered: %s (%s)", req.name, req.degree_level)
    return {"token": token, "user": _safe_user(user)}


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    for user in USERS.values():
        if user["email"] == req.email:
            if _check_password(req.password, user["password_hash"]):
                token = _create_token(user["id"])
                return {"token": token, "user": _safe_user(user)}
    raise HTTPException(401, "Invalid email or password")


@app.get("/api/auth/me")
async def me(user=Depends(get_current_user)):
    return _safe_user(user)


# ── Routes: Profile ──────────────────────────────────────────

@app.patch("/api/profile")
async def update_profile(update: ProfileUpdate, user=Depends(get_current_user)):
    for field, value in update.dict(exclude_none=True).items():
        user[field] = value
    return _safe_user(user)


@app.post("/api/profile/upload-doc")
async def upload_document(file: UploadFile = File(...),
                           user=Depends(get_current_user)):
    """Upload CV, transcript, or certificates for profile extraction."""
    allowed = {".pdf", ".docx", ".doc", ".jpg", ".jpeg", ".png"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"File type {ext} not supported")

    user_dir = Path(f"data/uploads/{user['id']}")
    user_dir.mkdir(parents=True, exist_ok=True)
    save_path = user_dir / f"{uuid.uuid4().hex[:8]}_{file.filename}"

    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Try to extract profile data
    extracted = _extract_from_doc(str(save_path), ext, user)
    if extracted:
        user.update(extracted)
        return {"message": "Document uploaded and profile updated",
                "extracted": extracted}
    return {"message": "Document uploaded", "path": str(save_path)}


# ── Routes: Scholarships ─────────────────────────────────────

@app.get("/api/scholarships")
async def get_scholarships(
    degree_level: Optional[str] = None,
    field: Optional[str] = None,
    region: Optional[str] = None,
    min_amount: Optional[int] = None,
    max_amount: Optional[int] = None,
    user=Depends(optional_user),
):
    """Get all scholarships with optional filters."""
    from engine.scholarship_engine import get_scholarships_for_profile
    profile = user if user else _default_profile()
    if degree_level:
        profile = dict(profile)
        profile["degree_level"] = degree_level
    scholarships = get_scholarships_for_profile(profile)
    # Apply filters
    if min_amount:
        scholarships = [s for s in scholarships if s.get("amount_usd", 0) >= min_amount]
    if max_amount:
        scholarships = [s for s in scholarships if s.get("amount_usd", 0) <= max_amount]
    if field:
        scholarships = [s for s in scholarships
                       if field.lower() in " ".join(s.get("tags", [])).lower() or
                          field.lower() in s.get("name", "").lower()]
    if region:
        scholarships = [s for s in scholarships
                       if any(region.lower() in c.lower()
                              for c in s.get("eligible_countries", []))]
    return {"scholarships": scholarships, "count": len(scholarships)}


@app.get("/api/scholarships/matched")
async def get_matched(user=Depends(get_current_user)):
    """Get scholarships matched and ranked for this user's profile."""
    from engine.scholarship_engine import rank_for_profile
    ranked = rank_for_profile(user)
    return {"scholarships": ranked, "count": len(ranked),
            "total_potential_usd": sum(s.get("amount_usd", 0) for s in ranked)}


@app.get("/api/scholarships/{scholarship_id}")
async def get_scholarship(scholarship_id: str, user=Depends(optional_user)):
    from engine.scholarship_engine import get_by_id
    s = get_by_id(scholarship_id)
    if not s:
        raise HTTPException(404, "Scholarship not found")
    return s


# ── Routes: Essays ───────────────────────────────────────────

@app.post("/api/essays/generate")
async def generate_essay(req: EssayRequest,
                          background_tasks: BackgroundTasks,
                          user=Depends(get_current_user)):
    """Generate a tailored essay for a scholarship."""
    from engine.scholarship_engine import get_by_id
    scholarship = get_by_id(req.scholarship_id)
    if not scholarship:
        raise HTTPException(404, "Scholarship not found")

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    JOBS[job_id] = {"status": "running", "result": None, "started_at": time.time()}

    background_tasks.add_task(
        _generate_essay_job, job_id, scholarship, user, req.tone, req.max_words)

    return {"job_id": job_id, "status": "running",
            "message": "Essay generation started — poll /api/jobs/{job_id} for result"}


@app.get("/api/essays/{scholarship_id}")
async def get_essay(scholarship_id: str, user=Depends(get_current_user)):
    """Get a previously generated essay."""
    essay_path = Path(f"data/packages/{user['id']}/{scholarship_id}_essay.txt")
    if not essay_path.exists():
        raise HTTPException(404, "No essay found — generate one first")
    return {"essay": essay_path.read_text(encoding="utf-8"),
            "scholarship_id": scholarship_id}


# ── Routes: Application Packages ────────────────────────────

@app.post("/api/packages/prepare")
async def prepare_packages(req: PrepareRequest,
                            background_tasks: BackgroundTasks,
                            user=Depends(get_current_user)):
    """Generate complete application packages for top N scholarships."""
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    JOBS[job_id] = {"status": "running", "result": None, "started_at": time.time()}
    background_tasks.add_task(_prepare_packages_job, job_id, user, req)
    return {"job_id": job_id, "status": "running",
            "message": f"Preparing packages for top {req.top_n} scholarships"}


@app.get("/api/packages")
async def list_packages(user=Depends(get_current_user)):
    """List all generated application packages for this user."""
    pkg_dir = Path(f"data/packages/{user['id']}")
    if not pkg_dir.exists():
        return {"packages": []}
    packages = []
    for d in sorted(pkg_dir.iterdir()):
        if d.is_dir() and (d / "briefing.html").exists():
            meta_path = d / "meta.json"
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            packages.append({
                "id": d.name,
                "scholarship": meta.get("scholarship", d.name),
                "amount_usd": meta.get("amount_usd", 0),
                "deadline": meta.get("deadline", ""),
                "days_left": meta.get("days_left", 0),
                "url": meta.get("url", ""),
                "essay_preview": _essay_preview(d),
                "briefing_url": f"/api/packages/{user['id']}/{d.name}/briefing",
                "essay_url": f"/api/packages/{user['id']}/{d.name}/essay",
            })
    return {"packages": packages}


@app.get("/api/packages/{user_id}/{package_id}/briefing")
async def get_briefing(user_id: str, package_id: str,
                        user=Depends(get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(403, "Access denied")
    path = Path(f"data/packages/{user_id}/{package_id}/briefing.html")
    if not path.exists():
        raise HTTPException(404, "Briefing not found")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/api/packages/{user_id}/{package_id}/essay")
async def get_package_essay(user_id: str, package_id: str,
                              user=Depends(get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(403, "Access denied")
    path = Path(f"data/packages/{user_id}/{package_id}/essay.txt")
    if not path.exists():
        raise HTTPException(404, "Essay not found")
    return {"essay": path.read_text(encoding="utf-8")}


@app.get("/api/packages/{user_id}/{package_id}/download")
async def download_package(user_id: str, package_id: str,
                            user=Depends(get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(403, "Access denied")
    path = Path(f"data/packages/{user_id}/{package_id}/briefing.html")
    if not path.exists():
        raise HTTPException(404, "Package not found")
    return FileResponse(path, media_type="text/html",
                        filename=f"{package_id}_briefing.html")


# ── Routes: Applications tracker ────────────────────────────

@app.get("/api/applications")
async def list_applications(user=Depends(get_current_user)):
    apps = APPLICATIONS.get(user["id"], [])
    return {
        "applications": apps,
        "total": len(apps),
        "submitted": sum(1 for a in apps if a.get("status") == "submitted"),
        "pending": sum(1 for a in apps if a.get("status") == "pending"),
        "won": sum(1 for a in apps if a.get("status") == "won"),
        "total_applied_usd": sum(a.get("amount_usd", 0) for a in apps),
        "total_won_usd": sum(a.get("amount_usd", 0) for a in apps
                             if a.get("status") == "won"),
    }


@app.post("/api/applications/record")
async def record_application(data: dict, user=Depends(get_current_user)):
    """Record that user manually submitted an application."""
    app_record = {
        "id": f"app_{uuid.uuid4().hex[:8]}",
        "scholarship_id": data.get("scholarship_id"),
        "scholarship_name": data.get("scholarship_name"),
        "amount_usd": data.get("amount_usd", 0),
        "status": "submitted",
        "submitted_at": datetime.now().isoformat(),
        "deadline": data.get("deadline"),
    }
    if user["id"] not in APPLICATIONS:
        APPLICATIONS[user["id"]] = []
    APPLICATIONS[user["id"]].append(app_record)
    user["applications_this_month"] = user.get("applications_this_month", 0) + 1
    return app_record


@app.patch("/api/applications/{app_id}/outcome")
async def update_outcome(app_id: str, data: dict,
                          user=Depends(get_current_user)):
    """Update the outcome of an application (won/rejected/pending)."""
    apps = APPLICATIONS.get(user["id"], [])
    for a in apps:
        if a["id"] == app_id:
            a["status"] = data.get("status", a["status"])
            a["outcome_date"] = datetime.now().isoformat()
            a["notes"] = data.get("notes", "")
            return a
    raise HTTPException(404, "Application not found")


# ── Routes: Interview Coach ──────────────────────────────────

@app.get("/api/interview/questions/{scholarship_slug}")
async def get_interview_questions(scholarship_slug: str,
                                   user=Depends(get_current_user)):
    from engine.interview_data import QUESTION_BANKS
    questions = QUESTION_BANKS.get(scholarship_slug.lower(),
                                   QUESTION_BANKS["general"])
    return {"scholarship": scholarship_slug, "questions": questions}


@app.post("/api/interview/score")
async def score_interview_answer(data: dict, user=Depends(get_current_user)):
    """Score an interview answer using AI."""
    from engine.scholarship_engine import score_answer
    result = score_answer(
        question=data.get("question", ""),
        answer=data.get("answer", ""),
        profile=user,
        scholarship=data.get("scholarship", "general"),
    )
    return result


# ── Routes: Jobs (async polling) ─────────────────────────────

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, user=Depends(get_current_user)):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


# ── Routes: Stats / Dashboard ────────────────────────────────

@app.get("/api/dashboard")
async def dashboard(user=Depends(get_current_user)):
    from engine.scholarship_engine import get_scholarships_for_profile
    matched = get_scholarships_for_profile(user)
    apps = APPLICATIONS.get(user["id"], [])
    return {
        "user": _safe_user(user),
        "scholarships_matched": len(matched),
        "total_potential_usd": sum(s.get("amount_usd", 0) for s in matched),
        "applications_submitted": sum(1 for a in apps if a.get("status") == "submitted"),
        "applications_won": sum(1 for a in apps if a.get("status") == "won"),
        "total_won_usd": sum(a.get("amount_usd", 0) for a in apps if a.get("status") == "won"),
        "upcoming_deadlines": sorted(
            [{"name": s.get("name"), "deadline": s.get("deadline"),
              "amount_usd": s.get("amount_usd"), "days_left": _days_until(s.get("deadline", ""))}
             for s in matched if _days_until(s.get("deadline", "")) < 60],
            key=lambda x: x["days_left"]
        )[:5],
    }


# ── Admin / Health ────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "users": len(USERS),
            "version": "1.0.0", "timestamp": datetime.now().isoformat()}


@app.get("/api/stats")
async def public_stats():
    return {
        "total_users": len(USERS),
        "scholarships_in_db": _scholarship_count(),
        "total_potential_funding_usd": 2200000,
        "degree_levels": ["Undergraduate", "Graduate", "Postgraduate"],
        "countries_covered": 50,
        "fields_covered": ["CS", "IT", "Cybersecurity", "AI/ML",
                           "Data Science", "Software Engineering"],
    }


# ── Static files & SPA fallback ───────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_spa():
    spa_path = Path("static/index.html")
    if spa_path.exists():
        return HTMLResponse(spa_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>ScholarBot API running. Frontend not found.</h1>")


try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    pass

# Catch-all for SPA routing
@app.get("/{path:path}", response_class=HTMLResponse)
async def spa_fallback(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    spa_path = Path("static/index.html")
    if spa_path.exists():
        return HTMLResponse(spa_path.read_text(encoding="utf-8"))
    raise HTTPException(404)


# ── Background job workers ────────────────────────────────────

def _generate_essay_job(job_id: str, scholarship: dict, user: dict,
                         tone: str, max_words: int):
    try:
        from engine.scholarship_engine import generate_essay_for
        essay = generate_essay_for(scholarship, user, tone, max_words)
        # Save to user's package dir
        pkg_dir = Path(f"data/packages/{user['id']}/{scholarship['id']}")
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "essay.txt").write_text(essay, encoding="utf-8")
        JOBS[job_id] = {
            "status": "done",
            "result": {"essay": essay, "word_count": len(essay.split()),
                       "scholarship_id": scholarship["id"]},
            "completed_at": time.time(),
        }
    except Exception as e:
        JOBS[job_id] = {"status": "failed", "error": str(e)}


def _prepare_packages_job(job_id: str, user: dict, req: PrepareRequest):
    try:
        from engine.scholarship_engine import prepare_packages
        packages = prepare_packages(user, req.top_n, req.scholarship_ids)
        JOBS[job_id] = {
            "status": "done",
            "result": {"packages": packages, "count": len(packages)},
            "completed_at": time.time(),
        }
    except Exception as e:
        JOBS[job_id] = {"status": "failed", "error": str(e)}


# ── Helpers ──────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    import hashlib
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{h}"

def _check_password(password: str, hashed: str) -> bool:
    import hashlib
    try:
        salt, h = hashed.split(":", 1)
        return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == h
    except Exception:
        return False

def _create_token(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = user_id
    return token

def _safe_user(user: dict) -> dict:
    return {k: v for k, v in user.items() if k != "password_hash"}

def _default_profile() -> dict:
    return {"degree_level": "Graduate", "nationality": "Kenya",
            "major": "Information Technology", "gpa": 3.0,
            "financial_need": False, "demographic_tags": []}

def _days_until(deadline_str: str) -> int:
    try:
        return (datetime.strptime(deadline_str, "%Y-%m-%d") - datetime.now()).days
    except Exception:
        return 999

def _essay_preview(pkg_dir: Path) -> str:
    essay_path = pkg_dir / "essay.txt"
    if essay_path.exists():
        return essay_path.read_text(encoding="utf-8")[:120] + "..."
    return ""

def _scholarship_count() -> int:
    try:
        from engine.scholarship_engine import count_scholarships
        return count_scholarships()
    except Exception:
        return 80

def _extract_from_doc(path: str, ext: str, user: dict) -> dict:
    """Try to extract profile data from uploaded document."""
    extracted = {}
    try:
        if ext == ".pdf":
            import fitz
            doc = fitz.open(path)
            text = " ".join(p.get_text() for p in doc)
        elif ext in (".docx", ".doc"):
            import docx
            d = docx.Document(path)
            text = " ".join(p.text for p in d.paragraphs)
        else:
            return {}
        # Simple GPA extraction
        import re
        gpa_match = re.search(r'(?:gpa|cgpa)[:\s]+(\d+\.?\d*)', text.lower())
        if gpa_match:
            gpa = float(gpa_match.group(1))
            if gpa > 4.0:
                gpa = round(gpa * 4.0 / 5.0, 2)
            extracted["gpa"] = min(4.0, gpa)
    except Exception as e:
        logger.debug("Doc extraction failed: %s", e)
    return extracted
