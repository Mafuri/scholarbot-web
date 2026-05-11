"""System router — /api/health, /api/stats, /api/dashboard, /api/jobs/*"""
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db, User, Application, Job
from app.dependencies import get_current_user
from app.services.cache import match_cache
from app.config import APP_VERSION

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/manifest.json")
async def manifest():
    """PWA manifest."""
    p = Path("static/manifest.json")
    if p.exists():
        return FileResponse(str(p), media_type="application/manifest+json")
    return JSONResponse({})


@router.get("/sw.js")
async def service_worker():
    """PWA service worker — served from root scope."""
    p = Path("static/sw.js")
    if p.exists():
        return FileResponse(str(p), media_type="application/javascript",
                           headers={"Service-Worker-Allowed": "/"})
    return JSONResponse({})


@router.get("/health")
async def health(db: Session = Depends(get_db)):
    db_error_msg = None
    try:
        user_count = db.query(User).count()
        db_ok = True
    except Exception as e:
        user_count = -1
        db_ok = False
        db_error_msg = str(e)[:200]
    from app.config import DATABASE_URL
    return {
        "status": "ok" if db_ok else "db_error",
        "version": APP_VERSION,
        "users": user_count,
        "db_type": DATABASE_URL.split("://")[0],
        "db_error": db_error_msg,
        "cache": match_cache.stats(),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/stats")
async def stats(db: Session = Depends(get_db)):
    from engine.opportunity_db import load_all_opportunities
    opps = load_all_opportunities()
    by_type: dict = {}
    for o in opps:
        by_type.setdefault(o["opportunity_type"], 0)
        by_type[o["opportunity_type"]] += 1
    return {
        "total_users": db.query(User).count(),
        "opportunities_in_db": len(opps),
        "total_potential_funding_usd": sum(o["amount_usd"] for o in opps),
        "by_type": by_type,
        "degree_levels": ["Undergraduate", "Graduate", "Postgraduate"],
        "cache": match_cache.stats(),
    }


@router.get("/dashboard")
async def dashboard(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from engine.opportunity_db import match_opportunities
    from app.services.cache import profile_cache_key

    cache_key = profile_cache_key(user.to_dict(), "dashboard")
    cached = match_cache.get(cache_key)
    if cached is None:
        cached = match_opportunities(user.to_dict())
        match_cache.set(cache_key, cached)

    matched = cached
    apps = db.query(Application).filter(Application.user_id == user.id).all()
    won = [a for a in apps if a.stage == "won"]
    submitted = [a for a in apps if a.stage == "submitted"]

    upcoming = []
    for o in matched:
        try:
            days = (datetime.strptime(o.get("deadline", ""), "%Y-%m-%d")
                    - datetime.utcnow()).days
        except Exception:
            continue
        if 0 <= days <= 60:
            upcoming.append({
                "name": o["name"], "deadline": o["deadline"],
                "amount_usd": o.get("amount_usd", 0), "days_left": days,
                "opportunity_type": o.get("opportunity_type", "scholarship"),
            })
    upcoming.sort(key=lambda x: x["days_left"])

    return {
        "user": user.to_dict(),
        "scholarships_matched": len(matched),
        "total_potential_usd": sum(o["amount_usd"] for o in matched),
        "applications_submitted": len(submitted),
        "applications_won": len(won),
        "total_won_usd": sum(a.amount_usd for a in won),
        "upcoming_deadlines": upcoming[:5],
    }


@router.get("/validate-listings")
async def validate_listings(user: User = Depends(get_current_user)):
    """Phase 4 T4: Run fraud detection on all scholarship listings."""
    from app.services.fraud_detection import validate_all_opportunities
    return validate_all_opportunities()


@router.get("/jobs/{jid}")
async def get_job(jid: str,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    j = db.query(Job).filter(Job.id == jid, Job.user_id == user.id).first()
    if not j:
        raise HTTPException(404, "Job not found")
    return j.to_dict()
