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

from app.services.void_parts.common import _customer_label

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

    from app.services.addon_stock import deduct_addons_for_product

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
            from app.services.catalog_addons import kept_addon_ids_for_customer_product

            deduct_addons_for_product(
                db,
                catalog_product_id=ln.catalog_product_id,
                units=int(ln.quantity_returned),
                reference_type="customer_return",
                reference_id=ret.id,
                party=label,
                note="Return voided" + (f" — {reason_txt}" if reason_txt else ""),
                only_addon_ids=kept_addon_ids_for_customer_product(db, ret.customer_id, ln.catalog_product_id),
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

    from app.services.addon_stock import deduct_addons_for_product

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
            from app.services.catalog_addons import kept_addon_ids_for_customer_product

            deduct_addons_for_product(
                db,
                catalog_product_id=ln.catalog_product_id,
                units=-int(ln.quantity_returned),
                reference_type="customer_return",
                reference_id=ret.id,
                party=label,
                note="Return restored from recycle bin",
                only_addon_ids=kept_addon_ids_for_customer_product(db, ret.customer_id, ln.catalog_product_id),
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
