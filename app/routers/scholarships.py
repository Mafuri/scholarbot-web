"""Scholarships router — /api/scholarships/* and /api/opportunities/*"""
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db, User
from app.dependencies import get_current_user, optional_user
from app.services.cache import match_cache, profile_cache_key

router = APIRouter(prefix="/api", tags=["scholarships"])


def _match(profile, opp_type=None, field=None, region=None, min_amount=0):
    from engine.opportunity_db import match_opportunities
    cache_key = profile_cache_key(profile, f"{opp_type}:{field}:{region}:{min_amount}")
    cached = match_cache.get(cache_key)
    if cached is not None:
        return cached
    opps = match_opportunities(profile, opp_type=opp_type, min_amount=min_amount or 0)
    if field:
        opps = [o for o in opps if
                field.lower() in o.get("name", "").lower() or
                field.lower() in " ".join(o.get("tags", [])).lower()]
    if region:
        opps = [o for o in opps if
                any(region.lower() in c.lower()
                    for c in o.get("eligible_countries", []))]
    match_cache.set(cache_key, opps)
    return opps


@router.get("/opportunities")
async def get_opportunities(
    opp_type: Optional[str] = None,
    degree_level: Optional[str] = None,
    field: Optional[str] = None,
    region: Optional[str] = None,
    min_amount: Optional[int] = None,
    user: User = Depends(optional_user),
):
    profile = user.to_dict() if user else {
        "degree_level": degree_level or "Graduate",
        "nationality": "Kenya", "financial_need": False, "gpa": 0, "major": "",
    }
    opps = _match(profile, opp_type=opp_type, field=field,
                  region=region, min_amount=min_amount)
    by_type: dict = {}
    for o in opps:
        by_type.setdefault(o["opportunity_type"], 0)
        by_type[o["opportunity_type"]] += 1
    return {"opportunities": opps, "count": len(opps), "by_type": by_type,
            "total_potential_usd": sum(o["amount_usd"] for o in opps)}


@router.get("/scholarships")
async def get_scholarships(
    degree_level: Optional[str] = None,
    field: Optional[str] = None,
    region: Optional[str] = None,
    min_amount: Optional[int] = None,
    user: User = Depends(optional_user),
):
    profile = user.to_dict() if user else {
        "degree_level": degree_level or "Graduate",
        "nationality": "Kenya", "financial_need": False, "gpa": 0, "major": "",
    }
    opps = _match(profile, opp_type="scholarship",
                  field=field, region=region, min_amount=min_amount)
    return {"scholarships": opps, "count": len(opps),
            "total_potential_usd": sum(o["amount_usd"] for o in opps)}


@router.get("/scholarships/matched")
async def matched_scholarships(user: User = Depends(get_current_user)):
    opps = _match(user.to_dict(), opp_type="scholarship")
    return {"scholarships": opps, "count": len(opps),
            "total_potential_usd": sum(o["amount_usd"] for o in opps)}
