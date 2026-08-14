"""Freight agent ledger — same signed-amount convention as AR/AP.

entry_type:
  opening_balance (+) | charge (+) | settlement (−) | advance (−)

outstanding = Σ signed amount
  > 0 → amount due to agent
  < 0 → advance left with agent (prepaid credit)

balance_due on FreightAgent is a cache of outstanding (can be negative).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.freight_agent import FreightAgent, FreightLedgerEntry
from app.services.money import as_signed_decrease, as_signed_increase, mag
from app.services.storage import presigned_url


def agent_freight_totals(db: Session, agent_id: int) -> dict:
    rows = (
        db.query(FreightLedgerEntry)
        .filter(FreightLedgerEntry.freight_agent_id == agent_id)
        .all()
    )
    outstanding = sum((Decimal(str(r.amount)) for r in rows), Decimal("0")).quantize(Decimal("0.01"))
    opening = sum((r.amount for r in rows if r.entry_type == "opening_balance"), Decimal("0"))
    charges = sum((r.amount for r in rows if r.entry_type == "charge"), Decimal("0"))
    settlements = sum(
        (-r.amount for r in rows if r.entry_type in ("settlement", "advance")),
        Decimal("0"),
    )
    due = outstanding if outstanding > 0 else Decimal("0.00")
    advance_left = (-outstanding) if outstanding < 0 else Decimal("0.00")
    return {
        "outstanding": outstanding,
        "due": due.quantize(Decimal("0.01")),
        "advance_left": advance_left.quantize(Decimal("0.01")),
        "opening_total": opening.quantize(Decimal("0.01")),
        "charge_total": charges.quantize(Decimal("0.01")),
        "settlement_total": settlements.quantize(Decimal("0.01")),
        "transaction_count": len(rows),
    }


def recompute_balance_due(db: Session, agent_id: int) -> Decimal:
    totals = agent_freight_totals(db, agent_id)
    agent = db.get(FreightAgent, agent_id)
    if agent:
        agent.balance_due = totals["outstanding"]
    return totals["outstanding"]


def post_freight_charge(
    db: Session,
    *,
    agent_id: int,
    amount: Decimal,
    customer_bill_id: Optional[int],
    notes: Optional[str],
    actor_name: str,
) -> FreightLedgerEntry:
    entry = FreightLedgerEntry(
        freight_agent_id=agent_id,
        entry_type="charge",
        amount=as_signed_increase(amount),
        customer_bill_id=customer_bill_id,
        notes=notes,
        created_by_name=actor_name,
    )
    db.add(entry)
    db.flush()
    recompute_balance_due(db, agent_id)
    return entry


def post_freight_settlement(
    db: Session,
    *,
    agent_id: int,
    amount: Decimal,
    expense_id: Optional[int],
    transaction_ref: str,
    notes: Optional[str],
    actor_name: str,
    payment_receipt_key: Optional[str] = None,
    document_key: Optional[str] = None,
    entry_type: str = "settlement",
) -> FreightLedgerEntry:
    if entry_type not in ("settlement", "advance"):
        entry_type = "settlement"
    entry = FreightLedgerEntry(
        freight_agent_id=agent_id,
        entry_type=entry_type,
        amount=as_signed_decrease(amount),
        expense_id=expense_id,
        transaction_ref=transaction_ref,
        notes=notes,
        payment_receipt_key=payment_receipt_key,
        document_key=document_key,
        created_by_name=actor_name,
    )
    db.add(entry)
    db.flush()
    recompute_balance_due(db, agent_id)
    return entry


def post_freight_opening(
    db: Session,
    *,
    agent_id: int,
    amount: Decimal,
    notes: Optional[str],
    actor_name: str,
) -> Optional[FreightLedgerEntry]:
    """Upsert a single opening_balance row, then recompute."""
    existing = (
        db.query(FreightLedgerEntry)
        .filter(
            FreightLedgerEntry.freight_agent_id == agent_id,
            FreightLedgerEntry.entry_type == "opening_balance",
        )
        .all()
    )
    for row in existing:
        db.delete(row)
    db.flush()
    amt = mag(amount)
    if amt <= 0:
        recompute_balance_due(db, agent_id)
        return None
    entry = FreightLedgerEntry(
        freight_agent_id=agent_id,
        entry_type="opening_balance",
        amount=as_signed_increase(amt),
        notes=notes or "Opening balance",
        created_by_name=actor_name,
    )
    db.add(entry)
    db.flush()
    recompute_balance_due(db, agent_id)
    return entry


def build_freight_ledger(db: Session, agent_id: int) -> list[dict]:
    rows = (
        db.query(FreightLedgerEntry)
        .filter(FreightLedgerEntry.freight_agent_id == agent_id)
        .order_by(FreightLedgerEntry.created_at.asc(), FreightLedgerEntry.id.asc())
        .all()
    )
    bill_ids = [e.customer_bill_id for e in rows if e.customer_bill_id]
    bills: dict[int, CustomerBill] = {}
    customers: dict[int, Customer] = {}
    if bill_ids:
        for b in db.query(CustomerBill).filter(CustomerBill.id.in_(bill_ids)).all():
            bills[b.id] = b
        cust_ids = {b.customer_id for b in bills.values()}
        if cust_ids:
            for c in db.query(Customer).filter(Customer.id.in_(cust_ids)).all():
                customers[c.id] = c

    running = Decimal("0")
    out = []
    for e in rows:
        signed = Decimal(str(e.amount)).quantize(Decimal("0.01"))
        running = (running + signed).quantize(Decimal("0.01"))
        bill = bills.get(e.customer_bill_id) if e.customer_bill_id else None
        cust = customers.get(bill.customer_id) if bill else None
        party_label = None
        bill_number = None
        if cust:
            party_label = cust.business_name or cust.person_name or cust.alias
        if bill:
            bill_number = bill.bill_number
        out.append(
            {
                "id": e.id,
                "entry_type": e.entry_type,
                "amount": format(mag(e.amount), "f"),
                "signed_amount": format(signed, "f"),
                "running_balance": format(running, "f"),
                "customer_bill_id": e.customer_bill_id,
                "party_label": party_label,
                "bill_number": bill_number,
                "expense_id": e.expense_id,
                "transaction_ref": e.transaction_ref,
                "notes": e.notes,
                "payment_receipt_url": presigned_url(e.payment_receipt_key) if e.payment_receipt_key else None,
                "document_key": e.document_key,
                "has_document": bool(e.document_key),
                "created_by_name": e.created_by_name,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
        )
    out.reverse()
    return out


def open_freight_charges(db: Session, agent_id: int) -> list[dict]:
    """Charge rows for voucher context (newest first) with party names."""
    rows = (
        db.query(FreightLedgerEntry)
        .filter(
            FreightLedgerEntry.freight_agent_id == agent_id,
            FreightLedgerEntry.entry_type == "charge",
        )
        .order_by(FreightLedgerEntry.created_at.desc(), FreightLedgerEntry.id.desc())
        .limit(40)
        .all()
    )
    out = []
    for e in rows:
        party = None
        bill_number = None
        if e.customer_bill_id:
            bill = db.get(CustomerBill, e.customer_bill_id)
            if bill:
                bill_number = bill.bill_number
                cust = db.get(Customer, bill.customer_id)
                if cust:
                    party = cust.business_name or cust.person_name or cust.alias
        out.append(
            {
                "party_label": party or (e.notes or "Freight"),
                "bill_number": bill_number,
                "amount": format(mag(e.amount), "f"),
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
        )
    return out


def list_freight_agents_dues(db: Session) -> list[dict]:
    """Use cached balance_due for list speed; settle/charge paths recompute it."""
    agents = db.query(FreightAgent).order_by(FreightAgent.name.asc()).all()
    out = []
    for a in agents:
        outstanding = (a.balance_due or Decimal("0")).quantize(Decimal("0.01"))
        due = outstanding if outstanding > 0 else Decimal("0.00")
        advance_left = (-outstanding) if outstanding < 0 else Decimal("0.00")
        out.append(
            {
                "id": a.id,
                "name": a.name,
                "outstanding": format(outstanding, "f"),
                "balance_due": format(due, "f"),
                "advance_left": format(advance_left, "f"),
                "notes": a.notes,
                "transaction_count": 0,
            }
        )
    return out


def freight_dues_total(db: Session) -> dict:
    parties = [a for a in list_freight_agents_dues(db) if Decimal(a["balance_due"]) > 0]
    total = sum((Decimal(a["balance_due"]) for a in parties), Decimal("0")).quantize(Decimal("0.01"))
    return {"total": total, "count": len(parties), "parties": parties}


def reconcile_all_freight_balances(db: Session) -> int:
    """Recompute every agent's balance_due from ledger. Returns agents updated."""
    n = 0
    for a in db.query(FreightAgent).all():
        before = (a.balance_due or Decimal("0")).quantize(Decimal("0.01"))
        after = recompute_balance_due(db, a.id)
        if before != after:
            n += 1
    return n
