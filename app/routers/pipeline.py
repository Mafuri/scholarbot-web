"""
ScholarBot Pipeline router.
During migration, all route handlers delegate to web_app.py.
Phase 2: move handler logic here and remove web_app.py dependency.
"""
from fastapi import APIRouter
import web_app as _wa

router = APIRouter(tags=["Pipeline"])

# Route registrations — handlers still live in web_app.py (migration phase 1)
# To complete the migration, move each handler body into this file.

def _reg():
    """Register all Pipeline routes."""
    pass

# router.add_api_route("/api/pipeline", _wa.???, methods=["GET"])
# router.add_api_route("/api/pipeline/add", _wa.???, methods=["POST"])
# router.add_api_route("/api/pipeline/{app_id}/move", _wa.???, methods=["PATCH"])
# router.add_api_route("/api/pipeline/{app_id}/notes", _wa.???, methods=["PATCH"])
# router.add_api_route("/api/pipeline/export.csv", _wa.???, methods=["GET"])
# router.add_api_route("/api/applications", _wa.???, methods=["GET"])
# router.add_api_route("/api/applications/record", _wa.???, methods=["POST"])
# router.add_api_route("/api/applications/{app_id}/feedback", _wa.???, methods=["POST"])