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

from app.services.ar_ledger_parts.labels import _doc_status

def build_ar_ledger(db: Session, customer_id: int) -> list[dict]:
    entries = (
        db.query(ArLedgerEntry)
        .filter(ArLedgerEntry.customer_id == customer_id, ArLedgerEntry.deleted_at.is_(None))
        .order_by(ArLedgerEntry.created_at.asc(), ArLedgerEntry.id.asc())
        .all()
    )
    customer = db.get(Customer, customer_id)
    party = customer.business_name if customer else f"Customer #{customer_id}"
    bill_ids = {e.bill_id for e in entries if e.entry_type == "bill" and e.bill_id}
    bills = {
        b.id: b for b in db.query(CustomerBill).filter(CustomerBill.id.in_(bill_ids)).all()
    } if bill_ids else {}
    running = Decimal("0")
    out: list[dict] = []
    for e in entries:
        signed = Decimal(str(e.amount)).quantize(Decimal("0.01"))
        running = (running + signed).quantize(Decimal("0.01"))
        party_name = None
        display_date = e.value_date or e.created_at
        display_name = e.payment_ref or e.description
        status = "open"
        if e.entry_type == "payment":
            party_name = party
            display_name = e.payment_ref or party or e.description
        elif e.entry_type == "bill" and e.bill_id:
            bill = bills.get(e.bill_id)
            if bill is not None:
                display_date = bill.bill_date or display_date
                display_name = f"Bill {bill.bill_number}" if bill.bill_number else f"Bill #{bill.id}"
                status = _doc_status(bill)
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
                "party_name": party_name,
                "display_date": display_date,
                "display_name": display_name,
                "status": status,
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
        .filter(ArLedgerEntry.deleted_at.is_(None))
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
            ArLedgerEntry.deleted_at.is_(None),
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
            WHERE e.deleted_at IS NULL
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
