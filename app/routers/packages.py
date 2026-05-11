"""Packages & Essays router — /api/packages/* and /api/essays/*"""
import uuid
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db, User, Package
from app.dependencies import get_current_user, check_rate_limit
from app.services import jobs as job_service

router = APIRouter(prefix="/api", tags=["packages"])


@router.post("/packages/prepare")
async def prepare_packages(
    request: Request,
    req: dict,
    bt: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else "unknown"
    check_rate_limit(ip, "/api/packages")
    job = job_service.create_job(db, user.id, "packages")
    top_n = int(req.get("top_n", 5))
    bt.add_task(
        job_service.run_job,
        job.id,
        job_service.packages_worker,
        user.to_dict(), top_n, req.get("opportunity_ids"),
    )
    return {"job_id": job.id, "status": "running",
            "message": f"Preparing top {top_n} packages"}


@router.get("/packages")
async def list_packages(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pkgs = (db.query(Package)
            .filter(Package.user_id == user.id)
            .order_by(Package.created_at.desc())
            .all())
    return {"packages": [p.to_dict() for p in pkgs]}


@router.get("/packages/{uid}/{pid}/briefing", response_class=HTMLResponse)
async def get_briefing(
    uid: str, pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.id != uid:
        raise HTTPException(403, "Access denied")
    pkg = db.query(Package).filter(Package.id == pid).first()
    if not pkg:
        raise HTTPException(404, "Package not found")
    return HTMLResponse(pkg.briefing_html or "<p>Briefing not available</p>")


@router.get("/packages/{uid}/{pid}/essay")
async def get_essay(
    uid: str, pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.id != uid:
        raise HTTPException(403, "Access denied")
    pkg = db.query(Package).filter(Package.id == pid).first()
    if not pkg:
        raise HTTPException(404, "Package not found")
    return {"essay": pkg.essay_text or "", "version": pkg.essay_version}


@router.post("/essays/generate")
async def generate_essay(
    request: Request,
    req: dict,
    bt: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else "unknown"
    check_rate_limit(ip, "/api/essays")
    from engine.opportunity_db import load_all_opportunities
    opp = next(
        (o for o in load_all_opportunities()
         if o["id"] == req.get("scholarship_id", "")),
        None
    )
    if not opp:
        raise HTTPException(404, "Opportunity not found")
    job = job_service.create_job(db, user.id, "essay")
    bt.add_task(
        job_service.run_job,
        job.id,
        job_service.essay_worker,
        opp, user.to_dict(),
        req.get("tone", "personal-narrative"),
        int(req.get("max_words", 400)),
    )
    return {"job_id": job.id, "status": "running",
            "message": "Essay generation started"}
