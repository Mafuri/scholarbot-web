"""
ScholarBot security — password hashing, JWT tokens, 2FA, input sanitisation.
"""
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional
from jose import jwt, JWTError
import bcrypt
from app.config import SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_DAYS

# ── Injection patterns ─────────────────────────────────────────
_INJECTION = [
    r"ignore\s+(?:all\s+)?(?:previous|above|prior)",
    r"disregard\s+(?:all\s+)?(?:previous|above)",
    r"new\s+instructions?:",
    r"system\s*prompt",
    r"you\s+are\s+now",
    r"forget\s+(?:all\s+)?(?:previous|your)",
    r"act\s+as\s+(?:a\s+)?(?:DAN|jailbreak|uncensored)",
    r"<\s*/?(?:system|user|assistant)\s*>",
]


def normalise_unicode(text: str) -> str:
    """Normalise unicode homoglyphs used in prompt injection attacks."""
    import unicodedata
    text = unicodedata.normalize("NFKC", text)
    for ch in ["\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"]:
        text = text.replace(ch, "")
    return text


def sanitise(text, max_len: int = 8000) -> str:
    """Sanitise user input — strip control chars and injection patterns."""
    if not text:
        return ""
    text = normalise_unicode(str(text))
    text = "".join(ch for ch in text if ord(ch) >= 32 or ch in "\n\r\t")
    for pattern in _INJECTION:
        text = re.sub(pattern, "[REMOVED]", text, flags=re.IGNORECASE)
    return text[:max_len]


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode()


def check_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def make_token(uid: str, days: int = JWT_EXPIRE_DAYS) -> str:
    return jwt.encode(
        {"sub": uid,
         "exp": datetime.utcnow() + timedelta(days=days),
         "iat": datetime.utcnow(),
         "ver": 1},
        SECRET_KEY, algorithm=JWT_ALGORITHM
    )


def decode_token(tok: str) -> Optional[str]:
    try:
        return jwt.decode(tok, SECRET_KEY, algorithms=[JWT_ALGORITHM]).get("sub")
    except JWTError:
        return None
