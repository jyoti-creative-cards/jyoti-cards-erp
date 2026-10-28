"""Buying-price / cost visibility — hidden from staff by default.

Only admin (owner) and staff explicitly granted the `costs.read` permission can see
our buying price, cost totals, and margins. Everyone else gets a masked placeholder
so existing `fmtPrice()`-style frontend formatters render it as "—" without needing
per-call-site changes.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from app.deps import AuthContext

HIDDEN = "—"

# Matches the "buying_price: <old> → <new>" segment emitted by app.services.history.diff_summary
_BUYING_PRICE_DIFF_RE = re.compile(r"buying_price: [^;]*(?:; |$)")


def can_see_cost(auth: Optional[AuthContext]) -> bool:
    if auth is None:
        return False
    return auth.is_admin or auth.has("costs.read")


def hide_cost(value, auth: Optional[AuthContext]):
    """Mask a formatted price/amount string (or any value) unless the actor can see costs."""
    if value is None:
        return None
    return value if can_see_cost(auth) else HIDDEN


def hide_cost_in_diff_summary(summary: Optional[str], auth: Optional[AuthContext]) -> Optional[str]:
    """Strip the 'buying_price: X → Y' segment out of a history.diff_summary() string.

    diff_summary() embeds raw field values as free text (e.g. "buying_price: 100 → 120; unit: box → dz"),
    so hide_cost() alone can't mask just the price part of a change-history line.
    """
    if not summary or can_see_cost(auth):
        return summary
    cleaned = _BUYING_PRICE_DIFF_RE.sub("", summary).strip("; ").strip()
    return cleaned or "updated"


def hide_cost_in_snapshot_json(snapshot_json: Optional[str], auth: Optional[AuthContext]) -> Optional[str]:
    """Mask the raw `buying_price` value inside a history.row_snapshot() JSON blob."""
    if not snapshot_json or can_see_cost(auth):
        return snapshot_json
    try:
        data = json.loads(snapshot_json)
    except (TypeError, ValueError):
        return snapshot_json
    if isinstance(data, dict) and "buying_price" in data and data["buying_price"] is not None:
        data["buying_price"] = HIDDEN
        return json.dumps(data)
    return snapshot_json
