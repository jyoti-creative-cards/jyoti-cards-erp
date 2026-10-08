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
from app.services.catalog_addons import billing_addons_for_products, merge_priced_addon_charges
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

from app.services.customer_bills.common import _line_disc_to_store, _persist_totals_addons, _resolve_bill_transport

def process_customer_bill(
    db: Session,
    *,
    customer_id: int,
    customer_name: str,
    lines_in: list[dict],
    overall_discount_percent: Optional[Decimal],
    gst_enabled: bool,
    gst_rate_percent: Decimal,
    freight_agent_id: Optional[int],
    freight_charges: Optional[Decimal],
    packaging_charges: Optional[Decimal],
    additional_charges: Optional[list[dict]],
    bill_series_id: int,
    narration: Optional[str],
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
    force_credit_override: bool = False,
    bill_date=None,
    bill_number: str | None = None,
    transport_mode: Optional[str] = None,
    transport_receipt_number: Optional[str] = None,
    freight_charges_raw: object = None,
) -> CustomerBill:
    ship_lines = [ln for ln in lines_in if int(ln.get("quantity_to_ship") or 0) > 0]
    if not ship_lines:
        raise HTTPException(400, "enter quantity to ship on at least one line")

    assert_discount_xor(overall_discount_percent, ship_lines)
    t, agent_name = _resolve_bill_transport(
        db,
        transport_mode=transport_mode,
        freight_agent_id=freight_agent_id,
        freight_charges=freight_charges_raw if freight_charges_raw is not None else freight_charges,
        transport_receipt_number=transport_receipt_number,
    )
    freight_agent_id = t["freight_agent_id"]
    freight_charges = t["freight_charges"]

    open_map = {
        r.catalog_product_id: r
        for r in db.query(CustomerOpenLine)
        .filter(CustomerOpenLine.customer_id == customer_id, CustomerOpenLine.status == "open")
        .with_for_update()
        .all()
    }

    bill_items: list[dict] = []
    item_overrides: list[dict] = []
    use_overall = overall_discount_percent is not None and overall_discount_percent > 0

    for ln in ship_lines:
        cid = int(ln["catalog_product_id"])
        qty = int(ln["quantity_to_ship"])
        row = open_map.get(cid)
        if not row or qty > row.quantity_open:
            raise HTTPException(400, f"cannot ship more than open qty for product {cid}")
        bill_items.append(
            {
                "catalog_product_id": cid,
                "our_product_id": row.our_product_id,
                # Customer-facing doc — never show the vendor's own product code here.
                "name": row.our_product_id,
                "quantity": qty,
                "unit_price": str(row.unit_price),
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

    addon_map = billing_addons_for_products(
        db, customer_id, [int(x["catalog_product_id"]) for x in bill_items]
    )
    additional_charges = merge_priced_addon_charges(additional_charges, addon_map, bill_items)

    totals = compute_bill_totals(
        bill_items,
        gst_enabled=gst_enabled,
        gst_rate_percent=gst_rate_percent,
        discount_percent=overall_discount_percent if use_overall else None,
        freight_charges=freight_charges,
        packaging_charges=packaging_charges,
        item_overrides=item_overrides if not use_overall else None,
        additional_charges=additional_charges,
    )
    totals = stamp_transport_on_totals(totals, t, agent_name=agent_name)
    grand_check = Decimal(str(totals.get("rounded_grand_total") or totals["grand_total"]))
    assert_credit_allows_bill(db, customer_id, grand_check, force=force_credit_override)

    from app.services.biz_date import resolve_biz_dt, resolve_invoice_date

    bill_number = resolve_bill_number(db, bill_series_id, bill_number)
    entered_at = datetime.now(timezone.utc)
    invoice_day = resolve_invoice_date(bill_date)
    # bill.created_at / placement.placed_at stay real "now" on purpose — the Billed hub
    # tab's Today/Past scoping keys off these (same rule as backdated customer orders:
    # a backdated entry lands in Past, it doesn't masquerade as Today). The AR *ledger*
    # row is different — it's a money record, not a queue item, so it should carry the
    # bill's real (possibly backdated) date the same way vendor AP entries already do.
    ar_posted_at = resolve_biz_dt(bill_date)

    billed_order = get_or_create_customer_order(db, customer_id, "billed", "billed")
    from app.services.doc_gen import source_order_for_customer

    src_at, src_by = source_order_for_customer(
        db, customer_id, [int(x["catalog_product_id"]) for x in bill_items]
    )
    if src_by == "Party (app)":
        src_source, src_name = "app", None
    elif src_by:
        src_source, src_name = "offline", src_by
    else:
        src_source, src_name = None, None
    placement = CustomerOrderPlacement(
        customer_order_id=billed_order.id,
        status="billed",
        placed_at=src_at or entered_at,
        order_source=src_source,
        placed_by_name=src_name,
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
        freight_agent_id=freight_agent_id,
        freight_charges=freight_charges,
        transport_mode=t["transport_mode"],
        transport_receipt_number=t["transport_receipt_number"],
        packaging_charges=packaging_charges,
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
        bill_date=invoice_day,
        created_at=entered_at,
    )
    db.add(bill)
    db.flush()

    line_totals = {int(ln["catalog_product_id"]): ln for ln in ship_lines}
    billed_qty: dict[int, int] = {}
    for bl in totals.get("lines") or []:
        sku = bl.get("our_product_id")
        match = next((x for x in bill_items if x["our_product_id"] == sku), None)
        if not match:
            continue
        cid = int(match["catalog_product_id"])
        qty = int(match["quantity"])
        line_total = Decimal(str(bl.get("line_total") or "0"))
        disc = _line_disc_to_store(use_overall, overall_discount_percent, line_totals.get(cid, {}), bl)

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
                addons_json=addon_map.get(cid) if addon_map.get(cid) is not None else None,
                status="billed",
            )
        )
        open_row = open_map.get(cid)
        if open_row:
            open_row.quantity_open = max(0, open_row.quantity_open - qty)
            open_row.quantity_billed += qty
            if open_row.quantity_open <= 0:
                open_row.status = "open"
        billed_qty[cid] = billed_qty.get(cid, 0) + qty

    _apply_billed_qtys_to_received(db, customer_id, billed_qty)

    from app.services.freight_parcels import ensure_bill_freight_charge

    ensure_bill_freight_charge(
        db, bill, customer_name=customer_name, actor_name=actor_name,
    )

    post_bill_entry(
        db,
        customer_id=customer_id,
        bill_id=bill.id,
        amount=grand,
        description=f"Bill {bill_number} — ₹{grand}",
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
        value_date=invoice_day,
        created_at=ar_posted_at,
    )
    _persist_totals_addons(db, bill)
    billed_order.updated_at = entered_at
    freeze_card(db, "customer_bill", bill)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    response_cache.invalidate("catalog:")
    return bill

def _apply_billed_to_received_lines(db: Session, customer_id: int, catalog_product_id: int, qty: int) -> None:
    _apply_billed_qtys_to_received(db, customer_id, {int(catalog_product_id): int(qty)})


def _apply_billed_qtys_to_received(db: Session, customer_id: int, qty_by_product: dict[int, int]) -> None:
    """Mark New-order lines billed in one read. Oldest placement first, same as before."""
    remaining = {int(cid): int(qty) for cid, qty in qty_by_product.items() if int(qty) > 0}
    if not remaining:
        close_received_order_if_fully_billed(db, customer_id)
        return
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
        .order_by(CustomerOrderPlacement.placed_at.asc(), CustomerOrderPlacement.id.asc())
        .all()
    )
    if not placements:
        close_received_order_if_fully_billed(db, customer_id)
        return
    rank = {p.id: i for i, p in enumerate(placements)}
    lines = (
        db.query(CustomerOrderLine)
        .filter(
            CustomerOrderLine.placement_id.in_([p.id for p in placements]),
            CustomerOrderLine.catalog_product_id.in_(list(remaining)),
            CustomerOrderLine.status == "active",
        )
        .all()
    )
    lines.sort(key=lambda ln: (rank.get(ln.placement_id, 0), ln.id))
    for ln in lines:
        left = remaining.get(int(ln.catalog_product_id), 0)
        if left <= 0:
            continue
        unbilled = int(ln.quantity) - int(ln.quantity_billed or 0)
        if unbilled <= 0:
            continue
        take = min(left, unbilled)
        ln.quantity_billed = int(ln.quantity_billed or 0) + take
        remaining[int(ln.catalog_product_id)] = left - take
    close_received_order_if_fully_billed(db, customer_id)

