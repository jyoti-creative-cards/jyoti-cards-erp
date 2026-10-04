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

from app.services.customer_bills.common import _persist_totals_addons

def process_offline_customer_order(
    db: Session,
    *,
    customer_id: int,
    customer_name: str,
    lines_in: list[dict],
    overall_discount_percent: Optional[Decimal],
    gst_enabled: bool,
    gst_rate_percent: Decimal,
    additional_charges: Optional[list[dict]],
    bill_series_id: int,
    narration: Optional[str],
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
) -> tuple[CustomerBill, CustomerOrderPlacement]:
    order_lines = [ln for ln in lines_in if int(ln.get("quantity") or 0) > 0]
    if not order_lines:
        raise HTTPException(400, "enter quantity on at least one line")

    bill_items: list[dict] = []
    item_overrides: list[dict] = []
    use_overall = overall_discount_percent is not None and overall_discount_percent > 0

    for ln in order_lines:
        cid = int(ln["catalog_product_id"])
        qty = int(ln["quantity"])
        prod = db.get(CatalogProduct, cid)
        if not prod or not prod.is_active:
            raise HTTPException(400, f"product {cid} not found")
        if prod.selling_price is None:
            raise HTTPException(400, f"sell price not set for {prod.our_product_id}")
        bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == cid).first()
        on_hand = bal.quantity_on_hand if bal else 0
        if on_hand < qty:
            raise HTTPException(400, f"insufficient stock for {prod.our_product_id} (have {on_hand})")
        unit_price = prod.selling_price
        bill_items.append(
            {
                "catalog_product_id": cid,
                "our_product_id": prod.our_product_id,
                # Customer-facing doc — never show the vendor's own product code here.
                "name": prod.our_product_id,
                "quantity": qty,
                "unit_price": format(unit_price, "f"),
            }
        )
        if not use_overall:
            ov: dict = {"catalog_product_id": cid}
            if ln.get("net_rate") is not None and str(ln.get("net_rate")).strip() != "":
                ov["override_price"] = ln["net_rate"]
            if ln.get("discount_percent") is not None:
                ov["discount_percent"] = ln["discount_percent"]
            if "override_price" in ov or "discount_percent" in ov:
                item_overrides.append(ov)

    totals = compute_bill_totals(
        bill_items,
        gst_enabled=gst_enabled,
        gst_rate_percent=gst_rate_percent,
        discount_percent=overall_discount_percent if use_overall else None,
        item_overrides=item_overrides if not use_overall else None,
        additional_charges=additional_charges,
    )

    from app.services.biz_date import today_ist

    bill_number = allocate_bill_number(db, bill_series_id)
    now = datetime.now(timezone.utc)

    billed_order = get_or_create_customer_order(db, customer_id, "billed", "billed")
    placement = CustomerOrderPlacement(
        customer_order_id=billed_order.id,
        status="billed",
        customer_notes=narration or "Offline order",
        order_source="offline",
        placed_by_name="Admin" if actor_type == "admin" else ((actor_name or "").strip() or "Staff"),
        placed_at=now,
    )
    db.add(placement)
    db.flush()

    grand = Decimal(str(totals.get("rounded_grand_total") or totals["grand_total"]))
    bill = CustomerBill(
        customer_id=customer_id,
        placement_id=placement.id,
        bill_number=bill_number,
        bill_series_id=bill_series_id,
        narration=narration,
        gst_enabled=gst_enabled,
        gst_rate_percent=gst_rate_percent,
        discount_percent=overall_discount_percent,
        additional_charges=additional_charges,
        subtotal_inclusive=Decimal(str(totals["subtotal_inclusive"])),
        discount_amount=Decimal(str(totals.get("discount_amount") or "0")),
        taxable_value=Decimal(str(totals.get("taxable_value") or "0")),
        gst_amount=Decimal(str(totals.get("gst_amount") or "0")),
        grand_total=grand,
        totals_json=totals,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
        bill_date=today_ist(),
        created_at=now,
    )
    db.add(bill)
    db.flush()

    line_totals = {int(ln["catalog_product_id"]): ln for ln in order_lines}
    addon_map = addon_snapshots_map(db, [int(x["catalog_product_id"]) for x in bill_items])
    for bl in totals.get("lines") or []:
        sku = bl.get("our_product_id")
        match = next((x for x in bill_items if x["our_product_id"] == sku), None)
        if not match:
            continue
        cid = int(match["catalog_product_id"])
        qty = int(match["quantity"])
        line_total = Decimal(str(bl.get("line_total") or "0"))
        disc = None
        if use_overall:
            disc = overall_discount_percent
        else:
            raw = line_totals.get(cid, {})
            if raw.get("discount_percent") is not None:
                disc = Decimal(str(raw["discount_percent"]))
        addons = addon_map.get(cid) or []
        db.add(
            CustomerBillLine(
                bill_id=bill.id,
                catalog_product_id=cid,
                our_product_id=sku,
                quantity_shipped=qty,
                unit_price=Decimal(str(match["unit_price"])),
                line_total=line_total,
                discount_percent=disc,
            )
        )
        db.add(
            CustomerOrderLine(
                placement_id=placement.id,
                catalog_product_id=cid,
                our_product_id=sku,
                quantity=qty,
                quantity_billed=qty,
                unit_price=Decimal(str(match["unit_price"])),
                addons_json=addons or None,
                status="billed",
            )
        )
        add_stock(
            db,
            catalog_product_id=cid,
            our_product_id=sku,
            quantity=-qty,
            entry_type="sold",
            reference_type="customer_bill",
            reference_id=bill.id,
            party=customer_name,
            notes=f"Offline bill {bill_number}",
        )

    if bill.totals_json and isinstance(bill.totals_json.get("lines"), list):
        _persist_totals_addons(db, bill)

    post_bill_entry(
        db,
        customer_id=customer_id,
        bill_id=bill.id,
        amount=grand,
        description=f"Bill {bill_number} — ₹{grand}",
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
        value_date=today_ist(),
        created_at=now,
    )
    billed_order.updated_at = now
    return bill, placement

