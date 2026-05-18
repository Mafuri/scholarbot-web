"""
ScholarBot Scholarships router.
During migration, all route handlers delegate to web_app.py.
Phase 2: move handler logic here and remove web_app.py dependency.
"""
from fastapi import APIRouter
import web_app as _wa

router = APIRouter(tags=["Scholarships"])

# Route registrations — handlers still live in web_app.py (migration phase 1)
# To complete the migration, move each handler body into this file.

def _reg():
    """Register all Scholarships routes."""
    pass

# router.add_api_route("/api/scholarships", _wa.???, methods=["GET"])
# router.add_api_route("/api/scholarships/matched", _wa.???, methods=["GET"])
# router.add_api_route("/api/scholarships/recommended", _wa.???, methods=["GET"])
# router.add_api_route("/api/scholarships/search", _wa.???, methods=["GET"])
# router.add_api_route("/api/scholarships/{sid}/explain", _wa.???, methods=["GET"])
# router.add_api_route("/api/scholarships/{sid}/predict", _wa.???, methods=["GET"])
# router.add_api_route("/api/scholarships/{sid}/quality", _wa.???, methods=["GET"])
# router.add_api_route("/api/scholarships/{sid}/trust", _wa.???, methods=["GET"])
# router.add_api_route("/api/scholarships/compare", _wa.???, methods=["POST"])
# router.add_api_route("/api/scholarships/share", _wa.???, methods=["POST"])
# router.add_api_route("/api/scholarships/{sid}/bookmark", _wa.???, methods=["POST"])
# router.add_api_route("/api/gpa/detect", _wa.???, methods=["POST"])
# router.add_api_route("/api/opportunities", _wa.???, methods=["GET"])
# router.add_api_route("/api/skills/suggestions", _wa.???, methods=["GET"])
# router.add_api_route("/api/nationalities", _wa.???, methods=["GET"])