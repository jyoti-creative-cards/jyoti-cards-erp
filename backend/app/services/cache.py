"""Simple in-process TTL cache for hot read endpoints.

Uses Redis if REDIS_URL is set; otherwise falls back to a thread-safe in-memory dict.
This is intentionally simple — no cluster support needed for a single-process uvicorn instance.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Optional


class _MemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: int = 60) -> None:
        with self._lock:
            self._store[key] = (value, time.monotonic() + ttl)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear_prefix(self, prefix: str) -> None:
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]


_mem_cache = _MemoryCache()
_redis_client: Any = None

_redis_url = os.environ.get("REDIS_URL", "").strip()
if _redis_url:
    try:
        import redis
        _redis_client = redis.from_url(_redis_url, decode_responses=True, socket_timeout=2)
        _redis_client.ping()
        print("[cache] Redis connected")
    except Exception as e:
        print(f"[cache] Redis unavailable ({e}), using in-memory cache")
        _redis_client = None
else:
    print("[cache] No REDIS_URL set, using in-memory cache")


def cache_get(key: str) -> Optional[Any]:
    if _redis_client:
        try:
            raw = _redis_client.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            pass
    return _mem_cache.get(key)


def cache_set(key: str, value: Any, ttl: int = 60) -> None:
    if _redis_client:
        try:
            _redis_client.setex(key, ttl, json.dumps(value, default=str))
            return
        except Exception:
            pass
    _mem_cache.set(key, value, ttl)


def cache_invalidate(prefix: str) -> None:
    """Bust all cache keys starting with prefix."""
    if _redis_client:
        try:
            for key in _redis_client.scan_iter(f"{prefix}*"):
                _redis_client.delete(key)
            return
        except Exception:
            pass
    _mem_cache.clear_prefix(prefix)


def cached(key: str, ttl: int = 30) -> Callable:
    """Decorator: cache the return value of the function for `ttl` seconds."""
    def decorator(fn: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            hit = cache_get(key)
            if hit is not None:
                return hit
            result = fn(*args, **kwargs)
            cache_set(key, result, ttl)
            return result
        return wrapper
    return decorator
