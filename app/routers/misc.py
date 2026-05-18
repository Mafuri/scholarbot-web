"""
ScholarBot misc router — health, debug, sitemap, robots, service worker.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
import web_app as _wa

router = APIRouter(tags=["System"])

router.add_api_route("/api/health",   _wa.health,   methods=["GET"])
router.add_api_route("/api/debug",    _wa.debug_info, methods=["GET"])
router.add_api_route("/manifest.json", _wa.manifest, methods=["GET"])
router.add_api_route("/sw.js",        _wa.sw,        methods=["GET"])
router.add_api_route("/sitemap.xml",  _wa.sitemap,   methods=["GET"])
router.add_api_route("/robots.txt",   _wa.robots,    methods=["GET"])
router.add_api_route("/api/readiness", _wa.readiness, methods=["GET"])
router.add_api_route("/api/profile",  _wa.update_profile, methods=["PATCH"])
router.add_api_route("/api/profile/upload-doc", _wa.upload_doc, methods=["POST"])
