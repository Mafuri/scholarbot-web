"""
ScholarBot — Account management router (Phase 4).
GDPR data export, right to be forgotten, account deletion.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, User, Application, Package, RecRequest, Job
from app.dependencies import get_current_user
from app.core.security import verify_password

router = APIRouter(prefix="/api/account", tags=["account"])


class DeleteAccountReq(BaseModel):
    password: str
    confirm: str  # Must equal "DELETE MY ACCOUNT"


@router.get("/export")
async def export_data(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    GDPR Article 20 — Right to data portability.
    Returns all user data as a structured JSON export.
    """
    apps = db.query(Application).filter(Application.user_id == user.id).all()
    pkgs = db.query(Package).filter(Package.user_id == user.id).all()
    recs = db.query(RecRequest).filter(RecRequest.user_id == user.id).all()
    jobs = db.query(Job).filter(Job.user_id == user.id).all()

    export = {
        "export_generated_at": datetime.utcnow().isoformat(),
        "export_format_version": "1.0",
        "platform": "ScholarBot v4.1.0",
        "data_controller": "ScholarBot Platform",
        "profile": user.to_dict(),
        "applications": [a.to_dict() for a in apps],
        "packages": [
            {
                "id": p.id,
                "scholarship_name": p.scholarship_name,
                "amount_usd": p.amount_usd,
                "deadline": p.deadline,
                "essay_text": p.essay_text,
                "essay_version": p.essay_version,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in pkgs
        ],
        "recommendation_requests": [r.to_dict() for r in recs],
        "job_history": [
            {"id": j.id, "job_type": j.job_type, "status": j.status,
             "started_at": j.started_at.isoformat() if j.started_at else None}
            for j in jobs
        ],
        "statistics": {
            "total_applications": len(apps),
            "won": sum(1 for a in apps if a.stage == "won"),
            "total_won_usd": sum(a.amount_usd for a in apps if a.stage == "won"),
            "packages_generated": len(pkgs),
            "account_created": user.created_at.isoformat() if user.created_at else None,
        },
    }

    # Return as downloadable JSON
    filename = f"scholarbot_export_{user.id}_{datetime.utcnow().strftime('%Y%m%d')}.json"
    return JSONResponse(
        content=export,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/json",
        },
    )


@router.delete("/delete")
async def delete_account(
    req: DeleteAccountReq,
    bt: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    GDPR Article 17 — Right to erasure ('right to be forgotten').
    Permanently deletes the account and all associated data.
    Requires password confirmation and explicit consent string.
    """
    # Verify intent
    if req.confirm != "DELETE MY ACCOUNT":
        raise HTTPException(
            400,
            "To confirm deletion, the confirm field must contain exactly: DELETE MY ACCOUNT"
        )

    # Verify password
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "Incorrect password")

    user_id = user.id
    user_email = user.email

    # Delete all related data (cascade handles DB records)
    # Delete uploaded files in background
    bt.add_task(_delete_user_files, user_id)

    # Delete DB records — cascade from user deletion handles the rest
    db.delete(user)
    db.commit()

    return {
        "message": f"Account {user_email} and all associated data have been permanently deleted.",
        "deleted_at": datetime.utcnow().isoformat(),
        "data_removed": [
            "Profile and personal information",
            "Application history",
            "Generated essays and packages",
            "Recommendation letter requests",
            "Job history",
            "Uploaded documents",
        ],
    }


@router.patch("/anonymise")
async def anonymise_account(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Soft anonymisation — keeps anonymised records for analytics
    but removes all personally identifiable information.
    GDPR-compliant alternative to full deletion.
    """
    anon_id = f"anon_{uuid.uuid4().hex[:8]}"
    user.name = f"Anonymised User {anon_id}"
    user.email = f"{anon_id}@deleted.scholarbot.internal"
    user.password_hash = "ANONYMISED"
    user.personal_statement = ""
    user.demographic_tags = []
    user.skills = []
    user.extracurriculars = []
    user.gpa = 0.0
    user.gpa_original = None
    user.school = ""
    user.nationality = ""
    user.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Account anonymised. All PII has been removed.", "anon_id": anon_id}


def _delete_user_files(user_id: str) -> None:
    """Background task to remove uploaded files."""
    import shutil
    upload_dir = Path(f"data/uploads/{user_id}")
    if upload_dir.exists():
        shutil.rmtree(str(upload_dir), ignore_errors=True)
