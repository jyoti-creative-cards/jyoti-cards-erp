from __future__ import annotations
"""Split from app/services/customer_bill_process.py."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.stock import StockBalance
from app.models.freight_agent import FreightAgent
from app.services.ar_ledger import post_bill_entry, update_bill_ledger_amount
from app.services.bill_series_alloc import allocate_bill_number, resolve_bill_number
from app.services.catalog_addons import addon_snapshots_map, attach_addons_to_totals
from app.services.credit_limit import assert_credit_allows_bill, credit_status
from app.services.customer_bill_math import assert_discount_xor, compute_bill_totals
from app.services.document_present import freeze_card
from app.services import response_cache
from app.services.transport_mode import normalize_transport, stamp_transport_on_totals
from app.services.customer_order_flow import (
    _get_or_create_open_line,
    close_received_order_if_fully_billed,
    get_or_create_customer_order,
    reserve_stock,
    restore_stock,
)
from app.services.stock_receipt import add_stock

from app.services.customer_bills.sync import _shrink_received_for_bill_delta

def cancel_open_line(db: Session, line_id: int, reason: str, customer_name: str) -> None:
    row = db.get(CustomerOpenLine, line_id)
    if not row or row.status != "open":
        raise HTTPException(404, "open line not found")
    qty = row.quantity_open
    if qty <= 0:
        raise HTTPException(400, "nothing to cancel")
    from app.services.catalog_addons import kept_addon_ids_for_customer_product

    restore_stock(
        db,
        catalog_product_id=row.catalog_product_id,
        our_product_id=row.our_product_id,
        quantity=qty,
        reference_id=line_id,
        party=customer_name,
        notes=f"Cancelled open: {reason}",
        only_addon_ids=kept_addon_ids_for_customer_product(db, row.customer_id, row.catalog_product_id),
    )
    row.quantity_open = 0
    row.quantity_received = max(row.quantity_billed, row.quantity_received - qty)
    # Billed qty stays — only open is cancelled
    if int(row.quantity_billed or 0) > 0:
        row.status = "open"
        row.cancel_reason = None
    else:
        row.status = "cancelled"
        row.cancel_reason = reason
    _cancel_received_qty(db, row.customer_id, row.catalog_product_id, qty, reason)

def _cancel_received_qty(db: Session, customer_id: int, catalog_product_id: int, qty: int, reason: str) -> None:
    remaining = qty
    cancelled_order = get_or_create_customer_order(db, customer_id, "cancelled", "cancelled")
    placement = CustomerOrderPlacement(
        customer_order_id=cancelled_order.id,
        status="cancelled",
        cancel_reason=reason,
        placed_at=datetime.now(timezone.utc),
    )
    db.add(placement)
    db.flush()
    received = (
        db.query(CustomerOrder)
        .filter(CustomerOrder.customer_id == customer_id, CustomerOrder.bucket == "received", CustomerOrder.is_open.is_(True))
        .first()
    )
    if not received:
        return
    for p in (
        db.query(CustomerOrderPlacement)
        .filter(CustomerOrderPlacement.customer_order_id == received.id, CustomerOrderPlacement.status == "received")
        .order_by(CustomerOrderPlacement.placed_at.asc())
        .all()
    ):
        if remaining <= 0:
            break
        for ln in db.query(CustomerOrderLine).filter(
            CustomerOrderLine.placement_id == p.id,
            CustomerOrderLine.catalog_product_id == catalog_product_id,
            CustomerOrderLine.status == "active",
        ).all():
            if remaining <= 0:
                break
            billed = int(ln.quantity_billed or 0)
            unbilled = int(ln.quantity) - billed
            if unbilled <= 0:
                continue
            take = min(remaining, unbilled)
            remaining -= take
            if billed > 0:
                # Keep billed qty on the received line; only drop unbilled
                ln.quantity = billed
            else:
                ln.status = "cancelled"
                ln.cancel_reason = reason
            db.add(
                CustomerOrderLine(
                    placement_id=placement.id,
                    catalog_product_id=catalog_product_id,
                    our_product_id=ln.our_product_id,
                    quantity=take,
                    quantity_billed=0,
                    unit_price=ln.unit_price,
                    status="cancelled",
                    cancel_reason=reason,
                )
            )

def cancel_customer_bill(
    db: Session,
    *,
    bill_id: int,
    reason: str,
    actor_name: str,
) -> CustomerBill:
    """Cancel a bill: AR cleared, freight cleared, stock released back to on-hand.

    The cancelled qty is dropped from the customer's order entirely (not sent back to
    "to bill") — it is deliberately NOT re-added to CustomerOpenLine.quantity_open,
    because that stock is no longer actually held for this customer once released. If
    it were silently re-opened, a later re-bill would ship it without re-reserving,
    double-selling the same units. If the customer still wants these items, place a
    fresh order — that reserves stock again the normal way.
    """
    from app.services.freight_parcels import remove_charge_for_bill

    bill = db.get(CustomerBill, bill_id)
    if not bill:
        raise HTTPException(404, "bill not found")
    if bill.cancelled_at:
        raise HTTPException(400, "bill already cancelled")

    customer = db.get(Customer, bill.customer_id)
    customer_name = customer.business_name if customer else f"Customer #{bill.customer_id}"
    reason = (reason or "").strip() or "cancelled"
    lines = (
        db.query(CustomerBillLine)
        .filter(CustomerBillLine.bill_id == bill.id)
        .all()
    )
    closed_count = sum(1 for ln in lines if ln.status == "closed")
    if 0 < closed_count < len(lines):
        raise HTTPException(400, "cannot cancel — some lines already closed and some are not; close or reverse them consistently first")
    # If every line is already closed there's nothing left to reverse (stock was
    # legitimately dispatched) — the loop below is a no-op for "closed" lines, so
    # cancelling just records the cancellation and zeroes the AR ledger amount below.

    for ln in lines:
        if ln.status != "billed":
            continue
        qty = int(ln.quantity_shipped or 0)
        if qty <= 0:
            ln.status = "closed"
            ln.close_reason = reason
            ln.closed_at = datetime.now(timezone.utc)
            continue

        # Release the stock this bill line held — whether it came from a portal
        # reservation (at order time) or an offline sale (at bill time), the deal is
        # off: give the units back to on-hand.
        from app.services.catalog_addons import kept_addon_ids_for_customer_product

        restore_stock(
            db,
            catalog_product_id=ln.catalog_product_id,
            our_product_id=ln.our_product_id,
            quantity=qty,
            reference_id=bill.id,
            party=customer_name,
            notes=f"Bill {bill.bill_number} cancelled — stock released",
            only_addon_ids=kept_addon_ids_for_customer_product(db, bill.customer_id, ln.catalog_product_id),
        )

        # Drop the qty from the customer's outstanding order (do not reopen it — see
        # docstring). Reduce billed/received tallies only; quantity_open is untouched.
        open_row = (
            db.query(CustomerOpenLine)
            .filter(
                CustomerOpenLine.customer_id == bill.customer_id,
                CustomerOpenLine.catalog_product_id == ln.catalog_product_id,
            )
            .first()
        )
        if open_row:
            open_row.quantity_billed = max(0, int(open_row.quantity_billed or 0) - qty)
            open_row.quantity_received = max(
                int(open_row.quantity_open or 0),
                int(open_row.quantity_received or 0) - qty,
            )
            if int(open_row.quantity_open or 0) <= 0 and int(open_row.quantity_billed or 0) <= 0:
                open_row.status = "cancelled"
        _shrink_received_for_bill_delta(db, bill.customer_id, ln.catalog_product_id, qty)

        ln.status = "closed"
        ln.close_reason = f"Bill cancelled — {reason}"[:500]
        ln.closed_at = datetime.now(timezone.utc)

    # Cancel billed placement lines for this bill — move history into Cancelled bucket
    if bill.placement_id:
        for ol in (
            db.query(CustomerOrderLine)
            .filter(CustomerOrderLine.placement_id == bill.placement_id)
            .all()
        ):
            ol.status = "cancelled"
            ol.cancel_reason = reason
        placement = db.get(CustomerOrderPlacement, bill.placement_id)
        if placement:
            placement.status = "cancelled"
            placement.cancel_reason = reason
            # Re-home under cancelled order so Past → Billed does not keep showing them
            cancelled_order = get_or_create_customer_order(
                db, bill.customer_id, "cancelled", "cancelled"
            )
            if placement.customer_order_id != cancelled_order.id:
                placement.customer_order_id = cancelled_order.id
                cancelled_order.updated_at = datetime.now(timezone.utc)

    # Freight: drop dues charge + clear assignment (pending or picked)
    remove_charge_for_bill(db, bill.id)
    bill.freight_agent_id = None
    bill.freight_charges = None
    bill.freight_picked_at = None
    bill.freight_picked_by = None

    update_bill_ledger_amount(
        db,
        bill_id=bill.id,
        amount=Decimal("0"),
        description=f"Bill {bill.bill_number} cancelled — {reason}"[:500],
    )

    bill.cancelled_at = datetime.now(timezone.utc)
    bill.cancel_reason = reason
    bill.document_key = None
    db.flush()
    # Bill number stays consumed — cancelled bills keep their number; next bill advances.
    return bill

def close_bill_line(db: Session, bill_line_id: int, reason: str) -> None:
    row = db.get(CustomerBillLine, bill_line_id)
    if not row or row.status == "closed":
        raise HTTPException(404, "bill line not found or already closed")
    bill = db.get(CustomerBill, row.bill_id)
    if not bill:
        raise HTTPException(404, "bill not found")
    now = datetime.now(timezone.utc)
    row.status = "closed"
    row.close_reason = reason
    row.closed_at = now
    closed_order = get_or_create_customer_order(db, bill.customer_id, "closed", "closed")
    placement = CustomerOrderPlacement(
        customer_order_id=closed_order.id,
        status="closed",
        cancel_reason=reason,
        placed_at=now,
        closed_at=now,
    )
    db.add(placement)
    db.flush()
    db.add(
        CustomerOrderLine(
            placement_id=placement.id,
            catalog_product_id=row.catalog_product_id,
            our_product_id=row.our_product_id,
            quantity=row.quantity_shipped,
            quantity_billed=row.quantity_shipped,
            unit_price=row.unit_price,
            status="closed",
            cancel_reason=reason,
        )
    )
    closed_order.updated_at = now
    db.flush()

    # Once every line on this bill is closed, the bill itself is done — drop it out of
    # the "Billed" backlog (its per-line history now lives under "Closed"). Without this,
    # a fully-settled bill stays visible in "Billed" forever with no way to clear it.
    remaining_open = (
        db.query(CustomerBillLine)
        .filter(CustomerBillLine.bill_id == bill.id, CustomerBillLine.status != "closed")
        .count()
    )
    if remaining_open == 0 and not bill.closed_at:
        bill.closed_at = now
    freeze_card(db, "customer_order", placement)

