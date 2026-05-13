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


# ── Rate limiting — Redis if available, in-memory fallback ────
import os as _os
_rate_store: dict = defaultdict(list)
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        redis_url = _os.environ.get("REDIS_URL", "")
        if redis_url:
            try:
                import redis
                _redis_client = redis.Redis.from_url(
                    redis_url, decode_responses=True, socket_timeout=1
                )
                _redis_client.ping()
                import logging; logging.getLogger(__name__).info(
                    "Rate limiting: Redis connected (%s)", redis_url[:30])
            except Exception as e:
                import logging; logging.getLogger(__name__).warning(
                    "Redis unavailable, using in-memory rate limiting: %s", e)
                _redis_client = False   # Mark as tried-and-failed
    return _redis_client if _redis_client else None


def check_rate_limit(ip: str, path: str) -> None:
    """Raise 429 if IP exceeded limit. Uses Redis if REDIS_URL set, else in-memory."""
    now = time.time()
    for prefix, (limit, window) in RATE_LIMITS.items():
        if path.startswith(prefix):
            key = f"rl:{ip}:{prefix}"
            redis = _get_redis()
            if redis:
                # Redis sliding window — works correctly across all workers
                try:
                    pipe = redis.pipeline()
                    pipe.zremrangebyscore(key, 0, now - window)
                    pipe.zcard(key)
                    pipe.zadd(key, {str(now): now})
                    pipe.expire(key, window)
                    _, count, *_ = pipe.execute()
                    if count >= limit:
                        raise HTTPException(
                            429, f"Rate limit: max {limit}/hour.")
                    return
                except HTTPException:
                    raise
                except Exception:
                    pass   # Fall through to in-memory on Redis error
            # In-memory fallback (per-worker, acceptable on single worker)
            _rate_store[key] = [t for t in _rate_store[key] if now - t < window]
            if len(_rate_store[key]) >= limit:
                raise HTTPException(429, f"Rate limit: max {limit}/hour.")
            _rate_store[key].append(now)
            break
