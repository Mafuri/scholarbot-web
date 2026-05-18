"""
ScholarBot background tasks — essay generation, package preparation,
deadline reminders, and persistent job worker.
"""
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger("scholarbot.tasks")


async def job_worker():
    """
    Persistent job queue — polls the database every 5 seconds.
    Runs essay and package generation jobs. Survives worker restarts.
    """
    from app.database import SessionLocal
    from app.database import Job
    logger.info("Job worker started — polling every 5s")
    while True:
        try:
            db = SessionLocal()
            pending = db.query(Job).filter(
                Job.status == "pending",
                Job.retry_count < 3,
            ).limit(3).all()
            db.close()
            for job in pending:
                db2 = SessionLocal()
                try:
                    j = db2.query(Job).filter(Job.id == job.id).first()
                    if j:
                        j.status = "running"
                        db2.commit()
                finally:
                    db2.close()
                if job.job_type == "essay":
                    meta = job.result or {}
                    if meta.get("opp") and meta.get("profile"):
                        essay_job(job.id, meta["opp"], meta["profile"])
                elif job.job_type == "packages":
                    meta = job.result or {}
                    if meta.get("profile"):
                        packages_job(job.id, meta["profile"], meta.get("top_n", 5))
        except Exception as e:
            logger.debug("Job worker tick error (non-critical): %s", e)
        await asyncio.sleep(5)


def update_job(jid: str, status: str, result=None, error=None):
    """Update job status in database."""
    from app.database import SessionLocal, Job
    db = SessionLocal()
    try:
        j = db.query(Job).filter(Job.id == jid).first()
        if j:
            j.status = status
            j.updated_at = datetime.utcnow()
            if result is not None:
                j.result = result
            if error is not None:
                j.error = error
            db.commit()
    finally:
        db.close()


def essay_job(jid: str, opp: dict, profile: dict):
    """Generate a single essay in background."""
    # Full implementation lives in web_app.py _essay_job
    # This stub delegates to the legacy implementation during migration
    try:
        import web_app as _wa
        _wa._essay_job(jid, opp, profile)
    except Exception as e:
        update_job(jid, "failed", error=str(e)[:500])


def packages_job(jid: str, profile: dict, top_n: int = 5):
    """Generate top-N essay packages in background."""
    try:
        import web_app as _wa
        _wa._packages_job(jid, profile, top_n)
    except Exception as e:
        update_job(jid, "failed", error=str(e)[:500])


async def send_deadline_reminders():
    """Send daily 08:00 deadline reminder emails."""
    try:
        import web_app as _wa
        await _wa._send_reminders()
    except Exception as e:
        logger.error("Deadline reminders error: %s", e)
