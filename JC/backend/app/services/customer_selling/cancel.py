from __future__ import annotations
"""Split from app/services/customer_order_flow.py."""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.stock import StockBalance
from app.services.stock_receipt import add_stock
from app.services.addon_stock import deduct_addons_for_product

from app.services.customer_selling.buckets import get_or_create_customer_order
from app.services.customer_selling.stock import restore_stock

def cancel_customer_placement(
    db: Session,
    *,
    placement_id: int,
    reason: str,
    customer_name: str,
) -> CustomerOrderPlacement:
    """Cancel unbilled qty on a received placement. Billed qty is never cancelled."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("cancel reason required")

    placement = db.get(CustomerOrderPlacement, placement_id)
    if not placement:
        raise ValueError("placement not found")
    if placement.status != "received":
        raise ValueError("only received placements can be cancelled")

    order = db.get(CustomerOrder, placement.customer_order_id)
    if not order or order.bucket != "received":
        raise ValueError("cannot cancel — not a received order")

    lines = (
        db.query(CustomerOrderLine)
        .filter(
            CustomerOrderLine.placement_id == placement.id,
            CustomerOrderLine.status == "active",
        )
        .all()
    )
    cancellable = []
    for ln in lines:
        billed = int(ln.quantity_billed or 0)
        unbilled = int(ln.quantity) - billed
        if unbilled > 0:
            cancellable.append((ln, unbilled, billed))
    if not cancellable:
        raise ValueError("nothing left to cancel — already billed")

    cancelled_order = get_or_create_customer_order(db, order.customer_id, "cancelled", "cancelled")
    hist = CustomerOrderPlacement(
        customer_order_id=cancelled_order.id,
        status="cancelled",
        cancel_reason=reason,
        customer_notes=placement.customer_notes,
        placed_at=placement.placed_at,
    )
    db.add(hist)
    db.flush()

    now = datetime.now(timezone.utc)
    for ln, unbilled, billed in cancellable:
        # NB: only "received" (not yet confirmed) placements reach here — CustomerOpenLine
        # rows are created at confirm time, so there's nothing on that table to unwind.
        restore_stock(
            db,
            catalog_product_id=ln.catalog_product_id,
            our_product_id=ln.our_product_id,
            quantity=unbilled,
            reference_id=placement.id,
            party=customer_name,
            notes=f"Cancelled placement open: {reason}",
        )

        if billed > 0:
            ln.quantity = billed
        else:
            ln.status = "cancelled"
            ln.cancel_reason = reason

        db.add(
            CustomerOrderLine(
                placement_id=hist.id,
                catalog_product_id=ln.catalog_product_id,
                our_product_id=ln.our_product_id,
                quantity=unbilled,
                quantity_billed=0,
                unit_price=ln.unit_price,
                addons_json=ln.addons_json,
                status="cancelled",
                cancel_reason=reason,
            )
        )

    still_active = (
        db.query(CustomerOrderLine)
        .filter(
            CustomerOrderLine.placement_id == placement.id,
            CustomerOrderLine.status == "active",
        )
        .count()
    )
    if still_active == 0:
        placement.status = "cancelled"
        placement.cancel_reason = reason
        placement.closed_at = now
    order.updated_at = now
    cancelled_order.updated_at = now
    return placement

