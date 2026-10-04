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


def _persist_totals_addons(db: Session, bill: CustomerBill) -> None:
    bill.totals_json = attach_addons_to_totals(db, bill.totals_json)
    flag_modified(bill, "totals_json")

def _resolve_bill_transport(
    db: Session,
    *,
    transport_mode: Optional[str],
    freight_agent_id: Optional[int],
    freight_charges: object,
    transport_receipt_number: Optional[str],
) -> tuple[dict, Optional[str]]:
    t = normalize_transport(
        transport_mode=transport_mode,
        freight_agent_id=freight_agent_id,
        freight_charges=freight_charges,
        transport_receipt_number=transport_receipt_number,
    )
    agent_name = None
    if t["freight_agent_id"]:
        agent = db.get(FreightAgent, t["freight_agent_id"])
        if not agent:
            raise HTTPException(400, "freight agent not found")
        agent_name = agent.name
    return t, agent_name

def _line_disc_to_store(use_overall: bool, overall, raw: dict, totals_line: dict) -> Optional[Decimal]:
    if use_overall:
        return overall
    if raw.get("discount_percent") is not None and str(raw.get("discount_percent")).strip() != "":
        return Decimal(str(raw["discount_percent"]))
    pct = totals_line.get("item_discount_percent") if isinstance(totals_line, dict) else None
    if pct is not None and str(pct).strip() != "":
        return Decimal(str(pct))
    return None

