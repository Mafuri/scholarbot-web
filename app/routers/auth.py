"""Auth router — /api/auth/*
Includes: register, login, logout, me, forgot-password, reset-password, verify-email
"""
import uuid
import hashlib
import secrets
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import (get_db, User, PasswordResetToken,
                           EmailVerification, PledgeLog)
from app.core.security import hash_password, verify_password, create_token
from app.dependencies import get_current_user, check_rate_limit
from app.config import COOKIE_NAME
from app.services.email import (send_password_reset_email,
                                 send_verification_email, email_configured)

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

PLEDGE_TEXT = (
    "I will read and personalise every AI-generated essay before submitting. "
    "I will ensure all facts accurately reflect my own experience. "
    "I take full personal responsibility for all application content."
)
PLEDGE_HASH = hashlib.sha256(PLEDGE_TEXT.encode()).hexdigest()


class RegisterReq(BaseModel):
    name: str
    email: str
    password: str
    degree_level: str = "Graduate"
    major: str = ""
    school: str = ""
    nationality: str = "Kenya"
    gpa: float = 0.0
    financial_need: bool = False


class LoginReq(BaseModel):
    email: str
    password: str


class ForgotPasswordReq(BaseModel):
    email: str


class ResetPasswordReq(BaseModel):
    token: str
    new_password: str


def _set_cookie(resp: JSONResponse, token: str) -> None:
    resp.set_cookie(key=COOKIE_NAME, value=token, httponly=True,
                    secure=True, samesite="strict",
                    max_age=604800, path="/api")


@router.post("/register")
async def register(request: Request, req: RegisterReq,
                   bt: BackgroundTasks,
                   db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    check_rate_limit(ip, "/api/auth/register")
    try:
        if db.query(User).filter(User.email == req.email).first():
            raise HTTPException(400, "Email already registered")

        from app.services.gpa import normalise_gpa
        gpa_info = normalise_gpa(req.gpa or 0, country=req.nationality)

        u = User(
            id=f"user_{uuid.uuid4().hex[:10]}",
            name=req.name, email=req.email.lower().strip(),
            password_hash=hash_password(req.password),
            degree_level=req.degree_level,
            major=req.major, school=req.school,
            nationality=req.nationality,
            gpa=gpa_info["gpa_4"],
            financial_need=bool(req.financial_need),
            email_verified=not email_configured(),  # auto-verify if no email service
            languages=["English"], skills=[],
            extracurriculars=[], demographic_tags=[],
            personal_statement="",
        )
        db.add(u); db.commit(); db.refresh(u)

        # Send verification email if SendGrid configured
        if email_configured():
            raw = secrets.token_urlsafe(32)
            ev = EmailVerification(
                id=f"ev_{uuid.uuid4().hex[:8]}",
                user_id=u.id,
                token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            db.add(ev); db.commit()
            bt.add_task(send_verification_email, u.email, u.name, raw)

        token = create_token(u.id)
        resp = JSONResponse({"token": token, "user": u.to_dict()})
        _set_cookie(resp, token)
        return resp
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Register error: %s", e, exc_info=True)
        raise HTTPException(400, f"Registration error: {str(e)}")


@router.post("/login")
async def login(request: Request, req: LoginReq,
                db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    check_rate_limit(ip, "/api/auth/login")
    u = db.query(User).filter(User.email == req.email.lower().strip()).first()
    if not u or not verify_password(req.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    token = create_token(u.id)
    resp = JSONResponse({"token": token, "user": u.to_dict()})
    _set_cookie(resp, token)
    return resp


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return user.to_dict()


@router.post("/logout")
async def logout():
    resp = JSONResponse({"message": "Logged out"})
    resp.delete_cookie(key=COOKIE_NAME, path="/api")
    return resp


# ── Blocker 1: Password reset ─────────────────────────────────
@router.post("/forgot-password")
async def forgot_password(
    request: Request,
    req: ForgotPasswordReq,
    bt: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Always returns generic message — prevents email enumeration attacks."""
    ip = request.client.host if request.client else "unknown"
    check_rate_limit(ip, "/api/auth/register")  # reuse register limit

    u = db.query(User).filter(User.email == req.email.lower().strip()).first()
    if u:
        raw = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        rt = PasswordResetToken(
            id=f"prt_{uuid.uuid4().hex[:8]}",
            user_id=u.id,
            token_hash=token_hash,
            expires_at=datetime.utcnow() + timedelta(hours=24),
            used=False,
        )
        db.add(rt); db.commit()
        if email_configured():
            bt.add_task(send_password_reset_email, u.email, u.name, raw)
        else:
            logger.info("PASSWORD RESET TOKEN (no email service): %s", raw)

    return {"message": "If an account exists with this email, "
                       "you will receive a reset link within 5 minutes."}


@router.post("/reset-password")
async def reset_password(req: ResetPasswordReq, db: Session = Depends(get_db)):
    if len(req.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    token_hash = hashlib.sha256(req.token.encode()).hexdigest()
    rt = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used == False,
        PasswordResetToken.expires_at > datetime.utcnow(),
    ).first()

    if not rt:
        raise HTTPException(400, "Invalid or expired reset link. Please request a new one.")

    u = db.query(User).filter(User.id == rt.user_id).first()
    if not u:
        raise HTTPException(400, "Account not found")

    u.password_hash = hash_password(req.new_password)
    rt.used = True
    db.commit()
    return {"message": "Password updated. Please log in with your new password."}


@router.get("/validate-reset-token")
async def validate_reset_token(token: str, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    rt = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used == False,
        PasswordResetToken.expires_at > datetime.utcnow(),
    ).first()
    if not rt:
        raise HTTPException(400, "Invalid or expired token")
    u = db.query(User).filter(User.id == rt.user_id).first()
    return {"valid": True, "email": u.email if u else ""}


# ── Blocker 3: Email verification ────────────────────────────
@router.get("/verify-email")
async def verify_email(token: str, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    ev = db.query(EmailVerification).filter(
        EmailVerification.token_hash == token_hash,
        EmailVerification.verified == False,
        EmailVerification.expires_at > datetime.utcnow(),
    ).first()
    if not ev:
        raise HTTPException(400, "Invalid or expired verification link")
    u = db.query(User).filter(User.id == ev.user_id).first()
    if u:
        u.email_verified = True
    ev.verified = True
    db.commit()
    return {"message": "Email verified. You can now log in."}
