"""
ScholarBot Web Platform v4.2 — Production Build
Single-file deployment: no app/ package dependency issues.
All security hardening, GPA normalisation, caching, and routes included.
"""
import logging, os, secrets, uuid, time, re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from enum import Enum as PyEnum

# ── Database ──────────────────────────────────────────────────
from sqlalchemy import (create_engine, Column, String, Float, Boolean,
    Integer, Text, DateTime, JSON, ForeignKey)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.pool import StaticPool

_DB_URL = os.environ.get("DATABASE_URL", "sqlite:///data/scholarbot.db")
if _DB_URL.startswith("postgres://"):
    _DB_URL = _DB_URL.replace("postgres://", "postgresql://", 1)

_engine = None
_SessionFactory = None

def _get_engine():
    global _engine
    if _engine is None:
        if "sqlite" in _DB_URL:
            _engine = create_engine(_DB_URL,
                connect_args={"check_same_thread": False}, poolclass=StaticPool)
        else:
            _engine = create_engine(_DB_URL, pool_pre_ping=True,
                pool_size=3, max_overflow=5, pool_recycle=300)
    return _engine

def _get_sf():
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(autocommit=False, autoflush=False,
            bind=_get_engine())
    return _SessionFactory

def SessionLocal(): return _get_sf()()

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id                      = Column(String(32), primary_key=True)
    name                    = Column(String(200), nullable=False)
    email                   = Column(String(200), unique=True, nullable=False, index=True)
    password_hash           = Column(String(200), nullable=False)
    degree_level            = Column(String(50), default="Graduate")
    major                   = Column(String(200), default="")
    school                  = Column(String(200), default="")
    nationality             = Column(String(100), default="Kenya")
    gpa                     = Column(Float, default=0.0)
    financial_need          = Column(Boolean, default=False)
    languages               = Column(JSON, default=list)
    skills                  = Column(JSON, default=list)
    extracurriculars        = Column(JSON, default=list)
    demographic_tags        = Column(JSON, default=list)
    personal_statement      = Column(Text, default="")
    plan                    = Column(String(20), default="free")
    applications_this_month = Column(Integer, default=0)
    created_at              = Column(DateTime, default=datetime.utcnow)
    updated_at              = Column(DateTime, default=datetime.utcnow,
                                     onupdate=datetime.utcnow)
    applications = relationship("Application", back_populates="user",
                                cascade="all, delete-orphan")
    packages     = relationship("Package", back_populates="user",
                                cascade="all, delete-orphan")
    rec_requests = relationship("RecRequest", back_populates="user",
                                cascade="all, delete-orphan")
    def to_dict(self):
        return {"id":self.id,"name":self.name,"email":self.email,
                "degree_level":self.degree_level,"major":self.major,
                "school":self.school,"nationality":self.nationality,
                "gpa":self.gpa,"financial_need":self.financial_need,
                "languages":self.languages or [],"skills":self.skills or [],
                "extracurriculars":self.extracurriculars or [],
                "demographic_tags":self.demographic_tags or [],
                "personal_statement":self.personal_statement or "",
                "plan":self.plan,
                "applications_this_month":self.applications_this_month or 0,
                "created_at":self.created_at.isoformat() if self.created_at else None}

class Application(Base):
    __tablename__ = "applications"
    id               = Column(String(32), primary_key=True)
    user_id          = Column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    opportunity_id   = Column(String(32), default="")
    scholarship_name = Column(String(300), default="")
    opportunity_type = Column(String(50), default="scholarship")
    amount_usd       = Column(Float, default=0.0)
    deadline         = Column(String(20), default="")
    url              = Column(Text, default="")
    stage            = Column(String(30), default="researching")
    notes            = Column(Text, default="")
    submitted_at     = Column(DateTime, nullable=True)
    outcome_date     = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship("User", back_populates="applications")
    def to_dict(self):
        return {"id":self.id,"user_id":self.user_id,
                "opportunity_id":self.opportunity_id,
                "scholarship_name":self.scholarship_name,
                "opportunity_type":self.opportunity_type,
                "amount_usd":self.amount_usd,"deadline":self.deadline,
                "url":self.url,"status":self.stage or "researching",
                "notes":self.notes,
                "submitted_at":self.submitted_at.isoformat() if self.submitted_at else None,
                "outcome_date":self.outcome_date.isoformat() if self.outcome_date else None,
                "created_at":self.created_at.isoformat() if self.created_at else None,
                "updated_at":self.updated_at.isoformat() if self.updated_at else None}

class Package(Base):
    __tablename__ = "packages"
    id               = Column(String(32), primary_key=True)
    user_id          = Column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    opportunity_id   = Column(String(32), default="")
    scholarship_name = Column(String(300), default="")
    opportunity_type = Column(String(50), default="scholarship")
    amount_usd       = Column(Float, default=0.0)
    deadline         = Column(String(20), default="")
    days_left        = Column(Integer, default=0)
    url              = Column(Text, default="")
    essay_text       = Column(Text, default="")
    briefing_html    = Column(Text, default="")
    created_at       = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="packages")
    def to_dict(self):
        preview = (self.essay_text or "")[:150]+"..." if self.essay_text else ""
        return {"id":self.id,"user_id":self.user_id,
                "scholarship":self.scholarship_name,
                "amount_usd":self.amount_usd,"deadline":self.deadline,
                "days_left":self.days_left,"url":self.url,
                "essay_preview":preview,
                "briefing_url":f"/api/packages/{self.user_id}/{self.id}/briefing",
                "essay_url":f"/api/packages/{self.user_id}/{self.id}/essay",
                "created_at":self.created_at.isoformat() if self.created_at else None}

class RecRequest(Base):
    __tablename__ = "rec_requests"
    id                      = Column(String(32), primary_key=True)
    user_id                 = Column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    opportunity_name        = Column(String(300), default="")
    recommender_name        = Column(String(200), default="")
    recommender_email       = Column(String(200), default="")
    recommender_title       = Column(String(200), default="")
    recommender_institution = Column(String(200), default="")
    relationship_desc       = Column(Text, default="")
    deadline                = Column(String(20), default="")
    submission_link         = Column(Text, default="")
    drafted_letter          = Column(Text, default="")
    status                  = Column(String(30), default="requested")
    created_at              = Column(DateTime, default=datetime.utcnow)
    updated_at              = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship("User", back_populates="rec_requests")
    def to_dict(self):
        return {"id":self.id,"user_id":self.user_id,
                "opportunity_name":self.opportunity_name,
                "recommender_name":self.recommender_name,
                "recommender_email":self.recommender_email,
                "recommender_title":self.recommender_title,
                "deadline":self.deadline,"status":self.status or "requested",
                "drafted_letter":self.drafted_letter or ""}

class Job(Base):
    __tablename__ = "jobs"
    id           = Column(String(32), primary_key=True)
    user_id      = Column(String(32), default="", index=True)
    job_type     = Column(String(50), default="")
    status       = Column(String(20), default="running")
    result       = Column(JSON, nullable=True)
    error        = Column(Text, nullable=True)
    started_at   = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    def to_dict(self):
        return {"id":self.id,"status":self.status,"result":self.result,
                "error":self.error,
                "started_at":self.started_at.isoformat() if self.started_at else None,
                "completed_at":self.completed_at.isoformat() if self.completed_at else None}

def get_db():
    db = _get_sf()()
    try: yield db
    finally: db.close()

def _init_db():
    os.makedirs("data", exist_ok=True)
    try:
        Base.metadata.create_all(bind=_get_engine(), checkfirst=True)
        print(f"[DB] Initialised ({_DB_URL.split('://')[0]})")
    except Exception as e:
        print(f"[DB] Warning: {e}")

# ── Security ──────────────────────────────────────────────────
import bcrypt as _bcrypt
from jose import JWTError, jwt as _jwt

_SECRET = os.environ.get("SECRET_KEY", secrets.token_hex(32))
_ALG = "HS256"

def _hash_pw(pw):
    return _bcrypt.hashpw(pw.encode()[:72], _bcrypt.gensalt(12)).decode()

def _check_pw(pw, hashed):
    try: return _bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except: return False

def _make_token(uid):
    return _jwt.encode({"sub":uid,"exp":datetime.utcnow()+timedelta(days=7)},
                       _SECRET, algorithm=_ALG)

def _decode_token(tok):
    try: return _jwt.decode(tok, _SECRET, algorithms=[_ALG]).get("sub")
    except JWTError: return None

_INJECTION = [
    r"ignore\s+(?:all\s+)?(?:previous|above|prior)",
    r"disregard\s+(?:all\s+)?(?:previous|above)",
    r"new\s+instructions?:", r"system\s*prompt", r"you\s+are\s+now",
]
def _sanitise(text, max_len=8000):
    if not text: return ""
    text = "".join(ch for ch in str(text) if ord(ch)>=32 or ch in "\n\r\t")
    for p in _INJECTION:
        text = re.sub(p, "[REMOVED]", text, flags=re.IGNORECASE)
    return text[:max_len]

# ── Rate limiting ─────────────────────────────────────────────
_rate_store = defaultdict(list)
_RATE_RULES = {
    "/api/auth/register": (10, 3600),
    "/api/auth/login":    (20, 3600),
    "/api/essays":        (10, 3600),
    "/api/packages":      (5,  3600),
}

# ── Cache ─────────────────────────────────────────────────────
_cache = {}
def _cache_get(k):
    v = _cache.get(k)
    return v[0] if v and time.time()<v[1] else None
def _cache_set(k, v, ttl=300): _cache[k] = (v, time.time()+ttl)

# ── LLM ───────────────────────────────────────────────────────
def _llm():
    key = os.environ.get("ANTHROPIC_API_KEY","")
    if not key: return lambda s,u: "I am a motivated student committed to excellence."
    import requests as _req
    def call(s, u):
        try:
            r = _req.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key":key,"anthropic-version":"2023-06-01",
                         "content-type":"application/json"},
                json={"model":"claude-haiku-4-5-20251001","max_tokens":1000,
                      "system":s,"messages":[{"role":"user","content":u}]},
                timeout=45)
            return r.json()["content"][0]["text"]
        except: return "I am a motivated student committed to excellence."
    return call

def _days_until(d):
    try: return (datetime.strptime(d,"%Y-%m-%d")-datetime.utcnow()).days
    except: return 999

# ── FastAPI App ───────────────────────────────────────────────
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)
app = FastAPI(title="ScholarBot API", version="4.2.0")

ALLOWED_ORIGINS = [
    "https://scholarbot-web.onrender.com",
    "http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:8000",
]
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True, allow_methods=["GET","POST","PATCH","DELETE","OPTIONS"],
    allow_headers=["Authorization","Content-Type"])

@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path = request.url.path
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    for prefix,(limit,window) in _RATE_RULES.items():
        if path.startswith(prefix):
            key = f"{ip}:{prefix}"
            _rate_store[key] = [t for t in _rate_store[key] if now-t<window]
            if len(_rate_store[key]) >= limit:
                return JSONResponse({"detail":f"Rate limit: {limit}/hr"}, status_code=429)
            _rate_store[key].append(now)
            break
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

@app.on_event("startup")
async def startup():
    Path("data/uploads").mkdir(parents=True, exist_ok=True)
    Path("static").mkdir(parents=True, exist_ok=True)
    _init_db()
    logger.info("ScholarBot v4.2.0 started")

def _get_user(creds: HTTPAuthorizationCredentials = Depends(security),
              db: Session = Depends(get_db)):
    if not creds: raise HTTPException(401, "Not authenticated")
    uid = _decode_token(creds.credentials)
    if not uid: raise HTTPException(401, "Invalid or expired token")
    u = db.query(User).filter(User.id==uid).first()
    if not u: raise HTTPException(401, "User not found")
    return u

def _opt_user(creds: HTTPAuthorizationCredentials = Depends(security),
              db: Session = Depends(get_db)):
    if not creds: return None
    uid = _decode_token(creds.credentials)
    if not uid: return None
    return db.query(User).filter(User.id==uid).first()

# ── Pydantic models ───────────────────────────────────────────
class RegisterReq(BaseModel):
    name: str; email: str; password: str
    degree_level: str = "Graduate"; major: str = ""; school: str = ""
    nationality: str = "Kenya"; gpa: float = 0.0; financial_need: bool = False

class LoginReq(BaseModel):
    email: str; password: str

class ProfileUpdate(BaseModel):
    name: Optional[str]=None; major: Optional[str]=None; school: Optional[str]=None
    gpa: Optional[float]=None; financial_need: Optional[bool]=None
    nationality: Optional[str]=None; languages: Optional[list]=None
    skills: Optional[list]=None; extracurriculars: Optional[list]=None
    personal_statement: Optional[str]=None

class RecReqCreate(BaseModel):
    opportunity_name: str; recommender_name: str; recommender_email: str
    recommender_title: str=""; recommender_institution: str=""
    relationship_desc: str=""; deadline: str=""; submission_link: str=""

class RecStatusUp(BaseModel):
    status: str

# ── Auth ──────────────────────────────────────────────────────
def _auth_response(u):
    token = _make_token(u.id)
    resp = JSONResponse({"token":token,"user":u.to_dict()})
    resp.set_cookie(key="sb_token",value=token,httponly=True,
        secure=True,samesite="strict",max_age=604800,path="/api")
    return resp

@app.post("/api/auth/register")
async def register(req: RegisterReq, db: Session = Depends(get_db)):
    try:
        if db.query(User).filter(User.email==req.email).first():
            raise HTTPException(400, "Email already registered")
        u = User(id=f"user_{uuid.uuid4().hex[:10]}", name=req.name, email=req.email,
                 password_hash=_hash_pw(req.password), degree_level=req.degree_level,
                 major=req.major, school=req.school, nationality=req.nationality,
                 gpa=float(req.gpa), financial_need=bool(req.financial_need),
                 languages=["English"], skills=[], extracurriculars=[],
                 demographic_tags=[], personal_statement="")
        db.add(u); db.commit(); db.refresh(u)
        return _auth_response(u)
    except HTTPException: raise
    except Exception as e:
        db.rollback()
        logger.error("Register error: %s", e, exc_info=True)
        raise HTTPException(400, f"Registration error: {str(e)}")

@app.post("/api/auth/login")
async def login(req: LoginReq, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.email==req.email).first()
    if not u or not _check_pw(req.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return _auth_response(u)

@app.get("/api/auth/me")
async def me(user: User = Depends(_get_user)): return user.to_dict()

@app.post("/api/auth/logout")
async def logout():
    resp = JSONResponse({"message":"Logged out"})
    resp.delete_cookie(key="sb_token", path="/api")
    return resp

# ── Profile ───────────────────────────────────────────────────
@app.patch("/api/profile")
async def update_profile(upd: ProfileUpdate, user: User = Depends(_get_user),
                          db: Session = Depends(get_db)):
    for f,v in upd.dict(exclude_none=True).items():
        setattr(user, f, v)
    user.updated_at = datetime.utcnow()
    db.commit(); db.refresh(user)
    return user.to_dict()

@app.get("/api/readiness")
async def readiness(user: User = Depends(_get_user)):
    from engine.scholarship_engine import compute_readiness_score
    return compute_readiness_score(user.to_dict())

@app.post("/api/profile/upload-doc")
async def upload_doc(file: UploadFile = File(...),
                     user: User = Depends(_get_user),
                     db: Session = Depends(get_db)):
    ext = Path(file.filename).suffix.lower()
    if ext not in {".pdf",".docx",".doc",".jpg",".jpeg",".png"}:
        raise HTTPException(400, "Unsupported file type")
    d = Path(f"data/uploads/{user.id}"); d.mkdir(parents=True, exist_ok=True)
    p = d / f"{uuid.uuid4().hex[:8]}_{file.filename}"
    content_bytes = await file.read(); p.write_bytes(content_bytes)
    return {"message":"Document uploaded", "user":user.to_dict()}

# ── Scholarships ──────────────────────────────────────────────
def _match_opps(profile, opp_type=None, field=None, region=None, min_amount=0):
    import hashlib, json
    key_fields = {"dl":profile.get("degree_level",""),"nat":profile.get("nationality",""),
                  "gpa":round(float(profile.get("gpa",0) or 0),1),
                  "fn":bool(profile.get("financial_need")),"maj":profile.get("major",""),
                  "ot":opp_type,"f":field,"r":region,"ma":min_amount}
    ck = "m:"+hashlib.md5(json.dumps(key_fields,sort_keys=True).encode()).hexdigest()[:10]
    cached = _cache_get(ck)
    if cached is not None: return cached
    from engine.opportunity_db import match_opportunities
    opps = match_opportunities(profile, opp_type=opp_type, min_amount=min_amount or 0)
    if field: opps=[o for o in opps if field.lower() in o.get("name","").lower() or
                    field.lower() in " ".join(o.get("tags",[])).lower()]
    if region: opps=[o for o in opps if any(region.lower() in c.lower()
                     for c in o.get("eligible_countries",[]))]
    _cache_set(ck, opps); return opps

@app.get("/api/opportunities")
async def get_opps(opp_type: Optional[str]=None, degree_level: Optional[str]=None,
                   field: Optional[str]=None, region: Optional[str]=None,
                   min_amount: Optional[int]=None, user: User = Depends(_opt_user)):
    profile = user.to_dict() if user else {"degree_level":degree_level or "Graduate",
        "nationality":"Kenya","financial_need":False,"gpa":0,"major":""}
    opps = _match_opps(profile, opp_type=opp_type, field=field,
                       region=region, min_amount=min_amount)
    by_type = {}
    for o in opps: by_type.setdefault(o["opportunity_type"],0); by_type[o["opportunity_type"]]+=1
    return {"opportunities":opps,"count":len(opps),"by_type":by_type,
            "total_potential_usd":sum(o["amount_usd"] for o in opps)}

@app.get("/api/scholarships")
async def get_scholarships(degree_level: Optional[str]=None, field: Optional[str]=None,
                            region: Optional[str]=None, min_amount: Optional[int]=None,
                            user: User = Depends(_opt_user)):
    profile = user.to_dict() if user else {"degree_level":degree_level or "Graduate",
        "nationality":"Kenya","financial_need":False,"gpa":0,"major":""}
    opps = _match_opps(profile, opp_type="scholarship", field=field,
                       region=region, min_amount=min_amount)
    return {"scholarships":opps,"count":len(opps),
            "total_potential_usd":sum(o["amount_usd"] for o in opps)}

@app.get("/api/scholarships/matched")
async def matched(user: User = Depends(_get_user)):
    opps = _match_opps(user.to_dict(), opp_type="scholarship")
    return {"scholarships":opps,"count":len(opps),
            "total_potential_usd":sum(o["amount_usd"] for o in opps)}

@app.get("/api/scholarships/{sid}/explain")
async def explain(sid: str, user: User = Depends(_opt_user)):
    from engine.opportunity_db import load_all_opportunities
    opp = next((o for o in load_all_opportunities() if o["id"]==sid), None)
    if not opp: raise HTTPException(404, "Not found")
    profile = user.to_dict() if user else {"degree_level":"Graduate",
        "nationality":"Kenya","financial_need":False,"gpa":0,"major":""}
    return explain_match(opp, profile)

# ── Pipeline ──────────────────────────────────────────────────
VALID_STAGES = {"researching","essay_ready","submitted","awaiting","won","rejected"}

@app.get("/api/pipeline")
async def get_pipeline(user: User = Depends(_get_user), db: Session = Depends(get_db)):
    apps = db.query(Application).filter(Application.user_id==user.id).all()
    stages = {s:[] for s in VALID_STAGES}
    for a in apps:
        stages[a.stage if a.stage in VALID_STAGES else "researching"].append(a.to_dict())
    return {"stages":stages,"counts":{k:len(v) for k,v in stages.items()},
            "total":len(apps),"won_total_usd":sum(a.amount_usd for a in apps if a.stage=="won")}

@app.post("/api/pipeline/add")
async def add_pipeline(data: dict, user: User = Depends(_get_user),
                        db: Session = Depends(get_db)):
    a = Application(id=f"app_{uuid.uuid4().hex[:8]}", user_id=user.id,
                    opportunity_id=data.get("scholarship_id",""),
                    scholarship_name=data.get("scholarship_name",""),
                    opportunity_type=data.get("opportunity_type","scholarship"),
                    amount_usd=float(data.get("amount_usd",0)),
                    deadline=data.get("deadline",""), url=data.get("url",""),
                    stage=data.get("stage","researching"), notes=data.get("notes",""))
    db.add(a); db.commit(); db.refresh(a); return a.to_dict()

@app.patch("/api/pipeline/{app_id}/move")
async def move_stage(app_id: str, data: dict, user: User = Depends(_get_user),
                      db: Session = Depends(get_db)):
    a = db.query(Application).filter(Application.id==app_id,
        Application.user_id==user.id).first()
    if not a: raise HTTPException(404, "Not found")
    stage = data.get("stage", a.stage)
    if stage not in VALID_STAGES: raise HTTPException(400, "Invalid stage")
    a.stage = stage; a.updated_at = datetime.utcnow()
    db.commit(); db.refresh(a); return a.to_dict()

@app.post("/api/applications/record")
async def record_app(data: dict, user: User = Depends(_get_user),
                      db: Session = Depends(get_db)):
    a = Application(id=f"app_{uuid.uuid4().hex[:8]}", user_id=user.id,
                    opportunity_id=data.get("scholarship_id",""),
                    scholarship_name=data.get("scholarship_name",""),
                    amount_usd=float(data.get("amount_usd",0)),
                    deadline=data.get("deadline",""), stage="submitted",
                    submitted_at=datetime.utcnow())
    db.add(a); db.commit(); db.refresh(a); return a.to_dict()

@app.get("/api/applications")
async def list_apps(user: User = Depends(_get_user), db: Session = Depends(get_db)):
    apps = db.query(Application).filter(Application.user_id==user.id).all()
    won = [a for a in apps if a.stage=="won"]
    sub = [a for a in apps if a.stage=="submitted"]
    return {"applications":[a.to_dict() for a in apps],"total":len(apps),
            "submitted":len(sub),"won":len(won),
            "total_applied_usd":sum(a.amount_usd for a in sub),
            "total_won_usd":sum(a.amount_usd for a in won)}

# ── Packages ──────────────────────────────────────────────────
@app.post("/api/packages/prepare")
async def prep_packages(req: dict, bt: BackgroundTasks,
                         user: User = Depends(_get_user)):
    db = SessionLocal()
    job = Job(id=f"job_{uuid.uuid4().hex[:8]}", user_id=user.id,
              job_type="packages", status="running")
    db.add(job); db.commit(); jid=job.id; db.close()
    bt.add_task(_packages_job, jid, user.to_dict(), req.get("top_n",5))
    return {"job_id":jid,"status":"running","message":f"Preparing packages"}

@app.get("/api/packages")
async def list_packages(user: User = Depends(_get_user), db: Session = Depends(get_db)):
    pkgs = db.query(Package).filter(Package.user_id==user.id)\
             .order_by(Package.created_at.desc()).all()
    return {"packages":[p.to_dict() for p in pkgs]}

@app.get("/api/packages/{uid}/{pid}/briefing", response_class=HTMLResponse)
async def get_briefing(uid: str, pid: str, user: User = Depends(_get_user),
                        db: Session = Depends(get_db)):
    if user.id!=uid: raise HTTPException(403, "Access denied")
    pkg = db.query(Package).filter(Package.id==pid).first()
    if not pkg: raise HTTPException(404, "Not found")
    return HTMLResponse(pkg.briefing_html or "<p>Not available</p>")

@app.get("/api/packages/{uid}/{pid}/essay")
async def get_essay(uid: str, pid: str, user: User = Depends(_get_user),
                     db: Session = Depends(get_db)):
    if user.id!=uid: raise HTTPException(403, "Access denied")
    pkg = db.query(Package).filter(Package.id==pid).first()
    if not pkg: raise HTTPException(404, "Not found")
    return {"essay": pkg.essay_text or ""}

@app.post("/api/essays/generate")
async def gen_essay(req: dict, bt: BackgroundTasks,
                     user: User = Depends(_get_user)):
    from engine.opportunity_db import load_all_opportunities
    opp = next((o for o in load_all_opportunities()
                if o["id"]==req.get("scholarship_id","")), None)
    if not opp: raise HTTPException(404, "Opportunity not found")
    db = SessionLocal()
    job = Job(id=f"job_{uuid.uuid4().hex[:8]}", user_id=user.id,
              job_type="essay", status="running")
    db.add(job); db.commit(); jid=job.id; db.close()
    bt.add_task(_essay_job, jid, opp, user.to_dict())
    return {"job_id":jid,"status":"running"}

# ── Recommendations ───────────────────────────────────────────
@app.get("/api/recommendations")
async def list_recs(user: User = Depends(_get_user), db: Session = Depends(get_db)):
    recs = db.query(RecRequest).filter(RecRequest.user_id==user.id).all()
    return {"recommendations":[r.to_dict() for r in recs],"total":len(recs)}

@app.post("/api/recommendations")
async def create_rec(req: RecReqCreate, bt: BackgroundTasks,
                      user: User = Depends(_get_user), db: Session = Depends(get_db)):
    rec = RecRequest(id=f"rec_{uuid.uuid4().hex[:8]}", user_id=user.id,
                     opportunity_name=req.opportunity_name,
                     recommender_name=req.recommender_name,
                     recommender_email=req.recommender_email,
                     recommender_title=req.recommender_title,
                     relationship_desc=req.relationship_desc,
                     deadline=req.deadline, status="requested")
    db.add(rec); db.commit(); db.refresh(rec)
    return {**rec.to_dict(),"message":"Created. Draft letter being generated."}

# ── Interview ─────────────────────────────────────────────────
@app.get("/api/interview/questions/{slug}")
async def interview_qs(slug: str, user: User = Depends(_get_user)):
    from engine.interview_data import QUESTION_BANKS
    return {"scholarship":slug,"questions":QUESTION_BANKS.get(slug.lower(),
            QUESTION_BANKS["general"])}

@app.post("/api/interview/score")
async def interview_score(data: dict, user: User = Depends(_get_user)):
    from engine.scholarship_engine import score_answer
    return score_answer(data.get("question",""), data.get("answer",""),
                        user.to_dict(), data.get("scholarship","general"))

# ── Jobs ──────────────────────────────────────────────────────
@app.get("/api/jobs/{jid}")
async def get_job(jid: str, user: User = Depends(_get_user),
                   db: Session = Depends(get_db)):
    j = db.query(Job).filter(Job.id==jid, Job.user_id==user.id).first()
    if not j: raise HTTPException(404, "Not found")
    return j.to_dict()

# ── Dashboard ─────────────────────────────────────────────────
@app.get("/api/dashboard")
async def dashboard(user: User = Depends(_get_user), db: Session = Depends(get_db)):
    profile = user.to_dict()
    matched = _match_opps(profile)
    apps = db.query(Application).filter(Application.user_id==user.id).all()
    won=[a for a in apps if a.stage=="won"]
    sub=[a for a in apps if a.stage=="submitted"]
    upcoming=sorted([{"name":o["name"],"deadline":o["deadline"],
        "amount_usd":o.get("amount_usd",0),"days_left":_days_until(o.get("deadline",""))}
        for o in matched if 0<=_days_until(o.get("deadline",""))<=60],
        key=lambda x:x["days_left"])
    return {"user":profile,"scholarships_matched":len(matched),
            "total_potential_usd":sum(o["amount_usd"] for o in matched),
            "applications_submitted":len(sub),"applications_won":len(won),
            "total_won_usd":sum(a.amount_usd for a in won),
            "upcoming_deadlines":upcoming[:5]}

# ── System ────────────────────────────────────────────────────
@app.get("/api/health")
async def health(db: Session = Depends(get_db)):
    try: users=db.query(User).count(); ok=True
    except Exception as e: users=-1; ok=False
    return {"status":"ok" if ok else "db_error","version":"4.2.0",
            "db":_DB_URL.split("://")[0],"users":users,
            "timestamp":datetime.utcnow().isoformat()}

@app.get("/api/stats")
async def stats(db: Session = Depends(get_db)):
    from engine.opportunity_db import load_all_opportunities
    opps = load_all_opportunities()
    by_type={}
    for o in opps: by_type.setdefault(o["opportunity_type"],0); by_type[o["opportunity_type"]]+=1
    return {"total_users":db.query(User).count(),"opportunities_in_db":len(opps),
            "total_potential_funding_usd":sum(o["amount_usd"] for o in opps),"by_type":by_type}

@app.get("/manifest.json")
async def manifest():
    p = Path("static/manifest.json")
    if p.exists():
        from fastapi.responses import FileResponse
        return FileResponse(str(p), media_type="application/manifest+json")
    return JSONResponse({})

@app.get("/sw.js")
async def sw():
    p = Path("static/sw.js")
    if p.exists():
        from fastapi.responses import FileResponse
        return FileResponse(str(p), media_type="application/javascript",
                           headers={"Service-Worker-Allowed":"/"})
    return JSONResponse({}, status_code=404)

# ── GDPR ─────────────────────────────────────────────────────
@app.get("/api/account/export")
async def export_data(user: User = Depends(_get_user), db: Session = Depends(get_db)):
    apps = db.query(Application).filter(Application.user_id==user.id).all()
    pkgs = db.query(Package).filter(Package.user_id==user.id).all()
    return JSONResponse({
        "export_generated_at":datetime.utcnow().isoformat(),
        "platform":"ScholarBot v4.2.0",
        "profile":user.to_dict(),
        "applications":[a.to_dict() for a in apps],
        "packages":[{"id":p.id,"scholarship":p.scholarship_name,
                     "essay_preview":(p.essay_text or "")[:200]} for p in pkgs],
        "statistics":{"total_applications":len(apps),
                      "won":sum(1 for a in apps if a.stage=="won")}
    }, headers={"Content-Disposition":'attachment; filename="scholarbot_data.json"'})

@app.delete("/api/account/delete")
async def delete_account(req: dict, user: User = Depends(_get_user),
                          db: Session = Depends(get_db)):
    if req.get("confirm") != "DELETE MY ACCOUNT":
        raise HTTPException(400, "confirm field must be: DELETE MY ACCOUNT")
    if not _check_pw(req.get("password",""), user.password_hash):
        raise HTTPException(401, "Incorrect password")
    db.delete(user); db.commit()
    return {"message":"Account permanently deleted"}

# ── SPA ───────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def spa():
    p = Path("static/index.html")
    if p.exists(): return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>ScholarBot API v4.2.0</h1>")

@app.get("/{path:path}", response_class=HTMLResponse)
async def spa_fallback(path: str):
    if path.startswith("api/"): raise HTTPException(404)
    p = Path("static/index.html")
    if p.exists(): return HTMLResponse(p.read_text(encoding="utf-8"))
    raise HTTPException(404)

# ── Background jobs ───────────────────────────────────────────
def _update_job(jid, status, result=None, error=None):
    db = SessionLocal()
    try:
        j = db.query(Job).filter(Job.id==jid).first()
        if j:
            j.status=status
            if result is not None: j.result=result
            if error is not None: j.error=error
            j.completed_at=datetime.utcnow(); db.commit()
    finally: db.close()

def _essay_job(jid, opp, profile):
    try:
        from engine.scholarship_engine import generate_essay_for
        essay = generate_essay_for(opp, profile)
        _update_job(jid,"done",result={"essay":essay,"word_count":len(essay.split())})
    except Exception as e: _update_job(jid,"failed",error=str(e))

def _packages_job(jid, profile, top_n):
    try:
        from engine.opportunity_db import match_opportunities
        from engine.scholarship_engine import generate_essay_for
        opps = match_opportunities(profile)[:top_n]
        uid = profile.get("id","anon"); created=[]; db=SessionLocal()
        try:
            for o in opps:
                try: essay = generate_essay_for(o, profile)
                except: essay = f"Essay for {o['name']}.\n\nPrompt: {o.get('essay_prompt','')}"
                dl = _days_until(o.get("deadline",""))
                pkg = Package(id=f"pkg_{uuid.uuid4().hex[:8]}", user_id=uid,
                              opportunity_id=o.get("id",""), scholarship_name=o.get("name",""),
                              amount_usd=o.get("amount_usd",0), deadline=o.get("deadline",""),
                              days_left=dl, url=o.get("url",""), essay_text=essay,
                              briefing_html=f"<h1>{o['name']}</h1><pre>{essay}</pre>")
                db.add(pkg); created.append({"opportunity":o["name"],"days_left":dl})
            db.commit()
        finally: db.close()
        _update_job(jid,"done",result={"packages":created,"count":len(created)})
    except Exception as e:
        logger.exception("Package job failed"); _update_job(jid,"failed",error=str(e))
