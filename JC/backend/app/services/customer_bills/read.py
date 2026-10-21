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
from app.services.catalog_addons import billing_addons_for_products
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


def get_process_lines(db: Session, customer_id: int) -> dict:
    rows = (
        db.query(CustomerOpenLine)
        .filter(CustomerOpenLine.customer_id == customer_id, CustomerOpenLine.status == "open", CustomerOpenLine.quantity_open > 0)
        .order_by(CustomerOpenLine.our_product_id.asc())
        .all()
    )
    notes_parts: list[str] = []
    received = (
        db.query(CustomerOrder)
        .filter(CustomerOrder.customer_id == customer_id, CustomerOrder.bucket == "received", CustomerOrder.is_open.is_(True))
        .first()
    )
    if received:
        for p in db.query(CustomerOrderPlacement).filter(CustomerOrderPlacement.customer_order_id == received.id).all():
            if p.customer_notes:
                notes_parts.append(p.customer_notes)

    product_ids = [row.catalog_product_id for row in rows]
    bal_map: dict[int, int] = {}
    if product_ids:
        for bal in db.query(StockBalance).filter(StockBalance.catalog_product_id.in_(product_ids)).all():
            bal_map[int(bal.catalog_product_id)] = int(bal.quantity_on_hand or 0)
    addon_map = billing_addons_for_products(db, customer_id, product_ids) if product_ids else {}
    from app.services.document_present import live_product_names
    names = live_product_names(db, product_ids)

    out = []
    for row in rows:
        out.append(
            {
                "open_line_id": row.id,
                "catalog_product_id": row.catalog_product_id,
                "our_product_id": names.get(int(row.catalog_product_id)) or row.our_product_id,
                "unit_price": format(row.unit_price, "f"),
                "quantity_placed": row.quantity_received,
                "quantity_open": row.quantity_open,
                "quantity_billed": row.quantity_billed,
                "quantity_on_hand": bal_map.get(row.catalog_product_id, 0),
                "addons": addon_map.get(int(row.catalog_product_id), []),
            }
        )
    return {
        "lines": out,
        "orders": billable_orders(db, customer_id),
        "default_narration": " · ".join(notes_parts),
        "credit": credit_status(db, customer_id),
    }


def billable_orders(db: Session, customer_id: int) -> list[dict]:
    """Confirmed orders that still have quantity to bill.

    Older bills sometimes reduced the open tally without marking the order line
    billed. Those already-billed orders must not come back as selected rows.
    Anything above the quantity still open is treated as already billed, oldest
    order first. A hold note stays on the orders that are still open.
    """
    orders = (
        db.query(CustomerOrder)
        .filter(
            CustomerOrder.customer_id == customer_id,
            CustomerOrder.is_open.is_(True),
            CustomerOrder.bucket.in_(["open", "received"]),
        )
        .all()
    )
    if not orders:
        return []
    placements = (
        db.query(CustomerOrderPlacement)
        .filter(
            CustomerOrderPlacement.customer_order_id.in_([o.id for o in orders]),
            CustomerOrderPlacement.deleted_at.is_(None),
            CustomerOrderPlacement.status.in_(["open", "received"]),
        )
        .order_by(CustomerOrderPlacement.placed_at.asc(), CustomerOrderPlacement.id.asc())
        .all()
    )
    if not placements:
        return []
    lines = (
        db.query(CustomerOrderLine)
        .filter(
            CustomerOrderLine.placement_id.in_([p.id for p in placements]),
            CustomerOrderLine.status == "active",
        )
        .order_by(CustomerOrderLine.id.asc())
        .all()
    )
    by_placement: dict[int, list] = {}
    for ln in lines:
        left = int(ln.quantity) - int(ln.quantity_billed or 0)
        if left <= 0:
            continue
        by_placement.setdefault(int(ln.placement_id), []).append(
            {
                "catalog_product_id": int(ln.catalog_product_id),
                "our_product_id": ln.our_product_id,
                "quantity": left,
                "unit_price": format(ln.unit_price, "f"),
            }
        )
    room = {
        int(row.catalog_product_id): int(row.quantity_open or 0)
        for row in db.query(CustomerOpenLine).filter(
            CustomerOpenLine.customer_id == customer_id,
            CustomerOpenLine.status == "open",
            CustomerOpenLine.quantity_open > 0,
        ).all()
    }
    still_open = {int(cid): int(qty) for cid, qty in room.items()}
    for placement in placements:
        for row in by_placement.get(int(placement.id)) or []:
            cid = int(row["catalog_product_id"])
            still_open[cid] = still_open.get(cid, 0) - int(row["quantity"])
    # Negative means the order lines claim more unbilled qty than is still open.
    hide_left = {cid: -qty for cid, qty in still_open.items() if qty < 0}
    out = []
    for placement in placements:
        shown = []
        for row in by_placement.get(int(placement.id)) or []:
            cid = int(row["catalog_product_id"])
            qty = int(row["quantity"])
            hide = min(qty, int(hide_left.get(cid) or 0))
            if hide:
                hide_left[cid] = int(hide_left.get(cid) or 0) - hide
            keep = qty - hide
            if keep <= 0:
                continue
            shown.append({**row, "quantity": keep})
        if not shown:
            continue
        out.append(
            {
                "placement_id": int(placement.id),
                "placed_at": placement.placed_at,
                "order_source": placement.order_source,
                "placed_by_name": placement.placed_by_name,
                "customer_notes": placement.customer_notes,
                "lines": shown,
            }
        )
    return out

