"""Pipeline router — /api/pipeline/*  and /api/applications/*"""
import uuid
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.database import get_db, User, Application
from app.dependencies import get_current_user

router = APIRouter(prefix="/api", tags=["pipeline"])

VALID_STAGES = {"researching","essay_ready","submitted","awaiting","won","rejected"}


@router.get("/pipeline")
async def get_pipeline(user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    apps = db.query(Application).filter(Application.user_id == user.id).all()
    stages = {s: [] for s in VALID_STAGES}
    for a in apps:
        s = a.stage if a.stage in VALID_STAGES else "researching"
        stages[s].append(a.to_dict())
    won_total = sum(a.amount_usd for a in apps if a.stage == "won")
    return {"stages": stages,
            "counts": {k: len(v) for k, v in stages.items()},
            "total": len(apps), "won_total_usd": won_total}


@router.post("/pipeline/add")
async def add_to_pipeline(data: dict,
                           user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    stage = data.get("stage", "researching")
    if stage not in VALID_STAGES:
        stage = "researching"
    a = Application(
        id=f"app_{uuid.uuid4().hex[:8]}",
        user_id=user.id,
        opportunity_id=data.get("scholarship_id", ""),
        scholarship_name=data.get("scholarship_name", ""),
        opportunity_type=data.get("opportunity_type", "scholarship"),
        amount_usd=float(data.get("amount_usd", 0)),
        deadline=data.get("deadline", ""),
        url=data.get("url", ""),
        stage=stage,
        notes=data.get("notes", ""),
    )
    db.add(a); db.commit(); db.refresh(a)
    return a.to_dict()


@router.patch("/pipeline/{app_id}/move")
async def move_stage(app_id: str, data: dict,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    a = db.query(Application).filter(
        Application.id == app_id, Application.user_id == user.id
    ).first()
    if not a:
        raise HTTPException(404, "Application not found")
    new_stage = data.get("stage", a.stage)
    if new_stage not in VALID_STAGES:
        raise HTTPException(400, f"Invalid stage. Valid: {VALID_STAGES}")
    a.stage = new_stage
    if new_stage == "submitted" and not a.submitted_at:
        a.submitted_at = datetime.utcnow()
    a.updated_at = datetime.utcnow()
    db.commit(); db.refresh(a)
    return a.to_dict()


@router.get("/applications")
async def list_applications(user: User = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    apps = db.query(Application).filter(Application.user_id == user.id).all()
    won = [a for a in apps if a.stage == "won"]
    submitted = [a for a in apps if a.stage == "submitted"]
    return {
        "applications": [a.to_dict() for a in apps],
        "total": len(apps), "submitted": len(submitted), "won": len(won),
        "total_applied_usd": sum(a.amount_usd for a in submitted),
        "total_won_usd": sum(a.amount_usd for a in won),
    }


@router.post("/applications/record")
async def record_application(data: dict,
                              user: User = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    a = Application(
        id=f"app_{uuid.uuid4().hex[:8]}",
        user_id=user.id,
        opportunity_id=data.get("scholarship_id", ""),
        scholarship_name=data.get("scholarship_name", ""),
        opportunity_type=data.get("opportunity_type", "scholarship"),
        amount_usd=float(data.get("amount_usd", 0)),
        deadline=data.get("deadline", ""),
        url=data.get("url", ""),
        stage="submitted",
        submitted_at=datetime.utcnow(),
    )
    db.add(a)
    user.applications_this_month = (user.applications_this_month or 0) + 1
    db.commit(); db.refresh(a)
    return a.to_dict()


@router.patch("/applications/{app_id}/outcome")
async def update_outcome(app_id: str, data: dict,
                          user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    a = db.query(Application).filter(
        Application.id == app_id, Application.user_id == user.id
    ).first()
    if not a:
        raise HTTPException(404, "Application not found")
    new_stage = data.get("status", a.stage)
    if new_stage in VALID_STAGES:
        a.stage = new_stage
    a.notes = data.get("notes", a.notes)
    a.outcome_date = datetime.utcnow()
    a.updated_at = datetime.utcnow()
    db.commit(); db.refresh(a)
    return a.to_dict()
