"""
ScholarBot Admin & Partnerships router.
During migration, all route handlers delegate to web_app.py.
Phase 2: move handler logic here and remove web_app.py dependency.
"""
from fastapi import APIRouter
import web_app as _wa

router = APIRouter(tags=["Admin & Partnerships"])

# Route registrations — handlers still live in web_app.py (migration phase 1)
# To complete the migration, move each handler body into this file.

def _reg():
    """Register all Admin & Partnerships routes."""
    pass

# router.add_api_route("/api/admin/stats", _wa.???, methods=["GET"])
# router.add_api_route("/api/admin/users", _wa.???, methods=["GET"])
# router.add_api_route("/api/admin/users/{uid}/plan", _wa.???, methods=["PATCH"])
# router.add_api_route("/api/admin/validate-listings", _wa.???, methods=["GET"])
# router.add_api_route("/api/admin/scrape-opportunity", _wa.???, methods=["POST"])
# router.add_api_route("/api/account/export", _wa.???, methods=["GET"])
# router.add_api_route("/api/account/export.json", _wa.???, methods=["GET"])
# router.add_api_route("/api/account/delete", _wa.???, methods=["DELETE"])
# router.add_api_route("/api/account/anonymise", _wa.???, methods=["GET"])
# router.add_api_route("/api/institutions", _wa.???, methods=["POST"])
# router.add_api_route("/api/institutions/{domain}/dashboard", _wa.???, methods=["GET"])
# router.add_api_route("/api/institutions", _wa.???, methods=["GET"])
# router.add_api_route("/api/expert-review/my-reviews", _wa.???, methods=["GET"])
# router.add_api_route("/api/expert-review/queue", _wa.???, methods=["GET"])
# router.add_api_route("/api/expert-review/{review_id}/complete", _wa.???, methods=["PATCH"])
# router.add_api_route("/api/expert-review/request", _wa.???, methods=["POST"])
# router.add_api_route("/api/developer/keys", _wa.???, methods=["GET"])
# router.add_api_route("/api/developer/keys", _wa.???, methods=["POST"])
# router.add_api_route("/api/developer/keys/{key_id}", _wa.???, methods=["DELETE"])
# router.add_api_route("/api/developer/docs", _wa.???, methods=["GET"])
# router.add_api_route("/api/alerts/subscribe", _wa.???, methods=["POST"])
# router.add_api_route("/api/alerts/unsubscribe", _wa.???, methods=["DELETE"])
# router.add_api_route("/api/alerts/status", _wa.???, methods=["GET"])
# router.add_api_route("/api/digest/send", _wa.???, methods=["POST"])
# router.add_api_route("/api/digest/preview", _wa.???, methods=["GET"])
# router.add_api_route("/api/partnerships/email-template", _wa.???, methods=["POST"])
# router.add_api_route("/api/partnerships/pitch-deck-data", _wa.???, methods=["GET"])
# router.add_api_route("/api/scholars/peer-match", _wa.???, methods=["GET"])
# router.add_api_route("/api/push/subscribe", _wa.???, methods=["POST"])
# router.add_api_route("/api/push/test", _wa.???, methods=["POST"])
# router.add_api_route("/api/i18n/{locale}", _wa.???, methods=["GET"])
# router.add_api_route("/api/i18n", _wa.???, methods=["GET"])