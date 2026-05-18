"""
ScholarBot configuration — all environment variables and constants.
"""
import os

# Database
DB_URL = os.environ.get("DATABASE_URL", "sqlite:///data/scholarbot.db")
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

# Auth
SECRET_KEY      = os.environ.get("SECRET_KEY", "dev-secret-change-me")
JWT_ALGORITHM   = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_DAYS = 7

# Email
SENDER_API_KEY = os.environ.get("SENDER_API_KEY", "")
FROM_EMAIL     = os.environ.get("FROM_EMAIL", "noreply@scholarbot.app")
FROM_NAME      = os.environ.get("FROM_NAME", "ScholarBot")
BASE_URL       = os.environ.get("BASE_URL", "https://scholarbot-web.onrender.com")

# Stripe
STRIPE_SECRET_KEY     = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PRO_PRICE_ID   = os.environ.get("STRIPE_PRO_PRICE_ID", "")
STRIPE_ENT_PRICE_ID   = os.environ.get("STRIPE_ENT_PRICE_ID", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# Cloudflare R2
R2_ACCOUNT_ID  = os.environ.get("CLOUDFLARE_R2_ACCOUNT_ID", "")
R2_ACCESS_KEY  = os.environ.get("CLOUDFLARE_R2_ACCESS_KEY", "")
R2_SECRET_KEY  = os.environ.get("CLOUDFLARE_R2_SECRET_KEY", "")
R2_BUCKET      = os.environ.get("CLOUDFLARE_R2_BUCKET", "")

# Redis
REDIS_URL = os.environ.get("REDIS_URL", "")

# AI
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Admin
ADMIN_EMAILS = [e.strip() for e in
                os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()]
SENTRY_DSN   = os.environ.get("SENTRY_DSN", "")

# Plan limits
PLAN_LIMITS = {
    "free":       {"essays_per_day": 3,   "packages_per_day": 1},
    "pro":        {"essays_per_day": 20,  "packages_per_day": 5},
    "enterprise": {"essays_per_day": -1,  "packages_per_day": -1},
    "partner":    {"essays_per_day": -1,  "packages_per_day": -1},
}
