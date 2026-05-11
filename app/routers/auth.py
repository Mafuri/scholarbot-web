"""Auth router — /api/auth/*"""
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, User
from app.core.security import hash_password, verify_password, create_token
from app.dependencies import get_current_user, check_rate_limit
from app.config import COOKIE_NAME

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterReq(BaseModel):
    name: str
    email: str
    password: str
    degree_level: str = "Graduate"
    major: str = ""
    school: str = ""
    nationality: str = "Kenya"
    gpa: float = 0.0
    gpa_original: float = 0.0
    gpa_scale: float = 4.0
    financial_need: bool = False


class LoginReq(BaseModel):
    email: str
    password: str


def _set_auth_cookie(resp: JSONResponse, token: str) -> None:
    resp.set_cookie(
        key=COOKIE_NAME, value=token,
        httponly=True, secure=True, samesite="strict",
        max_age=604800, path="/api",
    )


@router.post("/register")
async def register(request: Request, req: RegisterReq,
                   db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    check_rate_limit(ip, "/api/auth/register")
    try:
        if db.query(User).filter(User.email == req.email).first():
            raise HTTPException(400, "Email already registered")

        # Normalise GPA
        from app.services.gpa import normalise_gpa
        gpa_info = normalise_gpa(
            req.gpa if req.gpa else req.gpa_original,
            scale=req.gpa_scale,
            country=req.nationality,
        )

        u = User(
            id=f"user_{uuid.uuid4().hex[:10]}",
            name=req.name, email=req.email,
            password_hash=hash_password(req.password),
            degree_level=req.degree_level,
            major=req.major, school=req.school,
            nationality=req.nationality,
            gpa=gpa_info["gpa_4"],
            gpa_original=req.gpa_original or req.gpa,
            gpa_scale=gpa_info["scale"],
            financial_need=req.financial_need,
            languages=["English"], skills=[],
            extracurriculars=[], demographic_tags=[],
            personal_statement="",
        )
        db.add(u); db.commit(); db.refresh(u)
        token = create_token(u.id)
        resp = JSONResponse({"token": token, "user": u.to_dict()})
        _set_auth_cookie(resp, token)
        return resp
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback; import logging
        logging.getLogger(__name__).error(traceback.format_exc())
        raise HTTPException(400, f"Registration error: {str(e)}")


@router.post("/login")
async def login(request: Request, req: LoginReq,
                db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    check_rate_limit(ip, "/api/auth/login")
    u = db.query(User).filter(User.email == req.email).first()
    if not u or not verify_password(req.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    token = create_token(u.id)
    resp = JSONResponse({"token": token, "user": u.to_dict()})
    _set_auth_cookie(resp, token)
    return resp


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return user.to_dict()


@router.post("/logout")
async def logout():
    resp = JSONResponse({"message": "Logged out"})
    resp.delete_cookie(key=COOKIE_NAME, path="/api")
    return resp
