from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.accounts_receivable import ArLedgerEntry, CustomerArAccount
from app.models.customer import Customer
from app.models.city import City
from app.services.money import as_signed_decrease, as_signed_increase, mag


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
        .filter(ArLedgerEntry.customer_id == customer_id)
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
    if amt <= 0:
        return None
    entry = ArLedgerEntry(
        customer_id=customer_id,
        entry_type="opening_balance",
        amount=as_signed_increase(amt),
        description=f"Opening balance (as on {as_on.isoformat()}) — ₹{amt}",
        value_date=as_on,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
        created_at=datetime(as_on.year, as_on.month, as_on.day, tzinfo=timezone.utc),
    )
    db.add(entry)
    db.flush()
    return entry


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
        signed = Decimal(str(e.amount)).quantize(Decimal("0.01"))
        running = (running + signed).quantize(Decimal("0.01"))
        out.append(
            {
                "id": e.id,
                "entry_type": e.entry_type,
                "amount": format(mag(e.amount), "f"),
                "signed_amount": format(signed, "f"),
                "running_balance": format(running, "f"),
                "bill_id": e.bill_id,
                "return_id": e.return_id,
                "payment_ref": e.payment_ref,
                "payment_mode": getattr(e, "payment_mode", None),
                "payment_comment": e.payment_comment,
                "description": e.description,
                "value_date": e.value_date.isoformat() if e.value_date else None,
                "reverses_entry_id": e.reverses_entry_id,
                "created_by_name": e.created_by_name or "",
                "created_at": e.created_at,
            }
        )
    return out


def list_ar_customers(db: Session) -> list[dict]:
    """One aggregate query + one customer/city join — no per-customer N+1.

    Signed convention: outstanding = Σ amount; payment/credit totals are magnitudes.
    """
    from sqlalchemy import case, func

    opening_sum = func.coalesce(
        func.sum(case((ArLedgerEntry.entry_type == "opening_balance", ArLedgerEntry.amount), else_=0)),
        0,
    )
    bill_sum = func.coalesce(
        func.sum(case((ArLedgerEntry.entry_type == "bill", ArLedgerEntry.amount), else_=0)),
        0,
    )
    # Payments negative; reversals positive — net then magnitude
    payment_sum = func.coalesce(
        func.sum(
            case(
                (ArLedgerEntry.entry_type.in_(("payment", "payment_reversal")), ArLedgerEntry.amount),
                else_=0,
            )
        ),
        0,
    )
    credit_sum = func.coalesce(
        func.sum(case((ArLedgerEntry.entry_type == "credit_note", ArLedgerEntry.amount), else_=0)),
        0,
    )
    outstanding_sum = func.coalesce(func.sum(ArLedgerEntry.amount), 0)
    agg_rows = (
        db.query(
            ArLedgerEntry.customer_id,
            func.count(ArLedgerEntry.id),
            opening_sum,
            bill_sum,
            payment_sum,
            credit_sum,
            outstanding_sum,
        )
        .group_by(ArLedgerEntry.customer_id)
        .all()
    )
    if not agg_rows:
        return []

    by_id = {
        int(cid): {
            "txn_count": int(txn or 0),
            "opening_total": Decimal(str(op or 0)).quantize(Decimal("0.01")),
            "bill_total": Decimal(str(bill or 0)).quantize(Decimal("0.01")),
            "payment_total": mag(pay),
            "credit_total": mag(cred),
            "outstanding": Decimal(str(out or 0)).quantize(Decimal("0.01")),
        }
        for cid, txn, op, bill, pay, cred, out in agg_rows
    }
    cust_ids = list(by_id.keys())
    customers = (
        db.query(Customer)
        .filter(Customer.id.in_(cust_ids), Customer.deleted_at.is_(None))
        .all()
    )
    city_ids = {c.city_id for c in customers if c.city_id}
    cities = {
        c.id: c.name
        for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
    }
    latest_opening: dict[int, ArLedgerEntry] = {}
    for e in (
        db.query(ArLedgerEntry)
        .filter(
            ArLedgerEntry.customer_id.in_(cust_ids),
            ArLedgerEntry.entry_type == "opening_balance",
        )
        .all()
    ):
        prev = latest_opening.get(e.customer_id)
        if prev is None or e.id > prev.id:
            latest_opening[e.customer_id] = e

    out = []
    for customer in customers:
        t = by_id.get(customer.id)
        if not t:
            continue
        outstanding = t["outstanding"]
        city_name = cities.get(customer.city_id) if customer.city_id else None
        label = f"{customer.business_name} — {city_name}" if city_name else customer.business_name
        opening = latest_opening.get(customer.id)
        out.append(
            {
                "customer_id": customer.id,
                "customer_label": label,
                "business_name": customer.business_name,
                "person_name": customer.person_name,
                "alias": customer.alias,
                "phone": customer.phone,
                "city_name": city_name,
                "outstanding": format(outstanding, "f"),
                "opening_total": format(t["opening_total"], "f"),
                "opening_as_on": opening.value_date.isoformat() if opening and opening.value_date else None,
                "bill_total": format(t["bill_total"], "f"),
                "payment_total": format(t["payment_total"], "f"),
                "credit_total": format(t["credit_total"], "f"),
                "transaction_count": t["txn_count"],
            }
        )
    out.sort(key=lambda x: x["customer_label"].lower())
    return out


def ar_dues_total(db: Session) -> dict:
    """Canonical Collect total — same number Home, Finance pulse, and Collect tab must show.

    One SQL join+group — outstanding > 0 only.
    """
    from sqlalchemy import text

    rows = db.execute(
        text(
            """
            SELECT c.id, c.business_name, ci.name AS city_name, SUM(e.amount) AS outstanding
            FROM jc_ar_ledger_entries e
            JOIN jc_customers c ON c.id = e.customer_id AND c.deleted_at IS NULL
            LEFT JOIN jc_cities ci ON ci.id = c.city_id
            GROUP BY c.id, c.business_name, ci.name
            HAVING SUM(e.amount) > 0
            ORDER BY SUM(e.amount) DESC
            """
        )
    ).all()
    due = [
        {
            "customer_id": int(r.id),
            "customer_label": f"{r.business_name} — {r.city_name}" if r.city_name else r.business_name,
            "outstanding": format(Decimal(str(r.outstanding or 0)).quantize(Decimal("0.01")), "f"),
        }
        for r in rows
    ]
    total = sum((Decimal(c["outstanding"]) for c in due), Decimal("0")).quantize(Decimal("0.01"))
    return {"total": total, "count": len(due), "parties": due}
