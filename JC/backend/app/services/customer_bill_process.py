from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.freight_agent import FreightAgent, FreightLedgerEntry
from app.models.stock import StockBalance
from app.services.ar_ledger import post_bill_entry
from app.services.bill_series_alloc import allocate_bill_number
from app.services.catalog_addons import addon_snapshots_map
from app.services.customer_bill_math import compute_bill_totals
from app.services.customer_order_flow import get_or_create_customer_order, restore_stock
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

    out = []
    for row in rows:
        bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == row.catalog_product_id).first()
        qty_on_hand = bal.quantity_on_hand if bal else 0
        prod = db.get(CatalogProduct, row.catalog_product_id)
        out.append(
            {
                "open_line_id": row.id,
                "catalog_product_id": row.catalog_product_id,
                "our_product_id": row.our_product_id,
                "unit_price": format(row.unit_price, "f"),
                "quantity_placed": row.quantity_received,
                "quantity_open": row.quantity_open,
                "quantity_billed": row.quantity_billed,
                "quantity_on_hand": qty_on_hand,
            }
        )
    return {"lines": out, "default_narration": " · ".join(notes_parts)}


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
) -> CustomerBill:
    ship_lines = [ln for ln in lines_in if int(ln.get("quantity_to_ship") or 0) > 0]
    if not ship_lines:
        raise HTTPException(400, "enter quantity to ship on at least one line")

    open_map = {
        r.catalog_product_id: r
        for r in db.query(CustomerOpenLine)
        .filter(CustomerOpenLine.customer_id == customer_id, CustomerOpenLine.status == "open")
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
        prod = db.get(CatalogProduct, cid)
        bill_items.append(
            {
                "catalog_product_id": cid,
                "our_product_id": row.our_product_id,
                "name": prod.vendor_product_id if prod else row.our_product_id,
                "quantity": qty,
                "unit_price": str(row.unit_price),
            }
        )
        if not use_overall and ln.get("discount_percent") is not None:
            item_overrides.append({"catalog_product_id": cid, "discount_percent": ln["discount_percent"]})

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

    bill_number = allocate_bill_number(db, bill_series_id)
    now = datetime.now(timezone.utc)

    billed_order = get_or_create_customer_order(db, customer_id, "billed", "billed")
    placement = CustomerOrderPlacement(
        customer_order_id=billed_order.id,
        status="billed",
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
        freight_agent_id=freight_agent_id,
        freight_charges=freight_charges,
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
    )
    db.add(bill)
    db.flush()

    line_totals = {int(ln["catalog_product_id"]): ln for ln in ship_lines}
    for bl in totals.get("lines") or []:
        sku = bl.get("our_product_id")
        match = next((x for x in bill_items if x["our_product_id"] == sku), None)
        if not match:
            continue
        cid = int(match["catalog_product_id"])
        qty = int(match["quantity"])
        line_total = Decimal(str(bl.get("line_total") or "0"))
        disc = None
        if not use_overall:
            raw = line_totals.get(cid, {})
            if raw.get("discount_percent") is not None:
                disc = Decimal(str(raw["discount_percent"]))

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
                status="billed",
            )
        )
        open_row = open_map.get(cid)
        if open_row:
            open_row.quantity_open = max(0, open_row.quantity_open - qty)
            open_row.quantity_billed += qty
            if open_row.quantity_open <= 0:
                open_row.status = "open"

        _apply_billed_to_received_lines(db, customer_id, cid, qty)

    if freight_agent_id and freight_charges and freight_charges > 0:
        agent = db.get(FreightAgent, freight_agent_id)
        if agent:
            agent.balance_due = (agent.balance_due + freight_charges).quantize(Decimal("0.01"))
            db.add(
                FreightLedgerEntry(
                    freight_agent_id=agent.id,
                    entry_type="charge",
                    amount=freight_charges.quantize(Decimal("0.01")),
                    customer_bill_id=bill.id,
                    notes=f"Bill {bill_number}",
                    created_by_name=actor_name,
                )
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
    )
    addon_map = addon_snapshots_map(db, [int(x["catalog_product_id"]) for x in bill_items])
    if bill.totals_json and isinstance(bill.totals_json.get("lines"), list):
        enriched = []
        for bl in bill.totals_json["lines"]:
            if not isinstance(bl, dict):
                continue
            row = dict(bl)
            cid = int(row.get("catalog_product_id") or 0)
            if not cid:
                match = next((x for x in bill_items if x.get("our_product_id") == row.get("our_product_id")), None)
                cid = int(match["catalog_product_id"]) if match else 0
            if cid:
                row["catalog_product_id"] = cid
                if cid in addon_map:
                    row["addons"] = addon_map[cid]
            enriched.append(row)
        bill.totals_json = {**bill.totals_json, "lines": enriched}
    billed_order.updated_at = now
    return bill


def _apply_billed_to_received_lines(db: Session, customer_id: int, catalog_product_id: int, qty: int) -> None:
    remaining = qty
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
        .order_by(CustomerOrderPlacement.placed_at.asc())
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
            unbilled = ln.quantity - ln.quantity_billed
            if unbilled <= 0:
                continue
            take = min(remaining, unbilled)
            ln.quantity_billed += take
            remaining -= take


def cancel_open_line(db: Session, line_id: int, reason: str, customer_name: str) -> None:
    row = db.get(CustomerOpenLine, line_id)
    if not row or row.status != "open":
        raise HTTPException(404, "open line not found")
    qty = row.quantity_open
    if qty <= 0:
        raise HTTPException(400, "nothing to cancel")
    restore_stock(
        db,
        catalog_product_id=row.catalog_product_id,
        our_product_id=row.our_product_id,
        quantity=qty,
        reference_id=line_id,
        party=customer_name,
        notes=f"Cancelled open: {reason}",
    )
    row.quantity_open = 0
    row.quantity_received = max(row.quantity_billed, row.quantity_received - qty)
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
            unbilled = ln.quantity - ln.quantity_billed
            if unbilled <= 0:
                continue
            take = min(remaining, unbilled)
            ln.status = "cancelled"
            ln.cancel_reason = reason
            remaining -= take
            prod = db.get(CatalogProduct, catalog_product_id)
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


def close_bill_line(db: Session, bill_line_id: int, reason: str) -> None:
    row = db.get(CustomerBillLine, bill_line_id)
    if not row or row.status == "closed":
        raise HTTPException(404, "bill line not found or already closed")
    bill = db.get(CustomerBill, row.bill_id)
    if not bill:
        raise HTTPException(404, "bill not found")
    row.status = "closed"
    row.close_reason = reason
    row.closed_at = datetime.now(timezone.utc)
    closed_order = get_or_create_customer_order(db, bill.customer_id, "closed", "closed")
    placement = CustomerOrderPlacement(
        customer_order_id=closed_order.id,
        status="closed",
        cancel_reason=reason,
        placed_at=datetime.now(timezone.utc),
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
    closed_order.updated_at = datetime.now(timezone.utc)


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
        if prod.selling_price is None or prod.selling_price <= 0:
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
                "name": prod.vendor_product_id or prod.our_product_id,
                "quantity": qty,
                "unit_price": format(unit_price, "f"),
            }
        )
        if not use_overall and ln.get("discount_percent") is not None:
            item_overrides.append({"catalog_product_id": cid, "discount_percent": ln["discount_percent"]})

    totals = compute_bill_totals(
        bill_items,
        gst_enabled=gst_enabled,
        gst_rate_percent=gst_rate_percent,
        discount_percent=overall_discount_percent if use_overall else None,
        item_overrides=item_overrides if not use_overall else None,
        additional_charges=additional_charges,
    )

    bill_number = allocate_bill_number(db, bill_series_id)
    now = datetime.now(timezone.utc)

    billed_order = get_or_create_customer_order(db, customer_id, "billed", "billed")
    placement = CustomerOrderPlacement(
        customer_order_id=billed_order.id,
        status="billed",
        customer_notes=narration or "Offline order",
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
        if not use_overall:
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
        enriched = []
        for bl in bill.totals_json["lines"]:
            if not isinstance(bl, dict):
                continue
            row = dict(bl)
            cid = int(row.get("catalog_product_id") or 0)
            if not cid:
                match = next((x for x in bill_items if x.get("our_product_id") == row.get("our_product_id")), None)
                cid = int(match["catalog_product_id"]) if match else 0
            if cid and cid in addon_map:
                row["addons"] = addon_map[cid]
            enriched.append(row)
        bill.totals_json = {**bill.totals_json, "lines": enriched}

    post_bill_entry(
        db,
        customer_id=customer_id,
        bill_id=bill.id,
        amount=grand,
        description=f"Bill {bill_number} — ₹{grand}",
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
    )
    billed_order.updated_at = now
    return bill, placement
