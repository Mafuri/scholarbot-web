"""
ScholarBot — FastAPI dependencies.
DB session, auth, rate limiting injected per-request.
"""
import time
from collections import defaultdict
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db, User
from app.core.security import decode_token
from app.config import RATE_LIMITS

security = HTTPBearer(auto_error=False)

# ── Auth dependencies ─────────────────────────────────────────
def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if not creds:
        raise HTTPException(401, "Not authenticated")
    uid = decode_token(creds.credentials)
    if not uid:
        raise HTTPException(401, "Invalid or expired token")
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(401, "User not found")
    return user


def optional_user(
    creds: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User | None:
    if not creds:
        return None
    uid = decode_token(creds.credentials)
    if not uid:
        return None
    return db.query(User).filter(User.id == uid).first()


# ── Rate limiting (middleware-compatible store) ────────────────
_rate_store: dict = defaultdict(list)


def check_rate_limit(ip: str, path: str) -> None:
    """Raise 429 if IP has exceeded the limit for this path prefix."""
    now = time.time()
    for prefix, (limit, window) in RATE_LIMITS.items():
        if path.startswith(prefix):
            key = f"{ip}:{prefix}"
            _rate_store[key] = [
                t for t in _rate_store[key] if now - t < window
            ]
            if len(_rate_store[key]) >= limit:
                raise HTTPException(
                    429,
                    f"Rate limit exceeded. Max {limit} requests per hour."
                )
            _rate_store[key].append(now)
            break
