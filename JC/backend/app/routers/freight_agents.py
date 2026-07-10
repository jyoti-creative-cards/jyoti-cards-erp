from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin, require_permission
from app.models.expense import Expense
from app.models.freight_agent import FreightAgent, FreightLedgerEntry
from app.services.activity import log_from_auth

router = APIRouter(prefix="/freight-agents", tags=["freight-agents"])


class FreightAgentIn(BaseModel):
    name: str
    notes: Optional[str] = None


class FreightAgentPublic(BaseModel):
    id: int
    name: str
    balance_due: str
    notes: Optional[str] = None


class FreightLedgerOut(BaseModel):
    id: int
    entry_type: str
    amount: str
    customer_bill_id: Optional[int] = None
    expense_id: Optional[int] = None
    transaction_ref: Optional[str] = None
    notes: Optional[str] = None
    created_by_name: str
    created_at: str


class FreightSettleIn(BaseModel):
    amount: Decimal = Field(..., gt=0)
    transaction_ref: str = Field(..., min_length=1, max_length=200)
    notes: Optional[str] = None


def _pub(row: FreightAgent) -> FreightAgentPublic:
    return FreightAgentPublic(
        id=row.id,
        name=row.name,
        balance_due=format(row.balance_due or Decimal("0"), "f"),
        notes=row.notes,
    )


@router.get("", response_model=List[FreightAgentPublic])
def list_freight_agents(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("vendor_orders.read"))):
    rows = db.query(FreightAgent).order_by(FreightAgent.name.asc()).all()
    return [_pub(r) for r in rows]


@router.post("", response_model=FreightAgentPublic, status_code=201)
def create_freight_agent(body: FreightAgentIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    row = FreightAgent(name=body.name.strip(), notes=(body.notes or "").strip() or None)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _pub(row)


@router.patch("/{agent_id}", response_model=FreightAgentPublic)
def update_freight_agent(agent_id: int, body: FreightAgentIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    row = db.get(FreightAgent, agent_id)
    if not row:
        raise HTTPException(404, "freight agent not found")
    row.name = body.name.strip()
    row.notes = (body.notes or "").strip() or None
    db.commit()
    db.refresh(row)
    return _pub(row)


@router.get("/{agent_id}/ledger", response_model=List[FreightLedgerOut])
def get_ledger(agent_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    rows = (
        db.query(FreightLedgerEntry)
        .filter(FreightLedgerEntry.freight_agent_id == agent_id)
        .order_by(FreightLedgerEntry.created_at.desc(), FreightLedgerEntry.id.desc())
        .all()
    )
    return [
        FreightLedgerOut(
            id=r.id,
            entry_type=r.entry_type,
            amount=format(r.amount, "f"),
            customer_bill_id=r.customer_bill_id,
            expense_id=r.expense_id,
            transaction_ref=r.transaction_ref,
            notes=r.notes,
            created_by_name=r.created_by_name,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.post("/{agent_id}/settle", status_code=201)
def settle_freight_agent(
    agent_id: int,
    body: FreightSettleIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    agent = db.get(FreightAgent, agent_id)
    if not agent:
        raise HTTPException(404, "freight agent not found")
    balance = (agent.balance_due or Decimal("0")).quantize(Decimal("0.01"))
    amount = body.amount.quantize(Decimal("0.01"))
    if balance <= 0:
        raise HTTPException(400, "no balance due")
    if amount > balance:
        raise HTTPException(400, f"cannot settle more than balance ₹{balance}")

    expense = Expense(
        expense_date=date.today(),
        category="transport",
        description=f"Freight settlement — {agent.name}",
        amount=amount,
        reference=body.transaction_ref.strip(),
        freight_agent_id=agent.id,
        created_by_name=auth.actor_name,
    )
    db.add(expense)
    db.flush()

    agent.balance_due = (balance - amount).quantize(Decimal("0.01"))
    entry = FreightLedgerEntry(
        freight_agent_id=agent.id,
        entry_type="settlement",
        amount=amount,
        expense_id=expense.id,
        transaction_ref=body.transaction_ref.strip(),
        notes=body.notes,
        created_by_name=auth.actor_name,
    )
    db.add(entry)
    log_from_auth(
        db,
        auth,
        action="freight_settle",
        entity_type="freight_agent",
        entity_id=agent.id,
        entity_label=agent.name,
        detail=f"₹{amount} ref {body.transaction_ref.strip()}",
    )
    db.commit()
    return {"ok": True, "balance_due": format(agent.balance_due, "f"), "expense_id": expense.id}
