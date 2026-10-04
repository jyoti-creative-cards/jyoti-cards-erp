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

from app.services.customer_bills.create import _apply_billed_to_received_lines

def _shrink_received_for_bill_delta(
    db: Session, customer_id: int, catalog_product_id: int, take: int
) -> None:
    """Reduce received order qty + billed mark by `take` (LIFO)."""
    remaining = take
    received = (
        db.query(CustomerOrder)
        .filter(CustomerOrder.customer_id == customer_id, CustomerOrder.bucket == "received", CustomerOrder.is_open.is_(True))
        .first()
    )
    if not received:
        return
    placements = (
        db.query(CustomerOrderPlacement)
        .filter(CustomerOrderPlacement.customer_order_id == received.id, CustomerOrderPlacement.status == "received")
        .order_by(CustomerOrderPlacement.placed_at.desc())
        .all()
    )
    for p in placements:
        if remaining <= 0:
            break
        lines = (
            db.query(CustomerOrderLine)
            .filter(
                CustomerOrderLine.placement_id == p.id,
                CustomerOrderLine.catalog_product_id == catalog_product_id,
                CustomerOrderLine.status == "active",
            )
            .all()
        )
        for ln in lines:
            if remaining <= 0:
                break
            billed = int(ln.quantity_billed or 0)
            if billed <= 0:
                continue
            cut = min(remaining, billed)
            ln.quantity_billed = billed - cut
            ln.quantity = max(int(ln.quantity_billed), int(ln.quantity) - cut)
            if int(ln.quantity) <= 0:
                ln.status = "cancelled"
            remaining -= cut

def _grow_received_for_bill_delta(
    db: Session,
    customer_id: int,
    catalog_product_id: int,
    take: int,
    unit_price: Decimal,
    customer_name: str,
) -> None:
    """Increase received order qty + billed mark by `take` (latest placement)."""
    if take <= 0:
        return
    received = get_or_create_customer_order(db, customer_id, "received", "received")
    placement = (
        db.query(CustomerOrderPlacement)
        .filter(CustomerOrderPlacement.customer_order_id == received.id, CustomerOrderPlacement.status == "received")
        .order_by(CustomerOrderPlacement.placed_at.desc())
        .first()
    )
    if not placement:
        placement = CustomerOrderPlacement(
            customer_order_id=received.id,
            status="received",
            placed_at=datetime.now(timezone.utc),
        )
        db.add(placement)
        db.flush()
    prod = db.get(CatalogProduct, catalog_product_id)
    our_id = prod.our_product_id if prod else str(catalog_product_id)
    ln = (
        db.query(CustomerOrderLine)
        .filter(
            CustomerOrderLine.placement_id == placement.id,
            CustomerOrderLine.catalog_product_id == catalog_product_id,
            CustomerOrderLine.status == "active",
        )
        .first()
    )
    if ln:
        ln.quantity = int(ln.quantity) + take
        ln.quantity_billed = int(ln.quantity_billed or 0) + take
    else:
        db.add(
            CustomerOrderLine(
                placement_id=placement.id,
                catalog_product_id=catalog_product_id,
                our_product_id=our_id,
                quantity=take,
                quantity_billed=take,
                unit_price=unit_price,
                status="active",
            )
        )
    received.updated_at = datetime.now(timezone.utc)
    close_received_order_if_fully_billed(db, customer_id)

def _apply_bill_qty_delta_to_order(
    db: Session,
    *,
    customer_id: int,
    catalog_product_id: int,
    delta: int,
    unit_price: Decimal,
    customer_name: str,
    bill_placement_id: Optional[int],
) -> None:
    """Keep customer order in sync when a bill line qty changes."""
    if delta == 0:
        return
    prod = db.get(CatalogProduct, catalog_product_id)
    our_id = prod.our_product_id if prod else str(catalog_product_id)

    if bill_placement_id:
        bline = (
            db.query(CustomerOrderLine)
            .filter(
                CustomerOrderLine.placement_id == bill_placement_id,
                CustomerOrderLine.catalog_product_id == catalog_product_id,
            )
            .first()
        )
        if delta > 0:
            if bline:
                bline.quantity = int(bline.quantity) + delta
                bline.quantity_billed = int(bline.quantity_billed or 0) + delta
                bline.status = "billed"
            else:
                db.add(
                    CustomerOrderLine(
                        placement_id=bill_placement_id,
                        catalog_product_id=catalog_product_id,
                        our_product_id=our_id,
                        quantity=delta,
                        quantity_billed=delta,
                        unit_price=unit_price,
                        status="billed",
                    )
                )
        elif bline:
            take = -delta
            bline.quantity = max(0, int(bline.quantity) - take)
            bline.quantity_billed = max(0, int(bline.quantity_billed or 0) - take)
            if bline.quantity <= 0:
                bline.status = "cancelled"

    open_row = (
        db.query(CustomerOpenLine)
        .filter(
            CustomerOpenLine.customer_id == customer_id,
            CustomerOpenLine.catalog_product_id == catalog_product_id,
        )
        .first()
    )

    if delta > 0:
        # Prefer billing existing open qty first; only grow the order for the rest.
        take_from_open = min(delta, int(open_row.quantity_open) if open_row else 0)
        grow = delta - take_from_open
        if take_from_open and open_row:
            open_row.quantity_open = max(0, int(open_row.quantity_open) - take_from_open)
            open_row.quantity_billed = int(open_row.quantity_billed or 0) + take_from_open
            open_row.status = "open"
            _apply_billed_to_received_lines(db, customer_id, catalog_product_id, take_from_open)
        if grow > 0:
            reserve_stock(
                db,
                catalog_product_id=catalog_product_id,
                our_product_id=our_id,
                quantity=grow,
                reference_id=bill_placement_id or catalog_product_id,
                party=customer_name,
            )
            _grow_received_for_bill_delta(
                db, customer_id, catalog_product_id, grow, unit_price, customer_name
            )
            if not open_row:
                open_row = _get_or_create_open_line(db, customer_id, catalog_product_id, unit_price)
            open_row.quantity_received = int(open_row.quantity_received) + grow
            open_row.quantity_billed = int(open_row.quantity_billed or 0) + grow
            open_row.status = "open"
    else:
        take = -delta
        restore_stock(
            db,
            catalog_product_id=catalog_product_id,
            our_product_id=our_id,
            quantity=take,
            reference_id=bill_placement_id or catalog_product_id,
            party=customer_name,
            notes=f"Bill edit reduce {take}",
        )
        _shrink_received_for_bill_delta(db, customer_id, catalog_product_id, take)
        if open_row:
            open_row.quantity_billed = max(0, int(open_row.quantity_billed or 0) - take)
            open_row.quantity_received = max(
                int(open_row.quantity_billed),
                int(open_row.quantity_received) - take,
            )
            if open_row.quantity_open <= 0 and open_row.quantity_billed <= 0:
                open_row.status = "cancelled"

