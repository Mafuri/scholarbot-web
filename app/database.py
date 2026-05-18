"""
ScholarBot database — SQLAlchemy engine, session factory, and all ORM models.
"""
import os
from datetime import datetime
from pathlib import Path
from sqlalchemy import (create_engine, Column, String, Float, Boolean,
    Integer, Text, DateTime, JSON, ForeignKey)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.pool import StaticPool
from app.config import DB_URL

_engine = None
_SessionFactory = None


def get_engine():
    global _engine
    if _engine is None:
        if "sqlite" in DB_URL:
            _engine = create_engine(DB_URL,
                connect_args={"check_same_thread": False}, poolclass=StaticPool)
        else:
            _engine = create_engine(DB_URL, pool_pre_ping=True,
                pool_size=3, max_overflow=5, pool_recycle=300)
    return _engine


def SessionLocal():
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(autocommit=False, autoflush=False,
            bind=get_engine())
    return _SessionFactory()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


Base = declarative_base()


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
