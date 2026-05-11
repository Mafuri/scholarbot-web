"""
ScholarBot — Centralised configuration
All env vars and constants in one place.
"""
import os
import secrets

# ── Database ──────────────────────────────────────────────────
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", "sqlite:///data/scholarbot.db"
)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ── Auth ──────────────────────────────────────────────────────
SECRET_KEY: str = os.environ.get("SECRET_KEY", secrets.token_hex(32))
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_DAYS: int = 7
COOKIE_NAME: str = "sb_token"

# ── AI ────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL: str = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS: int = 1000

# ── CORS ─────────────────────────────────────────────────────
ALLOWED_ORIGINS: list = [
    "https://scholarbot-web.onrender.com",
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# ── Rate limits (requests, window_seconds) ────────────────────
RATE_LIMITS: dict = {
    "/api/auth/register": (10, 3600),
    "/api/auth/login":    (20, 3600),
    "/api/essays":        (10, 3600),
    "/api/packages":      (5,  3600),
}

# ── Cache TTL (seconds) ───────────────────────────────────────
MATCH_CACHE_TTL: int = 300   # 5 minutes

# ── File upload ───────────────────────────────────────────────
UPLOAD_DIR: str = "data/uploads"
ALLOWED_EXTENSIONS: set = {
    ".pdf", ".docx", ".doc",
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"
}
MAX_FILE_SIZE_MB: int = 10

# ── App metadata ──────────────────────────────────────────────
APP_VERSION: str = "4.1.0"
APP_TITLE: str = "ScholarBot API"
