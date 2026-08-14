from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.stock import StockReceipt, StockReceiptLine
from app.models.vendor_open_line import VendorOpenLine
from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement


def received_qty_by_product(db: Session, vendor_id: int) -> dict[int, int]:
    """Goods received into stock — exclude bill-only receipts (they copy qty for AP lines)."""
    rows = (
        db.query(
            StockReceiptLine.catalog_product_id,
            func.coalesce(func.sum(StockReceiptLine.quantity_received), 0),
        )
        .join(StockReceipt, StockReceiptLine.receipt_id == StockReceipt.id)
        .filter(
            StockReceipt.vendor_id == vendor_id,
            StockReceipt.receipt_type != "vendor_bill",
        )
        .group_by(StockReceiptLine.catalog_product_id)
        .all()
    )
    return {int(cat_id): int(qty or 0) for cat_id, qty in rows}


def placed_qty_by_product(db: Session, vendor_id: int) -> dict[int, int]:
    """Immutable placed record — includes cancelled drops still kept under the placed order."""
    placed = (
        db.query(VendorOrder)
        .filter(
            VendorOrder.vendor_id == vendor_id,
            VendorOrder.bucket == "placed",
            VendorOrder.is_open.is_(True),
        )
        .first()
    )
    if not placed:
        return {}
    rows = (
        db.query(
            VendorOrderLine.catalog_product_id,
            func.coalesce(func.sum(VendorOrderLine.quantity), 0),
        )
        .join(VendorOrderPlacement, VendorOrderLine.placement_id == VendorOrderPlacement.id)
        .filter(VendorOrderPlacement.vendor_order_id == placed.id)
        .group_by(VendorOrderLine.catalog_product_id)
        .all()
    )
    return {int(cat_id): int(qty or 0) for cat_id, qty in rows}


def open_qty_by_product(db: Session, vendor_id: int) -> dict[int, int]:
    """Pending-to-bill qty from open lines (source of truth for Open bucket)."""
    rows = (
        db.query(VendorOpenLine)
        .filter(
            VendorOpenLine.vendor_id == vendor_id,
            VendorOpenLine.status == "open",
            VendorOpenLine.quantity > 0,
        )
        .all()
    )
    return {r.catalog_product_id: int(r.quantity) for r in rows}


def pending_qty_by_product(db: Session, vendor_id: int) -> dict[int, int]:
    """Yet-to-receive quantity — driven by open lines."""
    return open_qty_by_product(db, vendor_id)
