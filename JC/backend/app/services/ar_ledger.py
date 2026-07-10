from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.accounts_receivable import ArLedgerEntry, CustomerArAccount
from app.models.customer import Customer
from app.models.city import City


def _customer_label(db: Session, customer_id: int) -> str:
    c = db.get(Customer, customer_id)
    if not c:
        return f"Customer #{customer_id}"
    city_name = None
    if c.city_id:
        city = db.get(City, c.city_id)
        city_name = city.name if city else None
    return f"{c.business_name} — {city_name}" if city_name else c.business_name


def get_or_create_ar_account(db: Session, customer_id: int) -> CustomerArAccount:
    row = db.query(CustomerArAccount).filter(CustomerArAccount.customer_id == customer_id).first()
    if row:
        return row
    row = CustomerArAccount(customer_id=customer_id, is_open=True)
    db.add(row)
    db.flush()
    return row


def customer_ar_totals(db: Session, customer_id: int) -> dict[str, Decimal]:
    entries = db.query(ArLedgerEntry).filter(ArLedgerEntry.customer_id == customer_id).all()
    bill_total = Decimal("0")
    payment_total = Decimal("0")
    for e in entries:
        if e.entry_type == "bill":
            bill_total += e.amount
        elif e.entry_type == "payment":
            payment_total += e.amount
    outstanding = (bill_total - payment_total).quantize(Decimal("0.01"))
    return {
        "bill_total": bill_total.quantize(Decimal("0.01")),
        "payment_total": payment_total.quantize(Decimal("0.01")),
        "outstanding": outstanding,
    }


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
) -> ArLedgerEntry:
    get_or_create_ar_account(db, customer_id)
    entry = ArLedgerEntry(
        customer_id=customer_id,
        entry_type="bill",
        amount=amount.quantize(Decimal("0.01")),
        bill_id=bill_id,
        description=description,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(entry)
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
) -> ArLedgerEntry:
    get_or_create_ar_account(db, customer_id)
    entry = ArLedgerEntry(
        customer_id=customer_id,
        entry_type="payment",
        amount=amount.quantize(Decimal("0.01")),
        payment_ref=payment_ref,
        payment_comment=payment_comment,
        description=description,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(entry)
    db.flush()
    return entry


def build_ar_ledger(db: Session, customer_id: int) -> list[dict]:
    entries = (
        db.query(ArLedgerEntry)
        .filter(ArLedgerEntry.customer_id == customer_id)
        .order_by(ArLedgerEntry.created_at.asc(), ArLedgerEntry.id.asc())
        .all()
    )
    running = Decimal("0")
    out: list[dict] = []
    for e in entries:
        signed = e.amount if e.entry_type == "bill" else -e.amount
        running = (running + signed).quantize(Decimal("0.01"))
        out.append(
            {
                "id": e.id,
                "entry_type": e.entry_type,
                "amount": format(e.amount, "f"),
                "signed_amount": format(signed, "f"),
                "running_balance": format(running, "f"),
                "bill_id": e.bill_id,
                "payment_ref": e.payment_ref,
                "payment_comment": e.payment_comment,
                "description": e.description,
                "created_by_name": e.created_by_name,
                "created_at": e.created_at,
            }
        )
    return out


def list_ar_customers(db: Session) -> list[dict]:
    from sqlalchemy import func
    from app.models.customer import Customer as Cust

    rows = (
        db.query(ArLedgerEntry.customer_id, func.count(ArLedgerEntry.id))
        .group_by(ArLedgerEntry.customer_id)
        .all()
    )
    out = []
    for customer_id, txn_count in rows:
        totals = customer_ar_totals(db, int(customer_id))
        if totals["bill_total"] == 0 and totals["payment_total"] == 0:
            continue
        out.append(
            {
                "customer_id": int(customer_id),
                "customer_label": _customer_label(db, int(customer_id)),
                "outstanding": format(totals["outstanding"], "f"),
                "bill_total": format(totals["bill_total"], "f"),
                "payment_total": format(totals["payment_total"], "f"),
                "transaction_count": int(txn_count or 0),
            }
        )
    out.sort(key=lambda x: x["customer_label"].lower())
    return out
