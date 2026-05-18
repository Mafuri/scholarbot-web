"""
ScholarBot Payments & Plans router.
During migration, all route handlers delegate to web_app.py.
Phase 2: move handler logic here and remove web_app.py dependency.
"""
from fastapi import APIRouter
import web_app as _wa

router = APIRouter(tags=["Payments & Plans"])

# Route registrations — handlers still live in web_app.py (migration phase 1)
# To complete the migration, move each handler body into this file.

def _reg():
    """Register all Payments & Plans routes."""
    pass

# router.add_api_route("/api/plans", _wa.???, methods=["GET"])
# router.add_api_route("/api/my-plan", _wa.???, methods=["GET"])
# router.add_api_route("/api/payments/create-checkout", _wa.???, methods=["POST"])
# router.add_api_route("/api/payments/webhook", _wa.???, methods=["POST"])
# router.add_api_route("/api/stripe/create-checkout", _wa.???, methods=["POST"])
# router.add_api_route("/api/stripe/webhook", _wa.???, methods=["POST"])
# router.add_api_route("/api/stripe/plans", _wa.???, methods=["GET"])