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


def reserved_by_party(db: Session, catalog_product_id: int) -> list[dict]:
    """Per-customer breakdown of stock currently held for a product — the "who reserved
    how much" view the stock ledger screen was missing. Three buckets per customer:

    - unconfirmed: still sitting in "New" (received, not yet confirmed) — stock is
      already deducted (reserve_stock runs at order time), but the order isn't final.
    - to_bill: confirmed (CustomerOpenLine.quantity_open) — committed, awaiting billing.
    - billed_not_dispatched: billed (CustomerOpenLine.quantity_billed) — invoiced but the
      bill line hasn't been closed/dispatched yet.

    Only customers with > 0 total held are returned. This does not include vendor-side
    "Pending order" (inbound goods not yet received) — that is a different number,
    already shown separately.
    """
    from app.models.customer import Customer
    from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderLine, CustomerOrderPlacement

    result: dict[int, dict] = {}

    def _row(customer_id: int) -> dict:
        return result.setdefault(
            customer_id,
            {"customer_id": customer_id, "unconfirmed": 0, "to_bill": 0, "billed_not_dispatched": 0},
        )

    unconfirmed_rows = (
        db.query(CustomerOrder.customer_id, CustomerOrderLine.quantity, CustomerOrderLine.quantity_billed)
        .join(CustomerOrderPlacement, CustomerOrderLine.placement_id == CustomerOrderPlacement.id)
        .join(CustomerOrder, CustomerOrderPlacement.customer_order_id == CustomerOrder.id)
        .filter(
            CustomerOrder.bucket == "received",
            CustomerOrder.is_open.is_(True),
            CustomerOrderLine.catalog_product_id == catalog_product_id,
            CustomerOrderLine.status == "active",
        )
        .all()
    )
    for customer_id, qty, billed in unconfirmed_rows:
        unbilled = int(qty or 0) - int(billed or 0)
        if unbilled > 0:
            _row(customer_id)["unconfirmed"] += unbilled

    open_rows = (
        db.query(CustomerOpenLine.customer_id, CustomerOpenLine.quantity_open, CustomerOpenLine.quantity_billed)
        .filter(CustomerOpenLine.catalog_product_id == catalog_product_id)
        .all()
    )
    for customer_id, qty_open, qty_billed in open_rows:
        qty_open = int(qty_open or 0)
        qty_billed = int(qty_billed or 0)
        if qty_open <= 0 and qty_billed <= 0:
            continue
        row = _row(customer_id)
        row["to_bill"] += qty_open
        row["billed_not_dispatched"] += qty_billed

    if not result:
        return []

    names = {
        c.id: c.business_name
        for c in db.query(Customer.id, Customer.business_name).filter(Customer.id.in_(result.keys())).all()
    }
    out = []
    for customer_id, row in result.items():
        total = row["unconfirmed"] + row["to_bill"] + row["billed_not_dispatched"]
        if total <= 0:
            continue
        row["customer_name"] = names.get(customer_id, f"Customer #{customer_id}")
        row["total_held"] = total
        out.append(row)
    out.sort(key=lambda r: -r["total_held"])
    return out
