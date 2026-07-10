from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def apply_is_active(row: Any, is_active: bool) -> None:
    """Keep is_active and deleted_at in sync on PATCH."""
    row.is_active = is_active
    if is_active:
        row.deleted_at = None
    else:
        row.deleted_at = datetime.now(timezone.utc)
