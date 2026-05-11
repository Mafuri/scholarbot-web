"""
ScholarBot web_app.py — Phase 2 entry point.
All logic lives in the app/ package (routers, services, core).
This file is the uvicorn entry point: uvicorn web_app:app
"""
from app.main import app  # noqa: F401
