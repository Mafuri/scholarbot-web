"""Recommendations router — /api/recommendations/*"""
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, User, RecRequest
from app.dependencies import get_current_user
from app.services import jobs as job_service

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


class RecReqCreate(BaseModel):
    opportunity_name: str
    recommender_name: str
    recommender_email: str
    recommender_title: str = ""
    recommender_institution: str = ""
    relationship_desc: str = ""
    deadline: str = ""
    submission_link: str = ""


class RecStatusUpdate(BaseModel):
    status: str


VALID_STATUSES = {"requested", "reminded", "received", "submitted"}


@router.get("")
async def list_recommendations(user: User = Depends(get_current_user),
                                db: Session = Depends(get_db)):
    recs = (db.query(RecRequest)
            .filter(RecRequest.user_id == user.id)
            .order_by(RecRequest.created_at.desc())
            .all())
    return {
        "recommendations": [r.to_dict() for r in recs],
        "total": len(recs),
        "received": sum(1 for r in recs if r.status == "received"),
        "pending": sum(1 for r in recs if r.status != "received"),
    }


@router.post("")
async def create_recommendation(
    req: RecReqCreate,
    bt: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rec = RecRequest(
        id=f"rec_{uuid.uuid4().hex[:8]}",
        user_id=user.id,
        opportunity_name=req.opportunity_name,
        recommender_name=req.recommender_name,
        recommender_email=req.recommender_email,
        recommender_title=req.recommender_title,
        recommender_institution=req.recommender_institution,
        relationship_desc=req.relationship_desc,
        deadline=req.deadline,
        submission_link=req.submission_link,
        status="requested",
    )
    db.add(rec); db.commit(); db.refresh(rec)
    job = job_service.create_job(db, user.id, "rec_letter")
    bt.add_task(
        job_service.run_job,
        job.id,
        job_service.rec_letter_worker,
        rec.id, user.to_dict(), req.dict(),
    )
    return {**rec.to_dict(),
            "message": "Request created. Draft letter being generated."}


@router.patch("/{rid}/status")
async def update_status(
    rid: str,
    upd: RecStatusUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rec = db.query(RecRequest).filter(
        RecRequest.id == rid, RecRequest.user_id == user.id
    ).first()
    if not rec:
        raise HTTPException(404, "Recommendation request not found")
    if upd.status not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status. Valid: {VALID_STATUSES}")
    rec.status = upd.status
    if upd.status == "received":
        rec.received_at = datetime.utcnow()
    rec.updated_at = datetime.utcnow()
    db.commit(); db.refresh(rec)
    return rec.to_dict()
