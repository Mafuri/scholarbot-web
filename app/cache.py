"""
ScholarBot in-process cache — simple TTL key-value store.
For multi-worker deployments, replace with Redis-backed cache.
"""
import time

_cache: dict = {}


def cache_get(k: str):
    """Return cached value or None if missing/expired."""
    entry = _cache.get(k)
    if entry is None:
        return None
    value, expires_at = entry
    if time.time() > expires_at:
        del _cache[k]
        return None
    return value


def cache_set(k: str, v, ttl: int = 300):
    """Store value with TTL in seconds (default 5 minutes)."""
    _cache[k] = (v, time.time() + ttl)


def cache_delete(k: str):
    """Remove a key from cache."""
    _cache.pop(k, None)


def cache_clear():
    """Clear all cached entries."""
    _cache.clear()
