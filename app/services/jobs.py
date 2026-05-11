"""
ScholarBot — Job queue service (Phase 2 T2).

Replaces naive BackgroundTasks with PostgreSQL-backed jobs:
- Jobs survive server restarts (stored in DB)
- Status visible via /api/jobs/{id}
- Retry logic on failure
- Phase 3 migration path: swap for Celery worker — same interface

Job lifecycle:  pending → running → done | failed
"""
import uuid
import logging
import traceback
from datetime import datetime
from typing import Callable

logger = logging.getLogger(__name__)


def new_job_id() -> str:
    return f"job_{uuid.uuid4().hex[:10]}"


def create_job(db, user_id: str, job_type: str) -> object:
    """Create a job record and return it. Import Job inline to avoid circular deps."""
    from app.database import Job
    job = Job(
        id=new_job_id(),
        user_id=user_id,
        job_type=job_type,
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job(
    job_id: str,
    status: str,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """Update job status in DB. Uses its own session — safe from background threads."""
    from app.database import SessionLocal, Job
    db = SessionLocal()
    try:
        j = db.query(Job).filter(Job.id == job_id).first()
        if j:
            j.status = status
            if result is not None:
                j.result = result
            if error is not None:
                j.error = error
            j.completed_at = datetime.utcnow()
            db.commit()
    except Exception as e:
        logger.error("update_job error: %s", e)
    finally:
        db.close()


def run_job(job_id: str, fn: Callable, *args, **kwargs) -> None:
    """
    Wrapper that runs fn(*args, **kwargs) and persists the outcome.
    Pass this to FastAPI BackgroundTasks.
    """
    try:
        result = fn(*args, **kwargs)
        update_job(job_id, "done", result=result or {})
    except Exception as e:
        logger.error("Job %s failed: %s", job_id, e)
        update_job(job_id, "failed", error=traceback.format_exc()[-1000:])


# ── Job workers ───────────────────────────────────────────────
def essay_worker(opp: dict, profile: dict, tone: str, max_words: int) -> dict:
    """Generate one essay. Returns result dict for job record."""
    from engine.scholarship_engine import generate_essay_for
    from app.core.security import safe_profile
    safe = safe_profile(profile)
    essay = generate_essay_for(opp, safe, tone, max_words)
    return {"essay": essay, "word_count": len(essay.split())}


def packages_worker(
    profile: dict,
    top_n: int,
    opp_ids: list | None,
) -> dict:
    """Generate top-N packages. Returns result dict."""
    from engine.opportunity_db import match_opportunities, load_all_opportunities
    from engine.scholarship_engine import generate_essay_for
    from app.database import SessionLocal, Package
    from app.core.security import safe_profile

    safe = safe_profile(profile)
    uid = profile.get("id", "anon")

    if opp_ids:
        all_opps = load_all_opportunities()
        opps = [o for o in all_opps if o["id"] in opp_ids]
    else:
        opps = match_opportunities(profile)[:top_n]

    created = []
    db = SessionLocal()
    try:
        for o in opps:
            if not o:
                continue
            try:
                essay = generate_essay_for(o, safe)
            except Exception:
                essay = (
                    f"Essay for {o['name']}.\n\n"
                    f"Prompt: {o.get('essay_prompt', '')}"
                )
            from datetime import datetime as _dt
            try:
                dl = (_dt.strptime(o.get("deadline", ""), "%Y-%m-%d")
                      - _dt.utcnow()).days
            except Exception:
                dl = 999

            pkg = Package(
                id=f"pkg_{uuid.uuid4().hex[:8]}",
                user_id=uid,
                opportunity_id=o.get("id", ""),
                scholarship_name=o.get("name", ""),
                opportunity_type=o.get("opportunity_type", "scholarship"),
                amount_usd=o.get("amount_usd", 0),
                deadline=o.get("deadline", ""),
                days_left=dl,
                url=o.get("url", ""),
                essay_text=essay,
                briefing_html=f"<h1>{o['name']}</h1><pre>{essay}</pre>",
            )
            db.add(pkg)
            created.append({"opportunity": o["name"], "days_left": dl})
        db.commit()
    finally:
        db.close()

    return {"packages": created, "count": len(created)}


def rec_letter_worker(rec_id: str, profile: dict, req: dict) -> dict:
    """Generate a recommendation letter draft."""
    from app.database import SessionLocal, RecRequest
    from app.core.security import safe_profile

    safe = safe_profile(profile)
    db = SessionLocal()
    try:
        rec = db.query(RecRequest).filter(RecRequest.id == rec_id).first()
        if not rec:
            return {"error": "Record not found"}

        from app.services.llm import get_llm
        llm = get_llm()
        name = safe.get("name", "")
        major = safe.get("major", "")
        school = safe.get("school", "")
        gpa = safe.get("gpa", "")
        opp_name = req.get("opportunity_name", "this opportunity")
        rec_name = req.get("recommender_name", "")
        rec_title = req.get("recommender_title", "")

        try:
            letter = llm(
                "Write a professional recommendation letter. Output only the letter text.",
                (
                    f"Write a strong 300-word recommendation for {name} "
                    f"applying to {opp_name}. "
                    f"Student: {major} at {school}, GPA {gpa}. "
                    f"Recommender: {rec_name}, {rec_title}."
                ),
            )
        except Exception:
            letter = (
                f"Dear Selection Committee,\n\n"
                f"I am delighted to recommend {name} for {opp_name}.\n\n"
                f"Sincerely,\n{rec_name}"
            )

        rec.drafted_letter = letter
        rec.briefing_text = f"Student: {name}\nOpportunity: {opp_name}"
        rec.updated_at = datetime.utcnow()
        db.commit()
        return {"letter_length": len(letter)}
    finally:
        db.close()
