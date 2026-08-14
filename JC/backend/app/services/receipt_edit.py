"""Edit vendor receive / bill receipts — stock, AP, open/unbilled, history."""
from __future__ import annotations

import json
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.deps import AuthContext
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.debit_note import DebitNote
from app.models.stock import StockBalance, StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.models.vendor_order import VendorOrderLine
from app.schemas.stock import VendorReceiptCreate
from app.services.activity import log_from_auth
from app.services.ap_ledger import receipt_bill_amount, sync_receipt_bill_ledger
from app.services.debit_notes import create_debit_note, reverse_debit_note_effects
from app.services.history import record_entity_history
from app.services.open_lines import add_to_open, reduce_from_open
from app.services.stock_receipt import add_stock
from app.services.storage import delete_keys
from app.services.vendor_receive_bill import reduce_unbilled_received


def _vendor_label(db: Session, vendor_id: int) -> str:
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        return f"Vendor #{vendor_id}"
    city_name = None
    if vendor.city_id:
        city = db.get(City, vendor.city_id)
        city_name = city.name if city else None
    return f"{vendor.business_name} — {city_name}" if city_name else vendor.business_name


def _receipt_snapshot(db: Session, receipt: StockReceipt) -> dict:
    lines = (
        db.query(StockReceiptLine)
        .filter(StockReceiptLine.receipt_id == receipt.id)
        .order_by(StockReceiptLine.id.asc())
        .all()
    )
    notes = db.query(DebitNote).filter(DebitNote.receipt_id == receipt.id).order_by(DebitNote.id.asc()).all()
    return {
        "receipt_type": receipt.receipt_type,
        "bill_number": receipt.bill_number,
        "order_receipt_number": receipt.order_receipt_number,
        "notes": receipt.notes,
        "total_billed_amount": format(receipt.total_billed_amount, "f") if receipt.total_billed_amount is not None else None,
        "additional_charges": format(receipt.additional_charges, "f") if receipt.additional_charges is not None else None,
        "bill_file_key": receipt.bill_file_key,
        "lines": [
            {
                "catalog_product_id": ln.catalog_product_id,
                "our_product_id": ln.our_product_id,
                "quantity_received": ln.quantity_received,
                "quantity_billed": ln.quantity_billed,
                "billed_amount": format(ln.billed_amount, "f"),
            }
            for ln in lines
        ],
        "debit_notes": [
            {
                "id": n.id,
                "note_type": n.note_type,
                "direction": n.direction,
                "catalog_product_id": n.catalog_product_id,
                "quantity": n.quantity,
                "amount": format(n.amount, "f"),
                "notes": n.notes,
            }
            for n in notes
        ],
    }


def _summary_from_snapshots(before: dict, after: dict) -> str:
    parts: list[str] = []
    for field in ("bill_number", "order_receipt_number", "total_billed_amount", "additional_charges", "bill_file_key", "notes"):
        if before.get(field) != after.get(field):
            parts.append(f"{field}: {before.get(field)} → {after.get(field)}")
    before_lines = {int(x["catalog_product_id"]): x for x in before.get("lines") or []}
    after_lines = {int(x["catalog_product_id"]): x for x in after.get("lines") or []}
    for pid in sorted(set(before_lines) | set(after_lines)):
        b, a = before_lines.get(pid), after_lines.get(pid)
        if b != a:
            label = (a or b or {}).get("our_product_id") or pid
            parts.append(
                f"line {label}: recv {(b or {}).get('quantity_received')}→{(a or {}).get('quantity_received')}, "
                f"billed {(b or {}).get('quantity_billed')}→{(a or {}).get('quantity_billed')}"
            )
    b_notes = before.get("debit_notes") or []
    a_notes = after.get("debit_notes") or []
    if json.dumps(b_notes, sort_keys=True, default=str) != json.dumps(a_notes, sort_keys=True, default=str):
        parts.append(f"debit_notes: {len(b_notes)} → {len(a_notes)} note(s)")
    return "; ".join(parts) if parts else "updated"


def _stock_delta(db: Session, receipt: StockReceipt, label: str, pid: int, delta: int, note: str) -> None:
    if delta == 0:
        return
    prod = db.get(CatalogProduct, pid)
    if not prod:
        raise HTTPException(400, f"invalid product {pid}")
    if delta < 0:
        bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == pid).first()
        on_hand = int(bal.quantity_on_hand or 0) if bal else 0
        if on_hand + delta < 0:
            raise HTTPException(
                400,
                f"cannot reduce qty for {prod.our_product_id}: stock would go negative",
            )
    add_stock(
        db,
        catalog_product_id=pid,
        our_product_id=prod.our_product_id,
        quantity=delta,
        entry_type="receipt_adjustment",
        reference_type="stock_receipt",
        reference_id=receipt.id,
        party=label,
        notes=note,
    )


def _replace_receipt_lines(db: Session, receipt: StockReceipt, lines: list, *, recv_field: bool) -> None:
    old = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).all()
    for ln in old:
        db.delete(ln)
    db.flush()
    for ln in lines:
        prod = db.get(CatalogProduct, ln.catalog_product_id)
        if not prod or prod.vendor_id != receipt.vendor_id:
            raise HTTPException(400, f"invalid product {ln.catalog_product_id} for vendor")
        recv = int(ln.quantity_received or 0) if recv_field else int(ln.quantity_received or ln.quantity_billed or 0)
        billed = int(ln.quantity_billed or 0)
        db.add(
            StockReceiptLine(
                receipt_id=receipt.id,
                catalog_product_id=prod.id,
                our_product_id=prod.our_product_id,
                quantity_received=recv,
                quantity_billed=billed,
                billed_amount=(ln.billed_amount or Decimal("0")).quantize(Decimal("0.01")),
                buying_price=prod.buying_price,
            )
        )


def _cleanup_s3(old_doc_key, old_bill_key, new_bill_key) -> None:
    to_delete = []
    if old_doc_key:
        to_delete.append(old_doc_key)
    if old_bill_key and old_bill_key != new_bill_key:
        to_delete.append(old_bill_key)
    if to_delete:
        try:
            delete_keys(to_delete)
        except Exception:
            pass


def _edit_receive(db: Session, auth: AuthContext, receipt: StockReceipt, body: VendorReceiptCreate) -> dict:
    """Edit goods-receive: stock ±, open ±, received placement lines. No AP."""
    stock_lines = [ln for ln in body.lines if int(ln.quantity_received or 0) > 0]
    if not stock_lines:
        raise HTTPException(400, "enter quantity received on at least one row")

    label = _vendor_label(db, receipt.vendor_id)
    before = _receipt_snapshot(db, receipt)
    old_lines = {
        ln.catalog_product_id: ln
        for ln in db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).all()
    }
    new_by_pid = {ln.catalog_product_id: ln for ln in stock_lines}

    # Received placement lines — preserve already-billed portion
    placement_lines = {}
    if receipt.received_placement_id:
        for vol in db.query(VendorOrderLine).filter(VendorOrderLine.placement_id == receipt.received_placement_id).all():
            placement_lines[vol.catalog_product_id] = vol

    for pid in set(old_lines) | set(new_by_pid) | set(placement_lines):
        old_recv = int(old_lines[pid].quantity_received or 0) if pid in old_lines else 0
        new_recv = int(new_by_pid[pid].quantity_received or 0) if pid in new_by_pid else 0
        vol = placement_lines.get(pid)
        already_billed = 0
        if vol:
            already_billed = max(0, int(vol.quantity or 0) - int(vol.quantity_remaining or 0))
            if already_billed == 0 and vol.quantity_billed:
                already_billed = int(vol.quantity_billed or 0)
        if new_recv < already_billed:
            prod = db.get(CatalogProduct, pid)
            raise HTTPException(
                400,
                f"cannot set received below already billed ({already_billed}) for "
                f"{prod.our_product_id if prod else pid} — edit the bill first",
            )
        _stock_delta(db, receipt, label, pid, new_recv - old_recv, f"Edit receive #{receipt.id}")

    # Open: restore old receive, apply new
    restore = [(pid, int(ln.quantity_received or 0)) for pid, ln in old_lines.items() if int(ln.quantity_received or 0) > 0]
    apply = [(ln.catalog_product_id, int(ln.quantity_received or 0)) for ln in stock_lines]
    if restore:
        add_to_open(db, receipt.vendor_id, restore)
    if apply:
        reduce_from_open(db, receipt.vendor_id, apply)

    _replace_receipt_lines(db, receipt, stock_lines, recv_field=True)

    if receipt.received_placement_id:
        for vol in list(placement_lines.values()):
            db.delete(vol)
        db.flush()
        for ln in stock_lines:
            prod = db.get(CatalogProduct, ln.catalog_product_id)
            if not prod:
                continue
            new_recv = int(ln.quantity_received or 0)
            old_vol = placement_lines.get(prod.id)
            already_billed = 0
            if old_vol:
                already_billed = max(0, int(old_vol.quantity or 0) - int(old_vol.quantity_remaining or 0))
                if already_billed == 0 and old_vol.quantity_billed:
                    already_billed = int(old_vol.quantity_billed or 0)
            already_billed = min(already_billed, new_recv)
            db.add(
                VendorOrderLine(
                    placement_id=receipt.received_placement_id,
                    catalog_product_id=prod.id,
                    our_product_id=prod.our_product_id,
                    quantity=new_recv,
                    quantity_remaining=new_recv - already_billed,
                    quantity_billed=already_billed,
                    billed_amount=Decimal("0"),
                    buying_price=prod.buying_price,
                )
            )

    old_bill_key = receipt.bill_file_key
    old_doc_key = receipt.receipt_document_key
    if body.bill_file_key is not None:
        receipt.bill_file_key = body.bill_file_key or None
    orn = (getattr(body, "order_receipt_number", None) or "").strip()
    if not orn:
        raise HTTPException(400, "order receipt number is required")
    receipt.order_receipt_number = orn[:120]
    if body.notes is not None:
        receipt.notes = (body.notes or "").strip() or None
    receipt.receipt_document_key = None

    after = _receipt_snapshot(db, receipt)
    summary = _summary_from_snapshots(before, after)
    record_entity_history(db, "stock_receipt", receipt.id, before, summary)
    log_from_auth(
        db, auth, action="update", entity_type="stock_receipt", entity_id=receipt.id,
        entity_label=label, detail=summary[:500],
    )
    _cleanup_s3(old_doc_key, old_bill_key, receipt.bill_file_key)
    db.commit()
    return {"ok": True, "receipt_id": receipt.id, "message": "Receive updated", "change_summary": summary}


def _edit_bill(db: Session, auth: AuthContext, receipt: StockReceipt, body: VendorReceiptCreate) -> dict:
    """Edit bill against received: AP + DN + billed lines + unbilled received. No stock."""
    normalized = []
    for ln in body.lines:
        bq = int(ln.quantity_billed or 0)
        if bq <= 0:
            bq = int(ln.quantity_received or 0)
        if bq > 0:
            normalized.append((ln, bq))
    if not normalized:
        raise HTTPException(400, "enter billed quantity on at least one row")
    line_bill_total = sum((ln.billed_amount or Decimal("0")) for ln, _ in normalized)
    if body.total_billed_amount is None and line_bill_total <= 0:
        raise HTTPException(400, "enter total bill amount for this shipment")

    label = _vendor_label(db, receipt.vendor_id)
    before = _receipt_snapshot(db, receipt)
    old_lines = {
        ln.catalog_product_id: ln
        for ln in db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).all()
    }

    # Restore unbilled received from old billed qty, then apply new
    restore = [
        (pid, int(ln.quantity_billed or ln.quantity_received or 0))
        for pid, ln in old_lines.items()
        if int(ln.quantity_billed or ln.quantity_received or 0) > 0
    ]
    if restore:
        # add back to quantity_remaining on received lines (reverse of reduce)
        from app.services.stock_receipt import get_open_order
        from app.models.vendor_order import VendorOrderPlacement

        received = get_open_order(db, receipt.vendor_id, "received")
        if received:
            for catalog_product_id, qty in restore:
                left = int(qty or 0)
                if left <= 0:
                    continue
                order_lines = (
                    db.query(VendorOrderLine)
                    .join(VendorOrderPlacement, VendorOrderLine.placement_id == VendorOrderPlacement.id)
                    .filter(
                        VendorOrderPlacement.vendor_order_id == received.id,
                        VendorOrderPlacement.status == "received",
                        VendorOrderLine.catalog_product_id == catalog_product_id,
                    )
                    .order_by(VendorOrderPlacement.placed_at.desc(), VendorOrderLine.id.desc())
                    .all()
                )
                for ol in order_lines:
                    if left <= 0:
                        break
                    billed = int(ol.quantity_billed or 0)
                    take = min(billed, left) if billed > 0 else min(
                        max(0, int(ol.quantity or 0) - int(ol.quantity_remaining or 0)), left
                    )
                    if take <= 0:
                        # if no billed marker, put back up to quantity - remaining room
                        room = max(0, int(ol.quantity or 0) - int(ol.quantity_remaining or 0))
                        take = min(room, left)
                    if take <= 0:
                        continue
                    ol.quantity_remaining = int(ol.quantity_remaining or 0) + take
                    ol.quantity_billed = max(0, int(ol.quantity_billed or 0) - take)
                    left -= take
                if left > 0:
                    prod = db.get(CatalogProduct, catalog_product_id)
                    raise HTTPException(
                        400,
                        f"cannot restore unbilled received for "
                        f"{prod.our_product_id if prod else catalog_product_id} — short by {left}",
                    )

    apply = [(ln.catalog_product_id, bq) for ln, bq in normalized]
    # Validate against restored pool then reduce
    from app.services.vendor_receive_bill import unbilled_received_qty_by_product

    unbilled = unbilled_received_qty_by_product(db, receipt.vendor_id)
    for ln, bq in normalized:
        have = int(unbilled.get(ln.catalog_product_id, 0))
        if bq > have:
            prod = db.get(CatalogProduct, ln.catalog_product_id)
            raise HTTPException(
                400,
                f"billed qty for {prod.our_product_id if prod else ln.catalog_product_id} ({bq}) "
                f"exceeds unbilled received ({have})",
            )
    reduce_unbilled_received(db, receipt.vendor_id, apply)

    # No stock change for vendor_bill
    bill_body_lines = []
    for ln, bq in normalized:
        # reuse schema objects with billed qty
        ln.quantity_billed = bq
        ln.quantity_received = bq
        bill_body_lines.append(ln)
    _replace_receipt_lines(db, receipt, bill_body_lines, recv_field=False)

    if receipt.billed_placement_id:
        old_vol = (
            db.query(VendorOrderLine)
            .filter(VendorOrderLine.placement_id == receipt.billed_placement_id)
            .all()
        )
        for vol in old_vol:
            db.delete(vol)
        db.flush()
        for ln, bq in normalized:
            prod = db.get(CatalogProduct, ln.catalog_product_id)
            if not prod:
                continue
            db.add(
                VendorOrderLine(
                    placement_id=receipt.billed_placement_id,
                    catalog_product_id=prod.id,
                    our_product_id=prod.our_product_id,
                    quantity=bq,
                    quantity_remaining=bq,
                    quantity_billed=bq,
                    billed_amount=(ln.billed_amount or Decimal("0")).quantize(Decimal("0.01")),
                    buying_price=prod.buying_price,
                )
            )

    old_bill_key = receipt.bill_file_key
    old_doc_key = receipt.receipt_document_key
    receipt.bill_number = (body.bill_number or "").strip() or None
    receipt.additional_charges = (
        body.additional_charges.quantize(Decimal("0.01")) if body.additional_charges is not None else None
    )
    receipt.total_billed_amount = (
        body.total_billed_amount.quantize(Decimal("0.01")) if body.total_billed_amount is not None else None
    )
    if body.bill_file_key is not None:
        receipt.bill_file_key = body.bill_file_key or None
    if body.notes is not None:
        receipt.notes = (body.notes or "").strip() or None
    receipt.receipt_document_key = None

    old_notes = db.query(DebitNote).filter(DebitNote.receipt_id == receipt.id).all()
    for n in old_notes:
        reverse_debit_note_effects(db, auth, n, reason=f"receipt edit #{receipt.id}")
        db.delete(n)
    db.flush()

    bill_product_ids = {ln.catalog_product_id for ln, _ in normalized}
    for dn_in in body.debit_notes or []:
        if dn_in.note_type == "item" and dn_in.catalog_product_id not in bill_product_ids:
            raise HTTPException(400, "debit note item must be from billed lines")
        create_debit_note(db, auth, vendor_id=receipt.vendor_id, receipt_id=receipt.id, body=dn_in)

    bill_total = receipt_bill_amount(db, receipt.id)
    sync_receipt_bill_ledger(
        db,
        vendor_id=receipt.vendor_id,
        receipt_id=receipt.id,
        bill_total=bill_total,
        bill_label=str(receipt.bill_number or receipt.id),
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        actor_name=auth.actor_name,
    )

    after = _receipt_snapshot(db, receipt)
    summary = _summary_from_snapshots(before, after)
    record_entity_history(db, "stock_receipt", receipt.id, before, summary)
    log_from_auth(
        db, auth, action="update", entity_type="stock_receipt", entity_id=receipt.id,
        entity_label=label, detail=summary[:500],
    )
    _cleanup_s3(old_doc_key, old_bill_key, receipt.bill_file_key)
    db.commit()
    return {"ok": True, "receipt_id": receipt.id, "message": "Bill updated", "change_summary": summary}


def _edit_combined(db: Session, auth: AuthContext, receipt: StockReceipt, body: VendorReceiptCreate) -> dict:
    """Legacy vendor_order / offline_vendor: stock + open + AP together."""
    bill_lines = [ln for ln in body.lines if ln.quantity_received > 0 or (ln.quantity_billed or 0) > 0]
    if not bill_lines:
        raise HTTPException(400, "enter quantity received or billed on at least one row")
    line_bill_total = sum((ln.billed_amount or Decimal("0")) for ln in bill_lines)
    if body.total_billed_amount is None and line_bill_total <= 0:
        raise HTTPException(400, "enter total bill amount for this shipment")

    offline = receipt.receipt_type == "offline_vendor"
    label = _vendor_label(db, receipt.vendor_id)
    before = _receipt_snapshot(db, receipt)
    old_lines = {
        ln.catalog_product_id: ln
        for ln in db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).all()
    }
    new_by_pid = {ln.catalog_product_id: ln for ln in bill_lines}

    for pid in set(old_lines) | set(new_by_pid):
        old_recv = int(old_lines[pid].quantity_received or 0) if pid in old_lines else 0
        new_recv = int(new_by_pid[pid].quantity_received or 0) if pid in new_by_pid else 0
        _stock_delta(
            db, receipt, label, pid, new_recv - old_recv,
            f"Edit bill {body.bill_number or receipt.bill_number or receipt.id}",
        )

    if not offline:
        restore = [(pid, int(ln.quantity_received or 0)) for pid, ln in old_lines.items() if int(ln.quantity_received or 0) > 0]
        apply = [(ln.catalog_product_id, int(ln.quantity_received or 0)) for ln in bill_lines if int(ln.quantity_received or 0) > 0]
        if restore:
            add_to_open(db, receipt.vendor_id, restore)
        if apply:
            reduce_from_open(db, receipt.vendor_id, apply)

    _replace_receipt_lines(db, receipt, bill_lines, recv_field=True)

    if receipt.billed_placement_id:
        old_vol = (
            db.query(VendorOrderLine)
            .filter(VendorOrderLine.placement_id == receipt.billed_placement_id)
            .all()
        )
        for vol in old_vol:
            db.delete(vol)
        db.flush()
        for ln in bill_lines:
            recv_qty = int(ln.quantity_received or 0)
            if recv_qty <= 0:
                continue
            prod = db.get(CatalogProduct, ln.catalog_product_id)
            if not prod:
                continue
            db.add(
                VendorOrderLine(
                    placement_id=receipt.billed_placement_id,
                    catalog_product_id=prod.id,
                    our_product_id=prod.our_product_id,
                    quantity=recv_qty,
                    quantity_remaining=recv_qty,
                    quantity_billed=int(ln.quantity_billed or 0),
                    billed_amount=(ln.billed_amount or Decimal("0")).quantize(Decimal("0.01")),
                    buying_price=prod.buying_price,
                )
            )

    old_bill_key = receipt.bill_file_key
    old_doc_key = receipt.receipt_document_key
    receipt.bill_number = (body.bill_number or "").strip() or None
    receipt.additional_charges = (
        body.additional_charges.quantize(Decimal("0.01")) if body.additional_charges is not None else None
    )
    receipt.total_billed_amount = (
        body.total_billed_amount.quantize(Decimal("0.01")) if body.total_billed_amount is not None else None
    )
    if body.bill_file_key is not None:
        receipt.bill_file_key = body.bill_file_key or None
    if body.notes is not None:
        receipt.notes = (body.notes or "").strip() or None
    receipt.receipt_document_key = None

    old_notes = db.query(DebitNote).filter(DebitNote.receipt_id == receipt.id).all()
    for n in old_notes:
        reverse_debit_note_effects(db, auth, n, reason=f"receipt edit #{receipt.id}")
        db.delete(n)
    db.flush()

    bill_product_ids = {ln.catalog_product_id for ln in bill_lines}
    for dn_in in body.debit_notes or []:
        if dn_in.note_type == "item" and dn_in.catalog_product_id not in bill_product_ids:
            raise HTTPException(400, "debit note item must be from billed or received lines")
        create_debit_note(db, auth, vendor_id=receipt.vendor_id, receipt_id=receipt.id, body=dn_in)

    bill_total = receipt_bill_amount(db, receipt.id)
    sync_receipt_bill_ledger(
        db,
        vendor_id=receipt.vendor_id,
        receipt_id=receipt.id,
        bill_total=bill_total,
        bill_label=str(receipt.bill_number or receipt.id),
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        actor_name=auth.actor_name,
    )

    after = _receipt_snapshot(db, receipt)
    summary = _summary_from_snapshots(before, after)
    record_entity_history(db, "stock_receipt", receipt.id, before, summary)
    log_from_auth(
        db, auth, action="update", entity_type="stock_receipt", entity_id=receipt.id,
        entity_label=label, detail=summary[:500],
    )
    _cleanup_s3(old_doc_key, old_bill_key, receipt.bill_file_key)
    db.commit()
    return {"ok": True, "receipt_id": receipt.id, "message": "Bill updated", "change_summary": summary}


def update_vendor_receipt(
    db: Session,
    auth: AuthContext,
    receipt_id: int,
    body: VendorReceiptCreate,
) -> dict:
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "receipt not found")
    if body.vendor_id != receipt.vendor_id:
        raise HTTPException(400, "cannot change vendor on an existing bill")

    rtype = receipt.receipt_type or "vendor_order"
    if rtype == "vendor_receive":
        return _edit_receive(db, auth, receipt, body)
    if rtype == "vendor_bill":
        return _edit_bill(db, auth, receipt, body)
    return _edit_combined(db, auth, receipt, body)
