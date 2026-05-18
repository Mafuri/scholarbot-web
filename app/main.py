"""
ScholarBot FastAPI application factory.
Imports all routers and configures middleware, startup, and static file serving.
"""
import os
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import BASE_URL, SENTRY_DSN
from app.database import get_engine, Base
from app.routers import auth, scholarships, pipeline, essays
from app.routers import recommendations, analytics, payments, admin, misc

logger = logging.getLogger("scholarbot")
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")

app = FastAPI(
    title="ScholarBot API",
    version="4.3.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ── CORS ──────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[BASE_URL, "http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Security headers middleware ────────────────────────────────
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"]        = "DENY"
    response.headers["X-XSS-Protection"]       = "1; mode=block"
    return response

# ── Routers ───────────────────────────────────────────────────
app.include_router(auth.router,            prefix="/api")
app.include_router(scholarships.router,    prefix="/api")
app.include_router(pipeline.router,        prefix="/api")
app.include_router(essays.router,          prefix="/api")
app.include_router(recommendations.router, prefix="/api")
app.include_router(analytics.router,       prefix="/api")
app.include_router(payments.router,        prefix="/api")
app.include_router(admin.router,           prefix="/api")
app.include_router(misc.router)

# ── Startup ───────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    import asyncio
    Path("data/uploads").mkdir(parents=True, exist_ok=True)
    Path("data/packages").mkdir(parents=True, exist_ok=True)
    Path("static").mkdir(parents=True, exist_ok=True)

    # Sentry
    if SENTRY_DSN:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            sentry_sdk.init(dsn=SENTRY_DSN, integrations=[FastApiIntegration()])
        except ImportError:
            pass

    # Database init
    from app.database import init_db
    init_db()

    # APScheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from app.tasks import send_deadline_reminders
        scheduler = AsyncIOScheduler()
        scheduler.add_job(send_deadline_reminders, "cron", hour=8, minute=0)
        scheduler.start()
        logger.info("APScheduler started")
    except ImportError:
        pass

    # Persistent job worker
    from app.tasks import job_worker
    asyncio.create_task(job_worker())
    logger.info("ScholarBot v4.3.0 started")


# ── Static file serving ───────────────────────────────────────
@app.get("/assets/{path:path}")
async def serve_assets(path: str):
    from fastapi.responses import FileResponse
    p = Path(f"static/assets/{path}")
    if p.exists():
        ct = ("application/javascript" if path.endswith(".js") else
              "text/css"               if path.endswith(".css") else
              "image/svg+xml"          if path.endswith(".svg") else
              "image/png"              if path.endswith(".png") else
              "application/octet-stream")
        return FileResponse(str(p), media_type=ct)
    from fastapi import HTTPException
    raise HTTPException(404)


@app.get("/", response_class=HTMLResponse)
async def spa():
    p = Path("static/index.html")
    if p.exists():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>ScholarBot API v4.3.0</h1>")


@app.get("/{path:path}", response_class=HTMLResponse)
async def spa_fallback(path: str):
    if path.startswith("api/"):
        from fastapi import HTTPException
        raise HTTPException(404)
    p = Path("static/index.html")
    if p.exists():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    from fastapi import HTTPException
    raise HTTPException(404)
