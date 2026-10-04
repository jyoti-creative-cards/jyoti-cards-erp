"""Void / restore / purge for vendor receipts (incl. bills) and debit notes.

Append-only accounting, but "I entered this by mistake" needs an undo path:
  - void:    soft-delete (deleted_at) + reverse the stock effect with a real ledger entry.
             AP entries tied to the receipt/debit-note are excluded from all "active" queries
             the instant deleted_at is set (see ap_ledger.py / ledger.py / stock.py filters).
  - restore: clear deleted_at on the receipt/note and on the AP entries voided in the *same*
             action (matched by timestamp), and re-apply the stock effect.
  - purge:   permanent — hard-delete the row(s) and their AP entries. Requires void first.

Stock reversal always allowed to go negative (received qty may already be shipped out) —
this only corrects the running total, it never blocks.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.deps import AuthContext
from app.models.accounts_payable import ApLedgerEntry
from app.models.debit_note import DebitNote
from app.models.stock import StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.services.activity import log_from_auth
from app.services.open_lines import add_to_open, reduce_from_open
from app.services.stock_receipt import add_stock

from app.services.void_parts.common import _reapply_item_dn_stock, _reverse_item_dn_stock, _vendor_label

def void_receipt(db: Session, auth: AuthContext, receipt_id: int, reason: Optional[str]) -> dict:
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt or receipt.deleted_at:
        raise HTTPException(404, "receipt not found")
    label = _vendor_label(db, receipt.vendor_id)
    now = datetime.now(timezone.utc)
    reason_txt = (reason or "").strip() or None

    lines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt_id).all()
    for ln in lines:
        if ln.quantity_received:
            add_stock(
                db,
                catalog_product_id=ln.catalog_product_id,
                our_product_id=ln.our_product_id,
                quantity=-int(ln.quantity_received),
                entry_type="void_receipt",
                reference_type="stock_receipt",
                reference_id=receipt.id,
                party=label,
                notes="Receipt voided" + (f" — {reason_txt}" if reason_txt else ""),
            )

    # This receipt reduced the vendor's pending open-order lines when it was
    # created (see vendor_receive_bill.receive_vendor_goods) — voiding it means
    # those units were never actually received, so give the pending qty back.
    # placed_order_id is only ever set on that non-offline receive path.
    if receipt.placed_order_id is not None:
        add_to_open(
            db, receipt.vendor_id,
            [(ln.catalog_product_id, int(ln.quantity_received or 0)) for ln in lines],
        )

    ap_entries = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.receipt_id == receipt_id, ApLedgerEntry.deleted_at.is_(None))
        .all()
    )
    for e in ap_entries:
        e.deleted_at = now

    notes = (
        db.query(DebitNote)
        .filter(DebitNote.receipt_id == receipt_id, DebitNote.deleted_at.is_(None))
        .all()
    )
    for dn in notes:
        _reverse_item_dn_stock(db, dn, label, f"Receipt #{receipt.id} voided")
        dn.deleted_at = now
        dn.deleted_reason = reason_txt
        dn.deleted_by_name = auth.actor_name

    receipt.deleted_at = now
    receipt.deleted_reason = reason_txt
    receipt.deleted_by_name = auth.actor_name

    log_from_auth(
        db, auth, action="void", entity_type="stock_receipt", entity_id=receipt.id,
        entity_label=label,
        detail=f"{'bill' if receipt.bill_status == 'billed' else 'receipt'} voided"
        + (f" — {reason_txt}" if reason_txt else ""),
    )
    db.commit()
    return {"ok": True, "message": "Receipt voided — moved to recycle bin"}

def restore_receipt(db: Session, auth: AuthContext, receipt_id: int) -> dict:
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt or not receipt.deleted_at:
        raise HTTPException(404, "deleted receipt not found")
    label = _vendor_label(db, receipt.vendor_id)
    voided_at = receipt.deleted_at

    lines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt_id).all()
    for ln in lines:
        if ln.quantity_received:
            add_stock(
                db,
                catalog_product_id=ln.catalog_product_id,
                our_product_id=ln.our_product_id,
                quantity=int(ln.quantity_received),
                entry_type="restore_receipt",
                reference_type="stock_receipt",
                reference_id=receipt.id,
                party=label,
                notes="Receipt restored from recycle bin",
            )

    # Mirror of the void-time restore above — re-consume the pending open qty
    # this receipt originally satisfied.
    if receipt.placed_order_id is not None:
        reduce_from_open(
            db, receipt.vendor_id,
            [(ln.catalog_product_id, int(ln.quantity_received or 0)) for ln in lines],
        )

    (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.receipt_id == receipt_id, ApLedgerEntry.deleted_at == voided_at)
        .update({"deleted_at": None}, synchronize_session=False)
    )
    for dn in (
        db.query(DebitNote)
        .filter(DebitNote.receipt_id == receipt_id, DebitNote.deleted_at == voided_at)
        .all()
    ):
        _reapply_item_dn_stock(db, dn, label, f"Receipt #{receipt.id} restored")
        dn.deleted_at = None
        dn.deleted_reason = None
        dn.deleted_by_name = None

    receipt.deleted_at = None
    receipt.deleted_reason = None
    receipt.deleted_by_name = None

    log_from_auth(db, auth, action="restore", entity_type="stock_receipt", entity_id=receipt.id, entity_label=label)
    db.commit()
    return {"ok": True, "message": "Receipt restored"}

def purge_receipt(db: Session, auth: AuthContext, receipt_id: int) -> dict:
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt or not receipt.deleted_at:
        raise HTTPException(404, "deleted receipt not found — void it first")
    label = _vendor_label(db, receipt.vendor_id)

    db.query(ApLedgerEntry).filter(ApLedgerEntry.receipt_id == receipt_id).delete(synchronize_session=False)
    # DebitNote.receipt_id is ON DELETE RESTRICT — must clear before dropping the receipt.
    db.query(DebitNote).filter(DebitNote.receipt_id == receipt_id).delete(synchronize_session=False)

    log_from_auth(db, auth, action="purge", entity_type="stock_receipt", entity_id=receipt.id, entity_label=label)
    db.delete(receipt)  # cascades StockReceiptLine
    db.commit()
    return {"ok": True, "message": "Receipt permanently deleted"}

def void_debit_note(db: Session, auth: AuthContext, note_id: int, reason: Optional[str]) -> dict:
    note = db.get(DebitNote, note_id)
    if not note or note.deleted_at:
        raise HTTPException(404, "debit note not found")
    label = _vendor_label(db, note.vendor_id)
    now = datetime.now(timezone.utc)
    reason_txt = (reason or "").strip() or None

    entry = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.debit_note_id == note_id, ApLedgerEntry.deleted_at.is_(None))
        .first()
    )
    if entry:
        entry.deleted_at = now

    _reverse_item_dn_stock(db, note, label, "Debit note voided" + (f" — {reason_txt}" if reason_txt else ""))
    note.deleted_at = now
    note.deleted_reason = reason_txt
    note.deleted_by_name = auth.actor_name

    log_from_auth(
        db, auth, action="void", entity_type="debit_note", entity_id=note.id, entity_label=label,
        detail=f"₹{note.amount}" + (f" — {reason_txt}" if reason_txt else ""),
    )
    db.commit()
    return {"ok": True, "message": "Debit note voided — moved to recycle bin"}

def restore_debit_note(db: Session, auth: AuthContext, note_id: int) -> dict:
    note = db.get(DebitNote, note_id)
    if not note or not note.deleted_at:
        raise HTTPException(404, "deleted debit note not found")
    label = _vendor_label(db, note.vendor_id)
    voided_at = note.deleted_at

    entry = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.debit_note_id == note_id, ApLedgerEntry.deleted_at == voided_at)
        .first()
    )
    if entry:
        entry.deleted_at = None

    _reapply_item_dn_stock(db, note, label, "Debit note restored from recycle bin")
    note.deleted_at = None
    note.deleted_reason = None
    note.deleted_by_name = None

    log_from_auth(db, auth, action="restore", entity_type="debit_note", entity_id=note.id, entity_label=label)
    db.commit()
    return {"ok": True, "message": "Debit note restored"}

def purge_debit_note(db: Session, auth: AuthContext, note_id: int) -> dict:
    note = db.get(DebitNote, note_id)
    if not note or not note.deleted_at:
        raise HTTPException(404, "deleted debit note not found — void it first")
    label = _vendor_label(db, note.vendor_id)

    db.query(ApLedgerEntry).filter(ApLedgerEntry.debit_note_id == note_id).delete(synchronize_session=False)
    log_from_auth(db, auth, action="purge", entity_type="debit_note", entity_id=note.id, entity_label=label)
    db.delete(note)
    db.commit()
    return {"ok": True, "message": "Debit note permanently deleted"}
