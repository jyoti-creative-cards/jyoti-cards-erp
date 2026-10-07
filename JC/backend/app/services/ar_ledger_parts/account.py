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

def get_or_create_ar_account(db: Session, customer_id: int) -> CustomerArAccount:
    row = db.query(CustomerArAccount).filter(CustomerArAccount.customer_id == customer_id).first()
    if row:
        return row
    from sqlalchemy.exc import IntegrityError

    try:
        with db.begin_nested():
            row = CustomerArAccount(customer_id=customer_id, is_open=True)
            db.add(row)
            db.flush()
    except IntegrityError:
        # customer_id is unique — two concurrent first-ever bills/payments for the same
        # customer can both miss the SELECT above and both try to insert (same shape as
        # get_or_create_customer_order / add_stock's StockBalance race).
        row = db.query(CustomerArAccount).filter(CustomerArAccount.customer_id == customer_id).first()
        if not row:
            raise
    return row

def lock_ar_account(db: Session, customer_id: int) -> CustomerArAccount:
    """Row lock for settle / payment races."""
    row = (
        db.query(CustomerArAccount)
        .filter(CustomerArAccount.customer_id == customer_id)
        .with_for_update()
        .first()
    )
    if row:
        return row
    get_or_create_ar_account(db, customer_id)
    row = (
        db.query(CustomerArAccount)
        .filter(CustomerArAccount.customer_id == customer_id)
        .with_for_update()
        .first()
    )
    if not row:
        raise RuntimeError(f"AR account missing for customer {customer_id}")
    return row

def customer_ar_totals(db: Session, customer_id: int) -> dict[str, Decimal]:
    """Signed ledger: outstanding = Σ amount. Magnitudes for payment/credit display."""
    from sqlalchemy import case, func

    row = (
        db.query(
            func.coalesce(
                func.sum(case((ArLedgerEntry.entry_type == "opening_balance", ArLedgerEntry.amount), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((ArLedgerEntry.entry_type == "bill", ArLedgerEntry.amount), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((ArLedgerEntry.entry_type == "payment", func.abs(ArLedgerEntry.amount)), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((ArLedgerEntry.entry_type == "payment_reversal", func.abs(ArLedgerEntry.amount)), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((ArLedgerEntry.entry_type == "credit_note", func.abs(ArLedgerEntry.amount)), else_=0)),
                0,
            ),
            func.coalesce(func.sum(ArLedgerEntry.amount), 0),
        )
        .filter(ArLedgerEntry.customer_id == customer_id, ArLedgerEntry.deleted_at.is_(None))
        .one()
    )
    opening_total, bill_total, pay_mag, rev_mag, credit_total, outstanding = row
    return {
        "opening_total": Decimal(str(opening_total or 0)).quantize(Decimal("0.01")),
        "bill_total": Decimal(str(bill_total or 0)).quantize(Decimal("0.01")),
        "payment_total": (Decimal(str(pay_mag or 0)) - Decimal(str(rev_mag or 0))).quantize(Decimal("0.01")),
        "credit_total": Decimal(str(credit_total or 0)).quantize(Decimal("0.01")),
        "outstanding": Decimal(str(outstanding or 0)).quantize(Decimal("0.01")),
    }

def batch_customer_ar_totals(db: Session, customer_ids: list[int]) -> dict[int, dict[str, Decimal]]:
    """Same figures as customer_ar_totals, for many customers in one query."""
    if not customer_ids:
        return {}
    from sqlalchemy import case, func

    rows = (
        db.query(
            ArLedgerEntry.customer_id,
            func.coalesce(
                func.sum(case((ArLedgerEntry.entry_type == "opening_balance", ArLedgerEntry.amount), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((ArLedgerEntry.entry_type == "bill", ArLedgerEntry.amount), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((ArLedgerEntry.entry_type == "payment", func.abs(ArLedgerEntry.amount)), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((ArLedgerEntry.entry_type == "payment_reversal", func.abs(ArLedgerEntry.amount)), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((ArLedgerEntry.entry_type == "credit_note", func.abs(ArLedgerEntry.amount)), else_=0)),
                0,
            ),
            func.coalesce(func.sum(ArLedgerEntry.amount), 0),
        )
        .filter(ArLedgerEntry.customer_id.in_(customer_ids), ArLedgerEntry.deleted_at.is_(None))
        .group_by(ArLedgerEntry.customer_id)
        .all()
    )
    out: dict[int, dict[str, Decimal]] = {}
    for cid, opening_total, bill_total, pay_mag, rev_mag, credit_total, outstanding in rows:
        out[int(cid)] = {
            "opening_total": Decimal(str(opening_total or 0)).quantize(Decimal("0.01")),
            "bill_total": Decimal(str(bill_total or 0)).quantize(Decimal("0.01")),
            "payment_total": (Decimal(str(pay_mag or 0)) - Decimal(str(rev_mag or 0))).quantize(Decimal("0.01")),
            "credit_total": Decimal(str(credit_total or 0)).quantize(Decimal("0.01")),
            "outstanding": Decimal(str(outstanding or 0)).quantize(Decimal("0.01")),
        }
    return out


def batch_customer_outstanding(db: Session, customer_ids: list[int]) -> dict[int, Decimal]:
    """Return {customer_id: outstanding_balance} for multiple customers in one query."""
    if not customer_ids:
        return {}
    from sqlalchemy import func

    rows = (
        db.query(ArLedgerEntry.customer_id, func.sum(ArLedgerEntry.amount))
        .filter(ArLedgerEntry.customer_id.in_(customer_ids), ArLedgerEntry.deleted_at.is_(None))
        .group_by(ArLedgerEntry.customer_id)
        .all()
    )
    return {cid: Decimal(str(total or 0)).quantize(Decimal("0.01")) for cid, total in rows}

def get_opening_balance(db: Session, customer_id: int) -> Optional[ArLedgerEntry]:
    return (
        db.query(ArLedgerEntry)
        .filter(ArLedgerEntry.customer_id == customer_id, ArLedgerEntry.entry_type == "opening_balance")
        .order_by(ArLedgerEntry.id.desc())
        .first()
    )

def set_opening_balance(
    db: Session,
    *,
    customer_id: int,
    amount: Decimal,
    as_on: date,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
) -> Optional[ArLedgerEntry]:
    """Upsert single opening_balance AR entry. amount=0 removes it."""
    get_or_create_ar_account(db, customer_id)
    existing = (
        db.query(ArLedgerEntry)
        .filter(ArLedgerEntry.customer_id == customer_id, ArLedgerEntry.entry_type == "opening_balance")
        .all()
    )
    for row in existing:
        db.delete(row)
    db.flush()
    amt = amount.quantize(Decimal("0.01"))
    if amt == Decimal("0"):
        return None
    # Positive amt = customer owes us (debit); negative = we owe customer (credit)
    direction = "debit" if amt > 0 else "credit"
    entry = ArLedgerEntry(
        customer_id=customer_id,
        entry_type="opening_balance",
        amount=amt,
        description=f"Opening balance as on {as_on.isoformat()} [{direction} ₹{abs(amt)}]",
        value_date=as_on,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
        created_at=datetime(as_on.year, as_on.month, as_on.day, tzinfo=timezone.utc),
    )
    db.add(entry)
    db.flush()
    return entry
