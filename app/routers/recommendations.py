"""
ScholarBot Recommendations & Interview router.
During migration, all route handlers delegate to web_app.py.
Phase 2: move handler logic here and remove web_app.py dependency.
"""
from fastapi import APIRouter
import web_app as _wa

router = APIRouter(tags=["Recommendations & Interview"])

# Route registrations — handlers still live in web_app.py (migration phase 1)
# To complete the migration, move each handler body into this file.

def _reg():
    """Register all Recommendations & Interview routes."""
    pass

# router.add_api_route("/api/recommendations", _wa.???, methods=["GET"])
# router.add_api_route("/api/recommendations", _wa.???, methods=["POST"])
# router.add_api_route("/api/interview/questions/{slug}", _wa.???, methods=["GET"])
# router.add_api_route("/api/interview/score", _wa.???, methods=["POST"])
# router.add_api_route("/api/interview/tips/{scholarship_slug}", _wa.???, methods=["GET"])