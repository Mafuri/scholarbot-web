"""
ScholarBot Authentication router.
Handles registration, login, logout, email verification,
password reset, 2FA, and session management.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user

router = APIRouter(tags=["Authentication"])

# ── All auth routes delegate to web_app.py during migration ──
# Phase 2 migration: move each handler body into this file

import web_app as _wa

router.add_api_route("/auth/register",          _wa.register,           methods=["POST"])
router.add_api_route("/auth/login",             _wa.login,              methods=["POST"])
router.add_api_route("/auth/me",                _wa.me,                 methods=["GET"])
router.add_api_route("/auth/logout",            _wa.logout,             methods=["POST"])
router.add_api_route("/auth/verify-email",      _wa.verify_email,       methods=["GET"])
router.add_api_route("/auth/resend-verification", _wa.resend_verification, methods=["POST"])
router.add_api_route("/auth/forgot-password",   _wa.forgot_password,    methods=["POST"])
router.add_api_route("/auth/reset-password",    _wa.reset_password,     methods=["POST"])
router.add_api_route("/auth/change-password",   _wa.change_password,    methods=["POST"])
router.add_api_route("/auth/anonymise",         _wa.anonymise_account,  methods=["POST"])
router.add_api_route("/auth/sessions",          _wa.list_sessions,      methods=["GET"])
router.add_api_route("/auth/2fa/setup",         _wa.setup_2fa,          methods=["POST"])
router.add_api_route("/auth/2fa/verify",        _wa.verify_2fa,         methods=["POST"])
router.add_api_route("/auth/2fa/validate",      _wa.validate_2fa,       methods=["POST"])
router.add_api_route("/auth/2fa/disable",       _wa.disable_2fa,        methods=["DELETE"])
