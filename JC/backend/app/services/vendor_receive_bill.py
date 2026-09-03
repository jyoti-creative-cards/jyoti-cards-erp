"""Split vendor flow: receive goods (stock) then bill (AP) against unbilled received."""
from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.deps import AuthContext
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.stock import StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.schemas.stock import VendorBillIn, VendorReceiptCreate
from app.services.activity import log_from_auth
from app.services.ap_ledger import post_bill_entry
from app.services.debit_notes import create_debit_note
from app.services.open_lines import reduce_from_open
from app.services.stock_receipt import add_stock, get_open_order
from app.services.vendor_billing_math import (
    amount_deviation_debit_note,
    compute_bill_totals,
    line_value_deviation_debit_note,
)


def _vendor_label(db: Session, vendor: Vendor) -> str:
    city_name = None
    if vendor.city_id:
        city = db.get(City, vendor.city_id)
        city_name = city.name if city else None
    return f"{vendor.business_name} — {city_name}" if city_name else vendor.business_name


def receive_vendor_goods(
    db: Session,
    auth: AuthContext,
    body: VendorReceiptCreate,
    *,
    offline: bool = False,
) -> dict:
    """Stock in + received aggregate. No AP, no debit notes. Order receipt # required.

    offline=True: no placed order / open-line reduce — pick any vendor products.
    """
    stock_lines = [ln for ln in body.lines if int(ln.quantity_received or 0) > 0]
    if not stock_lines:
        raise HTTPException(400, "enter quantity received on at least one row")
    order_receipt_number = (getattr(body, "order_receipt_number", None) or "").strip()
    if not order_receipt_number:
        raise HTTPException(400, "order receipt number is required")

    vendor = db.get(Vendor, body.vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    label = _vendor_label(db, vendor)

    placed = None
    if not offline:
        placed = get_open_order(db, body.vendor_id, "placed")
        if not placed:
            raise HTTPException(400, "no open placed order for this vendor")

        from app.services.order_summary import pending_qty_by_product

        pending = pending_qty_by_product(db, body.vendor_id)
        for ln in stock_lines:
            pid = ln.catalog_product_id
            want = int(ln.quantity_received or 0)
            have = int(pending.get(pid, 0))
            if want > have:
                prod = db.get(CatalogProduct, pid)
                raise HTTPException(
                    400,
                    f"received qty for {prod.our_product_id if prod else pid} ({want}) exceeds pending ({have})",
                )

    from app.services.biz_date import resolve_biz_dt

    now = resolve_biz_dt(getattr(body, "received_on", None))

    note = (getattr(body, "notes", None) or "").strip() or None
    receipt = StockReceipt(
        # Same receive type so Received → Bill / edit paths stay unified
        receipt_type="vendor_receive",
        vendor_id=body.vendor_id,
        placed_order_id=placed.id if placed else None,
        billed_placement_id=None,
        received_placement_id=None,
        additional_charges=None,
        total_billed_amount=None,
        bill_number=None,
        order_receipt_number=order_receipt_number[:120],
        bill_file_key=body.bill_file_key,
        notes=note,
        received_by_type=auth.actor_type,
        received_by_id=auth.actor_id,
        received_by_name=auth.actor_name,
        received_at=now,
    )
    db.add(receipt)
    db.flush()

    line_summary = []
    total_actual_value = Decimal("0")
    for ln in stock_lines:
        prod = db.get(CatalogProduct, ln.catalog_product_id)
        if not prod or prod.vendor_id != body.vendor_id:
            raise HTTPException(400, f"invalid product {ln.catalog_product_id} for vendor")
        recv_qty = int(ln.quantity_received or 0)
        total_actual_value += prod.buying_price * recv_qty
        db.add(
            StockReceiptLine(
                receipt_id=receipt.id,
                catalog_product_id=prod.id,
                our_product_id=prod.our_product_id,
                quantity_received=recv_qty,
                quantity_billed=0,
                billed_amount=Decimal("0"),
                buying_price=prod.buying_price,
            )
        )
        add_stock(
            db,
            catalog_product_id=prod.id,
            our_product_id=prod.our_product_id,
            quantity=recv_qty,
            entry_type="received",
            reference_type="stock_receipt",
            reference_id=receipt.id,
            party=label,
            notes=note or ("Offline goods received" if offline else "Goods received"),
        )
        line_summary.append(f"{prod.our_product_id}+{recv_qty}")

    if not offline:
        reduce_from_open(
            db,
            body.vendor_id,
            [(ln.catalog_product_id, int(ln.quantity_received or 0)) for ln in stock_lines],
        )
        placed.updated_at = now

    bill_total, extra_cash = compute_bill_totals(
        total_actual_value=total_actual_value,
        billing_pct=vendor.billing_pct,
        additional_charge=vendor.additional_charge,
        discount_pct=vendor.discount_pct,
        gst_included=vendor.gst_included,
        gst_rate_pct=vendor.gst_rate_pct,
    )
    receipt.expected_bill_amount = bill_total
    receipt.expected_extra_cash = extra_cash if vendor.billing_pct < 100 else None
    receipt.bill_status = "pending_bill"

    log_from_auth(
        db,
        auth,
        action="offline_receive" if offline else "receive_goods",
        entity_type="stock_receipt",
        entity_id=receipt.id,
        entity_label=label,
        detail=", ".join(line_summary[:10]),
    )
    db.commit()
    return {
        "ok": True,
        "receipt_id": receipt.id,
        "vendor_id": body.vendor_id,
        "message": f"{'Offline receive' if offline else 'Received goods'} for {len(stock_lines)} product(s)",
        "document_url": None,
    }


def bill_receipt(db: Session, auth: AuthContext, receipt_id: int, body: VendorBillIn) -> dict:
    """Bill a single pending receipt in place. One-to-one: no cross-receipt aggregation."""
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "receipt not found")
    if receipt.deleted_at:
        raise HTTPException(400, "receipt is voided — restore it from the recycle bin first")
    if receipt.bill_status != "pending_bill":
        raise HTTPException(400, "receipt is not open for billing")

    vendor = db.get(Vendor, receipt.vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    label = _vendor_label(db, vendor)

    lines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt_id).all()
    billed_qty_in = {ln_in.catalog_product_id: ln_in.quantity_billed for ln_in in (body.lines or [])}
    billed_amt_in = {
        ln_in.catalog_product_id: ln_in.billed_amount
        for ln_in in (body.lines or []) if ln_in.billed_amount is not None
    }

    normalized: list[tuple[StockReceiptLine, int, Decimal]] = []
    for ln in lines:
        bq = billed_qty_in.get(ln.catalog_product_id)
        bq = int(bq) if bq is not None else int(ln.quantity_received or 0)
        if bq < 0:
            raise HTTPException(400, f"billed qty for {ln.our_product_id} cannot be negative")
        # Raw (pre-billing_pct) line value — defaults to qty x our catalog rate, but the
        # vendor's actual paper-bill rate/amount can override it per line.
        raw_amt = billed_amt_in.get(ln.catalog_product_id)
        raw_amt = raw_amt if raw_amt is not None else (ln.buying_price * bq)
        normalized.append((ln, bq, raw_amt))
    if not any(bq > 0 for _, bq, _ in normalized):
        raise HTTPException(400, "enter billed quantity on at least one row")

    # One-off billing % override for this bill only — never mutates the vendor
    # profile, so it can't affect any other (past or future) bill for this vendor.
    billing_pct = (
        Decimal(str(body.billing_pct_override)).quantize(Decimal("0.01"))
        if body.billing_pct_override is not None else vendor.billing_pct
    )
    if not (Decimal("0") < billing_pct <= Decimal("100")):
        raise HTTPException(400, "billing % override must be between 0 and 100")

    total_actual_value = sum((raw_amt for _, _, raw_amt in normalized), Decimal("0"))
    bill_total, extra_cash = compute_bill_totals(
        total_actual_value=total_actual_value,
        billing_pct=billing_pct, additional_charge=vendor.additional_charge,
        discount_pct=vendor.discount_pct, gst_included=vendor.gst_included, gst_rate_pct=vendor.gst_rate_pct,
    )
    entered_total = body.total_billed_amount.quantize(Decimal("0.01"))
    is_split = billing_pct < 100

    from app.services.biz_date import as_biz_date, resolve_biz_dt
    now = resolve_biz_dt(body.bill_date)

    for ln, bq, raw_amt in normalized:
        ln.quantity_billed = bq
        ln.billed_amount = (raw_amt * billing_pct / 100).quantize(Decimal("0.01"))

    receipt.bill_number = (body.bill_number or "").strip() or None
    receipt.bill_file_key = body.bill_file_key
    receipt.billing_pct_applied = billing_pct
    receipt.additional_charges = vendor.additional_charge.quantize(Decimal("0.01"))
    receipt.total_billed_amount = entered_total
    receipt.actual_ap_amount = (entered_total + extra_cash).quantize(Decimal("0.01")) if extra_cash > 0 else None
    if body.notes is not None:
        receipt.notes = (body.notes or "").strip() or None
    receipt.bill_status = "billed"
    receipt.billed_at = now

    bill_num_label = receipt.bill_number or str(receipt.id)
    post_bill_entry(
        db, vendor_id=receipt.vendor_id, receipt_id=receipt.id, amount=entered_total,
        description=f"Bill {bill_num_label} — ₹{entered_total}",
        actor_type=auth.actor_type, actor_id=auth.actor_id, actor_name=auth.actor_name,
        value_date=as_biz_date(now), created_at=now,
    )
    if is_split and extra_cash > 0:
        post_bill_entry(
            db, vendor_id=receipt.vendor_id, receipt_id=receipt.id, amount=extra_cash,
            description=f"Bill {bill_num_label} — extra cash (half-price balance) ₹{extra_cash}",
            actor_type=auth.actor_type, actor_id=auth.actor_id, actor_name=auth.actor_name,
            value_date=as_biz_date(now), created_at=now,
        )

    bill_product_ids = {ln.catalog_product_id for ln, _, _ in normalized}
    for dn_in in body.debit_notes or []:
        if dn_in.note_type == "item" and dn_in.catalog_product_id not in bill_product_ids:
            raise HTTPException(400, "debit note item must be from billed lines")
        create_debit_note(db, auth, vendor_id=receipt.vendor_id, receipt_id=receipt.id, body=dn_in, source="manual")

    log_from_auth(
        db, auth, action="bill_received", entity_type="stock_receipt", entity_id=receipt.id,
        entity_label=label, detail=f"billed {len(normalized)} line(s), total ₹{entered_total}",
    )
    db.commit()
    return {
        "ok": True, "receipt_id": receipt.id, "vendor_id": receipt.vendor_id,
        "message": f"Billed {len(normalized)} product(s)", "document_url": None,
    }


def preview_bill_deviations(
    db: Session, vendor: Vendor, lines: list[StockReceiptLine], billed_qty_by_pid: dict[int, int], entered_total: Decimal,
    products: dict[int, CatalogProduct] | None = None,
    billed_amount_by_pid: dict[int, Decimal] | None = None,
    billing_pct: Decimal | None = None,
) -> dict:
    """Returns expected totals + suggested (unsaved) debit notes for the bill-review UI.

    `billing_pct` — one-off override for this bill only (e.g. vendor is normally
    50% split but this particular invoice is 25%). Defaults to the vendor's
    profile setting; never mutates the vendor record.
    """
    products = products or {}
    billed_amount_by_pid = billed_amount_by_pid or {}
    billing_pct = billing_pct if billing_pct is not None else vendor.billing_pct
    suggestions = []
    total_actual_value = Decimal("0")
    for ln in lines:
        bq = billed_qty_by_pid.get(ln.catalog_product_id, int(ln.quantity_received or 0))
        raw_amt = billed_amount_by_pid.get(ln.catalog_product_id)
        raw_amt = raw_amt if raw_amt is not None else (ln.buying_price * bq)
        total_actual_value += raw_amt
        dn = line_value_deviation_debit_note(
            billed_amount=raw_amt, received_qty=int(ln.quantity_received or 0),
            buying_price=ln.buying_price, billing_pct=billing_pct,
        )
        if dn:
            prod = products.get(ln.catalog_product_id)
            expected_raw = Decimal(int(ln.quantity_received or 0)) * ln.buying_price
            if bq != int(ln.quantity_received or 0) and raw_amt == (ln.buying_price * bq):
                reason = f"billed qty {bq} vs received {ln.quantity_received}"
            elif raw_amt != expected_raw:
                reason = f"billed amount ₹{raw_amt} vs expected ₹{expected_raw} (qty {bq})"
            else:
                reason = f"billed {bq} vs received {ln.quantity_received}"
            suggestions.append({
                "note_type": "value", "direction": dn["direction"], "amount": str(abs(dn["amount"])),
                "catalog_product_id": ln.catalog_product_id, "our_product_id": ln.our_product_id,
                "vendor_product_id": prod.vendor_product_id if prod else None,
                "notes": f"Auto: {reason} for {ln.our_product_id}",
                "source": "auto",
            })
    bill_total, extra_cash = compute_bill_totals(
        total_actual_value=total_actual_value, billing_pct=billing_pct,
        additional_charge=vendor.additional_charge, discount_pct=vendor.discount_pct,
        gst_included=vendor.gst_included, gst_rate_pct=vendor.gst_rate_pct,
    )
    amt_dn = amount_deviation_debit_note(expected_bill_total=bill_total, entered_bill_total=entered_total)
    if amt_dn:
        suggestions.append({
            "note_type": "value", "direction": amt_dn["direction"], "amount": str(abs(amt_dn["amount"])),
            "catalog_product_id": None, "our_product_id": None, "vendor_product_id": None,
            "notes": f"Auto: entered total ₹{entered_total} vs expected ₹{bill_total}",
            "source": "auto",
        })
    return {
        "expected_bill_total": str(bill_total), "expected_extra_cash": str(extra_cash) if billing_pct < 100 else None,
        "suggested_debit_notes": suggestions,
    }
