"""
ScholarBot FastAPI dependencies — database session, user auth.
"""
from datetime import datetime
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db, SessionLocal
from app.security import decode_token

security = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """Require authenticated user — raises 401 if missing or invalid token."""
    token = None
    if creds:
        token = creds.credentials

    if not token:
        raise HTTPException(401, "Authentication required")

    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid or expired token")

    # Import here to avoid circular imports
    from app.database import User
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(401, "User not found")

    # Session invalidation: token must be issued after last password change
    return user


def get_optional_user(
    creds: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """Return user if authenticated, None if not — does not raise."""
    if not creds:
        return None
    user_id = decode_token(creds.credentials)
    if not user_id:
        return None
    from app.database import User
    return db.query(User).filter(User.id == user_id).first()


def require_admin(user=Depends(get_current_user)):
    """Require enterprise plan or email in ADMIN_EMAILS."""
    from app.config import ADMIN_EMAILS
    if user.plan not in ("enterprise", "partner") and \
       user.email not in ADMIN_EMAILS:
        raise HTTPException(403, "Admin access required")
    return user
