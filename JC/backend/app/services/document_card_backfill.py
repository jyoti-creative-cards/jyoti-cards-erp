"""One-shot backfill of card_json on locked documents that predate freeze_card."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.entity_history import EntityHistory
from app.models.stock import StockReceipt, StockReceiptLine
from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement
from app.services.biz_date import as_biz_date
from app.services.document_present import (
    _live_vendor_order_card,
    freeze_card,
)


def _missing_card(row) -> bool:
    """True when card_json is absent. SQL NULL and JSON null both count as missing."""
    return not isinstance(getattr(row, "card_json", None), dict)


def backfill_locked_cards(db: Session) -> int:
    """Set card_json on locked rows that still lack one. Returns how many were filled."""
    filled = 0

    bills = db.query(CustomerBill).filter(CustomerBill.deleted_at.is_(None)).all()
    for bill in bills:
        if not _missing_card(bill):
            continue
        _backfill_customer_bill(db, bill)
        filled += 1

    receipts = (
        db.query(StockReceipt)
        .filter(
            StockReceipt.bill_status == "billed",
            StockReceipt.deleted_at.is_(None),
        )
        .all()
    )
    for receipt in receipts:
        if not _missing_card(receipt):
            continue
        _backfill_vendor_bill(db, receipt)
        filled += 1

    customer_placements = (
        db.query(CustomerOrderPlacement)
        .join(CustomerOrder, CustomerOrder.id == CustomerOrderPlacement.customer_order_id)
        .filter(
            CustomerOrder.bucket == "closed",
            CustomerOrderPlacement.deleted_at.is_(None),
        )
        .all()
    )
    for placement in customer_placements:
        if not _missing_card(placement):
            continue
        _backfill_customer_order(db, placement)
        filled += 1

    vendor_placements = (
        db.query(VendorOrderPlacement)
        .join(VendorOrder, VendorOrder.id == VendorOrderPlacement.vendor_order_id)
        .filter(VendorOrder.bucket == "closed")
        .all()
    )
    for placement in vendor_placements:
        if not _missing_card(placement):
            continue
        _backfill_vendor_order(db, placement)
        filled += 1

    db.flush()
    return filled


def _store_card(row, card: dict) -> None:
    """Assign a fresh dict so SQLAlchemy persists overlays on JSON columns."""
    row.card_json = deepcopy(card)
    flag_modified(row, "card_json")


def _backfill_customer_bill(db: Session, bill: CustomerBill) -> None:
    card = freeze_card(db, "customer_bill", bill)
    lines = (
        db.query(CustomerBillLine)
        .filter(CustomerBillLine.bill_id == bill.id)
        .order_by(CustomerBillLine.id.asc())
        .all()
    )
    _apply_line_precedence(
        db,
        card.get("lines") or [],
        lines,
        business_date=_business_date(bill.bill_date or bill.created_at),
        unit_price_attr="unit_price",
    )
    _store_card(bill, card)


def _backfill_vendor_bill(db: Session, receipt: StockReceipt) -> None:
    card = freeze_card(db, "vendor_bill", receipt)
    lines = (
        db.query(StockReceiptLine)
        .filter(StockReceiptLine.receipt_id == receipt.id)
        .order_by(StockReceiptLine.id.asc())
        .all()
    )
    biz = _business_date(receipt.billed_at or receipt.received_at or receipt.created_at)
    _apply_line_precedence(
        db,
        card.get("lines") or [],
        lines,
        business_date=biz,
        unit_price_attr=None,
    )
    _store_card(receipt, card)


def _backfill_customer_order(db: Session, placement: CustomerOrderPlacement) -> None:
    card = freeze_card(db, "customer_order", placement)
    lines = (
        db.query(CustomerOrderLine)
        .filter(CustomerOrderLine.placement_id == placement.id)
        .order_by(CustomerOrderLine.id.asc())
        .all()
    )
    _apply_line_precedence(
        db,
        card.get("lines") or [],
        lines,
        business_date=_business_date(placement.placed_at),
        unit_price_attr="unit_price",
    )
    _store_card(placement, card)


def _backfill_vendor_order(db: Session, placement: VendorOrderPlacement) -> None:
    # freeze_card does not yet cover vendor_order; snapshot via the live builder once.
    card = _live_vendor_order_card(db, placement)
    lines = (
        db.query(VendorOrderLine)
        .filter(VendorOrderLine.placement_id == placement.id)
        .order_by(VendorOrderLine.id.asc())
        .all()
    )
    _apply_line_precedence(
        db,
        card.get("lines") or [],
        lines,
        business_date=_business_date(placement.placed_at),
        unit_price_attr="buying_price",
        unit_price_card_key="unit_price",
    )
    _store_card(placement, card)


def _apply_line_precedence(
    db: Session,
    card_lines: list[dict],
    db_lines: list,
    *,
    business_date: Optional[date],
    unit_price_attr: Optional[str],
    unit_price_card_key: str = "unit_price",
) -> None:
    """Line columns win; EntityHistory fills images/add-ons; else keep live (from freeze)."""
    for card_line, db_line in zip(card_lines, db_lines):
        card_line["our_product_id"] = db_line.our_product_id
        if unit_price_attr:
            price = getattr(db_line, unit_price_attr, None)
            if price is not None:
                card_line[unit_price_card_key] = _money_str(price)

        pid = int(db_line.catalog_product_id)
        snap = _product_history_at(db, pid, business_date)
        if not snap:
            continue

        if "image_keys" in snap:
            card_line["image_keys"] = list(snap.get("image_keys") or [])

        for field in (
            "vendor_product_id",
            "year_group",
            "category",
            "series",
            "unit",
            "marking",
        ):
            if field in snap:
                card_line[field] = snap.get(field)

        for money_field in ("buying_price", "selling_price"):
            if money_field in snap:
                card_line[money_field] = _money_str(snap.get(money_field))

        # Add-on list is not on the catalog_product snapshot; leave freeze/live addons.


def _product_history_at(
    db: Session, catalog_product_id: int, business_date: Optional[date]
) -> Optional[dict]:
    if business_date is None:
        return None
    rows = (
        db.query(EntityHistory)
        .filter(
            EntityHistory.entity_type == "catalog_product",
            EntityHistory.entity_id == catalog_product_id,
        )
        .order_by(EntityHistory.valid_from.desc(), EntityHistory.id.desc())
        .all()
    )
    for row in rows:
        if _history_covers(row, business_date):
            try:
                data = json.loads(row.snapshot_json)
            except (TypeError, json.JSONDecodeError):
                return None
            return data if isinstance(data, dict) else None
    return None


def _history_covers(row: EntityHistory, business_date: date) -> bool:
    """valid_from <= bill date and (valid_to is null or valid_to > bill date)."""
    vf = as_biz_date(row.valid_from)
    if vf is None or vf > business_date:
        return False
    if row.valid_to is None:
        return True
    vt = as_biz_date(row.valid_to)
    if vt is None:
        return True
    return vt > business_date


def _business_date(value: date | datetime | None) -> Optional[date]:
    return as_biz_date(value)


def _money_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return format(Decimal(str(value)), "f")
