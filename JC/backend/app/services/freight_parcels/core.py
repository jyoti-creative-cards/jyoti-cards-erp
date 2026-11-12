"""Freight parcels. The agent ledger gets the charge when the bill is saved."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOrderPlacement
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


def ensure_bill_freight_charge(
    db: Session,
    bill: CustomerBill,
    *,
    customer_name: str,
    actor_name: str,
) -> None:
    """Keep one agent charge in step with the bill.

    Bus or transport, with an agent and an amount, posts it. Self-pickup does
    not. The customer ledger stays the one bill total.
    """
    mode = bill.transport_mode or ("bus" if bill.freight_agent_id else "self_pickup")
    amt = (bill.freight_charges or Decimal("0")).quantize(Decimal("0.01"))
    if mode not in ("bus", "transport") or not bill.freight_agent_id or amt <= 0:
        if charge_for_bill(db, bill.id):
            remove_charge_for_bill(db, bill.id)
        return
    entry = charge_for_bill(db, bill.id)
    if entry and entry.freight_agent_id != bill.freight_agent_id:
        remove_charge_for_bill(db, bill.id)
        entry = None
    party = customer_name or f"Bill {bill.bill_number}"
    if entry:
        if mag(entry.amount) != amt or (entry.notes or "") != party:
            entry.amount = as_signed_increase(amt)
            entry.notes = party
            db.flush()
            recompute_balance_due(db, entry.freight_agent_id)
        return
    agent = db.get(FreightAgent, bill.freight_agent_id)
    if not agent:
        return
    post_freight_charge(
        db,
        agent_id=agent.id,
        amount=amt,
        customer_bill_id=bill.id,
        notes=party,
        actor_name=actor_name,
    )


def sync_bill_freight_on_edit(
    db: Session,
    *,
    bill: CustomerBill,
    freight_agent_id: Optional[int],
    freight_charges: Optional[Decimal],
    customer_name: str,
    actor_name: str,
) -> None:
    """Update freight on a bill. A picked parcel can still move to another agent.

    The bill screen sends an agent only for bus. A transport bill that already
    has an agent keeps that agent, so an edit does not drop the freight charge.
    """
    if freight_agent_id is None and bill.freight_agent_id and (bill.transport_mode == "transport"):
        freight_agent_id = bill.freight_agent_id
    bill.freight_agent_id = freight_agent_id
    bill.freight_charges = freight_charges
    if freight_agent_id and bill.transport_mode not in ("bus", "transport"):
        bill.transport_mode = "bus"
    ensure_bill_freight_charge(db, bill, customer_name=customer_name, actor_name=actor_name)


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
    agent = db.get(FreightAgent, freight_agent_id)
    if not agent:
        raise HTTPException(400, "freight agent not found")
    bill.freight_agent_id = freight_agent_id
    if freight_charges is not None:
        bill.freight_charges = freight_charges
    customer = db.get(Customer, bill.customer_id)
    party = (customer.business_name if customer else None) or f"Bill {bill.bill_number}"
    ensure_bill_freight_charge(db, bill, customer_name=party, actor_name="reassign")
    db.flush()
    return bill


def _parcel_dict(
    db: Session,
    bill: CustomerBill,
    agents: dict[int, str],
    *,
    customer: Optional[Customer] = None,
    lines: Optional[list] = None,
) -> dict:
    # Both batch-fetched by the caller (list_parcels) to avoid N+1 queries — kept as
    # optional lookups here (falling back to a single fetch) so other callers of this
    # helper still work unchanged.
    if customer is None:
        customer = db.get(Customer, bill.customer_id)
    if lines is None:
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
    who = "Staff"
    if bill.placement_id:
        placed = db.get(CustomerOrderPlacement, bill.placement_id)
        if placed is not None:
            from app.routers.customer_orders.listing import _who_made
            who = _who_made(placed.order_source, placed.placed_by_name, placed.customer_notes)
    if who == "Staff":
        who = (bill.created_by_name or "").strip() or "Staff"
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
        "freight_handler": bill.freight_handler,
        "freight_charges": format(bill.freight_charges or 0, "f"),
        "transport_mode": bill.transport_mode or ("bus" if bill.freight_agent_id else "self_pickup"),
        "transport_receipt_number": bill.transport_receipt_number,
        "packaging_charges": format(bill.packaging_charges or 0, "f"),
        "additional_charges": bill.additional_charges or [],
        "dispatch_narration": (bill.dispatch_narration or "").strip() or None,
        "pick_narration": (bill.pick_narration or "").strip() or None,
        "status": "picked" if picked else "pending",
        "picked_at": bill.freight_picked_at.isoformat() if bill.freight_picked_at else None,
        "picked_by": bill.freight_picked_by,
        "line_count": len(line_rows),
        "total_pcs": pcs,
        "lines": line_rows,
        "bill_total": format(bill.grand_total or 0, "f"),
        "created_at": bill.created_at.isoformat() if bill.created_at else None,
        "bill_date": bill.bill_date.isoformat() if bill.bill_date else None,
        "created_by": who,
        "marking": (bill.narration or "").strip() or None,
        "customer_marking": None,
    }


def _parcel_day_bounds(day: str) -> tuple[datetime, datetime] | None:
    if not day or day == "all":
        return None
    if day == "today":
        chosen = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date()
    else:
        try:
            chosen = date.fromisoformat(day)
        except ValueError:
            raise HTTPException(400, "bad date") from None
    start_local = datetime(chosen.year, chosen.month, chosen.day, tzinfo=ZoneInfo("Asia/Kolkata"))
    return start_local.astimezone(timezone.utc), (start_local + timedelta(days=1)).astimezone(timezone.utc)


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
    # Day-scoped consistently with every other queue in the app now: day=today shows
    # only bills created today, a YYYY-MM-DD shows that IST day, day=all shows the
    # full backlog regardless of status — nothing is ever lost, it just moves from
    # Today to Past.
    bounds = _parcel_day_bounds(day)
    if bounds is not None:
        day_start, day_end = bounds
        q = q.filter(CustomerBill.created_at >= day_start, CustomerBill.created_at < day_end)
    rows = q.order_by(CustomerBill.created_at.desc(), CustomerBill.id.desc()).limit(300).all()
    agent_ids = {b.freight_agent_id for b in rows if b.freight_agent_id}
    agents = {
        a.id: a.name
        for a in (
            db.query(FreightAgent).filter(FreightAgent.id.in_(agent_ids)).all() if agent_ids else []
        )
    }
    # Batch-fetch everything the loop needs up front — avoids one Customer + one
    # CustomerBillLine query per row (was O(n) round trips for n parcels).
    from app.models.city import City

    bill_ids = [b.id for b in rows]
    customer_ids = {b.customer_id for b in rows}
    cust_map = {
        c.id: c
        for c in (db.query(Customer).filter(Customer.id.in_(customer_ids)).all() if customer_ids else [])
    }
    city_ids = {c.city_id for c in cust_map.values() if c.city_id}
    cities = {
        c.id: c.name
        for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
    }
    lines_by_bill: dict[int, list] = {}
    if bill_ids:
        for ln in db.query(CustomerBillLine).filter(CustomerBillLine.bill_id.in_(bill_ids)).all():
            lines_by_bill.setdefault(ln.bill_id, []).append(ln)

    from app.services.customer_selling.marking import clean_mark

    out = []
    for b in rows:
        c = cust_map.get(b.customer_id)
        d = _parcel_dict(db, b, agents, customer=c, lines=lines_by_bill.get(b.id, []))
        d["marking"] = clean_mark(b.narration)
        d["customer_marking"] = None
        if c and c.city_id:
            d["customer_city"] = cities.get(c.city_id)
        if c:
            d["customer_label"] = c.business_name or c.person_name or d["customer_label"]
            d["customer_phone"] = c.phone
        out.append(d)
    return out


def _money(value) -> Decimal:
    try:
        amount = Decimal(str(value or "0"))
    except Exception:
        amount = Decimal("0")
    if amount < 0:
        amount = Decimal("0")
    return amount.quantize(Decimal("0.01"))


def _charge_sum(freight, packaging, additional) -> Decimal:
    total = _money(freight) + _money(packaging)
    for row in additional or []:
        if isinstance(row, dict):
            total += _money(row.get("amount"))
    return total.quantize(Decimal("0.01"))


def save_dispatch_and_pick(
    db: Session,
    *,
    bill_id: int,
    transport_mode: str,
    freight_agent_id: Optional[int],
    freight_charges: Optional[str],
    transport_receipt_number: Optional[str],
    packaging_charges: Optional[str],
    additional_charges: Optional[list],
    narration: Optional[str],
    pick_narration: Optional[str],
    actor_name: str,
    freight_handler: Optional[str] = None,
) -> CustomerBill:
    """Save the send-by form, then mark the parcel picked."""
    from app.services.commission_ledger import sync_bill_due
    from app.services.customer_selling.marking import clean_mark
    from app.services.document_present import freeze_card
    from app.services.text_events import remember
    bill = db.get(CustomerBill, bill_id)
    if not bill or bill.deleted_at or bill.cancelled_at:
        raise HTTPException(404, "bill not found")
    if bill.freight_picked_at:
        raise HTTPException(400, "already picked")
    mode = (transport_mode or "").strip().lower()
    if mode not in ("bus", "transport", "self_pickup"):
        raise HTTPException(400, "Select how this is sent")
    freight = _money(freight_charges) if mode in ("bus", "transport") else Decimal("0")
    packing = _money(packaging_charges)
    extras = []
    for row in additional_charges or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        amount = _money(row.get("amount"))
        if name and amount > 0:
            extras.append({"name": name, "amount": format(amount, "f")})
    if mode == "bus":
        if not freight_agent_id:
            raise HTTPException(400, "Select the freight agent")
        if freight <= 0:
            raise HTTPException(400, "Enter freight")
    elif mode == "transport":
        if freight <= 0:
            raise HTTPException(400, "Enter transport charges")
        freight_agent_id = None
    else:
        freight_agent_id = None
        freight = Decimal("0")

    old_extra = _charge_sum(bill.freight_charges, bill.packaging_charges, bill.additional_charges)
    new_extra = _charge_sum(freight, packing, extras)
    totals = dict(bill.totals_json or {})
    base = totals.get("after_discount_inclusive")
    if base is None:
        base = Decimal(str(bill.grand_total or 0)) - old_extra
    else:
        base = Decimal(str(base))
    raw = (base + new_extra).quantize(Decimal("0.01"))
    rounded = raw.quantize(Decimal("1"))
    bill.transport_mode = mode
    bill.transport_receipt_number = (transport_receipt_number or "").strip() or None
    bill.freight_agent_id = freight_agent_id if mode == "bus" else None
    bill.freight_charges = freight if freight > 0 else None
    bill.packaging_charges = packing if packing > 0 else None
    bill.additional_charges = extras or None
    spoken = " ".join((pick_narration or "").split())
    if not spoken:
        raise HTTPException(400, "Enter a narration")
    bill.pick_narration = spoken[:800]
    bill.narration = clean_mark(narration)
    bill.grand_total = rounded
    totals["freight_charges"] = format(freight, "f") if freight > 0 else None
    totals["packaging_charges"] = format(packing, "f") if packing > 0 else None
    totals["additional_charges"] = extras or None
    totals["grand_total"] = format(raw, "f")
    totals["rounded_grand_total"] = format(rounded, "f")
    bill.totals_json = totals
    from app.services.freight_handler import apply_freight_handler

    apply_freight_handler(db, bill, freight_handler)
    bill.document_key = None
    remember(db, kind="bill", subject=str(bill.id), body=bill.narration or "", actor=actor_name)
    customer = db.get(Customer, bill.customer_id)
    customer_name = customer.business_name if customer else ""
    sync_bill_freight_on_edit(
        db,
        bill=bill,
        freight_agent_id=bill.freight_agent_id,
        freight_charges=bill.freight_charges,
        customer_name=customer_name,
        actor_name=actor_name,
    )
    sync_bill_due(
        db,
        bill=bill,
        amount=rounded,
        description=f"Bill {bill.bill_number} (dispatch) — ₹{rounded}",
    )
    freeze_card(db, "customer_bill", bill)
    return pick_parcel(db, bill_id=bill.id, actor_name=actor_name)


def parcel_story(db: Session, bill_id: int) -> dict:
    from app.services.customer_selling.marking import clean_mark

    bill = db.get(CustomerBill, bill_id)
    if not bill or bill.deleted_at:
        raise HTTPException(404, "bill not found")
    lines = [
        {
            "our_product_id": ln.our_product_id,
            "quantity": int(ln.quantity_shipped or 0),
            "rate": format(ln.unit_price or 0, "f"),
        }
        for ln in db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id).all()
    ]
    order_lines = lines
    created_at = bill.created_at
    created_by = bill.created_by_name or "Staff"
    order_mark = None
    if bill.placement_id:
        placement = db.get(CustomerOrderPlacement, bill.placement_id)
        if placement is not None:
            created_at = placement.placed_at or created_at
            created_by = (placement.placed_by_name or "").strip() or created_by
            from app.models.customer_order import CustomerOrder, CustomerOrderLine
            order = db.get(CustomerOrder, placement.customer_order_id)
            order_mark = clean_mark(order.marking if order else None) or clean_mark(placement.customer_notes)
            order_lines = [
                {
                    "our_product_id": ln.our_product_id,
                    "quantity": int(ln.quantity or 0),
                    "rate": format(ln.unit_price or 0, "f"),
                }
                for ln in db.query(CustomerOrderLine).filter(
                    CustomerOrderLine.placement_id == placement.id,
                    CustomerOrderLine.status == "active",
                ).all()
            ] or lines
    charges = {
        "transport_mode": bill.transport_mode,
        "freight_charges": format(bill.freight_charges or 0, "f"),
        "freight_agent_id": bill.freight_agent_id,
        "transport_receipt_number": bill.transport_receipt_number,
        "packaging_charges": format(bill.packaging_charges or 0, "f"),
        "additional_charges": bill.additional_charges or [],
        "marking": clean_mark(bill.narration),
    }
    def row(at, who, items, extra=None):
        out = {
            "at": at.isoformat() if at else None,
            "by": who or "Staff",
            "lines": items,
        }
        if extra:
            out.update(extra)
        return out
    return {
        "created": row(created_at, created_by, order_lines, {"marking": order_mark}),
        "billed": row(bill.created_at, bill.created_by_name, lines, charges),
        "dispatched": row(bill.created_at, bill.created_by_name, lines, charges),
        "picked": row(bill.freight_picked_at, bill.freight_picked_by, lines, charges) if bill.freight_picked_at else None,
    }
