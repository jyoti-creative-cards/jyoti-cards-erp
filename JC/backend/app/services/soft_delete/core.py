from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def apply_is_active(row: Any, is_active: bool) -> None:
    """Keep is_active and deleted_at in sync on PATCH.

    3-state model (customers):
      active   → is_active=True,  deleted_at=None
      inactive → is_active=False, deleted_at=None   (hidden but not deleted)
      deleted  → is_active=False, deleted_at set    (recycle bin)

    Toggling active→inactive does NOT touch deleted_at.
    Restoring (inactive→active) clears deleted_at.
    Hard delete (DELETE endpoint) sets deleted_at separately.
    """
    row.is_active = is_active
    if is_active:
        row.deleted_at = None
    # inactive: leave deleted_at unchanged (None if never deleted)
