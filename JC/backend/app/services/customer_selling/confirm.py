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

from app.services.customer_selling.buckets import add_to_customer_open, get_open_customer_order, get_or_create_customer_order

def confirm_received_order(db: Session, customer_id: int) -> bool:
    """Move a customer's received (New) order to the open (Confirmed) bucket.

    Returns True if something was confirmed, False if there was nothing to confirm.
    CustomerOpenLine (the running unbilled tally used for the Confirmed list + billing)
    is only populated here, at confirm time — never at placement time — so a fresh order
    only ever shows under "New" until someone explicitly confirms it.
    """
    received = get_open_customer_order(db, customer_id, "received")
    if not received:
        return False

    # Check there are any active lines worth confirming
    placements = (
        db.query(CustomerOrderPlacement)
        .filter(
            CustomerOrderPlacement.customer_order_id == received.id,
            CustomerOrderPlacement.status == "received",
        )
        .all()
    )
    active_lines = (
        db.query(CustomerOrderLine)
        .filter(
            CustomerOrderLine.placement_id.in_([p.id for p in placements]),
            CustomerOrderLine.status == "active",
        )
        .all()
    ) if placements else []

    if not active_lines:
        return False

    # Only now does this order's qty become part of the billable "open" tally.
    add_to_customer_open(
        db,
        customer_id,
        [
            (int(ln.catalog_product_id), int(ln.quantity) - int(ln.quantity_billed or 0), ln.unit_price)
            for ln in active_lines
            if int(ln.quantity) - int(ln.quantity_billed or 0) > 0
        ],
    )

    # Move the order bucket from received → open
    # Get or create the open order for this customer
    open_order = get_open_customer_order(db, customer_id, "open")
    if open_order is None:
        # Repurpose the received order as the open order
        received.bucket = "open"
        received.status = "open"
        received.updated_at = datetime.now(timezone.utc)
        for p in placements:
            p.status = "open"
    else:
        # Re-parent placements to the existing open order
        for p in placements:
            p.customer_order_id = open_order.id
            p.status = "open"
        open_order.updated_at = datetime.now(timezone.utc)
        # Close the (now empty) received order
        received.is_open = False

    return True

def promote_placement_to_confirmed(db: Session, placement: CustomerOrderPlacement) -> None:
    """Staff placed this order for the customer. Skip New and put it in Confirmed."""
    order = db.get(CustomerOrder, placement.customer_order_id)
    if not order or order.bucket != "received":
        return
    lines = (
        db.query(CustomerOrderLine)
        .filter(CustomerOrderLine.placement_id == placement.id, CustomerOrderLine.status == "active")
        .all()
    )
    add_to_customer_open(
        db,
        order.customer_id,
        [
            (int(ln.catalog_product_id), int(ln.quantity) - int(ln.quantity_billed or 0), ln.unit_price)
            for ln in lines
            if int(ln.quantity) - int(ln.quantity_billed or 0) > 0
        ],
        as_of=datetime.now(timezone.utc),
    )
    others = (
        db.query(CustomerOrderPlacement)
        .filter(
            CustomerOrderPlacement.customer_order_id == order.id,
            CustomerOrderPlacement.id != placement.id,
            CustomerOrderPlacement.deleted_at.is_(None),
            CustomerOrderPlacement.status == "received",
        )
        .count()
    )
    open_order = get_open_customer_order(db, order.customer_id, "open")
    if open_order is None and others == 0:
        order.bucket = "open"
        order.status = "open"
        order.updated_at = datetime.now(timezone.utc)
        placement.status = "open"
        return
    if open_order is None:
        open_order = get_or_create_customer_order(db, order.customer_id, "open", "open")
    placement.customer_order_id = open_order.id
    placement.status = "open"
    open_order.updated_at = datetime.now(timezone.utc)
    if others == 0:
        order.is_open = False

def close_received_order_if_fully_billed(db: Session, customer_id: int) -> None:
    """A New order whose every line is already on a bill should leave the New list."""
    received = get_open_customer_order(db, customer_id, "received")
    if not received:
        return
    leftover = (
        db.query(CustomerOrderLine.id)
        .join(CustomerOrderPlacement, CustomerOrderPlacement.id == CustomerOrderLine.placement_id)
        .filter(
            CustomerOrderPlacement.customer_order_id == received.id,
            CustomerOrderPlacement.deleted_at.is_(None),
            CustomerOrderLine.status == "active",
            CustomerOrderLine.quantity > CustomerOrderLine.quantity_billed,
        )
        .first()
    )
    if leftover:
        return
    received.is_open = False
    received.updated_at = datetime.now(timezone.utc)

def get_open_unbilled_placement(db: Session, customer_id: int) -> CustomerOrderPlacement | None:
    """Latest open received placement with no billed lines — dealer’s one active order."""
    received = get_open_customer_order(db, customer_id, "received")
    if not received:
        return None
    placements = (
        db.query(CustomerOrderPlacement)
        .filter(
            CustomerOrderPlacement.customer_order_id == received.id,
            CustomerOrderPlacement.status == "received",
        )
        .order_by(CustomerOrderPlacement.placed_at.desc())
        .all()
    )
    for p in placements:
        lines = (
            db.query(CustomerOrderLine)
            .filter(CustomerOrderLine.placement_id == p.id, CustomerOrderLine.status.in_(["active", "billed"]))
            .all()
        )
        if not lines:
            return p
        if any(int(ln.quantity_billed or 0) > 0 for ln in lines):
            continue
        return p
    return None

