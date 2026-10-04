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
    addon_map = addon_snapshots_map(db, product_ids, with_images=False) if product_ids else {}
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
        "default_narration": " · ".join(notes_parts),
        "credit": credit_status(db, customer_id),
    }

