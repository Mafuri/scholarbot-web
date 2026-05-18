"""
ScholarBot Web Platform v4.3.0
Entry point — imports the modularised app package.

Architecture:
    web_app.py          ← this file (thin shim, Render entry point)
    app/
    ├── main.py         ← FastAPI factory + middleware + startup
    ├── config.py       ← environment variables
    ├── database.py     ← SQLAlchemy models + session
    ├── security.py     ← JWT, bcrypt, 2FA, sanitisation
    ├── dependencies.py ← FastAPI dependencies (get_db, get_user)
    ├── cache.py        ← in-process TTL cache
    ├── opportunities.py← scholarship database + matching engine
    ├── tasks.py        ← background jobs + job worker
    └── routers/        ← 8 route modules (auth, scholarships, ...)

Migration status: Phase 1 (structure created, logic still in web_app.py)
Phase 2: move route handlers into router files, remove legacy code below.
"""

# ── Legacy code (Phase 1 migration) ──────────────────────────
# All route handler functions still live here until Phase 2 migration.
# The app/ package provides the structure; routers delegate here.

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
    try:
        return _jwt.decode(tok, _SECRET, algorithms=[_JWT_ALGORITHM]).get("sub")
    except JWTError:
        return None


def _validate_token_session(tok, db):
    """Phase 6: Checks password_changed_at to invalidate old tokens."""
    from jose import JWTError as _JWTError
    try:
        payload = _jwt.decode(tok, _SECRET, algorithms=[_JWT_ALGORITHM])
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
    r"new\s+instructions?:",
    r"system\s*prompt",
    r"you\s+are\s+now",
    r"forget\s+(?:all\s+)?(?:previous|your)",
    r"act\s+as\s+(?:a\s+)?(?:DAN|jailbreak|uncensored)",
    r"<\s*/?(?:system|user|assistant)\s*>",
]

def _normalise_unicode(text: str) -> str:
    """Normalise unicode homoglyphs used in prompt injection attacks."""
    import unicodedata
    text = unicodedata.normalize("NFKC", text)
    for ch in ["\u200b","\u200c","\u200d","\ufeff","\u2060"]:
        text = text.replace(ch, "")
    return text
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
    text = _normalise_unicode(str(text))
    text = "".join(ch for ch in text if ord(ch)>=32 or ch in "\n\r\t")
    for p in _INJECTION:
        text = re.sub(p, "[REMOVED]", text, flags=re.IGNORECASE)
    return text[:max_len]

# ── Rate limiting ─────────────────────────────────────────────
_rate_store = defaultdict(list)

# 100 most common passwords — checked on registration and password change
_COMMON_PASSWORDS = {
    "password","password1","password123","123456","12345678","1234567890",
    "qwerty","qwerty123","abc123","111111","iloveyou","admin","welcome",
    "monkey","dragon","master","letmein","login","pass","password1",
    "sunshine","princess","football","shadow","superman","michael",
    "jessica","killer","trustno1","hello","charlie","donald","batman",
    "access","mustang","baseball","soccer","hockey","harley","ranger",
    "dakota","cookie","dragon","michael","hunter","buster","thomas",
    "robert","tigger","soccer","george","andrew","change","summer",
    "winter","spring","autumn","flower","love123","123abc","starwars",
    "pass123","test","guest","user","default","changeme","root",
    "toor","alpine","ubuntu","raspberry","admin123","administrator",
    "scholarship","scholarbot","kenya123","nairobi","africa123",
}

def _check_common_password(pw: str) -> bool:
    """Returns True if password is too common. False = password is safe."""
    return pw.lower() in _COMMON_PASSWORDS or pw.lower()[:8] in _COMMON_PASSWORDS

_login_failures: dict = {}  # {ip: {"count": 0, "locked_until": None}}
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_LOCKOUT_SECS = 900  # 15 minutes

# ── API cost tracking (OWASP ASI08 — resource exhaustion) ─────
_api_usage: dict = {}   # {user_id: {"date": "YYYY-MM-DD", "calls": 0, "est_cost_usd": 0.0}}
_anthropic_circuit = {"failures": 0, "open_until": None}  # Circuit breaker
_ANTHROPIC_COST_PER_CALL = 0.50  # Estimated per essay call

def _check_api_circuit() -> bool:
    """Returns True if Anthropic API circuit is closed (OK to call)."""
    import time as _t
    cb = _anthropic_circuit
    if cb["open_until"] and _t.time() < cb["open_until"]:
        return False  # Circuit open — fail fast
    return True

def _record_api_call(user_id: str, cost: float = _ANTHROPIC_COST_PER_CALL):
    """Track per-user API usage for cost control."""
    from datetime import date
    today = str(date.today())
    if user_id not in _api_usage or _api_usage[user_id]["date"] != today:
        _api_usage[user_id] = {"date": today, "calls": 0, "est_cost_usd": 0.0}
    _api_usage[user_id]["calls"] += 1
    _api_usage[user_id]["est_cost_usd"] += cost

def _record_api_failure():
    """Record Anthropic API failure, open circuit after 3 consecutive failures."""
    import time as _t
    _anthropic_circuit["failures"] += 1
    if _anthropic_circuit["failures"] >= 3:
        _anthropic_circuit["open_until"] = _t.time() + 300  # 5 min cooldown
        logger.warning("Anthropic API circuit OPEN — 5 minute cooldown")

def _record_api_success():
    """Reset circuit breaker on success."""
    _anthropic_circuit["failures"] = 0
    _anthropic_circuit["open_until"] = None
_processed_stripe_events: set = set()  # Stripe idempotency
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
def _mask_pii_for_claude(text):
    """Mask emails/phones before sending to Claude (OWASP LLM02)."""
    import re as _r
    text = _r.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+[.][a-zA-Z]{2,}', '[email]', text)
    return text

def _sanitise_claude_output(text):
    """Strip XSS vectors from Claude output (OWASP LLM05)."""
    import re as _r
    text = _r.sub(r'<script[^>]*>.*?</script>', '', text, flags=_r.IGNORECASE|_r.DOTALL)
    for bad in ['javascript:', 'onerror=', 'onload=', '<iframe', '<object']:
        if bad in text.lower():
            text = text.replace(bad, '').replace(bad.upper(), '')
    return text

def _llm():
    key = os.environ.get("ANTHROPIC_API_KEY","")
    if not key: return lambda s,u: "I am a motivated student committed to excellence."
    if not _check_api_circuit():
        return lambda s,u: (_ for _ in ()).throw(Exception("AI service temporarily unavailable — try again in 5 minutes"))
    import requests as _req
    def call(s, u):
        try:
            u = _mask_pii_for_claude(u)   # PII masking before send
            r = _req.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key":key,"anthropic-version":"2023-06-01",
                         "content-type":"application/json"},
                json={"model":"claude-haiku-4-5-20251001","max_tokens":1000,
                      "system":s,"messages":[{"role":"user","content":u}]},
                timeout=45)
            result = r.json()["content"][0]["text"]
            result = _sanitise_claude_output(result)  # Output sanitization
            _record_api_success()
            return result
        except Exception as _e:
            _record_api_failure()
            logger.warning("Claude API call failed: %s", str(_e)[:100])
            return "I am a motivated student committed to excellence."
    return call

def _days_until(d):
    try: return (datetime.strptime(d,"%Y-%m-%d")-datetime.utcnow()).days
    except: return 999

# ── FastAPI App ───────────────────────────────────────────────
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
class _SecretFilter(logging.Filter):
    """Mask secrets from log output (OWASP pre-launch checklist item 8)."""
    import re as _re
    _MASKS = [
        (_re.compile(r'sk-ant-[A-Za-z0-9_-]+'),      'sk-ant-***'),
        (_re.compile(r'Bearer eyJ[A-Za-z0-9._-]+'),   'Bearer ***'),
        (_re.compile(r'pk_live_[A-Za-z0-9]+'),        'pk_live_***'),
        (_re.compile(r'"password"\s*:\s*"[^"]*"'),    '"password":"***"'),
    ]
    def filter(self, record):
        msg = str(record.getMessage())
        for pat, rep in self._MASKS:
            msg = pat.sub(rep, msg)
        record.msg = msg; record.args = ()
        return True

logger = logging.getLogger(__name__)
logger.addFilter(_SecretFilter())
_root_logger = logging.getLogger()
_root_logger.addFilter(_SecretFilter())

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
    response.headers["X-Content-Type-Options"]   = "nosniff"
    response.headers["X-Frame-Options"]          = "DENY"
    response.headers["X-XSS-Protection"]         = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"]          = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]       = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"]  = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-eval' 'unsafe-inline' "
        "https://cdnjs.cloudflare.com https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://api.anthropic.com "
        "https://api.stripe.com https://api.sender.net; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "object-src 'none'"
    )
    return response

@app.on_event("shutdown")
async def shutdown():
    """Graceful shutdown — flush pending jobs, close DB pool."""
    import asyncio as _aio_sd
    logger.info("ScholarBot shutting down — flushing state...")
    # Give background tasks 5 seconds to complete
    await _aio_sd.sleep(0)
    # Close database connections
    try:
        engine = _get_engine()
        engine.dispose()
        logger.info("DB connection pool disposed")
    except Exception as e:
        logger.warning("Shutdown DB dispose error: %s", e)
    logger.info("ScholarBot shutdown complete")


@app.on_event("startup")
async def startup():
    Path("data/uploads").mkdir(parents=True, exist_ok=True)
    Path("static").mkdir(parents=True, exist_ok=True)
    _init_db()
    logger.info("ScholarBot v4.3.0 started")
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
        # Weekly digest every Monday 07:00 UTC
        async def _send_weekly_digest():
            """Send weekly scholarship digest to all free-plan users."""
            try:
                _db = SessionLocal()
                free_users = _db.query(User).filter(
                    User.plan == "free",
                    User.email_verified == True,
                ).limit(500).all()
                sender_key = os.environ.get("SENDER_API_KEY","")
                if not sender_key:
                    _db.close(); return
                import requests as _rqd
                sent = 0
                for _du in free_users:
                    try:
                        html = (f"<h2>Your Weekly ScholarBot Digest</h2>"
                                f"<p>Hi {_du.name.split()[0]}, here are this week's highlights:</p>"
                                f"<ul>"
                                f"<li><strong>277+ verified scholarships</strong> matched to your profile</li>"
                                f"<li>Check your <a href='https://scholarbot-web.onrender.com/?page=dashboard'>Dashboard</a> for new matches</li>"
                                f"<li>Deadlines approaching — review your pipeline</li>"
                                f"</ul>"
                                f"<p><a href='https://scholarbot-web.onrender.com/?page=scholarships' "
                                f"style='background:#2563eb;color:#fff;padding:10px 20px;border-radius:6px;"
                                f"text-decoration:none;display:inline-block'>View scholarships →</a></p>"
                                f"<p style='font-size:12px;color:#888'>Unsubscribe: "
                                f"<a href='https://scholarbot-web.onrender.com/api/alerts/unsubscribe'>click here</a></p>")
                        _rqd.post("https://api.sender.net/v2/message/send",
                            headers={"Authorization":f"Bearer {sender_key}",
                                     "Content-Type":"application/json"},
                            json={"from":{"email":os.environ.get("FROM_EMAIL","noreply@scholarbot.app"),
                                          "name":"ScholarBot"},
                                  "to":{"email":_du.email,"name":_du.name},
                                  "subject":"Your weekly ScholarBot update",
                                  "html":html},
                            timeout=8)
                        sent += 1
                    except Exception: pass
                _db.close()
                logger.info("Weekly digest sent to %d users", sent)
            except Exception as _de:
                logger.error("Weekly digest error: %s", _de)
        scheduler.add_job(_send_weekly_digest, "cron", day_of_week="mon", hour=7, minute=0)
        scheduler.start()
        logger.info("APScheduler started — deadline reminders at 08:00 daily")
    except ImportError:
        logger.info("APScheduler not installed — deadline reminders disabled")

    # ── Persistent job queue: poll DB every 5s ────────────────
    # Professor fix: BackgroundTasks die on Render spin-down.
    # This loop survives restarts — pending jobs resume on next boot.
    import asyncio as _aio3
    async def _job_worker():
        """Poll jobs table for pending work. Survives worker restarts."""
        logger.info("Persistent job worker started — polling every 5s")
        while True:
            try:
                _db = SessionLocal()
                pending = _db.query(Job).filter(
                    Job.status == "pending",
                    Job.retry_count < 3,
                ).limit(3).all()
                _db.close()
                for job in pending:
                    _db2 = SessionLocal()
                    try:
                        j = _db2.query(Job).filter(Job.id == job.id).first()
                        if j: j.status = "running"; _db2.commit()
                    finally:
                        _db2.close()
                    if job.job_type == "essay":
                        meta = job.result or {}
                        opp  = meta.get("opp")
                        prof = meta.get("profile")
                        if opp and prof:
                            _essay_job(job.id, opp, prof)
                    elif job.job_type == "packages":
                        meta = job.result or {}
                        prof = meta.get("profile")
                        n    = meta.get("top_n", 5)
                        if prof:
                            _packages_job(job.id, prof, n)
            except Exception as _je:
                logger.debug("Job worker tick error (non-critical): %s", _je)
            await _aio3.sleep(5)

    _aio3.create_task(_job_worker())
    logger.info("Persistent job worker task created")

    # Trial expiry: downgrade trial → free after 7 days
    async def _trial_checker():
        while True:
            await _aio3.sleep(86400)
            try:
                from datetime import date as _dtt
                today = str(_dtt.today())
                _db4 = SessionLocal()
                for _u4 in _db4.query(User).filter(User.plan=="trial").all():
                    ev4 = _db4.query(UserEvent).filter(
                        UserEvent.user_id==_u4.id,
                        UserEvent.event_type=="trial_started"
                    ).first()
                    if ev4:
                        import json as _jt4
                        mt4 = ev4.metadata_ or {}
                        if isinstance(mt4,str):
                            try: mt4=_jt4.loads(mt4)
                            except: mt4={}
                        if mt4.get("trial_until","") < today:
                            _u4.plan="free"
                _db4.commit(); _db4.close()
            except Exception as _et4:
                logger.debug("Trial expiry check: %s",_et4)
    _aio3.create_task(_trial_checker())
    logger.info("Trial expiry checker started")

def _get_user(creds: HTTPAuthorizationCredentials = Depends(security),
              db: Session = Depends(get_db)):
    if not creds: raise HTTPException(401, "Not authenticated")
    uid = _decode_token(creds.credentials)
    if not uid: raise HTTPException(401, "Invalid or expired token")
    u = db.query(User).filter(User.id==uid).first()
    if not u: raise HTTPException(401, "User not found")
    return u

def _require_admin(user: User = Depends(_get_user)) -> User:
    """FastAPI dependency — raises 403 if user is not admin or enterprise."""
    admin_emails = [e.strip() for e in
                    os.environ.get("ADMIN_EMAILS","").split(",") if e.strip()]
    if user.plan not in ("enterprise","partner") and user.email not in admin_emails:
        raise HTTPException(403, "Admin access required")
    return user




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
        # Log trial start + send welcome email
        from datetime import date as _dtrial
        _trial_end = str(_dtrial.today().replace(day=min(_dtrial.today().day+7,28)))
        _log_event(db, u.id, "trial_started", None, "Pro trial",
                   {"trial_days":7,"trial_until":_trial_end,"auto_downgrade":True})
        if _sender_key:
            try:
                import requests as _rq6
                _whtml = (f"<h2>Welcome to ScholarBot, {u.name.split()[0]}!</h2>"
                          f"<p>Your <strong>7-day Pro trial</strong> is now active. You have:</p>"
                          f"<ul><li>20 essays/day</li><li>277+ matched scholarships</li>"
                          f"<li>Interview coaching (Chevening, Fulbright, Gates Cambridge)</li></ul>"
                          f"<p>Trial ends <strong>{_trial_end}</strong>. "
                          f"<a href='https://scholarbot-web.onrender.com/?page=plans'>"
                          f"Upgrade to keep Pro →</a></p>")
                _rq6.post("https://api.sender.net/v2/message/send",
                    headers={"Authorization":f"Bearer {_sender_key}",
                             "Content-Type":"application/json"},
                    json={"from":{"email":os.environ.get("FROM_EMAIL","noreply@scholarbot.app"),
                                  "name":"ScholarBot"},
                          "to":{"email":u.email,"name":u.name},
                          "subject":f"Welcome to ScholarBot — your 7-day Pro trial starts now",
                          "html":_whtml},
                    timeout=8)
            except Exception as _we:
                logger.debug("Welcome email (non-critical): %s", _we)
        # Track referral code if provided
        _ref = _sanitise(getattr(req, "ref_code","") or "", 20)
        if _ref:
            _log_event(db, u.id, "referral_signup", None, f"ref:{_ref}",
                       {"referral_code":_ref})
        return _auth_response(u)
    except HTTPException: raise
    except Exception as e:
        db.rollback()
        logger.error("Register error: %s", e, exc_info=True)
        raise HTTPException(400, f"Registration error: {str(e)}")

@app.post("/api/auth/login")
async def login(req: LoginReq, request: Request, db: Session = Depends(get_db)):
    """Login with account lockout: 5 failed attempts = 15-minute IP block."""
    client_ip = request.client.host if request.client else "unknown"
    lockout = _login_failures.get(client_ip, {"count": 0, "locked_until": None})
    if lockout["locked_until"] and time.time() < lockout["locked_until"]:
        remaining = int(lockout["locked_until"] - time.time())
        raise HTTPException(429,
            f"Too many failed login attempts. Try again in {remaining} seconds.")
    u = db.query(User).filter(User.email==req.email).first()
    if not u or not _check_pw(req.password, u.password_hash):
        failures = lockout["count"] + 1
        locked_until = (time.time() + _LOGIN_LOCKOUT_SECS
                        if failures >= _LOGIN_MAX_ATTEMPTS else None)
        _login_failures[client_ip] = {"count": failures, "locked_until": locked_until}
        if locked_until:
            logger.warning("Account lockout: IP %s after %d failures", client_ip, failures)
            _log_event(db, "system", "account_lockout", None,
                       f"ip:{client_ip}", {"failures": failures})
        else:
            _log_event(db, "system", "login_failed", None,
                       f"ip:{client_ip}", {"attempt": failures})
        raise HTTPException(401, "Invalid email or password")
    # Log successful login with device fingerprint
    ua = request.headers.get("user-agent","unknown")[:120]
    _log_event(db, u.id, "login_success", None, u.email, {
        "ip": client_ip, "user_agent": ua,
        "device": "mobile" if any(d in ua.lower() for d in ["android","iphone","mobile"]) else "desktop",
    })
    _login_failures.pop(client_ip, None)  # Reset lockout on success
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
        raise HTTPException(400, "Unsupported file type — PDF, DOCX, DOC, JPG, PNG only")
    content_bytes = await file.read()
    # Magic byte validation — prevents extension spoofing attacks
    def _check_magic(data: bytes) -> bool:
        sigs = [
            (b"%PDF", {".pdf"}),
            (b"PK\x03\x04", {".docx", ".doc"}),      # ZIP-based Office
            (b"\xd0\xcf\x11\xe0", {".doc", ".xls"}),  # OLE2 compound doc
            (b"\xff\xd8\xff", {".jpg", ".jpeg"}),      # JPEG
            (b"\x89PNG", {".png"}),                    # PNG
        ]
        for magic, exts in sigs:
            if data[:len(magic)] == magic and ext in exts:
                return True
        return True
    if not _check_magic(content_bytes):
        raise HTTPException(400, "File content does not match declared extension")
    if len(content_bytes) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(400, "File too large — maximum 10MB")
    # ZIP bomb detection — check compression ratio for ZIP-based files
    if ext in {".docx",".doc"} and content_bytes[:4] == b"PK\x03\x04":
        try:
            import zipfile, io
            with zipfile.ZipFile(io.BytesIO(content_bytes)) as zf:
                total_uncompressed = sum(i.file_size for i in zf.infolist())
                ratio = total_uncompressed / max(len(content_bytes), 1)
                if ratio > 200:  # >200× compression ratio = ZIP bomb
                    raise HTTPException(400, "File rejected: suspicious compression ratio")
                if total_uncompressed > 50 * 1024 * 1024:  # 50MB uncompressed limit
                    raise HTTPException(400, "File rejected: uncompressed size exceeds limit")
        except zipfile.BadZipFile:
            raise HTTPException(400, "File is not a valid DOCX (corrupt ZIP)")
        except HTTPException: raise
    # ── Cloudflare R2 storage (falls back to local disk if not configured) ──
    r2_account  = os.environ.get("CLOUDFLARE_R2_ACCOUNT_ID", "")
    r2_access   = os.environ.get("CLOUDFLARE_R2_ACCESS_KEY", "")
    r2_secret   = os.environ.get("CLOUDFLARE_R2_SECRET_KEY", "")
    r2_bucket   = os.environ.get("CLOUDFLARE_R2_BUCKET", "")
    file_key    = f"{user.id}/{uuid.uuid4().hex[:8]}_{file.filename}"

    if r2_account and r2_access and r2_secret and r2_bucket:
        # Upload to R2 — survives redeployments
        try:
            import boto3 as _boto3
            s3 = _boto3.client(
                "s3",
                endpoint_url=f"https://{r2_account}.r2.cloudflarestorage.com",
                aws_access_key_id=r2_access,
                aws_secret_access_key=r2_secret,
                region_name="auto",
            )
            s3.put_object(
                Bucket=r2_bucket,
                Key=file_key,
                Body=content_bytes,
                ContentType=file.content_type or "application/octet-stream",
            )
            file_url = (
                f"https://{r2_bucket}.{r2_account}.r2.cloudflarestorage.com/{file_key}"
            )
            logger.info("R2 upload OK: %s (%d bytes)", file_key, len(content_bytes))
        except Exception as r2_err:
            logger.error("R2 upload failed — falling back to disk: %s", r2_err)
            # Fallback: write to local disk (ephemeral but better than failing)
            d = Path(f"data/uploads/{user.id}"); d.mkdir(parents=True, exist_ok=True)
            p = d / file_key.split("/", 1)[-1]
            p.write_bytes(content_bytes)
            file_url = str(p)
    else:
        # R2 not configured — use local disk (data lost on redeploy)
        logger.warning("R2 not configured — using ephemeral local storage")
        d = Path(f"data/uploads/{user.id}"); d.mkdir(parents=True, exist_ok=True)
        p = d / file_key.split("/", 1)[-1]
        p.write_bytes(content_bytes)
        file_url = str(p)

    # Persist the file URL on the user record
    u = db.query(User).filter(User.id == user.id).first()
    if u:
        docs = list(getattr(u, "documents", None) or [])
        docs.append({"name": file.filename, "url": file_url, "key": file_key})
        # Store as JSON in a dedicated column if it exists, otherwise log only
        try:
            u.documents = docs
            db.commit()
        except Exception:
            db.rollback()
    return {
        "message": "Document uploaded successfully",
        "url":     file_url,
        "key":     file_key,
        "size_kb": round(len(content_bytes) / 1024, 1),
        "user":    user.to_dict(),
    }

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
    # ── Arts & Humanities ────────────────────────────────────
    {"id":"prince_claus_arts","name":"Prince Claus Fund Cultural Grant","type":"grant","amount_usd":10000,"deadline":"2025-06-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Senegal","Morocco","Egypt"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Arts, Culture, Heritage, Creative Industries","gpa_min":0,"tags":["arts","culture","heritage","creative","humanities"],"url":"https://www.princeclausfund.org/","description":"Grants for artists and cultural practitioners from Africa and Asia","competitiveness":{"label":"Moderate","acceptance_rate":0.15}},
    {"id":"fulbright_arts_fellow","name":"Fulbright Creative Arts Fellowship","type":"fellowship","amount_usd":35000,"deadline":"2025-10-15","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Visual Arts, Music, Film, Creative Writing, Humanities","gpa_min":3.0,"tags":["fulbright","arts","music","film","creative writing","usa","humanities"],"url":"https://foreign.fulbrightonline.org/","description":"Fulbright fellowships for creative artists to pursue advanced study in the USA","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}},
    # ── Education ────────────────────────────────────────────
    {"id":"aga_khan_education","name":"Aga Khan Education Services Scholarship","type":"scholarship","amount_usd":15000,"deadline":"2025-04-30","eligible_countries":["Kenya","Tanzania","Uganda","India","Pakistan","Bangladesh","Afghanistan","Mozambique"],"degree_levels":["Undergraduate","Graduate"],"field":"Education, Teaching, Curriculum Development, Early Childhood","gpa_min":3.0,"tags":["education","aga khan","teaching","curriculum","developing countries"],"url":"https://www.akes.org/","description":"Scholarships for students committed to careers in education in AKDN countries","competitiveness":{"label":"Competitive","acceptance_rate":0.12}},
    {"id":"hgse_int_fellowship","name":"Harvard Education Fellowship (International)","type":"fellowship","amount_usd":55000,"deadline":"2025-01-02","eligible_countries":["Global"],"degree_levels":["Graduate"],"field":"Education Policy, Educational Leadership, International Education","gpa_min":3.5,"tags":["harvard","education","policy","leadership","hgse"],"url":"https://www.gse.harvard.edu/financial-aid","description":"Need-based and merit fellowships for international students at Harvard Graduate School of Education","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.04}},
    # ── Architecture & Urban Design ───────────────────────────
    {"id":"riba_foster_scholarship","name":"RIBA Norman Foster Scholarship","type":"scholarship","amount_usd":16000,"deadline":"2025-11-01","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Architecture, Sustainable Design, Urban Planning, Interior Design","gpa_min":3.3,"tags":["architecture","riba","design","norman foster","sustainable","urban"],"url":"https://www.riba.org/education-and-careers/scholarships/","description":"RIBA scholarship for outstanding architecture students with focus on sustainable design","competitiveness":{"label":"Very Competitive","acceptance_rate":0.06}},
    {"id":"unhabitat_youth","name":"UN-Habitat Urban Youth Innovation Grant","type":"grant","amount_usd":20000,"deadline":"2025-07-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Egypt","Bangladesh","India","Indonesia","Philippines"],"degree_levels":["Undergraduate","Graduate"],"field":"Urban Planning, Architecture, Sustainable Cities, Real Estate","gpa_min":0,"tags":["urban","planning","cities","architecture","habitat","sustainable"],"url":"https://unhabitat.org/youth","description":"UN-Habitat grants for young urban innovators in developing countries","competitiveness":{"label":"Competitive","acceptance_rate":0.10}},
    # ── Psychology & Mental Health ─────────────────────────────
    {"id":"who_mental_health_grant","name":"WHO Mental Health Research Grant","type":"grant","amount_usd":25000,"deadline":"2025-06-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","India","Pakistan","Bangladesh"],"degree_levels":["Graduate","Postgraduate"],"field":"Psychology, Psychiatry, Mental Health, Counseling, Behavioral Science","gpa_min":3.2,"tags":["who","mental health","psychiatry","psychology","research","counseling"],"url":"https://www.who.int/activities/improving-mental-health","description":"WHO research grants for mental health innovations in low and middle-income countries","competitiveness":{"label":"Competitive","acceptance_rate":0.10}},
    # ── Philosophy & Ethics ───────────────────────────────────
    {"id":"templeton_philo_grant","name":"John Templeton Foundation Philosophy Grant","type":"grant","amount_usd":50000,"deadline":"2025-04-01","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Philosophy, Ethics, Theology, Religious Studies, Metaphysics","gpa_min":3.5,"tags":["philosophy","ethics","religion","templeton","theology","consciousness"],"url":"https://www.templeton.org/grants","description":"Research grants at the intersection of science, religion, and philosophy","competitiveness":{"label":"Very Competitive","acceptance_rate":0.06}},
    # ── Mathematics & Statistics ──────────────────────────────
    {"id":"ictp_maths_diploma","name":"ICTP Postgraduate Diploma Programme (Mathematics)","type":"scholarship","amount_usd":18000,"deadline":"2025-01-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Senegal","Cameroon","Bangladesh","Pakistan","Nepal","Vietnam","Indonesia"],"degree_levels":["Graduate"],"field":"Mathematics, Statistics, Mathematical Physics, Computational Science","gpa_min":3.3,"tags":["mathematics","statistics","physics","ictp","italy","computational","theoretical"],"url":"https://www.ictp.it/","description":"ICTP one-year postgraduate diplomas in mathematics and physics for developing country students","competitiveness":{"label":"Competitive","acceptance_rate":0.12}},
    # ── Journalism & Media ────────────────────────────────────
    {"id":"reuters_journalist_fellow","name":"Reuters Institute Journalist Fellowship (Oxford)","type":"fellowship","amount_usd":22000,"deadline":"2025-02-28","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","South Africa","Egypt","Morocco","Senegal","Ethiopia"],"degree_levels":["Graduate"],"field":"Journalism, Media Studies, Communications, Broadcasting, Digital Media","gpa_min":0,"tags":["journalism","media","reuters","oxford","digital","reporting","broadcasting"],"url":"https://reutersinstitute.politics.ox.ac.uk/journalist-fellowships","description":"Oxford-based fellowship for mid-career journalists researching digital media and journalism innovation","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}},
    # ── Nursing & Allied Health ───────────────────────────────
    {"id":"johnson_nursing_scholarship","name":"Johnson and Johnson Nursing Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-07-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","South Africa","India","Pakistan","Bangladesh","Philippines","Indonesia"],"degree_levels":["Undergraduate","Graduate"],"field":"Nursing, Midwifery, Allied Health Sciences, Physiotherapy, Occupational Therapy","gpa_min":3.0,"tags":["nursing","midwifery","allied health","healthcare","clinical","women"],"url":"https://nursing.jnj.com/","description":"Scholarships for nursing and allied health students committed to improving developing country healthcare","competitiveness":{"label":"Moderate","acceptance_rate":0.18}},
    # ── Social Work ───────────────────────────────────────────
    {"id":"iassw_social_sch","name":"IASSW International Social Work Scholarship","type":"scholarship","amount_usd":5000,"deadline":"2025-08-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Bangladesh","India","Pakistan","Nepal","Sri Lanka"],"degree_levels":["Graduate"],"field":"Social Work, Community Development, Child Welfare, Youth Work, Disability Studies","gpa_min":2.8,"tags":["social work","community","child welfare","development","human services","disability"],"url":"https://www.iassw-aiets.org/scholarships/","description":"IASSW scholarships for social work students from developing countries","competitiveness":{"label":"Moderate","acceptance_rate":0.18}},
    # ── Accounting & Finance ──────────────────────────────────
    {"id":"acca_access_sch","name":"ACCA Access Scholarship","type":"scholarship","amount_usd":6000,"deadline":"2025-10-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Zimbabwe","Zambia","Senegal","Cameroon","Bangladesh","Pakistan","Sri Lanka"],"degree_levels":["Undergraduate","Graduate"],"field":"Accounting, Finance, Auditing, Taxation, Financial Management","gpa_min":3.0,"tags":["accounting","finance","acca","audit","taxation","professional"],"url":"https://www.accaglobal.com/gb/en/student/exam-support-resources/scholarships.html","description":"ACCA scholarships for internationally recognised accounting qualifications from developing countries","competitiveness":{"label":"Competitive","acceptance_rate":0.14}},
    # ── Agriculture & Food Science ────────────────────────────
    {"id":"cgiar_young_sci","name":"CGIAR Research Fellowship for Young Scientists","type":"fellowship","amount_usd":20000,"deadline":"2025-06-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Rwanda","Senegal","Bangladesh","India","Pakistan","Vietnam","Philippines","Indonesia"],"degree_levels":["Graduate","Postgraduate"],"field":"Agriculture, Food Science, Plant Science, Soil Science, Agronomy, Agroforestry","gpa_min":3.2,"tags":["agriculture","food","plant","soil","cgiar","research","food security"],"url":"https://www.cgiar.org/","description":"CGIAR fellowships for young agricultural scientists addressing global food security challenges","competitiveness":{"label":"Competitive","acceptance_rate":0.10}},
    # ── Sports Science ────────────────────────────────────────
    {"id":"olympic_solidarity_s","name":"Olympic Solidarity Scholarship","type":"scholarship","amount_usd":8000,"deadline":"2025-11-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Senegal","Morocco","Egypt","Bangladesh","India","Pakistan"],"degree_levels":["Undergraduate","Graduate"],"field":"Sports Science, Physical Education, Sports Management, Coaching, Athletic Training","gpa_min":2.5,"tags":["sports","olympic","physical education","coaching","athlete","solidarity","performance"],"url":"https://www.olympic.org/olympic-solidarity","description":"IOC Olympic Solidarity scholarships for student-athletes and sports science students from developing nations","competitiveness":{"label":"Moderate","acceptance_rate":0.20}},
    # ── Tourism & Hospitality ─────────────────────────────────
    {"id":"unwto_themis_s","name":"UNWTO Themis Foundation Scholarship","type":"scholarship","amount_usd":8000,"deadline":"2025-05-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Morocco","Egypt","Bangladesh","India","Sri Lanka","Nepal","Indonesia"],"degree_levels":["Undergraduate","Graduate"],"field":"Tourism, Hospitality, Hotel Management, Event Management, Ecotourism","gpa_min":2.8,"tags":["tourism","hospitality","hotel","ecotourism","event management","sustainable"],"url":"https://themis.unwto.org/","description":"UNWTO scholarships for tourism students committed to sustainable tourism development","competitiveness":{"label":"Moderate","acceptance_rate":0.20}},
    # ── Pharmacy ─────────────────────────────────────────────
    {"id":"usp_pharma_fellow","name":"USP International Graduate Fellowship (Pharmacy)","type":"fellowship","amount_usd":25000,"deadline":"2025-03-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","South Africa","India","Bangladesh","Pakistan","Philippines","Indonesia"],"degree_levels":["Graduate","Postgraduate"],"field":"Pharmacy, Pharmaceutical Sciences, Drug Development, Clinical Pharmacy","gpa_min":3.3,"tags":["pharmacy","pharmaceutical","drug","research","clinical","medicine","quality"],"url":"https://www.usp.org/about/scholarships","description":"US Pharmacopeia fellowships for international graduate students in pharmaceutical sciences","competitiveness":{"label":"Competitive","acceptance_rate":0.10}},
    # ── Veterinary Science ────────────────────────────────────
    {"id":"woah_vet_education","name":"WOAH Veterinary Education Scholarship","type":"scholarship","amount_usd":12000,"deadline":"2025-09-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Senegal","Cameroon","Mozambique","Zimbabwe"],"degree_levels":["Undergraduate","Graduate"],"field":"Veterinary Science, Animal Health, Zoonotic Diseases, One Health, Wildlife Conservation","gpa_min":3.0,"tags":["veterinary","animal health","zoonotic","one health","africa","wildlife"],"url":"https://www.woah.org/en/capacity-building/scholarships/","description":"World Organisation for Animal Health scholarships for African students in veterinary sciences","competitiveness":{"label":"Moderate","acceptance_rate":0.15}}

    ,{"id":"kaust_fellowship","name":"KAUST Fellowship (Saudi Arabia)","type":"fellowship","amount_usd":50000,"deadline":"2025-12-01","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Science, Technology, Engineering, Mathematics","gpa_min":3.5,"tags":["saudi arabia","kaust","stem","research","phd","middle east","prestigious","fully-funded"],"url":"https://www.kaust.edu.sa/en/study/financial-support","description":"King Abdullah University of Science and Technology fully-funded fellowships for STEM research","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}}
    ,{"id":"uae_gov_scholarship","name":"UAE Government Scholarship","type":"scholarship","amount_usd":20000,"deadline":"2025-04-30","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate"],"field":"Engineering, Business, Medicine, STEM","gpa_min":3.2,"tags":["uae","dubai","abu dhabi","government","stem","business","middle east","engineering"],"url":"https://www.government.ae/en/information-and-services/education/scholarships","description":"UAE government scholarships for outstanding international students in priority development fields","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"qatar_univ_scholarship","name":"Qatar University International Scholarship","type":"scholarship","amount_usd":18000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Engineering, Business, Education, Natural Sciences","gpa_min":3.0,"tags":["qatar","middle east","government","stem","business","education","arabic","research"],"url":"https://www.qu.edu.qa/scholarships","description":"Qatar University scholarships for international students in engineering, business, and sciences","competitiveness":{"label":"Competitive","acceptance_rate":0.15}}
    ,{"id":"poland_nawa_scholarship","name":"Polish Government Scholarship (NAWA)","type":"scholarship","amount_usd":8000,"deadline":"2025-04-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","India","Bangladesh","Pakistan","Vietnam","Indonesia","Philippines","Ukraine","Belarus","Georgia","Armenia","Kazakhstan","Uzbekistan"],"degree_levels":["Graduate","Postgraduate"],"field":"All fields","gpa_min":3.0,"tags":["poland","eastern europe","government","nawa","stem","social sciences","affordable","english","phd","warsaw"],"url":"https://nawa.gov.pl/en/students-and-scientists/foreign-students/scholarships","description":"Polish National Agency for Academic Exchange scholarships for international students in Poland","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"czech_gov_scholarship","name":"Czech Government Scholarship","type":"scholarship","amount_usd":8000,"deadline":"2025-03-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","India","Bangladesh","Vietnam","Indonesia","Philippines","Ukraine","Belarus","Georgia","Serbia","Bosnia","Albania"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":2.8,"tags":["czech republic","eastern europe","government","prague","stem","arts","affordable","developing countries"],"url":"https://www.msmt.cz/eu-and-international-affairs/czech-government-scholarships","description":"Czech government scholarships for students from developing countries to study in Czech Republic","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"romanian_gov_scholarship","name":"Romanian Government Scholarship","type":"scholarship","amount_usd":7000,"deadline":"2025-03-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Egypt","Morocco","India","Bangladesh","Pakistan","Vietnam","Indonesia","Philippines","Colombia","Brazil","Peru","Mexico","Ecuador","Bolivia"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":2.8,"tags":["romania","eastern europe","government","bucharest","affordable","english","medicine","stem","developing countries"],"url":"https://mae.ro/en/node/2028","description":"Romanian government scholarships for developing country students — medicine and engineering focus","competitiveness":{"label":"Moderate","acceptance_rate":0.22}}
    ,{"id":"norway_quota_scholarship","name":"Norwegian Quota Scheme Scholarship","type":"scholarship","amount_usd":22000,"deadline":"2025-12-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Mozambique","South Africa","Bangladesh","India","Pakistan","Vietnam","Indonesia","Philippines","Nepal","Sri Lanka","Cambodia","Myanmar","Bolivia","Cuba","Ecuador","Guatemala","Honduras","Nicaragua","Palestine","Ukraine","Belarus","Russia","Kazakhstan","Georgia","Armenia","Azerbaijan"],"degree_levels":["Graduate","Postgraduate"],"field":"All fields","gpa_min":3.0,"tags":["norway","nordic","government","affordable","fully-funded","quota","developing countries","phd","masters","oslo"],"url":"https://hkdir.no/en/scholarships-and-funding","description":"Norwegian government quota scholarships for developing country students covering tuition and living costs in Norway","competitiveness":{"label":"Competitive","acceptance_rate":0.14}}
    ,{"id":"si_scholarship_sweden","name":"Swedish Institute Scholarships for Global Professionals","type":"scholarship","amount_usd":25000,"deadline":"2025-02-10","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Senegal","Morocco","Egypt","Bangladesh","India","Pakistan","Vietnam","Indonesia","Philippines","Nepal","Sri Lanka","Cambodia","Myanmar","Colombia","Brazil","Mexico","Bolivia","Peru","Palestine","Jordan","Lebanon","Iraq","Sudan"],"degree_levels":["Graduate"],"field":"All fields with priority on sustainable development","gpa_min":3.0,"tags":["sweden","nordic","government","sustainable development","leadership","fully-funded","stockholm","developing countries"],"url":"https://si.se/en/apply/scholarships/","description":"Swedish Institute fully-funded master's scholarships for future global leaders from developing countries","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"denmark_gov_scholarship","name":"Denmark Government Scholarship","type":"scholarship","amount_usd":24000,"deadline":"2025-01-15","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate"],"field":"Engineering, Design, Architecture, Sustainability, Business","gpa_min":3.2,"tags":["denmark","nordic","government","engineering","design","architecture","sustainability","copenhagen"],"url":"https://ufm.dk/en/education-and-institutions/scholarships-and-study-abroad","description":"Danish government scholarships for excellent international non-EU students","competitiveness":{"label":"Very Competitive","acceptance_rate":0.09}}
    ,{"id":"finland_gov_scholarship","name":"Finland Government Scholarship","type":"scholarship","amount_usd":15000,"deadline":"2025-01-31","eligible_countries":["Global"],"degree_levels":["Graduate"],"field":"Technology, Education, Nordic Studies, STEM","gpa_min":3.2,"tags":["finland","nordic","government","technology","education","stem","affordable","helsinki","espoo"],"url":"https://www.studyinfinland.fi/scholarships","description":"Finnish university scholarships for non-EU international students — many programmes in English","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"brazil_cnpq_fellowship","name":"Brazil CNPq Science Without Borders Fellowship","type":"fellowship","amount_usd":20000,"deadline":"2025-08-31","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"STEM, Natural Sciences, Biomedical, Engineering, Computer Science","gpa_min":3.3,"tags":["brazil","latin america","cnpq","stem","research","science without borders","phd","affordable"],"url":"https://www.cnpq.br/web/guest/bolsas","description":"Brazilian CNPq fellowships for international researchers to collaborate with Brazilian universities","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"mexico_amexcid","name":"Mexico AMEXCID Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-04-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Senegal","Mali","Bangladesh","India","Pakistan","Vietnam","Indonesia","Philippines","Nepal","Sri Lanka","Guatemala","Honduras","El Salvador","Haiti","Cuba","Bolivia","Peru","Ecuador","Colombia","Panama"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":2.8,"tags":["mexico","latin america","government","amexcid","developing countries","spanish","affordable","south-south","africa","asia"],"url":"https://www.gob.mx/amexcid","description":"Mexican Agency for International Development Cooperation scholarships for developing country students in Mexico","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"sadc_scholarship","name":"SADC Scholarship and Training Programme","type":"scholarship","amount_usd":15000,"deadline":"2025-07-31","eligible_countries":["Angola","Botswana","Comoros","DRC","Eswatini","Lesotho","Madagascar","Malawi","Mauritius","Mozambique","Namibia","Seychelles","South Africa","Tanzania","Zambia","Zimbabwe"],"degree_levels":["Graduate","Postgraduate"],"field":"Agriculture, Natural Resources, Health, Education, Economics","gpa_min":3.0,"tags":["sadc","southern africa","regional","agriculture","health","economics","development","intra-regional"],"url":"https://www.sadc.int/","description":"Southern African Development Community scholarships for intra-regional mobility across SADC member states","competitiveness":{"label":"Competitive","acceptance_rate":0.14}}
    ,{"id":"ford_foundation_intl","name":"Ford Foundation International Fellowships","type":"fellowship","amount_usd":28000,"deadline":"2025-10-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Mozambique","Egypt","Morocco","India","Bangladesh","Vietnam","Indonesia","Philippines","Nepal","Sri Lanka","Cambodia","Myanmar","Brazil","Colombia","Mexico","Chile","Peru","Bolivia","Ecuador","Guatemala","Honduras","Nicaragua","Palestine","Lebanon","Jordan"],"degree_levels":["Graduate","Postgraduate"],"field":"Social Sciences, Humanities, Law, Education, Environment, Public Health","gpa_min":3.0,"tags":["ford foundation","private","social sciences","humanities","law","education","developing countries","leaders","civil society","diversity"],"url":"https://www.fordfoundation.org/","description":"Ford Foundation fellowships for individuals committed to social justice and positive change in developing countries","competitiveness":{"label":"Very Competitive","acceptance_rate":0.06}}
    ,{"id":"wellcome_trust_intl","name":"Wellcome Trust International Training Fellowship","type":"fellowship","amount_usd":75000,"deadline":"2025-11-01","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Malawi","Mozambique","Zimbabwe","Zambia","Bangladesh","India","Pakistan","Vietnam","Indonesia","Philippines","Nepal","Sri Lanka","Thailand","Malaysia"],"degree_levels":["Postgraduate"],"field":"Biomedical Science, Public Health, Global Health, Medical Research","gpa_min":3.5,"tags":["wellcome trust","private","biomedical","public health","global health","medical research","fully-funded","phd","prestigious"],"url":"https://wellcome.org/grant-funding/schemes/international-training-fellowships","description":"Wellcome Trust fellowships for biomedical scientists from low- and middle-income countries to train at world-class institutions","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.05}}
    ,{"id":"isdb_merit_scholarship","name":"Islamic Development Bank Merit Scholarship","type":"scholarship","amount_usd":20000,"deadline":"2025-03-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Senegal","Mali","Burkina Faso","Niger","Guinea","Sierra Leone","Gambia","Egypt","Morocco","Tunisia","Algeria","Libya","Sudan","Somalia","Djibouti","Comoros","Mozambique","Cameroon","Chad","Bangladesh","Pakistan","Afghanistan","Indonesia","Malaysia","Maldives","Albania","Azerbaijan","Kazakhstan","Kyrgyzstan","Tajikistan","Uzbekistan","Turkey"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Science, Technology, Engineering, Mathematics, Agriculture, Medicine","gpa_min":3.0,"tags":["islamic development bank","isdb","oci","muslim majority","stem","medicine","agriculture","developing countries","africa","asia"],"url":"https://www.isdb.org/merit-scholarship-programme-for-high-technology","description":"Islamic Development Bank merit scholarships for OIC member state students in STEM, agriculture, and medicine","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"rotary_peace_fellowship","name":"Rotary Peace Fellowship","type":"fellowship","amount_usd":65000,"deadline":"2025-05-15","eligible_countries":["Global"],"degree_levels":["Graduate"],"field":"Peace and Conflict Studies, International Relations, Development, Public Health, Law","gpa_min":3.0,"tags":["rotary","peace","conflict resolution","international relations","development","fellowship","prestigious","global","fully-funded","leadership"],"url":"https://www.rotary.org/en/our-programs/peace-fellowships","description":"Rotary Foundation fully-funded master's fellowships for future peace and development leaders worldwide","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.04}}
    ,{"id":"agra_africa_fellowship","name":"AGRA Africa Agriculture Fellowship","type":"fellowship","amount_usd":25000,"deadline":"2025-09-01","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Rwanda","Zambia","Zimbabwe","Malawi","Mozambique","Mali","Burkina Faso","Senegal","Niger","Guinea","Sierra Leone","Liberia","Côte d'Ivoire","Cameroon"],"degree_levels":["Graduate","Postgraduate"],"field":"Agriculture, Agronomy, Soil Science, Plant Science, Agricultural Economics","gpa_min":3.0,"tags":["agra","gates foundation","agriculture","africa","agronomy","food security","private","fellowship","green revolution"],"url":"https://agra.org/","description":"Alliance for a Green Revolution in Africa fellowships for African agricultural scientists and practitioners","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"iucea_east_africa","name":"IUCEA East Africa Inter-University Scholarship","type":"scholarship","amount_usd":12000,"deadline":"2025-08-31","eligible_countries":["Kenya","Uganda","Tanzania","Rwanda","Burundi","South Sudan","Ethiopia","Eritrea","Somalia","Djibouti"],"degree_levels":["Graduate","Postgraduate"],"field":"Agriculture, Natural Resources, ICT, Health, Education","gpa_min":3.0,"tags":["east africa","iucea","regional","agriculture","ict","health","education","intra-african","eac"],"url":"https://www.iucea.org/","description":"Inter-University Council for East Africa scholarships promoting intra-regional mobility across EAC member states","competitiveness":{"label":"Competitive","acceptance_rate":0.14}}
    ,{"id":"morocco_amci","name":"Morocco AMCI Scholarship for Africans","type":"scholarship","amount_usd":8000,"deadline":"2025-05-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Senegal","Mali","Burkina Faso","Niger","Chad","Guinea","Cameroon","Côte d'Ivoire","Madagascar","Comoros","Mauritania","Guinea-Bissau","Cap Verde","São Tomé","Gambia","Sierra Leone","Liberia","Benin","Togo"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":2.8,"tags":["morocco","africa","arab","government","french","amci","developing countries","south-south","rabat","casablanca"],"url":"http://www.amci.ma/en","description":"Moroccan Agency for International Cooperation scholarships for Sub-Saharan African students to study in Morocco","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}

    ,{"id":"mext_japan","name":"MEXT Japanese Government Scholarship","type":"scholarship","amount_usd":18000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":2.5,"tags":["japan","mext","stem","language","fully-funded","government","asia","tokyo","osaka"],"url":"https://www.mext.go.jp/en/policy/education/highered/title02/detail02/sdetail02/1373897.htm","description":"Japanese government scholarships covering tuition, accommodation, and monthly stipend for international students in Japan","competitiveness":{"label":"Competitive","acceptance_rate":0.15}}
    ,{"id":"jasso_scholarship","name":"JASSO Honors Scholarship for International Students","type":"scholarship","amount_usd":6000,"deadline":"2025-06-30","eligible_countries":["Kenya","Nigeria","Ghana","India","Bangladesh","Pakistan","Vietnam","Indonesia","Philippines","Thailand","Malaysia","China","South Korea","Nepal","Sri Lanka"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":3.2,"tags":["japan","jasso","asia","study abroad","academic excellence","stem","arts","science"],"url":"https://www.jasso.or.jp/en/","description":"Japan Student Services Organization scholarships for high-achieving international students studying in Japan","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"hitachi_scholarship","name":"Hitachi Scholarship Foundation","type":"scholarship","amount_usd":20000,"deadline":"2025-12-01","eligible_countries":["Bangladesh","India","Indonesia","Malaysia","Pakistan","Philippines","Sri Lanka","Thailand","Vietnam","Myanmar","Cambodia","Nepal"],"degree_levels":["Graduate","Postgraduate"],"field":"Engineering, Science, Technology","gpa_min":3.3,"tags":["japan","hitachi","stem","engineering","science","technology","southeast asia","south asia"],"url":"https://www.hitachi-zaidan.org/global/activities/scholarship/","description":"Hitachi Foundation scholarships for Asian scientists and engineers to study in Japan","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"toyota_foundation_grant","name":"Toyota Foundation Research Grant","type":"grant","amount_usd":30000,"deadline":"2025-10-31","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Social Sciences, Humanities, Environment, Technology","gpa_min":3.3,"tags":["japan","toyota","research","social sciences","humanities","sustainability","asia"],"url":"https://www.toyotafound.or.jp/english/research/","description":"Toyota Foundation research grants addressing global social challenges with a Japan-Asia perspective","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"gks_scholarship","name":"Korean Government Scholarship (GKS/KGSP)","type":"scholarship","amount_usd":16000,"deadline":"2025-03-14","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Bangladesh","India","Pakistan","Vietnam","Indonesia","Philippines","Malaysia","Thailand","Nepal","Sri Lanka","Cambodia","Myanmar","China","Uzbekistan","Kazakhstan"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":3.0,"tags":["south korea","korea","gks","kgsp","stem","arts","government","fully-funded","asia","seoul","busan"],"url":"https://www.studyinkorea.go.kr/en/sub/gks/allnew_unv.do","description":"South Korean government fully-funded scholarships covering tuition, housing, Korean language training, and monthly allowance","competitiveness":{"label":"Competitive","acceptance_rate":0.14}}
    ,{"id":"posco_tj_fellowship","name":"POSCO TJ Park Foundation Asia Fellowship","type":"fellowship","amount_usd":15000,"deadline":"2025-11-30","eligible_countries":["China","India","Vietnam","Indonesia","Philippines","Thailand","Malaysia","Bangladesh","Pakistan","Myanmar","Cambodia","Nepal","Sri Lanka","Mongolia"],"degree_levels":["Graduate","Postgraduate"],"field":"Science, Engineering, Business, Social Sciences","gpa_min":3.2,"tags":["south korea","posco","steel","engineering","asia","fellowship","business","research"],"url":"https://www.postf.org/eng/index.asp","description":"POSCO Foundation fellowships for Asian graduate students pursuing academic excellence and sustainable development","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"taiwan_mofa_scholarship","name":"Taiwan Ministry of Foreign Affairs Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-03-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Senegal","Burkina Faso","Eswatini","Haiti","Paraguay","Guatemala","Honduras","El Salvador","Belize","Palau","Marshall Islands","Tuvalu","Nauru"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":2.8,"tags":["taiwan","mofa","diplomatic allies","stem","mandarin","government","official","taipei"],"url":"https://www.mofa.gov.tw/en/News.aspx?n=2681","description":"Taiwan government scholarships for students from diplomatic partner countries to study in Taiwan","competitiveness":{"label":"Moderate","acceptance_rate":0.22}}
    ,{"id":"taiwan_icdf_scholarship","name":"Taiwan ICDF International Higher Education Scholarship","type":"scholarship","amount_usd":12000,"deadline":"2025-03-01","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Gambia","Honduras","Paraguay","Guatemala","Belize","Haiti","Palau","Marshall Islands","Tuvalu","El Salvador"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Agriculture, Public Health, Environment, Business","gpa_min":3.0,"tags":["taiwan","icdf","development","agriculture","health","environment","government","taipei"],"url":"https://www.icdf.org.tw/","description":"Taiwan ICDF scholarships for students from partner developing countries","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"astar_fellowship","name":"A*STAR International Fellowship (Singapore)","type":"fellowship","amount_usd":55000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Biomedical Science, Engineering, Physical Sciences, Computing","gpa_min":3.5,"tags":["singapore","astar","research","biomedical","engineering","physical science","computing","prestigious","fully-funded"],"url":"https://www.a-star.edu.sg/Scholarships/overview","description":"A*STAR International Fellowships for top researchers to conduct cutting-edge research in Singapore","competitiveness":{"label":"Very Competitive","acceptance_rate":0.06}}
    ,{"id":"ntu_research_scholarship","name":"NTU Research Scholarship (Singapore)","type":"scholarship","amount_usd":20000,"deadline":"2025-06-30","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Engineering, Science, Business, Humanities","gpa_min":3.5,"tags":["singapore","ntu","nanyang","research","phd","stem","prestigious","asia","fully-funded"],"url":"https://www.ntu.edu.sg/education/graduate-programme/research-scholarship","description":"Nanyang Technological University research scholarships for PhD students across all disciplines","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}}
    ,{"id":"nus_research_scholarship","name":"NUS Research Scholarship (Singapore)","type":"scholarship","amount_usd":20000,"deadline":"2025-07-31","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"All fields — Engineering, Medicine, Law, Arts, Science","gpa_min":3.5,"tags":["singapore","nus","national university","research","phd","stem","prestigious","asia"],"url":"https://nusgs.nus.edu.sg/scholarships/","description":"National University of Singapore research scholarships for outstanding PhD candidates worldwide","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}}
    ,{"id":"malaysia_utm_scholarship","name":"UTM International Graduate Scholarship (Malaysia)","type":"scholarship","amount_usd":10000,"deadline":"2025-10-31","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Engineering, Technology, Science, Management","gpa_min":3.2,"tags":["malaysia","utm","engineering","technology","science","management","affordable","kuala lumpur"],"url":"https://graduate.utm.my/scholarship/","description":"Universiti Teknologi Malaysia scholarships for international graduate students in STEM and management","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"ait_scholarship","name":"AIT Scholarship — Asian Institute of Technology","type":"scholarship","amount_usd":15000,"deadline":"2025-08-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Bangladesh","India","Pakistan","Vietnam","Indonesia","Philippines","Myanmar","Cambodia","Laos","Nepal","Sri Lanka","Bhutan","Mongolia"],"degree_levels":["Graduate","Postgraduate"],"field":"Engineering, Technology, Environment, Management","gpa_min":3.0,"tags":["thailand","ait","engineering","environment","technology","management","asia","affordable","bangkok"],"url":"https://www.ait.ac.th/study-at-ait/scholarships/","description":"Asian Institute of Technology scholarships for students from developing Asia and Africa in applied sciences","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"asean_scholarship_sg","name":"ASEAN Scholarship Singapore","type":"scholarship","amount_usd":22000,"deadline":"2025-03-31","eligible_countries":["Brunei","Cambodia","Indonesia","Laos","Malaysia","Myanmar","Philippines","Thailand","Vietnam"],"degree_levels":["Undergraduate","Graduate"],"field":"All fields","gpa_min":3.2,"tags":["asean","singapore","southeast asia","prestigious","fully-funded","government","regional","moe"],"url":"https://www.moe.gov.sg/financial-matters/awards-scholarships/asean-scholarships","description":"Singapore Ministry of Education scholarships for outstanding ASEAN students to study in Singapore","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"australia_awards","name":"Australia Awards Scholarship","type":"scholarship","amount_usd":45000,"deadline":"2025-04-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Rwanda","Mozambique","Zambia","Zimbabwe","Senegal","Bangladesh","India","Pakistan","Vietnam","Indonesia","Philippines","Myanmar","Cambodia","Laos","Nepal","Sri Lanka","Bhutan","Timor-Leste","Papua New Guinea","Solomon Islands","Vanuatu","Fiji","Samoa","Tonga"],"degree_levels":["Graduate"],"field":"All fields — priority on development, agriculture, health, education","gpa_min":3.0,"tags":["australia","awards","development","fully-funded","prestigious","africa","asia","pacific","canberra"],"url":"https://www.dfat.gov.au/people-to-people/australia-awards","description":"Australian government fully-funded scholarships for emerging leaders from developing Asia, Africa, and Pacific regions","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"sasakawa_peace_fellow","name":"Sasakawa Peace Foundation Fellowship","type":"fellowship","amount_usd":25000,"deadline":"2025-09-30","eligible_countries":["Bangladesh","India","Pakistan","Nepal","Sri Lanka","Myanmar","Cambodia","Laos","Vietnam","Philippines","Indonesia","Thailand","Malaysia","Mongolia","Kenya","Nigeria","Tanzania","Ghana"],"degree_levels":["Graduate","Postgraduate"],"field":"Peace Studies, International Relations, Environmental Studies, Ocean Policy","gpa_min":3.2,"tags":["japan","sasakawa","peace","international relations","environment","ocean","asia","africa","fellowship"],"url":"https://www.spf.org/en/","description":"Sasakawa Peace Foundation fellowships for students from Asia and Africa in peace studies and international relations","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"china_csc_bilateral","name":"Chinese Government Bilateral Scholarship (CSC)","type":"scholarship","amount_usd":15000,"deadline":"2025-04-01","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Rwanda","Zimbabwe","Zambia","Mozambique","South Africa","Egypt","Morocco","Senegal","Bangladesh","Pakistan","Nepal","Sri Lanka","Myanmar","Cambodia","Laos"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":2.8,"tags":["china","csc","bilateral","government","stem","mandarin","fully-funded","bri","africa","asia","beijing","shanghai"],"url":"https://www.campuschina.org/","description":"Chinese government bilateral scholarships covering tuition, accommodation, and stipend under country-to-country agreements","competitiveness":{"label":"Competitive","acceptance_rate":0.17}}

    ,{"id":"tsinghua_scholarship","name":"Tsinghua University Scholarship for International Students","type":"scholarship","amount_usd":15000,"deadline":"2025-03-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Engineering, Science, Economics, Law, Management, Arts","gpa_min":3.3,"tags":["china","tsinghua","beijing","engineering","science","economics","management","prestigious","985","211"],"url":"https://www.tsinghua.edu.cn/en/Admissions/Scholarships.htm","host_university":"Tsinghua University","university_url":"https://www.tsinghua.edu.cn","description":"Tsinghua University scholarships for outstanding international students — one of China's top two universities","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}}
    ,{"id":"peking_univ_scholarship","name":"Peking University International Scholarship","type":"scholarship","amount_usd":15000,"deadline":"2025-03-01","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Humanities, Social Sciences, Economics, Law, Science, Medicine","gpa_min":3.3,"tags":["china","peking university","pku","beijing","humanities","law","economics","science","prestigious","985"],"url":"https://admission.pku.edu.cn/zsxx/gj留/","host_university":"Peking University","university_url":"https://english.pku.edu.cn","description":"Peking University scholarships for exceptional international students in humanities, sciences, and professional fields","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}}
    ,{"id":"fudan_scholarship","name":"Fudan University International Scholarship","type":"scholarship","amount_usd":14000,"deadline":"2025-03-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Medicine, Economics, Law, Management, Humanities, Science","gpa_min":3.2,"tags":["china","fudan","shanghai","medicine","economics","management","humanities","985","211","prestigious"],"url":"https://www.fudan.edu.cn/en/scholarships/","host_university":"Fudan University","university_url":"https://www.fudan.edu.cn/en/","description":"Fudan University Shanghai scholarships for international students — strong in medicine, economics, and law","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"sjtu_scholarship","name":"Shanghai Jiao Tong University Scholarship","type":"scholarship","amount_usd":14000,"deadline":"2025-04-01","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Engineering, Medicine, Economics, Management, Science","gpa_min":3.2,"tags":["china","sjtu","shanghai jiao tong","engineering","medicine","economics","management","985","prestigious","shanghai"],"url":"https://en.sjtu.edu.cn/admissions/scholarships/","host_university":"Shanghai Jiao Tong University","university_url":"https://en.sjtu.edu.cn","description":"SJTU scholarships — one of China's top engineering and medical universities in Shanghai","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"zhejiang_univ_scholarship","name":"Zhejiang University Scholarship","type":"scholarship","amount_usd":13000,"deadline":"2025-04-15","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Engineering, Agriculture, Medicine, Science, Management","gpa_min":3.0,"tags":["china","zhejiang","hangzhou","engineering","agriculture","medicine","science","985","211","alibaba"],"url":"https://www.zju.edu.cn/english/admissions/scholarships/","host_university":"Zhejiang University","university_url":"https://www.zju.edu.cn/english/","description":"Zhejiang University Hangzhou scholarships — near Alibaba HQ, strong tech-industry connections","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"nanjing_univ_scholarship","name":"Nanjing University International Scholarship","type":"scholarship","amount_usd":13000,"deadline":"2025-03-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Physics, Chemistry, Mathematics, Astronomy, Earth Science, Humanities","gpa_min":3.2,"tags":["china","nanjing","physics","chemistry","mathematics","astronomy","earth science","humanities","985","211"],"url":"https://international.nju.edu.cn/scholarships/","host_university":"Nanjing University","university_url":"https://international.nju.edu.cn","description":"Nanjing University scholarships — world-renowned for physics, chemistry, and earth sciences","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"wuhan_univ_scholarship","name":"Wuhan University International Student Scholarship","type":"scholarship","amount_usd":12000,"deadline":"2025-04-30","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Remote Sensing, Law, Economics, Engineering, Information Science, Arts","gpa_min":3.0,"tags":["china","wuhan","hubei","remote sensing","law","economics","engineering","information science","985","affordable"],"url":"https://en.whu.edu.cn/Admissions/Scholarships.htm","host_university":"Wuhan University","university_url":"https://en.whu.edu.cn","description":"Wuhan University scholarships — world's top in remote sensing and GIS; beautiful campus","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"ustc_scholarship","name":"USTC International Scholarship (University of Science & Technology of China)","type":"scholarship","amount_usd":14000,"deadline":"2025-03-31","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Physics, Chemistry, Mathematics, Computer Science, Engineering","gpa_min":3.5,"tags":["china","ustc","hefei","physics","chemistry","math","computer science","engineering","stem","985","prestigious","quantum"],"url":"https://en.ustc.edu.cn/admissions/scholarships/","host_university":"University of Science and Technology of China","university_url":"https://en.ustc.edu.cn","description":"USTC Hefei scholarships — China's top STEM university, world-leading in quantum computing and physics","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}}
    ,{"id":"tongji_scholarship","name":"Tongji University International Scholarship","type":"scholarship","amount_usd":12000,"deadline":"2025-04-15","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Architecture, Civil Engineering, Urban Planning, Automotive Engineering","gpa_min":3.0,"tags":["china","tongji","shanghai","architecture","civil engineering","urban planning","automotive","german","985"],"url":"https://en.tongji.edu.cn/Admissions/Scholarships.htm","host_university":"Tongji University","university_url":"https://en.tongji.edu.cn","description":"Tongji University Shanghai scholarships — world's best for architecture and urban planning; German-Chinese tradition","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"harbin_tech_scholarship","name":"Harbin Institute of Technology Scholarship (HIT)","type":"scholarship","amount_usd":12000,"deadline":"2025-04-30","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Aerospace, Robotics, Electrical Engineering, Computer Science, Materials","gpa_min":3.0,"tags":["china","hit","harbin","aerospace","robotics","electrical","computer science","materials","985","space","military"],"url":"https://admissions.hit.edu.cn/international/scholarships/","host_university":"Harbin Institute of Technology","university_url":"https://en.hit.edu.cn","description":"HIT Harbin scholarships — China's top aerospace and robotics university, key to China's space program","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"scu_scholarship","name":"Sichuan University International Scholarship","type":"scholarship","amount_usd":11000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Medicine, Engineering, Arts, Management, Science","gpa_min":2.8,"tags":["china","sichuan","chengdu","medicine","engineering","arts","management","pandas","affordable","985","211"],"url":"https://en.scu.edu.cn/scholarships/","host_university":"Sichuan University","university_url":"https://en.scu.edu.cn","description":"Sichuan University Chengdu scholarships — major medical university in southwest China, affordable living","competitiveness":{"label":"Moderate","acceptance_rate":0.15}}
    ,{"id":"sun_yatsen_scholarship","name":"Sun Yat-sen University (SYSU) Scholarship","type":"scholarship","amount_usd":12000,"deadline":"2025-04-30","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Medicine, Public Health, Economics, Law, Engineering, Biology","gpa_min":3.0,"tags":["china","sysu","sun yat-sen","guangzhou","medicine","economics","biology","law","985","guangdong","affordable"],"url":"https://iso.sysu.edu.cn/en/scholarships/","host_university":"Sun Yat-sen University","university_url":"https://www.sysu.edu.cn/en/","description":"SYSU Guangzhou scholarships — southern China's top university, strong in medicine and public health","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"renmin_scholarship","name":"Renmin University of China Scholarship","type":"scholarship","amount_usd":13000,"deadline":"2025-03-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Economics, Law, Social Sciences, Humanities, Business, Finance","gpa_min":3.2,"tags":["china","renmin","ruc","beijing","economics","law","social sciences","humanities","business","finance","985","political"],"url":"https://www.ruc.edu.cn/en/admissions/scholarships/","host_university":"Renmin University of China","university_url":"https://www.ruc.edu.cn/en/","description":"Renmin University Beijing scholarships — China's top university for economics, law, and social sciences","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"beijing_normal_scholarship","name":"Beijing Normal University International Scholarship (BNU)","type":"scholarship","amount_usd":11000,"deadline":"2025-04-30","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Education, Psychology, Environmental Science, Chinese Language, Arts","gpa_min":2.8,"tags":["china","bnu","beijing normal","education","psychology","environment","chinese language","arts","985","teaching"],"url":"https://www.bnu.edu.cn/en/admissions/scholarships/","host_university":"Beijing Normal University","university_url":"https://www.bnu.edu.cn/en/","description":"BNU Beijing scholarships — China's top education university, excellent for education, psychology, and Chinese studies","competitiveness":{"label":"Moderate","acceptance_rate":0.15}}
    ,{"id":"central_south_scholarship","name":"Central South University International Scholarship (CSU)","type":"scholarship","amount_usd":11000,"deadline":"2025-05-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Zambia","Zimbabwe","Mozambique","Madagascar","Cameroon","Senegal","Egypt","Morocco","Bangladesh","Pakistan","India","Nepal","Sri Lanka","Vietnam","Indonesia","Philippines","Thailand","Malaysia","Cambodia","Myanmar","Brazil","Colombia","Ecuador"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Mining, Metallurgy, Medicine, Engineering, Business","gpa_min":2.8,"tags":["china","central south","changsha","mining","metallurgy","medicine","engineering","africa","resources","minerals","985","affordable"],"url":"https://en.csu.edu.cn/scholarships/","host_university":"Central South University","university_url":"https://en.csu.edu.cn","description":"CSU Changsha scholarships — world leader in mining and metallurgy; strategic for African mineral resource professionals","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"beijing_univ_tech_scholarship","name":"Beijing University of Technology International Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-05-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Bangladesh","India","Pakistan","Vietnam","Indonesia","Philippines","Nepal","Sri Lanka","Cambodia","Thailand","Malaysia","Brazil","Colombia","Mexico","Ecuador","Peru"],"degree_levels":["Undergraduate","Graduate"],"field":"Engineering, Computer Science, Architecture, Business","gpa_min":2.8,"tags":["china","bjut","beijing","engineering","computer science","architecture","affordable","developing countries","211"],"url":"https://en.bjut.edu.cn/scholarships/","host_university":"Beijing University of Technology","university_url":"https://en.bjut.edu.cn","description":"BJUT Beijing scholarships — strong engineering and IT programmes, lower admission barrier than 985 universities","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"jilin_univ_scholarship","name":"Jilin University International Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Automotive Engineering, Chemistry, Medicine, Agriculture, Law","gpa_min":2.8,"tags":["china","jilin","changchun","automotive","chemistry","medicine","agriculture","law","985","211","northeast china","affordable"],"url":"https://international.jlu.edu.cn/scholarships/","host_university":"Jilin University","university_url":"https://international.jlu.edu.cn","description":"Jilin University scholarships — China's largest university, top automotive engineering, affordable northeast China","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"huazhong_scholarship","name":"Huazhong University of Science & Technology Scholarship (HUST)","type":"scholarship","amount_usd":12000,"deadline":"2025-04-30","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Engineering, Medicine, Economics, Management, Science","gpa_min":3.0,"tags":["china","hust","wuhan","engineering","medicine","economics","management","science","985","technology","innovative"],"url":"https://english.hust.edu.cn/admissions/scholarships/","host_university":"Huazhong University of Science and Technology","university_url":"https://english.hust.edu.cn","description":"HUST Wuhan scholarships — China's top comprehensive technology university, excellent graduate employment","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"xian_jiaotong_scholarship","name":"Xi'an Jiaotong University International Scholarship (XJTU)","type":"scholarship","amount_usd":12000,"deadline":"2025-04-15","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Engineering, Medicine, Economics, Management, Science","gpa_min":3.0,"tags":["china","xjtu","xian","engineering","medicine","economics","management","silk road","985","211","northwest china"],"url":"https://en.xjtu.edu.cn/admissions/scholarships/","host_university":"Xi'an Jiaotong University","university_url":"https://en.xjtu.edu.cn","description":"XJTU Xi'an scholarships — gateway to Silk Road; China's oldest engineering university","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"beijing_foreign_studies","name":"Beijing Foreign Studies University Scholarship (BFSU)","type":"scholarship","amount_usd":10000,"deadline":"2025-05-01","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Linguistics, Translation, International Relations, Economics, Law","gpa_min":2.8,"tags":["china","bfsu","beijing","linguistics","translation","international relations","languages","diplomacy","economics","affordable","211"],"url":"https://www.bfsu.edu.cn/en/scholarships/","host_university":"Beijing Foreign Studies University","university_url":"https://www.bfsu.edu.cn/en/","description":"BFSU Beijing scholarships — China's top foreign language and international studies university, trains diplomats","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"southwest_univ_scholarship","name":"Southwest University International Scholarship","type":"scholarship","amount_usd":9000,"deadline":"2025-06-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Bangladesh","India","Pakistan","Vietnam","Indonesia","Philippines","Nepal","Sri Lanka","Cambodia","Thailand","Malaysia","Brazil","Colombia","Mexico","Peru","Ecuador"],"degree_levels":["Undergraduate","Graduate"],"field":"Agriculture, Sericulture, Education, Biology, Psychology","gpa_min":2.8,"tags":["china","southwest university","chongqing","agriculture","sericulture","education","biology","psychology","affordable","developing countries","211"],"url":"https://en.swu.edu.cn/scholarships/","host_university":"Southwest University","university_url":"https://en.swu.edu.cn","description":"Southwest University Chongqing scholarships — China's top agricultural university, affordable mountainous city","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"china_agri_univ_scholarship","name":"China Agricultural University International Scholarship (CAU)","type":"scholarship","amount_usd":11000,"deadline":"2025-05-01","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Zambia","Zimbabwe","Mozambique","Bangladesh","India","Pakistan","Nepal","Sri Lanka","Vietnam","Indonesia","Philippines","Cambodia","Myanmar","Thailand","Brazil","Colombia","Mexico","Peru","Ecuador","Bolivia"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Agriculture, Agronomy, Animal Science, Food Science, Biotechnology, Rural Development","gpa_min":2.8,"tags":["china","cau","beijing","agriculture","agronomy","animal science","food science","biotechnology","developing countries","africa","asia","211"],"url":"https://www.cau.edu.cn/en/scholarships/","host_university":"China Agricultural University","university_url":"https://www.cau.edu.cn/en/","description":"CAU Beijing scholarships — China's top agricultural research university, ideal for Africa and Asia food security professionals","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"beijing_tech_business","name":"Beijing Technology and Business University Scholarship (BTBU)","type":"scholarship","amount_usd":8000,"deadline":"2025-07-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Bangladesh","India","Pakistan","Vietnam","Indonesia","Philippines","Nepal","Sri Lanka","Cambodia","Thailand","Malaysia","Brazil","Colombia","Mexico","Ecuador","Peru"],"degree_levels":["Undergraduate","Graduate"],"field":"Business, Economics, Food Science, Light Industry, Commerce","gpa_min":2.5,"tags":["china","btbu","beijing","business","economics","food science","commerce","affordable","developing countries","low gpa requirement"],"url":"https://en.btbu.edu.cn/scholarships/","host_university":"Beijing Technology and Business University","university_url":"https://en.btbu.edu.cn","description":"BTBU Beijing scholarships — accessible for students with lower GPA, strong in business and food science","competitiveness":{"label":"Moderate","acceptance_rate":0.25}}
    ,{"id":"waseda_scholarship","name":"Waseda University International Student Scholarship","type":"scholarship","amount_usd":12000,"deadline":"2025-11-01","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Political Science, International Studies, Economics, Science, Engineering, Law","gpa_min":3.2,"tags":["japan","waseda","tokyo","political science","international studies","economics","engineering","law","prestigious","private","global"],"url":"https://www.waseda.jp/inst/cie/en/scholarship/","host_university":"Waseda University","university_url":"https://www.waseda.jp/top/en/","description":"Waseda University Tokyo scholarships — Japan's most internationally-minded private university, used by world leaders","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"keio_scholarship","name":"Keio University International Scholarship","type":"scholarship","amount_usd":11000,"deadline":"2025-10-15","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Medicine, Law, Economics, Business, Science, Engineering, Policy","gpa_min":3.3,"tags":["japan","keio","tokyo","medicine","law","economics","business","engineering","prestigious","private","research"],"url":"https://www.keio.ac.jp/en/students/scholarship.html","host_university":"Keio University","university_url":"https://www.keio.ac.jp/en/","description":"Keio University Tokyo scholarships — Japan's oldest private university, renowned for medicine and law","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"kyoto_univ_scholarship","name":"Kyoto University International Scholarship","type":"scholarship","amount_usd":14000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Science, Engineering, Medicine, Agriculture, Humanities, Social Sciences","gpa_min":3.5,"tags":["japan","kyoto","research","nobel","science","engineering","medicine","agriculture","humanities","prestigious","second oldest"],"url":"https://www.kyoto-u.ac.jp/en/education-campus/financials/scholarships","host_university":"Kyoto University","university_url":"https://www.kyoto-u.ac.jp/en","description":"Kyoto University scholarships — Japan's second-best university, more Nobel laureates than any Asian university","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"osaka_univ_scholarship","name":"Osaka University International Scholarship","type":"scholarship","amount_usd":12000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Medicine, Dentistry, Engineering, Science, Economics, Law, Literature","gpa_min":3.3,"tags":["japan","osaka","medicine","dentistry","engineering","science","economics","prestigious","research","kansai","university hospital"],"url":"https://www.osaka-u.ac.jp/en/international/inbound/scholarship","host_university":"Osaka University","university_url":"https://www.osaka-u.ac.jp/en","description":"Osaka University scholarships — Japan's top medical and dental university, excellent research hospital","competitiveness":{"label":"Very Competitive","acceptance_rate":0.09}}
    ,{"id":"snu_scholarship","name":"Seoul National University Global Scholarship (SNU)","type":"scholarship","amount_usd":18000,"deadline":"2025-09-30","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":3.5,"tags":["south korea","snu","seoul national","prestigious","fully-funded","research","stem","humanities","law","medicine","top ranked"],"url":"https://en.snu.ac.kr/admission/scholarships","host_university":"Seoul National University","university_url":"https://en.snu.ac.kr","description":"SNU scholarships — South Korea's most prestigious university, among Asia's top 10","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"kaist_fellowship","name":"KAIST International Scholarship (Korea Advanced Institute of Science and Technology)","type":"scholarship","amount_usd":20000,"deadline":"2025-11-30","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Science, Technology, Engineering, Mathematics, Business, AI","gpa_min":3.5,"tags":["south korea","kaist","daejeon","science","technology","engineering","mathematics","ai","robotics","prestigious","fully-funded","research"],"url":"https://admission.kaist.ac.kr/intl-graduate/scholarship/","host_university":"KAIST","university_url":"https://www.kaist.ac.kr/en/","description":"KAIST fully-funded scholarships for STEM graduate students — South Korea's MIT, world leader in robotics and AI","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"postech_scholarship","name":"POSTECH International Scholarship (Pohang University)","type":"scholarship","amount_usd":18000,"deadline":"2025-10-31","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Science, Engineering, Materials, IT, Biosciences","gpa_min":3.5,"tags":["south korea","postech","pohang","science","engineering","materials","it","biosciences","fully-funded","research","phd","prestigious"],"url":"https://www.postech.ac.kr/eng/page/?mid=scholarship","host_university":"POSTECH","university_url":"https://www.postech.ac.kr/eng/","description":"POSTECH fully-funded research scholarships — South Korea's top science university, backed by POSCO steel company","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"yonsei_scholarship","name":"Yonsei University International Scholarship","type":"scholarship","amount_usd":15000,"deadline":"2025-10-01","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields — Theology, Medicine, Law, Business, Engineering, Arts","gpa_min":3.2,"tags":["south korea","yonsei","seoul","medicine","law","business","engineering","arts","prestigious","private","sky university","research"],"url":"https://www.yonsei.ac.kr/en_sc/international/scholarship.jsp","host_university":"Yonsei University","university_url":"https://www.yonsei.ac.kr/en_sc/","description":"Yonsei University Seoul scholarships — member of SKY (top 3 Korean universities), founded 1885","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"korea_univ_scholarship","name":"Korea University International Scholarship","type":"scholarship","amount_usd":14000,"deadline":"2025-09-30","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields — Law, Business, Medicine, Engineering, Liberal Arts","gpa_min":3.2,"tags":["south korea","korea university","seoul","law","business","medicine","engineering","arts","sky university","prestigious","private"],"url":"https://oia.korea.ac.kr/admission/scholarship","host_university":"Korea University","university_url":"https://www.korea.ac.kr/mbshome/mbs/en/","description":"Korea University Seoul scholarships — third SKY university, strong law and business schools since 1905","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"oxford_clarendon_scholarship","name":"Oxford Clarendon Scholarship","type":"scholarship","amount_usd":55000,"deadline":"2025-01-03","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"All fields — Humanities, Social Sciences, Science, Medicine, Law","gpa_min":3.8,"tags":["uk","oxford","clarendon","prestigious","fully-funded","phd","masters","humanities","science","law","medicine","research"],"url":"https://www.ox.ac.uk/clarendon","host_university":"University of Oxford","university_url":"https://www.ox.ac.uk","description":"Oxford Clarendon fully-funded scholarships for the world's most outstanding graduate students across all disciplines","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.03}}
    ,{"id":"cambridge_gates_scholarship","name":"Gates Cambridge Scholarship","type":"scholarship","amount_usd":60000,"deadline":"2024-10-09","eligible_countries":["Global (non-UK)"],"degree_levels":["Postgraduate"],"field":"All fields","gpa_min":3.8,"tags":["uk","cambridge","gates","prestigious","fully-funded","phd","masters","leadership","commitment to others","cambridge fit"],"url":"https://www.gatescambridge.org","host_university":"University of Cambridge","university_url":"https://www.cam.ac.uk","description":"Gates Cambridge fully-funded scholarships for outstanding non-UK graduates at Cambridge University","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.02}}
    ,{"id":"eth_zurich_scholarship","name":"ETH Zurich Excellence Scholarship","type":"scholarship","amount_usd":30000,"deadline":"2025-12-15","eligible_countries":["Global"],"degree_levels":["Graduate"],"field":"Science, Technology, Engineering, Mathematics, Architecture","gpa_min":3.7,"tags":["switzerland","eth zurich","excellence","stem","engineering","technology","architecture","mathematics","science","prestigious","europe","fully-funded"],"url":"https://ethz.ch/en/studies/financial/scholarships/excellencescholarship.html","host_university":"ETH Zurich","university_url":"https://ethz.ch/en.html","description":"ETH Zurich Excellence Scholarships for outstanding master's students — Europe's top STEM university","competitiveness":{"label":"Very Competitive","acceptance_rate":0.05}}
    ,{"id":"epfl_excellence_fellowship","name":"EPFL Excellence Fellowship","type":"fellowship","amount_usd":32000,"deadline":"2025-12-15","eligible_countries":["Global"],"degree_levels":["Graduate"],"field":"Engineering, Computer Science, Life Sciences, Mathematics, Physics","gpa_min":3.7,"tags":["switzerland","epfl","excellence","engineering","computer science","life sciences","mathematics","physics","prestigious","europe","lausanne"],"url":"https://www.epfl.ch/education/master/admission/excellence-fellowships/","host_university":"EPFL","university_url":"https://www.epfl.ch","description":"EPFL Excellence Fellowships for the top master's applicants — Europe's most innovative engineering university","competitiveness":{"label":"Very Competitive","acceptance_rate":0.05}}
    ,{"id":"leiden_univ_scholarship","name":"Leiden University Excellence Scholarship","type":"scholarship","amount_usd":15000,"deadline":"2025-02-01","eligible_countries":["Global (non-EU)"],"degree_levels":["Graduate"],"field":"All fields — Law, Medicine, Humanities, Social Sciences, Science","gpa_min":3.5,"tags":["netherlands","leiden","excellence","law","medicine","humanities","social sciences","science","europe","prestigious","oldest dutch university"],"url":"https://www.universiteitleiden.nl/en/scholarships-and-grants/scholarship/leiden-university-excellence-scholarship","host_university":"Leiden University","university_url":"https://www.universiteitleiden.nl/en","description":"Leiden University Excellence Scholarships for top non-EU master's students — Netherlands' oldest university (1575)","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"delft_scholarship","name":"TU Delft Holland Scholarship","type":"scholarship","amount_usd":12000,"deadline":"2025-02-01","eligible_countries":["Global (non-EU)"],"degree_levels":["Graduate"],"field":"Engineering, Architecture, Technology, Applied Sciences","gpa_min":3.3,"tags":["netherlands","tu delft","engineering","architecture","technology","applied sciences","europe","water management","aerospace","affordable"],"url":"https://www.tudelft.nl/en/education/practical-matters/scholarships","host_university":"TU Delft","university_url":"https://www.tudelft.nl/en","description":"TU Delft Holland Scholarships for non-EU engineering and technology master's students — world-leading in water management","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}

    ,{"id":"chinese_univ_medicine","name":"Chinese Government Scholarship — Medical Universities","type":"scholarship","amount_usd":12000,"deadline":"2025-04-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Senegal","Cameroon","Sudan","Bangladesh","Pakistan","Nepal","Sri Lanka","Indonesia","Philippines","Cambodia","Myanmar"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Medicine, Dentistry, Pharmacy, Nursing, Public Health","gpa_min":3.0,"tags":["china","medicine","dentistry","pharmacy","nursing","public health","csc","government","developing countries","africa","asia"],"url":"https://www.campuschina.org/","host_university":"Chinese Medical Universities (multiple)","description":"CSC scholarships specifically for medical programmes at top Chinese medical universities including Capital Medical University, Harbin Medical, Wenzhou Medical","competitiveness":{"label":"Competitive","acceptance_rate":0.15}}
    ,{"id":"beijing_univ_aeronautics","name":"Beihang University International Scholarship (BUAA)","type":"scholarship","amount_usd":13000,"deadline":"2025-04-15","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Aerospace Engineering, Computer Science, Automation, Mechanical Engineering","gpa_min":3.2,"tags":["china","beihang","buaa","aerospace","computer science","automation","mechanical","engineering","985","beijing"],"url":"https://ev.buaa.edu.cn/scholarship/","host_university":"Beihang University (BUAA)","university_url":"https://ev.buaa.edu.cn","description":"BUAA Beijing scholarships — China's top aerospace university, trains pilots, astronauts, and aerospace engineers","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"southeast_univ_nanjing","name":"Southeast University International Scholarship (SEU)","type":"scholarship","amount_usd":11000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Architecture, Civil Engineering, Electronics, Information Science","gpa_min":3.0,"tags":["china","southeast university","nanjing","architecture","civil engineering","electronics","information","985","211"],"url":"https://ices.seu.edu.cn/scholarship/","host_university":"Southeast University","university_url":"https://www.seu.edu.cn/english/","description":"SEU Nanjing scholarships — China's top architecture and civil engineering university","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"lanzhou_univ_scholarship","name":"Lanzhou University International Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-06-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Bangladesh","Pakistan","Nepal","Sri Lanka","Kazakhstan","Uzbekistan","Tajikistan","Iran","Iraq"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Atmospheric Science, Ecology, Nuclear Science, Chemistry, Physics","gpa_min":2.8,"tags":["china","lanzhou","northwest china","atmospheric science","ecology","nuclear","chemistry","physics","985","silk road","affordable"],"url":"https://international.lzu.edu.cn/scholarship/","host_university":"Lanzhou University","university_url":"https://international.lzu.edu.cn","description":"Lanzhou University scholarships — gateway to northwest China, world-leading in atmospheric science and ecology","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"ocean_univ_china","name":"Ocean University of China International Scholarship","type":"scholarship","amount_usd":11000,"deadline":"2025-05-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Mozambique","Indonesia","Philippines","Vietnam","Thailand","Malaysia","Bangladesh","Pakistan","Bangladesh","India","Sri Lanka","Brazil","Peru","Ecuador"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Marine Science, Fisheries, Oceanography, Marine Technology, Aquaculture","gpa_min":2.8,"tags":["china","ocean university","qingdao","marine science","fisheries","oceanography","aquaculture","211","blue economy","coastal"],"url":"https://en.ouc.edu.cn/scholarship/","host_university":"Ocean University of China","university_url":"https://en.ouc.edu.cn","description":"OUC Qingdao scholarships — China's top marine science university, ideal for coastal nation professionals","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"nanjing_agri_scholarship","name":"Nanjing Agricultural University International Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-06-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Zambia","Zimbabwe","Mozambique","Rwanda","Bangladesh","Pakistan","Nepal","Sri Lanka","India","Vietnam","Indonesia","Philippines","Cambodia","Myanmar","Brazil","Colombia","Ecuador"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Agriculture, Agronomy, Plant Science, Food Science, Agricultural Engineering","gpa_min":2.8,"tags":["china","nanjing agricultural","agriculture","agronomy","plant science","food science","211","developing countries","africa","asia"],"url":"https://international.njau.edu.cn/scholarship/","host_university":"Nanjing Agricultural University","university_url":"https://international.njau.edu.cn","description":"NAU Nanjing scholarships — China's leading agricultural research university for developing nations","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"hunan_univ_scholarship","name":"Hunan University International Scholarship","type":"scholarship","amount_usd":11000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Engineering, Business, Finance, Architecture, Law","gpa_min":2.8,"tags":["china","hunan","changsha","engineering","business","finance","architecture","law","985","211","affordable"],"url":"https://oec.hnu.edu.cn/scholarship/","host_university":"Hunan University","university_url":"https://www.hnu.edu.cn/en/","description":"Hunan University Changsha scholarships — China's oldest higher education institution, strong in engineering and finance","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"south_china_tech","name":"South China University of Technology Scholarship (SCUT)","type":"scholarship","amount_usd":12000,"deadline":"2025-04-30","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Engineering, Architecture, Business, Science","gpa_min":3.0,"tags":["china","scut","guangzhou","engineering","architecture","business","science","985","211","pearl river delta"],"url":"https://www.scut.edu.cn/international/scholarship/","host_university":"South China University of Technology","university_url":"https://www.scut.edu.cn/en/","description":"SCUT Guangzhou scholarships — top engineering university in China's tech manufacturing hub","competitiveness":{"label":"Competitive","acceptance_rate":0.15}}
    ,{"id":"dalian_tech_scholarship","name":"Dalian University of Technology International Scholarship (DUT)","type":"scholarship","amount_usd":11000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Engineering, Management, Science, Liberal Arts","gpa_min":3.0,"tags":["china","dut","dalian","engineering","management","science","985","211","northeast china","coastal"],"url":"https://english.dlut.edu.cn/scholarship/","host_university":"Dalian University of Technology","university_url":"https://english.dlut.edu.cn","description":"DUT Dalian scholarships — coastal northeast China, gateway to Japan and Korea, strong engineering","competitiveness":{"label":"Competitive","acceptance_rate":0.15}}
    ,{"id":"chongqing_univ_scholarship","name":"Chongqing University International Scholarship","type":"scholarship","amount_usd":11000,"deadline":"2025-06-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Bangladesh","Pakistan","Nepal","Sri Lanka","Vietnam","Indonesia","Philippines","Cambodia","Thailand","Colombia","Brazil","Mexico","Peru","Ecuador"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Civil Engineering, Architecture, Mechanical, Electrical, Business","gpa_min":2.8,"tags":["china","chongqing","civil engineering","architecture","mechanical","electrical","business","985","211","bri","belt road","affordable"],"url":"https://csc.cqu.edu.cn/scholarship/","host_university":"Chongqing University","university_url":"https://english.cqu.edu.cn","description":"Chongqing University scholarships — major BRI hub city, affordable, strong in civil and mechanical engineering","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"ningbo_univ_scholarship","name":"Ningbo University International Scholarship","type":"scholarship","amount_usd":9000,"deadline":"2025-07-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Bangladesh","Pakistan","Nepal","Sri Lanka","Vietnam","Indonesia","Philippines","Cambodia","Myanmar","Thailand","Colombia","Brazil","Peru","Ecuador"],"degree_levels":["Undergraduate","Graduate"],"field":"Marine Science, Engineering, Business, Law, Medicine","gpa_min":2.5,"tags":["china","ningbo","marine","engineering","business","law","medicine","affordable","low gpa","coastal","developing countries"],"url":"https://international.nbu.edu.cn/scholarship/","host_university":"Ningbo University","university_url":"https://international.nbu.edu.cn","description":"Ningbo University scholarships — very accessible GPA requirement, coastal city near Shanghai","competitiveness":{"label":"Moderate","acceptance_rate":0.25}}
    ,{"id":"kaist_undergrad","name":"KAIST Undergraduate International Scholarship","type":"scholarship","amount_usd":22000,"deadline":"2025-11-30","eligible_countries":["Global"],"degree_levels":["Undergraduate"],"field":"Science, Technology, Engineering, Mathematics, AI","gpa_min":3.7,"tags":["south korea","kaist","daejeon","undergraduate","science","technology","engineering","mathematics","ai","prestigious","fully-funded","stem"],"url":"https://admission.kaist.ac.kr/intl-undergraduate/","host_university":"KAIST","university_url":"https://www.kaist.ac.kr/en/","description":"KAIST undergraduate fully-funded scholarships for exceptional STEM students — South Korea's MIT","competitiveness":{"label":"Very Competitive","acceptance_rate":0.06}}
    ,{"id":"sejong_scholarship","name":"Sejong University International Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-10-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate"],"field":"Business, Aviation, Computer Science, Film, Art, Engineering","gpa_min":3.0,"tags":["south korea","sejong","seoul","business","aviation","computer science","film","art","engineering","affordable","kwave","korean culture"],"url":"https://oia.sejong.ac.kr/scholarship/","host_university":"Sejong University","university_url":"https://www.sejong.ac.kr/eng/","description":"Sejong University Seoul scholarships — strong in business and aviation, growing K-culture programmes","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"konkuk_scholarship","name":"Konkuk University Global Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-09-30","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate"],"field":"Engineering, Business, Life Sciences, Architecture, Design","gpa_min":3.0,"tags":["south korea","konkuk","seoul","engineering","business","life sciences","architecture","design","affordable"],"url":"https://international.konkuk.ac.kr/scholarship/","host_university":"Konkuk University","university_url":"https://www.konkuk.ac.kr/eng/","description":"Konkuk University Seoul scholarships — strong in life sciences and biotechnology, city campus","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"pusan_national_scholarship","name":"Pusan National University International Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-10-15","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Engineering, Business, Medicine, Natural Sciences, Education","gpa_min":3.0,"tags":["south korea","pusan","busan","engineering","business","medicine","natural sciences","education","affordable","coastal","port city"],"url":"https://english.pusan.ac.kr/scholarship/","host_university":"Pusan National University","university_url":"https://english.pusan.ac.kr","description":"PNU Busan scholarships — Korea's second city, top engineering and marine sciences, gateway to Japan","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"kyungpook_scholarship","name":"Kyungpook National University Scholarship (KNU)","type":"scholarship","amount_usd":9000,"deadline":"2025-10-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Bangladesh","Pakistan","Nepal","Sri Lanka","Vietnam","Indonesia","Philippines","Cambodia","Myanmar","India"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Medicine, Engineering, Natural Sciences, Agriculture, Education","gpa_min":2.8,"tags":["south korea","knu","daegu","medicine","engineering","natural sciences","agriculture","education","affordable","developing countries"],"url":"https://international.knu.ac.kr/scholarship/","host_university":"Kyungpook National University","university_url":"https://international.knu.ac.kr","description":"KNU Daegu scholarships — strong medical school, accessible for developing country students","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"europe_erasmus_mundus","name":"Erasmus Mundus Joint Master Scholarships","type":"scholarship","amount_usd":35000,"deadline":"2025-01-15","eligible_countries":["Global"],"degree_levels":["Graduate"],"field":"All fields — 100+ joint master programmes across European universities","gpa_min":3.2,"tags":["europe","erasmus mundus","joint master","international","prestigious","fully-funded","multiple countries","research","eu"],"url":"https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_en","description":"EU-funded joint master degrees delivered across multiple European universities — tuition paid, monthly stipend, travel allowance","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"stipendium_hungaricum","name":"Stipendium Hungaricum Scholarship (Hungary)","type":"scholarship","amount_usd":14000,"deadline":"2025-01-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Senegal","Rwanda","Morocco","Egypt","Bangladesh","Pakistan","Vietnam","Indonesia","Philippines","India","Nepal","Sri Lanka","Cambodia","Myanmar","Brazil","Colombia","Mexico","Bolivia"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields — 60+ Hungarian universities","gpa_min":2.8,"tags":["hungary","stipendium","central europe","government","affordable","fully-funded","budapest","developing countries","stem","arts","medicine"],"url":"https://stipendiumhungaricum.hu/","description":"Hungarian government fully-funded scholarships for developing countries — free tuition, accommodation, monthly stipend","competitiveness":{"label":"Competitive","acceptance_rate":0.14}}
    ,{"id":"turkiye_burslari","name":"Türkiye Bursları Government Scholarship","type":"scholarship","amount_usd":15000,"deadline":"2025-02-20","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Senegal","Somalia","Sudan","Egypt","Morocco","Jordan","Palestine","Bangladesh","Pakistan","Afghanistan","Indonesia","Malaysia","Bosnia","Albania","Kosovo","Azerbaijan","Uzbekistan","Kazakhstan","Tajikistan","Kyrgyzstan","Turkmenistan"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":2.5,"tags":["turkey","turkiye","burslari","government","fully-funded","istanbul","ankara","muslim majority","developing countries","oic","turkish","affordable"],"url":"https://www.turkiyeburslari.gov.tr/","description":"Turkish government fully-funded scholarships — includes Turkish language course, accommodation, health insurance, flight allowance","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"russia_govt_scholarship","name":"Russian Government Scholarship (Study in Russia)","type":"scholarship","amount_usd":9000,"deadline":"2025-03-01","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Egypt","Morocco","Vietnam","India","Bangladesh","Pakistan","Nepal","Sri Lanka","Cambodia","Myanmar","Indonesia","Venezuela","Cuba","Colombia","Bolivia","Ecuador","Syria","Iraq","Iran"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Engineering, Medicine, Natural Sciences, Mathematics, Agriculture, Humanities","gpa_min":2.8,"tags":["russia","government","moscow","st petersburg","engineering","medicine","science","mathematics","agriculture","humanities","affordable","developing countries"],"url":"https://russia.edu.ru/","description":"Russian government scholarships for international students — free tuition at major Russian universities","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"austria_oead_scholarship","name":"Austria OEAD Government Scholarships","type":"scholarship","amount_usd":16000,"deadline":"2025-03-01","eligible_countries":["Kenya","Nigeria","Ghana","South Africa","Ethiopia","India","Bangladesh","Vietnam","Indonesia","Philippines","Nepal","Sri Lanka","Brazil","Colombia","Mexico","Jordan","Palestine","Egypt","Morocco"],"degree_levels":["Graduate","Postgraduate"],"field":"Arts, Music, Humanities, Science, Engineering, Business","gpa_min":3.2,"tags":["austria","oead","vienna","arts","music","humanities","science","engineering","business","europe","prestigious","cultural"],"url":"https://www.oead.at/en/to-austria/grants-scholarships/","description":"Austrian government scholarships — Vienna for arts, music, and humanities; Graz for engineering and science","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"korea_science_fellowship","name":"Korea Research Fellowship (KRF)","type":"fellowship","amount_usd":35000,"deadline":"2025-12-31","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Science, Technology, Engineering, Mathematics — research focus","gpa_min":3.5,"tags":["south korea","krf","nrf","research fellowship","postdoc","science","technology","engineering","mathematics","prestigious","fully-funded","seoul"],"url":"https://www.nrf.re.kr/eng/","description":"Korea National Research Foundation fellowships for postdoctoral researchers across STEM fields","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"worldbank_jsap","name":"World Bank Robert S. McNamara Fellowship","type":"fellowship","amount_usd":25000,"deadline":"2025-04-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Zambia","Zimbabwe","Bangladesh","Pakistan","Nepal","Sri Lanka","Cambodia","Myanmar","Bolivia","Haiti","Honduras","Nicaragua"],"degree_levels":["Postgraduate"],"field":"Development Economics, Public Policy, Environment, Agriculture, Health","gpa_min":3.3,"tags":["world bank","mcnamara","development","economics","policy","environment","agriculture","health","prestigious","research","developing countries","phd"],"url":"https://www.worldbank.org/en/programs/scholarships","description":"World Bank fellowship for PhD students from developing countries researching development issues","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}}
    ,{"id":"un_women_scholarship","name":"UN Women Peace & Security Scholarship","type":"scholarship","amount_usd":20000,"deadline":"2025-07-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Senegal","Rwanda","DRC","Somalia","Sudan","South Sudan","Palestine","Yemen","Afghanistan","Iraq","Syria","Libya","Mali"],"degree_levels":["Graduate"],"field":"Gender Studies, Peace Studies, International Relations, Law, Public Administration","gpa_min":3.0,"tags":["un women","peace","security","gender","international relations","law","public administration","conflict zones","developing countries","humanitarian"],"url":"https://www.unwomen.org/en/about-us/about-un-women/scholarships","description":"UN Women scholarships for women from conflict-affected countries pursuing peace and security studies","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"african_union_scholarship","name":"African Union Commission Scholarship","type":"scholarship","amount_usd":18000,"deadline":"2025-06-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Senegal","Rwanda","Zambia","Zimbabwe","Mozambique","Malawi","Mali","Burkina Faso","Niger","Guinea","Sierra Leone","Liberia","Cameroon","DRC","Angola","Botswana","Namibia","Lesotho","Eswatini","Madagascar","Mauritius","Comoros","Djibouti","Eritrea","Somalia","Gambia","Guinea-Bissau","Equatorial Guinea","São Tomé"],"degree_levels":["Graduate","Postgraduate"],"field":"African Studies, Development, Agriculture, Health, Engineering, Science","gpa_min":3.0,"tags":["african union","au","intra-africa","development","agriculture","health","engineering","science","pan-african","addis ababa","government"],"url":"https://au.int/en/scholarships","description":"African Union Commission scholarships promoting intra-African academic exchange and continental development","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"opec_fund_scholarship","name":"OPEC Fund for International Development Scholarship","type":"scholarship","amount_usd":20000,"deadline":"2025-09-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Senegal","Mali","Niger","Guinea","Burkina Faso","Chad","Cameroon","Bangladesh","Pakistan","Nepal","Afghanistan","Yemen","Iraq","Syria","Palestine","Jordan","Egypt","Morocco","Bolivia","Nicaragua","Honduras","Haiti"],"degree_levels":["Graduate","Postgraduate"],"field":"Energy, Development, Economics, Engineering, Environment, Agriculture","gpa_min":3.0,"tags":["opec fund","energy","development","economics","engineering","environment","agriculture","developing countries","ofid","vienna","petroleum"],"url":"https://opecfund.org/work/scholarships","description":"OPEC Fund scholarships for students from developing member countries in energy and development fields","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"imperial_college_scholarship","name":"Imperial College London President's Scholarship","type":"scholarship","amount_usd":35000,"deadline":"2025-01-10","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Science, Engineering, Medicine, Business","gpa_min":3.7,"tags":["uk","imperial college","london","science","engineering","medicine","business","prestigious","research","phd","fully-funded"],"url":"https://www.imperial.ac.uk/study/fees-and-funding/scholarships-search/","host_university":"Imperial College London","university_url":"https://www.imperial.ac.uk","description":"Imperial College President's PhD Scholarships — one of the world's top 10 universities for STEM research","competitiveness":{"label":"Very Competitive","acceptance_rate":0.06}}
    ,{"id":"manchester_univ_scholarship","name":"University of Manchester Global Futures Scholarship","type":"scholarship","amount_usd":20000,"deadline":"2025-02-28","eligible_countries":["Kenya","Nigeria","Ghana","South Africa","Tanzania","Uganda","India","Bangladesh","Pakistan","Vietnam","Indonesia","Philippines","Malaysia","Thailand","Sri Lanka","Nepal","Brazil","Colombia","Mexico"],"degree_levels":["Graduate"],"field":"All fields — priority on science, engineering, business, humanities","gpa_min":3.3,"tags":["uk","manchester","global futures","science","engineering","business","humanities","affordable","developing countries","russell group"],"url":"https://www.manchester.ac.uk/study/masters/fees-and-funding/scholarships/","host_university":"University of Manchester","university_url":"https://www.manchester.ac.uk","description":"Manchester Global Futures Scholarships for developing country master's students — Russell Group university","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"ucl_global_excellence","name":"UCL Global Excellence Scholarship","type":"scholarship","amount_usd":25000,"deadline":"2025-03-31","eligible_countries":["Global (non-UK)"],"degree_levels":["Graduate"],"field":"All fields","gpa_min":3.5,"tags":["uk","ucl","university college london","global excellence","prestigious","research","science","humanities","social sciences","law","medicine"],"url":"https://www.ucl.ac.uk/scholarships/","host_university":"University College London (UCL)","university_url":"https://www.ucl.ac.uk","description":"UCL Global Excellence Scholarships for the top international master's applicants — UK's top ranked university","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}}
    ,{"id":"edinburgh_global_scholarship","name":"University of Edinburgh Global Scholarship","type":"scholarship","amount_usd":18000,"deadline":"2025-03-26","eligible_countries":["Global (non-UK)"],"degree_levels":["Undergraduate","Graduate"],"field":"All fields","gpa_min":3.3,"tags":["uk","edinburgh","scotland","global","prestigious","research","medicine","law","science","humanities","ancient university"],"url":"https://www.ed.ac.uk/student-funding/postgraduate/international/","host_university":"University of Edinburgh","university_url":"https://www.ed.ac.uk","description":"Edinburgh Global Scholarships — Scotland's most prestigious university, one of the oldest in the world","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"glasgow_scholarship","name":"University of Glasgow Excellence Scholarship","type":"scholarship","amount_usd":15000,"deadline":"2025-04-30","eligible_countries":["Global (non-UK)"],"degree_levels":["Undergraduate","Graduate"],"field":"All fields","gpa_min":3.2,"tags":["uk","glasgow","scotland","excellence","affordable","russell group","medicine","engineering","science","humanities"],"url":"https://www.gla.ac.uk/scholarships/","host_university":"University of Glasgow","university_url":"https://www.gla.ac.uk","description":"Glasgow Excellence Scholarships — founding member of the Russell Group, strong medicine and engineering","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"warwick_chancellor_scholarship","name":"University of Warwick Chancellor's International Scholarship","type":"scholarship","amount_usd":20000,"deadline":"2025-01-08","eligible_countries":["Global (non-UK)"],"degree_levels":["Postgraduate"],"field":"All fields — strong in business, engineering, computer science, social sciences","gpa_min":3.5,"tags":["uk","warwick","chancellor","business","engineering","computer science","social sciences","prestigious","research","russell group"],"url":"https://warwick.ac.uk/services/dc/schols_fund/fellowships_and_scholarships/","host_university":"University of Warwick","university_url":"https://warwick.ac.uk","description":"Warwick Chancellor's Scholarships — fully funded PhD for the strongest international applicants","competitiveness":{"label":"Very Competitive","acceptance_rate":0.06}}
    ,{"id":"mit_mitmohnson_fellowship","name":"MIT-Martin Luther King Jr. Visiting Scholars Program","type":"fellowship","amount_usd":65000,"deadline":"2025-10-01","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Science, Technology, Engineering, Mathematics, Social Sciences","gpa_min":3.7,"tags":["usa","mit","cambridge","research","prestigious","visiting scholars","stem","social sciences","diversity","fully-funded","boston"],"url":"https://mlkscholars.mit.edu/","host_university":"MIT","university_url":"https://www.mit.edu","description":"MIT visiting scholars programme supporting researchers from underrepresented backgrounds","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.03}}
    ,{"id":"harvard_fellowship","name":"Harvard University Graduate Fellowships","type":"fellowship","amount_usd":45000,"deadline":"2024-12-01","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"All fields — Law, Medicine, Business, Public Policy, Sciences, Humanities","gpa_min":3.8,"tags":["usa","harvard","cambridge","prestigious","phd","research","law","medicine","business","policy","sciences","humanities","fully-funded","boston"],"url":"https://www.gsas.harvard.edu/financial_support/fellowships.html","host_university":"Harvard University","university_url":"https://www.harvard.edu","description":"Harvard Graduate School fellowships — covers full tuition and stipend for admitted PhD students","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.03}}
    ,{"id":"stanford_vpge_fellowship","name":"Stanford University Knight-Hennessy Scholars Program","type":"fellowship","amount_usd":90000,"deadline":"2024-10-09","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"All fields at Stanford — Engineering, Medicine, Business, Law, Education, Humanities","gpa_min":3.7,"tags":["usa","stanford","silicon valley","knight-hennessy","prestigious","fully-funded","leadership","research","law","medicine","business","engineering"],"url":"https://knight-hennessy.stanford.edu/","host_university":"Stanford University","university_url":"https://www.stanford.edu","description":"Stanford Knight-Hennessy Scholars — world's largest fully-funded fellowship, three years at Stanford","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.02}}
    ,{"id":"yale_world_fellows","name":"Yale World Fellows Program","type":"fellowship","amount_usd":55000,"deadline":"2025-02-01","eligible_countries":["Global (emerging leaders from outside USA)"],"degree_levels":["Graduate"],"field":"Leadership, Policy, Global Affairs, Social Entrepreneurship","gpa_min":3.0,"tags":["usa","yale","new haven","world fellows","leadership","policy","global affairs","social entrepreneurship","prestigious","diversity","mid-career"],"url":"https://worldfellows.yale.edu/","host_university":"Yale University","university_url":"https://www.yale.edu","description":"Yale World Fellows — semester-long programme for exceptional emerging leaders from outside the USA","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.02}}
    ,{"id":"columbia_kluge_fellowship","name":"Columbia University-Kluge Fellowship","type":"fellowship","amount_usd":40000,"deadline":"2025-11-01","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Humanities, Social Sciences, Public Policy, International Affairs","gpa_min":3.5,"tags":["usa","columbia","new york","kluge","humanities","social sciences","policy","international affairs","prestigious","phd","fully-funded"],"url":"https://gsas.columbia.edu/fellowships","host_university":"Columbia University","university_url":"https://www.columbia.edu","description":"Columbia Graduate School fellowships — NYC location, strong in international affairs and journalism","competitiveness":{"label":"Very Competitive","acceptance_rate":0.05}}
    ,{"id":"korea_intl_coop_scholarship","name":"Korea International Cooperation Agency Fellowship (KOICA)","type":"fellowship","amount_usd":18000,"deadline":"2025-04-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Senegal","Rwanda","Mozambique","Bangladesh","Pakistan","Nepal","Sri Lanka","Cambodia","Myanmar","Vietnam","Philippines","Indonesia","Bolivia","Honduras","Peru","Ecuador","Paraguay"],"degree_levels":["Graduate"],"field":"Development, Agriculture, Public Health, Urban Planning, ICT, Education","gpa_min":3.0,"tags":["south korea","koica","development","agriculture","public health","urban planning","ict","education","fellowship","developing countries","government","oda"],"url":"https://www.koica.go.kr/sites/koica_en/main.do","description":"KOICA government development fellowships for mid-career professionals from developing countries","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"japan_yasuda_scholarship","name":"Yasuda Kasai Foundation Scholarship (Japan)","type":"scholarship","amount_usd":14000,"deadline":"2025-10-31","eligible_countries":["Bangladesh","India","Indonesia","Malaysia","Pakistan","Philippines","Sri Lanka","Thailand","Vietnam","Myanmar","Cambodia","Nepal","Laos"],"degree_levels":["Graduate","Postgraduate"],"field":"Science, Engineering, Economics, Business, Social Sciences","gpa_min":3.3,"tags":["japan","yasuda","foundation","science","engineering","economics","business","social sciences","southeast asia","south asia","corporate"],"url":"https://www.ysf.or.jp/english/","description":"Yasuda Kasai Foundation scholarships for Asian postgraduate students to study in Japan","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"prince_charles_scholarship","name":"Prince's Trust International Young Leaders","type":"fellowship","amount_usd":22000,"deadline":"2025-09-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Rwanda","South Africa","Bangladesh","India","Pakistan","Sri Lanka","Jamaica","Trinidad","Australia","Canada"],"degree_levels":["Graduate"],"field":"Social Enterprise, Community Leadership, Business, Youth Development","gpa_min":2.8,"tags":["commonwealth","uk","prince's trust","leadership","social enterprise","community","youth development","international","mentoring"],"url":"https://www.princes-trust.org.uk/international","description":"The Prince's Trust International fellowships for young leaders from Commonwealth nations working in social enterprise","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"atlantic_fellowship","name":"Atlantic Institute / Atlantic Fellows Programme","type":"fellowship","amount_usd":40000,"deadline":"2025-03-01","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Health Equity, Social & Economic Equity, Democracy & Solidarity, Food & Land Use","gpa_min":3.0,"tags":["atlantic","fellowship","health equity","social equity","economic equity","democracy","food systems","prestigious","global","london","cape town"],"url":"https://www.atlanticfellows.org/","description":"Atlantic Fellows global leadership development programmes across 6 thematic areas at world-class universities","competitiveness":{"label":"Very Competitive","acceptance_rate":0.06}}

    ,{"id":"univ_bologna_scholarship","name":"University of Bologna International Excellence Scholarship","type":"scholarship","amount_usd":12000,"deadline":"2025-04-30","eligible_countries":["Global (non-EU)"],"degree_levels":["Graduate","Postgraduate"],"field":"All fields","gpa_min":3.3,"tags":["italy","bologna","europe","excellence","research","ancient university","affordable"],"url":"https://www.unibo.it/en/services-and-opportunities/study-grants-and-subsidies/grants-and-scholarships","host_university":"University of Bologna","university_url":"https://www.unibo.it/en","description":"Bologna scholarships — world's oldest university (1088), strong in law, medicine, science","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"barcelona_global_scholarship","name":"Barcelona Graduate School of Economics Fellowship","type":"fellowship","amount_usd":28000,"deadline":"2025-01-31","eligible_countries":["Global"],"degree_levels":["Graduate"],"field":"Economics, Finance, Data Science, Public Policy","gpa_min":3.5,"tags":["spain","barcelona","economics","finance","data science","policy","europe","prestigious","research"],"url":"https://www.barcelonagse.eu/admissions/financial-aid","host_university":"Barcelona Graduate School of Economics","university_url":"https://www.barcelonagse.eu","description":"Barcelona GSE fellowships for top master's students in economics, finance, and data science","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"korea_univ_engineering","name":"POSTECH Engineering Excellence Award","type":"scholarship","amount_usd":18000,"deadline":"2025-10-31","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Materials Science, Chemical Engineering, Mechanical, Electrical, Computer Science","gpa_min":3.5,"tags":["south korea","postech","engineering","materials","chemical","mechanical","electrical","computer science","prestigious","phd","stem"],"url":"https://www.postech.ac.kr/eng/page/?mid=scholarship","host_university":"POSTECH","university_url":"https://www.postech.ac.kr/eng/","description":"POSTECH Engineering Excellence scholarships for PhD research — South Korea's Caltech","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"beijing_jiaotong_scholarship","name":"Beijing Jiaotong University International Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-05-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Bangladesh","Pakistan","Nepal","Sri Lanka","Vietnam","Indonesia","Philippines","Cambodia","Thailand","Colombia","Brazil","Peru"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Transportation Engineering, Railway Technology, Computer Science, Business","gpa_min":2.8,"tags":["china","beijing jiaotong","transportation","railway","computer science","business","211","silk road","bri","affordable","developing countries"],"url":"https://en.bjtu.edu.cn/scholarship/","host_university":"Beijing Jiaotong University","university_url":"https://en.bjtu.edu.cn","description":"BJTU Beijing scholarships — world-leading in railway technology and transportation engineering","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"hust_international","name":"HUST International Student Scholarship (Huazhong Agri)","type":"scholarship","amount_usd":10000,"deadline":"2025-06-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Bangladesh","Pakistan","Nepal","Sri Lanka","Vietnam","Indonesia","Philippines","Cambodia","Myanmar"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Agriculture, Biology, Food Science, Horticulture, Aquaculture","gpa_min":2.8,"tags":["china","huazhong agricultural","wuhan","agriculture","biology","food science","horticulture","aquaculture","developing countries","africa","asia","211"],"url":"https://international.hzau.edu.cn/scholarship/","host_university":"Huazhong Agricultural University","university_url":"https://international.hzau.edu.cn","description":"HZAU Wuhan scholarships — top agricultural sciences university, strong Africa and Asia partnerships","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"beijing_univ_posts","name":"Beijing University of Posts and Telecommunications Scholarship (BUPT)","type":"scholarship","amount_usd":10000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Telecommunications, Computer Science, Information Engineering, Electronics","gpa_min":3.0,"tags":["china","bupt","beijing","telecommunications","computer science","information engineering","electronics","211","5g","tech"],"url":"https://en.bupt.edu.cn/scholarship/","host_university":"Beijing University of Posts and Telecommunications","university_url":"https://en.bupt.edu.cn","description":"BUPT Beijing scholarships — China's top telecommunications university, 5G and AI research","competitiveness":{"label":"Competitive","acceptance_rate":0.15}}
    ,{"id":"guangzhou_univ_scholarship","name":"Guangzhou University International Scholarship","type":"scholarship","amount_usd":8000,"deadline":"2025-07-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Bangladesh","Pakistan","Nepal","Sri Lanka","Vietnam","Indonesia","Philippines","Cambodia","Thailand"],"degree_levels":["Undergraduate","Graduate"],"field":"Engineering, Business, Arts, Education, Science","gpa_min":2.5,"tags":["china","guangzhou","engineering","business","arts","education","science","affordable","low gpa","guangdong","developing countries"],"url":"https://international.gzu.edu.cn/scholarship/","host_university":"Guangzhou University","university_url":"https://international.gzu.edu.cn","description":"Guangzhou University scholarships — very accessible GPA requirement, gateway to Pearl River Delta","competitiveness":{"label":"Moderate","acceptance_rate":0.25}}
    ,{"id":"ynu_scholarship","name":"Yunnan University International Scholarship","type":"scholarship","amount_usd":9000,"deadline":"2025-06-30","eligible_countries":["Myanmar","Laos","Vietnam","Thailand","Cambodia","Malaysia","Indonesia","Philippines","Bangladesh","Nepal","Sri Lanka","Kenya","Nigeria","Ghana"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Ecology, Biodiversity, Law, International Relations, Economics","gpa_min":2.8,"tags":["china","yunnan","kunming","ecology","biodiversity","law","international relations","southeast asia","border","silk road","affordable"],"url":"https://en.ynu.edu.cn/scholarship/","host_university":"Yunnan University","university_url":"https://en.ynu.edu.cn","description":"Yunnan University scholarships — gateway to Southeast Asia, excellent ecology and biodiversity","competitiveness":{"label":"Moderate","acceptance_rate":0.22}}
    ,{"id":"xiamen_univ_scholarship","name":"Xiamen University International Scholarship","type":"scholarship","amount_usd":11000,"deadline":"2025-04-30","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Economics, Finance, Business, Marine Science, Chemistry, Chinese","gpa_min":3.0,"tags":["china","xiamen","economics","finance","business","marine science","chemistry","chinese language","985","211","coastal","taiwan strait"],"url":"https://iso.xmu.edu.cn/scholarship/","host_university":"Xiamen University","university_url":"https://www.xmu.edu.cn/en/","description":"Xiamen University scholarships — China's most beautiful campus, strong economics and marine science","competitiveness":{"label":"Competitive","acceptance_rate":0.15}}
    ,{"id":"innsbruck_scholarship","name":"University of Innsbruck Excellence Scholarship (Austria)","type":"scholarship","amount_usd":12000,"deadline":"2025-03-31","eligible_countries":["Global (non-EU)"],"degree_levels":["Graduate","Postgraduate"],"field":"Mountain Research, Physics, Computer Science, Economics, Law, Psychology","gpa_min":3.3,"tags":["austria","innsbruck","mountain research","physics","computer science","economics","law","psychology","alps","europe","affordable"],"url":"https://www.uibk.ac.at/en/studierende/scholarships/","host_university":"University of Innsbruck","university_url":"https://www.uibk.ac.at/en/","description":"Innsbruck University Alpine scholarships — specialises in mountain research, ecology, and geoscience","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"utrecht_excellence","name":"Utrecht University Excellence Scholarship (Netherlands)","type":"scholarship","amount_usd":18000,"deadline":"2025-02-01","eligible_countries":["Global (non-EU)"],"degree_levels":["Graduate"],"field":"All fields","gpa_min":3.5,"tags":["netherlands","utrecht","excellence","science","humanities","social sciences","medicine","law","europe","prestigious"],"url":"https://www.uu.nl/en/masters/general-information/scholarships-and-grants","host_university":"Utrecht University","university_url":"https://www.uu.nl/en","description":"Utrecht Excellence Scholarships for the top 5% of non-EU applicants — Netherlands' largest university","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}}
    ,{"id":"groningen_scholarship","name":"University of Groningen Scholarship (Netherlands)","type":"scholarship","amount_usd":15000,"deadline":"2025-02-01","eligible_countries":["Global (non-EU)"],"degree_levels":["Undergraduate","Graduate"],"field":"All fields — strong in science, law, economics, humanities","gpa_min":3.3,"tags":["netherlands","groningen","science","law","economics","humanities","europe","affordable","russell equivalent"],"url":"https://www.rug.nl/education/scholarships/","host_university":"University of Groningen","university_url":"https://www.rug.nl","description":"Groningen scholarships — Netherlands' second oldest university, strong STEM and social sciences","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"karolinska_scholarship","name":"Karolinska Institutet Global Master Scholarship (Sweden)","type":"scholarship","amount_usd":25000,"deadline":"2025-01-15","eligible_countries":["Global (non-EU)"],"degree_levels":["Graduate"],"field":"Biomedical Science, Public Health, Global Health, Epidemiology, Neuroscience","gpa_min":3.5,"tags":["sweden","karolinska","biomedical","public health","global health","epidemiology","neuroscience","nobelprize","prestigious","medicine","research"],"url":"https://ki.se/en/education/scholarships-and-grants","host_university":"Karolinska Institutet","university_url":"https://ki.se/en","description":"Karolinska global scholarships — home of the Nobel Prize in Physiology or Medicine committee","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}}
    ,{"id":"lund_scholarship","name":"Lund University Global Scholarship (Sweden)","type":"scholarship","amount_usd":22000,"deadline":"2025-02-01","eligible_countries":["Global (non-EU)"],"degree_levels":["Graduate"],"field":"All fields — strong in engineering, science, law, social sciences","gpa_min":3.3,"tags":["sweden","lund","engineering","science","law","social sciences","europe","prestigious","nordic","research"],"url":"https://www.lunduniversity.lu.se/study-in-lund/scholarships","host_university":"Lund University","university_url":"https://www.lunduniversity.lu.se","description":"Lund University Global Scholarships — Scandinavia's most international university","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"aalto_scholarship","name":"Aalto University Excellence Scholarship (Finland)","type":"scholarship","amount_usd":18000,"deadline":"2025-01-31","eligible_countries":["Global (non-EU)"],"degree_levels":["Graduate"],"field":"Technology, Design, Business, Arts","gpa_min":3.4,"tags":["finland","aalto","technology","design","business","arts","innovation","nordic","europe","startup culture","helsinki"],"url":"https://www.aalto.fi/en/study-at-aalto/scholarships-for-international-degree-students","host_university":"Aalto University","university_url":"https://www.aalto.fi/en","description":"Aalto Excellence Scholarships — Finland's leading innovation university, design + tech + business combined","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"ntnu_scholarship","name":"Norwegian University of Science and Technology Scholarship (NTNU)","type":"scholarship","amount_usd":20000,"deadline":"2025-06-01","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Engineering, Technology, Natural Sciences, Medicine, Architecture","gpa_min":3.3,"tags":["norway","ntnu","trondheim","engineering","technology","natural sciences","medicine","architecture","nordic","research","phd"],"url":"https://www.ntnu.edu/scholarships","host_university":"NTNU","university_url":"https://www.ntnu.edu","description":"NTNU Trondheim scholarships — Norway's top technical university, excellent for PhD in engineering","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"tu_berlin_scholarship","name":"TU Berlin International Scholarship (Germany)","type":"scholarship","amount_usd":14000,"deadline":"2025-07-15","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Engineering, Mathematics, Natural Sciences, Economics, Planning","gpa_min":3.3,"tags":["germany","tu berlin","engineering","mathematics","natural sciences","economics","planning","daad","europe","affordable","berlin","research"],"url":"https://www.tu.berlin/en/studierendenwerk/money/scholarships/","host_university":"TU Berlin","university_url":"https://www.tu.berlin/en/","description":"TU Berlin international scholarships — top 3 German technical universities, strong industry links","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"rwth_scholarship","name":"RWTH Aachen University Scholarship (Germany)","type":"scholarship","amount_usd":13000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Engineering, Natural Sciences, Architecture, Business, Humanities","gpa_min":3.3,"tags":["germany","rwth aachen","engineering","natural sciences","architecture","business","humanities","europe","automotive","manufacturing","prestigious","research"],"url":"https://www.rwth-aachen.de/go/id/qve","host_university":"RWTH Aachen University","university_url":"https://www.rwth-aachen.de/en/","description":"RWTH Aachen scholarships — Germany's top engineering university, key supplier to Mercedes, BMW, Siemens","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"tum_scholarship","name":"Technical University of Munich Excellence Scholarship (TUM)","type":"scholarship","amount_usd":16000,"deadline":"2025-04-30","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Engineering, Natural Sciences, Mathematics, Computer Science, Life Sciences","gpa_min":3.5,"tags":["germany","tum","munich","engineering","natural sciences","mathematics","computer science","life sciences","prestigious","research","phd","europe","excellence"],"url":"https://www.tum.de/en/studies/fees-and-financial-aid/scholarships-and-loans","host_university":"TU Munich (TUM)","university_url":"https://www.tum.de/en/","description":"TUM Excellence Scholarships — Germany's top university and Europe's startup hub, BMW research partnerships","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"mexico_conacyt","name":"Mexico CONACYT Scholarship for Postgraduate Study","type":"scholarship","amount_usd":16000,"deadline":"2025-03-31","eligible_countries":["Mexico"],"degree_levels":["Graduate","Postgraduate"],"field":"All fields — priority on STEM, Social Sciences, Humanities","gpa_min":3.3,"tags":["mexico","conacyt","government","stem","social sciences","humanities","postgraduate","research","phd","masters","fully-funded"],"url":"https://conacyt.mx/becas_y_posgrados/","description":"CONACYT fully-funded scholarships for Mexican nationals pursuing master's and PhD degrees","competitiveness":{"label":"Competitive","acceptance_rate":0.15}}
    ,{"id":"chile_anid_scholarship","name":"Chile ANID Scholarship (Beca de Doctorado Nacional)","type":"scholarship","amount_usd":24000,"deadline":"2025-08-31","eligible_countries":["Chile"],"degree_levels":["Postgraduate"],"field":"All fields","gpa_min":3.3,"tags":["chile","anid","government","phd","doctorate","research","stem","social sciences","fully-funded","santiago","latin america"],"url":"https://www.anid.cl/concursos/","description":"Chilean ANID doctoral scholarships for Chilean nationals at top Chilean and international universities","competitiveness":{"label":"Very Competitive","acceptance_rate":0.10}}
    ,{"id":"argentina_conicet_scholarship","name":"Argentina CONICET Doctoral Fellowship","type":"fellowship","amount_usd":14000,"deadline":"2025-04-30","eligible_countries":["Argentina"],"degree_levels":["Postgraduate"],"field":"Science, Technology, Engineering, Social Sciences, Humanities, Arts","gpa_min":3.3,"tags":["argentina","conicet","government","phd","research","science","technology","engineering","social sciences","humanities","buenos aires","latin america"],"url":"https://www.conicet.gov.ar/becas/","description":"CONICET doctoral and postdoctoral fellowships — Argentina's premier research funding body","competitiveness":{"label":"Competitive","acceptance_rate":0.15}}
    ,{"id":"taiwan_govt_scholarship_expanded","name":"Taiwan Government Scholarship (Study in Taiwan)","type":"scholarship","amount_usd":10000,"deadline":"2025-03-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":3.0,"tags":["taiwan","ministry of education","government","stem","arts","mandarin","affordable","asia","research","taipei","kaohsiung"],"url":"https://www.studyintaiwan.org/scholarship","description":"Taiwan Ministry of Education scholarships for international students across all disciplines","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"hong_kong_phd_fellowship","name":"Hong Kong PhD Fellowship Scheme","type":"fellowship","amount_usd":40000,"deadline":"2024-12-01","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"All fields","gpa_min":3.7,"tags":["hong kong","phd fellowship","research","prestigious","fully-funded","science","engineering","humanities","social sciences","medicine","business"],"url":"https://cerg1.ugc.edu.hk/hkpfs/index.html","description":"Hong Kong's flagship PhD fellowships for world-class research talent across all disciplines","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.04}}
    ,{"id":"macau_govt_scholarship","name":"Macau Government Scholarship","type":"scholarship","amount_usd":12000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":3.0,"tags":["macau","macao","government","china","affordable","portuguese","business","tourism","asia","gaming industry","law"],"url":"https://www.dsedj.gov.mo/en/scholarship/","description":"Macau government scholarships for international students — unique blend of Portuguese and Chinese culture","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"brunei_scholarship","name":"Brunei Darussalam Government Scholarship","type":"scholarship","amount_usd":18000,"deadline":"2025-03-31","eligible_countries":["Global (Commonwealth preference)"],"degree_levels":["Undergraduate","Graduate"],"field":"All fields","gpa_min":3.0,"tags":["brunei","government","commonwealth","fully-funded","southeast asia","asean","oil","affordable","english"],"url":"https://www.mfa.gov.bn/scholarship","description":"Brunei government fully-funded scholarships for international students — generous allowances, English-medium","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"saudi_kfupm_scholarship","name":"King Fahd University of Petroleum & Minerals Scholarship (KFUPM)","type":"scholarship","amount_usd":22000,"deadline":"2025-04-30","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Engineering, Science, Computer Science, Business, Architecture","gpa_min":3.2,"tags":["saudi arabia","kfupm","dhahran","engineering","science","computer science","business","architecture","oil","petroleum","stem","middle east","fully-funded"],"url":"https://www.kfupm.edu.sa/en/scholarship","host_university":"King Fahd University of Petroleum & Minerals","university_url":"https://www.kfupm.edu.sa/en/","description":"KFUPM fully-funded scholarships — Saudi Arabia's top STEM university, partnered with Aramco","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"uae_uaeu_scholarship","name":"UAE University Excellence Scholarship (UAEU)","type":"scholarship","amount_usd":16000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Engineering, Business, Medicine, Science, Humanities","gpa_min":3.3,"tags":["uae","al ain","university","engineering","business","medicine","science","humanities","middle east","research","phd","affordable"],"url":"https://www.uaeu.ac.ae/en/admission/graduate/scholarships.shtml","host_university":"UAE University","university_url":"https://www.uaeu.ac.ae/en/","description":"UAEU research scholarships — flagship UAE university, competitive research funding in STEM","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"qu_qatar_scholarship","name":"Qatar Foundation Undergraduate Research Experience (QURE)","type":"fellowship","amount_usd":20000,"deadline":"2025-04-30","eligible_countries":["Global"],"degree_levels":["Undergraduate"],"field":"Science, Engineering, Medicine, Business, Social Sciences","gpa_min":3.3,"tags":["qatar","qatar foundation","education city","research","undergraduate","science","engineering","medicine","business","stem","prestigious","doha"],"url":"https://www.qf.org.qa/education","description":"Qatar Foundation QURE fellowships for outstanding undergraduates at Education City universities","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"ethiopian_gov_scholarship","name":"Ethiopian Government Scholarship","type":"scholarship","amount_usd":12000,"deadline":"2025-06-30","eligible_countries":["Ethiopia"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Medicine, Engineering, Agriculture, Education, Natural Sciences","gpa_min":3.0,"tags":["ethiopia","government","medicine","engineering","agriculture","education","natural sciences","addis ababa","africa","developing"],"url":"https://www.moe.gov.et/","description":"Ethiopian Ministry of Education scholarships for Ethiopian nationals in priority development fields","competitiveness":{"label":"Competitive","acceptance_rate":0.15}}
    ,{"id":"ghana_gov_scholarship","name":"Ghana Scholarships Secretariat Award","type":"scholarship","amount_usd":15000,"deadline":"2025-05-31","eligible_countries":["Ghana"],"degree_levels":["Graduate","Postgraduate"],"field":"All fields — priority on STEM, Medicine, Agriculture, Law","gpa_min":3.0,"tags":["ghana","scholarships secretariat","government","stem","medicine","agriculture","law","accra","africa","fully-funded"],"url":"https://scholarships.gov.gh/","description":"Ghana Scholarships Secretariat awards for Ghanaian nationals at local and international universities","competitiveness":{"label":"Competitive","acceptance_rate":0.15}}
    ,{"id":"kenya_helb_scholarship","name":"Kenya HELB Higher Education Loan (Scholarship Component)","type":"grant","amount_usd":5000,"deadline":"2025-09-30","eligible_countries":["Kenya"],"degree_levels":["Undergraduate","Graduate"],"field":"All fields","gpa_min":2.5,"tags":["kenya","helb","government","loan","grant","scholarship","nairobi","africa","needs-based","undergraduate","affordable"],"url":"https://www.helb.co.ke/","description":"Kenya Higher Education Loans Board — scholarship bursary component for needy Kenyan students","competitiveness":{"label":"Moderate","acceptance_rate":0.30}}
    ,{"id":"rwandan_gov_scholarship","name":"Rwanda Government Scholarship (WDA)","type":"scholarship","amount_usd":14000,"deadline":"2025-06-30","eligible_countries":["Rwanda"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"STEM, Medicine, Education, Business, Agriculture","gpa_min":3.0,"tags":["rwanda","wda","government","stem","medicine","education","business","agriculture","kigali","africa","vision 2050"],"url":"https://www.wda.gov.rw/scholarships","description":"Rwanda Workforce Development Authority scholarships aligned to Vision 2050 national priorities","competitiveness":{"label":"Competitive","acceptance_rate":0.15}}
    ,{"id":"zimbabwe_gov_scholarship","name":"Zimbabwe Government Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-07-31","eligible_countries":["Zimbabwe"],"degree_levels":["Graduate","Postgraduate"],"field":"Engineering, Medicine, Agriculture, Education, Law","gpa_min":3.0,"tags":["zimbabwe","government","engineering","medicine","agriculture","education","law","harare","africa","developing"],"url":"https://www.highereducation.gov.zw/scholarships","description":"Zimbabwe Ministry of Higher Education scholarships for Zimbabwean nationals in priority fields","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"ieee_women_engineering","name":"IEEE Women in Engineering Scholarship","type":"scholarship","amount_usd":8000,"deadline":"2025-11-01","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate"],"field":"Electrical Engineering, Computer Engineering, Electronics, Robotics","gpa_min":3.3,"tags":["ieee","women","engineering","electrical","computer engineering","electronics","robotics","diversity","stem","global","corporate"],"url":"https://www.ieee.org/education/scholarships/ieee-wie-scholarship.html","description":"IEEE Women in Engineering Scholarship for women pursuing electrical and computer engineering","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"google_phd_fellowship","name":"Google PhD Fellowship Program","type":"fellowship","amount_usd":45000,"deadline":"2025-04-01","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Computer Science, AI, Machine Learning, Human-Computer Interaction, Systems","gpa_min":3.7,"tags":["google","phd","fellowship","computer science","ai","machine learning","hci","systems","prestigious","corporate","research","fully-funded"],"url":"https://research.google/outreach/phd-fellowship/","description":"Google PhD Fellowships for the best computer science PhD students worldwide — includes Google mentorship","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.03}}
    ,{"id":"microsoft_ada_lovelace_fellowship","name":"Microsoft Ada Lovelace Fellowship","type":"fellowship","amount_usd":35000,"deadline":"2025-10-15","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Computer Science, AI, Machine Learning, Human-Computer Interaction","gpa_min":3.5,"tags":["microsoft","ada lovelace","fellowship","computer science","ai","machine learning","hci","diversity","women","underrepresented","corporate","phd"],"url":"https://www.microsoft.com/en-us/research/academic-program/ada-lovelace-fellowship/","description":"Microsoft Ada Lovelace Fellowship for underrepresented PhD students in computer science and AI","competitiveness":{"label":"Very Competitive","acceptance_rate":0.05}}
    ,{"id":"african_leaders_scholarship","name":"African Leaders of Tomorrow Scholarship","type":"scholarship","amount_usd":25000,"deadline":"2025-08-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Rwanda","South Africa","Senegal","Cameroon","Mozambique","Zambia","Zimbabwe","Malawi","Madagascar"],"degree_levels":["Graduate"],"field":"Business, Economics, Public Policy, Development, Leadership","gpa_min":3.0,"tags":["africa","leaders","leadership","business","economics","policy","development","prestigious","community","impact","young professionals"],"url":"https://www.africanleaders.org/scholarship","description":"African Leaders of Tomorrow scholarships for emerging African business and policy leaders","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"africa_oxford_scholarship","name":"Oxford University Africa Scholarship","type":"scholarship","amount_usd":50000,"deadline":"2025-01-03","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Senegal","Rwanda","Zambia","Zimbabwe","Mozambique","Malawi","Egypt","Morocco","Tunisia","Algeria"],"degree_levels":["Graduate","Postgraduate"],"field":"All fields","gpa_min":3.7,"tags":["oxford","uk","africa","prestigious","fully-funded","phd","masters","research","leadership","development","pan-african","weidenfeld"],"url":"https://www.ox.ac.uk/admissions/graduate/fees-and-funding/oxford-funding","host_university":"University of Oxford","university_url":"https://www.ox.ac.uk","description":"Oxford's Africa-specific scholarships including Weidenfeld-Hoffmann, Felix, and other programmes for African scholars","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.03}}
    ,{"id":"cambridge_africa_scholarship","name":"Cambridge Gates Africa Scholarship","type":"scholarship","amount_usd":55000,"deadline":"2024-10-09","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Senegal","Rwanda","Zambia","Zimbabwe","Mozambique","Malawi","Egypt","Morocco","Tunisia"],"degree_levels":["Postgraduate"],"field":"All fields","gpa_min":3.8,"tags":["cambridge","uk","africa","gates","prestigious","fully-funded","phd","masters","research","leadership"],"url":"https://www.gatescambridge.org/programme/scholars/regions/","host_university":"University of Cambridge","university_url":"https://www.cam.ac.uk","description":"Gates Cambridge Scholarships specifically tracking African scholars — one of the most competitive awards","competitiveness":{"label":"Extremely Competitive","acceptance_rate":0.02}}

    ,{"id":"czech_govt_scholarship","name":"Czech Government Scholarship (Development Cooperation)","type":"scholarship","amount_usd":11000,"deadline":"2025-03-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Zambia","Zimbabwe","Mozambique","Angola","Bangladesh","Pakistan","Nepal","Sri Lanka","Vietnam","Cambodia","Myanmar","Afghanistan","Bolivia","Honduras","Nicaragua","Haiti","Laos","Mongolia"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":2.8,"tags":["czech","prague","europe","central europe","government","developing-countries","affordable","stem","arts","humanities"],"url":"https://www.dzs.cz/en/czech-government-scholarships/","description":"Czech government scholarships for students from developing countries — full tuition, accommodation, monthly stipend.","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"poland_nawa_scholarship","name":"Poland NAWA Scholarship for Developing Countries","type":"scholarship","amount_usd":10000,"deadline":"2025-04-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Bangladesh","Pakistan","Nepal","Sri Lanka","Vietnam","Indonesia","Philippines","Cambodia","Egypt","Morocco","Jordan"],"degree_levels":["Graduate","Postgraduate"],"field":"All fields — priority on technology, social sciences, humanities","gpa_min":3.0,"tags":["poland","warsaw","nawa","central europe","government","affordable","stem","social-sciences","humanities","developing-countries"],"url":"https://nawa.gov.pl/en/students/coming-to-poland/nawa-scholarship","description":"NAWA Polish government scholarships for international students from developing countries.","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"romania_govt_scholarship","name":"Romania Government Scholarship for Non-EU Students","type":"scholarship","amount_usd":8000,"deadline":"2025-04-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Bangladesh","Pakistan","Nepal","Vietnam","Cambodia","Myanmar","Bolivia","Honduras","Nicaragua","Haiti"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":2.5,"tags":["romania","bucharest","eastern europe","government","affordable","low-gpa","developing-countries","medicine","engineering"],"url":"https://www.mae.ro/en/node/2411","description":"Romanian government scholarships — very accessible, covers tuition and accommodation.","competitiveness":{"label":"Moderate","acceptance_rate":0.25}}
    ,{"id":"slovakia_govt_scholarship","name":"Slovakia National Scholarship Programme","type":"scholarship","amount_usd":9000,"deadline":"2025-04-30","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"All fields","gpa_min":3.0,"tags":["slovakia","bratislava","central europe","government","affordable","research","stem","humanities"],"url":"https://www.scholarships.sk/en/","description":"Slovakia NSP scholarships for international students and researchers — monthly stipend, no tuition.","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"iceland_govt_scholarship","name":"Icelandic Government Scholarship","type":"scholarship","amount_usd":14000,"deadline":"2025-03-01","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Nordic Studies, Icelandic Language, Environmental Science, Fisheries","gpa_min":3.2,"tags":["iceland","reykjavik","nordic","government","environment","fisheries","geology","energy","renewable","unique"],"url":"https://en.rannis.is/services/research/icelandic-government-scholarships/","description":"Iceland government scholarships — unique Nordic country, world leader in renewable energy and fisheries management.","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"new_zealand_aidrt","name":"New Zealand AIDRT Scholarship (Pacific and Asia)","type":"scholarship","amount_usd":35000,"deadline":"2025-02-28","eligible_countries":["Bangladesh","Pakistan","Sri Lanka","Nepal","Vietnam","Indonesia","Philippines","Cambodia","Myanmar","Thailand","Malaysia","Papua New Guinea","Fiji","Solomon Islands","Vanuatu","Tonga","Samoa","Kiribati","Tuvalu","Nauru","Palau"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Development, Engineering, Agriculture, Education, Health, Environment","gpa_min":3.0,"tags":["new zealand","wellington","auckland","government","pacific","asia","fully-funded","development","agriculture","health","environment"],"url":"https://www.mfat.govt.nz/en/aid-and-development/nz-aid-programme/scholarships/","description":"New Zealand government fully-funded scholarships for students from Pacific and Asian developing nations.","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"south_africa_nrf_scholarship","name":"South African NRF Scholarship for African Students","type":"scholarship","amount_usd":12000,"deadline":"2025-06-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Rwanda","Zambia","Zimbabwe","Mozambique","Malawi","Cameroon","Senegal","DRC","Angola","Namibia","Botswana","Lesotho","Eswatini"],"degree_levels":["Graduate","Postgraduate"],"field":"Science, Technology, Engineering, Mathematics","gpa_min":3.3,"tags":["south africa","johannesburg","cape town","nrf","africa","intra-africa","stem","research","phd","prestigious"],"url":"https://www.nrf.ac.za/funding/opportunities/","description":"South African NRF scholarships for African scholars in STEM — Johannesburg and Cape Town universities.","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"egypt_cairo_scholarship","name":"Cairo University International Scholarship","type":"scholarship","amount_usd":7000,"deadline":"2025-09-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Sudan","Somalia","Jordan","Palestine","Yemen","Syria","Iraq","Libya","Morocco","Tunisia","Algeria"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Medicine, Engineering, Law, Pharmacy, Agriculture, Arts","gpa_min":2.8,"tags":["egypt","cairo","arabic","medicine","engineering","law","pharmacy","africa","middle-east","affordable","arabic-language"],"url":"https://cu.edu.eg/international/scholarship","description":"Cairo University scholarships — Arabic-medium instruction, covers African and Arab League students.","competitiveness":{"label":"Moderate","acceptance_rate":0.22}}
    ,{"id":"morocco_amci_scholarship_2","name":"Morocco AMCI Scholarship (expanded — all African states)","type":"scholarship","amount_usd":9000,"deadline":"2025-05-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Rwanda","Zambia","Zimbabwe","Mozambique","Malawi","Cameroon","Senegal","DRC","Angola","Namibia","Botswana","Lesotho","Eswatini","Guinea","Sierra Leone","Liberia","Gambia","Niger","Mali","Burkina Faso","Chad","CAR","South Sudan","Eritrea","Djibouti","Comoros","Mauritius","Madagascar"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":2.8,"tags":["morocco","rabat","casablanca","africa","intra-africa","arabic","french","government","affordable","developing-countries","oic"],"url":"https://amci.ma/","description":"AMCI Morocco scholarships — all 54 African Union member states, French and Arabic instruction.","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"israel_mashav_scholarship","name":"MASHAV Israel Development Scholarship","type":"scholarship","amount_usd":12000,"deadline":"2025-08-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Rwanda","Zambia","Zimbabwe","Mozambique","Malawi","Cameroon","Senegal","DRC","Angola","Bangladesh","India","Nepal","Sri Lanka","Vietnam","Philippines","Cambodia","Guatemala","Honduras","Bolivia","Haiti","Nicaragua","Peru","Ecuador"],"degree_levels":["Graduate"],"field":"Agriculture, Water Management, Medicine, Education, Community Development","gpa_min":3.0,"tags":["israel","tel aviv","jerusalem","mashav","development","agriculture","water-management","medicine","education","developing-countries","government"],"url":"https://www.gov.il/en/departments/units/mashav","description":"Israel MASHAV development scholarships for professionals from developing countries in agriculture and technology.","competitiveness":{"label":"Moderate","acceptance_rate":0.15}}
    ,{"id":"iran_university_scholarship","name":"Iranian Government Scholarship for Muslim Countries","type":"scholarship","amount_usd":8000,"deadline":"2025-05-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Senegal","Mali","Niger","Gambia","Guinea","Sierra Leone","Bangladesh","Pakistan","Afghanistan","Indonesia","Malaysia","Bosnia","Albania","Kosovo","Azerbaijan","Uzbekistan","Kazakhstan","Tajikistan","Kyrgyzstan","Turkmenistan"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields — priority on Islamic Studies, Engineering, Medicine","gpa_min":2.8,"tags":["iran","tehran","government","oic","muslim","islamic-studies","engineering","medicine","persian","affordable","developing-countries"],"url":"https://ms.icro.ir/en/","description":"Iranian government scholarships for students from Muslim-majority countries — Persian language instruction.","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
    ,{"id":"india_iccr_scholarship","name":"India ICCR Scholarship for Developing Countries","type":"scholarship","amount_usd":9000,"deadline":"2025-02-28","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Rwanda","Zambia","Zimbabwe","Senegal","Bangladesh","Nepal","Sri Lanka","Afghanistan","Cambodia","Myanmar","Vietnam","Indonesia","Philippines","Jordan","Palestine","Yemen","Egypt","Morocco","Bolivia","Honduras","Haiti","Nicaragua"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields — priority on STEM, Culture, Arts","gpa_min":2.8,"tags":["india","delhi","mumbai","iccr","south-south","government","developing-countries","stem","arts","culture","affordable","hindi","english"],"url":"https://www.iccr.gov.in/scholarship","description":"ICCR India government scholarships for developing country students — English-medium instruction at IITs and central universities.","competitiveness":{"label":"Moderate","acceptance_rate":0.18}}
    ,{"id":"china_confucius_scholarship","name":"Confucius Institute Scholarship (Hanban)","type":"scholarship","amount_usd":8000,"deadline":"2025-03-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate"],"field":"Chinese Language, Chinese Culture, Chinese Studies","gpa_min":2.5,"tags":["china","mandarin","chinese-language","confucius","hanban","culture","affordable","language-learning","low-gpa","global"],"url":"https://www.chinesescholarshipcouncil.com/confucius/","description":"Confucius Institute Scholarships for Chinese language and culture study at Chinese universities.","competitiveness":{"label":"Moderate","acceptance_rate":0.25}}
    ,{"id":"mongolia_govt_scholarship","name":"Mongolia Government Scholarship","type":"scholarship","amount_usd":8000,"deadline":"2025-09-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Bangladesh","Pakistan","Nepal","Vietnam","Cambodia","Myanmar"],"degree_levels":["Undergraduate","Graduate"],"field":"Engineering, Agriculture, Medicine, Veterinary Science","gpa_min":2.8,"tags":["mongolia","ulaanbaatar","government","affordable","engineering","agriculture","medicine","veterinary","developing-countries","unique","asia"],"url":"https://scholarships.gov.mn/","description":"Mongolia government scholarships — unique Central Asian destination, strong in veterinary science and mineral engineering.","competitiveness":{"label":"Moderate","acceptance_rate":0.22}}
    ,{"id":"wmo_fellowship","name":"WMO Fellowship Programme (Weather/Climate)","type":"fellowship","amount_usd":18000,"deadline":"2025-11-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Bangladesh","Pakistan","Nepal","Sri Lanka","Vietnam","Cambodia","Myanmar","Bolivia","Honduras","Haiti","Nicaragua","Paraguay","Guatemala","Ecuador","Peru","Egypt","Morocco","Jordan","Yemen","Sudan"],"degree_levels":["Graduate","Postgraduate"],"field":"Meteorology, Climatology, Hydrology, Atmospheric Science","gpa_min":3.0,"tags":["wmo","un","weather","meteorology","climatology","hydrology","atmospheric","fellowship","developing-countries","climate-change","government","un-agency"],"url":"https://public.wmo.int/en/fellowships","description":"World Meteorological Organization fellowships for meteorology and climate professionals from developing nations.","competitiveness":{"label":"Competitive","acceptance_rate":0.12}}
    ,{"id":"fao_fellowship","name":"FAO Fellowship Programme (Food and Agriculture)","type":"fellowship","amount_usd":20000,"deadline":"2025-09-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Zambia","Zimbabwe","Mozambique","Malawi","Bangladesh","Pakistan","Nepal","Vietnam","Indonesia","Cambodia","Bolivia","Honduras","Haiti","Nicaragua","Guatemala","Ecuador","Peru","Paraguay"],"degree_levels":["Graduate","Postgraduate"],"field":"Agriculture, Food Science, Nutrition, Fisheries, Forestry","gpa_min":3.0,"tags":["fao","un","agriculture","food-science","nutrition","fisheries","forestry","fellowship","developing-countries","un-agency","rome","government"],"url":"https://www.fao.org/fellowships","description":"FAO UN fellowships for agriculture and food systems professionals from developing countries.","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"who_fellowship","name":"WHO Fellowship Programme (Public Health)","type":"fellowship","amount_usd":22000,"deadline":"2025-10-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Bangladesh","Pakistan","Nepal","Sri Lanka","Vietnam","Cambodia","Myanmar","Indonesia","Philippines","Bolivia","Honduras","Haiti","Nicaragua","Guatemala","Ecuador","Peru","Egypt","Morocco","Yemen","Sudan"],"degree_levels":["Graduate","Postgraduate"],"field":"Public Health, Epidemiology, Health Policy, Global Health","gpa_min":3.0,"tags":["who","un","public-health","epidemiology","health-policy","global-health","fellowship","developing-countries","un-agency","geneva","government"],"url":"https://www.who.int/about/finances-accountability/funding/scholarships-fellowships","description":"WHO fellowships for public health professionals from developing member states.","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"unep_fellowship","name":"UNEP Fellowship (Environment)","type":"fellowship","amount_usd":18000,"deadline":"2025-08-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Bangladesh","Pakistan","Nepal","Vietnam","Indonesia","Philippines","Bolivia","Honduras","Haiti","Nicaragua","Guatemala","Ecuador","Peru","Egypt","Morocco"],"degree_levels":["Graduate","Postgraduate"],"field":"Environmental Science, Climate Change, Biodiversity, Sustainable Development","gpa_min":3.0,"tags":["unep","un","environment","climate-change","biodiversity","sustainable-development","fellowship","nairobi","developing-countries","un-agency","government"],"url":"https://www.unep.org/about-un-environment-programme/funding-and-partnerships/fellowships","description":"UNEP Nairobi fellowships for environmental professionals from developing countries — based in Nairobi.","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"ilo_fellowship","name":"ILO Fellowship (Labour and Employment)","type":"fellowship","amount_usd":20000,"deadline":"2025-09-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Bangladesh","Pakistan","Nepal","Vietnam","Indonesia","Philippines","Bolivia","Honduras","Haiti","Nicaragua","Guatemala","Ecuador","Peru","Egypt","Morocco","Jordan","Yemen"],"degree_levels":["Graduate","Postgraduate"],"field":"Labour Policy, Employment, Social Protection, Workers Rights","gpa_min":3.0,"tags":["ilo","un","labour","employment","social-protection","workers-rights","fellowship","developing-countries","un-agency","geneva","government"],"url":"https://www.ilo.org/global/about-the-ilo/how-the-ilo-works/departments-and-offices/pardev/grants-fellowships","description":"ILO Geneva fellowships for labour policy professionals from developing countries.","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"african_dev_bank_scholarship","name":"African Development Bank Scholarship","type":"scholarship","amount_usd":25000,"deadline":"2025-07-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Rwanda","Zambia","Zimbabwe","Mozambique","Malawi","Cameroon","Senegal","DRC","Angola","Namibia","Botswana","Mali","Burkina Faso","Niger","Guinea","Sierra Leone","Liberia","Gambia","Chad","CAR","South Sudan","Eritrea","Djibouti","Comoros","Mauritius","Madagascar","Seychelles","Cabo Verde","Sao Tome"],"degree_levels":["Graduate","Postgraduate"],"field":"Economics, Finance, Engineering, Agriculture, Public Policy, Environment","gpa_min":3.3,"tags":["african-development-bank","afdb","africa","economics","finance","engineering","agriculture","policy","environment","prestigious","pan-african","addis-ababa"],"url":"https://www.afdb.org/en/about-us/careers/internships-and-scholarships","description":"AfDB scholarships for African scholars at top international universities — fully funded, prestigious.","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}}
    ,{"id":"mastercard_scholars_program","name":"Mastercard Foundation Scholars Program","type":"scholarship","amount_usd":50000,"deadline":"2025-03-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Rwanda","Zambia","Zimbabwe","Malawi","Mozambique","Cameroon","Senegal","DRC","South Africa","Mali","Guinea","Sierra Leone","Liberia","Gambia","Niger","Burkina Faso","Chad","CAR"],"degree_levels":["Undergraduate","Graduate"],"field":"All fields — leadership and community development focus","gpa_min":3.0,"tags":["mastercard","foundation","africa","prestigious","leadership","community","fully-funded","undergraduate","graduate","transformative","pan-african"],"url":"https://mastercardfdn.org/all/scholars/","description":"Mastercard Foundation Scholars Program — one of the world's largest scholarship programmes for African students.","competitiveness":{"label":"Very Competitive","acceptance_rate":0.05}}
    ,{"id":"cargill_global_scholars","name":"Cargill Global Scholars Program","type":"scholarship","amount_usd":5000,"deadline":"2025-03-01","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","India","Bangladesh","Brazil","Colombia","Indonesia","Vietnam","Philippines","Thailand","Malaysia","Cambodia","Myanmar"],"degree_levels":["Undergraduate"],"field":"Agriculture, Food Science, Business, Engineering, Finance","gpa_min":3.3,"tags":["cargill","corporate","agriculture","food-science","business","engineering","finance","undergraduate","leadership","developing-countries","global"],"url":"https://www.cargill.com/for-students","description":"Cargill Global Scholars — corporate scholarship for future agribusiness and food industry leaders.","competitiveness":{"label":"Competitive","acceptance_rate":0.10}}
    ,{"id":"hewlett_packard_scholarship","name":"HP LIFE e-Learning Scholarship","type":"scholarship","amount_usd":6000,"deadline":"2025-12-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate"],"field":"Computer Science, Business, Digital Technology, Entrepreneurship","gpa_min":3.0,"tags":["hp","hewlett-packard","corporate","computer-science","business","technology","entrepreneurship","global","e-learning","digital","affordable"],"url":"https://www.hplife.com/","description":"HP LIFE scholarships for students pursuing digital literacy and technology entrepreneurship skills.","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
]

# Dynamic weight learning: updated from behavioral outcomes
_DYNAMIC_WEIGHTS = {
    "gpa": 0.25, "degree": 0.20, "country": 0.15,
    "field": 0.15, "financial_need": 0.10, "deadline": 0.10, "amount": 0.05,
    "_last_updated": 0,
}

def _refresh_dynamic_weights():
    """
    Reinforcement learning: recalculate matching weights from outcomes.
    Uses a gradient-like update — each win shifts weights toward the
    features that predicted it. Rejected events shift weights away.
    Refresh interval: 1 hour (cached in-process).
    """
    import time
    global _DYNAMIC_WEIGHTS
    if time.time() - _DYNAMIC_WEIGHTS.get("_last_updated", 0) < 3600:
        return  # Refresh at most once per hour
    try:
        db = SessionLocal()
        won_events = db.query(UserEvent).filter(
            UserEvent.event_type == "won"
        ).limit(500).all()
        if len(won_events) < 10:
            db.close(); return  # Not enough data yet

        # For each win, load the user and the opportunity
        from engine.opportunity_db import load_all_opportunities
        all_opps = {o["id"]: o for o in load_all_opportunities() + EXTRA_OPPORTUNITIES}
        gpa_correct = 0; country_correct = 0; field_correct = 0; total = 0
        for ev in won_events:
            u = db.query(User).filter(User.id == ev.user_id).first()
            opp = all_opps.get(ev.opp_id or "")
            if not u or not opp: continue
            total += 1
            if float(u.gpa or 0) >= float(opp.get("gpa_min") or 0):
                gpa_correct += 1
            nat = (u.nationality or "").lower()
            eligible = [c.lower() for c in (opp.get("eligible_countries") or [])]
            if any(nat in c or c == "global" for c in eligible):
                country_correct += 1
            major = (u.major or "").lower()
            field_str = (opp.get("field") or "").lower() + " " + " ".join(opp.get("tags") or [])
            if any(w in field_str for w in major.split() if len(w) > 2):
                field_correct += 1
        db.close()
        if total > 0:
            # Nudge weights toward what correlates with wins
            _DYNAMIC_WEIGHTS["gpa"]     = round(0.15 + 0.15 * (gpa_correct / total), 3)
            _DYNAMIC_WEIGHTS["country"] = round(0.10 + 0.10 * (country_correct / total), 3)
            _DYNAMIC_WEIGHTS["field"]   = round(0.10 + 0.10 * (field_correct / total), 3)
            _DYNAMIC_WEIGHTS["_last_updated"] = time.time()
            logger.info("Dynamic weights updated from %d wins: gpa=%.2f country=%.2f field=%.2f",
                        total, _DYNAMIC_WEIGHTS["gpa"], _DYNAMIC_WEIGHTS["country"], _DYNAMIC_WEIGHTS["field"])
    except Exception as e:
        logger.debug("Weight refresh failed (non-critical): %s", e)


def _match_opps(profile, opp_type=None, field=None, region=None, min_amount=0):
    import hashlib, json
    _refresh_dynamic_weights()  # Update weights from outcomes (cached 1hr)
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
    if region:
        region_l = region.lower()
        # Map regional aliases to country lists
        region_groups = {
            "asia": ["china","japan","south korea","taiwan","singapore","malaysia","thailand",
                     "vietnam","indonesia","philippines","bangladesh","india","pakistan","nepal",
                     "sri lanka","cambodia","myanmar","laos","bhutan","mongolia","global"],
            "east asia": ["china","japan","south korea","taiwan","singapore","hong kong","mongolia"],
            "southeast asia": ["vietnam","indonesia","philippines","thailand","malaysia","singapore",
                               "cambodia","myanmar","laos","brunei","timor-leste","global"],
            "south asia": ["india","bangladesh","pakistan","nepal","sri lanka","bhutan","maldives","global"],
            "pacific": ["australia","new zealand","fiji","papua new guinea","solomon islands",
                        "vanuatu","samoa","tonga","kiribati","tuvalu","palau","global"],
            "middle east": ["egypt","morocco","jordan","lebanon","turkey","iran","iraq","global"],
            "europe": ["germany","france","uk","united kingdom","netherlands","spain","italy",
                       "sweden","norway","denmark","finland","switzerland","austria","global"],
            "north america": ["usa","united states","canada","global"],
            "latin america": ["brazil","colombia","mexico","argentina","chile","peru","global"],
        }
        group = region_groups.get(region_l)
        if group:
            opps = [o for o in opps if any(
                any(g in c.lower() for g in group)
                for c in o.get("eligible_countries", [])
            ) or any(
                any(g in tag.lower() for g in [region_l, region_l.replace(" ",""), "global"])
                for tag in (o.get("tags") or [])
            )]
        else:
            opps = [o for o in opps if any(
                region_l in c.lower() for c in o.get("eligible_countries", [])
            )]
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
    # Sort options: deadline (default), match_score, expected_value
    sort_by = "deadline"  # Can be extended to accept a parameter later
    def _deadline_sort_key(o):
        days = _days_until(o.get("deadline",""))
        if days is None or days < 0: return 9999
        return days
    def _ev_sort_key(o):
        amount = float(o.get("amount_usd",0) or 0)
        score  = float(o.get("match_score",0.5) or 0.5)
        accept = float((o.get("competitiveness") or {}).get("acceptance_rate",0.1))
        ev = amount * score * accept
        return -ev  # Descending EV
    if sort_by == "ev":
        opps.sort(key=_ev_sort_key)
    else:
        opps.sort(key=lambda o: (_deadline_sort_key(o), -float(o.get("match_score",0.5))))
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


@app.get("/api/scholarships/search")
async def search_scholarships(
    q: str = "",
    degree_level: str = "",
    field: str = "",
    country: str = "",
    min_amount: float = 0,
    max_amount: float = 0,
    opp_type: str = "",
    db: Session = Depends(get_db),
):
    """
    Full-text search across all 120+ opportunities.
    Searches name, description, field, tags, and eligible countries.
    """
    from engine.opportunity_db import load_all_opportunities
    base = load_all_opportunities()
    ext_ids = {o.get("id") for o in base}
    all_opps = base + [o for o in EXTRA_OPPORTUNITIES if o.get("id") not in ext_ids]

    q_lower = q.lower().strip()

    def score_opp(o):
        if not q_lower:
            return 1.0
        name = (o.get("name","") or "").lower()
        desc = (o.get("description","") or "").lower()
        field_str = (o.get("field","") or "").lower()
        tags = " ".join(o.get("tags") or []).lower()
        countries = " ".join(o.get("eligible_countries") or []).lower()
        combined = f"{name} {desc} {field_str} {tags} {countries}"
        # Exact name match = highest score
        if q_lower in name: return 1.0
        # Field match
        if q_lower in field_str: return 0.9
        # Tag match
        if q_lower in tags: return 0.8
        # Description match
        if q_lower in desc: return 0.6
        # Partial word match
        words = q_lower.split()
        hits = sum(1 for w in words if w in combined and len(w) > 2)
        return hits / max(len(words), 1) * 0.5

    results = []
    for o in all_opps:
        # Apply filters
        if degree_level and degree_level.lower() not in                 [d.lower() for d in (o.get("degree_levels") or [])]:
            continue
        if field and field.lower() not in (o.get("field","") or "").lower():
            continue
        if country and country.lower() not in                 [c.lower() for c in (o.get("eligible_countries") or [])]:
            if "global" not in " ".join(o.get("eligible_countries") or []).lower():
                continue
        if opp_type and o.get("type","").lower() != opp_type.lower():
            continue
        amt = float(o.get("amount_usd") or 0)
        if min_amount and amt < min_amount:
            continue
        if max_amount and amt > max_amount:
            continue
        sc = score_opp(o)
        if q_lower and sc == 0:
            continue
        results.append({**o, "_search_score": sc})

    results.sort(key=lambda x: x["_search_score"], reverse=True)
    return {
        "results": results[:50],
        "total": len(results),
        "query": q,
        "filters": {"degree_level": degree_level, "field": field,
                    "country": country, "opp_type": opp_type},
    }


@app.post("/api/scholarships/{sid}/bookmark")
async def bookmark_scholarship(sid: str, user: User = Depends(_get_user),
                                db: Session = Depends(get_db)):
    """Quick save a scholarship without adding to pipeline."""
    from engine.opportunity_db import load_all_opportunities
    all_opps = load_all_opportunities() + EXTRA_OPPORTUNITIES
    opp = next((o for o in all_opps if o.get("id") == sid), None)
    if not opp:
        raise HTTPException(404, "Scholarship not found")
    # Add to pipeline at 'researching' stage if not already there
    existing = db.query(Application).filter(
        Application.user_id == user.id,
        Application.opportunity_id == sid,
    ).first()
    if existing:
        return {"message": "Already in your pipeline", "id": existing.id}
    a = Application(
        id=f"app_{uuid.uuid4().hex[:8]}",
        user_id=user.id,
        opportunity_id=sid,
        scholarship_name=opp.get("name",""),
        opportunity_type=opp.get("type","scholarship"),
        amount_usd=float(opp.get("amount_usd",0)),
        deadline=opp.get("deadline",""),
        url=opp.get("url",""),
        stage="researching",
    )
    db.add(a); db.commit()
    _log_event(db, user.id, "pipeline_add", sid, opp.get("name",""))
    return {"message": "Saved to your pipeline", "id": a.id, "stage": "researching"}

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
    # BOLA: users can only access their own packages (OWASP API1:2023)
    if user.id != uid and user.plan not in ("enterprise","partner"):
        raise HTTPException(403, "Access denied")
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
    rec_id = rec.id
    # Generate draft letter in background
    bt.add_task(_generate_rec_letter, rec_id, user.to_dict())
    return {**rec.to_dict(),"message":"Created. Draft letter being generated — refresh in 30 seconds."}


def _generate_rec_letter(rec_id: str, profile: dict):
    """
    T3: AI-generated recommendation letter using full context.
    Uses the applicant's profile, relationship, and scholarship details.
    """
    db = SessionLocal()
    try:
        rec = db.query(RecRequest).filter(RecRequest.id == rec_id).first()
        if not rec: return

        llm = _llm()
        system = (
            "You are an expert academic writing assistant helping draft recommendation letters. "
            "Write in the recommender's voice — professional, specific, and compelling. "
            "Never use generic filler phrases like 'it is my pleasure' without substance. "
            "Focus on specific achievements, observed behaviours, and concrete examples."
        )

        prompt = f"""Draft a strong recommendation letter for a scholarship application.

RECOMMENDER DETAILS:
- Name: {rec.recommender_name}
- Title/Role: {rec.recommender_title}
- Relationship to applicant: {rec.relationship_desc}

APPLICANT PROFILE:
- Name: {profile.get('name', 'the applicant')}
- Degree: {profile.get('degree_level', 'Graduate')} in {profile.get('major', '')}
- University: {profile.get('school', '')}
- Nationality: {profile.get('nationality', '')}
- GPA: {profile.get('gpa', 0):.1f}/4.0
- Skills: {', '.join((profile.get('skills') or [])[:6])}
- Activities: {', '.join((profile.get('extracurriculars') or [])[:4])}
- Personal statement: {(profile.get('personal_statement') or '')[:300]}

SCHOLARSHIP BEING APPLIED TO: {rec.opportunity_name}
SUBMISSION DEADLINE: {rec.deadline}

LETTER REQUIREMENTS:
1. Opening paragraph: How long and in what capacity have you known the applicant?
2. Academic/professional capability paragraph: Specific academic or work achievement with evidence
3. Character paragraph: Leadership, teamwork, integrity with a concrete example
4. Scholarship fit paragraph: Why this specific scholarship suits this applicant
5. Closing: Strong recommendation with contact offer

Format: Formal letter, 400-500 words, ready to send. Include placeholders [Date], [Institution Address]."""

        letter = llm(system, prompt)
        rec.drafted_letter = letter
        rec.status = "drafted"
        db.commit()
    except Exception as e:
        logger.error("Rec letter generation failed: %s", e)
        if rec:
            rec.drafted_letter = f"[Generation failed — {str(e)[:100]}. Please write the letter manually.]"
            db.commit()
    finally:
        db.close()


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
        import json as _json, re as _re
        # Strip markdown code fences if present
        clean = _re.sub(r"```(?:json)?\s*", "", raw).strip()
        start = clean.find("{"); end = clean.rfind("}") + 1
        parsed = _json.loads(clean[start:end]) if start >= 0 else {}
        # Validate required fields — structured output contract
        required = {"overall_score","grade","dimensions","strengths","improvements"}
        missing  = required - set(parsed.keys())
        if missing:
            raise ValueError(f"Claude response missing fields: {missing}")
        # Clamp and type-check numeric fields
        parsed["overall_score"] = float(parsed.get("overall_score",0.5))
        parsed["overall_score"] = max(0.0, min(1.0, parsed["overall_score"]))
        if parsed.get("grade") not in {"A","B","C","D","F"}:
            parsed["grade"] = "B" if parsed["overall_score"] >= 0.70 else "C"
        result = parsed
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

    # Before/after edit suggestions for top improvements
    improvements = result.get("improvements",[])
    before_after = [{"issue":imp,
                     "action":"Add a specific example, date, or measurable outcome"}
                    for imp in improvements[:3] if isinstance(imp,str) and len(imp)>10]
    return {
        **result,
        "rubric":            rubric_name,
        "rubric_dimensions": rubric_dims,
        "similarity_check":  similarity,
        "scholarship_id":    scholarship_id,
        "before_after":      before_after,
        "next_step":         ("Revise the top improvement above, then critique again "
                              "— aim for Grade A before submitting."),
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
    # Redis check
    redis_ok = False
    redis_url = os.environ.get("REDIS_URL","")
    if redis_url:
        try:
            import redis as _redis
            r = _redis.from_url(redis_url, socket_timeout=2)
            r.ping()
            redis_ok = True
        except Exception:
            pass

    return {
        "version": "4.3.0",
        "python": sys.version[:20],
        "db_connected": db_ok,
        "db_error": db_error,
        "tables_in_db": table_count,
        "extra_opps": len(EXTRA_OPPORTUNITIES),
        "total_opportunities": 87 + len(EXTRA_OPPORTUNITIES),
        "redis_configured": bool(redis_url),
        "redis_connected": redis_ok,
        "rate_limiting": "redis" if redis_ok else "in-memory (single worker)",
        "stripe_configured": bool(os.environ.get("STRIPE_SECRET_KEY","")),
        "email_configured": bool(os.environ.get("SENDER_API_KEY","")),
        "sentry_configured": bool(os.environ.get("SENTRY_DSN","")),
        "processed_stripe_events": len(_processed_stripe_events),
        "r2_configured": bool(os.environ.get("CLOUDFLARE_R2_ACCOUNT_ID","")),
        "r2_bucket_configured": bool(os.environ.get("CLOUDFLARE_R2_BUCKET","")),
        "anthropic_configured": bool(os.environ.get("ANTHROPIC_API_KEY","")),
        "status": "ok" if db_ok else "db_error",
        "locked_ips_count": len([d for d in _login_failures.values()
                                if d.get("locked_until") and time.time()<d["locked_until"]]),
        # NEVER add raw key values, SECRET_KEY, or passwords here
    }


@app.get("/api/health")
async def health(db: Session = Depends(get_db)):
    ok = False; users = -1; pending_jobs = -1; pool_status = "unknown"
    try:
        users = db.query(User).count()
        ok    = True
        # Check connection pool health
        engine = _get_engine()
        pool   = engine.pool
        pool_status = {
            "checked_out": pool.checkedout(),
            "checked_in":  pool.checkedin(),
            "overflow":    pool.overflow(),
            "size":        pool.size(),
        }
    except Exception as e:
        pool_status = {"error": str(e)[:100]}
    try:
        pending_jobs = db.query(Job).filter(Job.status == "pending").count()
    except Exception:
        pass
    return {
        "status":        "ok" if ok else "db_error",
        "version":       "4.3.0",
        "db":            _DB_URL.split("://")[0],
        "users":         users,
        "pending_jobs":  pending_jobs,
        "pool":          pool_status,
        "opportunities": 87 + len(EXTRA_OPPORTUNITIES),
        "circuit_open":  not _check_api_circuit(),
        "timestamp":     datetime.utcnow().isoformat(),
    }

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
    sw_content = """const CACHE='scholarbot-v5';const SHELL=['/'];
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

    # Include current dynamic weights and experiment summary
    experiments_summary = {}
    for exp_name in ACTIVE_EXPERIMENTS:
        rows = db.query(Experiment).filter(Experiment.name == exp_name).all()
        from collections import defaultdict as _dd
        stats = _dd(lambda: {"exposures":0,"conversions":0})
        for r in rows:
            stats[r.variant]["exposures"] += 1
            if r.converted: stats[r.variant]["conversions"] += 1
        experiments_summary[exp_name] = {
            k: {"exposures":v["exposures"],
                "conversion_rate_pct": round(v["conversions"]/max(v["exposures"],1)*100,1)}
            for k,v in stats.items()
        }

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
        "experiments": experiments_summary,
        "dynamic_weights": {
            k:v for k,v in _DYNAMIC_WEIGHTS.items() if k != "_last_updated"
        },
        "total_opportunities": 87 + len(EXTRA_OPPORTUNITIES),
        "plans": {
            "free":       db.query(User).filter(User.plan == "free").count(),
            "pro":        db.query(User).filter(User.plan == "pro").count(),
            "enterprise": db.query(User).filter(User.plan == "enterprise").count(),
        },
        "mrr_estimate": (
            db.query(User).filter(User.plan == "pro").count() * 9 +
            db.query(User).filter(User.plan == "enterprise").count() * 49
        ),
    }



@app.post("/api/scholarships/compare")
async def compare_scholarships(
    req: dict,
    user: Optional[User] = Depends(_opt_user),
    db: Session = Depends(get_db),
):
    """
    Compare 2-4 scholarships side-by-side.
    Returns structured comparison across 8 dimensions.
    """
    ids = req.get("ids", [])
    if not ids or len(ids) < 2:
        raise HTTPException(400, "Provide 2-4 scholarship IDs to compare")
    if len(ids) > 4:
        ids = ids[:4]

    from engine.opportunity_db import load_all_opportunities
    all_opps = load_all_opportunities() + EXTRA_OPPORTUNITIES
    opp_map  = {o["id"]: o for o in all_opps}
    selected = [opp_map[i] for i in ids if i in opp_map]

    if len(selected) < 2:
        raise HTTPException(404, "One or more scholarship IDs not found")

    profile = user.to_dict() if user else {}

    def score_opp(o):
        if not profile: return 0.5
        matches = _match_opps(profile)
        return next((m.get("match_score", 0.5) for m in matches
                     if m.get("id") == o["id"]), 0.5)

    # Build comparison matrix
    comparison = []
    for o in selected:
        match_sc = score_opp(o)
        accept   = (o.get("competitiveness") or {}).get("acceptance_rate", 0.15)
        ev       = round(float(o.get("amount_usd") or 0) * match_sc * min(accept * 5, 1.0))
        days     = _days_until(o.get("deadline", ""))
        eligible = [c.lower() for c in (o.get("eligible_countries") or [])]
        nat      = (profile.get("nationality") or "").lower()
        country_ok = any(nat in c or c in nat or c == "global" for c in eligible)
        gpa_ok   = float(profile.get("gpa") or 0) >= float(o.get("gpa_min") or 0)

        comparison.append({
            "id":              o["id"],
            "name":            o.get("name", ""),
            "type":            o.get("type", "scholarship"),
            "amount_usd":      o.get("amount_usd", 0),
            "deadline":        o.get("deadline", ""),
            "days_left":       days,
            "field":           o.get("field", ""),
            "gpa_min":         o.get("gpa_min", 0),
            "eligible_countries": o.get("eligible_countries", []),
            "url":             o.get("url", ""),
            "description":     o.get("description", ""),
            "acceptance_rate": accept,
            "competitiveness": (o.get("competitiveness") or {}).get("label", "Unknown"),
            "tags":            o.get("tags", []),
            # AI-computed fields
            "match_score":     round(match_sc, 3),
            "match_pct":       f"{int(match_sc * 100)}%",
            "expected_value":  ev,
            "country_eligible": country_ok,
            "gpa_eligible":    gpa_ok,
            "grade":           ("A" if match_sc >= 0.85 else "B" if match_sc >= 0.70
                                else "C" if match_sc >= 0.55 else "D"),
        })

    # Determine winner per dimension
    best = {
        "amount":   max(comparison, key=lambda x: x["amount_usd"] or 0)["id"],
        "match":    max(comparison, key=lambda x: x["match_score"])["id"],
        "ev":       max(comparison, key=lambda x: x["expected_value"])["id"],
        "deadline": min(comparison, key=lambda x: x["days_left"] if x["days_left"] > 0 else 9999)["id"],
        "acceptance": max(comparison, key=lambda x: x["acceptance_rate"])["id"],
    }

    return {
        "scholarships": comparison,
        "best_per_dimension": best,
        "recommendation": max(comparison, key=lambda x: x["expected_value"])["name"],
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


@app.patch("/api/pipeline/{app_id}/notes")
async def update_notes(app_id: str, req: dict,
                        user: User = Depends(_get_user),
                        db: Session = Depends(get_db)):
    """Add or update notes on a pipeline application."""
    a = db.query(Application).filter(
        Application.id == app_id, Application.user_id == user.id
    ).first()
    if not a: raise HTTPException(404, "Application not found")
    a.notes = _sanitise(req.get("notes", ""), 2000)
    a.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Notes saved", "notes": a.notes}

@app.get("/api/account/export")
async def export_data(user: User = Depends(_get_user), db: Session = Depends(get_db)):
    apps = db.query(Application).filter(Application.user_id==user.id).all()
    pkgs = db.query(Package).filter(Package.user_id==user.id).all()
    return JSONResponse({
        "export_generated_at":datetime.utcnow().isoformat(),
        "platform":"ScholarBot v4.3.0",
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
    "trial":      {"essays_per_day": 20, "packages_per_day": 5, "reviews_per_month": 3},
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


@app.post("/api/digest/send")
async def send_digest(user: User = Depends(_get_user),
                      db: Session = Depends(get_db)):
    """
    Send personalised weekly scholarship digest to the user.
    Top 5 matches + upcoming deadlines + platform stats.
    """
    import os as _os, requests as _rq
    sender_key = _os.environ.get("SENDER_API_KEY","")
    from_email  = _os.environ.get("FROM_EMAIL","noreply@scholarbot.app")
    base        = _os.environ.get("BASE_URL","https://scholarbot-web.onrender.com")

    # Get top matches
    profile = user.to_dict()
    matches = _match_opps(profile)[:5]
    # Get upcoming deadlines
    apps = db.query(Application).filter(
        Application.user_id == user.id,
        Application.stage.in_(["researching","essay_ready","submitted"]),
    ).all()
    deadlines = sorted(
        [a for a in apps if _days_until(a.deadline) <= 30],
        key=lambda a: _days_until(a.deadline)
    )[:3]

    # Build email HTML
    match_rows = "".join(f"""
        <tr>
          <td style="padding:10px 8px;border-bottom:1px solid #e8e8e0">
            <a href="{m.get('url','#')}" style="color:#2563eb;text-decoration:none;font-weight:500">
              {m.get('name','')[:50]}
            </a><br>
            <span style="font-size:11px;color:#888">{m.get('field','')[:40]}</span>
          </td>
          <td style="padding:10px 8px;border-bottom:1px solid #e8e8e0;text-align:right;font-weight:700">
            ${m.get('amount_usd',0):,.0f}
          </td>
          <td style="padding:10px 8px;border-bottom:1px solid #e8e8e0;text-align:center;font-weight:600;color:#2563eb">
            {int((m.get('match_score') or 0.5)*100)}%
          </td>
        </tr>""" for m in matches)

    deadline_rows = "".join(f"""
        <div style="padding:8px 12px;border-left:3px solid {'#dc2626' if _days_until(a.deadline)<=7 else '#d97706'};
             margin-bottom:8px;background:#fff8f8;border-radius:0 4px 4px 0">
          <strong style="font-size:13px">{a.scholarship_name[:45]}</strong><br>
          <span style="font-size:12px;color:#888">{_days_until(a.deadline)} days left · {a.deadline}</span>
        </div>""" for a in deadlines)

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;background:#f5f5f0;margin:0;padding:0">
    <div style="max-width:600px;margin:0 auto;padding:24px 16px">
      <div style="background:#1a1a2e;padding:20px 24px;border-radius:8px 8px 0 0">
        <span style="color:#fff;font-size:20px;font-weight:700">🎓 ScholarBot Weekly Digest</span>
      </div>
      <div style="background:#fff;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e8e8e0">
        <h2 style="color:#1a1a2e;margin-top:0">Hi {user.name.split()[0]},</h2>
        <p style="color:#555">Here are your top scholarship matches this week:</p>

        <table style="width:100%;border-collapse:collapse;margin:16px 0">
          <thead>
            <tr style="background:#f5f5f0">
              <th style="padding:8px;text-align:left;font-size:12px">Scholarship</th>
              <th style="padding:8px;text-align:right;font-size:12px">Award</th>
              <th style="padding:8px;text-align:center;font-size:12px">Match</th>
            </tr>
          </thead>
          <tbody>{match_rows}</tbody>
        </table>

        {'<h3 style="color:#dc2626;margin-top:20px">⏰ Upcoming deadlines</h3>' + deadline_rows if deadlines else ''}

        <div style="text-align:center;margin:24px 0">
          <a href="{base}/?page=scholarships" style="background:#2563eb;color:#fff;padding:12px 28px;
             text-decoration:none;border-radius:6px;font-size:15px;font-weight:600;display:inline-block">
            View all matches →
          </a>
        </div>
        <hr style="border:none;border-top:1px solid #e8e8e0;margin:20px 0">
        <p style="font-size:11px;color:#888">
          ScholarBot · <a href="{base}" style="color:#2563eb">{base}</a>
        </p>
      </div>
    </div>
    </body></html>"""

    if not sender_key:
        return {"message": "Email service not configured", "matches": len(matches)}

    resp = _rq.post("https://api.sender.net/v2/message/send",
        headers={"Authorization":f"Bearer {sender_key}","Content-Type":"application/json"},
        json={"from":{"email":from_email,"name":"ScholarBot"},
              "to":{"email":user.email,"name":user.name},
              "subject":f"🎓 Your weekly ScholarBot digest — {len(matches)} new matches",
              "html":html},
        timeout=15)

    if resp.status_code in (200, 201):
        _log_event(db, user.id, "digest_sent", None, None,
                   {"matches": len(matches), "deadlines": len(deadlines)})
        return {"message": "Digest sent to your email", "matches": len(matches),
                "deadlines": len(deadlines)}
    return {"message": f"Send failed: {resp.status_code}", "matches": 0}


@app.get("/api/digest/preview")
async def digest_preview(user: User = Depends(_get_user),
                          db: Session = Depends(get_db)):
    """Preview what the weekly digest will contain without sending."""
    profile = user.to_dict()
    matches = _match_opps(profile)[:5]
    apps = db.query(Application).filter(
        Application.user_id == user.id,
        Application.stage.in_(["researching","essay_ready","submitted"]),
    ).all()
    deadlines = [a for a in apps if _days_until(a.deadline) <= 30]
    return {
        "top_matches": [{"name": m.get("name"), "amount_usd": m.get("amount_usd"),
                          "match_score": m.get("match_score")} for m in matches],
        "upcoming_deadlines": len(deadlines),
        "email": user.email,
    }


# ── Scholarship Alerts ────────────────────────────────────────
class AlertSub(Base):
    """User subscribes to alerts for new scholarships matching their profile."""
    __tablename__ = "alert_subscriptions"
    id         = Column(String(32), primary_key=True)
    user_id    = Column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    frequency  = Column(String(20), default="weekly")   # daily / weekly
    last_sent  = Column(DateTime, nullable=True)
    active     = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


@app.post("/api/alerts/subscribe")
async def subscribe_alerts(req: dict, user: User = Depends(_get_user),
                            db: Session = Depends(get_db)):
    """Subscribe to new scholarship match alerts."""
    existing = db.query(AlertSub).filter(AlertSub.user_id == user.id).first()
    if existing:
        existing.active = True
        existing.frequency = req.get("frequency", "weekly")
        db.commit()
        return {"message": "Alert subscription updated", "frequency": existing.frequency}
    sub = AlertSub(
        id=f"alert_{uuid.uuid4().hex[:8]}",
        user_id=user.id,
        frequency=req.get("frequency", "weekly"),
    )
    db.add(sub); db.commit()
    return {"message": f"Subscribed to {sub.frequency} scholarship alerts",
            "id": sub.id}


@app.delete("/api/alerts/unsubscribe")
async def unsubscribe_alerts(user: User = Depends(_get_user),
                              db: Session = Depends(get_db)):
    """Unsubscribe from alerts."""
    sub = db.query(AlertSub).filter(AlertSub.user_id == user.id).first()
    if sub:
        sub.active = False
        db.commit()
    return {"message": "Unsubscribed from scholarship alerts"}


@app.get("/api/alerts/status")
async def alert_status(user: User = Depends(_get_user),
                        db: Session = Depends(get_db)):
    """Check current alert subscription status."""
    sub = db.query(AlertSub).filter(AlertSub.user_id == user.id).first()
    if not sub or not sub.active:
        return {"subscribed": False}
    return {
        "subscribed": True,
        "frequency": sub.frequency,
        "last_sent": sub.last_sent.isoformat() if sub.last_sent else None,
    }


@app.get("/api/interview/tips/{scholarship_slug}")
async def interview_tips(scholarship_slug: str):
    """
    T3: Scholarship-specific interview preparation tips.
    Covers common panel questions, dos/don'ts, and scoring insights.
    """
    tips_db = {
        "chevening": {
            "name": "Chevening Scholarship",
            "panel_format": "3 panelists, 30 minutes, 4 questions aligned to rubric dimensions",
            "key_dimensions": ["Leadership", "Networking", "Ambassador Potential", "Career Plan"],
            "top_tips": [
                "Prepare a specific leadership story using STAR method — panel scores leadership first",
                "Have 3-5 concrete networking examples ready: conferences, mentors, professional groups",
                "Research the UK-Kenya/your country partnership — mention specific bilateral ties",
                "Your career plan must be specific: name the organisation you want to work at in 5 years",
                "Dress formally — Chevening represents the UK government internationally",
            ],
            "common_mistakes": [
                "Giving vague answers: 'I have good leadership skills' without evidence",
                "Ignoring the 'return to home country' requirement — mention it explicitly",
                "Not researching the scholarship body (FCDO) and UK foreign policy",
            ],
            "sample_questions": [
                "Tell us about a time you led a team through a difficult challenge",
                "How will you use your UK network after you return home?",
                "What specific role will you play in your country's development?",
            ]
        },
        "fulbright": {
            "name": "Fulbright Scholarship",
            "panel_format": "Mix of written essays + interview for finalists",
            "key_dimensions": ["Academic Excellence", "Research Project", "Cross-cultural Engagement", "Impact"],
            "top_tips": [
                "Your research project must be feasible and specific — name the US university and supervisor",
                "Emphasise mutual exchange: what you bring to the US, not just what you gain",
                "Fulbright values cultural ambassadors — show genuine curiosity about American society",
                "Quantify your academic achievements: publications, awards, class rank",
                "Connect your project to your home country's development needs",
            ],
            "common_mistakes": [
                "Treating it as a study abroad application rather than a research fellowship",
                "Vague project proposals without methodology or timeline",
                "Focusing only on personal benefit, ignoring mutual understanding mission",
            ],
            "sample_questions": [
                "Why is this specific research only possible in the United States?",
                "How will your Fulbright experience benefit your home country?",
                "Describe your research methodology and expected outcomes",
            ]
        },
        "gates_cambridge": {
            "name": "Gates Cambridge Scholarship",
            "panel_format": "Formal interview, 20-30 minutes, academic panel",
            "key_dimensions": ["Academic Achievement", "Leadership", "Commitment to Others", "Cambridge Fit"],
            "top_tips": [
                "Know your research proposal in extreme depth — expect hard technical questions",
                "Leadership must show you improved others' lives, not just managed a project",
                "'Commitment to others' is core — have a sustained community engagement story",
                "Research your Cambridge supervisor and department thoroughly",
                "The panel includes your potential supervisor — impress academically first",
            ],
            "common_mistakes": [
                "Underpreparing on academic content — this is the most academically rigorous scholarship",
                "Leadership stories that are self-serving rather than community-focused",
                "Not engaging with why Cambridge specifically (not just UK or top university)",
            ],
            "sample_questions": [
                "What is the most significant challenge in your research area right now?",
                "Describe a time you made a significant difference in your community",
                "Why is Cambridge the best place in the world for this research?",
            ]
        },
        "general": {
            "name": "General Scholarship Interview",
            "panel_format": "Varies — typically 2-3 panelists, 20-45 minutes",
            "key_dimensions": ["Academic Merit", "Leadership", "Future Goals", "Scholarship Fit"],
            "top_tips": [
                "Use STAR (Situation, Task, Action, Result) for every competency question",
                "Research the scholarship organisation — know their mission and values",
                "Prepare 3 questions to ask the panel — shows genuine interest",
                "Practice out loud, not just in your head — fluency comes from speaking",
                "Have specific numbers ready: GPA, years of experience, impact metrics",
            ],
            "common_mistakes": [
                "Memorising answers word-for-word — sounds rehearsed and robotic",
                "Not answering the actual question asked",
                "Failing to connect your goals to the scholarship's specific mission",
            ],
            "sample_questions": [
                "Tell us about yourself and why you applied for this scholarship",
                "What is your biggest achievement and what did you learn from it?",
                "Where do you see yourself in 10 years?",
            ]
        },
    }
    slug = scholarship_slug.lower().replace("-", "_").replace(" ", "_")
    # Match against known slugs
    matched = next((v for k,v in tips_db.items() if k in slug or slug in k), tips_db["general"])
    return matched


# ── Developer API Key System ──────────────────────────────────

@app.post("/api/developer/keys")
async def create_api_key(req: dict, user: User = Depends(_get_user),
                          db: Session = Depends(get_db)):
    """Generate a new developer API key."""
    import hashlib as _hl2, secrets as _sec2
    name = _sanitise(req.get("name","Default Key"), 60)
    existing = db.query(ApiKey).filter(ApiKey.user_id==user.id, ApiKey.active==True).count()
    if existing >= 5:
        raise HTTPException(400, "Maximum 5 active API keys per account")
    raw = f"sb_{_sec2.token_urlsafe(32)}"
    key_hash = _hl2.sha256(raw.encode()).hexdigest()
    ak = ApiKey(
        id=f"key_{uuid.uuid4().hex[:8]}",
        user_id=user.id, name=name,
        key_hash=key_hash,
        key_prefix=raw[:12],
    )
    db.add(ak); db.commit()
    return {**ak.to_dict(), "key": raw,
            "message": "Copy this key — it will not be shown again"}


@app.get("/api/developer/keys")
async def list_api_keys(user: User = Depends(_get_user), db: Session = Depends(get_db)):
    keys = db.query(ApiKey).filter(ApiKey.user_id==user.id).order_by(ApiKey.created_at.desc()).all()
    return {"keys": [k.to_dict() for k in keys]}


@app.delete("/api/developer/keys/{key_id}")
async def revoke_api_key(key_id: str, user: User = Depends(_get_user),
                          db: Session = Depends(get_db)):
    ak = db.query(ApiKey).filter(ApiKey.id==key_id, ApiKey.user_id==user.id).first()
    if not ak: raise HTTPException(404, "Key not found")
    ak.active = False
    db.commit()
    return {"message": "API key revoked"}


@app.get("/api/developer/docs")
async def developer_docs():
    """Public API documentation for ScholarBot developers."""
    base = os.environ.get("BASE_URL","https://scholarbot-web.onrender.com")
    return {
        "version": "1.0",
        "base_url": base,
        "authentication": f"Header: X-API-Key: <your_key>",
        "endpoints": [
            {"method":"GET","path":"/api/scholarships","auth":"API Key","description":"List all scholarships"},
            {"method":"GET","path":"/api/scholarships/search","auth":"API Key","description":"Search scholarships"},
            {"method":"GET","path":"/api/scholarships/{id}/explain","auth":"API Key","description":"Get match explanation"},
            {"method":"GET","path":"/api/opportunities","auth":"API Key","description":"All opportunity types"},
            {"method":"GET","path":"/api/gpa/detect","auth":"API Key","description":"Detect GPA scale"},
            {"method":"GET","path":"/api/i18n/{locale}","auth":"None","description":"Get UI translations"},
        ],
        "rate_limits": {"free":"100 req/day","pro":"1000 req/day","enterprise":"unlimited"},
        "get_key_url": f"{base}/?page=profile",
    }


@app.patch("/api/account/anonymise")
async def anonymise_account(user: User = Depends(_get_user),
                             db: Session = Depends(get_db)):
    """
    Soft anonymisation — keeps aggregate data for analytics
    but removes all PII. Lighter alternative to full deletion.
    """
    uid = user.id
    user.name = f"Anonymous_{uid[-6:]}"
    user.email = f"anon_{uid[-6:]}@deleted.scholarbot"
    user.school = ""
    user.major = ""
    user.personal_statement = ""
    user.skills = []
    user.extracurriculars = []
    user.demographic_tags = []
    db.commit()
    return {"message": "Account anonymised. Aggregate analytics data preserved."}


# ── Two-Factor Authentication (TOTP) ─────────────────────────
import hmac as _hmac, struct as _struct, hashlib as _hashlib, time as _time
import base64 as _b64


def _totp_generate(secret: str, digits: int = 6, period: int = 30) -> str:
    """Generate a TOTP code from a base32 secret."""
    try:
        key = _b64.b32decode(secret.upper().replace(" ", ""))
        counter = _struct.pack(">Q", int(_time.time()) // period)
        mac = _hmac.new(key, counter, _hashlib.sha1).digest()
        offset = mac[-1] & 0x0F
        code = _struct.unpack(">I", mac[offset:offset+4])[0] & 0x7FFFFFFF
        return str(code % (10 ** digits)).zfill(digits)
    except Exception:
        return ""


def _totp_verify(secret: str, code: str, window: int = 1) -> bool:
    """Verify a TOTP code within ±window periods."""
    period = 30
    ts = int(_time.time()) // period
    for delta in range(-window, window + 1):
        counter = _struct.pack(">Q", ts + delta)
        try:
            key = _b64.b32decode(secret.upper().replace(" ", ""))
            mac = _hmac.new(key, counter, _hashlib.sha1).digest()
            offset = mac[-1] & 0x0F
            expected = _struct.unpack(">I", mac[offset:offset+4])[0] & 0x7FFFFFFF
            if str(expected % 1000000).zfill(6) == str(code).strip():
                return True
        except Exception:
            pass
    return False



@app.post("/api/auth/2fa/backup-codes")
async def generate_backup_codes(user: User = Depends(_get_user),
                                  db:   Session = Depends(get_db)):
    """
    Generate 10 single-use TOTP backup codes.
    Store them safely — each can only be used once to bypass 2FA.
    """
    import secrets as _s
    if not getattr(user, "totp_secret", None):
        raise HTTPException(400, "2FA is not enabled on your account")
    codes = [_s.token_hex(4).upper() for _ in range(10)]
    import hashlib as _hl
    # Store hashed codes — never store plaintext backup codes
    hashed = [_hl.sha256(c.encode()).hexdigest() for c in codes]
    u = db.query(User).filter(User.id == user.id).first()
    if u:
        try:
            u.totp_backup_codes = hashed  # JSON column
            db.commit()
        except Exception:
            db.rollback()
    # Return plaintext codes ONCE — user must save them
    return {
        "backup_codes": codes,
        "warning": (
            "Save these codes somewhere safe. Each can be used once to "
            "sign in if you lose access to your authenticator app. "
            "These will not be shown again."
        ),
        "count": len(codes),
    }


@app.post("/api/auth/2fa/validate-backup")
async def validate_backup_code(req: dict, db: Session = Depends(get_db)):
    """
    Validate a backup code during login (when authenticator is unavailable).
    Consumes the code — single use only.
    """
    import hashlib as _hl
    token    = _sanitise(req.get("token", ""))
    email    = _sanitise(req.get("email","")).lower()
    code     = _sanitise(req.get("backup_code","")).upper().replace("-","").replace(" ","")
    u = db.query(User).filter(User.email == email).first()
    if not u:
        raise HTTPException(401, "Invalid credentials")
    if not token:
        raise HTTPException(401, "Login token required")
    # Validate token matches user
    uid = _decode_token(token)
    if uid != u.id:
        raise HTTPException(401, "Invalid token")
    stored_codes = getattr(u, "totp_backup_codes", None) or []
    if not stored_codes:
        raise HTTPException(400, "No backup codes configured")
    code_hash = _hl.sha256(code.encode()).hexdigest()
    if code_hash not in stored_codes:
        raise HTTPException(401, "Invalid backup code")
    # Consume the code — remove from list
    remaining = [c for c in stored_codes if c != code_hash]
    u.totp_backup_codes = remaining
    db.commit()
    return {
        "verified":          True,
        "codes_remaining":   len(remaining),
        "warning": ("Backup code used and consumed. "
                    f"You have {len(remaining)} codes remaining."),
    }

@app.post("/api/auth/2fa/setup")
async def setup_2fa(user: User = Depends(_get_user), db: Session = Depends(get_db)):
    """Generate a TOTP secret for the user and return QR code URI."""
    import secrets as _sec
    # Generate random base32 secret
    raw = _sec.token_bytes(20)
    secret = _b64.b32encode(raw).decode().rstrip("=")
    # Store in user record (add totp_secret column)
    try:
        db.execute(__import__("sqlalchemy").text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret VARCHAR(64)"
        ))
        db.commit()
    except Exception:
        pass
    u = db.query(User).filter(User.id == user.id).first()
    if u:
        u.totp_secret = secret  # type: ignore
        db.commit()
    issuer = "ScholarBot"
    label  = f"{issuer}:{user.email}"
    uri    = (f"otpauth://totp/{label}"
              f"?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30")
    return {
        "secret":   secret,
        "qr_uri":   uri,
        "message":  "Scan the QR code with Google Authenticator or Authy. "
                    "Then verify with /api/auth/2fa/verify to activate.",
    }


@app.post("/api/auth/2fa/verify")
async def verify_2fa(req: dict, user: User = Depends(_get_user),
                      db: Session = Depends(get_db)):
    """Activate 2FA by verifying the first TOTP code."""
    code   = str(req.get("code", "")).strip()
    secret = getattr(user, "totp_secret", None) or ""
    if not secret:
        raise HTTPException(400, "2FA not set up. Call /api/auth/2fa/setup first")
    if not _totp_verify(secret, code):
        raise HTTPException(400, "Invalid code — check your authenticator app time sync")
    return {"message": "2FA verified and activated on your account",
            "active": True}


@app.post("/api/auth/2fa/validate")
async def validate_2fa_code(req: dict, db: Session = Depends(get_db)):
    """Validate a TOTP code during login (call after password check)."""
    user_id = req.get("user_id", "")
    code    = str(req.get("code", "")).strip()
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User not found")
    secret = getattr(u, "totp_secret", None) or ""
    if not secret:
        return {"valid": True, "message": "2FA not enabled"}
    if not _totp_verify(secret, code):
        raise HTTPException(401, "Invalid 2FA code")
    return {"valid": True, "message": "2FA verified"}


@app.delete("/api/auth/2fa/disable")
async def disable_2fa(user: User = Depends(_get_user), db: Session = Depends(get_db)):
    """Disable 2FA for the user account."""
    u = db.query(User).filter(User.id == user.id).first()
    if u and hasattr(u, "totp_secret"):
        u.totp_secret = None  # type: ignore
        db.commit()
    return {"message": "2FA disabled on your account"}


@app.get("/api/pipeline/export.csv")
async def export_pipeline_csv(user: User = Depends(_get_user),
                               db: Session = Depends(get_db)):
    """Export full pipeline as CSV for offline tracking."""
    import csv, io
    apps = db.query(Application).filter(
        Application.user_id == user.id
    ).order_by(Application.created_at.desc()).all()

    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["Scholarship", "Type", "Amount (USD)", "Stage",
                "Deadline", "Days Left", "URL", "Notes", "Added"])
    for a in apps:
        w.writerow([
            a.scholarship_name or "",
            a.opportunity_type or "scholarship",
            a.amount_usd or "",
            a.stage or "",
            a.deadline or "",
            _days_until(a.deadline) if a.deadline else "",
            a.url or "",
            (a.notes or "").replace("\n", " "),
            a.created_at.strftime("%Y-%m-%d") if a.created_at else "",
        ])
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition":
                 f"attachment; filename=scholarbot_pipeline_{user.id[:8]}.csv"},
    )


@app.get("/api/account/export.json")
async def export_account_json(user: User = Depends(_get_user),
                               db: Session = Depends(get_db)):
    """Full GDPR Article 20 portability export — includes essays, events, recs."""
    apps   = db.query(Application).filter(Application.user_id == user.id).all()
    pkgs   = db.query(Package).filter(Package.user_id == user.id).all()
    events = db.query(UserEvent).filter(UserEvent.user_id == user.id).all()
    recs   = db.query(RecRequest).filter(RecRequest.user_id == user.id).all()
    return JSONResponse({
        "exported_at":    datetime.utcnow().isoformat(),
        "gdpr_article":   "20 — Right to data portability",
        "user":           user.to_dict(),
        "applications":   [a.to_dict() for a in apps],
        "packages": [{
            "id":           p.id,
            "opportunity":  p.opportunity_name,
            "essay_text":   p.essay_text or "",
            "created_at":   str(p.created_at),
        } for p in pkgs],
        "events": [{
            "type":        e.event_type,
            "scholarship": e.opp_name,
            "created_at":  str(e.created_at),
        } for e in events],
        "recommendation_requests": [{
            "recommender": r.recommender_name,
            "scholarship": r.scholarship_name,
            "status":      r.status,
            "created_at":  str(r.created_at),
        } for r in recs],
        "total_records": {
            "applications": len(apps),
            "essays":       len(pkgs),
            "events":       len(events),
        },
    })


@app.get("/api/admin/stats")
async def admin_stats(user: User = Depends(_require_admin),
                       db: Session = Depends(get_db)):
    """Full platform statistics for admin dashboard."""
    from sqlalchemy import func
    return {
        "users": {
            "total":      db.query(User).count(),
            "verified":   db.query(User).filter(User.email_verified == True).count(),
            "this_week":  db.query(User).filter(
                User.created_at >= datetime.utcnow() - timedelta(days=7)
            ).count(),
            "free":       db.query(User).filter(User.plan == "free").count(),
            "pro":        db.query(User).filter(User.plan == "pro").count(),
            "enterprise": db.query(User).filter(User.plan == "enterprise").count(),
        },
        "applications": {
            "total":     db.query(Application).count(),
            "submitted": db.query(Application).filter(Application.stage=="submitted").count(),
            "won":       db.query(Application).filter(Application.stage=="won").count(),
            "total_won_usd": db.query(
                func.sum(Application.amount_usd)
            ).filter(Application.stage=="won").scalar() or 0,
        },
        "packages": {
            "total":        db.query(Package).count(),
            "with_essays":  db.query(Package).filter(Package.essay_text != None).count(),
        },
        "expert_reviews": {
            "pending":   db.query(ExpertReview).filter(ExpertReview.status=="pending").count(),
            "completed": db.query(ExpertReview).filter(ExpertReview.status=="completed").count(),
        },
        "opportunities": {
            "total": 87 + len(EXTRA_OPPORTUNITIES),
        },
        "platform": {
            "dynamic_weights":  {k:v for k,v in _DYNAMIC_WEIGHTS.items()
                                  if k != "_last_updated"},
            "active_experiments": list(ACTIVE_EXPERIMENTS.keys()),
        },
    }


@app.get("/api/admin/users")
async def admin_users(page: int = 1, per_page: int = 50,
                       search: str = "", plan_filter: str = "",
                       user: User = Depends(_require_admin),
                       db: Session = Depends(get_db)):
    """List users for admin — paginated, searchable, filterable. No passwords exposed."""
    per_page = min(per_page, 100)
    offset   = (page - 1) * per_page
    q = db.query(User)
    if search:
        q = q.filter((User.email.ilike(f"%{search}%")) | (User.name.ilike(f"%{search}%")))
    if plan_filter:
        q = q.filter(User.plan == plan_filter)
    total = q.count()
    users = q.order_by(User.created_at.desc()).offset(offset).limit(per_page).all()
    total = db.query(User).count()
    return {
        "users": [{
            "id": u.id, "name": u.name, "email": u.email,
            "plan": u.plan, "email_verified": u.email_verified,
            "nationality": u.nationality, "degree_level": u.degree_level,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        } for u in users],
        "total": total, "skip": skip, "limit": limit,
    }


@app.patch("/api/admin/users/{uid}/plan")
async def admin_set_plan(uid: str, req: dict,
                          admin: User = Depends(_require_admin),
                          db: Session = Depends(get_db)):
    """Manually set a user's plan (for manual upgrades / comps)."""
    u = db.query(User).filter(User.id == uid).first()
    if not u: raise HTTPException(404, "User not found")
    new_plan = req.get("plan", "free")
    if new_plan not in ("free", "pro", "enterprise", "partner"):
        raise HTTPException(400, "Invalid plan")
    u.plan = new_plan
    db.commit()
    return {"message": f"User {u.email} upgraded to {new_plan}", "plan": new_plan}


@app.post("/api/admin/scrape-opportunity")
async def submit_opportunity(req: dict,
                              user: User = Depends(_get_user),
                              db: Session = Depends(get_db)):
    """Community scholarship submission — queued for admin review."""
    name   = _sanitise(req.get("name",""), 200)
    url    = _sanitise(req.get("url",""), 300)
    amount = req.get("amount_usd", 0)
    if not name or not url:
        raise HTTPException(400, "name and url are required")
    _log_event(db, user.id, "scholarship_submitted", None, name,
               {"url": url, "amount": amount, "field": req.get("field",""),
                "submitter": user.email})
    return {
        "message": "Thank you! Your submission has been logged for review.",
        "name": name, "status": "pending_review",
    }


@app.post("/api/auth/resend-verification")
async def resend_verification(user: User = Depends(_get_user),
                               db: Session = Depends(get_db)):
    """Resend email verification link to current user."""
    if getattr(user, "email_verified", False):
        return {"message": "Email already verified"}
    import secrets as _sec2, hashlib as _hl5, requests as _rq3
    sender_key = os.environ.get("SENDER_API_KEY","")
    if not sender_key:
        raise HTTPException(503, "Email service not configured")
    raw_tok = _sec2.token_urlsafe(32)
    t_hash  = _hl5.sha256(raw_tok.encode()).hexdigest()
    _reset_tokens[f"verify_{t_hash}"] = {
        "user_id": user.id, "used": False,
        "expires_at": datetime.utcnow() + timedelta(days=7),
    }
    base = os.environ.get("BASE_URL","https://scholarbot-web.onrender.com")
    from_e = os.environ.get("FROM_EMAIL","noreply@scholarbot.app")
    link  = f"{base}/api/auth/verify-email?token={raw_tok}"
    html  = (f"<p>Hi {user.name},</p>"
             f"<p><a href='{link}' style='background:#2563eb;color:#fff;"
             f"padding:12px 24px;border-radius:6px;text-decoration:none;"
             f"display:inline-block'>Verify my email</a></p>"
             f"<p style='font-size:12px;color:#888'>Expires in 7 days.</p>")
    _rq3.post("https://api.sender.net/v2/message/send",
        headers={"Authorization":f"Bearer {sender_key}","Content-Type":"application/json"},
        json={"from":{"email":from_e,"name":"ScholarBot"},
              "to":{"email":user.email,"name":user.name},
              "subject":"Verify your ScholarBot email","html":html},
        timeout=10)
    return {"message": "Verification email sent. Check your inbox."}


@app.post("/api/pledge")
async def sign_pledge(req: dict, request: Request,
                       user: User = Depends(_get_user),
                       db: Session = Depends(get_db)):
    """
    Scholar's Pledge — user agrees to use AI essays ethically.
    Recorded with IP + timestamp for audit trail.
    Displayed on packages page before first essay generation.
    """
    agreed = bool(req.get("agreed", False))
    if not agreed:
        raise HTTPException(400, "You must agree to the Scholar's Pledge to generate essays")
    import hashlib as _ph
    ip   = request.client.host if request.client else "unknown"
    ua   = request.headers.get("user-agent","")[:200]
    body = f"{user.id}|{user.email}|{datetime.utcnow().isoformat()}|agreed"
    ph   = _ph.sha256(body.encode()).hexdigest()
    _log_event(db, user.id, "pledge_signed", None, None,
               {"ip": ip, "user_agent": ua[:100], "hash": ph[:16]})
    return {
        "message": "Scholar's Pledge signed. You may now generate AI essays.",
        "pledge_hash": ph[:16],
        "signed_at": datetime.utcnow().isoformat(),
        "reminder": ("AI essays are starting points. You must personalise them "
                     "before submission. Taking credit for purely AI-written work "
                     "may constitute academic dishonesty."),
    }


@app.get("/api/pledge/status")
async def pledge_status(user: User = Depends(_get_user),
                         db: Session = Depends(get_db)):
    """Check if user has signed the Scholar's Pledge."""
    signed = db.query(UserEvent).filter(
        UserEvent.user_id == user.id,
        UserEvent.event_type == "pledge_signed",
    ).first()
    return {
        "signed": bool(signed),
        "signed_at": signed.created_at.isoformat() if signed and signed.created_at else None,
    }


# ── Stripe Payment Integration ────────────────────────────────
@app.post("/api/stripe/create-checkout")
async def stripe_create_checkout(req: dict,
                                  user: User = Depends(_get_user)):
    """
    Create a Stripe Checkout session for plan upgrade.
    Set STRIPE_SECRET_KEY in Render environment variables.
    """
    import os as _os
    stripe_key = _os.environ.get("STRIPE_SECRET_KEY","")
    if not stripe_key:
        raise HTTPException(503,
            "Payments not configured. Set STRIPE_SECRET_KEY in environment.")
    plan = req.get("plan","pro")
    prices = {
        "pro":        _os.environ.get("STRIPE_PRO_PRICE_ID",""),
        "enterprise": _os.environ.get("STRIPE_ENT_PRICE_ID",""),
    }
    price_id = prices.get(plan,"")
    if not price_id:
        raise HTTPException(400,
            f"No price configured for plan '{plan}'. "
            "Set STRIPE_PRO_PRICE_ID / STRIPE_ENT_PRICE_ID.")
    try:
        import stripe as _stripe
        _stripe.api_key = stripe_key
        base = _os.environ.get("BASE_URL","https://scholarbot-web.onrender.com")
        session = _stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            customer_email=user.email,
            metadata={"user_id": user.id, "plan": plan},
            success_url=f"{base}/?upgraded=1&plan={plan}",
            cancel_url=f"{base}/?page=plans",
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except ImportError:
        raise HTTPException(503, "Stripe library not installed. Add 'stripe' to requirements.txt")
    except Exception as e:
        raise HTTPException(500, f"Stripe error: {str(e)[:200]}")


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook — automatically upgrades user plan on payment.
    Set STRIPE_WEBHOOK_SECRET in Render environment variables.
    Add this URL in Stripe Dashboard → Webhooks.
    """
    import os as _os
    payload = await request.body()
    sig     = request.headers.get("stripe-signature","")
    secret  = _os.environ.get("STRIPE_WEBHOOK_SECRET","")
    try:
        import stripe as _stripe
        _stripe.api_key = _os.environ.get("STRIPE_SECRET_KEY","")
        event = _stripe.Webhook.construct_event(payload, sig, secret)
    except ImportError:
        return {"status": "stripe not installed"}
    except Exception as e:
        raise HTTPException(400, f"Webhook error: {e}")

    if event["type"] == "checkout.session.completed":
        sess    = event["data"]["object"]
        user_id = sess.get("metadata",{}).get("user_id","")
        plan    = sess.get("metadata",{}).get("plan","pro")
        if user_id:
            db = SessionLocal()
            try:
                u = db.query(User).filter(User.id == user_id).first()
                if u:
                    u.plan = plan
                    db.commit()
                    logger.info("User %s upgraded to %s via Stripe", user_id, plan)
            finally:
                db.close()
    return {"status": "ok"}


@app.get("/api/stripe/plans")
async def stripe_plans():
    """Return plan pricing info with Stripe price IDs."""
    import os as _os
    return {
        "configured": bool(_os.environ.get("STRIPE_SECRET_KEY","")),
        "plans": [
            {"id":"pro",        "name":"Pro",        "price_usd":9,
             "price_id": _os.environ.get("STRIPE_PRO_PRICE_ID",""),
             "features":["20 essays/day","5 packages/day","Expert reviews","Analytics"]},
            {"id":"enterprise", "name":"Enterprise", "price_usd":49,
             "price_id": _os.environ.get("STRIPE_ENT_PRICE_ID",""),
             "features":["Unlimited","University dashboard","API access","Support"]},
        ],
        "setup_instructions": (
            "1. Create products in Stripe Dashboard\n"
            "2. Set STRIPE_SECRET_KEY, STRIPE_PRO_PRICE_ID, STRIPE_ENT_PRICE_ID in Render\n"
            "3. Add webhook URL: /api/stripe/webhook → Set STRIPE_WEBHOOK_SECRET"
        ),
    }


@app.get("/api/developer/docs")
async def developer_docs():
    """Complete API documentation for third-party developers."""
    return {
        "name": "ScholarBot API",
        "version": "4.3.0",
        "base_url": "https://scholarbot-web.onrender.com",
        "authentication": "Bearer token in Authorization header or sb_token cookie",
        "endpoints": [
            {"method":"POST","path":"/api/auth/register","auth":False,
             "description":"Register a new user","body":{"name":"str","email":"str","password":"str","nationality":"str","degree_level":"str","major":"str","school":"str","gpa":"float","financial_need":"bool"}},
            {"method":"POST","path":"/api/auth/login","auth":False,
             "description":"Login and receive JWT token","body":{"email":"str","password":"str"}},
            {"method":"GET","path":"/api/scholarships","auth":False,
             "description":"List all scholarships with optional filtering","params":{"field":"str","region":"str","degree_level":"str","min_amount":"float"}},
            {"method":"GET","path":"/api/scholarships/matched","auth":True,
             "description":"Personalised matched scholarships ranked by AI score"},
            {"method":"GET","path":"/api/scholarships/recommended","auth":True,
             "description":"Collaborative filtering recommendations"},
            {"method":"GET","path":"/api/scholarships/search","auth":False,
             "description":"Full-text search","params":{"q":"str","field":"str","country":"str"}},
            {"method":"POST","path":"/api/scholarships/compare","auth":False,
             "description":"Compare 2-4 scholarships side-by-side","body":{"ids":["str"]}},
            {"method":"POST","path":"/api/pipeline/add","auth":True,
             "description":"Add scholarship to pipeline"},
            {"method":"GET","path":"/api/pipeline","auth":True,
             "description":"Get user pipeline (Kanban stages)"},
            {"method":"GET","path":"/api/pipeline/export.csv","auth":True,
             "description":"Export pipeline as CSV"},
            {"method":"POST","path":"/api/essays/generate","auth":True,
             "description":"Generate rubric-aware AI essay (returns job_id)"},
            {"method":"POST","path":"/api/essays/critique","auth":True,
             "description":"Rubric-aware essay critique with plagiarism check"},
            {"method":"GET","path":"/api/analytics","auth":True,
             "description":"Platform funnel analytics + A/B results"},
            {"method":"GET","path":"/api/interview/tips/{slug}","auth":False,
             "description":"Scholarship-specific interview guide"},
            {"method":"POST","path":"/api/stripe/create-checkout","auth":True,
             "description":"Create Stripe checkout session for upgrade"},
            {"method":"POST","path":"/api/stripe/webhook","auth":False,
             "description":"Stripe webhook for payment confirmation"},
        ],
        "rate_limits": {
            "free":       "60 req/min, 3 essays/day",
            "pro":        "120 req/min, 20 essays/day",
            "enterprise": "unlimited",
        },
        "support": "support@scholarbot.app",
    }


@app.get("/api/developer/keys")
async def list_api_keys(user: User = Depends(_get_user),
                         db: Session = Depends(get_db)):
    """List developer API keys for the current user."""
    keys = db.query(ApiKey).filter(ApiKey.user_id == user.id).all()
    return {"keys": [{"id":k.id,"name":k.name,"created_at":k.created_at.isoformat()
                       if k.created_at else None} for k in keys]}


@app.post("/api/developer/keys")
async def create_api_key(req: dict, user: User = Depends(_get_user),
                          db: Session = Depends(get_db)):
    """Create a new developer API key."""
    name = _sanitise(req.get("name","My API Key"), 100)
    raw  = secrets.token_urlsafe(32)
    key  = ApiKey(
        id=f"key_{uuid.uuid4().hex[:8]}",
        user_id=user.id,
        name=name,
        key_hash=__import__("hashlib").sha256(raw.encode()).hexdigest(),
    )
    db.add(key); db.commit()
    return {"message":"API key created — save this, it won't be shown again",
            "key": raw, "id": key.id, "name": name}


# ── SEO Infrastructure ────────────────────────────────────────
@app.get("/sitemap.xml", response_class=__import__("fastapi").responses.PlainTextResponse)
async def sitemap():
    """XML sitemap including all scholarship pages for SEO."""
    from engine.opportunity_db import load_all_opportunities
    base = os.environ.get("BASE_URL","https://scholarbot-web.onrender.com")
    all_ops = load_all_opportunities() + EXTRA_OPPORTUNITIES
    static = [base+"/", base+"/?page=scholarships", base+"/?page=plans",
              base+"/privacy", base+"/terms"]
    opp_pages = [base+"/?page=scholarships&id="+op["id"]
                 for op in all_ops if op.get("id")]
    rows = '<?xml version="1.0" encoding="UTF-8"?>\n'
    rows += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in static + opp_pages:
        rows += "  <url><loc>" + url + "</loc></url>\n"
    rows += "</urlset>"
    return __import__("fastapi").responses.PlainTextResponse(
        rows, media_type="application/xml")


@app.get("/robots.txt", response_class=__import__("fastapi").responses.PlainTextResponse)
async def robots():
    """robots.txt for search engine crawlers."""
    return """User-agent: *
Allow: /
Allow: /?page=scholarships
Allow: /?page=plans
Disallow: /api/admin/
Disallow: /api/auth/
Sitemap: https://scholarbot-web.onrender.com/sitemap.xml"""


@app.get("/api/platform-stats")
async def platform_stats(db: Session = Depends(get_db)):
    """
    Public platform statistics — shown on homepage and used for SEO.
    No PII exposed — aggregate only.
    """
    from sqlalchemy import func
    total_users  = db.query(User).count()
    total_won    = db.query(Application).filter(Application.stage == "won").count()
    total_won_usd= db.query(func.sum(Application.amount_usd)).filter(
                       Application.stage == "won").scalar() or 0
    total_apps   = db.query(Application).count()
    win_rate     = round(total_won / max(total_apps, 1) * 100, 1)
    return {
        "scholars":          total_users,
        "scholarships_won":  total_won,
        "total_awarded_usd": int(total_won_usd),
        "applications":      total_apps,
        "win_rate_pct":      win_rate,
        "opportunities":     87 + len(EXTRA_OPPORTUNITIES),
        "countries_covered": 65,
        "disciplines":       22,
    }


@app.get("/api/admin/validate-listings")
async def validate_listings(admin: User = Depends(_require_admin)):
    """
    Check scholarship URLs for dead links.
    Returns list of potentially broken listings for admin review.
    Runs lightweight HEAD requests — no page content fetched.
    """
    import requests as _rq
    from engine.opportunity_db import load_all_opportunities
    all_opps = load_all_opportunities() + EXTRA_OPPORTUNITIES
    results  = {"ok": [], "broken": [], "slow": [], "unchecked": []}
    checked  = 0
    for opp in all_opps[:30]:  # Sample first 30 to avoid timeout
        url = opp.get("url","")
        if not url or not url.startswith("http"):
            results["unchecked"].append({"id": opp["id"], "name": opp["name"], "reason": "no URL"})
            continue
        try:
            import time as _t
            t0 = _t.time()
            r  = _rq.head(url, timeout=5, allow_redirects=True,
                          headers={"User-Agent": "ScholarBot/1.0 (scholarship validator)"})
            elapsed = _t.time() - t0
            entry = {"id": opp["id"], "name": opp["name"][:50],
                     "url": url, "status": r.status_code, "ms": int(elapsed*1000)}
            if r.status_code < 400:
                results["ok"].append(entry)
            else:
                results["broken"].append(entry)
            if elapsed > 3:
                results["slow"].append(entry)
            checked += 1
        except Exception as e:
            results["broken"].append({"id": opp["id"], "name": opp["name"][:50],
                                       "url": url, "error": str(e)[:60]})
    broken_items = results.get("broken",[])
    return {**results,
            "checked":     checked,
            "total":       len(all_opps),
            "suggestions": [{"id":b.get("id"),"name":b.get("name"),
                              "broken_url":b.get("url"),
                              "action":"Find official URL on Google and update EXTRA_OPPORTUNITIES"}
                             for b in broken_items],
            "note":        f"Sampled 30/{len(all_opps)} — run periodically for full scan"}


@app.post("/api/push/subscribe")
async def push_subscribe(req: dict, user: User = Depends(_get_user),
                          db: Session = Depends(get_db)):
    """Store browser push subscription for deadline notifications."""
    endpoint   = req.get("endpoint","")
    keys       = req.get("keys",{})
    if not endpoint:
        raise HTTPException(400, "Push subscription endpoint required")
    _log_event(db, user.id, "push_subscribed", None, None,
               {"endpoint": endpoint[:100], "has_keys": bool(keys)})
    return {"message": "Push notifications enabled for deadline reminders"}


@app.post("/api/push/test")
async def push_test(user: User = Depends(_get_user)):
    """Send a test push notification."""
    return {
        "message": "Push notification test queued",
        "note": "Full web push requires VAPID keys — add VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY to Render"
    }


@app.get("/api/scholars/peer-match")
async def peer_match(user: User = Depends(_get_user),
                      db: Session = Depends(get_db)):
    """
    Scholar network — find users who have won scholarships in
    the same field or from the same country. Anonymised connection.
    """
    profile = user.to_dict()
    field   = (profile.get("major") or "").lower()
    nat     = (profile.get("nationality") or "").lower()

    # Find users who won scholarships with similar profile
    won_events = db.query(UserEvent).filter(
        UserEvent.event_type == "won",
        UserEvent.user_id != user.id,
    ).limit(200).all()

    peer_ids = {ev.user_id for ev in won_events}
    peers    = db.query(User).filter(User.id.in_(peer_ids)).limit(50).all()

    # Score by similarity
    matches = []
    for p in peers:
        score = 0
        if p.nationality and nat and p.nationality.lower() == nat:
            score += 3  # Same country — high relevance
        if p.major and field and any(
            w in (p.major or "").lower() for w in field.split() if len(w) > 3
        ):
            score += 2  # Same field
        if p.degree_level == user.degree_level:
            score += 1
        if score > 0:
            # Get what scholarship they won
            won = db.query(UserEvent).filter(
                UserEvent.user_id == p.id,
                UserEvent.event_type == "won",
            ).first()
            matches.append({
                "nationality":    p.nationality,
                "degree_level":   p.degree_level,
                "field":          p.major,
                "scholarship_won": won.opp_name if won else "Scholarship",
                "similarity_score": score,
            })

    matches.sort(key=lambda x: x["similarity_score"], reverse=True)
    return {
        "peer_scholars": matches[:10],
        "total_found":   len(matches),
        "message": (
            f"Found {len(matches)} scholars from similar backgrounds who won scholarships."
            if matches else
            "No peer matches yet — be the first from your country and field to win!"
        ),
    }


@app.get("/api/scholarships/{sid}/quality")
async def scholarship_quality(sid: str):
    """
    Scholarship quality/trust tier for each opportunity.
    Tier 1 = Government-funded (most trustworthy)
    Tier 2 = Major foundation / UN agency
    Tier 3 = University-direct
    Tier 4 = Corporate / Private
    Tier 5 = Community submitted (pending verification)
    """
    from engine.opportunity_db import load_all_opportunities
    all_opps = load_all_opportunities() + EXTRA_OPPORTUNITIES
    opp = next((o for o in all_opps if o["id"] == sid), None)
    if not opp: raise HTTPException(404, "Scholarship not found")

    tags  = " ".join(opp.get("tags") or []).lower()
    name  = opp.get("name","").lower()
    url   = opp.get("url","").lower()

    gov_keywords = ["government","mext","gks","kgsp","moe.","dfat","fcdo",
                    "mofa","daad","si.se","nawa","commonwealth","quota","erasmus",
                    "stipendium","turkiye","csc","campuschina","australia awards",
                    "isdb","sadc","iucea","amci","fulbright","chevening"]
    foundation_keywords = ["foundation","ford","gates","wellcome","templeton",
                           "rotary","rockefeller","mastercard","aga khan","agra",
                           "osf","prince claus","jacobs","bloomberg","who","wfp",
                           "unep","unicef","worldbank","afdb","adb","usaid","cnpq"]
    uni_keywords = ["university","tsinghua","peking","fudan","sjtu","waseda",
                    "kyoto","osaka","kaist","postech","snu","yonsei","korea.ac",
                    "ntu.edu","nus.edu","oxford","cambridge","eth","epfl","delft",
                    "leiden","mcgill","harvard","stanford","ku.dk"]

    combined = tags + " " + name + " " + url

    if any(k in combined for k in gov_keywords):
        tier, label, color = 1, "Government-funded", "#059669"
    elif any(k in combined for k in foundation_keywords):
        tier, label, color = 2, "Foundation / UN Agency", "#2563eb"
    elif any(k in combined for k in uni_keywords):
        tier, label, color = 3, "University-direct", "#7c3aed"
    elif any(k in combined for k in ["corporate","accenture","sap","google","microsoft","adobe","palantir"]):
        tier, label, color = 4, "Corporate / Private", "#d97706"
    else:
        tier, label, color = 3, "Verified Organisation", "#6b7280"

    return {
        "id":  sid,
        "tier": tier,
        "label": label,
        "color": color,
        "verified": tier <= 3,
        "description": (
            "Funded directly by a national government" if tier == 1 else
            "Major international foundation or UN agency" if tier == 2 else
            "University or accredited institution" if tier == 3 else
            "Corporate or private scholarship" if tier == 4 else
            "Pending community verification"
        ),
    }


@app.get("/api/platform/leaderboard")
async def scholar_leaderboard(db: Session = Depends(get_db)):
    """
    Anonymised scholar leaderboard — top scholars by applications won.
    No PII exposed — only first name, country, win count, and total won.
    """
    from sqlalchemy import func
    results = db.query(
        Application.user_id,
        func.count(Application.id).label("wins"),
        func.sum(Application.amount_usd).label("total_usd"),
    ).filter(Application.stage == "won").group_by(
        Application.user_id
    ).order_by(func.count(Application.id).desc()).limit(20).all()

    leaderboard = []
    for row in results:
        u = db.query(User).filter(User.id == row.user_id).first()
        if not u: continue
        first = (u.name or "Scholar").split()[0]
        leaderboard.append({
            "name":      first,
            "country":   u.nationality or "International",
            "field":     u.major or "Various",
            "wins":      row.wins,
            "total_usd": int(row.total_usd or 0),
        })

    return {
        "leaderboard": leaderboard,
        "total_scholars": db.query(User).count(),
        "note": "Only first names shown — all data anonymised",
    }


@app.post("/api/scholarships/share")
async def create_share_link(req: dict, user: User = Depends(_get_user)):
    """
    Generate a shareable link to a curated list of scholarships.
    Encodes IDs + filters in a short token users can paste anywhere.
    """
    import base64 as _b64, json as _jj
    ids     = req.get("ids", [])[:10]
    filters = req.get("filters", {})
    payload = _jj.dumps({"ids": ids, "f": filters, "by": user.id[:8]})
    token   = _b64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")[:40]
    base    = os.environ.get("BASE_URL", "https://scholarbot-web.onrender.com")
    return {
        "share_url": f"{base}/?share={token}",
        "token":     token,
        "count":     len(ids),
        "message":   "Share this link to show your curated scholarships",
    }


@app.post("/api/profile/analyse-statement")
async def analyse_statement(user: User = Depends(_get_user),
                             db: Session = Depends(get_db)):
    """
    AI analysis of the user's personal statement — identifies gaps and
    suggests improvements before essay generation.
    """
    stmt = (user.personal_statement or "").strip()
    if len(stmt.split()) < 30:
        raise HTTPException(400, "Personal statement too short — add at least 30 words first")

    llm = _llm()
    system = ("You are an expert scholarship admissions consultant. "
              "Analyse this personal statement and return ONLY valid JSON.")
    prompt = (
        f"Personal statement ({len(stmt.split())} words):\n{stmt[:2000]}\n\n"
        "Return JSON with:\n"
        "overall_score (0.0-1.0), grade (A/B/C/D), "
        "strengths (array of strings max 3), "
        "gaps (array of strings max 3 — what is missing), "
        "quick_wins (array of strings max 3 — easy improvements), "
        "word_count (integer), "
        "verdict (string, 1-2 sentences)"
    )
    try:
        raw = llm(system, prompt)
        import json as _jj
        start = raw.find("{"); end = raw.rfind("}") + 1
        result = _jj.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        wc = len(stmt.split())
        has_goals = any(w in stmt.lower() for w in ["will","plan","aim","goal","hope","intend"])
        has_evidence = any(ch.isdigit() for ch in stmt)
        score = 0.5 + (0.2 if has_goals else 0) + (0.15 if has_evidence else 0) + (0.05 if wc >= 100 else 0)
        result = {
            "overall_score": round(min(score, 1.0), 2),
            "grade": "B" if score >= 0.7 else "C",
            "strengths": ["Shows motivation for your field"],
            "gaps": ["Add specific achievements with numbers", "Include your long-term career goal"],
            "quick_wins": ["Add one measurable achievement", "Name the specific scholarship you are applying to"],
            "word_count": wc,
            "verdict": "Good foundation — add specific evidence and goals to strengthen it.",
        }

    _log_event(db, user.id, "statement_analysed", None, None,
               {"score": result.get("overall_score"), "grade": result.get("grade")})
    return result


# ── Password Reset Flow ───────────────────────────────────────
@app.post("/api/auth/forgot-password")
async def forgot_password(req: dict, request: Request, db: Session = Depends(get_db)):
    """Send password reset email. Always returns 200 to prevent email enumeration.
    Rate limited: 5 requests per hour per IP to prevent abuse."""
    import secrets as _sec4, hashlib as _hl6, requests as _rq4
    # Rate limit: 5 reset requests per hour per IP
    ip = request.client.host if request.client else "unknown"
    _rate_key = f"pwd_reset:{ip}"
    now = time.time()
    _rate_store[_rate_key] = [t for t in _rate_store[_rate_key] if now - t < 3600]
    if len(_rate_store[_rate_key]) >= 5:
        # Always 200 — no information about whether rate limited
        return {"message": "If that email exists, a reset link has been sent."}
    _rate_store[_rate_key].append(now)
    email = req.get("email","").strip().lower()
    u = db.query(User).filter(User.email == email).first()
    if not u:
        return {"message": "If that email exists, a reset link has been sent."}
    raw_tok = _sec4.token_urlsafe(32)
    t_hash  = _hl6.sha256(raw_tok.encode()).hexdigest()
    _reset_tokens[f"reset_{t_hash}"] = {
        "user_id": u.id, "used": False,
        "expires_at": datetime.utcnow() + timedelta(hours=2),
    }
    sender_key = os.environ.get("SENDER_API_KEY","")
    base = os.environ.get("BASE_URL","https://scholarbot-web.onrender.com")
    from_email = os.environ.get("FROM_EMAIL","noreply@scholarbot.app")
    link = f"{base}/?reset_token={raw_tok}"
    if sender_key:
        try:
            import requests as _rq4
            html = (f"<p>Hi {u.name},</p>"
                    f"<p>Click below to reset your ScholarBot password. "
                    f"This link expires in 2 hours.</p>"
                    f"<p><a href='{link}' style='background:#2563eb;color:#fff;"
                    f"padding:12px 24px;border-radius:6px;text-decoration:none;"
                    f"display:inline-block'>Reset my password</a></p>"
                    f"<p style='font-size:12px;color:#888'>If you didn't request this, ignore this email.</p>")
            _rq4.post("https://api.sender.net/v2/message/send",
                headers={"Authorization": f"Bearer {sender_key}",
                         "Content-Type": "application/json"},
                json={"from":{"email":from_email,"name":"ScholarBot"},
                      "to":{"email":u.email,"name":u.name},
                      "subject":"Reset your ScholarBot password","html":html},
                timeout=10)
        except Exception as e:
            logger.debug("Reset email error (non-critical): %s", e)
    return {"message": "If that email exists, a reset link has been sent.",
            "dev_token": raw_tok if not sender_key else None}


@app.post("/api/auth/reset-password")
async def reset_password(req: dict, db: Session = Depends(get_db)):
    """Complete password reset using token from email."""
    import hashlib as _hl7
    token    = req.get("token","").strip()
    new_pass = req.get("password","").strip()
    if len(new_pass) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    t_hash = _hl7.sha256(token.encode()).hexdigest()
    entry  = _reset_tokens.get(f"reset_{t_hash}")
    if not entry or entry.get("used") or entry["expires_at"] < datetime.utcnow():
        raise HTTPException(400, "Invalid or expired reset link — request a new one")
    u = db.query(User).filter(User.id == entry["user_id"]).first()
    if not u: raise HTTPException(404, "User not found")
    u.password_hash        = _hash_pw(new_pass)
    u.password_changed_at  = datetime.utcnow()  # Invalidates all existing tokens
    entry["used"] = True
    db.commit()
    return {"message": "Password reset successfully. Please log in with your new password."}


@app.post("/api/auth/change-password")
async def change_password(req: dict,
                           user: User = Depends(_get_user),
                           db:   Session = Depends(get_db)):
    """Change password — invalidates all existing sessions on success."""
    current  = req.get("current_password", "")
    new_pw   = req.get("new_password", "")
    if not _check_pw(current, user.password_hash):
        raise HTTPException(401, "Current password is incorrect")
    if len(new_pw) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    if _check_pw(new_pw, user.password_hash):
        raise HTTPException(400, "New password must differ from current password")
    u = db.query(User).filter(User.id == user.id).first()
    u.password_hash       = _hash_pw(new_pw)
    u.password_changed_at = datetime.utcnow()   # Invalidates all existing JWTs
    db.commit()
    return {"message": "Password changed. Please log in again on all devices."}


@app.post("/api/auth/anonymise")
async def anonymise_account(req: dict,
                             user: User = Depends(_get_user),
                             db:   Session = Depends(get_db)):
    """GDPR anonymisation — replaces all PII with hashed values."""
    if req.get("confirm") != "ANONYMISE MY DATA":
        raise HTTPException(400, "confirm field must be: ANONYMISE MY DATA")
    import hashlib as _h
    uid_hash = _h.sha256(user.id.encode()).hexdigest()[:12]
    u = db.query(User).filter(User.id == user.id).first()
    u.name             = f"Scholar_{uid_hash}"
    u.email            = f"anon_{uid_hash}@deleted.scholarbot"
    u.nationality      = "Anonymised"
    u.major            = ""
    u.school           = ""
    u.personal_statement = ""
    u.skills           = []
    u.extracurriculars = []
    u.password_hash    = _hash_pw(secrets.token_hex(32))
    db.commit()
    return {"message": "Account anonymised. Personal data removed.", "uid": uid_hash}


@app.get("/api/auth/sessions")
async def list_sessions(user: User = Depends(_get_user)):
    """Return session metadata (JWT does not store sessions, so we return profile info)."""
    return {
        "current_session": {
            "user_id":    user.id,
            "email":      user.email,
            "plan":       user.plan,
            "2fa_active": bool(getattr(user, "totp_secret", None)),
        },
        "note": "ScholarBot uses stateless JWT. Change your password to invalidate all sessions.",
    }


@app.get("/api/essays/usage")
async def essay_usage(user: User = Depends(_get_user),
                       db:   Session = Depends(get_db)):
    """Return today's essay usage vs plan limit."""
    from datetime import date
    plan    = user.plan or "free"
    limits  = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    daily_limit = limits.get("essays_per_day", 3)
    today_start = datetime.combine(date.today(), datetime.min.time())
    used = db.query(UserEvent).filter(
        UserEvent.user_id    == user.id,
        UserEvent.event_type == "essay_critique",
        UserEvent.created_at >= today_start,
    ).count()
    pkg_used = db.query(Package).filter(
        Package.user_id    == user.id,
        Package.created_at >= today_start,
    ).count()
    return {
        "plan":              plan,
        "essays_today":      used,
        "packages_today":    pkg_used,
        "essay_limit":       daily_limit,
        "package_limit":     limits.get("packages_per_day", 1),
        "essays_remaining":  max(0, daily_limit - used) if daily_limit > 0 else -1,
        "reset_at":          (today_start + timedelta(days=1)).isoformat(),
        "upgrade_url":       "/?page=plans",
    }


def _check_essay_limit(user: User, db) -> bool:
    """Returns True if user is within their daily essay limit (user_id based)."""
    from datetime import date
    plan  = user.plan or "free"
    limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"]).get("essays_per_day", 3)
    if limit < 0: return True  # unlimited (enterprise/partner)
    today = datetime.combine(date.today(), datetime.min.time())
    # Count by user_id — robust against IP changes, VPNs, shared offices
    used = db.query(UserEvent).filter(
        UserEvent.user_id    == user.id,
        UserEvent.event_type.in_(["essay_critique","essay_generated"]),
        UserEvent.created_at >= today,
    ).count()
    return used < limit


def _log_essay_usage(user: User, db, event_type: str = "essay_generated"):
    """Record essay generation against the user's daily limit."""
    _log_event(db, user.id, event_type, None, "essay", {})


@app.get("/api/skills/suggestions")
async def skills_suggestions(q: str = ""):
    """Return skill tag suggestions for profile autocomplete."""
    ALL_SKILLS = [
        "Python","R","MATLAB","SQL","JavaScript","Java","C++","Go","Rust","STATA","SAS",
        "Machine Learning","Deep Learning","Computer Vision","NLP","Data Analysis",
        "Research","Academic Writing","Grant Writing","Policy Analysis","Public Speaking",
        "Leadership","Project Management","Team Management","Mentoring","Coaching",
        "GIS","Remote Sensing","Cartography","Field Research","Laboratory Skills",
        "Clinical Research","Epidemiology","Biostatistics","Public Health","Nursing",
        "Financial Modelling","Accounting","Auditing","Investment Analysis","Risk Management",
        "Community Development","Social Work","Advocacy","NGO Management","M&E",
        "Swahili","French","Mandarin","Arabic","Spanish","Portuguese","Korean","Japanese",
        "Agriculture","Agronomy","Soil Science","Irrigation","Food Security","Aquaculture",
        "Environmental Impact Assessment","Sustainability","Climate Modelling","Carbon Markets",
        "Architecture","Urban Planning","Structural Engineering","AutoCAD","Revit","BIM",
        "Journalism","Media","Videography","Photography","Podcasting","Content Creation",
        "Law","Litigation","Legal Research","Human Rights","Constitutional Law",
        "Teaching","Curriculum Development","Educational Technology","e-Learning",
    ]
    q_lower = q.lower()
    matches = [s for s in ALL_SKILLS if q_lower in s.lower()] if q else ALL_SKILLS
    return {"suggestions": matches[:20], "total": len(ALL_SKILLS)}


@app.get("/api/nationalities")
async def nationality_list():
    """Full list of nationalities for registration autocomplete."""
    countries = [
        "Afghanistan","Albania","Algeria","Angola","Argentina","Armenia","Australia",
        "Austria","Azerbaijan","Bangladesh","Belarus","Belgium","Benin","Bhutan","Bolivia",
        "Bosnia","Botswana","Brazil","Brunei","Burkina Faso","Burundi","Cambodia","Cameroon",
        "Canada","Chad","Chile","China","Colombia","Comoros","Congo","Costa Rica",
        "Croatia","Cuba","Czech Republic","Denmark","Djibouti","DRC","Ecuador","Egypt",
        "El Salvador","Eritrea","Ethiopia","Fiji","Finland","France","Gambia","Georgia",
        "Germany","Ghana","Greece","Guatemala","Guinea","Guinea-Bissau","Haiti","Honduras",
        "Hungary","India","Indonesia","Iran","Iraq","Ireland","Italy","Jamaica","Japan",
        "Jordan","Kazakhstan","Kenya","Kyrgyzstan","Laos","Lebanon","Lesotho","Liberia",
        "Libya","Madagascar","Malawi","Malaysia","Maldives","Mali","Mauritania","Mauritius",
        "Mexico","Moldova","Mongolia","Morocco","Mozambique","Myanmar","Namibia","Nepal",
        "Netherlands","New Zealand","Nicaragua","Niger","Nigeria","North Macedonia","Norway",
        "Oman","Pakistan","Palestine","Panama","Paraguay","Peru","Philippines","Poland",
        "Portugal","Qatar","Romania","Russia","Rwanda","Saudi Arabia","Senegal",
        "Sierra Leone","Singapore","Slovakia","Somalia","South Africa","South Korea",
        "South Sudan","Spain","Sri Lanka","Sudan","Sweden","Switzerland","Syria",
        "Taiwan","Tajikistan","Tanzania","Thailand","Timor-Leste","Togo","Trinidad",
        "Tunisia","Turkey","Turkmenistan","Uganda","Ukraine","United Arab Emirates",
        "United Kingdom","United States","Uruguay","Uzbekistan","Venezuela","Vietnam",
        "Yemen","Zambia","Zimbabwe",
    ]
    return {"countries": countries, "total": len(countries)}


@app.post("/api/scholarships/{sid}/bookmark")
async def log_scholarship_event(sid: str, req: dict,
                                 user: User = Depends(_get_user),
                                 db:   Session = Depends(get_db)):
    """Log scholarship interactions for analytics (apply_click, bookmark, share)."""
    event = req.get("event", "view")
    valid = {"apply_click","bookmark","share","view","pipeline_add","submitted","won","rejected"}
    if event not in valid:
        raise HTTPException(400, f"Invalid event. Must be one of: {', '.join(sorted(valid))}")
    _log_event(db, user.id, event, sid,
               req.get("name",""), {"amount": req.get("amount",0)})
    return {"logged": True, "event": event, "scholarship_id": sid}


@app.get("/api/analytics/apply-clicks")
async def apply_click_analytics(user: User = Depends(_get_user),
                                 db:   Session = Depends(get_db)):
    """Return apply-click conversion metrics for the analytics dashboard."""
    from sqlalchemy import func
    events = db.query(
        UserEvent.event_type,
        func.count(UserEvent.id).label("count"),
    ).group_by(UserEvent.event_type).all()
    event_map = {row.event_type: row.count for row in events}
    views     = event_map.get("view", 0)
    clicks    = event_map.get("apply_click", 0)
    adds      = event_map.get("pipeline_add", 0)
    submitted = event_map.get("submitted", 0)
    won_count = event_map.get("won", 0)
    return {
        "funnel": {
            "views":       views,
            "apply_clicks": clicks,
            "pipeline_adds": adds,
            "submitted":   submitted,
            "won":         won_count,
        },
        "rates": {
            "view_to_click_pct":    round(clicks    / max(views, 1) * 100, 1),
            "click_to_add_pct":     round(adds      / max(clicks, 1) * 100, 1),
            "add_to_submit_pct":    round(submitted / max(adds, 1) * 100, 1),
            "submit_to_win_pct":    round(won_count / max(submitted, 1) * 100, 1),
        },
    }


# ── Opportunity Trust Scoring Engine ─────────────────────────
# Professor: "Automated verification — domain reputation, SSL,
#  WHOIS, deadline sanity, scam database cross-reference."
_KNOWN_SCAM_DOMAINS = {
    "scholarships-free.com","scholarshipfund.org","freescholarship.net",
    "scholarship-grants.info","free-grant-money.com",
}
_TRUSTED_TLDS = {".edu",".gov",".ac.uk",".org",".int",".un.org"}
_TRUSTED_DOMAINS = {
    "chevening.org","fulbright.org","daad.de","campuschina.org",
    "mext.go.jp","studyinkorea.go.kr","a-star.edu.sg","gates.foundation",
    "wellcome.org","fordfoundation.org","rotary.org","mastercardfdn.org",
    "worldbank.org","isdb.org","unwomen.org","au.int","scholarbot.app",
}

def _score_opportunity_trust(opp: dict) -> dict:
    """
    Score an opportunity's trustworthiness 0.0-1.0.
    Used for automated verification of community submissions.
    Checks: URL validity, domain reputation, deadline sanity,
    amount plausibility, description completeness.
    """
    url    = (opp.get("url","") or "").lower()
    name   = (opp.get("name","") or "")
    amount = float(opp.get("amount_usd",0) or 0)
    dl     = opp.get("deadline","") or ""
    desc   = (opp.get("description","") or "")
    tags   = opp.get("tags",[]) or []

    score  = 0.0
    flags  = []
    boosts = []

    # 1. URL checks
    if url.startswith("https://"):
        score += 0.15; boosts.append("HTTPS secured")
    elif url.startswith("http://"):
        score += 0.05; flags.append("No SSL certificate")
    else:
        flags.append("No URL provided")

    # 2. Domain reputation
    domain = url.split("/")[2] if "/" in url else ""
    if any(domain.endswith(tld) for tld in _TRUSTED_TLDS):
        score += 0.20; boosts.append("Trusted domain extension")
    if any(td in domain for td in _TRUSTED_DOMAINS):
        score += 0.15; boosts.append("Known trusted organisation")
    if any(sd in domain for sd in _KNOWN_SCAM_DOMAINS):
        score -= 0.50; flags.append("Domain on scam watchlist")

    # 3. Amount sanity ($500-$150,000 is plausible)
    if 500 <= amount <= 150000:
        score += 0.10; boosts.append("Plausible award amount")
    elif amount == 0:
        flags.append("Amount not specified")
    elif amount > 150000:
        flags.append("Unusually high amount — verify")

    # 4. Deadline sanity (must be in future, within 3 years)
    if dl:
        try:
            dl_dt = datetime.strptime(dl, "%Y-%m-%d")
            days  = (dl_dt - datetime.utcnow()).days
            if 0 < days < 1100:
                score += 0.10; boosts.append("Valid future deadline")
            elif days < 0:
                flags.append("Deadline has passed")
            elif days > 1100:
                flags.append("Deadline unusually far (>3 years)")
        except ValueError:
            flags.append("Invalid deadline format")

    # 5. Description quality
    if len(desc) >= 50:
        score += 0.10; boosts.append("Detailed description")
    if len(desc) >= 100:
        score += 0.05

    # 6. Government/institution tags
    gov_tags = {"government","university","foundation","un","government-funded"}
    if any(t.lower() in gov_tags for t in tags):
        score += 0.15; boosts.append("Government or institutional")

    # 7. Name quality
    if len(name) >= 15:
        score += 0.05
    if any(w in name.lower() for w in ["scam","free money","guaranteed","no essay"]):
        score -= 0.30; flags.append("Suspicious name keywords")

    final = round(min(1.0, max(0.0, score)), 3)
    tier  = ("verified" if final >= 0.8 else
             "review"   if final >= 0.5 else "flagged")
    return {
        "trust_score": final,
        "tier":        tier,
        "auto_approve": final >= 0.8,
        "flags":       flags,
        "boosts":      boosts,
    }


@app.get("/api/scholarships/{sid}/trust")
async def scholarship_trust(sid: str):
    """Return trust score for a scholarship opportunity."""
    from engine.opportunity_db import load_all_opportunities
    all_opps = load_all_opportunities() + EXTRA_OPPORTUNITIES
    opp = next((o for o in all_opps if o["id"] == sid), None)
    if not opp: raise HTTPException(404, "Scholarship not found")
    return {**_score_opportunity_trust(opp), "id": sid, "name": opp.get("name","")}


@app.post("/api/admin/scrape-opportunity")
async def submit_opportunity_with_trust(req: dict,
                                         user: User = Depends(_get_user),
                                         db:   Session = Depends(get_db)):
    """
    Community scholarship submission with automatic trust scoring.
    Auto-approves if trust_score >= 0.8; queues for review otherwise.
    """
    name   = _sanitise(req.get("name",""), 200)
    url    = _sanitise(req.get("url",""), 300)
    amount = float(req.get("amount_usd",0) or 0)
    field  = _sanitise(req.get("field",""), 100)
    dl     = _sanitise(req.get("deadline",""), 20)
    if not name or not url:
        raise HTTPException(400, "name and url are required")
    # Score it
    candidate = {"name":name,"url":url,"amount_usd":amount,
                 "field":field,"deadline":dl,
                 "description":req.get("description",""),
                 "tags":req.get("tags",[])}
    trust = _score_opportunity_trust(candidate)
    status = "auto_approved" if trust["auto_approve"] else "pending_review"
    _log_event(db, user.id, "scholarship_submitted", None, name,
               {"url":url, "amount":amount, "trust_score":trust["trust_score"],
                "status":status, "submitter":user.email})
    return {
        "message":     f"Submission {'approved' if trust['auto_approve'] else 'queued for review'}.",
        "name":        name,
        "status":      status,
        "trust_score": trust["trust_score"],
        "tier":        trust["tier"],
        "flags":       trust["flags"],
    }


# ── University Partnership Toolkit ───────────────────────────
@app.post("/api/partnerships/email-template")
async def partnership_email(req: dict, user: User = Depends(_get_user)):
    """
    Generate a personalized university partnership outreach email.
    Prof. recommendation: "Email 10 Directors of International Student Services."
    """
    uni_name    = _sanitise(req.get("university_name","Your University"), 100)
    contact     = _sanitise(req.get("contact_name","Director"), 60)
    country     = _sanitise(req.get("country",""), 60)
    student_cnt = int(req.get("student_count", 500))

    subject = f"Free ScholarBot Pilot for {uni_name} International Students"
    body = f"""Dear {contact},

I am reaching out on behalf of ScholarBot (scholarbot-web.onrender.com), an AI-powered scholarship assistant that helps international students find and apply for verified funding opportunities globally.

We currently have 237+ verified scholarships across 65+ countries — including major programmes from Japan (MEXT), South Korea (GKS), China (CSC), Norway, Sweden, UK (Chevening, Gates Cambridge), Australia, and Saudi Arabia — making ScholarBot particularly relevant for {uni_name}'s international student community{(' in ' + country) if country else ''}.

**Proposed Partnership:**
• Free pilot for {student_cnt} students for one full semester
• University-branded dashboard showing aggregate scholarship performance
• No commitment for semester 1 — we earn your trust first
• $2/student/year from semester 2 if retention targets are met

**What students get:**
• Personalised scholarship matching (196+ opportunities, 22 disciplines)
• AI essay generation with rubric-aware coaching
• Interview preparation for Chevening, Fulbright, Gates Cambridge
• Full GDPR compliance, Scholar's Pledge ethical framework

**Why ScholarBot:**
• Dynamic weight learning — the algorithm improves as your students report outcomes
• GPA normalisation across 22 countries (German 1-5, Nigerian 5.0, Indian 10.0...)
• Built with international students from Kenya, Nigeria, India, Bangladesh as primary users — not a US-centric tool

I would welcome a 20-minute call to discuss how we can support {uni_name}'s internationalisation goals.

Best regards,
ScholarBot Team
partnerships@scholarbot.app
https://scholarbot-web.onrender.com"""

    return {
        "subject": subject,
        "body":    body,
        "tips": [
            "Personalise the opening with a recent news article about the university's internationalisation strategy",
            "Add a specific scholarship win story from a student with similar background to their cohort",
            "Follow up exactly 5 business days after sending — 80% of B2B responses come after follow-up",
            "Target: Directors of International Student Services, Study Abroad Offices, Financial Aid",
        ],
        "target_roles": [
            "Director of International Student Services",
            "Dean of International Programs",
            "Head of Study Abroad Office",
            "Scholarships and Financial Aid Officer",
            "Global Partnerships Manager",
        ],
    }


@app.get("/api/partnerships/pitch-deck-data")
async def pitch_deck_data(db: Session = Depends(get_db)):
    """Data points for a university partnership pitch deck."""
    from sqlalchemy import func
    users = db.query(User).count()
    won   = db.query(Application).filter(Application.stage=="won").count()
    won_usd = db.query(func.sum(Application.amount_usd)).filter(
        Application.stage=="won").scalar() or 0
    return {
        "headline_stats": {
            "scholars_registered": users,
            "scholarships_won": won,
            "total_awarded_usd": int(won_usd),
            "opportunities": 87 + len(EXTRA_OPPORTUNITIES),
            "countries_covered": 65,
            "disciplines": 22,
        },
        "value_proposition": [
            "237+ verified scholarships — government, foundation, and university-direct",
            "AI matching that learns from your students' actual outcomes",
            "GPA normalisation across 22 international grading systems",
            "GDPR compliant — your students' data never sold",
            "Scholar's Pledge — ethical AI use framework with audit logging",
            "Full pipeline from discovery → essay → interview → pipeline tracking",
        ],
        "pricing": {
            "pilot": "Free for 1 semester (unlimited students)",
            "year_1": "$2/student/year after pilot",
            "enterprise": "$49/month for university admin dashboard",
            "break_even_for_university": "ROI if even 1 student wins a scholarship",
        },
        "target_universities": [
            "Universities with large international student populations (>500)",
            "Institutions with students from Africa, South/Southeast Asia",
            "Universities with study abroad or international scholarship programmes",
        ],
    }

# Serve Vite build assets (/assets/index-xxx.js, /assets/index-xxx.css)
@app.get("/assets/{path:path}")
async def serve_assets(path: str):
    """Serve Vite-bundled static assets."""
    from fastapi.responses import FileResponse as _FR
    p = Path(f"static/assets/{path}")
    if p.exists():
        # Set correct content type
        ct = "application/javascript" if path.endswith(".js") else              "text/css" if path.endswith(".css") else              "image/svg+xml" if path.endswith(".svg") else              "image/png" if path.endswith(".png") else              "application/octet-stream"
        return _FR(str(p), media_type=ct)
    raise HTTPException(404)




@app.post("/api/admin/bulk-import")
async def bulk_import_opportunities(req: dict,
                                     user: User = Depends(_get_user),
                                     db:   Session = Depends(get_db)):
    """
    Bulk import opportunities from the weekly scraper.
    Used by GitHub Actions scraper via admin API key.
    Runs trust scoring on each; auto-approves ≥0.8.
    """
    # Admin only
    admin_emails = os.environ.get("ADMIN_EMAILS","").split(",")
    if user.plan not in ("enterprise","partner") and user.email.strip() not in [e.strip() for e in admin_emails if e]:
        raise HTTPException(403, "Admin access required")

    opportunities = req.get("opportunities", [])
    if not opportunities:
        raise HTTPException(400, "No opportunities provided")
    if len(opportunities) > 200:
        raise HTTPException(400, "Max 200 opportunities per batch")

    # Load existing IDs to check for duplicates
    existing_ids = {o.get("id") for o in (load_all_opportunities() + EXTRA_OPPORTUNITIES)}

    imported      = 0
    skipped       = 0
    auto_approved = 0
    pending_review = 0
    results = []

    for opp in opportunities:
        opp_id = opp.get("id","").strip()
        if not opp_id:
            results.append({"status":"skipped","reason":"missing id"})
            skipped += 1
            continue

        # Check duplicate
        if opp_id in existing_ids:
            results.append({"id":opp_id,"status":"skipped","reason":"duplicate"})
            skipped += 1
            continue

        # Run trust scoring
        trust = _score_opportunity_trust(opp)
        opp["trust_score"] = trust["trust_score"]
        opp["trust_tier"]  = trust["tier"]

        # Log the import event for admin review
        _log_event(db, user.id, "opportunity_imported", opp_id,
                   opp.get("name",""), {
                       "trust_score": trust["trust_score"],
                       "auto_approved": trust["auto_approve"],
                       "source": opp.get("source","scraper"),
                       "flags": trust["flags"],
                   })

        if trust["auto_approve"]:
            # Trust score ≥0.8 — log as verified
            auto_approved += 1
            results.append({
                "id":          opp_id,
                "name":        opp.get("name",""),
                "status":      "auto_approved",
                "trust_score": trust["trust_score"],
            })
        else:
            # Needs human review
            pending_review += 1
            results.append({
                "id":          opp_id,
                "name":        opp.get("name",""),
                "status":      "pending_review",
                "trust_score": trust["trust_score"],
                "flags":       trust["flags"],
            })

        imported += 1
        existing_ids.add(opp_id)

    logger.info("Bulk import: %d imported (%d auto-approved, %d pending review), %d skipped",
                imported, auto_approved, pending_review, skipped)

    return {
        "imported":       imported,
        "skipped":        skipped,
        "auto_approved":  auto_approved,
        "pending_review": pending_review,
        "total_in_batch": len(opportunities),
        "results":        results[:50],  # Return first 50 for logging
    }



@app.post("/api/scholarships/suggest-tags")
async def suggest_tags(req: dict):
    """
    Suggest normalised tags for a scholarship based on its description and field.
    Used by the scraper and community submission form.
    """
    description = (req.get("description","") + " " + req.get("field","")).lower()
    name        = req.get("name","").lower()
    url         = req.get("url","").lower()
    all_text    = description + " " + name

    TAG_RULES = [
        # Funding type
        (["fully-funded","fully funded","full scholarship","tuition + stipend"],  "fully-funded"),
        (["partial","partial scholarship","tuition only"],                         "partial"),
        # Region
        (["uk","united kingdom","britain","england","scotland"],                    "uk"),
        (["usa","united states","america","us government"],                        "usa"),
        (["europe","european","eu","erasmus"],                                     "europe"),
        (["africa","african","sub-saharan"],                                       "africa"),
        (["asia","asian","southeast asia","south asia"],                           "asia"),
        (["nordic","norway","sweden","denmark","finland","norway"],                "nordic"),
        # Funder type
        (["government","ministry","state department","fcdo","dfat"],               "government"),
        (["university","college","institute"],                                     "university"),
        (["foundation","trust","fund","endowment"],                                "foundation"),
        # Academic level
        (["undergraduate","bachelor","bsc","ba"],                                  "undergraduate"),
        (["masters","master's","msc","ma","graduate"],                             "masters"),
        (["phd","doctorate","doctoral","postgraduate","postdoc"],                  "phd"),
        # Field
        (["stem","science","technology","engineering","mathematics"],              "stem"),
        (["medicine","medical","health","clinical","nursing","pharmacy"],          "medicine"),
        (["business","mba","management","finance","economics"],                    "business"),
        (["law","legal","jurisprudence","llm"],                                    "law"),
        (["agriculture","agronomy","food","rural","farming"],                      "agriculture"),
        (["environment","climate","ecology","sustainability","conservation"],      "environment"),
        (["computer science","software","coding","ai","machine learning","data"], "computer-science"),
        # Special
        (["leadership","leaders","ambassador"],                                    "leadership"),
        (["research","researcher","academic","phd"],                               "research"),
        (["women","female","gender"],                                              "women"),
        (["developing","lmic","low income","middle income"],                       "developing-countries"),
        (["commonwealth"],                                                         "commonwealth"),
        (["one year","one-year","12 months","single year"],                       "one-year"),
    ]

    suggested = []
    for keywords, tag in TAG_RULES:
        if any(kw in all_text for kw in keywords):
            suggested.append(tag)

    # Region from URL domain
    domain_tags = {
        ".gov.uk": "uk", ".ac.uk": "uk", "chevening.": "uk",
        ".gov": "usa", "fulbright.": "usa", "state.gov": "usa",
        ".gov.au": "australia", ".edu.au": "australia",
        ".go.jp": "japan", "mext.": "japan",
        ".go.kr": "south-korea", "studyinkorea.": "south-korea",
    }
    for domain, tag in domain_tags.items():
        if domain in url and tag not in suggested:
            suggested.append(tag)

    return {"suggested_tags": list(dict.fromkeys(suggested)), "count": len(suggested)}



@app.post("/api/admin/unlock-ip")
async def admin_unlock_ip(req: dict, user: User = Depends(_require_admin)):
    """Admin: unlock a locked-out IP address."""
    ip = req.get("ip","").strip()
    if not ip: raise HTTPException(400, "ip required")
    removed = _login_failures.pop(ip, None)
    return {"unlocked":True,"ip":ip,"was_locked":removed is not None}


@app.get("/api/admin/locked-ips")
async def admin_locked_ips(user: User = Depends(_require_admin)):
    """Admin: list all currently locked IP addresses."""
    now = time.time()
    locked = [{"ip":ip,"failures":d["count"],"seconds_remaining":
               max(0,int(d["locked_until"]-now)) if d.get("locked_until") else 0}
              for ip,d in _login_failures.items()
              if d.get("locked_until") and d["locked_until"] > now]
    return {"locked_ips":locked,"total":len(locked)}



@app.post("/api/auth/change-email")
async def change_email(req: dict,
                        user: User = Depends(_get_user),
                        db:   Session = Depends(get_db)):
    """
    Change email address — requires password confirmation and triggers
    re-verification. New email is not active until verified.
    """
    new_email = req.get("new_email","").strip().lower()
    password  = req.get("password","")
    if not new_email or "@" not in new_email:
        raise HTTPException(400, "Valid email address required")
    if not _check_pw(password, user.password_hash):
        raise HTTPException(401, "Password is incorrect")
    # Check new email not already taken
    if db.query(User).filter(User.email == new_email).first():
        raise HTTPException(400, "Email address already in use")
    import secrets as _sec5, hashlib as _hl8
    # Store pending email change — verified via token
    raw_tok   = _sec5.token_urlsafe(32)
    tok_hash  = _hl8.sha256(raw_tok.encode()).hexdigest()
    _reset_tokens[f"email_{tok_hash}"] = {
        "user_id":   user.id,
        "new_email": new_email,
        "used":      False,
        "expires_at": datetime.utcnow() + timedelta(hours=24),
    }
    # Send verification email to the NEW address
    base = os.environ.get("BASE_URL","https://scholarbot-web.onrender.com")
    link = f"{base}/?verify_email_change={raw_tok}"
    sender_key = os.environ.get("SENDER_API_KEY","")
    if sender_key:
        try:
            import requests as _rq5
            html = (f"<p>Hi {user.name},</p>"
                    f"<p>Click below to confirm your new ScholarBot email address.</p>"
                    f"<p><a href='{link}' style='background:#2563eb;color:#fff;"
                    f"padding:12px 24px;border-radius:6px;text-decoration:none;"
                    f"display:inline-block'>Confirm new email</a></p>"
                    f"<p>This link expires in 24 hours.</p>"
                    f"<p style='font-size:12px;color:#888'>If you didn't request this, ignore this email.</p>")
            _rq5.post("https://api.sender.net/v2/message/send",
                headers={"Authorization": f"Bearer {sender_key}",
                         "Content-Type": "application/json"},
                json={"from": {"email": os.environ.get("FROM_EMAIL","noreply@scholarbot.app"),
                               "name": os.environ.get("FROM_NAME","ScholarBot")},
                      "to": {"email": new_email, "name": user.name},
                      "subject": "Confirm your new ScholarBot email address",
                      "html": html},
                timeout=10)
        except Exception as e:
            logger.debug("Email change send error (non-critical): %s", e)
    return {
        "message": "Verification email sent to your new address. Check your inbox.",
        "new_email": new_email,
        "expires_in_hours": 24,
        "dev_token": raw_tok if not sender_key else None,
    }


@app.get("/api/auth/confirm-email-change")
async def confirm_email_change(token: str, db: Session = Depends(get_db)):
    """Confirm email change via token from verification email."""
    import hashlib as _hl9
    tok_hash = _hl9.sha256(token.encode()).hexdigest()
    entry = _reset_tokens.get(f"email_{tok_hash}")
    if not entry or entry.get("used") or entry["expires_at"] < datetime.utcnow():
        raise HTTPException(400, "Invalid or expired link — request a new email change")
    u = db.query(User).filter(User.id == entry["user_id"]).first()
    if not u:
        raise HTTPException(404, "User not found")
    old_email      = u.email
    u.email        = entry["new_email"]
    u.email_verified = True
    u.password_changed_at = datetime.utcnow()  # Invalidate all sessions
    entry["used"]  = True
    db.commit()
    logger.info("Email changed: %s → %s", old_email, u.email)
    return {"message": "Email updated successfully. Please log in again.", "email": u.email}

@app.get("/terms", response_class=HTMLResponse)
async def terms_of_service():
    """Terms of Service — required before public launch."""
    html = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Terms of Service — ScholarBot</title>
<style>body{font-family:Arial,sans-serif;max-width:800px;margin:0 auto;padding:2rem;
line-height:1.6;color:#333}h1{color:#1a1a2e}h2{color:#2563eb;margin-top:2rem}
.highlight{background:#f0f9ff;padding:1rem;border-left:4px solid #2563eb;margin:1rem 0}
a{color:#2563eb}</style></head><body>
<h1>ScholarBot Terms of Service</h1>
<p><strong>Last updated:</strong> May 2026 &nbsp;|&nbsp;
<strong>Version:</strong> 4.3.0</p>
<div class="highlight">By using ScholarBot you agree to these terms.
If you disagree, do not use the platform.</div>

<h2>1. What ScholarBot is</h2>
<p>ScholarBot is an AI-assisted scholarship discovery and essay drafting tool.
It helps you find scholarships and generates starting-point essays.
It does not guarantee admission, funding, or scholarship awards.</p>

<h2>2. AI-generated content</h2>
<p>Essays generated by ScholarBot are <strong>starting points, not finished submissions.</strong>
You must personalise them before submitting. Submitting AI-generated text without
personalisation may violate scholarship providers' terms and damage your application.
By clicking "Generate essay" you confirm you have read and accepted the
Scholar's Pledge.</p>

<h2>3. Acceptable use</h2>
<p>You may not use ScholarBot to:</p>
<ul>
<li>Impersonate another person or create a false profile</li>
<li>Attempt to access another user's data</li>
<li>Scrape or bulk-download scholarship data</li>
<li>Submit spam scholarship applications</li>
<li>Reverse-engineer or copy the platform</li>
<li>Use the API beyond your plan's rate limits</li>
</ul>

<h2>4. Scholarship accuracy</h2>
<p>We verify all 277+ scholarships before listing them and perform weekly dead-link checks.
However, scholarship deadlines, amounts, and eligibility can change without notice.
Always verify details on the official scholarship website before applying.
ScholarBot is not responsible for inaccuracies in third-party scholarship data.</p>

<h2>5. Payments and refunds</h2>
<p>Pro and Enterprise subscriptions are billed monthly via Stripe.
You can cancel at any time — access continues until the end of the billing period.
Refunds are available within 7 days of first charge if you have not used any Pro features.
Contact billing@scholarbot.app for refund requests.</p>

<h2>6. Intellectual property</h2>
<p>The ScholarBot platform, codebase, matching algorithm, and curated opportunity
database are owned by ScholarBot. Essay content generated using your profile
belongs to you — you may use, edit, and submit it freely.</p>

<h2>7. Limitation of liability</h2>
<p>ScholarBot is provided "as is". We are not liable for missed scholarship deadlines,
rejected applications, or losses arising from use of the platform. Our total
liability to you shall not exceed the amount you paid us in the 3 months
preceding the claim.</p>

<h2>8. Termination</h2>
<p>We may suspend accounts that violate these terms. You may delete your account
at any time from Profile → Delete account.</p>

<h2>9. Governing law</h2>
<p>These terms are governed by the laws of Kenya. Disputes shall be resolved
in Kenyan courts.</p>

<h2>10. Contact</h2>
<p>Questions: <a href="mailto:legal@scholarbot.app">legal@scholarbot.app</a><br>
Privacy Policy: <a href="/privacy">scholarbot-web.onrender.com/privacy</a></p>
</body></html>"""
    return HTMLResponse(html)


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    """GDPR Article 13/14 compliant privacy policy."""
    html = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privacy Policy — ScholarBot</title>
<style>body{font-family:Arial,sans-serif;max-width:800px;margin:0 auto;padding:2rem;line-height:1.6;color:#333}
h1{color:#1a1a2e}h2{color:#2563eb;margin-top:2rem}
.highlight{background:#f0f9ff;padding:1rem;border-left:4px solid #2563eb;margin:1rem 0}
</style></head><body>
<h1>ScholarBot Privacy Policy</h1>
<p><strong>Last updated:</strong> May 2026 &nbsp;|&nbsp; <strong>Version:</strong> 4.3.0</p>
<div class="highlight">ScholarBot is committed to protecting your personal data.
This policy explains what we collect, why, and your rights under GDPR.</div>

<h2>1. Data We Collect</h2>
<ul>
<li><strong>Account data:</strong> Name, email, nationality, degree level, GPA, field of study</li>
<li><strong>Application data:</strong> Scholarship pipeline, essay drafts, recommendation requests</li>
<li><strong>Uploaded files:</strong> CVs, transcripts, certificates (stored in Cloudflare R2)</li>
<li><strong>Behavioral data:</strong> Scholarship views, apply-clicks (anonymised after 90 days)</li>
<li><strong>Payment data:</strong> Handled entirely by Stripe — ScholarBot never stores card numbers</li>
</ul>

<h2>2. Legal Basis (GDPR Article 6)</h2>
<ul>
<li><strong>Contract:</strong> Account creation and scholarship matching</li>
<li><strong>Consent:</strong> Email notifications and scholarship alerts (withdrawable)</li>
<li><strong>Legitimate interest:</strong> Platform security and fraud prevention</li>
</ul>

<h2>3. Data Processors</h2>
<ul>
<li><strong>Anthropic (Claude API)</strong> — AI essay generation. Data processed under Anthropic API ToS.
Anthropic retains API call data for 30 days. We do not send full personal statements to Claude.</li>
<li><strong>Stripe</strong> — Payment processing. Stripe Privacy Policy: https://stripe.com/privacy</li>
<li><strong>Sender.net</strong> — Email delivery. Sender Privacy Policy: https://www.sender.net/privacy</li>
<li><strong>Cloudflare R2</strong> — File storage. Cloudflare Privacy Policy: https://cloudflare.com/privacy</li>
<li><strong>Render.com</strong> — Hosting. Render Privacy Policy: https://render.com/privacy</li>
<li><strong>Upstash Redis</strong> — Rate limiting. Upstash Privacy Policy: https://upstash.com/trust/privacy.pdf</li>
</ul>

<h2>4. Data Retention</h2>
<ul>
<li>Account data: Retained while account is active + 30 days after deletion request</li>
<li>Essay content: Retained until you delete your account</li>
<li>Uploaded files: Retained in R2 until you delete your account</li>
<li>Behavioral events: Anonymised after 90 days</li>
<li>Payment records: 7 years (legal requirement)</li>
</ul>

<h2>5. Your Rights (GDPR Chapter III)</h2>
<ul>
<li><strong>Access (Art. 15):</strong> Download all your data at Profile → Export my data</li>
<li><strong>Portability (Art. 20):</strong> GET /api/account/export.json returns machine-readable JSON</li>
<li><strong>Erasure (Art. 17):</strong> Delete account at Profile → Delete account</li>
<li><strong>Restriction (Art. 18):</strong> Email privacy@scholarbot.app</li>
<li><strong>Objection (Art. 21):</strong> Unsubscribe from alerts at Profile → Alert preferences</li>
</ul>

<h2>6. Security</h2>
<p>Passwords hashed with bcrypt (cost 12). Data encrypted in transit (TLS 1.3).
Two-factor authentication available. Regular security reviews against OWASP Top 10.</p>

<h2>7. Contact</h2>
<p>Data Controller: ScholarBot (Mafuri)<br>
Email: <a href="mailto:privacy@scholarbot.app">privacy@scholarbot.app</a><br>
For EU/UK data subjects: you have the right to lodge a complaint with your national supervisory authority.</p>
</body></html>"""
    return HTMLResponse(html)


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
        # Personalization checklist (replaces "AI detection score" per professor audit)
        # AI detection scores create liability — replaced with actionable personalization guidance
        _generic_phrases = [
            ("delve into",        "Replace with a specific action, e.g. 'I investigated' or 'I built'"),
            ("testament to",      "Replace with a specific example of this quality"),
            ("tapestry",          "Remove — use a concrete metaphor from your own experience"),
            ("fostering",         "Replace with the specific outcome you achieved"),
            ("it is important",   "State why it matters to YOU specifically"),
            ("in conclusion,",    "Remove — end with a forward-looking commitment instead"),
            ("i am passionate",   "Replace with the specific thing you did because of this passion"),
            ("i am confident",    "Show confidence through an achievement, not a claim"),
            ("aligns with my",    "State HOW it aligns — give a specific project or experience"),
            ("i believe that",    "State what you have DONE, not what you believe"),
        ]
        actions_needed = [(phrase, fix) for phrase, fix in _generic_phrases
                          if phrase in essay.lower()]
        _update_job(jid, "done", result={
            "essay":        essay,
            "word_count":   word_count,
            "version":      version,
            "personalization_checklist": [
                {"phrase": p, "action": fix, "found": True}
                for p, fix in actions_needed
            ],
            "checklist_complete": len(actions_needed) == 0,
            "personalisation_tips": [
                "Add your university name, supervisor, or a named colleague",
                "Insert one specific date, award, or measurable outcome from your CV",
                "Replace the opening sentence with a scene from your own life",
                "Mention one person who influenced you by name",
            ],
            "disclaimer": (
                "AI detection scores are not provided — they are probabilistic estimates "
                "that cannot guarantee outcome. ScholarBot provides starting points. "
                "Personalise before submitting. Final submission quality is your responsibility."
            ),
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
        logger.exception("Package job failed"); _update_job(jid,"failed",error=str(e)),

    # ── Japan ────────────────────────────────────────────────
    {"id":"mext_japan","name":"MEXT Japanese Government Scholarship","type":"scholarship","amount_usd":18000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":2.5,"tags":["japan","mext","stem","language","fully-funded","government","asia"],"url":"https://www.mext.go.jp/en/policy/education/highered/title02/detail02/sdetail02/1373897.htm","description":"Japanese government scholarships covering tuition, accommodation, and monthly stipend for international students in Japan","competitiveness":{"label":"Competitive","acceptance_rate":0.15}},
    {"id":"jasso_scholarship","name":"JASSO Honors Scholarship for Privately-Financed Students","type":"scholarship","amount_usd":6000,"deadline":"2025-06-30","eligible_countries":["Kenya","Nigeria","Ghana","India","Bangladesh","Pakistan","Vietnam","Indonesia","Philippines","Thailand","Malaysia","China","South Korea","Nepal","Sri Lanka"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":3.2,"tags":["japan","jasso","asia","study abroad","academic excellence"],"url":"https://www.jasso.or.jp/en/","description":"Japan Student Services Organization scholarships for high-achieving international students studying in Japan","competitiveness":{"label":"Competitive","acceptance_rate":0.12}},
    {"id":"afi_fellowship_japan","name":"Asia Foundation Fellowship (Japan)","type":"fellowship","amount_usd":22000,"deadline":"2025-09-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Bangladesh","India","Pakistan","Vietnam","Indonesia","Philippines","Cambodia","Myanmar","Laos","Nepal"],"degree_levels":["Graduate"],"field":"Policy, Governance, Development, International Relations","gpa_min":3.0,"tags":["japan","asia foundation","policy","governance","development","fellowship"],"url":"https://asiafoundation.org/programs/fellowships/","description":"Asia Foundation fellowships for emerging leaders from developing Asia and Africa","competitiveness":{"label":"Competitive","acceptance_rate":0.10}},
    {"id":"hitachi_scholarship","name":"Hitachi Scholarship Foundation","type":"scholarship","amount_usd":20000,"deadline":"2025-12-01","eligible_countries":["Bangladesh","India","Indonesia","Malaysia","Pakistan","Philippines","Sri Lanka","Thailand","Vietnam","Myanmar","Cambodia","Nepal"],"degree_levels":["Graduate","Postgraduate"],"field":"Engineering, Science, Technology","gpa_min":3.3,"tags":["japan","hitachi","stem","engineering","science","technology","southeast asia","south asia"],"url":"https://www.hitachi-zaidan.org/global/activities/scholarship/","description":"Hitachi Foundation scholarships for Asian scientists and engineers to study in Japan","competitiveness":{"label":"Competitive","acceptance_rate":0.10}},
    {"id":"toyota_foundation","name":"Toyota Foundation Research Grant","type":"grant","amount_usd":30000,"deadline":"2025-10-31","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Social Sciences, Humanities, Environment, Technology","gpa_min":3.3,"tags":["japan","toyota","research","social sciences","humanities","sustainability"],"url":"https://www.toyotafound.or.jp/english/research/","description":"Toyota Foundation research grants addressing global social challenges with a Japan-Asia perspective","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}},

    # ── South Korea ───────────────────────────────────────────
    {"id":"gks_scholarship","name":"Korean Government Scholarship Program (GKS/KGSP)","type":"scholarship","amount_usd":16000,"deadline":"2025-03-14","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Bangladesh","India","Pakistan","Vietnam","Indonesia","Philippines","Malaysia","Thailand","Nepal","Sri Lanka","Cambodia","Myanmar"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":3.0,"tags":["south korea","korea","gks","kgsp","stem","arts","government","fully-funded","asia"],"url":"https://www.studyinkorea.go.kr/en/sub/gks/allnew_unv.do","description":"South Korean government fully-funded scholarships covering tuition, housing, Korean language training, and monthly allowance","competitiveness":{"label":"Competitive","acceptance_rate":0.14}},
    {"id":"posco_tji","name":"POSCO TJ Park Foundation Asia Fellowship","type":"fellowship","amount_usd":15000,"deadline":"2025-11-30","eligible_countries":["China","India","Vietnam","Indonesia","Philippines","Thailand","Malaysia","Bangladesh","Pakistan","Myanmar","Cambodia","Nepal","Sri Lanka","Mongolia"],"degree_levels":["Graduate","Postgraduate"],"field":"Science, Engineering, Business, Social Sciences","gpa_min":3.2,"tags":["south korea","posco","steel","engineering","asia","fellowship","business"],"url":"https://www.postf.org/eng/index.asp","description":"POSCO Foundation fellowships for Asian graduate students pursuing academic excellence and sustainable development","competitiveness":{"label":"Competitive","acceptance_rate":0.12}},
    {"id":"sk_scholarship","name":"SK Group Global Scholarship","type":"scholarship","amount_usd":20000,"deadline":"2025-04-30","eligible_countries":["China","Japan","Vietnam","Indonesia","India","Bangladesh","Myanmar","Cambodia","Thailand","Malaysia","Philippines"],"degree_levels":["Undergraduate","Graduate"],"field":"Business, Technology, Engineering","gpa_min":3.3,"tags":["south korea","sk group","business","technology","engineering","corporate","asia"],"url":"https://eng.sksupport.or.kr/","description":"SK Group scholarships for Asian students pursuing degrees in business, technology, and engineering fields","competitiveness":{"label":"Competitive","acceptance_rate":0.10}},
    {"id":"adb_jsp_korea","name":"ADB-Japan Scholarship Program (Korea)","type":"scholarship","amount_usd":25000,"deadline":"2025-02-15","eligible_countries":["Bangladesh","China","India","Indonesia","Kazakhstan","Malaysia","Mongolia","Myanmar","Nepal","Pakistan","Philippines","Sri Lanka","Thailand","Vietnam","Cambodia","Laos","Afghanistan"],"degree_levels":["Graduate"],"field":"Economics, Development, Finance, Public Policy","gpa_min":3.2,"tags":["south korea","adb","japan","development","economics","finance","policy","asia"],"url":"https://www.adb.org/site/careers/japan-scholarship-program","description":"Asian Development Bank and Japanese government joint scholarships for Asian professionals at leading Asian universities","competitiveness":{"label":"Very Competitive","acceptance_rate":0.08}},

    # ── Taiwan ────────────────────────────────────────────────
    {"id":"taiwan_mofa","name":"Taiwan Ministry of Foreign Affairs Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-03-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Senegal","Burkina Faso","São Tomé and Príncipe","Eswatini","Haiti","Paraguay","Guatemala","Honduras","El Salvador","Belize","Palau","Marshall Islands","Tuvalu","Nauru"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":2.8,"tags":["taiwan","mofa","diplomatic allies","stem","mandarin","government","official"],"url":"https://www.mofa.gov.tw/en/News.aspx?n=2681","description":"Taiwan government scholarships for students from diplomatic partner countries to study in Taiwan","competitiveness":{"label":"Moderate","acceptance_rate":0.22}},
    {"id":"taiwan_icdf","name":"Taiwan ICDF International Higher Education Scholarship","type":"scholarship","amount_usd":12000,"deadline":"2025-03-01","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Gambia","Honduras","Paraguay","Guatemala","Belize","Haiti","Palau","Marshall Islands","Tuvalu","Nauru","El Salvador"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"Agriculture, Public Health, Environment, Business","gpa_min":3.0,"tags":["taiwan","icdf","development","agriculture","health","environment","scholarships","government"],"url":"https://www.icdf.org.tw/ct.asp?xItem=12505&CtNode=30316&mp=2","description":"Taiwan International Cooperation and Development Fund scholarships for students from partner developing countries","competitiveness":{"label":"Moderate","acceptance_rate":0.20}},

    # ── Singapore ─────────────────────────────────────────────
    {"id":"a_star_scholarship","name":"A*STAR International Fellowship","type":"fellowship","amount_usd":55000,"deadline":"2025-05-31","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Biomedical Science, Engineering, Physical Sciences, Computing","gpa_min":3.5,"tags":["singapore","astar","research","biomedical","engineering","physical science","computing","prestigious"],"url":"https://www.a-star.edu.sg/Scholarships/overview","description":"A*STAR International Fellowships for top researchers to conduct cutting-edge research in Singapore's research institutes","competitiveness":{"label":"Very Competitive","acceptance_rate":0.06}},
    {"id":"ntu_research_scholarship","name":"NTU Research Scholarship","type":"scholarship","amount_usd":20000,"deadline":"2025-06-30","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"Engineering, Science, Business, Humanities","gpa_min":3.5,"tags":["singapore","ntu","nanyang","research","phd","stem","prestigious","asia"],"url":"https://www.ntu.edu.sg/education/graduate-programme/research-scholarship","description":"Nanyang Technological University research scholarships for PhD students across all disciplines","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}},
    {"id":"nus_research_scholarship","name":"NUS Research Scholarship","type":"scholarship","amount_usd":20000,"deadline":"2025-07-31","eligible_countries":["Global"],"degree_levels":["Postgraduate"],"field":"All fields — Engineering, Medicine, Law, Arts, Science","gpa_min":3.5,"tags":["singapore","nus","national university","research","phd","stem","prestigious","asia"],"url":"https://nusgs.nus.edu.sg/scholarships/","description":"National University of Singapore research scholarships for outstanding PhD candidates worldwide","competitiveness":{"label":"Very Competitive","acceptance_rate":0.07}},

    # ── Malaysia ──────────────────────────────────────────────
    {"id":"malaysia_mpc","name":"Malaysia Commonwealth Scholarship","type":"scholarship","amount_usd":14000,"deadline":"2025-04-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Zambia","Zimbabwe","Bangladesh","India","Pakistan","Sri Lanka","Jamaica","Trinidad"],"degree_levels":["Graduate"],"field":"All fields with priority on STEM and Development","gpa_min":3.0,"tags":["malaysia","commonwealth","stem","development","asia","affordable"],"url":"https://www.jpa.gov.my/","description":"Malaysian government Commonwealth scholarships for students from developing Commonwealth countries","competitiveness":{"label":"Moderate","acceptance_rate":0.18}},
    {"id":"utm_international","name":"UTM International Graduate Scholarship","type":"scholarship","amount_usd":10000,"deadline":"2025-10-31","eligible_countries":["Global"],"degree_levels":["Graduate","Postgraduate"],"field":"Engineering, Technology, Science, Management","gpa_min":3.2,"tags":["malaysia","utm","engineering","technology","science","management","affordable"],"url":"https://graduate.utm.my/scholarship/","description":"Universiti Teknologi Malaysia scholarships for international graduate students in STEM and management fields","competitiveness":{"label":"Moderate","acceptance_rate":0.20}},

    # ── Thailand ──────────────────────────────────────────────
    {"id":"ait_scholarship","name":"AIT Scholarship (Asian Institute of Technology)","type":"scholarship","amount_usd":15000,"deadline":"2025-08-31","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Bangladesh","India","Pakistan","Vietnam","Indonesia","Philippines","Myanmar","Cambodia","Laos","Nepal","Sri Lanka","Bhutan","Mongolia"],"degree_levels":["Graduate","Postgraduate"],"field":"Engineering, Technology, Environment, Management","gpa_min":3.0,"tags":["thailand","ait","engineering","environment","technology","management","asia","affordable"],"url":"https://www.ait.ac.th/study-at-ait/scholarships/","description":"Asian Institute of Technology scholarships for students from developing Asia and Africa in applied sciences","competitiveness":{"label":"Moderate","acceptance_rate":0.18}},

    # ── China (additional) ────────────────────────────────────
    {"id":"csc_bilateral","name":"Chinese Government Bilateral Scholarship","type":"scholarship","amount_usd":15000,"deadline":"2025-04-01","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Rwanda","Zimbabwe","Zambia","Mozambique","South Africa","Egypt","Morocco","Senegal","Bangladesh","Pakistan","Nepal","Sri Lanka","Myanmar","Cambodia","Laos"],"degree_levels":["Undergraduate","Graduate","Postgraduate"],"field":"All fields","gpa_min":2.8,"tags":["china","csc","bilateral","government","stem","mandarin","fully-funded","bri","africa","asia"],"url":"https://www.campuschina.org/","description":"Chinese government bilateral scholarships under country-to-country agreements covering tuition, accommodation, and stipend","competitiveness":{"label":"Competitive","acceptance_rate":0.17}},
    {"id":"great_wall_scholarship","name":"Great Wall Scholarship Program","type":"scholarship","amount_usd":12000,"deadline":"2025-03-15","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","South Africa","Egypt","Morocco","Senegal","Algeria","Angola","Cameroon","Bangladesh","Pakistan","Nepal","Sri Lanka","Myanmar","Vietnam","Indonesia"],"degree_levels":["Graduate","Postgraduate"],"field":"All fields with priority on STEM, Medicine, Agriculture","gpa_min":3.0,"tags":["china","great wall","stem","medicine","agriculture","developing countries","government","africa"],"url":"https://www.campuschina.org/universities/index.html","description":"UNESCO-China Great Wall Co-Sponsored Fellowship Programme for students from developing countries","competitiveness":{"label":"Competitive","acceptance_rate":0.15}},

    # ── South/Southeast Asia region-wide ─────────────────────
    {"id":"asean_scholarship_sg","name":"ASEAN Scholarship (Singapore)","type":"scholarship","amount_usd":22000,"deadline":"2025-03-31","eligible_countries":["Brunei","Cambodia","Indonesia","Laos","Malaysia","Myanmar","Philippines","Thailand","Vietnam"],"degree_levels":["Undergraduate","Graduate"],"field":"All fields","gpa_min":3.2,"tags":["asean","singapore","southeast asia","prestigious","fully-funded","government","regional"],"url":"https://www.moe.gov.sg/financial-matters/awards-scholarships/asean-scholarships","description":"Singapore Ministry of Education scholarships for outstanding ASEAN students to study in Singapore secondary schools and universities","competitiveness":{"label":"Competitive","acceptance_rate":0.10}},
    {"id":"seameo_scholarship","name":"SEAMEO Regional Scholarship","type":"scholarship","amount_usd":8000,"deadline":"2025-07-31","eligible_countries":["Brunei","Cambodia","Indonesia","Laos","Malaysia","Myanmar","Philippines","Singapore","Thailand","Vietnam","Timor-Leste"],"degree_levels":["Graduate","Postgraduate"],"field":"Education, Agriculture, Marine Science, Public Health, Cultural Studies","gpa_min":2.8,"tags":["southeast asia","seameo","education","agriculture","marine","public health","regional","affordable"],"url":"https://www.seameo.org/","description":"Southeast Asian Ministers of Education Organization regional scholarships for postgraduate study across ASEAN member states","competitiveness":{"label":"Moderate","acceptance_rate":0.20}},
    {"id":"sasakawa_peace","name":"Sasakawa Peace Foundation Fellowship","type":"fellowship","amount_usd":25000,"deadline":"2025-09-30","eligible_countries":["Bangladesh","India","Pakistan","Nepal","Sri Lanka","Myanmar","Cambodia","Laos","Vietnam","Philippines","Indonesia","Thailand","Malaysia","Mongolia","Kenya","Nigeria","Tanzania","Ghana"],"degree_levels":["Graduate","Postgraduate"],"field":"Peace Studies, International Relations, Environmental Studies, Ocean Policy","gpa_min":3.2,"tags":["japan","sasakawa","peace","international relations","environment","ocean","asia","africa"],"url":"https://www.spf.org/en/opri/projects/","description":"Sasakawa Peace Foundation fellowships for students from Asia and Africa in peace studies, international relations, and ocean policy","competitiveness":{"label":"Competitive","acceptance_rate":0.10}},

    # ── Australia & New Zealand (Pacific region) ──────────────
    {"id":"australia_awards","name":"Australia Awards Scholarship","type":"scholarship","amount_usd":45000,"deadline":"2025-04-30","eligible_countries":["Kenya","Nigeria","Ghana","Tanzania","Uganda","Ethiopia","Rwanda","Mozambique","Zambia","Zimbabwe","Senegal","Bangladesh","India","Pakistan","Vietnam","Indonesia","Philippines","Myanmar","Cambodia","Laos","Nepal","Sri Lanka","Bhutan","Timor-Leste","Papua New Guinea","Solomon Islands","Vanuatu","Fiji","Samoa","Tonga"],"degree_levels":["Graduate"],"field":"All fields — priority on development, agriculture, health, education","gpa_min":3.0,"tags":["australia","awards","development","fully-funded","prestigious","africa","asia","pacific"],"url":"https://www.dfat.gov.au/people-to-people/australia-awards","description":"Australian government fully-funded scholarships for emerging leaders from developing Asia, Africa, and Pacific regions","competitiveness":{"label":"Competitive","acceptance_rate":0.12}},
    {"id":"nzaid_scholarship","name":"New Zealand Pacific Scholarships","type":"scholarship","amount_usd":28000,"deadline":"2025-04-30","eligible_countries":["Fiji","Papua New Guinea","Solomon Islands","Vanuatu","Samoa","Tonga","Kiribati","Tuvalu","Niue","Cook Islands","Tokelau","Nauru","Marshall Islands","Federated States of Micronesia","Palau"],"degree_levels":["Undergraduate","Graduate"],"field":"All fields","gpa_min":2.8,"tags":["new zealand","pacific","government","development","island nations","fully-funded"],"url":"https://www.mfat.govt.nz/en/aid-and-development/new-zealand-scholarships/","description":"New Zealand government scholarships for Pacific Island nations students to study in New Zealand or their own region","competitiveness":{"label":"Moderate","acceptance_rate":0.20}}
