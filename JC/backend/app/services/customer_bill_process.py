from __future__ import annotations

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
from app.services.transport_mode import normalize_transport, stamp_transport_on_totals
from app.services.customer_order_flow import (
    _get_or_create_open_line,
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

    out = []
    for row in rows:
        out.append(
            {
                "open_line_id": row.id,
                "catalog_product_id": row.catalog_product_id,
                "our_product_id": row.our_product_id,
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
        freight_charges=freight_charges,
        packaging_charges=packaging_charges,
        item_overrides=item_overrides if not use_overall else None,
        additional_charges=additional_charges,
    )
    totals = stamp_transport_on_totals(totals, t, agent_name=agent_name)
    grand_check = Decimal(str(totals.get("rounded_grand_total") or totals["grand_total"]))
    assert_credit_allows_bill(db, customer_id, grand_check, force=force_credit_override)

    from app.services.biz_date import resolve_invoice_date

    bill_number = resolve_bill_number(db, bill_series_id, bill_number)
    entered_at = datetime.now(timezone.utc)
    invoice_day = resolve_invoice_date(bill_date)

    billed_order = get_or_create_customer_order(db, customer_id, "billed", "billed")
    placement = CustomerOrderPlacement(
        customer_order_id=billed_order.id,
        status="billed",
        placed_at=entered_at,
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
    addon_map = addon_snapshots_map(db, [int(x["catalog_product_id"]) for x in bill_items])
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
                addons_json=addon_map.get(cid) or None,
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

    # Freight dues post only when agent picks the parcel (Selling → Dispatch → Picked).
    # Bill still stores freight_agent_id + freight_charges for assignment.

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
        created_at=entered_at,
    )
    _persist_totals_addons(db, bill)
    billed_order.updated_at = entered_at
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


def _unapply_billed_from_received_lines(
    db: Session, customer_id: int, catalog_product_id: int, qty: int
) -> None:
    """Undo FIFO billed markers on received placements (newest billed first)."""
    remaining = qty
    received = (
        db.query(CustomerOrder)
        .filter(
            CustomerOrder.customer_id == customer_id,
            CustomerOrder.bucket == "received",
            CustomerOrder.is_open.is_(True),
        )
        .first()
    )
    if not received:
        return
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
            take = min(remaining, billed)
            ln.quantity_billed = billed - take
            remaining -= take


def cancel_customer_bill(
    db: Session,
    *,
    bill_id: int,
    reason: str,
    actor_name: str,
) -> CustomerBill:
    """Cancel a bill: AR cleared, freight cleared, qty returns to open (yet to bill).

    Stock stays reserved for the open order (portal flow). Offline sold stock is restored
    then re-reserved for open.
    """
    from app.models.stock import StockLedger
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
    if any(ln.status == "closed" for ln in lines):
        raise HTTPException(400, "cannot cancel — some lines already closed")

    for ln in lines:
        if ln.status != "billed":
            continue
        qty = int(ln.quantity_shipped or 0)
        if qty <= 0:
            ln.status = "closed"
            ln.close_reason = reason
            ln.closed_at = datetime.now(timezone.utc)
            continue

        # Offline bills sold stock at bill time — restore then keep reserved via open.
        sold = (
            db.query(StockLedger)
            .filter(
                StockLedger.reference_type == "customer_bill",
                StockLedger.reference_id == bill.id,
                StockLedger.catalog_product_id == ln.catalog_product_id,
                StockLedger.entry_type == "sold",
            )
            .first()
        )
        if sold:
            restore_stock(
                db,
                catalog_product_id=ln.catalog_product_id,
                our_product_id=ln.our_product_id,
                quantity=qty,
                reference_id=bill.id,
                party=customer_name,
                notes=f"Bill {bill.bill_number} cancelled",
            )
            reserve_stock(
                db,
                catalog_product_id=ln.catalog_product_id,
                our_product_id=ln.our_product_id,
                quantity=qty,
                reference_id=bill.placement_id or bill.id,
                party=customer_name,
            )

        open_row = (
            db.query(CustomerOpenLine)
            .filter(
                CustomerOpenLine.customer_id == bill.customer_id,
                CustomerOpenLine.catalog_product_id == ln.catalog_product_id,
            )
            .first()
        )
        if not open_row:
            open_row = _get_or_create_open_line(
                db, bill.customer_id, ln.catalog_product_id, ln.unit_price
            )
            open_row.quantity_received = qty
            open_row.quantity_open = qty
            open_row.quantity_billed = 0
        else:
            open_row.quantity_open = int(open_row.quantity_open or 0) + qty
            open_row.quantity_billed = max(0, int(open_row.quantity_billed or 0) - qty)
            open_row.quantity_received = max(
                int(open_row.quantity_received or 0),
                int(open_row.quantity_open) + int(open_row.quantity_billed or 0),
            )
        open_row.status = "open"
        _unapply_billed_from_received_lines(db, bill.customer_id, ln.catalog_product_id, qty)

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
                "name": prod.vendor_product_id or prod.our_product_id,
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
                "name": prod.vendor_product_id or prod.our_product_id,
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
    return bill
