"""
ScholarBot Web Platform v4 — Single File Edition
All database models inlined to eliminate import issues.
"""
from __future__ import annotations
import logging, os, secrets, uuid, traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from enum import Enum as PyEnum

from sqlalchemy import (create_engine, Column, String, Float, Boolean,
    Integer, Text, DateTime, JSON, ForeignKey)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///data/scholarbot.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
if "sqlite" in DATABASE_URL:
    engine = create_engine(DATABASE_URL,
        connect_args={"check_same_thread": False}, poolclass=StaticPool)
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
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

    def to_dict(self, include_password=False):
        d = {"id":self.id,"name":self.name,"email":self.email,
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
        if include_password:
            d["password_hash"] = self.password_hash
        return d

class Application(Base):
    __tablename__ = "applications"
    id               = Column(String(32), primary_key=True)
    user_id          = Column(String(32), ForeignKey("users.id"),
                              nullable=False, index=True)
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
    updated_at       = Column(DateTime, default=datetime.utcnow,
                              onupdate=datetime.utcnow)
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
    user_id          = Column(String(32), ForeignKey("users.id"),
                              nullable=False, index=True)
    opportunity_id   = Column(String(32), default="")
    scholarship_name = Column(String(300), default="")
    opportunity_type = Column(String(50), default="scholarship")
    amount_usd       = Column(Float, default=0.0)
    deadline         = Column(String(20), default="")
    days_left        = Column(Integer, default=0)
    url              = Column(Text, default="")
    essay_text       = Column(Text, default="")
    cover_letter     = Column(Text, default="")
    briefing_html    = Column(Text, default="")
    fields_json      = Column(JSON, default=dict)
    created_at       = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="packages")

    def to_dict(self):
        preview = (self.essay_text or "")[:150]+"..." if self.essay_text else ""
        return {"id":self.id,"user_id":self.user_id,
                "opportunity_id":self.opportunity_id,
                "scholarship":self.scholarship_name,
                "amount_usd":self.amount_usd,"deadline":self.deadline,
                "days_left":self.days_left,"url":self.url,
                "essay_preview":preview,
                "briefing_url":"/api/packages/"+self.user_id+"/"+self.id+"/briefing",
                "essay_url":"/api/packages/"+self.user_id+"/"+self.id+"/essay",
                "created_at":self.created_at.isoformat() if self.created_at else None}

class RecRequest(Base):
    __tablename__ = "rec_requests"
    id                      = Column(String(32), primary_key=True)
    user_id                 = Column(String(32), ForeignKey("users.id"),
                                    nullable=False, index=True)
    opportunity_name        = Column(String(300), default="")
    recommender_name        = Column(String(200), default="")
    recommender_email       = Column(String(200), default="")
    recommender_title       = Column(String(200), default="")
    recommender_institution = Column(String(200), default="")
    relationship_desc       = Column(Text, default="")
    deadline                = Column(String(20), default="")
    submission_link         = Column(Text, default="")
    drafted_letter          = Column(Text, default="")
    briefing_text           = Column(Text, default="")
    status                  = Column(String(30), default="requested")
    requested_at            = Column(DateTime, default=datetime.utcnow)
    reminded_at             = Column(DateTime, nullable=True)
    received_at             = Column(DateTime, nullable=True)
    created_at              = Column(DateTime, default=datetime.utcnow)
    updated_at              = Column(DateTime, default=datetime.utcnow,
                                     onupdate=datetime.utcnow)
    user = relationship("User", back_populates="rec_requests")

    def to_dict(self):
        return {"id":self.id,"user_id":self.user_id,
                "opportunity_name":self.opportunity_name,
                "recommender_name":self.recommender_name,
                "recommender_email":self.recommender_email,
                "recommender_title":self.recommender_title,
                "recommender_institution":self.recommender_institution,
                "relationship_desc":self.relationship_desc,
                "deadline":self.deadline,
                "submission_link":self.submission_link,
                "drafted_letter":self.drafted_letter or "",
                "briefing_text":self.briefing_text or "",
                "status":self.status or "requested",
                "requested_at":self.requested_at.isoformat() if self.requested_at else None,
                "reminded_at":self.reminded_at.isoformat() if self.reminded_at else None,
                "received_at":self.received_at.isoformat() if self.received_at else None}

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
    db = SessionLocal()
    try: yield db
    finally: db.close()

def init_db():
    os.makedirs("data", exist_ok=True)
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
        print("[DB] Initialised ("+DATABASE_URL.split("://")[0]+")")
    except Exception as e:
        print("[DB] Warning during init: "+str(e))
        for table in Base.metadata.sorted_tables:
            try: table.create(engine, checkfirst=True)
            except Exception as te: print("[DB] "+table.name+": "+str(te))

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from passlib.context import CryptContext

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger(__name__)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_JWT_SECRET = os.environ.get("SECRET_KEY", secrets.token_hex(32))
_JWT_ALG = "HS256"
_JWT_DAYS = 7
security = HTTPBearer(auto_error=False)

app = FastAPI(title="ScholarBot API", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
async def startup():
    Path("data/uploads").mkdir(parents=True, exist_ok=True)
    Path("data/packages").mkdir(parents=True, exist_ok=True)
    Path("static").mkdir(parents=True, exist_ok=True)
    init_db()
    logger.info("ScholarBot v4 started")

def _hash_pw(pw):
    # bcrypt hard limit is 72 bytes - encode then truncate
    pw_bytes = pw.encode('utf-8')[:72]
    pw_truncated = pw_bytes.decode('utf-8', errors='ignore')
    return _pwd.hash(pw_truncated)

def _check_pw(pw, hashed):
    if ":" in hashed and len(hashed.split(":")[0]) == 32:
        import hashlib
        try:
            salt, h = hashed.split(":", 1)
            return hashlib.sha256((salt+pw).encode()).hexdigest() == h
        except: return False
    try:
        pw_bytes = pw.encode('utf-8')[:72]
        pw_truncated = pw_bytes.decode('utf-8', errors='ignore')
        return _pwd.verify(pw_truncated, hashed)
    except: return False

def _make_token(uid):
    exp = datetime.utcnow() + timedelta(days=_JWT_DAYS)
    return jwt.encode({"sub": uid, "exp": exp}, _JWT_SECRET, algorithm=_JWT_ALG)

def _decode_jwt(token):
    try: return jwt.decode(token, _JWT_SECRET,
                           algorithms=[_JWT_ALG]).get("sub")
    except JWTError: return None

def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)):
    if not creds: raise HTTPException(401, "Not authenticated")
    uid = _decode_jwt(creds.credentials)
    if not uid: raise HTTPException(401, "Invalid or expired token")
    user = db.query(User).filter(User.id == uid).first()
    if not user: raise HTTPException(401, "User not found")
    return user

def optional_user(
    creds: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)):
    if not creds: return None
    uid = _decode_jwt(creds.credentials)
    if not uid: return None
    return db.query(User).filter(User.id == uid).first()

def _get_llm():
    import requests as req
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        def claude(s, u):
            try:
                r = req.post("https://api.anthropic.com/v1/messages",
                    headers={"x-api-key":key,
                             "anthropic-version":"2023-06-01",
                             "content-type":"application/json"},
                    json={"model":"claude-haiku-4-5-20251001",
                          "max_tokens":1000,"system":s,
                          "messages":[{"role":"user","content":u}]},
                    timeout=30)
                return r.json()["content"][0]["text"]
            except: return "I am a motivated student committed to excellence."
        return claude
    return lambda s, u: "I am a motivated student committed to excellence."

def _days_until(d):
    try: return (datetime.strptime(d,"%Y-%m-%d")-datetime.utcnow()).days
    except: return 999

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

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    major: Optional[str] = None
    school: Optional[str] = None
    gpa: Optional[float] = None
    financial_need: Optional[bool] = None
    nationality: Optional[str] = None
    languages: Optional[list] = None
    skills: Optional[list] = None
    extracurriculars: Optional[list] = None
    personal_statement: Optional[str] = None
    demographic_tags: Optional[list] = None

class RecReqCreate(BaseModel):
    opportunity_name: str
    recommender_name: str
    recommender_email: str
    recommender_title: str = ""
    recommender_institution: str = ""
    relationship_desc: str = ""
    deadline: str = ""
    submission_link: str = ""

class RecStatusUp(BaseModel):
    status: str

@app.post("/api/auth/register")
async def register(req: RegisterReq, db: Session = Depends(get_db)):
    try:
        existing = db.query(User).filter(User.email == req.email).first()
        if existing:
            raise HTTPException(400, "Email already registered")
        uid = "user_" + uuid.uuid4().hex[:10]
        u = User(
            id=uid,
            name=req.name,
            email=req.email,
            password_hash=_hash_pw(req.password),
            degree_level=req.degree_level,
            major=req.major,
            school=req.school,
            nationality=req.nationality,
            gpa=float(req.gpa),
            financial_need=bool(req.financial_need),
            languages=["English"],
            skills=[],
            extracurriculars=[],
            demographic_tags=[],
            personal_statement=""
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        token = _make_token(u.id)
        return {"token": token, "user": u.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        err_detail = traceback.format_exc()
        logger.error("REGISTER ERROR:\n%s", err_detail)
        raise HTTPException(400, "Registration error: " + str(e))

@app.post("/api/auth/login")
async def login(req: LoginReq, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.email == req.email).first()
    if not u or not _check_pw(req.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return {"token": _make_token(u.id), "user": u.to_dict()}

@app.get("/api/auth/me")
async def me(user: User = Depends(get_current_user)):
    return user.to_dict()

@app.patch("/api/profile")
async def update_profile(upd: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    for f, v in upd.dict(exclude_none=True).items():
        setattr(user, f, v)
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user.to_dict()

@app.post("/api/profile/upload-doc")
async def upload_doc(file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    ext = Path(file.filename).suffix.lower()
    if ext not in {".pdf",".docx",".doc",".jpg",".jpeg",".png"}:
        raise HTTPException(400, "Unsupported file type: "+ext)
    d = Path("data/uploads/"+user.id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / (uuid.uuid4().hex[:8]+"_"+file.filename)
    p.write_bytes(await file.read())
    return {"message": "Document uploaded"}

@app.get("/api/readiness")
async def readiness(user: User = Depends(get_current_user)):
    from engine.scholarship_engine import compute_readiness_score
    return compute_readiness_score(user.to_dict())

@app.get("/api/opportunities")
async def get_opps(opp_type: Optional[str]=None,
    degree_level: Optional[str]=None,
    field: Optional[str]=None,
    region: Optional[str]=None,
    min_amount: Optional[int]=None,
    user: User = Depends(optional_user)):
    from engine.opportunity_db import match_opportunities
    profile = user.to_dict() if user else {
        "degree_level": degree_level or "Graduate",
        "nationality":"Kenya","financial_need":False,"gpa":0,"major":""}
    opps = match_opportunities(profile, opp_type=opp_type,
                               min_amount=min_amount or 0)
    if field:
        opps = [o for o in opps if
            field.lower() in " ".join(o.get("tags",[])).lower() or
            field.lower() in o.get("name","").lower()]
    if region:
        opps = [o for o in opps if
            any(region.lower() in c.lower()
                for c in o.get("eligible_countries",[]))]
    by_type = {}
    for o in opps:
        by_type.setdefault(o["opportunity_type"],0)
        by_type[o["opportunity_type"]] += 1
    return {"opportunities":opps,"count":len(opps),"by_type":by_type,
            "total_potential_usd":sum(o["amount_usd"] for o in opps)}

@app.get("/api/scholarships")
async def get_scholarships(degree_level: Optional[str]=None,
    field: Optional[str]=None,
    region: Optional[str]=None,
    min_amount: Optional[int]=None,
    user: User = Depends(optional_user)):
    from engine.opportunity_db import match_opportunities
    profile = user.to_dict() if user else {
        "degree_level": degree_level or "Graduate",
        "nationality":"Kenya","financial_need":False,"gpa":0,"major":""}
    opps = match_opportunities(profile, opp_type="scholarship",
                               min_amount=min_amount or 0)
    if field:
        opps = [o for o in opps if
            field.lower() in o.get("name","").lower() or
            field.lower() in " ".join(o.get("tags",[])).lower()]
    if region:
        opps = [o for o in opps if
            any(region.lower() in c.lower()
                for c in o.get("eligible_countries",[]))]
    return {"scholarships":opps,"count":len(opps),
            "total_potential_usd":sum(o["amount_usd"] for o in opps)}

@app.get("/api/scholarships/matched")
async def matched_scholarships(user: User = Depends(get_current_user)):
    from engine.opportunity_db import match_opportunities
    opps = match_opportunities(user.to_dict(), opp_type="scholarship")
    return {"scholarships":opps,"count":len(opps),
            "total_potential_usd":sum(o["amount_usd"] for o in opps)}

@app.post("/api/essays/generate")
async def gen_essay(req: dict, bt: BackgroundTasks,
    user: User = Depends(get_current_user)):
    from engine.opportunity_db import load_all_opportunities
    opp = next((o for o in load_all_opportunities()
                if o["id"]==req.get("scholarship_id","")), None)
    if not opp: raise HTTPException(404, "Opportunity not found")
    db = SessionLocal()
    job = Job(id="job_"+uuid.uuid4().hex[:8], user_id=user.id,
              job_type="essay", status="running")
    db.add(job); db.commit(); jid = job.id; db.close()
    bt.add_task(_essay_job, jid, opp, user.to_dict(),
                req.get("tone","personal-narrative"),
                req.get("max_words",400))
    return {"job_id":jid,"status":"running",
            "message":"Essay generation started"}

@app.post("/api/packages/prepare")
async def prep_packages(req: dict, bt: BackgroundTasks,
    user: User = Depends(get_current_user)):
    db = SessionLocal()
    job = Job(id="job_"+uuid.uuid4().hex[:8], user_id=user.id,
              job_type="packages", status="running")
    db.add(job); db.commit(); jid = job.id; db.close()
    top_n = req.get("top_n", 5)
    bt.add_task(_packages_job, jid, user.to_dict(),
                top_n, req.get("opportunity_ids"))
    return {"job_id":jid,"status":"running",
            "message":"Preparing top "+str(top_n)+" packages"}

@app.get("/api/packages")
async def list_pkgs(user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    pkgs = db.query(Package).filter(
        Package.user_id==user.id
    ).order_by(Package.created_at.desc()).all()
    return {"packages":[p.to_dict() for p in pkgs]}

@app.get("/api/packages/{uid}/{pid}/briefing",
    response_class=HTMLResponse)
async def get_briefing(uid: str, pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    if user.id != uid: raise HTTPException(403, "Access denied")
    pkg = db.query(Package).filter(Package.id==pid).first()
    if not pkg: raise HTTPException(404, "Not found")
    return HTMLResponse(pkg.briefing_html or "<p>Not available</p>")

@app.get("/api/packages/{uid}/{pid}/essay")
async def get_pkg_essay(uid: str, pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    if user.id != uid: raise HTTPException(403, "Access denied")
    pkg = db.query(Package).filter(Package.id==pid).first()
    if not pkg: raise HTTPException(404, "Not found")
    return {"essay": pkg.essay_text or ""}

@app.get("/api/pipeline")
async def get_pipeline(user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    apps = db.query(Application).filter(
        Application.user_id==user.id).all()
    stages = {"researching":[],"essay_ready":[],"submitted":[],
              "awaiting":[],"won":[],"rejected":[]}
    for a in apps:
        s = a.stage if a.stage in stages else "researching"
        stages[s].append(a.to_dict())
    won_total = sum(a.amount_usd for a in apps if a.stage=="won")
    return {"stages":stages,
            "counts":{k:len(v) for k,v in stages.items()},
            "total":len(apps),"won_total_usd":won_total}

@app.patch("/api/pipeline/{app_id}/move")
async def move_stage(app_id: str, data: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    a = db.query(Application).filter(
        Application.id==app_id,
        Application.user_id==user.id).first()
    if not a: raise HTTPException(404, "Not found")
    a.stage = data.get("stage", a.stage)
    a.updated_at = datetime.utcnow()
    db.commit(); db.refresh(a)
    return a.to_dict()

@app.post("/api/pipeline/add")
async def add_pipeline(data: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    a = Application(
        id="app_"+uuid.uuid4().hex[:8],
        user_id=user.id,
        opportunity_id=data.get("scholarship_id",""),
        scholarship_name=data.get("scholarship_name",""),
        opportunity_type=data.get("opportunity_type","scholarship"),
        amount_usd=float(data.get("amount_usd",0)),
        deadline=data.get("deadline",""),
        url=data.get("url",""),
        stage=data.get("stage","researching"),
        notes=data.get("notes",""))
    db.add(a); db.commit(); db.refresh(a)
    return a.to_dict()

@app.get("/api/applications")
async def list_apps(user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    apps = db.query(Application).filter(
        Application.user_id==user.id).all()
    won = [a for a in apps if a.stage=="won"]
    submitted = [a for a in apps if a.stage=="submitted"]
    return {"applications":[a.to_dict() for a in apps],
            "total":len(apps),"submitted":len(submitted),"won":len(won),
            "total_applied_usd":sum(a.amount_usd for a in submitted),
            "total_won_usd":sum(a.amount_usd for a in won)}

@app.post("/api/applications/record")
async def record_app(data: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    a = Application(
        id="app_"+uuid.uuid4().hex[:8],
        user_id=user.id,
        opportunity_id=data.get("scholarship_id",""),
        scholarship_name=data.get("scholarship_name",""),
        opportunity_type=data.get("opportunity_type","scholarship"),
        amount_usd=float(data.get("amount_usd",0)),
        deadline=data.get("deadline",""),
        stage="submitted",
        submitted_at=datetime.utcnow())
    db.add(a)
    user.applications_this_month = (user.applications_this_month or 0)+1
    db.commit(); db.refresh(a)
    return a.to_dict()

@app.patch("/api/applications/{app_id}/outcome")
async def update_outcome(app_id: str, data: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    a = db.query(Application).filter(
        Application.id==app_id,
        Application.user_id==user.id).first()
    if not a: raise HTTPException(404, "Not found")
    a.stage = data.get("status", a.stage)
    a.notes = data.get("notes", a.notes)
    a.outcome_date = datetime.utcnow()
    a.updated_at = datetime.utcnow()
    db.commit(); db.refresh(a)
    return a.to_dict()

@app.get("/api/recommendations")
async def list_recs(user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    recs = db.query(RecRequest).filter(
        RecRequest.user_id==user.id
    ).order_by(RecRequest.created_at.desc()).all()
    return {"recommendations":[r.to_dict() for r in recs],
            "total":len(recs),
            "received":sum(1 for r in recs if r.status=="received"),
            "pending":sum(1 for r in recs if r.status!="received")}

@app.post("/api/recommendations")
async def create_rec(req: RecReqCreate, bt: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    rec = RecRequest(
        id="rec_"+uuid.uuid4().hex[:8],
        user_id=user.id,
        opportunity_name=req.opportunity_name,
        recommender_name=req.recommender_name,
        recommender_email=req.recommender_email,
        recommender_title=req.recommender_title,
        recommender_institution=req.recommender_institution,
        relationship_desc=req.relationship_desc,
        deadline=req.deadline,
        submission_link=req.submission_link,
        status="requested")
    db.add(rec); db.commit(); db.refresh(rec)
    bt.add_task(_rec_letter_job, rec.id, user.to_dict(), req.dict())
    return {**rec.to_dict(),
            "message":"Request created. Draft letter being generated."}

@app.patch("/api/recommendations/{rid}/status")
async def update_rec_status(rid: str, upd: RecStatusUp,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    rec = db.query(RecRequest).filter(
        RecRequest.id==rid,
        RecRequest.user_id==user.id).first()
    if not rec: raise HTTPException(404, "Not found")
    rec.status = upd.status
    if upd.status == "received":
        rec.received_at = datetime.utcnow()
    rec.updated_at = datetime.utcnow()
    db.commit(); db.refresh(rec)
    return rec.to_dict()

@app.get("/api/interview/questions/{scholarship_slug}")
async def interview_qs(scholarship_slug: str,
    user: User = Depends(get_current_user)):
    from engine.interview_data import QUESTION_BANKS
    return {"scholarship":scholarship_slug,
            "questions":QUESTION_BANKS.get(
                scholarship_slug.lower(),
                QUESTION_BANKS["general"])}

@app.post("/api/interview/score")
async def interview_score(data: dict,
    user: User = Depends(get_current_user)):
    from engine.scholarship_engine import score_answer
    return score_answer(data.get("question",""),
                        data.get("answer",""),
                        user.to_dict(),
                        data.get("scholarship","general"))

@app.get("/api/jobs/{jid}")
async def get_job(jid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    j = db.query(Job).filter(
        Job.id==jid, Job.user_id==user.id).first()
    if not j: raise HTTPException(404, "Job not found")
    return j.to_dict()

@app.get("/api/dashboard")
async def dashboard(user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    from engine.opportunity_db import match_opportunities
    profile = user.to_dict()
    matched = match_opportunities(profile)
    apps = db.query(Application).filter(
        Application.user_id==user.id).all()
    won = [a for a in apps if a.stage=="won"]
    submitted = [a for a in apps if a.stage=="submitted"]
    upcoming = sorted([
        {"name":o["name"],"deadline":o["deadline"],
         "amount_usd":o.get("amount_usd",0),
         "days_left":_days_until(o.get("deadline",""))}
        for o in matched
        if 0<=_days_until(o.get("deadline",""))<=60],
        key=lambda x: x["days_left"])
    return {"user":profile,"scholarships_matched":len(matched),
            "total_potential_usd":sum(o["amount_usd"] for o in matched),
            "applications_submitted":len(submitted),
            "applications_won":len(won),
            "total_won_usd":sum(a.amount_usd for a in won),
            "upcoming_deadlines":upcoming[:5]}

@app.get("/api/health")
async def health(db: Session = Depends(get_db)):
    try:
        user_count = db.query(User).count()
        db_ok = True
    except Exception as e:
        user_count = -1
        db_ok = False
    return {"status":"ok" if db_ok else "db_error",
            "users":user_count,"version":"4.0.0",
            "db":DATABASE_URL.split("://")[0],
            "timestamp":datetime.utcnow().isoformat()}

@app.get("/api/stats")
async def stats(db: Session = Depends(get_db)):
    from engine.opportunity_db import load_all_opportunities
    opps = load_all_opportunities()
    by_type = {}
    for o in opps:
        by_type.setdefault(o["opportunity_type"],0)
        by_type[o["opportunity_type"]] += 1
    return {"total_users":db.query(User).count(),
            "opportunities_in_db":len(opps),
            "total_potential_funding_usd":sum(
                o["amount_usd"] for o in opps),
            "by_type":by_type}

@app.get("/", response_class=HTMLResponse)
async def spa():
    p = Path("static/index.html")
    if p.exists():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>ScholarBot API v4</h1>")

@app.get("/{path:path}", response_class=HTMLResponse)
async def spa_fallback(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    p = Path("static/index.html")
    if p.exists():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    raise HTTPException(404)

def _update_job(jid, status, result=None, error=None):
    db = SessionLocal()
    try:
        j = db.query(Job).filter(Job.id==jid).first()
        if j:
            j.status = status
            if result is not None: j.result = result
            if error is not None: j.error = error
            j.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()

def _essay_job(jid, opp, profile, tone, max_words):
    try:
        from engine.scholarship_engine import generate_essay_for
        essay = generate_essay_for(opp, profile, tone, max_words)
        _update_job(jid,"done",
                    result={"essay":essay,
                            "word_count":len(essay.split())})
    except Exception as e:
        _update_job(jid,"failed",error=str(e))

def _packages_job(jid, profile, top_n, opp_ids):
    try:
        from engine.opportunity_db import (match_opportunities,
                                            load_all_opportunities)
        from engine.scholarship_engine import generate_essay_for
        if opp_ids:
            all_opps = load_all_opportunities()
            opps = [o for o in all_opps if o["id"] in opp_ids]
        else:
            opps = match_opportunities(profile)[:top_n]
        uid = profile.get("id","anon")
        created = []
        db = SessionLocal()
        try:
            for o in opps:
                if not o: continue
                try: essay = generate_essay_for(o, profile)
                except: essay = ("Essay for "+o["name"]+".\n\nPrompt: "+
                                  o.get("essay_prompt",""))
                dl = _days_until(o.get("deadline",""))
                pkg = Package(
                    id="pkg_"+uuid.uuid4().hex[:8],
                    user_id=uid,
                    opportunity_id=o.get("id",""),
                    scholarship_name=o.get("name",""),
                    opportunity_type=o.get("opportunity_type","scholarship"),
                    amount_usd=o.get("amount_usd",0),
                    deadline=o.get("deadline",""),
                    days_left=dl, url=o.get("url",""),
                    essay_text=essay,
                    briefing_html="<h1>"+o["name"]+"</h1><pre>"+essay+"</pre>")
                db.add(pkg)
                created.append({"opportunity":o["name"],"days_left":dl})
            db.commit()
        finally:
            db.close()
        _update_job(jid,"done",
                    result={"packages":created,"count":len(created)})
    except Exception as e:
        logger.exception("Package job failed")
        _update_job(jid,"failed",error=str(e))

def _rec_letter_job(rec_id, profile, req):
    db = SessionLocal()
    try:
        rec = db.query(RecRequest).filter(
            RecRequest.id==rec_id).first()
        if not rec: return
        llm = _get_llm()
        name = profile.get("name","")
        major = profile.get("major","")
        school = profile.get("school","")
        gpa = profile.get("gpa","")
        opp_name = req.get("opportunity_name","this opportunity")
        rec_name = req.get("recommender_name","")
        rec_title = req.get("recommender_title","")
        try:
            letter = llm(
                "Write a professional recommendation letter.",
                "Write a 300-word recommendation for "+name+
                " for "+opp_name+". Student: "+major+
                " at "+school+", GPA "+str(gpa)+
                ". Recommender: "+rec_name+", "+rec_title+".")
        except:
            letter = ("Dear Committee,\n\nI recommend "+name+
                      " for "+opp_name+".\n\nSincerely,\n"+rec_name)
        rec.drafted_letter = letter
        rec.briefing_text = "Student: "+name+"\nOpportunity: "+opp_name
        rec.updated_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        logger.error("Rec job failed: %s", e)
    finally:
        db.close()
