"""
ScholarBot Essays & Packages router.
During migration, all route handlers delegate to web_app.py.
Phase 2: move handler logic here and remove web_app.py dependency.
"""
from fastapi import APIRouter
import web_app as _wa

router = APIRouter(tags=["Essays & Packages"])

# Route registrations — handlers still live in web_app.py (migration phase 1)
# To complete the migration, move each handler body into this file.

def _reg():
    """Register all Essays & Packages routes."""
    pass

# router.add_api_route("/api/essays/generate", _wa.???, methods=["POST"])
# router.add_api_route("/api/essays/critique", _wa.???, methods=["POST"])
# router.add_api_route("/api/essays/diff/{uid}/{pid_a}/{pid_b}", _wa.???, methods=["GET"])
# router.add_api_route("/api/essays/usage", _wa.???, methods=["GET"])
# router.add_api_route("/api/packages", _wa.???, methods=["GET"])
# router.add_api_route("/api/packages/prepare", _wa.???, methods=["POST"])
# router.add_api_route("/api/packages/{uid}/{pid}/essay", _wa.???, methods=["GET"])
# router.add_api_route("/api/packages/{uid}/{pid}/briefing", _wa.???, methods=["GET"])
# router.add_api_route("/api/jobs/{jid}", _wa.???, methods=["GET"])
# router.add_api_route("/api/pledge", _wa.???, methods=["POST"])
# router.add_api_route("/api/pledge/status", _wa.???, methods=["GET"])
# router.add_api_route("/api/profile/analyse-statement", _wa.???, methods=["POST"])