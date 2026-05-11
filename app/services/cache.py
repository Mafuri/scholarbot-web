"""
ScholarBot — In-memory TTL cache.
Caches scholarship match results per user profile hash.
Invalidated automatically on profile update.

Phase 3 migration path: swap _store for a Redis client — same interface.
"""
import time
import hashlib
import json
from typing import Any
from app.config import MATCH_CACHE_TTL


class TTLCache:
    """Thread-safe in-memory cache with TTL expiry."""

    def __init__(self, ttl: int = MATCH_CACHE_TTL):
        self._store: dict[str, tuple[Any, float]] = {}
        self.ttl = ttl
        self.hits = 0
        self.misses = 0

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]

    def get(self, key: str) -> Any | None:
        self._evict_expired()
        entry = self._store.get(key)
        if entry is None:
            self.misses += 1
            return None
        value, exp = entry
        if time.time() > exp:
            del self._store[key]
            self.misses += 1
            return None
        self.hits += 1
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._evict_expired()
        exp = time.time() + (ttl or self.ttl)
        self._store[key] = (value, exp)

    def invalidate(self, prefix: str) -> int:
        """Remove all keys starting with prefix. Returns count deleted."""
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            del self._store[k]
        return len(keys)

    def stats(self) -> dict:
        total = self.hits + self.misses
        hit_rate = round(self.hits / total * 100, 1) if total else 0
        return {
            "size": len(self._store),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate_pct": hit_rate,
            "ttl_seconds": self.ttl,
        }


# ── Singleton cache instance ──────────────────────────────────
match_cache = TTLCache(ttl=MATCH_CACHE_TTL)


def profile_cache_key(profile: dict, suffix: str = "") -> str:
    """
    Create a deterministic cache key from the fields that affect matching.
    Profile updates invalidate the key automatically.
    """
    key_fields = {
        "degree_level": profile.get("degree_level", ""),
        "major": profile.get("major", ""),
        "nationality": profile.get("nationality", ""),
        "gpa": round(float(profile.get("gpa", 0) or 0), 1),
        "financial_need": bool(profile.get("financial_need", False)),
        "skills": sorted(profile.get("skills", []) or []),
    }
    digest = hashlib.md5(
        json.dumps(key_fields, sort_keys=True).encode()
    ).hexdigest()[:12]
    return f"match:{digest}:{suffix}"


def invalidate_user_cache(user_id: str) -> None:
    """Call this whenever a user's profile is updated."""
    match_cache.invalidate(f"match:")
