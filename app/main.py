"""
ScholarBot — FastAPI application factory (Phase 2 modular architecture).

web_app.py is now a thin entry point: `from app.main import app`
All logic lives in routers/ and services/.
"""
import time
import logging
from collections import defaultdict
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import ALLOWED_ORIGINS, APP_VERSION, APP_TITLE, RATE_LIMITS
from app.database import init_db

# ── Logger ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────
app = FastAPI(title=APP_TITLE, version=APP_VERSION)

# ── CORS — restricted to known origins (Phase 1 T1) ──────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── Rate limiting middleware (Phase 1 T2/T3) ─────────────────
_rate_store: dict = defaultdict(list)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    for prefix, (limit, window) in RATE_LIMITS.items():
        if path.startswith(prefix):
            key = f"{ip}:{prefix}"
            _rate_store[key] = [t for t in _rate_store[key] if now - t < window]
            if len(_rate_store[key]) >= limit:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    {"detail": f"Rate limit: max {limit} requests/hour"},
                    status_code=429,
                )
            _rate_store[key].append(now)
            break
    return await call_next(request)


# ── Routers ───────────────────────────────────────────────────
from app.routers import (
    auth, profile, scholarships, pipeline,
    packages, interview, recommendations, system, account,
)

app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(scholarships.router)
app.include_router(pipeline.router)
app.include_router(packages.router)
app.include_router(interview.router)
app.include_router(recommendations.router)
app.include_router(system.router)
app.include_router(account.router)

# ── Startup ───────────────────────────────────────────────────
@app.middleware("http")
async def security_headers_middleware(request, call_next):
    """Phase 4 T6: Security headers on all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # CSP: allow CDN for React/Babel, own origin for API
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
        "https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'self' https://api.anthropic.com; "
        "img-src 'self' data:; "
        "font-src 'self';"
    )
    return response


@app.on_event("startup")
async def startup():
    Path("data/uploads").mkdir(parents=True, exist_ok=True)
    Path("data/packages").mkdir(parents=True, exist_ok=True)
    Path("static").mkdir(parents=True, exist_ok=True)
    init_db()
    logger.info(
        "ScholarBot %s started — Phase 2 modular architecture active", APP_VERSION
    )
    logger.info(
        "Security: CORS restricted | Rate limiting: ON | "
        "Cache: TTL %ds | SHA256: removed",
        300,
    )

# ── SPA fallback ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def spa():
    p = Path("static/index.html")
    if p.exists():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse(
        f"<h1>ScholarBot API {APP_VERSION}</h1>"
        "<p>Frontend not found in static/index.html</p>"
    )


@app.get("/{path:path}", response_class=HTMLResponse)
async def spa_fallback(path: str):
    if path.startswith("api/"):
        from fastapi import HTTPException
        raise HTTPException(404, "API route not found")
    p = Path("static/index.html")
    if p.exists():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    from fastapi import HTTPException
    raise HTTPException(404)
