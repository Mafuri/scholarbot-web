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
    email_verified          = Column(Boolean, default=False)
    password_changed_at     = Column(DateTime, nullable=True)
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
    retry_count  = Column(Integer, default=0)
    started_at   = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    def to_dict(self):
        return {"id":self.id,"status":self.status,"result":self.result,
                "error":self.error, "retry_count": self.retry_count or 0,
                "started_at":self.started_at.isoformat() if self.started_at else None,
                "completed_at":self.completed_at.isoformat() if self.completed_at else None}

class UserEvent(Base):
    """T1: Behavioural event log — foundation for collaborative filtering."""
    __tablename__ = "user_events"
    id         = Column(String(32), primary_key=True)
    user_id    = Column(String(32), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)  # view/pipeline_add/essay_gen/submit/win/reject
    opp_id     = Column(String(32), nullable=True)
    opp_name   = Column(String(300), nullable=True)
    metadata_  = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Institution(Base):
    """T1: University/organisation for B2B partnerships."""
    __tablename__ = "institutions"
    id          = Column(String(32), primary_key=True)
    name        = Column(String(200), nullable=False)
    domain      = Column(String(100), unique=True, nullable=False, index=True)
    admin_email = Column(String(200), nullable=False)
    plan        = Column(String(20), default="partner")  # partner / enterprise
    student_count = Column(Integer, default=0)
    active      = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {"id":self.id,"name":self.name,"domain":self.domain,
                "admin_email":self.admin_email,"plan":self.plan,
                "student_count":self.student_count,"active":self.active,
                "created_at":self.created_at.isoformat() if self.created_at else None}


class Experiment(Base):
    """T2: A/B testing — tracks which variant each user sees."""
    __tablename__ = "experiments"
    id           = Column(String(32), primary_key=True)
    name         = Column(String(100), nullable=False, index=True)
    variant      = Column(String(50), nullable=False)   # control / treatment_a / treatment_b
    user_id      = Column(String(32), nullable=True, index=True)
    converted    = Column(Boolean, default=False)        # did the user achieve the goal?
    conversion_event = Column(String(50), nullable=True) # what counts as conversion
    metadata_    = Column(JSON, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)


class ExpertReview(Base):
    """T3: Human expert essay review queue."""
    __tablename__ = "expert_reviews"
    id           = Column(String(32), primary_key=True)
    user_id      = Column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    package_id   = Column(String(32), nullable=True)
    scholarship_name = Column(String(300), default="")
    essay_text   = Column(Text, nullable=False)
    rubric       = Column(String(50), default="general")
    status       = Column(String(30), default="pending")  # pending/in_review/completed
    reviewer_notes = Column(Text, nullable=True)
    score        = Column(Float, nullable=True)
    grade        = Column(String(5), nullable=True)
    feedback     = Column(Text, nullable=True)
    requested_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {"id":self.id,"user_id":self.user_id,"package_id":self.package_id,
                "scholarship_name":self.scholarship_name,"rubric":self.rubric,
                "status":self.status,"score":self.score,"grade":self.grade,
                "feedback":self.feedback or "",
                "reviewer_notes":self.reviewer_notes or "",
                "requested_at":self.requested_at.isoformat() if self.requested_at else None,
                "completed_at":self.completed_at.isoformat() if self.completed_at else None}


class ApiKey(Base):
    """T1: Developer API keys for third-party integrations."""
    __tablename__ = "api_keys"
    id         = Column(String(32), primary_key=True)
    user_id    = Column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    key_hash   = Column(String(64), unique=True, nullable=False, index=True)
    key_prefix = Column(String(8), nullable=False)   # first 8 chars shown to user
    name       = Column(String(100), default="My API Key")
    plan       = Column(String(20), default="free")  # free/pro/enterprise
    requests_today = Column(Integer, default=0)
    requests_total = Column(Integer, default=0)
    last_used  = Column(DateTime, nullable=True)
    active     = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {"id":self.id,"key_prefix":self.key_prefix+"...",
                "name":self.name,"plan":self.plan,
                "requests_today":self.requests_today,
                "requests_total":self.requests_total,
                "last_used":self.last_used.isoformat() if self.last_used else None,
                "active":self.active,
                "created_at":self.created_at.isoformat() if self.created_at else None}


def get_db():
    db = _get_sf()()
    try: yield db
    finally: db.close()

def _init_db():
    os.makedirs("data", exist_ok=True)
    engine = _get_engine()
    db_type = _DB_URL.split("://")[0]
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
        print(f"[DB] Initialised ({db_type})")
    except Exception as e:
        print(f"[DB] Warning: {e}")
        for t in Base.metadata.sorted_tables:
            try: t.create(engine, checkfirst=True)
            except: pass
    # Idempotent migrations — safe to run every startup
    if "postgres" in db_type:
        _safe_migrations(engine)


def _safe_migrations(engine):
    """SQLAlchemy 2.0 compatible migrations. Runs every startup — idempotent."""
    from sqlalchemy import text as _text
    sqls = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMP",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0",
        "CREATE TABLE IF NOT EXISTS user_events (id VARCHAR(32) PRIMARY KEY, user_id VARCHAR(32), event_type VARCHAR(50), opp_id VARCHAR(32), opp_name VARCHAR(300), metadata_ JSON, created_at TIMESTAMP DEFAULT NOW())",
        "CREATE TABLE IF NOT EXISTS institutions (id VARCHAR(32) PRIMARY KEY, name VARCHAR(200), domain VARCHAR(100) UNIQUE, admin_email VARCHAR(200), plan VARCHAR(20) DEFAULT 'partner', student_count INTEGER DEFAULT 0, active BOOLEAN DEFAULT TRUE, created_at TIMESTAMP DEFAULT NOW())",
        "CREATE TABLE IF NOT EXISTS experiments (id VARCHAR(32) PRIMARY KEY, name VARCHAR(100), variant VARCHAR(50), user_id VARCHAR(32), converted BOOLEAN DEFAULT FALSE, conversion_event VARCHAR(50), metadata_ JSON, created_at TIMESTAMP DEFAULT NOW())",
        "CREATE TABLE IF NOT EXISTS expert_reviews (id VARCHAR(32) PRIMARY KEY, user_id VARCHAR(32), package_id VARCHAR(32), scholarship_name VARCHAR(300), essay_text TEXT, rubric VARCHAR(50) DEFAULT 'general', status VARCHAR(30) DEFAULT 'pending', reviewer_notes TEXT, score FLOAT, grade VARCHAR(5), feedback TEXT, requested_at TIMESTAMP DEFAULT NOW(), completed_at TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS pledge_logs (id VARCHAR(32) PRIMARY KEY, user_id VARCHAR(32), ip_address VARCHAR(45), user_agent TEXT, pledge_hash VARCHAR(64), created_at TIMESTAMP DEFAULT NOW())",
    ]
    ok = 0
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            for sql in sqls:
                try:
                    conn.execute(_text(sql))
                    ok += 1
                except Exception as e:
                    logger.debug("Migration skipped: %s — %s", sql[:50], str(e)[:60])
        print(f"[DB] Migrations: {ok}/{len(sqls)} applied")
    except Exception as e:
        logger.warning("Migration block failed (non-critical): %s", e)


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


def _validate_token_session(tok, db):
    """Phase 6: Checks password_changed_at to invalidate old tokens."""
    from jose import JWTError as _JWTError
    try:
        payload = _jwt.decode(tok, _SECRET, algorithms=[_ALG])
        uid = payload.get("sub")
        iat = payload.get("iat", 0)
        if not uid: raise HTTPException(401, "Invalid token")
        u = db.query(User).filter(User.id == uid).first()
        if not u: raise HTTPException(401, "User not found")
        if u.password_changed_at:
            issued_at = datetime.utcfromtimestamp(iat)
            if u.password_changed_at > issued_at:
                raise HTTPException(401, "Password changed — please log in again.")
        return u
    except HTTPException: raise
    except _JWTError: raise HTTPException(401, "Invalid or expired token")

_INJECTION = [
    r"ignore\s+(?:all\s+)?(?:previous|above|prior)",
    r"disregard\s+(?:all\s+)?(?:previous|above)",
    r"new\s+instructions?:", r"system\s*prompt", r"you\s+are\s+now",
]
def _similarity_score(text_a: str, text_b: str) -> float:
    """T2: Trigram similarity (0-1). >0.65 = flag for review."""
    def ngrams(text, n=3):
        text = text.lower().strip()
        return set(text[i:i+n] for i in range(max(0, len(text)-n+1)))
    a, b = ngrams(text_a), ngrams(text_b)
    if not a or not b: return 0.0
    return round(len(a & b) / len(a | b), 3)


def _check_essay_similarity(essay: str, user_id: str, db) -> dict:
    """Compare essay against user's previous essays. Returns flagged status."""
    existing = db.query(Package).filter(
        Package.user_id == user_id,
        Package.essay_text != None,
        Package.essay_text != "",
    ).order_by(Package.created_at.desc()).limit(20).all()
    if not existing:
        return {"score": 0.0, "flagged": False,
                "message": "No previous essays to compare"}
    scores = [_similarity_score(essay, p.essay_text)
              for p in existing if p.essay_text]
    if not scores:
        return {"score": 0.0, "flagged": False, "message": "Original essay"}
    max_score = max(scores)
    flagged = max_score > 0.65
    return {
        "score": round(max_score, 3), "flagged": flagged,
        "message": (
            f"⚠️ {int(max_score*100)}% similar to a previous essay — "
            "personalise significantly before submitting."
        ) if flagged else f"Essay appears original ({int(max_score*100)}% similarity)",
    }


def _log_event(db, user_id: str, event_type: str,
               opp_id: str = None, opp_name: str = None, meta: dict = None):
    """Log a user behaviour event — powers collaborative filtering."""
    import uuid as _uuid2
    try:
        ev = UserEvent(
            id=f"ev_{_uuid2.uuid4().hex[:8]}",
            user_id=user_id, event_type=event_type,
            opp_id=opp_id, opp_name=opp_name, metadata_=meta or {},
        )
        db.add(ev); db.commit()
    except Exception as e:
        logger.debug("Event log failed (non-critical): %s", e)


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
    # T4: Sentry error tracking
    sentry_dsn = os.environ.get("SENTRY_DSN","")
    if sentry_dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
            sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=0.2,
                integrations=[FastApiIntegration(), SqlalchemyIntegration()])
            logger.info("Sentry error tracking: ACTIVE")
        except ImportError:
            logger.info("Sentry SDK not installed — add sentry-sdk to requirements.txt")
    # Phase 6: Start deadline reminder scheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        import os as _os
        _email_key = _os.environ.get("SENDER_API_KEY","")

        def _send_dl(to, name, scholarships):
            import requests as _req
            from_email = _os.environ.get("FROM_EMAIL","noreply@scholarbot.app")
            base = _os.environ.get("BASE_URL","https://scholarbot-web.onrender.com")
            rows = "".join(f"<tr><td>{s['name'][:50]}</td><td>{s['days_left']}d</td>"
                           f"<td>${s.get('amount_usd',0):,.0f}</td></tr>" for s in scholarships[:5])
            html = (f"<p>Hi {name}, you have {len(scholarships)} upcoming deadline(s):</p>"
                    f"<table>{rows}</table>"
                    f"<p><a href='{base}/?page=pipeline'>View pipeline</a></p>")
            _req.post("https://api.sender.net/v2/message/send",
                headers={"Authorization":f"Bearer {_email_key}","Content-Type":"application/json"},
                json={"from":{"email":from_email,"name":"ScholarBot"},
                      "to":{"email":to,"name":name},
                      "subject":f"⏰ {len(scholarships)} deadline(s) approaching","html":html},
                timeout=15)
        scheduler = AsyncIOScheduler()

        def _send_reminders():
            if not _email_key: return
            db = SessionLocal()
            try:
                apps = db.query(Application).filter(
                    Application.stage.in_(["researching","essay_ready","submitted"])
                ).all()
                # Group by user and find deadlines in 1 or 7 days
                from datetime import datetime as _dt
                user_deadlines = {}
                for a in apps:
                    days = _days_until(a.deadline)
                    if days in (1, 7):
                        user_deadlines.setdefault(a.user_id, []).append({
                            "name": a.scholarship_name, "deadline": a.deadline,
                            "days_left": days, "amount_usd": a.amount_usd, "url": a.url
                        })
                for uid, deadlines in user_deadlines.items():
                    u = db.query(User).filter(User.id == uid).first()
                    if u and u.email:
                        _send_dl(u.email, u.name, deadlines)
                        logger.info("Reminder sent to %s (%d deadlines)", u.email, len(deadlines))
            except Exception as e:
                logger.error("Reminder job failed: %s", e)
            finally:
                db.close()

        scheduler.add_job(_send_reminders, "cron", hour=8, minute=0)
        scheduler.start()
        logger.info("APScheduler started — deadline reminders at 08:00 daily")
    except ImportError:
        logger.info("APScheduler not installed — deadline reminders disabled")

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
        # Normalise GPA from any international scale
        from engine.scholarship_engine import normalise_gpa as _ngpa
        try:
            gpa_result = _ngpa(float(req.gpa or 0), country=req.nationality)
            gpa_normalised = gpa_result.get("gpa_4", float(req.gpa or 0))
        except Exception:
            gpa_normalised = float(req.gpa or 0)
        u = User(id=f"user_{uuid.uuid4().hex[:10]}", name=req.name, email=req.email,
                 password_hash=_hash_pw(req.password), degree_level=req.degree_level,
                 major=req.major, school=req.school, nationality=req.nationality,
                 gpa=min(4.0, gpa_normalised), financial_need=bool(req.financial_need),
                 languages=["English"], skills=[], extracurriculars=[],
                 demographic_tags=[], personal_statement="")
        db.add(u); db.commit(); db.refresh(u)
        # T5: Send verification email if Sender.net configured
        _sender_key = os.environ.get("SENDER_API_KEY","")
        if _sender_key:
            import secrets as _sec2, hashlib as _hl3, requests as _rq2
            raw_tok = _sec2.token_urlsafe(32)
            t_hash = _hl3.sha256(raw_tok.encode()).hexdigest()
            _reset_tokens[f"verify_{t_hash}"] = {
                "user_id": u.id, "used": False,
                "expires_at": datetime.utcnow() + timedelta(days=7),
            }
            _base = os.environ.get("BASE_URL","https://scholarbot-web.onrender.com")
            _from = os.environ.get("FROM_EMAIL","noreply@scholarbot.app")
            try:
                link = f"{_base}/api/auth/verify-email?token={raw_tok}"
                html = (f"<p>Hi {u.name},</p><p>Welcome to ScholarBot!</p>"
                        f"<p><a href='{link}' style='background:#2563eb;color:#fff;"
                        f"padding:12px 24px;border-radius:6px;text-decoration:none;"
                        f"display:inline-block'>Verify my email</a></p>"
                        f"<p style='font-size:12px;color:#888'>Link expires in 7 days.</p>")
                _rq2.post("https://api.sender.net/v2/message/send",
                    headers={"Authorization":f"Bearer {_sender_key}",
                             "Content-Type":"application/json"},
                    json={"from":{"email":_from,"name":"ScholarBot"},
                          "to":{"email":u.email,"name":u.name},
                          "subject":"Verify your ScholarBot email","html":html},
                    timeout=8)
            except Exception as _ve:
                logger.debug("Verification email (non-critical): %s", _ve)
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
@app.get("/api/auth/verify-email")
async def verify_email(token: str, db: Session = Depends(get_db)):
    """T5: Marks account as email-verified."""
    import hashlib as _hl4
    t_hash = _hl4.sha256(token.encode()).hexdigest()
    entry = _reset_tokens.get(f"verify_{t_hash}")
    if not entry or entry.get("used") or entry["expires_at"] < datetime.utcnow():
        raise HTTPException(400, "Invalid or expired verification link")
    u = db.query(User).filter(User.id == entry["user_id"]).first()
    if u:
        u.email_verified = True
        entry["used"] = True
        db.commit()
    return {"message": "Email verified. Your ScholarBot account is fully activated."}


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

# Phase 8+: Extra verified scholarships extending the engine database
EXTRA_OPPORTUNITIES = [
    {"id":"mastercard_scholars","name":"Mastercard Foundation Scholars Program","type":"scholarship","amount_usd":60000,"deadline":"2025-04-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Rwanda","Zambia","Zimbabwe","Senegal"],"degree_levels":["Undergraduate","Graduate"],"field":"All fields","gpa_min":3.0,"tags":["africa","leadership","community"],"url":"https://mastercardfdn.org/all/scholars/","description":"Full scholarships for academically talented and financially disadvantaged African youth","competitiveness":{"label":"Highly Competitive","acceptance_rate":0.05}},
    {"id":"daad_africa_dev","name":"DAAD Development-Related Postgraduate Scholarship","type":"scholarship","amount_usd":18000,"deadline":"2025-10-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Cameroon","South Africa","Ethiopia"],"degree_levels":["Graduate","Postgraduate"],"field":"STEM, Social Sciences","gpa_min":3.0,"tags":["germany","stem","development"],"url":"https://www.daad.de/en/study-and-research-in-germany/scholarships/","description":"DAAD scholarships for Africans to study in Germany","competitiveness":{"label":"Competitive","acceptance_rate":0.12}},
    {"id":"aga_khan_intl","name":"Aga Khan Foundation International Scholarship","type":"scholarship","amount_usd":45000,"deadline":"2025-03-31","eligible_countries":["Kenya","Tanzania","Uganda","India","Pakistan","Bangladesh","Mozambique"],"degree_levels":["Graduate"],"field":"All fields","gpa_min":3.2,"tags":["development","leadership"],"url":"https://www.akdn.org/our-agencies/aga-khan-foundation/international-scholarship-programme","description":"Postgraduate scholarships for outstanding students from developing countries","competitiveness":{"label":"Highly Competitive","acceptance_rate":0.06}},
    {"id":"google_anita_borg","name":"Google Anita Borg Memorial Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-12-01","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate"],"field":"Computer Science","gpa_min":3.2,"tags":["women","computer science","technology"],"url":"https://buildyourfuture.withgoogle.com/scholarships/generation-google-scholarship","description":"For women pursuing computer science and related fields","competitiveness":{"label":"Competitive","acceptance_rate":0.10}},
    {"id":"microsoft_phd","name":"Microsoft Research PhD Fellowship","type":"fellowship","amount_usd":42000,"deadline":"2025-09-30","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Computer Science, AI","gpa_min":3.5,"tags":["ai","machine learning","research","phd"],"url":"https://www.microsoft.com/en-us/research/academic-program/phd-fellowship/","description":"Two-year fellowship for PhD students in computer science","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.04}},
    {"id":"atlas_corps","name":"Atlas Corps Fellowship","type":"fellowship","amount_usd":8000,"deadline":"2025-11-30","eligible_countries":["Kenya","Nigeria","Ghana","India","Pakistan","Bangladesh","Brazil","Colombia","Philippines"],"degree_levels":["Graduate"],"field":"Nonprofit Management, Social Enterprise","gpa_min":2.8,"tags":["nonprofit","leadership","community"],"url":"https://atlascorps.org/apply/","description":"12-18 month professional fellowship at US nonprofits","competitiveness":{"label":"Moderate","acceptance_rate":0.18}},
    {"id":"obama_scholars","name":"Obama Foundation Scholars Program","type":"fellowship","amount_usd":65000,"deadline":"2025-01-15","eligible_countries":["Global"],"degree_levels":["Graduate"],"field":"Public Affairs, Leadership","gpa_min":3.0,"tags":["leadership","policy","civic"],"url":"https://www.obama.org/programs/scholars/","description":"One-year Columbia fellowship for emerging civic leaders","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.02}},
    {"id":"unep_champions","name":"UNEP Young Champions of the Earth","type":"competition","amount_usd":10000,"deadline":"2025-07-01","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Environment","gpa_min":0,"tags":["environment","climate","entrepreneurship","sustainability"],"url":"https://www.unep.org/youngchampions/","description":"Recognises bold young environmental entrepreneurs aged 18-30","competitiveness":{"label":"Highly Competitive","acceptance_rate":0.05}},
    {"id":"commonwealth_distance","name":"Commonwealth Distance Learning Scholarship","type":"scholarship","amount_usd":15000,"deadline":"2025-05-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Zambia","Bangladesh","India","Pakistan","Sri Lanka"],"degree_levels":["Graduate"],"field":"Development, Public Health","gpa_min":2.8,"tags":["commonwealth","distance learning","development","public health"],"url":"https://cscuk.fcdo.gov.uk/scholarships/commonwealth-distance-learning-scholarships/","description":"Distance-learning scholarships for Commonwealth development professionals","competitiveness":{"label":"Moderate","acceptance_rate":0.20}},
    {"id":"fogarty_global","name":"Fogarty International Research Fellowship","type":"fellowship","amount_usd":35000,"deadline":"2025-09-01","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Global Health, Medical Research","gpa_min":3.4,"tags":["health","medicine","research","global health","nih"],"url":"https://www.fic.nih.gov/Programs/Pages/fellows-international.aspx","description":"NIH fellowship for early-career global health researchers","competitiveness":{"label":"Competitive","acceptance_rate":0.12}},
    {"id":"young_africa_works","name":"Young Africa Works Innovation Fund","type":"grant","amount_usd":25000,"deadline":"2025-06-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Rwanda","Senegal"],"degree_levels":["Undergraduate","Graduate"],"field":"Business, Technology, Agriculture","gpa_min":0,"tags":["entrepreneurship","innovation","africa","business","agriculture"],"url":"https://mastercardfdn.org/all/young-africa-works/","description":"Funding for young African entrepreneurs creating jobs","competitiveness":{"label":"Competitive","acceptance_rate":0.10}},
    {"id":"awdf_grant","name":"African Women's Development Fund Grant","type":"grant","amount_usd":10000,"deadline":"2025-09-30","eligible_countries":["Kenya","Nigeria","Ghana","Uganda","Tanzania","Senegal","Mali"],"degree_levels":["Graduate","Postgraduate"],"field":"Gender, Development","gpa_min":2.8,"tags":["women","gender","development","africa","human rights"],"url":"https://awdf.org/","description":"Grants supporting African women in development and human rights","competitiveness":{"label":"Moderate","acceptance_rate":0.15}},
    {"id":"ieee_graduate","name":"IEEE Foundation Graduate Fellowship","type":"fellowship","amount_usd":10000,"deadline":"2025-10-01","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Electrical Engineering","gpa_min":3.5,"tags":["engineering","electrical","ieee","stem","research"],"url":"https://www.ieee.org/education/scholarships/index.html","description":"Recognises outstanding graduate students in electrical engineering","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}},
    {"id":"commonwealth_split","name":"Commonwealth Split-Site Scholarship","type":"scholarship","amount_usd":25000,"deadline":"2025-11-19","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Zambia","India","Pakistan","Sri Lanka"],"degree_levels":["Postgraduate"],"field":"All fields","gpa_min":3.0,"tags":["commonwealth","research","phd","split site"],"url":"https://cscuk.fcdo.gov.uk/scholarships/commonwealth-split-site-scholarships/","description":"PhD students spend up to 12 months at a UK university alongside home study","competitiveness":{"label":"Competitive","acceptance_rate":0.15}},
    {"id":"african_dev_bank_sc","name":"African Development Bank Scholarship","type":"scholarship","amount_usd":30000,"deadline":"2025-03-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Egypt","Morocco","South Africa"],"degree_levels":["Graduate"],"field":"Economics, Development, Finance","gpa_min":3.2,"tags":["economics","finance","development","africa","policy"],"url":"https://www.afdb.org/en/topics-and-sectors/initiatives-partnerships/african-development-bank-scholarship-program","description":"For African professionals in development-related postgraduate studies","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}},
    {"id":"soros_osi","name":"Open Society Foundations Scholarship","type":"scholarship","amount_usd":20000,"deadline":"2025-02-28","eligible_countries":["Kenya","Nigeria","Ghana","Uganda","Tanzania","South Africa","Zimbabwe","Zambia","Mozambique"],"degree_levels":["Graduate"],"field":"Law, Human Rights, Social Science, Media","gpa_min":3.0,"tags":["human rights","law","media","social justice","democracy"],"url":"https://www.opensocietyfoundations.org/grants/higher-education-support-program","description":"Supporting academics advancing open society values","competitiveness":{"label":"Competitive","acceptance_rate":0.10}},
]

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
    base_opps = match_opportunities(profile, opp_type=opp_type, min_amount=min_amount or 0)
    ext_ids = {o.get("id") for o in base_opps}
    opps = base_opps + [o for o in EXTRA_OPPORTUNITIES if o.get("id") not in ext_ids]
    if field: opps=[o for o in opps if field.lower() in o.get("name","").lower() or
                    field.lower() in " ".join(o.get("tags",[])).lower()]
    if region: opps=[o for o in opps if any(region.lower() in c.lower()
                     for c in o.get("eligible_countries",[]))]
    # T2: Behavioral score boosting — opportunities users like you won/submitted
    # get a small boost to their match score
    user_id = profile.get("id","")
    if user_id:
        try:
            db_temp = SessionLocal()
            # Find which opps this user's similar cohort has had positive outcomes with
            won_ids = {ev.opp_id for ev in db_temp.query(UserEvent).filter(
                UserEvent.event_type.in_(["won", "submitted"]),
                UserEvent.opp_id != None,
            ).limit(500).all()}
            db_temp.close()
            if won_ids:
                for o in opps:
                    if o.get("id") in won_ids:
                        o["_behavioral_boost"] = 0.05  # +5% for proven opportunities
        except Exception:
            pass
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


# ── Scholarship Full-Text Search ─────────────────────────────
@app.get("/api/scholarships/search")
async def search_scholarships(
    q: str = "",
    degree_level: str = None,
    country: str = None,
    min_amount: float = 0,
    opp_type: str = None,
    db: Session = Depends(get_db),
):
    """
    Full-text search across all opportunities.
    Searches: name, provider, tags, field, country, description.
    Supports filters: degree_level, country, min_amount, opp_type.
    """
    from engine.opportunity_db import load_all_opportunities
    all_opps = load_all_opportunities()

    if not q and not degree_level and not country and not opp_type and min_amount == 0:
        return {"results": all_opps[:20], "total": len(all_opps),
                "query": "", "message": "Showing first 20. Use q= to search."}

    query_terms = q.lower().split() if q else []
    results = []

    for opp in all_opps:
        # Build searchable text blob
        searchable = " ".join([
            opp.get("name",""), opp.get("provider",""),
            opp.get("opportunity_type",""),
            " ".join(opp.get("tags",[])),
            " ".join(opp.get("major_restrictions",[])),
            " ".join(opp.get("eligible_countries",[])),
            opp.get("essay_prompt",""), opp.get("eligibility",""),
        ]).lower()

        # Text match
        if query_terms:
            text_score = sum(1 for term in query_terms if term in searchable)
            if text_score == 0:
                continue
        else:
            text_score = 1

        # Filters
        if degree_level and degree_level not in (opp.get("degree_levels") or []):
            continue
        if min_amount and opp.get("amount_usd",0) < min_amount:
            continue
        if opp_type and opp.get("opportunity_type") != opp_type:
            continue
        if country:
            eligible = [c.lower() for c in (opp.get("eligible_countries") or [])]
            is_global = any(c in ("all countries","global","worldwide","international")
                           for c in eligible)
            if not is_global and country.lower() not in " ".join(eligible).lower():
                continue

        results.append({**opp, "_relevance": text_score})

    # Sort by relevance then amount
    results.sort(key=lambda x: (-x.get("_relevance",0), -x.get("amount_usd",0)))
    for r in results:
        r.pop("_relevance", None)

    return {
        "results": results[:50],
        "total": len(results),
        "query": q,
        "filters": {"degree_level": degree_level, "country": country,
                    "min_amount": min_amount, "opp_type": opp_type},
    }

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


@app.post("/api/gpa/detect")
async def detect_gpa(req: dict):
    """
    T3: GPA scale auto-detection for onboarding confirmation.
    Frontend calls this as user types their GPA to show:
    'Detected: Nigerian 4.2/5.0 → 3.36/4.0. Correct?'
    """
    gpa_raw = float(req.get("gpa", 0) or 0)
    country = req.get("nationality", "")
    if gpa_raw <= 0:
        return {"gpa_4": 0.0, "scale": 4.0, "label": "Enter your GPA", "confidence": "low"}

    # Scale detection thresholds
    breakpoints = [(4.5,4.0),(5.5,5.0),(6.5,6.0),(7.5,7.0),(10.5,10.0),(21.0,20.0),(float("inf"),100.0)]
    country_scales = {
        "kenya":4.0,"usa":4.0,"united states":4.0,"canada":4.0,
        "nigeria":5.0,"ghana":4.0,"tanzania":4.0,"uganda":4.0,"rwanda":4.0,
        "south africa":7.0,"australia":7.0,"new zealand":7.0,
        "india":10.0,"france":20.0,"lebanon":20.0,"senegal":20.0,
        "egypt":100.0,"china":100.0,"uk":100.0,"united kingdom":100.0,
        "germany":4.0,  # German scale handled separately
    }
    cl = country.lower().strip()
    is_german = cl == "germany"

    if is_german:
        # German 1-5 inverted scale
        german_map = {1.0:4.0,1.3:3.7,1.7:3.3,2.0:3.0,2.3:2.7,2.7:2.3,
                      3.0:2.0,3.3:1.7,3.7:1.3,4.0:1.0,5.0:0.0}
        nearest = min(german_map.keys(), key=lambda x: abs(x-gpa_raw))
        gpa_4 = german_map[nearest]
        return {"gpa_4": gpa_4, "scale": 5.0, "original": gpa_raw,
                "label": f"{gpa_raw}/5.0 (German) → {gpa_4}/4.0",
                "confidence": "high", "country": country}

    if cl in country_scales:
        scale = country_scales[cl]
        confidence = "high"
    else:
        scale = next(s for t,s in breakpoints if gpa_raw < t)
        confidence = "medium" if gpa_raw > 4.0 else "low"

    gpa_4 = round(min(4.0, (gpa_raw / scale) * 4.0), 2) if scale != 4.0 else min(4.0, gpa_raw)
    label = f"{gpa_raw}/{scale}"
    if cl: label += f" ({country.title()})"
    label += f" → {gpa_4}/4.0"
    return {"gpa_4": gpa_4, "scale": scale, "original": gpa_raw,
            "label": label, "confidence": confidence, "country": country}

@app.get("/api/scholarships/{sid}/explain")
async def explain(sid: str, user: User = Depends(_opt_user)):
    from engine.opportunity_db import load_all_opportunities
    opp = next((o for o in load_all_opportunities() if o["id"]==sid), None)
    if not opp: raise HTTPException(404, "Not found")
    profile = user.to_dict() if user else {"degree_level":"Graduate",
        "nationality":"Kenya","financial_need":False,"gpa":0,"major":""}

    # Inline explainability with Phase 6 fixed EV formula
    gpa_min = float(opp.get("gpa_min") or 0)
    gpa_user = float(profile.get("gpa") or 0)
    nationality = (profile.get("nationality") or "").lower()
    eligible = [c.lower() for c in (opp.get("eligible_countries") or [])]
    degree_levels = [d.lower() for d in (opp.get("degree_levels") or [])]
    degree_user = (profile.get("degree_level") or "Graduate").lower()
    amount = float(opp.get("amount_usd") or 0)
    acceptance = float((opp.get("competitiveness") or {}).get("acceptance_rate") or 0.15)

    factors = []
    # GPA
    if gpa_min:
        met = gpa_user >= gpa_min
        factors.append({"factor":"GPA","met":met,"icon":"📊",
            "detail": f"Your GPA {gpa_user:.1f} {'meets' if met else 'below'} minimum {gpa_min:.1f}"})
    else:
        factors.append({"factor":"GPA","met":True,"icon":"📊","detail":"No minimum GPA required"})
    # Country
    is_global = any(c in ("global","worldwide","all","international") for c in eligible)
    country_met = is_global or any(nationality in c or c in nationality for c in eligible)
    factors.append({"factor":"Country","met":country_met,"icon":"🌍",
        "detail": "Open to all countries" if is_global else
                  f"{nationality.title()} is {'eligible' if country_met else 'not listed'}"})
    # Degree
    degree_met = not degree_levels or any(degree_user in d or d in degree_user for d in degree_levels)
    factors.append({"factor":"Degree","met":degree_met,"icon":"🎓",
        "detail": f"{profile.get('degree_level','Graduate')} {'matches' if degree_met else 'does not match'}"})
    # Field
    opp_tags = " ".join(opp.get("tags") or []) + " " + (opp.get("field") or "")
    major = (profile.get("major") or "").lower()
    field_met = not opp_tags.strip() or any(w in opp_tags.lower() for w in major.split() if len(w) > 2)
    factors.append({"factor":"Field","met":field_met,"icon":"📚",
        "detail": f"Your major '{profile.get('major','')}' {'aligns' if field_met else 'may not align'}"})

    met_count = sum(1 for f in factors if f["met"])
    score = round(met_count / len(factors), 2) if factors else 0.5
    grade = "A" if score >= 0.85 else "B" if score >= 0.70 else "C" if score >= 0.55 else "D"

    # Phase 6: Fixed EV formula — diminishing penalty on competitive scholarships
    ev_penalty = min(acceptance * 5, 1.0)
    expected_value = round(amount * score * ev_penalty)

    gaps = [{"factor":f["factor"],"action":f"Improve your {f['factor']} to qualify"}
            for f in factors if not f["met"]]

    rec = ("Strong match — apply immediately." if score >= 0.85 else
           "Good match — personalise your essay carefully." if score >= 0.70 else
           "Partial match — address the gaps before applying." if score >= 0.55 else
           "Weak match — consider better-aligned scholarships first.")

    # Log scholarship view event
    if user:
        from sqlalchemy.orm import Session as _S
        _db = _get_sf()()
        try: _log_event(_db, user.id, "view", opp.get("id"), opp.get("name"))
        finally: _db.close()
    return {
        "scholarship_id": opp.get("id",""), "scholarship_name": opp.get("name",""),
        "match_score": score, "grade": grade,
        "amount_usd": amount, "acceptance_rate": acceptance,
        "expected_value_usd": expected_value,
        "competitiveness": f"{int(acceptance*100)}% acceptance rate",
        "factors": factors, "gaps": gaps, "strengths": [f["detail"] for f in factors if f["met"]],
        "recommendation": rec, "factors_met": met_count, "factors_total": len(factors),
    }


@app.get("/api/scholarships/recommended")
async def recommended_scholarships(user: User = Depends(_get_user),
                                    db: Session = Depends(get_db)):
    """
    Collaborative filtering: find scholarships that students similar to
    this user have added to their pipeline or submitted.
    Similar = same degree_level + nationality + financial_need.
    Returns up to 10 recommended opportunities not yet in user's pipeline.
    """
    from engine.opportunity_db import load_all_opportunities

    # Find similar users (same degree + nationality)
    similar_users = db.query(User).filter(
        User.id != user.id,
        User.degree_level == user.degree_level,
        User.nationality == user.nationality,
    ).limit(200).all()

    if not similar_users:
        # Fallback: just return top matches
        opps = _match_opps(user.to_dict())[:10]
        return {"recommended": opps, "method": "fallback_match",
                "similar_users_found": 0}

    similar_ids = [u.id for u in similar_users]

    # Find what those users added to pipeline / submitted / won
    events = db.query(UserEvent).filter(
        UserEvent.user_id.in_(similar_ids),
        UserEvent.event_type.in_(["pipeline_add", "submitted", "won"]),
        UserEvent.opp_id != None,
        UserEvent.opp_id != "",
    ).all()

    if not events:
        opps = _match_opps(user.to_dict())[:10]
        return {"recommended": opps, "method": "fallback_match",
                "similar_users_found": len(similar_ids)}

    # Score opportunities by how many similar users interacted with them
    from collections import Counter
    # Weight: won=3, submitted=2, pipeline_add=1
    weights = {"won": 3, "submitted": 2, "pipeline_add": 1}
    opp_scores: dict = Counter()
    opp_names: dict = {}
    for ev in events:
        opp_scores[ev.opp_id] += weights.get(ev.event_type, 1)
        if ev.opp_name:
            opp_names[ev.opp_id] = ev.opp_name

    # Get user's existing pipeline to exclude already-added items
    user_apps = db.query(Application).filter(
        Application.user_id == user.id
    ).all()
    already_added = {a.opportunity_id for a in user_apps}

    # Load full opportunity details for top recommendations
    all_opps = {o["id"]: o for o in load_all_opportunities()}
    recommendations = []
    for opp_id, score in opp_scores.most_common(20):
        if opp_id in already_added:
            continue
        opp = all_opps.get(opp_id)
        if opp:
            recommendations.append({**opp, "collab_score": score})
        if len(recommendations) >= 10:
            break

    # If fewer than 5, top up with regular matching
    if len(recommendations) < 5:
        matched = _match_opps(user.to_dict())
        matched_ids = {r["id"] for r in recommendations}
        for o in matched:
            if o["id"] not in matched_ids and o["id"] not in already_added:
                recommendations.append({**o, "collab_score": 0})
            if len(recommendations) >= 10:
                break

    return {
        "recommended": recommendations,
        "method": "collaborative_filtering",
        "similar_users_found": len(similar_ids),
        "based_on_events": len(events),
    }

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
    db.add(a); db.commit(); db.refresh(a)
    _log_event(db, user.id, "pipeline_add",
               data.get("scholarship_id",""), data.get("scholarship_name",""))
    return a.to_dict()

@app.patch("/api/pipeline/{app_id}/move")
async def move_stage(app_id: str, data: dict, user: User = Depends(_get_user),
                      db: Session = Depends(get_db)):
    a = db.query(Application).filter(Application.id==app_id,
        Application.user_id==user.id).first()
    if not a: raise HTTPException(404, "Not found")
    stage = data.get("stage", a.stage)
    if stage not in VALID_STAGES: raise HTTPException(400, "Invalid stage")
    a.stage = stage; a.updated_at = datetime.utcnow()
    db.commit(); db.refresh(a)
    if stage in ("submitted","won","rejected"):
        _log_event(db, user.id, stage, a.opportunity_id, a.scholarship_name)
    return a.to_dict()

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

@app.post("/api/applications/{app_id}/feedback")
async def application_feedback(app_id: str, data: dict,
                                 user: User = Depends(_get_user),
                                 db: Session = Depends(get_db)):
    """
    T3: Post-outcome feedback — used by the behavioral learning loop.
    helpfulness 1-5 updates the A/B test conversion tracking.
    """
    a = db.query(Application).filter(
        Application.id == app_id,
        Application.user_id == user.id,
    ).first()
    if not a: raise HTTPException(404, "Application not found")

    helpfulness = int(data.get("essay_helpfulness", 3))
    essay_used  = bool(data.get("essay_used", True))
    outcome     = data.get("outcome", a.stage)   # won / rejected

    # Log feedback as a behavioral event for the learning loop
    _log_event(db, user.id, f"feedback_{outcome}",
               a.opportunity_id, a.scholarship_name,
               {"helpfulness": helpfulness, "essay_used": essay_used})

    # Mark A/B experiment conversion if essay was helpful and outcome was positive
    if outcome == "won" and helpfulness >= 4:
        try:
            _record_experiment(db, "essay_model", user.id,
                               converted=True, event="essay_helpfulness_5")
        except Exception:
            pass

    return {"message": "Feedback recorded. Thank you — this improves future matches."}


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

@app.get("/api/essays/diff/{uid}/{pid_a}/{pid_b}")
async def essay_diff(uid: str, pid_a: str, pid_b: str,
                     user: User = Depends(_get_user),
                     db: Session = Depends(get_db)):
    """
    T4: Side-by-side diff between two essay versions.
    Returns unified diff + similarity score.
    """
    if user.id != uid:
        raise HTTPException(403, "Access denied")
    pkg_a = db.query(Package).filter(Package.id == pid_a).first()
    pkg_b = db.query(Package).filter(Package.id == pid_b).first()
    if not pkg_a or not pkg_b:
        raise HTTPException(404, "One or both packages not found")

    import difflib
    essay_a = (pkg_a.essay_text or "").splitlines(keepends=True)
    essay_b = (pkg_b.essay_text or "").splitlines(keepends=True)

    unified = list(difflib.unified_diff(
        essay_a, essay_b,
        fromfile=f"Version {pkg_a.created_at.strftime('%Y-%m-%d') if pkg_a.created_at else 'A'}",
        tofile=f"Version {pkg_b.created_at.strftime('%Y-%m-%d') if pkg_b.created_at else 'B'}",
        lineterm=""
    ))

    added = sum(1 for l in unified if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in unified if l.startswith("-") and not l.startswith("---"))
    sim = _similarity_score(pkg_a.essay_text or "", pkg_b.essay_text or "")

    return {
        "package_a": {"id": pid_a, "scholarship": pkg_a.scholarship_name,
                      "created_at": pkg_a.created_at.isoformat() if pkg_a.created_at else None},
        "package_b": {"id": pid_b, "scholarship": pkg_b.scholarship_name,
                      "created_at": pkg_b.created_at.isoformat() if pkg_b.created_at else None},
        "diff": "".join(unified),
        "lines_added": added,
        "lines_removed": removed,
        "similarity_score": sim,
        "changed_significantly": sim < 0.70,
    }


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
@app.post("/api/essays/critique")
async def critique_essay(req: dict, user: User = Depends(_get_user),
                          db: Session = Depends(get_db)):
    """
    T3: Rubric-aware essay critique (Sopact-style differentiator).
    Reads the essay against the scholarship rubric, cites specific sentences,
    and returns scored feedback with evidence.
    """
    essay = req.get("essay", "")
    scholarship_id = req.get("scholarship_id", "")
    scholarship_name = req.get("scholarship_name", "ScholarBot")

    if len(essay.split()) < 50:
        raise HTTPException(400, "Essay too short — minimum 50 words for critique")

    # Load rubric if available
    from engine.interview_data import QUESTION_BANKS
    rubric_name = req.get("rubric", "general")
    rubrics = {
        "chevening":       ["Leadership & Influence", "Networking Ability",
                            "Ambassador Potential", "Career Plan"],
        "fulbright":       ["Academic Excellence", "Project Feasibility",
                            "Cross-Cultural Engagement", "Long-term Impact"],
        "gates_cambridge": ["Academic Achievement", "Leadership Potential",
                            "Commitment to Others", "Cambridge Fit"],
        "general":         ["Clarity & Structure", "Specificity & Evidence",
                            "Relevance to Scholarship", "Potential Impact"],
    }
    rubric_dims = rubrics.get(rubric_name, rubrics["general"])
    rubric_str = ", ".join(f"{d}" for d in rubric_dims)

    # Check similarity against previous essays
    similarity = _check_essay_similarity(essay, user.id, db)

    # Claude rubric critique
    llm = _llm()
    system = (
        "You are a scholarship committee expert. Critique this essay against "
        "the scholarship rubric. For each rubric dimension, cite the EXACT "
        "sentence from the essay that best demonstrates it (or note if missing). "
        "Return ONLY valid JSON."
    )
    prompt = (
        f"Scholarship: {scholarship_name}\n"
        f"Rubric dimensions: {rubric_str}\n\n"
        f"Essay ({len(essay.split())} words):\n{essay[:3000]}\n\n"
        "Return JSON with:\n"
        "overall_score (0.0-1.0), grade (A/B/C/D), "
        "word_count (integer), "
        "dimensions (array of {name, score, evidence_sentence, feedback}), "
        "strengths (array of strings), "
        "improvements (array of strings), "
        "suggested_additions (array of strings)"
    )
    try:
        raw = llm(system, prompt)
        import json as _json
        start = raw.find("{"); end = raw.rfind("}") + 1
        result = _json.loads(raw[start:end]) if start >= 0 else {}
    except Exception as e:
        logger.warning("Critique AI fallback: %s", e)
        # Rule-based fallback
        wc = len(essay.split())
        has_numbers = any(ch.isdigit() for ch in essay)
        score = min(1.0, 0.5 + (0.1 if wc >= 300 else 0) +
                    (0.15 if has_numbers else 0) +
                    (0.1 if len(set(essay.lower().split())) / max(len(essay.split()), 1) > 0.6 else 0))
        result = {
            "overall_score": round(score, 2),
            "grade": "A" if score >= 0.85 else "B" if score >= 0.70 else "C",
            "word_count": wc,
            "dimensions": [{"name": d, "score": round(score, 2),
                             "evidence_sentence": "See essay for examples",
                             "feedback": "Provide specific examples"} for d in rubric_dims],
            "strengths": ["Content addresses the scholarship requirements"],
            "improvements": ["Add specific numbers and measurable outcomes",
                             "Include a concrete career plan"],
            "suggested_additions": ["Mention specific courses or research",
                                    "Quantify your leadership impact"],
        }

    # Log essay critique event
    _log_event(db, user.id, "essay_critique", scholarship_id, scholarship_name)

    return {
        **result,
        "rubric": rubric_name,
        "rubric_dimensions": rubric_dims,
        "similarity_check": similarity,
        "scholarship_id": scholarship_id,
    }


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
@app.get("/api/debug")
async def debug_info():
    """Diagnostic endpoint — shows exact version and startup status."""
    import sys
    db_ok = False
    db_error = ""
    table_count = 0
    try:
        from sqlalchemy import text as _t
        with _get_engine().connect() as conn:
            result = conn.execute(_t(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema='public'"
            ))
            table_count = result.scalar()
            db_ok = True
    except Exception as e:
        db_error = str(e)[:200]
    return {
        "version": "4.2.0",
        "python": sys.version[:20],
        "db_connected": db_ok,
        "db_error": db_error,
        "tables_in_db": table_count,
        "extra_opps": len(EXTRA_OPPORTUNITIES),
        "status": "ok" if db_ok else "db_error",
    }


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
    """Service worker with offline support and push notifications."""
    p = Path("static/sw.js")
    sw_content = """const CACHE='scholarbot-v4';const SHELL=['/'];
self.addEventListener('install',function(e){e.waitUntil(caches.open(CACHE).then(function(c){return c.addAll(SHELL);}));self.skipWaiting();});
self.addEventListener('activate',function(e){e.waitUntil(caches.keys().then(function(ks){return Promise.all(ks.filter(function(k){return k!==CACHE;}).map(function(k){return caches.delete(k);}));}));self.clients.claim();});
self.addEventListener('fetch',function(e){if(e.request.method!=='GET')return;if(e.request.url.includes('/api/')){e.respondWith(fetch(e.request).catch(function(){return new Response(JSON.stringify({error:'Offline'}),{headers:{'Content-Type':'application/json'}});}));return;}e.respondWith(caches.match(e.request).then(function(cached){return cached||fetch(e.request).then(function(resp){if(resp.ok){var cl=resp.clone();caches.open(CACHE).then(function(c){c.put(e.request,cl);});}return resp;});}));});
self.addEventListener('push',function(e){var d={};try{d=e.data.json();}catch(err){d={title:'ScholarBot',body:'Scholarship deadline approaching'};}e.waitUntil(self.registration.showNotification(d.title||'ScholarBot',{body:d.body||'Check your pipeline.',icon:'/favicon.ico',tag:d.tag||'sb',data:{url:d.url||'/'},actions:[{action:'view',title:'View Pipeline'},{action:'dismiss',title:'Dismiss'}]}));});
self.addEventListener('notificationclick',function(e){e.notification.close();if(e.action==='dismiss')return;var url=(e.notification.data&&e.notification.data.url)||'/';e.waitUntil(clients.matchAll({type:'window'}).then(function(cs){for(var i=0;i<cs.length;i++){if(cs[i].url.includes(self.location.origin)){cs[i].focus();return;}}return clients.openWindow(url);}));});"""
    if p.exists():
        content = p.read_text()
    else:
        content = sw_content
    return Response(content=content, media_type="application/javascript",
                    headers={"Service-Worker-Allowed": "/"})

# ── GDPR ─────────────────────────────────────────────────────

@app.get("/api/analytics")
async def analytics(user: User = Depends(_get_user),
                     db: Session = Depends(get_db)):
    """
    Product analytics — funnel metrics for the platform.
    Registration → profile → match → pipeline → submission → win.
    """
    from sqlalchemy import func

    total_users = db.query(User).count()
    users_with_gpa = db.query(User).filter(User.gpa > 0).count()
    users_with_skills = db.query(User).filter(
        User.skills != None, User.skills != "[]"
    ).count()

    total_apps = db.query(Application).count()
    submitted = db.query(Application).filter(
        Application.stage == "submitted"
    ).count()
    won = db.query(Application).filter(
        Application.stage == "won"
    ).count()
    total_won_usd = db.query(
        func.sum(Application.amount_usd)
    ).filter(Application.stage == "won").scalar() or 0

    total_packages = db.query(Package).count()
    users_with_packages = db.query(
        func.count(func.distinct(Package.user_id))
    ).scalar() or 0

    # Event funnel
    views = db.query(UserEvent).filter(
        UserEvent.event_type == "view"
    ).count()
    pipeline_adds = db.query(UserEvent).filter(
        UserEvent.event_type == "pipeline_add"
    ).count()
    submissions = db.query(UserEvent).filter(
        UserEvent.event_type == "submitted"
    ).count()
    wins = db.query(UserEvent).filter(
        UserEvent.event_type == "won"
    ).count()

    # Top scholarships by pipeline additions
    top_opps = db.query(
        UserEvent.opp_name,
        func.count(UserEvent.id).label("count")
    ).filter(
        UserEvent.event_type == "pipeline_add",
        UserEvent.opp_name != None,
    ).group_by(UserEvent.opp_name).order_by(
        func.count(UserEvent.id).desc()
    ).limit(10).all()

    return {
        "users": {
            "total": total_users,
            "profile_complete_pct": round(users_with_gpa / max(total_users, 1) * 100, 1),
            "with_skills_pct": round(users_with_skills / max(total_users, 1) * 100, 1),
        },
        "funnel": {
            "registered": total_users,
            "viewed_scholarship": views,
            "added_to_pipeline": pipeline_adds,
            "submitted": submissions,
            "won": wins,
            "view_to_pipeline_pct": round(pipeline_adds / max(views, 1) * 100, 1),
            "pipeline_to_submit_pct": round(submissions / max(pipeline_adds, 1) * 100, 1),
            "submit_to_win_pct": round(wins / max(submissions, 1) * 100, 1),
        },
        "packages": {
            "total_generated": total_packages,
            "users_with_packages": users_with_packages,
        },
        "outcomes": {
            "total_applications": total_apps,
            "submitted": submitted,
            "won": won,
            "total_won_usd": round(total_won_usd, 2),
            "win_rate_pct": round(won / max(submitted, 1) * 100, 1),
        },
        "top_scholarships": [
            {"name": row.opp_name, "pipeline_additions": row.count}
            for row in top_opps
        ],
    }


@app.get("/api/wins")
async def wins_feed(db: Session = Depends(get_db)):
    """
    T2: Social proof — anonymised recent wins to show on homepage.
    Shows first name + country + scholarship name + amount.
    No email, no surname, no identifiable data.
    """
    recent_wins = db.query(Application).filter(
        Application.stage == "won",
        Application.amount_usd > 0,
    ).order_by(Application.outcome_date.desc()).limit(20).all()

    if not recent_wins:
        # Seed with illustrative examples if no real data yet
        return {"wins": [
            {"name": "Amara O.", "country": "Nigeria", "scholarship": "Chevening Scholarship", "amount_usd": 45000},
            {"name": "Kenji M.", "country": "Kenya", "scholarship": "Gates Cambridge Scholarship", "amount_usd": 60000},
            {"name": "Priya S.", "country": "India", "scholarship": "Commonwealth Scholarship", "amount_usd": 25000},
            {"name": "Fatima B.", "country": "Senegal", "scholarship": "DAAD Scholarship", "amount_usd": 18000},
            {"name": "David A.", "country": "Ghana", "scholarship": "Fulbright Scholarship", "amount_usd": 35000},
        ], "total_awarded_usd": 183000, "source": "illustrative"}

    wins_data = []
    total = 0
    for w in recent_wins:
        # Get anonymised user info
        u = db.query(User).filter(User.id == w.user_id).first()
        if not u: continue
        first = (u.name or "").split()[0] if u.name else "Scholar"
        initial = (u.name or " ")[-1].upper() if u.name else "."
        wins_data.append({
            "name": f"{first} {initial}.",
            "country": u.nationality or "International",
            "scholarship": w.scholarship_name,
            "amount_usd": w.amount_usd,
            "won_at": w.outcome_date.isoformat() if w.outcome_date else None,
        })
        total += w.amount_usd or 0

    return {
        "wins": wins_data,
        "total_awarded_usd": round(total),
        "source": "real",
    }

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

# ── University Partnerships ───────────────────────────────────
@app.post("/api/institutions")
async def create_institution(req: dict, db: Session = Depends(get_db)):
    """
    T1: Register a university or organisation as a ScholarBot partner.
    Students with matching email domain are automatically linked.
    """
    name   = req.get("name","").strip()
    domain = req.get("domain","").strip().lower().lstrip("@")
    email  = req.get("admin_email","").strip()
    if not name or not domain or not email:
        raise HTTPException(400, "name, domain, and admin_email are required")
    if db.query(Institution).filter(Institution.domain == domain).first():
        raise HTTPException(400, f"Domain @{domain} is already registered")
    inst = Institution(
        id=f"inst_{uuid.uuid4().hex[:8]}",
        name=name, domain=domain, admin_email=email,
    )
    db.add(inst); db.commit(); db.refresh(inst)
    # Count existing users with this domain
    count = db.query(User).filter(User.email.like(f"%@{domain}")).count()
    inst.student_count = count
    db.commit()
    return {**inst.to_dict(),
            "message": f"Partnership created. {count} existing students with @{domain} linked."}


@app.get("/api/institutions/{domain}/dashboard")
async def institution_dashboard(domain: str, db: Session = Depends(get_db)):
    """
    T1: Aggregate dashboard for a university — see how their students are doing.
    No individual PII exposed — aggregate stats only.
    """
    inst = db.query(Institution).filter(Institution.domain == domain).first()
    if not inst or not inst.active:
        raise HTTPException(404, "Institution not found")

    # Find all students with this email domain
    students = db.query(User).filter(User.email.like(f"%@{domain}")).all()
    student_ids = [s.id for s in students]

    if not student_ids:
        return {**inst.to_dict(), "students": 0, "stats": {}}

    # Aggregate stats — no individual data exposed
    apps = db.query(Application).filter(
        Application.user_id.in_(student_ids)
    ).all()
    won = [a for a in apps if a.stage == "won"]
    submitted = [a for a in apps if a.stage == "submitted"]

    # Degree level breakdown
    from collections import Counter
    degree_dist = dict(Counter(s.degree_level for s in students))
    nationality_dist = dict(Counter(s.nationality for s in students).most_common(10))
    avg_gpa = round(sum(s.gpa for s in students if s.gpa) / max(len([s for s in students if s.gpa]), 1), 2)

    # Update student count
    inst.student_count = len(students)
    db.commit()

    return {
        **inst.to_dict(),
        "students": len(students),
        "avg_gpa": avg_gpa,
        "degree_distribution": degree_dist,
        "top_nationalities": nationality_dist,
        "applications": {
            "total": len(apps),
            "submitted": len(submitted),
            "won": len(won),
            "total_won_usd": sum(a.amount_usd for a in won),
            "win_rate_pct": round(len(won) / max(len(submitted), 1) * 100, 1),
        },
    }


@app.get("/api/institutions")
async def list_institutions(db: Session = Depends(get_db)):
    """List all active partner institutions."""
    insts = db.query(Institution).filter(Institution.active == True).all()
    return {"institutions": [i.to_dict() for i in insts], "total": len(insts)}


# ── A/B Testing Framework ─────────────────────────────────────
import hashlib as _abhl

# Active experiments — add new ones here
ACTIVE_EXPERIMENTS = {
    "essay_model": {
        "variants": ["haiku", "sonnet"],
        "weights": [0.7, 0.3],   # 70% haiku, 30% sonnet
        "description": "Test Claude Haiku vs Sonnet for essay quality",
        "conversion_event": "essay_helpfulness_5",
    },
    "match_algorithm": {
        "variants": ["weighted", "collaborative"],
        "weights": [0.5, 0.5],
        "description": "Compare static vs collaborative filtering",
        "conversion_event": "pipeline_add",
    },
}


def _get_variant(experiment_name: str, user_id: str) -> str:
    """
    Deterministic assignment — same user always gets same variant.
    Uses hash so no DB lookup needed for assignment.
    """
    exp = ACTIVE_EXPERIMENTS.get(experiment_name)
    if not exp: return "control"
    key = f"{experiment_name}:{user_id}"
    bucket = int(_abhl.md5(key.encode()).hexdigest(), 16) % 100
    cumulative = 0
    for variant, weight in zip(exp["variants"], exp["weights"]):
        cumulative += weight * 100
        if bucket < cumulative:
            return variant
    return exp["variants"][-1]


def _record_experiment(db, experiment: str, user_id: str,
                        converted: bool = False, event: str = None):
    """Record experiment exposure or conversion."""
    variant = _get_variant(experiment, user_id)
    existing = db.query(Experiment).filter(
        Experiment.name == experiment,
        Experiment.user_id == user_id,
    ).first()
    if existing:
        if converted:
            existing.converted = True
            existing.conversion_event = event
            db.commit()
        return variant
    rec = Experiment(
        id=f"exp_{uuid.uuid4().hex[:8]}",
        name=experiment, variant=variant,
        user_id=user_id, converted=converted,
        conversion_event=event,
    )
    db.add(rec); db.commit()
    return variant


@app.get("/api/experiments/{name}/results")
async def experiment_results(name: str, db: Session = Depends(get_db)):
    """T2: Get A/B test results for an experiment."""
    exp = ACTIVE_EXPERIMENTS.get(name)
    if not exp:
        raise HTTPException(404, f"Experiment '{name}' not found")
    rows = db.query(Experiment).filter(Experiment.name == name).all()
    from collections import defaultdict
    stats: dict = defaultdict(lambda: {"exposures":0,"conversions":0})
    for r in rows:
        stats[r.variant]["exposures"] += 1
        if r.converted:
            stats[r.variant]["conversions"] += 1
    results = {}
    for variant, s in stats.items():
        exp_count = max(s["exposures"], 1)
        results[variant] = {
            "exposures": s["exposures"],
            "conversions": s["conversions"],
            "conversion_rate_pct": round(s["conversions"] / exp_count * 100, 1),
        }
    return {
        "experiment": name,
        "description": exp["description"],
        "conversion_event": exp["conversion_event"],
        "variants": results,
        "total_exposures": sum(s["exposures"] for s in stats.values()),
    }


@app.get("/api/experiments")
async def list_experiments():
    """T2: List all active experiments."""
    return {"experiments": [
        {"name": k, "description": v["description"],
         "variants": v["variants"], "conversion_event": v["conversion_event"]}
        for k,v in ACTIVE_EXPERIMENTS.items()
    ]}


# ── Human Expert Review ───────────────────────────────────────
@app.post("/api/expert-review/request")
async def request_expert_review(
    req: dict,
    user: User = Depends(_get_user),
    db: Session = Depends(get_db),
):
    """
    T3: Submit essay for human expert review ($19/review).
    Expert reviews go into a queue and are processed within 48 hours.
    """
    essay = req.get("essay","").strip()
    if len(essay.split()) < 100:
        raise HTTPException(400, "Essay must be at least 100 words for expert review")

    # Check if user already has a pending review for this essay
    existing = db.query(ExpertReview).filter(
        ExpertReview.user_id == user.id,
        ExpertReview.status == "pending",
    ).count()
    if existing >= 3:
        raise HTTPException(400, "Maximum 3 pending reviews at a time")

    review = ExpertReview(
        id=f"rev_{uuid.uuid4().hex[:8]}",
        user_id=user.id,
        package_id=req.get("package_id"),
        scholarship_name=req.get("scholarship_name",""),
        essay_text=essay,
        rubric=req.get("rubric","general"),
        status="pending",
    )
    db.add(review); db.commit(); db.refresh(review)
    _log_event(db, user.id, "expert_review_requested",
               req.get("package_id"), req.get("scholarship_name"))
    return {
        **review.to_dict(),
        "message": "Review request submitted. An expert will review your essay within 48 hours.",
        "estimated_turnaround": "24-48 hours",
    }


@app.get("/api/expert-review/my-reviews")
async def my_expert_reviews(user: User = Depends(_get_user),
                              db: Session = Depends(get_db)):
    """Get all expert reviews for the current user."""
    reviews = db.query(ExpertReview).filter(
        ExpertReview.user_id == user.id
    ).order_by(ExpertReview.requested_at.desc()).all()
    return {
        "reviews": [r.to_dict() for r in reviews],
        "pending": sum(1 for r in reviews if r.status == "pending"),
        "completed": sum(1 for r in reviews if r.status == "completed"),
    }


@app.get("/api/expert-review/queue")
async def expert_review_queue(db: Session = Depends(get_db)):
    """
    Expert reviewer endpoint — see the queue of pending reviews.
    In production, restrict to expert role. Currently open for MVP.
    """
    pending = db.query(ExpertReview).filter(
        ExpertReview.status.in_(["pending","in_review"])
    ).order_by(ExpertReview.requested_at.asc()).all()
    return {
        "queue": [r.to_dict() for r in pending],
        "total_pending": len(pending),
    }


@app.patch("/api/expert-review/{review_id}/complete")
async def complete_expert_review(
    review_id: str,
    req: dict,
    db: Session = Depends(get_db),
):
    """Expert submits their review."""
    review = db.query(ExpertReview).filter(ExpertReview.id == review_id).first()
    if not review:
        raise HTTPException(404, "Review not found")
    review.status = "completed"
    review.score = float(req.get("score", 0.7))
    review.grade = req.get("grade","B")
    review.feedback = _sanitise(req.get("feedback",""), 3000)
    review.reviewer_notes = _sanitise(req.get("reviewer_notes",""), 1000)
    review.completed_at = datetime.utcnow()
    db.commit()
    return review.to_dict()


# ── Plan-based rate limits ────────────────────────────────────
PLAN_LIMITS = {
    "free":       {"essays_per_day": 3,  "packages_per_day": 1, "reviews_per_month": 0},
    "pro":        {"essays_per_day": 20, "packages_per_day": 5, "reviews_per_month": 3},
    "enterprise": {"essays_per_day": -1, "packages_per_day": -1, "reviews_per_month": -1},
    "partner":    {"essays_per_day": 10, "packages_per_day": 3, "reviews_per_month": 1},
}


@app.get("/api/plans")
async def get_plans():
    """T4: Available subscription plans."""
    return {
        "plans": [
            {"id":"free",       "name":"Free",       "price_usd":0,
             "essays_per_day":3,  "packages_per_day":1,
             "features":["3 essays/day","1 package/day","87 scholarships","Interview coaching"]},
            {"id":"pro",        "name":"Pro",        "price_usd":9,
             "essays_per_day":20, "packages_per_day":5,
             "features":["20 essays/day","5 packages/day","Priority matching",
                         "Expert review credits","Advanced analytics"]},
            {"id":"enterprise", "name":"Enterprise", "price_usd":49,
             "essays_per_day":-1, "packages_per_day":-1,
             "features":["Unlimited essays","Unlimited packages","University dashboard",
                         "API access","SIS integration","Dedicated support"]},
        ]
    }


@app.get("/api/my-plan")
async def my_plan(user: User = Depends(_get_user), db: Session = Depends(get_db)):
    """T4: Current user's plan and usage."""
    plan = user.plan or "free"
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    # Count today's usage from events
    from datetime import date
    today_start = datetime.combine(date.today(), datetime.min.time())
    essays_today = db.query(UserEvent).filter(
        UserEvent.user_id == user.id,
        UserEvent.event_type == "essay_critique",
        UserEvent.created_at >= today_start,
    ).count()
    packages_today = db.query(UserEvent).filter(
        UserEvent.user_id == user.id,
        UserEvent.event_type == "pipeline_add",
        UserEvent.created_at >= today_start,
    ).count()
    return {
        "plan": plan,
        "limits": limits,
        "usage_today": {
            "essays": essays_today,
            "packages": packages_today,
        },
        "upgrade_url": "https://scholarbot-web.onrender.com/?page=plans",
    }


# ── Developer API Keys ────────────────────────────────────────
@app.post("/api/developer/keys")
async def create_api_key(req: dict, user: User = Depends(_get_user),
                          db: Session = Depends(get_db)):
    """T1: Generate a developer API key for programmatic access."""
    import secrets as _sec3, hashlib as _hl5
    existing = db.query(ApiKey).filter(
        ApiKey.user_id == user.id, ApiKey.active == True
    ).count()
    if existing >= 5:
        raise HTTPException(400, "Maximum 5 active API keys per account")
    raw = f"sb_{_sec3.token_urlsafe(32)}"
    key_hash = _hl5.sha256(raw.encode()).hexdigest()
    key = ApiKey(
        id=f"ak_{uuid.uuid4().hex[:8]}",
        user_id=user.id, key_hash=key_hash,
        key_prefix=raw[:8],
        name=req.get("name","My API Key"),
        plan=user.plan or "free",
    )
    db.add(key); db.commit(); db.refresh(key)
    return {**key.to_dict(), "key": raw,
            "warning": "Save this key — it will not be shown again"}


@app.get("/api/developer/keys")
async def list_api_keys(user: User = Depends(_get_user),
                         db: Session = Depends(get_db)):
    """List all developer API keys for the current user."""
    keys = db.query(ApiKey).filter(ApiKey.user_id == user.id).all()
    return {"keys": [k.to_dict() for k in keys]}


@app.delete("/api/developer/keys/{key_id}")
async def revoke_api_key(key_id: str, user: User = Depends(_get_user),
                          db: Session = Depends(get_db)):
    """Revoke a developer API key."""
    key = db.query(ApiKey).filter(
        ApiKey.id == key_id, ApiKey.user_id == user.id
    ).first()
    if not key: raise HTTPException(404, "Key not found")
    key.active = False
    db.commit()
    return {"message": "API key revoked"}


@app.get("/api/developer/docs")
async def api_docs():
    """T1: Developer documentation — how to use the ScholarBot API."""
    return {
        "base_url": "https://scholarbot-web.onrender.com",
        "authentication": {
            "method": "Bearer token or API key",
            "header": "Authorization: Bearer <your_key>",
            "note": "API keys from /api/developer/keys work the same as JWT tokens",
        },
        "rate_limits": {
            "free": "200 requests/hour",
            "pro": "2000 requests/hour",
            "enterprise": "Unlimited",
        },
        "endpoints": {
            "scholarships": "GET /api/scholarships — list all scholarships",
            "match":        "GET /api/scholarships/matched — personalised matches",
            "explain":      "GET /api/scholarships/{id}/explain — match explanation",
            "gpa_detect":   "POST /api/gpa/detect — normalise any GPA scale",
            "critique":     "POST /api/essays/critique — rubric-aware essay critique",
            "analytics":    "GET /api/analytics — platform funnel metrics",
        },
        "example": {
            "curl": "curl -H 'Authorization: Bearer sb_...' https://scholarbot-web.onrender.com/api/scholarships/matched"
        }
    }


# ── Outcome Prediction ────────────────────────────────────────
@app.get("/api/scholarships/{sid}/predict")
async def predict_outcome(
    sid: str,
    user: User = Depends(_get_user),
    db: Session = Depends(get_db),
):
    """
    T5: Outcome prediction using real behavioral event data.
    Logistic approximation with 6 features:
    1. Profile match score (0-1)
    2. GPA percentile among matched users
    3. Whether user has submitted previously (experience signal)
    4. Days until deadline (urgency)
    5. Scholarship win rate from events (collaborative signal)
    6. User engagement score (views → adds → submissions)
    """
    from engine.opportunity_db import load_all_opportunities
    all_opps = load_all_opportunities() + EXTRA_OPPORTUNITIES
    opp = next((o for o in all_opps if o["id"] == sid), None)
    if not opp:
        raise HTTPException(404, "Scholarship not found")

    profile = user.to_dict()
    # Feature 1: match score
    matches = _match_opps(profile)
    match_score = next((m.get("match_score",0.5) for m in matches
                        if m.get("id") == sid), 0.5)

    # Feature 2: GPA relative to minimum
    gpa_user = float(profile.get("gpa") or 0)
    gpa_min  = float(opp.get("gpa_min") or 0)
    gpa_feat = min(1.0, (gpa_user - gpa_min + 0.5) / 1.5) if gpa_min else 0.7

    # Feature 3: User experience (previous submissions)
    prev_subs = db.query(UserEvent).filter(
        UserEvent.user_id == user.id,
        UserEvent.event_type == "submitted",
    ).count()
    exp_feat = min(1.0, prev_subs / 5.0)

    # Feature 4: Deadline urgency (sooner = more motivated applicants)
    days = _days_until(opp.get("deadline",""))
    urgency_feat = 1.0 if days and days < 30 else 0.7 if days and days < 90 else 0.5

    # Feature 5: Collaborative win signal — how often this opp leads to wins
    win_events = db.query(UserEvent).filter(
        UserEvent.event_type == "won",
        UserEvent.opp_id == sid,
    ).count()
    add_events = db.query(UserEvent).filter(
        UserEvent.event_type == "pipeline_add",
        UserEvent.opp_id == sid,
    ).count()
    collab_feat = min(1.0, (win_events * 3 + 1) / (add_events + 5))

    # Feature 6: Engagement (has user viewed + added this opp?)
    user_viewed = db.query(UserEvent).filter(
        UserEvent.user_id == user.id,
        UserEvent.event_type == "view",
        UserEvent.opp_id == sid,
    ).count()
    engagement_feat = min(1.0, user_viewed * 0.3 + (1 if match_score > 0.7 else 0) * 0.7)

    # Logistic combination with weights
    features = [
        (match_score,     0.35),
        (gpa_feat,        0.20),
        (exp_feat,        0.15),
        (urgency_feat,    0.10),
        (collab_feat,     0.10),
        (engagement_feat, 0.10),
    ]
    raw_score = sum(f * w for f, w in features)

    # Apply acceptance rate as prior
    acceptance = float((opp.get("competitiveness") or {}).get("acceptance_rate") or 0.1)
    final_prob = round(raw_score * acceptance * 5, 3)
    final_prob = min(0.95, max(0.01, final_prob))

    grade = "A" if final_prob >= 0.4 else "B" if final_prob >= 0.25 else "C" if final_prob >= 0.1 else "D"
    recommendation = (
        "Strong profile for this scholarship — apply immediately." if final_prob >= 0.4 else
        "Good chance — invest in essay quality to improve odds." if final_prob >= 0.25 else
        "Moderate chance — focus on matching requirements before applying." if final_prob >= 0.1 else
        "Low probability — consider higher-match scholarships first."
    )

    return {
        "scholarship_id": sid,
        "scholarship_name": opp.get("name",""),
        "win_probability": final_prob,
        "win_probability_pct": f"{final_prob*100:.1f}%",
        "grade": grade,
        "recommendation": recommendation,
        "features": {
            "profile_match": round(match_score, 3),
            "gpa_strength": round(gpa_feat, 3),
            "experience": round(exp_feat, 3),
            "deadline_urgency": round(urgency_feat, 3),
            "collaborative_signal": round(collab_feat, 3),
            "engagement": round(engagement_feat, 3),
        },
        "acceptance_rate": acceptance,
        "data_points": win_events + add_events,
        "note": "Prediction improves as more users apply and report outcomes.",
    }


# ── Stripe Payment Integration (stub — ready for STRIPE_SECRET_KEY) ──
@app.post("/api/payments/create-checkout")
async def create_checkout(req: dict, user: User = Depends(_get_user)):
    """
    Create a Stripe checkout session for plan upgrade.
    Set STRIPE_SECRET_KEY in Render environment to activate.
    """
    plan = req.get("plan","pro")
    price_map = {"pro": "price_pro_monthly", "enterprise": "price_enterprise_monthly"}
    stripe_key = os.environ.get("STRIPE_SECRET_KEY","")
    if not stripe_key:
        raise HTTPException(503,
            "Payment processing not yet configured. "
            "Contact support@scholarbot.app to upgrade.")
    try:
        import stripe as _stripe
        _stripe.api_key = stripe_key
        base = os.environ.get("BASE_URL","https://scholarbot-web.onrender.com")
        session = _stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_map.get(plan,"price_pro_monthly"), "quantity":1}],
            mode="subscription",
            success_url=f"{base}/?payment=success&plan={plan}",
            cancel_url=f"{base}/?page=plans",
            client_reference_id=user.id,
            customer_email=user.email,
            metadata={"user_id": user.id, "plan": plan},
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except Exception as e:
        raise HTTPException(500, f"Payment error: {str(e)[:200]}")


@app.post("/api/payments/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhook events — activates plan on successful payment."""
    stripe_key = os.environ.get("STRIPE_SECRET_KEY","")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET","")
    if not stripe_key:
        raise HTTPException(503, "Stripe not configured")
    payload = await request.body()
    sig = request.headers.get("stripe-signature","")
    try:
        import stripe as _stripe
        _stripe.api_key = stripe_key
        event = _stripe.Webhook.construct_event(payload, sig, webhook_secret)
        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            user_id = session.get("client_reference_id")
            plan = session.get("metadata",{}).get("plan","pro")
            if user_id:
                u = db.query(User).filter(User.id == user_id).first()
                if u:
                    u.plan = plan
                    db.commit()
                    logger.info("Plan upgraded: %s → %s", user_id, plan)
        return {"received": True}
    except Exception as e:
        raise HTTPException(400, f"Webhook error: {str(e)}")


# ── Internationalisation ──────────────────────────────────────
_TRANSLATIONS = {
    "en": {
        "welcome": "Welcome to ScholarBot",
        "find_scholarships": "Find Scholarships",
        "generate_essay": "Generate Essay",
        "add_to_pipeline": "Add to Pipeline",
        "match_score": "Match Score",
        "apply_now": "Apply Now",
        "why_match": "Why this match?",
        "deadline": "Deadline",
        "award": "Award",
        "sign_in": "Sign In",
        "create_account": "Create Account",
        "forgot_password": "Forgot your password?",
    },
    "fr": {
        "welcome": "Bienvenue sur ScholarBot",
        "find_scholarships": "Trouver des bourses",
        "generate_essay": "Générer une lettre",
        "add_to_pipeline": "Ajouter au suivi",
        "match_score": "Score de correspondance",
        "apply_now": "Postuler maintenant",
        "why_match": "Pourquoi cette bourse?",
        "deadline": "Date limite",
        "award": "Montant",
        "sign_in": "Se connecter",
        "create_account": "Créer un compte",
        "forgot_password": "Mot de passe oublié?",
    },
    "sw": {
        "welcome": "Karibu ScholarBot",
        "find_scholarships": "Tafuta Scholarships",
        "generate_essay": "Andika Insha",
        "add_to_pipeline": "Ongeza kwenye orodha",
        "match_score": "Alama ya mechi",
        "apply_now": "Omba sasa",
        "why_match": "Kwa nini mechi hii?",
        "deadline": "Tarehe ya mwisho",
        "award": "Thamani",
        "sign_in": "Ingia",
        "create_account": "Fungua akaunti",
        "forgot_password": "Umesahau nywila?",
    },
    "pt": {
        "welcome": "Bem-vindo ao ScholarBot",
        "find_scholarships": "Encontrar bolsas",
        "generate_essay": "Gerar redação",
        "add_to_pipeline": "Adicionar ao pipeline",
        "match_score": "Pontuação de correspondência",
        "apply_now": "Candidatar-se agora",
        "why_match": "Por que esta bolsa?",
        "deadline": "Prazo",
        "award": "Valor",
        "sign_in": "Entrar",
        "create_account": "Criar conta",
        "forgot_password": "Esqueceu sua senha?",
    },
}


@app.get("/api/i18n/{locale}")
async def get_translations(locale: str):
    """
    T4: Return UI translations for the requested locale.
    Frontend calls this on load to get localised labels.
    Falls back to English for unsupported locales.
    """
    lang = locale.split("-")[0].lower()   # 'fr-FR' → 'fr'
    translations = _TRANSLATIONS.get(lang, _TRANSLATIONS["en"])
    return {
        "locale": lang,
        "supported": list(_TRANSLATIONS.keys()),
        "translations": translations,
        "is_fallback": lang not in _TRANSLATIONS,
    }


@app.get("/api/i18n")
async def list_locales():
    """List all supported locales."""
    return {
        "supported": [
            {"code": "en", "name": "English", "flag": "🇬🇧"},
            {"code": "fr", "name": "Français", "flag": "🇫🇷"},
            {"code": "sw", "name": "Kiswahili", "flag": "🇰🇪"},
            {"code": "pt", "name": "Português", "flag": "🇧🇷"},
        ]
    }

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

# Rubric weights per scholarship type — used in essay prompt
_ESSAY_RUBRICS = {
    "chevening":       ["leadership and influence","networking ability","ambassador potential","clear career plan"],
    "fulbright":       ["academic excellence","research project quality","cross-cultural understanding","long-term impact"],
    "gates_cambridge": ["outstanding intellectual ability","leadership potential","commitment to improving lives","good fit with Cambridge"],
    "rhodes":          ["literary and scholastic attainments","energy and fondness for outdoor pursuits","truth and courage","devotion to duty","sympathy for the weak","kindliness","unselfishness","fellowship","moral force of character"],
    "general":         ["clarity and structure","specific evidence and examples","relevance to scholarship mission","potential impact"],
}


def _build_essay_prompt(opp: dict, profile: dict) -> str:
    """Build a rubric-aware, highly personalised essay prompt."""
    name    = opp.get("name","this scholarship")
    org     = opp.get("organisation","the awarding body")
    mission = opp.get("description","")
    amount  = opp.get("amount_usd", 0)
    field   = opp.get("field","")
    tags    = ", ".join(opp.get("tags",[]))
    prompt_hint = opp.get("essay_prompt","")

    # Select rubric
    slug = opp.get("id","").lower().replace("-","_").replace(" ","_")
    rubric = (_ESSAY_RUBRICS.get(slug)
              or _ESSAY_RUBRICS.get(next((k for k in _ESSAY_RUBRICS if k in slug), "general")))
    rubric_str = "; ".join(rubric)

    # Profile facts
    p_name   = _sanitise(profile.get("name","the applicant"), 60)
    p_deg    = profile.get("degree_level","Graduate")
    p_major  = profile.get("major","")
    p_school = profile.get("school","")
    p_nat    = profile.get("nationality","")
    p_gpa    = profile.get("gpa", 0)
    p_skills = ", ".join((profile.get("skills") or [])[:6])
    p_extras = ", ".join((profile.get("extracurriculars") or [])[:4])
    p_stmt   = _sanitise(profile.get("personal_statement",""), 400)

    return f"""Write a compelling 600-word scholarship application essay for {p_name}.

SCHOLARSHIP: {name}
ORGANISATION: {org}
AWARD: ${amount:,.0f}
FIELD: {field}
TAGS: {tags}
MISSION: {mission}
ESSAY PROMPT: {prompt_hint or "Why do you deserve this scholarship and how will it help you achieve your goals?"}

EVALUATION RUBRIC (panels score these dimensions — address ALL of them):
{rubric_str}

APPLICANT PROFILE:
- Name: {p_name}
- Degree: {p_deg} in {p_major} at {p_school}
- Nationality: {p_nat}
- GPA: {p_gpa:.1f}/4.0
- Key skills: {p_skills}
- Activities: {p_extras}
- Personal statement: {p_stmt}

WRITING REQUIREMENTS:
1. Open with a specific, vivid scene or moment — not a generic statement
2. Address every rubric dimension with concrete evidence from the profile
3. Include at least two specific numbers, dates, or measurable outcomes
4. End with a clear statement of how this scholarship enables a specific future contribution
5. Tone: confident, authentic, first person
6. Length: 550-650 words

Write only the essay. No headings, no meta-commentary."""


def _essay_job(jid, opp, profile):
    try:
        llm = _llm()
        system = ("You are an expert scholarship essay writer. "
                  "Write essays that are personal, specific, and directly address "
                  "the scholarship's evaluation criteria. Never use generic filler.")
        prompt = _build_essay_prompt(opp, profile)
        essay = llm(system, prompt)
        word_count = len(essay.split())
        db = SessionLocal()
        # Save to Package table for version history
        try:
            existing = db.query(Package).filter(
                Package.user_id == profile.get("id",""),
                Package.opportunity_id == opp.get("id",""),
            ).order_by(Package.created_at.desc()).first()
            version = 1
            if existing: version = 2  # increment for UI
            pkg = Package(
                id=f"pkg_{uuid.uuid4().hex[:8]}",
                user_id=profile.get("id",""),
                opportunity_id=opp.get("id",""),
                scholarship_name=opp.get("name",""),
                amount_usd=float(opp.get("amount_usd",0)),
                deadline=opp.get("deadline",""),
                days_left=_days_until(opp.get("deadline","")),
                url=opp.get("url",""),
                essay_text=essay,
                briefing_html=f"<h2>{opp.get('name','')}</h2><p>{opp.get('description','')}</p>",
            )
            db.add(pkg); db.commit()
        finally:
            db.close()
        _update_job(jid, "done", result={
            "essay": essay, "word_count": word_count, "version": version
        })
    except Exception as e:
        _update_job(jid, "failed", error=str(e)[:500])

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
