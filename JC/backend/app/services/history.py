from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.entity_history import EntityHistory
from app.models.price_history import PriceHistory

TRACKED_FIELDS = {
    "vendor": ("business_name", "phone", "person_name", "secondary_phone", "alias", "address", "city_id", "gst_number"),
    "customer": (
        "business_name", "phone", "person_name", "secondary_phone", "alias", "address",
        "city_id", "route_id", "gst_number", "credit_limit", "credit_override",
    ),
    "catalog_product": (
        "our_product_id", "vendor_id", "vendor_product_id", "category", "series",
        "unit", "year_group", "buying_price", "selling_price", "image_keys",
    ),
    "addon_product": (
        "our_product_id", "vendor_id", "vendor_product_id", "name", "description",
        "category", "unit", "buying_price", "image_keys",
    ),
}


def _serialize(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
    return obj


def row_snapshot(row: Any, fields: tuple[str, ...]) -> dict:
    out = {}
    for f in fields:
        if hasattr(row, f):
            out[f] = _serialize(getattr(row, f))
    return out


def record_entity_history(
    db: Session,
    entity_type: str,
    entity_id: int,
    snapshot: dict,
    change_summary: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc)
    prev = (
        db.query(EntityHistory)
        .filter(EntityHistory.entity_type == entity_type, EntityHistory.entity_id == entity_id, EntityHistory.valid_to.is_(None))
        .order_by(EntityHistory.id.desc())
        .first()
    )
    if prev:
        prev.valid_to = now
        db.add(prev)
    db.add(EntityHistory(
        entity_type=entity_type,
        entity_id=entity_id,
        snapshot_json=json.dumps(snapshot, default=str),
        change_summary=change_summary,
        valid_from=now,
        valid_to=None,
    ))


def diff_summary(entity_type: str, before: dict, after: dict) -> str:
    fields = TRACKED_FIELDS.get(entity_type, ())
    parts = []
    for f in fields:
        b, a = before.get(f), after.get(f)
        if b != a:
            parts.append(f"{f}: {b} → {a}")
    return "; ".join(parts) if parts else "updated"


def record_price_change(
    db: Session,
    entity_type: str,
    entity_id: int,
    buying_price: Decimal,
    selling_price: Optional[Decimal] = None,
) -> None:
    db.add(PriceHistory(
        entity_type=entity_type,
        entity_id=entity_id,
        buying_price=buying_price,
        selling_price=selling_price,
    ))


def list_entity_history(db: Session, entity_type: str, entity_id: int) -> list[EntityHistory]:
    return (
        db.query(EntityHistory)
        .filter(EntityHistory.entity_type == entity_type, EntityHistory.entity_id == entity_id)
        .order_by(EntityHistory.valid_from.desc())
        .all()
    )


def list_price_history(db: Session, entity_type: str, entity_id: int) -> list[PriceHistory]:
    return (
        db.query(PriceHistory)
        .filter(PriceHistory.entity_type == entity_type, PriceHistory.entity_id == entity_id)
        .order_by(PriceHistory.recorded_at.desc())
        .all()
    )
