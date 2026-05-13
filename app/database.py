"""
ScholarBot — Database setup and models.
Engine is created lazily on first use to ensure env vars are available
in all worker processes.
"""
import uuid
import os
import logging
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Float, Boolean,
    Integer, Text, DateTime, JSON, ForeignKey, event
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.pool import StaticPool

logger = logging.getLogger(__name__)

Base = declarative_base()
_engine = None
_SessionLocal = None


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "sqlite:///data/scholarbot.db")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def get_engine():
    global _engine
    if _engine is None:
        url = _get_database_url()
        if "sqlite" in url:
            _engine = create_engine(
                url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            _engine = create_engine(
                url,
                pool_pre_ping=True,
                pool_size=3,
                max_overflow=5,
                pool_recycle=300,
                connect_args={"connect_timeout": 10},
            )
        logger.info("Database engine created: %s", url.split("://")[0])
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=get_engine()
        )
    return _SessionLocal


def SessionLocal():
    return get_session_factory()()


# ── Models ────────────────────────────────────────────────────
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

    def to_dict(self, include_password: bool = False) -> dict:
        d = {
            "id": self.id, "name": self.name, "email": self.email,
            "degree_level": self.degree_level, "major": self.major,
            "school": self.school, "nationality": self.nationality,
            "gpa": self.gpa,
            "gpa_original": self.gpa,
            "gpa_scale": 4.0,
            "financial_need": self.financial_need,
            "languages": self.languages or [], "skills": self.skills or [],
            "extracurriculars": self.extracurriculars or [],
            "demographic_tags": self.demographic_tags or [],
            "personal_statement": self.personal_statement or "",
            "email_verified": bool(self.email_verified), "plan": self.plan,
            "applications_this_month": self.applications_this_month or 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_password:
            d["password_hash"] = self.password_hash
        return d


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
    # Phase 3: Feedback loop columns
    essay_used           = Column(Boolean, nullable=True)     # Did they use the AI essay?
    essay_helpfulness    = Column(Integer, nullable=True)     # 1-5 rating
    feedback_text        = Column(Text, nullable=True)        # Open feedback
    feedback_submitted_at = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship("User", back_populates="applications")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "user_id": self.user_id,
            "opportunity_id": self.opportunity_id,
            "scholarship_name": self.scholarship_name,
            "opportunity_type": self.opportunity_type,
            "amount_usd": self.amount_usd, "deadline": self.deadline,
            "url": self.url, "status": self.stage or "researching",
            "notes": self.notes,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "outcome_date": self.outcome_date.isoformat() if self.outcome_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "essay_used": getattr(self, "essay_used", None),
            "essay_helpfulness": getattr(self, "essay_helpfulness", None),
            "feedback_text": getattr(self, "feedback_text", None),
        }


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
    cover_letter     = Column(Text, default="")
    briefing_html    = Column(Text, default="")
    fields_json      = Column(JSON, default=dict)
    essay_version    = Column(Integer, default=1)
    parent_package_id = Column(String(32), nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="packages")

    def to_dict(self) -> dict:
        preview = (self.essay_text or "")[:150] + "..." if self.essay_text else ""
        return {
            "id": self.id, "user_id": self.user_id,
            "opportunity_id": self.opportunity_id,
            "scholarship": self.scholarship_name,
            "amount_usd": self.amount_usd, "deadline": self.deadline,
            "days_left": self.days_left, "url": self.url,
            "essay_preview": preview, "essay_version": self.essay_version,
            "briefing_url": f"/api/packages/{self.user_id}/{self.id}/briefing",
            "essay_url": f"/api/packages/{self.user_id}/{self.id}/essay",
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


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
    briefing_text           = Column(Text, default="")
    status                  = Column(String(30), default="requested")
    requested_at            = Column(DateTime, default=datetime.utcnow)
    reminded_at             = Column(DateTime, nullable=True)
    received_at             = Column(DateTime, nullable=True)
    created_at              = Column(DateTime, default=datetime.utcnow)
    updated_at              = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship("User", back_populates="rec_requests")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "user_id": self.user_id,
            "opportunity_name": self.opportunity_name,
            "recommender_name": self.recommender_name,
            "recommender_email": self.recommender_email,
            "recommender_title": self.recommender_title,
            "recommender_institution": self.recommender_institution,
            "relationship_desc": self.relationship_desc,
            "deadline": self.deadline, "submission_link": self.submission_link,
            "drafted_letter": self.drafted_letter or "",
            "briefing_text": self.briefing_text or "",
            "status": self.status or "requested",
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "reminded_at": self.reminded_at.isoformat() if self.reminded_at else None,
            "received_at": self.received_at.isoformat() if self.received_at else None,
        }


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

    def to_dict(self) -> dict:
        return {
            "id": self.id, "status": self.status,
            "result": self.result, "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# ── Session dependency ────────────────────────────────────────

class PledgeLog(Base):
    """Blocker 5: Audit log proving user agreed to Scholar's Pledge."""
    __tablename__ = "pledge_logs"
    id              = Column(String(32), primary_key=True)
    user_id         = Column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    ip_address      = Column(String(45), default="")
    user_agent      = Column(Text, default="")
    pledge_hash     = Column(String(64), default="")   # SHA-256 of pledge text shown
    created_at      = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id,
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PasswordResetToken(Base):
    """Blocker 1: Password reset tokens — store hash not raw token."""
    __tablename__ = "password_reset_tokens"
    id         = Column(String(32), primary_key=True)
    user_id    = Column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used       = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class EmailVerification(Base):
    """Blocker 3: Email verification tokens."""
    __tablename__ = "email_verifications"
    id         = Column(String(32), primary_key=True)
    user_id    = Column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    verified   = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


def get_db():
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


# ── Init ──────────────────────────────────────────────────────
def init_db():
    os.makedirs("data", exist_ok=True)
    engine = get_engine()
    db_type = _get_database_url().split("://")[0]
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
        logger.info("DB initialised (%s)", db_type)
        print(f"[DB] Initialised ({db_type})")
    except Exception as e:
        logger.error("DB init warning: %s", e)
        for table in Base.metadata.sorted_tables:
            try:
                table.create(engine, checkfirst=True)
            except Exception as te:
                logger.error("Table %s: %s", table.name, te)
    _run_migrations(engine, db_type)


def _run_migrations(engine, db_type: str):
    """Add new columns to existing tables — idempotent, safe on every startup."""
    import sqlalchemy as sa
    if db_type == "sqlite":
        migrations = [
            ("applications", "essay_used", "ALTER TABLE applications ADD COLUMN essay_used BOOLEAN"),
            ("applications", "essay_helpfulness", "ALTER TABLE applications ADD COLUMN essay_helpfulness INTEGER"),
            ("applications", "feedback_text", "ALTER TABLE applications ADD COLUMN feedback_text TEXT"),
            ("applications", "feedback_submitted_at", "ALTER TABLE applications ADD COLUMN feedback_submitted_at DATETIME"),
            ("packages", "essay_version", "ALTER TABLE packages ADD COLUMN essay_version INTEGER DEFAULT 1"),
            ("packages", "parent_package_id", "ALTER TABLE packages ADD COLUMN parent_package_id VARCHAR(32)"),
        ]
        with engine.connect() as conn:
            for table, column, sql in migrations:
                try:
                    result = conn.execute(sa.text(f"PRAGMA table_info({table})"))
                    cols = [row[1] for row in result]
                    if column not in cols:
                        conn.execute(sa.text(sql))
                        conn.commit()
                        logger.info("Migration: added %s.%s", table, column)
                except Exception as e:
                    logger.warning("Migration %s.%s: %s", table, column, e)
    else:
        pg_migrations = [
            "ALTER TABLE applications ADD COLUMN IF NOT EXISTS essay_used BOOLEAN",
            "ALTER TABLE applications ADD COLUMN IF NOT EXISTS essay_helpfulness INTEGER",
            "ALTER TABLE applications ADD COLUMN IF NOT EXISTS feedback_text TEXT",
            "ALTER TABLE applications ADD COLUMN IF NOT EXISTS feedback_submitted_at TIMESTAMP",
            "ALTER TABLE packages ADD COLUMN IF NOT EXISTS essay_version INTEGER DEFAULT 1",
            "ALTER TABLE packages ADD COLUMN IF NOT EXISTS parent_package_id VARCHAR(32)",
        ]
        # Use AUTOCOMMIT isolation — DDL must not run inside a transaction
        raw_conn = engine.raw_connection()
        raw_conn.set_isolation_level(0)  # AUTOCOMMIT
        cursor = raw_conn.cursor()
        for sql in pg_migrations:
            try:
                cursor.execute(sql)
                logger.info("Migration OK: %s", sql[:60])
            except Exception as e:
                logger.warning("Migration skipped (%s): %s", sql[:40], e)
        cursor.close()
        raw_conn.close()
        logger.info("Migrations complete (%s)", db_type)


