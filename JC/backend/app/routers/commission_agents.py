"""Commission agents. Parties stay the buyers. The agent carries the due."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin
from app.models.city import City
from app.models.commission_agent import CommissionAgent, CommissionLedgerEntry
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOpenLine
from app.services.activity import log_from_auth
from app.services.biz_date import today_ist
from app.services.commission_ledger import agent_outstanding, receive_agent_payment

router = APIRouter(prefix="/commission-agents", tags=["commission-agents"])


class AgentIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: Optional[str] = None
    notes: Optional[str] = None


class PaymentIn(BaseModel):
    amount: Decimal = Field(..., gt=0)
    note: Optional[str] = None
    paid_on: Optional[date] = None


def _money(value: Decimal) -> str:
    return format(Decimal(str(value or 0)).quantize(Decimal("0.01")), "f")


def _agent_or_404(db: Session, agent_id: int) -> CommissionAgent:
    row = db.get(CommissionAgent, agent_id)
    if not row or row.deleted_at:
        raise HTTPException(404, "commission agent not found")
    return row


@router.get("")
def list_agents(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    rows = (
        db.query(CommissionAgent)
        .filter(CommissionAgent.deleted_at.is_(None))
        .order_by(CommissionAgent.name.asc())
        .all()
    )
    out = []
    for row in rows:
        parties = (
            db.query(Customer)
            .filter(Customer.commission_agent_id == row.id, Customer.deleted_at.is_(None))
            .count()
        )
        out.append({
            "id": row.id,
            "name": row.name,
            "phone": row.phone or "",
            "notes": row.notes or "",
            "party_count": parties,
            "outstanding": _money(agent_outstanding(db, row.id)),
        })
    return out


@router.post("")
def create_agent(body: AgentIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    row = CommissionAgent(name=body.name.strip(), phone=(body.phone or "").strip() or None, notes=(body.notes or "").strip() or None)
    db.add(row)
    db.flush()
    log_from_auth(db, auth, action="create", entity_type="commission_agent", entity_id=row.id, entity_label=row.name)
    db.commit()
    return {"id": row.id}


@router.patch("/{agent_id}")
def update_agent(agent_id: int, body: AgentIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    row = _agent_or_404(db, agent_id)
    row.name = body.name.strip()
    row.phone = (body.phone or "").strip() or None
    row.notes = (body.notes or "").strip() or None
    row.updated_at = datetime.now(timezone.utc)
    log_from_auth(db, auth, action="update", entity_type="commission_agent", entity_id=row.id, entity_label=row.name)
    db.commit()
    return {"ok": True}


@router.delete("/{agent_id}")
def delete_agent(agent_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    row = _agent_or_404(db, agent_id)
    due = agent_outstanding(db, row.id)
    if due != 0:
        raise HTTPException(400, "This agent still has a balance. Collect or credit it before deleting.")
    for party in db.query(Customer).filter(Customer.commission_agent_id == row.id).all():
        party.commission_agent_id = None
    row.deleted_at = datetime.now(timezone.utc)
    row.is_active = False
    log_from_auth(db, auth, action="delete", entity_type="commission_agent", entity_id=row.id, entity_label=row.name)
    db.commit()
    return {"ok": True}


@router.get("/party-search")
def search_parties(q: str = "", db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    text = (q or "").strip()
    if len(text) < 2:
        return []
    like = f"%{text}%"
    rows = (
        db.query(Customer, City.name, CommissionAgent.name)
        .outerjoin(City, City.id == Customer.city_id)
        .outerjoin(CommissionAgent, CommissionAgent.id == Customer.commission_agent_id)
        .filter(
            Customer.deleted_at.is_(None),
            Customer.is_active.is_(True),
            or_(Customer.business_name.ilike(like), Customer.phone.ilike(like), City.name.ilike(like)),
        )
        .order_by(Customer.business_name.asc())
        .limit(15)
        .all()
    )
    return [
        {
            "id": customer.id,
            "business_name": customer.business_name,
            "city_name": city_name or "",
            "phone": customer.phone or "",
            "agent_name": agent_name or "",
        }
        for customer, city_name, agent_name in rows
    ]


@router.post("/{agent_id}/parties/{customer_id}")
def add_party(agent_id: int, customer_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    agent = _agent_or_404(db, agent_id)
    party = db.get(Customer, customer_id)
    if not party or party.deleted_at:
        raise HTTPException(404, "customer not found")
    party.commission_agent_id = agent.id
    log_from_auth(db, auth, action="assign", entity_type="commission_agent", entity_id=agent.id, entity_label=f"{party.business_name} → {agent.name}")
    db.commit()
    return {"ok": True}


@router.delete("/{agent_id}/parties/{customer_id}")
def remove_party(agent_id: int, customer_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    agent = _agent_or_404(db, agent_id)
    party = db.get(Customer, customer_id)
    if not party or party.commission_agent_id != agent.id:
        raise HTTPException(404, "party is not on this agent")
    party.commission_agent_id = None
    log_from_auth(db, auth, action="unassign", entity_type="commission_agent", entity_id=agent.id, entity_label=party.business_name)
    db.commit()
    return {"ok": True}


@router.post("/{agent_id}/payments")
def collect_payment(agent_id: int, body: PaymentIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    agent = _agent_or_404(db, agent_id)
    receive_agent_payment(
        db,
        agent_id=agent.id,
        amount=body.amount,
        note=body.note,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        actor_name=auth.actor_name,
        value_date=body.paid_on or today_ist(),
    )
    log_from_auth(db, auth, action="payment", entity_type="commission_agent", entity_id=agent.id, entity_label=f"₹{body.amount}")
    db.commit()
    return {"ok": True, "outstanding": _money(agent_outstanding(db, agent.id))}


@router.get("/{agent_id}")
def agent_detail(agent_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    agent = _agent_or_404(db, agent_id)
    parties = (
        db.query(Customer, City.name)
        .outerjoin(City, City.id == Customer.city_id)
        .filter(Customer.commission_agent_id == agent.id, Customer.deleted_at.is_(None))
        .order_by(Customer.business_name.asc())
        .all()
    )
    entries = (
        db.query(CommissionLedgerEntry, Customer.business_name)
        .outerjoin(Customer, Customer.id == CommissionLedgerEntry.customer_id)
        .filter(CommissionLedgerEntry.commission_agent_id == agent.id)
        .order_by(CommissionLedgerEntry.value_date.asc(), CommissionLedgerEntry.id.asc())
        .all()
    )
    balance = Decimal("0")
    ledger = []
    for entry, party_name in entries:
        balance += Decimal(str(entry.amount or 0))
        ledger.append({
            "id": entry.id,
            "date": entry.value_date.isoformat() if entry.value_date else (entry.created_at.date().isoformat() if entry.created_at else ""),
            "entry_type": entry.entry_type,
            "description": entry.description or "",
            "party_name": party_name or "",
            "amount": _money(Decimal(str(entry.amount or 0))),
            "balance": _money(balance),
        })
    ledger.reverse()
    goods_rows = (
        db.query(CustomerBill, CustomerBillLine, Customer.business_name)
        .join(CustomerBillLine, CustomerBillLine.bill_id == CustomerBill.id)
        .join(Customer, Customer.id == CustomerBill.customer_id)
        .filter(
            CustomerBill.commission_agent_id == agent.id,
            CustomerBill.deleted_at.is_(None),
            CustomerBill.cancelled_at.is_(None),
        )
        .order_by(CustomerBill.bill_date.desc(), CustomerBill.id.desc(), CustomerBillLine.id.asc())
        .limit(300)
        .all()
    )
    goods = [
        {
            "date": bill.bill_date.isoformat() if bill.bill_date else "",
            "bill_number": bill.bill_number,
            "party_name": party_name,
            "item": line.our_product_id,
            "qty": line.quantity_shipped,
            "amount": _money(Decimal(str(line.line_total or 0))),
        }
        for bill, line, party_name in goods_rows
    ]
    party_ids = [party.id for party, _city in parties]
    open_rows = []
    if party_ids:
        open_rows = (
            db.query(CustomerOpenLine, Customer.business_name)
            .join(Customer, Customer.id == CustomerOpenLine.customer_id)
            .filter(
                CustomerOpenLine.customer_id.in_(party_ids),
                CustomerOpenLine.status == "open",
                CustomerOpenLine.quantity_open > 0,
            )
            .order_by(Customer.business_name.asc())
            .limit(200)
            .all()
        )
    return {
        "id": agent.id,
        "name": agent.name,
        "phone": agent.phone or "",
        "notes": agent.notes or "",
        "outstanding": _money(agent_outstanding(db, agent.id)),
        "parties": [
            {"id": party.id, "business_name": party.business_name, "city_name": city_name or "", "phone": party.phone or ""}
            for party, city_name in parties
        ],
        "ledger": ledger,
        "goods": goods,
        "open_orders": [
            {"party_name": party_name, "item": line.our_product_id, "qty": line.quantity_open}
            for line, party_name in open_rows
        ],
    }
