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
from app.services.stock_receipt import add_stock


def _vendor_label(db: Session, vendor_id: int) -> str:
    from app.models.city import City

    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        return f"Vendor #{vendor_id}"
    city_name = None
    if vendor.city_id:
        city = db.get(City, vendor.city_id)
        city_name = city.name if city else None
    return f"{vendor.business_name} — {city_name}" if city_name else vendor.business_name


def _reverse_item_dn_stock(db: Session, dn: DebitNote, label: str, note: str) -> None:
    """Undo create_debit_note's stock effect for an item-type note (it applied -quantity)."""
    if dn.note_type == "item" and dn.catalog_product_id and dn.quantity:
        add_stock(
            db,
            catalog_product_id=int(dn.catalog_product_id),
            our_product_id=dn.our_product_id or "",
            quantity=int(dn.quantity),  # undo the -quantity applied at creation
            entry_type="void_debit_note",
            reference_type="debit_note",
            reference_id=dn.id,
            party=label,
            notes=note,
        )


def _reapply_item_dn_stock(db: Session, dn: DebitNote, label: str, note: str) -> None:
    """Re-apply create_debit_note's stock effect for an item-type note on restore."""
    if dn.note_type == "item" and dn.catalog_product_id and dn.quantity:
        add_stock(
            db,
            catalog_product_id=int(dn.catalog_product_id),
            our_product_id=dn.our_product_id or "",
            quantity=-int(dn.quantity),
            entry_type="restore_debit_note",
            reference_type="debit_note",
            reference_id=dn.id,
            party=label,
            notes=note,
        )


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


# ── Customer-side (Phase 2) ──────────────────────────────────────────────────
#
# Unlike vendor receipts, cancelling a customer bill/placement folds into a shared
# rolling balance (CustomerOpenLine, FIFO across placements) that isn't safely
# invertible once later orders/bills have touched the same customer+product.
# So here: void = cancel-if-not-already-cancelled + hide; restore = un-hide only
# (does NOT un-cancel). CustomerReturn has no such shared-balance risk, so it gets
# full symmetric void/restore like DebitNote (reverse stock, re-apply on restore).


def _customer_label(db: Session, customer_id: int) -> str:
    from app.models.city import City
    from app.models.customer import Customer

    customer = db.get(Customer, customer_id)
    if not customer:
        return f"Customer #{customer_id}"
    city_name = None
    if customer.city_id:
        city = db.get(City, customer.city_id)
        city_name = city.name if city else None
    return f"{customer.business_name} — {city_name}" if city_name else customer.business_name


def void_customer_bill(db: Session, auth: AuthContext, bill_id: int, reason: Optional[str]) -> dict:
    from app.models.accounts_receivable import ArLedgerEntry
    from app.models.customer_bill import CustomerBill
    from app.services.customer_bill_process import cancel_customer_bill

    bill = db.get(CustomerBill, bill_id)
    if not bill or bill.deleted_at:
        raise HTTPException(404, "bill not found")
    reason_txt = (reason or "").strip() or None

    if not bill.cancelled_at:
        cancel_customer_bill(db, bill_id=bill_id, reason=reason_txt or "voided", actor_name=auth.actor_name)

    now = datetime.now(timezone.utc)
    (
        db.query(ArLedgerEntry)
        .filter(ArLedgerEntry.bill_id == bill_id, ArLedgerEntry.deleted_at.is_(None))
        .update({"deleted_at": now}, synchronize_session=False)
    )
    bill.deleted_at = now
    bill.deleted_reason = reason_txt
    bill.deleted_by_name = auth.actor_name

    log_from_auth(
        db, auth, action="void", entity_type="customer_bill", entity_id=bill.id, entity_label=bill.bill_number,
        detail=(reason_txt or "voided"),
    )
    db.commit()
    return {"ok": True, "message": "Bill voided — moved to recycle bin"}


def restore_customer_bill(db: Session, auth: AuthContext, bill_id: int) -> dict:
    """Un-hide only — does not un-cancel. See module docstring."""
    from app.models.accounts_receivable import ArLedgerEntry
    from app.models.customer_bill import CustomerBill

    bill = db.get(CustomerBill, bill_id)
    if not bill or not bill.deleted_at:
        raise HTTPException(404, "deleted bill not found")
    voided_at = bill.deleted_at

    (
        db.query(ArLedgerEntry)
        .filter(ArLedgerEntry.bill_id == bill_id, ArLedgerEntry.deleted_at == voided_at)
        .update({"deleted_at": None}, synchronize_session=False)
    )
    bill.deleted_at = None
    bill.deleted_reason = None
    bill.deleted_by_name = None

    log_from_auth(db, auth, action="restore", entity_type="customer_bill", entity_id=bill.id, entity_label=bill.bill_number)
    db.commit()
    return {"ok": True, "message": "Bill restored" + (" — stays cancelled" if bill.cancelled_at else "")}


def purge_customer_bill(db: Session, auth: AuthContext, bill_id: int) -> dict:
    from app.models.accounts_receivable import ArLedgerEntry
    from app.models.customer_bill import CustomerBill
    from app.models.customer_return import CustomerReturnLine

    bill = db.get(CustomerBill, bill_id)
    if not bill or not bill.deleted_at:
        raise HTTPException(404, "deleted bill not found — void it first")
    ret_n = db.query(CustomerReturnLine).filter(CustomerReturnLine.bill_id == bill_id).count()
    if ret_n:
        raise HTTPException(400, f"bill has {ret_n} return line(s) against it — purge those returns first")

    db.query(ArLedgerEntry).filter(ArLedgerEntry.bill_id == bill_id).delete(synchronize_session=False)
    log_from_auth(db, auth, action="purge", entity_type="customer_bill", entity_id=bill.id, entity_label=bill.bill_number)
    db.delete(bill)  # cascades CustomerBillLine
    db.commit()
    return {"ok": True, "message": "Bill permanently deleted"}


def void_customer_placement(db: Session, auth: AuthContext, placement_id: int, reason: Optional[str]) -> dict:
    from app.models.customer_order import CustomerOrder, CustomerOrderPlacement
    from app.services.customer_order_flow import cancel_customer_placement

    placement = db.get(CustomerOrderPlacement, placement_id)
    if not placement or placement.deleted_at:
        raise HTTPException(404, "order not found")
    reason_txt = (reason or "").strip() or None
    order = db.get(CustomerOrder, placement.customer_order_id)
    label = _customer_label(db, order.customer_id) if order else f"Placement #{placement_id}"

    if placement.status == "received":
        try:
            cancel_customer_placement(db, placement_id=placement_id, reason=reason_txt or "voided", customer_name=label)
        except ValueError:
            pass  # nothing left to cancel (fully billed already) — just hide it

    now = datetime.now(timezone.utc)
    placement.deleted_at = now
    placement.deleted_reason = reason_txt
    placement.deleted_by_name = auth.actor_name

    log_from_auth(
        db, auth, action="void", entity_type="customer_placement", entity_id=placement.id, entity_label=label,
        detail=(reason_txt or "voided"),
    )
    db.commit()
    return {"ok": True, "message": "Order voided — moved to recycle bin"}


def restore_customer_placement(db: Session, auth: AuthContext, placement_id: int) -> dict:
    """Un-hide only — does not un-cancel. See module docstring."""
    from app.models.customer_order import CustomerOrderPlacement

    placement = db.get(CustomerOrderPlacement, placement_id)
    if not placement or not placement.deleted_at:
        raise HTTPException(404, "deleted order not found")
    placement.deleted_at = None
    placement.deleted_reason = None
    placement.deleted_by_name = None

    log_from_auth(db, auth, action="restore", entity_type="customer_placement", entity_id=placement.id, entity_label=f"Order #{placement.id}")
    db.commit()
    return {"ok": True, "message": "Order restored" + (" — stays cancelled" if placement.status == "cancelled" else "")}


def purge_customer_placement(db: Session, auth: AuthContext, placement_id: int) -> dict:
    from app.models.customer_order import CustomerOrderPlacement

    placement = db.get(CustomerOrderPlacement, placement_id)
    if not placement or not placement.deleted_at:
        raise HTTPException(404, "deleted order not found — void it first")

    log_from_auth(db, auth, action="purge", entity_type="customer_placement", entity_id=placement.id, entity_label=f"Order #{placement.id}")
    db.delete(placement)  # cascades CustomerOrderLine; bills referencing it are SET NULL
    db.commit()
    return {"ok": True, "message": "Order permanently deleted"}


def void_customer_return(db: Session, auth: AuthContext, return_id: int, reason: Optional[str]) -> dict:
    from app.models.accounts_receivable import ArLedgerEntry
    from app.models.customer_return import CustomerReturn, CustomerReturnLine

    ret = db.get(CustomerReturn, return_id)
    if not ret or ret.deleted_at:
        raise HTTPException(404, "return not found")
    label = _customer_label(db, ret.customer_id)
    now = datetime.now(timezone.utc)
    reason_txt = (reason or "").strip() or None

    lines = db.query(CustomerReturnLine).filter(CustomerReturnLine.return_id == return_id).all()
    for ln in lines:
        if ln.quantity_returned:
            add_stock(
                db,
                catalog_product_id=ln.catalog_product_id,
                our_product_id=ln.our_product_id,
                quantity=-int(ln.quantity_returned),
                entry_type="void_customer_return",
                reference_type="customer_return",
                reference_id=ret.id,
                party=label,
                notes="Return voided" + (f" — {reason_txt}" if reason_txt else ""),
            )

    (
        db.query(ArLedgerEntry)
        .filter(ArLedgerEntry.return_id == return_id, ArLedgerEntry.deleted_at.is_(None))
        .update({"deleted_at": now}, synchronize_session=False)
    )
    ret.deleted_at = now
    ret.deleted_reason = reason_txt
    ret.deleted_by_name = auth.actor_name

    log_from_auth(
        db, auth, action="void", entity_type="customer_return", entity_id=ret.id, entity_label=label,
        detail=f"₹{ret.credit_amount}" + (f" — {reason_txt}" if reason_txt else ""),
    )
    db.commit()
    return {"ok": True, "message": "Return voided — moved to recycle bin"}


def restore_customer_return(db: Session, auth: AuthContext, return_id: int) -> dict:
    from app.models.accounts_receivable import ArLedgerEntry
    from app.models.customer_return import CustomerReturn, CustomerReturnLine

    ret = db.get(CustomerReturn, return_id)
    if not ret or not ret.deleted_at:
        raise HTTPException(404, "deleted return not found")
    label = _customer_label(db, ret.customer_id)
    voided_at = ret.deleted_at

    lines = db.query(CustomerReturnLine).filter(CustomerReturnLine.return_id == return_id).all()
    for ln in lines:
        if ln.quantity_returned:
            add_stock(
                db,
                catalog_product_id=ln.catalog_product_id,
                our_product_id=ln.our_product_id,
                quantity=int(ln.quantity_returned),
                entry_type="restore_customer_return",
                reference_type="customer_return",
                reference_id=ret.id,
                party=label,
                notes="Return restored from recycle bin",
            )

    (
        db.query(ArLedgerEntry)
        .filter(ArLedgerEntry.return_id == return_id, ArLedgerEntry.deleted_at == voided_at)
        .update({"deleted_at": None}, synchronize_session=False)
    )
    ret.deleted_at = None
    ret.deleted_reason = None
    ret.deleted_by_name = None

    log_from_auth(db, auth, action="restore", entity_type="customer_return", entity_id=ret.id, entity_label=label)
    db.commit()
    return {"ok": True, "message": "Return restored"}


def purge_customer_return(db: Session, auth: AuthContext, return_id: int) -> dict:
    from app.models.accounts_receivable import ArLedgerEntry
    from app.models.customer_return import CustomerReturn

    ret = db.get(CustomerReturn, return_id)
    if not ret or not ret.deleted_at:
        raise HTTPException(404, "deleted return not found — void it first")
    label = _customer_label(db, ret.customer_id)

    db.query(ArLedgerEntry).filter(ArLedgerEntry.return_id == return_id).delete(synchronize_session=False)
    log_from_auth(db, auth, action="purge", entity_type="customer_return", entity_id=ret.id, entity_label=label)
    db.delete(ret)  # cascades CustomerReturnLine
    db.commit()
    return {"ok": True, "message": "Return permanently deleted"}
