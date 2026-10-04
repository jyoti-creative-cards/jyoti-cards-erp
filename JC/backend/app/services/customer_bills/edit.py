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

from app.services.customer_bills.common import _line_disc_to_store, _persist_totals_addons, _resolve_bill_transport
from app.services.customer_bills.sync import _apply_bill_qty_delta_to_order

def _prepare_edit_bill_totals(
    db: Session,
    *,
    bill_id: int,
    lines_in: list[dict],
    overall_discount_percent: Optional[Decimal],
    gst_enabled: bool,
    gst_rate_percent: Decimal,
    freight_agent_id: Optional[int],
    freight_charges: Optional[Decimal],
    packaging_charges: Optional[Decimal],
    additional_charges: Optional[list[dict]],
    transport_mode: Optional[str] = None,
    transport_receipt_number: Optional[str] = None,
    freight_charges_raw: object = None,
) -> dict:
    """Read-only: validate + compute totals for an edit-bill request. Shared by the real
    edit (which then persists) and the preview endpoint (which just returns this dict) so
    the two can never drift — the create-bill flow already has this create/preview split
    via compute_bill_totals; edit previously duplicated a simplified, wrong total in the
    frontend instead of reusing this math."""
    from app.services.pricing import effective_selling_price

    bill = db.get(CustomerBill, bill_id)
    if not bill:
        raise HTTPException(404, "bill not found")
    if bill.cancelled_at:
        raise HTTPException(400, "cannot edit — bill cancelled")
    customer_id = int(bill.customer_id)
    customer = db.get(Customer, customer_id)
    customer_name = customer.business_name if customer else f"Customer #{customer_id}"

    existing_lines = (
        db.query(CustomerBillLine)
        .filter(CustomerBillLine.bill_id == bill.id)
        .all()
    )
    if any(ln.status == "closed" for ln in existing_lines):
        raise HTTPException(400, "cannot edit — one or more lines are closed")

    old_by_cat = {int(ln.catalog_product_id): ln for ln in existing_lines if ln.status == "billed"}
    desired: dict[int, dict] = {}
    for raw in lines_in:
        qty = int(raw.get("quantity") or 0)
        if qty <= 0:
            continue
        cid = int(raw["catalog_product_id"])
        desired[cid] = {
            "quantity": qty,
            "discount_percent": raw.get("discount_percent"),
            "net_rate": raw.get("net_rate"),
        }
    if not desired:
        raise HTTPException(400, "bill must keep at least one product line")

    assert_discount_xor(overall_discount_percent, list(desired.values()))
    t, agent_name = _resolve_bill_transport(
        db,
        transport_mode=transport_mode,
        freight_agent_id=freight_agent_id,
        freight_charges=freight_charges_raw if freight_charges_raw is not None else freight_charges,
        transport_receipt_number=transport_receipt_number,
    )
    freight_agent_id = t["freight_agent_id"]
    freight_charges = t["freight_charges"]

    use_overall = overall_discount_percent is not None and overall_discount_percent > 0
    bill_items: list[dict] = []
    item_overrides: list[dict] = []
    for cid, meta in desired.items():
        qty = int(meta["quantity"])
        old = old_by_cat.get(cid)
        prod = db.get(CatalogProduct, cid)
        if not prod or not prod.is_active:
            raise HTTPException(400, f"product {cid} not found")
        unit_price = old.unit_price if old else effective_selling_price(prod.buying_price, prod.selling_price)
        if unit_price is None:
            raise HTTPException(400, f"sell price not set for {prod.our_product_id}")
        bill_items.append(
            {
                "catalog_product_id": cid,
                "our_product_id": prod.our_product_id,
                # Customer-facing doc — never show the vendor's own product code here.
                "name": prod.our_product_id,
                "quantity": qty,
                "unit_price": str(unit_price),
            }
        )
        if not use_overall:
            ov: dict = {"catalog_product_id": cid}
            if meta.get("net_rate") is not None and str(meta.get("net_rate")).strip() != "":
                ov["override_price"] = meta["net_rate"]
            if meta.get("discount_percent") is not None:
                ov["discount_percent"] = meta["discount_percent"]
            if "override_price" in ov or "discount_percent" in ov:
                item_overrides.append(ov)

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
    return {
        "bill": bill,
        "customer_id": customer_id,
        "customer_name": customer_name,
        "existing_lines": existing_lines,
        "old_by_cat": old_by_cat,
        "desired": desired,
        "use_overall": use_overall,
        "bill_items": bill_items,
        "item_overrides": item_overrides,
        "totals": totals,
        "freight_agent_id": freight_agent_id,
        "freight_charges": freight_charges,
        "transport": t,
    }

def preview_edit_customer_bill(
    db: Session,
    *,
    bill_id: int,
    lines_in: list[dict],
    overall_discount_percent: Optional[Decimal],
    gst_enabled: bool,
    gst_rate_percent: Decimal,
    freight_agent_id: Optional[int],
    freight_charges: Optional[Decimal],
    packaging_charges: Optional[Decimal],
    additional_charges: Optional[list[dict]],
    transport_mode: Optional[str] = None,
    transport_receipt_number: Optional[str] = None,
    freight_charges_raw: object = None,
) -> dict:
    """Read-only preview of what edit_customer_bill would save — same totals math, no
    writes. Lets the edit-bill review screen show the real server-computed grand total
    (incl. GST + additional charges) instead of a divergent client-side estimate."""
    prep = _prepare_edit_bill_totals(
        db,
        bill_id=bill_id,
        lines_in=lines_in,
        overall_discount_percent=overall_discount_percent,
        gst_enabled=gst_enabled,
        gst_rate_percent=gst_rate_percent,
        freight_agent_id=freight_agent_id,
        freight_charges=freight_charges,
        packaging_charges=packaging_charges,
        additional_charges=additional_charges,
        transport_mode=transport_mode,
        transport_receipt_number=transport_receipt_number,
        freight_charges_raw=freight_charges_raw,
    )
    return prep["totals"]

def edit_customer_bill(
    db: Session,
    *,
    bill_id: int,
    lines_in: list[dict],
    overall_discount_percent: Optional[Decimal],
    gst_enabled: bool,
    gst_rate_percent: Decimal,
    freight_agent_id: Optional[int],
    freight_charges: Optional[Decimal],
    packaging_charges: Optional[Decimal],
    additional_charges: Optional[list[dict]],
    narration: Optional[str],
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
    force_credit_override: bool = False,
    bill_number: str | None = None,
    transport_mode: Optional[str] = None,
    transport_receipt_number: Optional[str] = None,
    freight_charges_raw: object = None,
) -> CustomerBill:
    """Edit an existing bill (add/remove/change qty) and sync customer order qty."""
    prep = _prepare_edit_bill_totals(
        db,
        bill_id=bill_id,
        lines_in=lines_in,
        overall_discount_percent=overall_discount_percent,
        gst_enabled=gst_enabled,
        gst_rate_percent=gst_rate_percent,
        freight_agent_id=freight_agent_id,
        freight_charges=freight_charges,
        packaging_charges=packaging_charges,
        additional_charges=additional_charges,
        transport_mode=transport_mode,
        transport_receipt_number=transport_receipt_number,
        freight_charges_raw=freight_charges_raw,
    )
    bill = prep["bill"]
    customer_id = prep["customer_id"]
    customer_name = prep["customer_name"]
    existing_lines = prep["existing_lines"]
    old_by_cat = prep["old_by_cat"]
    desired = prep["desired"]
    use_overall = prep["use_overall"]
    bill_items = prep["bill_items"]
    totals = prep["totals"]
    freight_agent_id = prep["freight_agent_id"]
    freight_charges = prep["freight_charges"]
    t = prep["transport"]
    new_grand = Decimal(str(totals.get("rounded_grand_total") or totals["grand_total"]))
    old_grand = Decimal(str(bill.grand_total))
    pending_delta = new_grand - old_grand
    if pending_delta > 0:
        assert_credit_allows_bill(db, customer_id, pending_delta, force=force_credit_override)

    # Apply qty deltas → order sync
    all_cids = set(old_by_cat.keys()) | set(desired.keys())
    for cid in all_cids:
        old_qty = int(old_by_cat[cid].quantity_shipped) if cid in old_by_cat else 0
        new_qty = int(desired[cid]["quantity"]) if cid in desired else 0
        delta = new_qty - old_qty
        if delta == 0:
            continue
        unit_price = Decimal(str(
            next((x["unit_price"] for x in bill_items if int(x["catalog_product_id"]) == cid), "0")
            or (old_by_cat[cid].unit_price if cid in old_by_cat else 0)
        ))
        _apply_bill_qty_delta_to_order(
            db,
            customer_id=customer_id,
            catalog_product_id=cid,
            delta=delta,
            unit_price=unit_price,
            customer_name=customer_name,
            bill_placement_id=bill.placement_id,
        )

    # Rewrite bill lines
    for ln in existing_lines:
        db.delete(ln)
    db.flush()
    totals_by_sku = {bl.get("our_product_id"): bl for bl in (totals.get("lines") or []) if isinstance(bl, dict)}
    for item in bill_items:
        cid = int(item["catalog_product_id"])
        sku = item["our_product_id"]
        tline = totals_by_sku.get(sku) or {}
        disc = _line_disc_to_store(use_overall, overall_discount_percent, desired[cid], tline)
        db.add(
            CustomerBillLine(
                bill_id=bill.id,
                catalog_product_id=cid,
                our_product_id=sku,
                quantity_shipped=int(item["quantity"]),
                unit_price=Decimal(str(item["unit_price"])),
                line_total=Decimal(str(tline.get("line_total") or "0")),
                discount_percent=disc,
                status="billed",
            )
        )

    bill.narration = narration
    if bill_number:
        new_num = str(bill_number).strip()
        if new_num:
            clash = (
                db.query(CustomerBill)
                .filter(
                    CustomerBill.bill_number == new_num,
                    CustomerBill.id != bill.id,
                    CustomerBill.cancelled_at.is_(None),
                )
                .first()
            )
            if clash:
                raise HTTPException(400, f"bill number {new_num} already used on another open bill")
            bill.bill_number = new_num
    bill.gst_enabled = gst_enabled
    bill.gst_rate_percent = gst_rate_percent
    bill.discount_percent = overall_discount_percent if use_overall else None
    bill.packaging_charges = packaging_charges
    bill.additional_charges = additional_charges
    bill.transport_mode = t["transport_mode"]
    bill.transport_receipt_number = t["transport_receipt_number"]
    bill.subtotal_inclusive = Decimal(str(totals["subtotal_inclusive"]))
    bill.discount_amount = Decimal(str(totals.get("discount_amount") or "0"))
    bill.taxable_value = Decimal(str(totals.get("taxable_value") or "0"))
    bill.gst_amount = Decimal(str(totals.get("gst_amount") or "0"))
    bill.grand_total = new_grand
    bill.totals_json = totals
    bill.document_key = None  # regenerate PDF on next download
    _persist_totals_addons(db, bill)

    # Freight assignment: pending parcels can change agent; picked only amount sync.
    from app.services.freight_parcels import sync_bill_freight_on_edit

    sync_bill_freight_on_edit(
        db,
        bill=bill,
        freight_agent_id=freight_agent_id,
        freight_charges=freight_charges,
        customer_name=customer_name,
        actor_name=actor_name,
    )

    update_bill_ledger_amount(
        db,
        bill_id=bill.id,
        amount=new_grand,
        description=f"Bill {bill.bill_number} (edited) — ₹{new_grand}",
    )
    freeze_card(db, "customer_bill", bill)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    response_cache.invalidate("catalog:")
    return bill

