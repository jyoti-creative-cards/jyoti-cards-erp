"""Inventory lookup via Dashboard DB."""
from __future__ import annotations

from typing import Any, Optional

from dash_db import get_dashboard_db


def search(sku_query: str) -> Optional[dict[str, Any]]:
    db = get_dashboard_db()
    db.init_db()
    return db.lookup_product_availability(sku_query)


def image_abs_path(image_rel: str | None) -> str | None:
    if not image_rel:
        return None
    return get_dashboard_db().product_image_src(image_rel)
