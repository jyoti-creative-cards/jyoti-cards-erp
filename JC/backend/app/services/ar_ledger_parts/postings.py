from __future__ import annotations
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy.orm import Session
from app.models.accounts_receivable import ArLedgerEntry, CustomerArAccount
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.city import City
from app.services.money import as_signed_decrease, as_signed_increase, mag

from app.services.ar_ledger_parts.account import get_or_create_ar_account

def post_bill_entry(
    db: Session,
    *,
    customer_id: int,
    bill_id: int,
    amount: Decimal,
    description: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
    value_date: Optional[date] = None,
    created_at: Optional[datetime] = None,
) -> ArLedgerEntry:
    get_or_create_ar_account(db, customer_id)
    entry = ArLedgerEntry(
        customer_id=customer_id,
        entry_type="bill",
        amount=as_signed_increase(amount),
        bill_id=bill_id,
        description=description,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
        value_date=value_date,
    )
    if created_at is not None:
        entry.created_at = created_at
    db.add(entry)
    db.flush()
    return entry

def update_bill_ledger_amount(
    db: Session,
    *,
    bill_id: int,
    amount: Decimal,
    description: str,
) -> Optional[ArLedgerEntry]:
    """Rewrite the AR bill entry amount after a bill edit."""
    entry = (
        db.query(ArLedgerEntry)
        .filter(ArLedgerEntry.bill_id == bill_id, ArLedgerEntry.entry_type == "bill")
        .order_by(ArLedgerEntry.id.asc())
        .first()
    )
    if not entry:
        return None
    entry.amount = as_signed_increase(amount)
    entry.description = description
    db.flush()
    return entry

def post_payment_entry(
    db: Session,
    *,
    customer_id: int,
    amount: Decimal,
    payment_ref: str,
    payment_comment: Optional[str],
    description: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
    payment_mode: Optional[str] = None,
    value_date: Optional[date] = None,
) -> ArLedgerEntry:
    get_or_create_ar_account(db, customer_id)
    entry = ArLedgerEntry(
        customer_id=customer_id,
        entry_type="payment",
        amount=as_signed_decrease(amount),
        payment_ref=payment_ref,
        payment_mode=payment_mode,
        payment_comment=payment_comment,
        description=description,
        value_date=value_date,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(entry)
    db.flush()
    return entry

def post_credit_note_entry(
    db: Session,
    *,
    customer_id: int,
    return_id: int,
    amount: Decimal,
    description: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
) -> ArLedgerEntry:
    get_or_create_ar_account(db, customer_id)
    entry = ArLedgerEntry(
        customer_id=customer_id,
        entry_type="credit_note",
        amount=as_signed_decrease(amount),
        return_id=return_id,
        description=description,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(entry)
    db.flush()
    return entry
