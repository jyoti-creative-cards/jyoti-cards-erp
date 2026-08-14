"""Reverse / void AR & AP payments — never delete money rows."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.accounts_payable import ApLedgerEntry
from app.models.accounts_receivable import ArLedgerEntry
from app.services.money import mag


def _already_reversed_ar(db: Session, entry_id: int) -> bool:
    return (
        db.query(ArLedgerEntry.id)
        .filter(
            ArLedgerEntry.entry_type == "payment_reversal",
            ArLedgerEntry.reverses_entry_id == entry_id,
        )
        .first()
        is not None
    )


def _already_reversed_ap(db: Session, entry_id: int) -> bool:
    return (
        db.query(ApLedgerEntry.id)
        .filter(
            ApLedgerEntry.entry_type == "payment_reversal",
            ApLedgerEntry.reverses_entry_id == entry_id,
        )
        .first()
        is not None
    )


def reverse_ar_payment(
    db: Session,
    *,
    entry_id: int,
    reason: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
    void: bool = False,
) -> ArLedgerEntry:
    orig = db.get(ArLedgerEntry, entry_id)
    if not orig or orig.entry_type != "payment":
        raise HTTPException(404, "AR payment not found")
    if _already_reversed_ar(db, entry_id):
        raise HTTPException(400, "payment already reversed")
    amt = mag(orig.amount)
    if amt <= 0:
        raise HTTPException(400, "invalid payment amount")
    # Original payment is negative; reversal increases outstanding (+)
    action = "Void" if void else "Reverse"
    note = (reason or "").strip() or "no reason"
    entry = ArLedgerEntry(
        customer_id=orig.customer_id,
        entry_type="payment_reversal",
        amount=amt,
        payment_ref=orig.payment_ref,
        payment_comment=orig.payment_comment,
        description=f"{action} payment #{orig.id} (ref {orig.payment_ref or '—'}) — {note}"[:500],
        reverses_entry_id=orig.id,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(entry)
    db.flush()
    return entry


def reverse_ap_payment(
    db: Session,
    *,
    entry_id: int,
    reason: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
    void: bool = False,
) -> ApLedgerEntry:
    orig = db.get(ApLedgerEntry, entry_id)
    if not orig or orig.entry_type != "payment":
        raise HTTPException(404, "AP payment not found")
    if _already_reversed_ap(db, entry_id):
        raise HTTPException(400, "payment already reversed")
    amt = mag(orig.amount)
    if amt <= 0:
        raise HTTPException(400, "invalid payment amount")
    action = "Void" if void else "Reverse"
    note = (reason or "").strip() or "no reason"
    entry = ApLedgerEntry(
        vendor_id=orig.vendor_id,
        entry_type="payment_reversal",
        amount=amt,  # increase payable
        payment_ref=orig.payment_ref,
        payment_receipt_key=orig.payment_receipt_key,
        payment_comment=orig.payment_comment,
        description=f"{action} payment #{orig.id} (ref {orig.payment_ref or '—'}) — {note}"[:500],
        reverses_entry_id=orig.id,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(entry)
    db.flush()
    return entry
