"""
ScholarBot — Security utilities.
JWT creation/decoding, password hashing, input sanitisation.
"""
import re
from datetime import datetime, timedelta
from jose import JWTError, jwt
import bcrypt as _bcrypt
from app.config import SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_DAYS


# ── Password hashing ──────────────────────────────────────────
def hash_password(pw: str) -> str:
    pw_bytes = pw.encode("utf-8")[:72]
    return _bcrypt.hashpw(pw_bytes, _bcrypt.gensalt(12)).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        pw_bytes = pw.encode("utf-8")[:72]
        return _bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT ───────────────────────────────────────────────────────
def create_token(user_id: str) -> str:
    exp = datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": user_id, "exp": exp},
        SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(
            token, SECRET_KEY, algorithms=[JWT_ALGORITHM]
        )
        return payload.get("sub")
    except JWTError:
        return None


# ── Input sanitisation ────────────────────────────────────────
_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+)?(?:previous|above|prior)",
    r"disregard\s+(?:all\s+)?(?:previous|above|prior)",
    r"forget\s+(?:all\s+)?(?:previous|above)",
    r"new\s+instructions?:",
    r"system\s*prompt",
    r"you\s+are\s+now",
]


def sanitise(text: str, max_len: int = 8000) -> str:
    """Strip control chars and block prompt injection."""
    if not text:
        return ""
    text = "".join(
        ch for ch in str(text) if ord(ch) >= 32 or ch in "\n\r\t"
    )
    for pattern in _INJECTION_PATTERNS:
        text = re.sub(pattern, "[REMOVED]", text, flags=re.IGNORECASE)
    return text[:max_len]


def safe_profile(profile: dict) -> dict:
    """Return sanitised copy of profile for LLM prompts."""
    safe: dict = {}
    str_fields = [
        "name", "major", "school", "nationality",
        "personal_statement", "degree_level",
    ]
    list_fields = ["skills", "extracurriculars", "languages"]
    for f in str_fields:
        safe[f] = sanitise(str(profile.get(f, "")), 500)
    for f in list_fields:
        raw = profile.get(f, [])
        if isinstance(raw, list):
            safe[f] = [sanitise(str(x), 100) for x in raw[:20]]
        else:
            safe[f] = [sanitise(str(raw), 500)]
    safe["gpa"] = float(profile.get("gpa", 0) or 0)
    safe["financial_need"] = bool(profile.get("financial_need", False))
    safe["id"] = str(profile.get("id", ""))
    return safe
