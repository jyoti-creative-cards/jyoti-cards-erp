"""Minimal in-process login rate limiter / lockout.

Single-instance, in-memory (no Redis dependency). Good enough to stop naive
password-guessing scripts on a single Railway service. If this app ever runs
multiple backend instances behind a load balancer, swap this for a shared
store (Redis/DB-backed) since each process has its own counters.
"""

from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
# key -> (failure_count, first_failure_ts, locked_until_ts)
_STATE: dict[str, tuple[int, float, float]] = {}

MAX_ATTEMPTS = 8
WINDOW_SECONDS = 15 * 60  # count failures within this rolling window
LOCKOUT_SECONDS = 15 * 60  # once tripped, block for this long


def _cleanup(now: float) -> None:
    # Cheap opportunistic sweep so the dict doesn't grow forever.
    if len(_STATE) < 5000:
        return
    stale = [k for k, (_, first, locked_until) in _STATE.items() if max(first + WINDOW_SECONDS, locked_until) < now]
    for k in stale:
        _STATE.pop(k, None)


def seconds_until_unlocked(key: str) -> float:
    """Returns 0 if not locked, else seconds remaining."""
    now = time.time()
    with _LOCK:
        entry = _STATE.get(key)
        if not entry:
            return 0.0
        count, first, locked_until = entry
        if locked_until and locked_until > now:
            return locked_until - now
        return 0.0


def record_failure(key: str) -> None:
    now = time.time()
    with _LOCK:
        _cleanup(now)
        count, first, locked_until = _STATE.get(key, (0, now, 0.0))
        if now - first > WINDOW_SECONDS:
            # window expired — start fresh
            count, first = 0, now
        count += 1
        if count >= MAX_ATTEMPTS:
            locked_until = now + LOCKOUT_SECONDS
        _STATE[key] = (count, first, locked_until)


def record_success(key: str) -> None:
    with _LOCK:
        _STATE.pop(key, None)
