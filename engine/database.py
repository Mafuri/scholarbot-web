"""
database.py — Production persistence layer
PostgreSQL in production, SQLite locally.
"""
from __future__ import annotations
import os, uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import (create_engine, Column, String, Float, Boolean,
    Integer, Text, DateTime, JSON, ForeignKey, Enum)
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


class ApplicationStage(str, PyEnum):
    researching = "researching"
    essay_ready = "essay_ready"
    submitted   = "submitted"
    awaiting    = "awaiting"
    won         = "won"
    rejected    = "rejected"


class RecStatus(str, PyEnum):
    requested = "requested"
    reminded  = "reminded"
    received  = "received"
    submitted = "submitted"


class User(Base):
    __tablename__ = "users"
    id                   = Column(String(32), primary_key=True, default=lambda: f"user_{uuid.uuid4().hex[:10]}")
    name                 = Column(String(200), nullable=False)
    email                = Column(String(200), unique=True, nullable=False, index=True)
    password_hash        = Column(String(200), nullable=False)
    degree_level         = Column(String(50), default="Graduate")
    major                = Column(String(200), default="")
    school               = Column(String(200), default="")
    nationality          = Column(String(100), default="Kenya")
    gpa                  = Column(Float, default=0.0)
    financial_need       = Column(Boolean, default=False)
    languages            = Column(JSON, default=list)
    skills               = Column(JSON, default=list)
    extracurriculars     = Column(JSON, default=list)
    demographic_tags     = Column(JSON, default=list)
    personal_statement   = Column(Text, default="")
    plan                 = Column(String(20), default="free")
    applications_this_month = Column(Integer, default=0)
    created_at           = Column(DateTime, default=datetime.utcnow)
    updated_at           = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    applications         = relationship("Application", back_populates="user", cascade="all, delete-orphan")
    packages             = relationship("Package", back_populates="user", cascade="all, delete-orphan")
    rec_requests         = relationship("RecRequest", back_populates="user", cascade="all, delete-orphan")

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
    id               = Column(String(32), primary_key=True, default=lambda: f"app_{uuid.uuid4().hex[:8]}")
    user_id          = Column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    opportunity_id   = Column(String(32), default="")
    scholarship_name = Column(String(300), default="")
    opportunity_type = Column(String(50), default="scholarship")
    amount_usd       = Column(Float, default=0.0)
    deadline         = Column(String(20), default="")
    url              = Column(Text, default="")
    stage            = Column(Enum(ApplicationStage), default=ApplicationStage.researching)
    notes            = Column(Text, default="")
    submitted_at     = Column(DateTime, nullable=True)
    outcome_date     = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user             = relationship("User", back_populates="applications")

    def to_dict(self):
        return {"id":self.id,"user_id":self.user_id,
                "opportunity_id":self.opportunity_id,
                "scholarship_name":self.scholarship_name,
                "opportunity_type":self.opportunity_type,
                "amount_usd":self.amount_usd,"deadline":self.deadline,
                "url":self.url,
                "status":self.stage.value if self.stage else "researching",
                "notes":self.notes,
                "submitted_at":self.submitted_at.isoformat() if self.submitted_at else None,
                "outcome_date":self.outcome_date.isoformat() if self.outcome_date else None,
                "created_at":self.created_at.isoformat() if self.created_at else None,
                "updated_at":self.updated_at.isoformat() if self.updated_at else None}


class Package(Base):
    __tablename__ = "packages"
    id               = Column(String(32), primary_key=True, default=lambda: f"pkg_{uuid.uuid4().hex[:8]}")
    user_id          = Column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    opportunity_id   = Column(String(32), default="")
    scholarship_name = Column(String(300), default="")
    amount_usd       = Column(Float, default=0.0)
    deadline         = Column(String(20), default="")
    days_left        = Column(Integer, default=0)
    url              = Column(Text, default="")
    essay_text       = Column(Text, default="")
    cover_letter     = Column(Text, default="")
    briefing_html    = Column(Text, default="")
    fields_json      = Column(JSON, default=dict)
    created_at       = Column(DateTime, default=datetime.utcnow)
    user             = relationship("User", back_populates="packages")

    def to_dict(self):
        preview = (self.essay_text or "")[:150] + "..." if self.essay_text else ""
        return {"id":self.id,"user_id":self.user_id,
                "opportunity_id":self.opportunity_id,
                "scholarship":self.scholarship_name,
                "amount_usd":self.amount_usd,"deadline":self.deadline,
                "days_left":self.days_left,"url":self.url,
                "essay_preview":preview,
                "briefing_url":f"/api/packages/{self.user_id}/{self.id}/briefing",
                "essay_url":f"/api/packages/{self.user_id}/{self.id}/essay",
                "created_at":self.created_at.isoformat() if self.created_at else None}


class RecRequest(Base):
    __tablename__ = "rec_requests"
    id                      = Column(String(32), primary_key=True, default=lambda: f"rec_{uuid.uuid4().hex[:8]}")
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
    briefing_text           = Column(Text, default="")
    status                  = Column(Enum(RecStatus), default=RecStatus.requested)
    requested_at            = Column(DateTime, default=datetime.utcnow)
    reminded_at             = Column(DateTime, nullable=True)
    received_at             = Column(DateTime, nullable=True)
    created_at              = Column(DateTime, default=datetime.utcnow)
    updated_at              = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user                    = relationship("User", back_populates="rec_requests")

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
                "status":self.status.value if self.status else "requested",
                "requested_at":self.requested_at.isoformat() if self.requested_at else None,
                "reminded_at":self.reminded_at.isoformat() if self.reminded_at else None,
                "received_at":self.received_at.isoformat() if self.received_at else None}


class Job(Base):
    __tablename__ = "jobs"
    id           = Column(String(32), primary_key=True, default=lambda: f"job_{uuid.uuid4().hex[:8]}")
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
    try:
        yield db
    finally:
        db.close()


def init_db():
    import os; os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    print(f"[DB] Initialised ({DATABASE_URL.split('://')[0]})")
