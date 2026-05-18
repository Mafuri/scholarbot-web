"""
ScholarBot Analytics & Dashboard router.
During migration, all route handlers delegate to web_app.py.
Phase 2: move handler logic here and remove web_app.py dependency.
"""
from fastapi import APIRouter
import web_app as _wa

router = APIRouter(tags=["Analytics & Dashboard"])

# Route registrations — handlers still live in web_app.py (migration phase 1)
# To complete the migration, move each handler body into this file.

def _reg():
    """Register all Analytics & Dashboard routes."""
    pass

# router.add_api_route("/api/dashboard", _wa.???, methods=["GET"])
# router.add_api_route("/api/analytics", _wa.???, methods=["GET"])
# router.add_api_route("/api/analytics/apply-clicks", _wa.???, methods=["GET"])
# router.add_api_route("/api/wins", _wa.???, methods=["GET"])
# router.add_api_route("/api/stats", _wa.???, methods=["GET"])
# router.add_api_route("/api/platform-stats", _wa.???, methods=["GET"])
# router.add_api_route("/api/platform/leaderboard", _wa.???, methods=["GET"])
# router.add_api_route("/api/experiments/{name}/results", _wa.???, methods=["GET"])
# router.add_api_route("/api/experiments", _wa.???, methods=["GET"])