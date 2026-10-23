"""Commission-agent money. The party keeps the order. The agent owes the bill."""

from __future__ import annotations

from datetime import date, datetime
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
):
    """New bills follow the party's agent. A party with no agent stays on their own ledger."""
    agent_id = live_agent_id(db, customer)
    if not agent_id:
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
