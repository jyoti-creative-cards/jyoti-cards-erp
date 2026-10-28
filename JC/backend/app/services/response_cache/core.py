"""Tiny in-process TTL cache for hot GET lists (stock/catalog/etc)."""
from __future__ import annotations

import time
from threading import Lock
from typing import Any, Optional

_lock = Lock()
_store: dict[str, tuple[float, Any]] = {}


def get(key: str) -> Optional[Any]:
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if not hit:
            return None
        expires, value = hit
        if now > expires:
            _store.pop(key, None)
            return None
        return value


def set(key: str, value: Any, ttl_seconds: float = 20.0) -> None:
    with _lock:
        _store[key] = (time.monotonic() + ttl_seconds, value)


def invalidate(prefix: str = "") -> None:
    with _lock:
        if not prefix:
            _store.clear()
            return
        for k in [k for k in _store if k.startswith(prefix)]:
            _store.pop(k, None)
