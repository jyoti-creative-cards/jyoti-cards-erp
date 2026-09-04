"""Freight parcels — bills assigned to an agent, dues only after pick."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.freight_agent import FreightAgent, FreightLedgerEntry
from app.services.freight_ledger import post_freight_charge, recompute_balance_due
from app.services.money import as_signed_increase, mag


def charge_for_bill(db: Session, bill_id: int) -> Optional[FreightLedgerEntry]:
    return (
        db.query(FreightLedgerEntry)
        .filter(
            FreightLedgerEntry.customer_bill_id == bill_id,
            FreightLedgerEntry.entry_type == "charge",
        )
        .first()
    )


def remove_charge_for_bill(db: Session, bill_id: int) -> None:
    entry = charge_for_bill(db, bill_id)
    if not entry:
        return
    agent_id = entry.freight_agent_id
    db.delete(entry)
    db.flush()
    recompute_balance_due(db, agent_id)


def sync_bill_freight_on_edit(
    db: Session,
    *,
    bill: CustomerBill,
    freight_agent_id: Optional[int],
    freight_charges: Optional[Decimal],
    customer_name: str,
    actor_name: str,
) -> None:
    """Update freight fields on bill edit. Picked parcels cannot change agent."""
    picked = bill.freight_picked_at is not None
    new_agent = freight_agent_id
    new_amt = (freight_charges or Decimal("0")).quantize(Decimal("0.01")) if freight_charges is not None else Decimal("0")

    if picked:
        if new_agent != bill.freight_agent_id:
            raise HTTPException(
                400,
                "parcel already picked — change freight agent only on pending parcels (Selling → Dispatch)",
            )
        bill.freight_charges = freight_charges
        entry = charge_for_bill(db, bill.id)
        if new_amt <= 0:
            remove_charge_for_bill(db, bill.id)
            bill.freight_picked_at = None
            bill.freight_picked_by = None
            bill.freight_agent_id = new_agent
            return
        if entry:
            if entry.freight_agent_id != bill.freight_agent_id:
                remove_charge_for_bill(db, bill.id)
                entry = None
            else:
                entry.amount = as_signed_increase(new_amt)
                entry.notes = customer_name or entry.notes
                db.flush()
                recompute_balance_due(db, entry.freight_agent_id)
        elif bill.freight_agent_id and new_amt > 0:
            agent = db.get(FreightAgent, bill.freight_agent_id)
            if agent:
                post_freight_charge(
                    db,
                    agent_id=agent.id,
                    amount=new_amt,
                    customer_bill_id=bill.id,
                    notes=customer_name or f"Bill {bill.bill_number}",
                    actor_name=actor_name,
                )
        return

    # Pending — free to reassign / clear
    bill.freight_agent_id = new_agent
    bill.freight_charges = freight_charges
    # Should not have a charge while pending; clean if orphaned
    if charge_for_bill(db, bill.id):
        remove_charge_for_bill(db, bill.id)


def pick_parcel(db: Session, *, bill_id: int, actor_name: str) -> CustomerBill:
    bill = db.get(CustomerBill, bill_id)
    if not bill:
        raise HTTPException(404, "bill not found")
    if bill.freight_picked_at:
        raise HTTPException(400, "already picked")
    mode = bill.transport_mode or ("bus" if bill.freight_agent_id else "self_pickup")
    now = datetime.now(timezone.utc)
    if mode != "bus":
        bill.freight_picked_at = now
        bill.freight_picked_by = actor_name
        db.flush()
        return bill
    if not bill.freight_agent_id:
        raise HTTPException(400, "no freight agent assigned")
    amt = (bill.freight_charges or Decimal("0")).quantize(Decimal("0.01"))
    if amt <= 0:
        bill.freight_picked_at = now
        bill.freight_picked_by = actor_name
        db.flush()
        return bill
    agent = db.get(FreightAgent, bill.freight_agent_id)
    if not agent:
        raise HTTPException(400, "freight agent not found")
    customer = db.get(Customer, bill.customer_id)
    party = (customer.business_name if customer else None) or f"Bill {bill.bill_number}"

    existing = charge_for_bill(db, bill.id)
    if existing:
        if existing.freight_agent_id != agent.id:
            remove_charge_for_bill(db, bill.id)
            existing = None
        elif mag(existing.amount) != amt:
            existing.amount = as_signed_increase(amt)
            existing.notes = party
            db.flush()
            recompute_balance_due(db, agent.id)
    if not existing:
        post_freight_charge(
            db,
            agent_id=agent.id,
            amount=amt,
            customer_bill_id=bill.id,
            notes=party,
            actor_name=actor_name,
        )
    bill.freight_picked_at = datetime.now(timezone.utc)
    bill.freight_picked_by = actor_name
    db.flush()
    return bill


def reassign_parcel(
    db: Session,
    *,
    bill_id: int,
    freight_agent_id: int,
    freight_charges: Optional[Decimal] = None,
) -> CustomerBill:
    bill = db.get(CustomerBill, bill_id)
    if not bill:
        raise HTTPException(404, "bill not found")
    if bill.freight_picked_at:
        raise HTTPException(400, "already picked — cannot change agent")
    agent = db.get(FreightAgent, freight_agent_id)
    if not agent:
        raise HTTPException(400, "freight agent not found")
    bill.freight_agent_id = freight_agent_id
    if freight_charges is not None:
        bill.freight_charges = freight_charges
    # Clear orphan charge if any
    if charge_for_bill(db, bill.id):
        remove_charge_for_bill(db, bill.id)
    db.flush()
    return bill


def _parcel_dict(db: Session, bill: CustomerBill, agents: dict[int, str]) -> dict:
    customer = db.get(Customer, bill.customer_id)
    lines = (
        db.query(CustomerBillLine)
        .filter(CustomerBillLine.bill_id == bill.id)
        .all()
    )
    line_rows = [
        {
            "our_product_id": ln.our_product_id,
            "quantity": int(ln.quantity_shipped or 0),
            "unit_price": format(ln.unit_price or 0, "f"),
            "line_total": format(ln.line_total or 0, "f"),
        }
        for ln in lines
    ]
    pcs = sum(int(ln.quantity_shipped or 0) for ln in lines)
    picked = bill.freight_picked_at is not None
    return {
        "bill_id": bill.id,
        "bill_number": bill.bill_number,
        "customer_id": bill.customer_id,
        "customer_label": (customer.business_name if customer else None)
        or (customer.person_name if customer else None)
        or f"Customer #{bill.customer_id}",
        "customer_phone": customer.phone if customer else None,
        "customer_city": None,
        "freight_agent_id": bill.freight_agent_id,
        "freight_agent_name": agents.get(bill.freight_agent_id or 0),
        "freight_charges": format(bill.freight_charges or 0, "f"),
        "transport_mode": bill.transport_mode or ("bus" if bill.freight_agent_id else "self_pickup"),
        "transport_receipt_number": bill.transport_receipt_number,
        "status": "picked" if picked else "pending",
        "picked_at": bill.freight_picked_at.isoformat() if bill.freight_picked_at else None,
        "picked_by": bill.freight_picked_by,
        "line_count": len(line_rows),
        "total_pcs": pcs,
        "lines": line_rows,
        "bill_total": format(bill.grand_total or 0, "f"),
        "created_at": bill.created_at.isoformat() if bill.created_at else None,
    }


def list_parcels(
    db: Session,
    *,
    agent_id: Optional[int] = None,
    status: str = "all",
    day: str = "all",
) -> list[dict]:
    q = db.query(CustomerBill).filter(
        CustomerBill.cancelled_at.is_(None),
        or_(
            CustomerBill.transport_mode.isnot(None),
            CustomerBill.freight_agent_id.isnot(None),
        ),
    )
    if agent_id:
        q = q.filter(CustomerBill.freight_agent_id == agent_id)
    if status == "pending":
        q = q.filter(CustomerBill.freight_picked_at.is_(None))
    elif status == "picked":
        q = q.filter(CustomerBill.freight_picked_at.isnot(None))
    # NB: "pending" is an actionable backlog (awaiting pickup), not a daily log — never
    # day-scope it away, or a bill created yesterday and still unpicked silently
    # disappears from the default "Today" dispatch queue. Only "picked"/"all" (already
    # actioned / full history) are meaningful to scope by day.
    if day == "today" and status != "pending":
        local_now = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata"))
        start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start = start_local.astimezone(timezone.utc)
        day_end = (start_local + timedelta(days=1)).astimezone(timezone.utc)
        q = q.filter(CustomerBill.created_at >= day_start, CustomerBill.created_at < day_end)
    rows = q.order_by(CustomerBill.created_at.desc(), CustomerBill.id.desc()).limit(300).all()
    agent_ids = {b.freight_agent_id for b in rows if b.freight_agent_id}
    agents = {
        a.id: a.name
        for a in (
            db.query(FreightAgent).filter(FreightAgent.id.in_(agent_ids)).all() if agent_ids else []
        )
    }
    # city names
    from app.models.city import City

    city_ids = set()
    cust_map = {}
    for b in rows:
        c = db.get(Customer, b.customer_id)
        if c:
            cust_map[b.customer_id] = c
            if c.city_id:
                city_ids.add(c.city_id)
    cities = {
        c.id: c.name
        for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
    }
    out = []
    for b in rows:
        d = _parcel_dict(db, b, agents)
        c = cust_map.get(b.customer_id)
        if c and c.city_id:
            d["customer_city"] = cities.get(c.city_id)
        if c:
            d["customer_label"] = c.business_name or c.person_name or d["customer_label"]
            d["customer_phone"] = c.phone
        out.append(d)
    return out
