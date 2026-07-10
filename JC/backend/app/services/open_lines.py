from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.vendor_open_line import VendorOpenLine


def _get_or_create_open(db: Session, vendor_id: int, catalog_product_id: int) -> VendorOpenLine | None:
    prod = db.get(CatalogProduct, catalog_product_id)
    if not prod:
        return None
    row = (
        db.query(VendorOpenLine)
        .filter(
            VendorOpenLine.vendor_id == vendor_id,
            VendorOpenLine.catalog_product_id == catalog_product_id,
        )
        .first()
    )
    if row:
        if row.status != "open":
            row.status = "open"
        row.buying_price = prod.buying_price
        row.our_product_id = prod.our_product_id
        return row
    row = VendorOpenLine(
        vendor_id=vendor_id,
        catalog_product_id=catalog_product_id,
        our_product_id=prod.our_product_id,
        quantity=0,
        buying_price=prod.buying_price,
        status="open",
    )
    db.add(row)
    db.flush()
    return row


def add_to_open(db: Session, vendor_id: int, lines: list[tuple[int, int]]) -> None:
    for catalog_product_id, qty in lines:
        if qty <= 0:
            continue
        row = _get_or_create_open(db, vendor_id, catalog_product_id)
        if row:
            row.quantity += qty
            row.status = "open"


def reduce_from_open(db: Session, vendor_id: int, lines: list[tuple[int, int]]) -> None:
    for catalog_product_id, qty in lines:
        if qty <= 0:
            continue
        row = (
            db.query(VendorOpenLine)
            .filter(
                VendorOpenLine.vendor_id == vendor_id,
                VendorOpenLine.catalog_product_id == catalog_product_id,
                VendorOpenLine.status == "open",
            )
            .first()
        )
        if not row:
            continue
        row.quantity = max(0, row.quantity - qty)


def close_open_line(db: Session, line_id: int, reason: str | None = None) -> VendorOpenLine:
    row = db.get(VendorOpenLine, line_id)
    if not row:
        raise ValueError("open line not found")
    row.status = "closed"
    if reason:
        row.close_reason = reason.strip()
    return row


def cancel_open_line(db: Session, line_id: int, reason: str | None = None) -> VendorOpenLine:
    row = db.get(VendorOpenLine, line_id)
    if not row:
        raise ValueError("open line not found")
    row.status = "cancelled"
    if reason:
        row.cancel_reason = reason.strip()
    return row


def cancel_open_qty(
    db: Session,
    vendor_id: int,
    lines: list[tuple[int, int]],
    reason: str | None = None,
) -> None:
    for catalog_product_id, qty in lines:
        if qty <= 0:
            continue
        row = (
            db.query(VendorOpenLine)
            .filter(
                VendorOpenLine.vendor_id == vendor_id,
                VendorOpenLine.catalog_product_id == catalog_product_id,
            )
            .first()
        )
        if not row:
            continue
        row.quantity = max(0, row.quantity - qty)
        if reason:
            row.cancel_reason = reason.strip()
        if row.quantity <= 0 and row.status == "open":
            row.status = "cancelled"


def open_lines_for_vendor(db: Session, vendor_id: int, *, status: str = "open") -> list[VendorOpenLine]:
    q = db.query(VendorOpenLine).filter(VendorOpenLine.vendor_id == vendor_id)
    if status:
        q = q.filter(VendorOpenLine.status == status)
    return q.order_by(VendorOpenLine.our_product_id.asc()).all()


def closed_qty_by_product(db: Session, vendor_id: int) -> dict[int, int]:
    rows = (
        db.query(VendorOpenLine)
        .filter(VendorOpenLine.vendor_id == vendor_id, VendorOpenLine.status == "closed")
        .all()
    )
    return {r.catalog_product_id: r.quantity for r in rows if r.quantity > 0}
