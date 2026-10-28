"""Commission-agent money. The party keeps the order. The agent owes the bill."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.commission_agent import CommissionAgent, CommissionLedgerEntry
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.services.ar_ledger import post_bill_entry, update_bill_ledger_amount
from app.services.money import as_signed_decrease, as_signed_increase, mag


def live_agent_id(db: Session, customer: Customer | None) -> Optional[int]:
    if customer is None or not customer.commission_agent_id:
        return None
    agent = db.get(CommissionAgent, customer.commission_agent_id)
    if not agent or agent.deleted_at or not agent.is_active:
        return None
    return agent.id


def agent_outstanding(db: Session, agent_id: int) -> Decimal:
    total = (
        db.query(func.coalesce(func.sum(CommissionLedgerEntry.amount), 0))
        .filter(CommissionLedgerEntry.commission_agent_id == agent_id)
        .scalar()
    )
    return Decimal(str(total or 0)).quantize(Decimal("0.01"))


def post_customer_bill_due(
    db: Session,
    *,
    bill: CustomerBill,
    customer: Customer | None,
    amount: Decimal,
    description: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
    value_date: Optional[date] = None,
    created_at: Optional[datetime] = None,
    on_agent: Optional[bool] = None,
):
    """New bills follow the party's agent unless this bill is a direct party order."""
    agent_id = live_agent_id(db, customer)
    if on_agent is False:
        agent_id = None
    if not agent_id:
        bill.commission_agent_id = None
        return post_bill_entry(
            db,
            customer_id=bill.customer_id,
            bill_id=bill.id,
            amount=amount,
            description=description,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_name=actor_name,
            value_date=value_date,
            created_at=created_at,
        )
    bill.commission_agent_id = agent_id
    entry = CommissionLedgerEntry(
        commission_agent_id=agent_id,
        entry_type="bill",
        amount=as_signed_increase(amount),
        customer_bill_id=bill.id,
        customer_id=bill.customer_id,
        description=description,
        value_date=value_date,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    if created_at is not None:
        entry.created_at = created_at
    db.add(entry)
    db.flush()
    return entry


def sync_bill_due(
    db: Session,
    *,
    bill: CustomerBill,
    amount: Decimal,
    description: str,
    value_date: Optional[date] = None,
    created_at: Optional[datetime] = None,
):
    if bill.commission_agent_id:
        entry = (
            db.query(CommissionLedgerEntry)
            .filter(
                CommissionLedgerEntry.customer_bill_id == bill.id,
                CommissionLedgerEntry.entry_type == "bill",
            )
            .order_by(CommissionLedgerEntry.id.asc())
            .first()
        )
        if entry is None:
            return None
        entry.amount = as_signed_increase(amount) if mag(amount) else Decimal("0.00")
        entry.description = description
        if value_date is not None:
            entry.value_date = value_date
        if created_at is not None:
            entry.created_at = created_at
        db.flush()
        return entry
    return update_bill_ledger_amount(
        db,
        bill_id=bill.id,
        amount=amount,
        description=description,
        value_date=value_date,
        created_at=created_at,
    )


def move_party_ledger_to_agent(db: Session, *, customer_id: int, agent_id: int) -> dict:
    """Move one party's opening, bills, and payments onto a commission agent.

    The party row and its orders stay, so old orders can still be opened.
    The money rows are soft-deleted on the party and copied, with the same
    signed amounts, onto the agent. Running this twice does not copy again.
    """
    from app.models.accounts_receivable import ArLedgerEntry

    agent = db.get(CommissionAgent, agent_id)
    customer = db.get(Customer, customer_id)
    if agent is None or agent.deleted_at:
        raise ValueError("commission agent not found")
    if customer is None or customer.deleted_at:
        raise ValueError("party not found")
    before_agent = agent_outstanding(db, agent_id)
    party_rows = (
        db.query(ArLedgerEntry)
        .filter(ArLedgerEntry.customer_id == customer_id, ArLedgerEntry.deleted_at.is_(None))
        .order_by(ArLedgerEntry.id.asc())
        .all()
    )
    before_party = sum((Decimal(str(row.amount)) for row in party_rows), Decimal("0")).quantize(Decimal("0.01"))
    now = datetime.now(timezone.utc)
    moved = 0
    for row in party_rows:
        if row.entry_type == "bill" and row.bill_id:
            already = (
                db.query(CommissionLedgerEntry)
                .filter(
                    CommissionLedgerEntry.commission_agent_id == agent_id,
                    CommissionLedgerEntry.customer_bill_id == row.bill_id,
                    CommissionLedgerEntry.entry_type == "bill",
                )
                .first()
            )
            if already is not None:
                row.deleted_at = now
                continue
        entry = CommissionLedgerEntry(
            commission_agent_id=agent_id,
            entry_type=row.entry_type[:20],
            amount=Decimal(str(row.amount)).quantize(Decimal("0.01")),
            customer_bill_id=row.bill_id if row.entry_type == "bill" else None,
            customer_id=customer_id,
            customer_return_id=row.return_id if row.entry_type == "credit_note" else None,
            description=(row.description or "Transferred from party ledger")[:500],
            value_date=row.value_date,
            created_by_type=row.created_by_type or "admin",
            created_by_id=row.created_by_id,
            created_by_name=row.created_by_name or "Transfer",
            created_at=row.created_at or now,
        )
        db.add(entry)
        row.deleted_at = now
        moved += 1
    bills = (
        db.query(CustomerBill)
        .filter(CustomerBill.customer_id == customer_id, CustomerBill.deleted_at.is_(None))
        .all()
    )
    for bill in bills:
        if bill.commission_agent_id and bill.commission_agent_id != agent_id:
            raise ValueError(f"bill {bill.id} already belongs to another agent")
        bill.commission_agent_id = agent_id
    db.flush()
    after_rows = (
        db.query(ArLedgerEntry)
        .filter(ArLedgerEntry.customer_id == customer_id, ArLedgerEntry.deleted_at.is_(None))
        .all()
    )
    after_party = sum((Decimal(str(row.amount)) for row in after_rows), Decimal("0")).quantize(Decimal("0.01"))
    after_agent = agent_outstanding(db, agent_id)
    expected = (before_agent + before_party).quantize(Decimal("0.01"))
    if after_party != Decimal("0.00"):
        raise ValueError(f"party ledger still has {after_party}")
    if after_agent != expected:
        raise ValueError(f"agent ledger {after_agent} is not {expected}")
    both = (
        db.query(CustomerBill.id)
        .join(ArLedgerEntry, ArLedgerEntry.bill_id == CustomerBill.id)
        .join(CommissionLedgerEntry, CommissionLedgerEntry.customer_bill_id == CustomerBill.id)
        .filter(
            CustomerBill.customer_id == customer_id,
            ArLedgerEntry.deleted_at.is_(None),
            ArLedgerEntry.entry_type == "bill",
            CommissionLedgerEntry.entry_type == "bill",
        )
        .count()
    )
    if both:
        raise ValueError(f"{both} bills are on both ledgers")
    return {
        "customer_id": customer_id,
        "agent_id": agent_id,
        "moved": moved,
        "bills": len(bills),
        "before_party": format(before_party, "f"),
        "before_agent": format(before_agent, "f"),
        "after_party": format(after_party, "f"),
        "after_agent": format(after_agent, "f"),
    }


def receive_agent_payment(
    db: Session,
    *,
    agent_id: int,
    amount: Decimal,
    note: Optional[str],
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
    value_date: Optional[date] = None,
) -> CommissionLedgerEntry:
    text = (note or "").strip()
    description = f"Received ₹{mag(amount)}"
    if text:
        description = f"{description} — {text}"
    entry = CommissionLedgerEntry(
        commission_agent_id=agent_id,
        entry_type="payment",
        amount=as_signed_decrease(amount),
        description=description[:500],
        value_date=value_date,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(entry)
    db.flush()
    return entry


def post_agent_credit(
    db: Session,
    *,
    agent_id: int,
    customer_id: int,
    return_id: int,
    amount: Decimal,
    description: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
) -> CommissionLedgerEntry:
    entry = CommissionLedgerEntry(
        commission_agent_id=agent_id,
        entry_type="credit_note",
        amount=as_signed_decrease(amount),
        customer_id=customer_id,
        customer_return_id=return_id,
        description=description[:500],
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(entry)
    db.flush()
    return entry
