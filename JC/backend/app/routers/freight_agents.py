from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin, require_any_permission, require_permission
from app.models.expense import Expense
from app.models.customer_bill import CustomerBill
from app.models.freight_agent import FreightAgent, FreightLedgerEntry
from app.services.activity import log_from_auth
from app.services.biz_date import today_ist
from app.services.money import as_signed_decrease, as_signed_increase, mag
from app.services.freight_ledger import (
    agent_freight_totals,
    build_freight_ledger,
    post_freight_settlement,
)
from app.services.freight_parcels import list_parcels, parcel_story, pick_parcel, reassign_parcel, save_dispatch_and_pick
from app.services.reports.pdfs import render_freight_payment_pdf
from app.services.storage import (
    freight_payment_key,
    presigned_url,
    storage_configured,
    upload_bytes,
    vendor_folder_slug,
)

router = APIRouter(prefix="/freight-agents", tags=["freight-agents"])

DEFAULT_FREIGHT_AGENT = "Vishnu Parcel"


class FreightAgentIn(BaseModel):
    name: str
    notes: Optional[str] = None


class FreightAgentPublic(BaseModel):
    id: int
    name: str
    balance_due: str
    advance_left: str = "0.00"
    outstanding: str = "0.00"
    notes: Optional[str] = None


class FreightLedgerOut(BaseModel):
    id: int
    entry_type: str
    amount: str
    signed_amount: Optional[str] = None
    running_balance: Optional[str] = None
    customer_bill_id: Optional[int] = None
    party_label: Optional[str] = None
    bill_number: Optional[str] = None
    expense_id: Optional[int] = None
    transaction_ref: Optional[str] = None
    notes: Optional[str] = None
    head: Optional[str] = None
    value_date: Optional[date] = None
    payment_receipt_url: Optional[str] = None
    has_document: bool = False
    created_by_name: str
    created_at: str
    display_date: Optional[Union[date, datetime]] = None


class FreightSettleIn(BaseModel):
    amount: Decimal = Field(..., gt=0)
    transaction_ref: str = Field(..., min_length=1, max_length=200)
    notes: Optional[str] = None
    payment_receipt_key: Optional[str] = None
    pay_date: Optional[date] = None


class FreightAdvanceIn(BaseModel):
    amount: Decimal = Field(..., gt=0)
    transaction_ref: str = Field(..., min_length=1, max_length=200)
    notes: Optional[str] = None
    payment_receipt_key: Optional[str] = None
    pay_date: Optional[date] = None


class FreightAdjustIn(BaseModel):
    head: str = Field(..., min_length=1, max_length=120)
    amount: Decimal = Field(..., gt=0)
    direction: str = "owe_more"
    notes: Optional[str] = None
    pay_date: Optional[date] = None


class FreightEntryEditIn(BaseModel):
    amount: Decimal = Field(..., gt=0)
    pay_date: Optional[date] = None
    notes: Optional[str] = None
    head: Optional[str] = None
    direction: Optional[str] = None


class FreightReassignIn(BaseModel):
    freight_agent_id: int
    freight_charges: Optional[Decimal] = Field(None, ge=0)


def _can_see_freight_money(auth: AuthContext) -> bool:
    """Freight dues are 3rd-party financial exposure, not just order data — a purely
    read-only staffer (vendor_orders.read/customer_orders.read with no write access
    anywhere) shouldn't see it, even though they need this endpoint's id/name list
    to render the agent picker while dispatching."""
    if auth.is_admin:
        return True
    return any(auth.has(p) for p in ("ap.read", "ap.write", "finance.write", "vendor_orders.write", "customer_orders.write"))


def _pub(row: FreightAgent, totals: Optional[dict] = None, *, auth: Optional[AuthContext] = None) -> FreightAgentPublic:
    t = totals or {}
    outstanding = t.get("outstanding")
    if outstanding is None:
        outstanding = row.balance_due or Decimal("0")
    outstanding = Decimal(str(outstanding)).quantize(Decimal("0.01"))
    due = outstanding if outstanding > 0 else Decimal("0.00")
    advance = (-outstanding) if outstanding < 0 else Decimal("0.00")
    if t:
        due = Decimal(str(t.get("due", due))).quantize(Decimal("0.01"))
        advance = Decimal(str(t.get("advance_left", advance))).quantize(Decimal("0.01"))
    hide = auth is not None and not _can_see_freight_money(auth)
    return FreightAgentPublic(
        id=row.id,
        name=row.name,
        balance_due="—" if hide else format(due, "f"),
        advance_left="—" if hide else format(advance, "f"),
        outstanding="—" if hide else format(outstanding, "f"),
        notes=row.notes,
    )


def _store_payment_pdf(db: Session, agent: FreightAgent, entry: FreightLedgerEntry) -> Optional[str]:
    try:
        pdf = render_freight_payment_pdf(db, agent_id=agent.id, entry_id=entry.id)
    except Exception:
        return None
    if not storage_configured() or not pdf:
        return None
    slug = vendor_folder_slug(agent.name)
    ref = entry.transaction_ref or f"frt-{entry.id}"
    key = freight_payment_key(slug, f"{ref}-{entry.id}", "pdf")
    try:
        upload_bytes(key, pdf, "application/pdf")
    except Exception:
        return None
    entry.document_key = key
    db.flush()
    return key


def _ensure_default_freight_agent(db: Session) -> None:
    wanted = DEFAULT_FREIGHT_AGENT.lower()
    rows = db.query(FreightAgent).all()
    if any((r.name or "").strip().lower() == wanted for r in rows):
        return
    db.add(FreightAgent(name=DEFAULT_FREIGHT_AGENT))
    db.commit()


@router.get("", response_model=List[FreightAgentPublic])
def list_freight_agents(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_any_permission("vendor_orders.read", "customer_orders.read")),
    names_only: bool = Query(False),
):
    _ensure_default_freight_agent(db)
    rows = db.query(FreightAgent).order_by(FreightAgent.name.asc()).all()
    if names_only:
        return [_pub(r, auth=auth) for r in rows]
    dirty = False
    out = []
    for r in rows:
        totals = agent_freight_totals(db, r.id)
        if (r.balance_due or Decimal("0")).quantize(Decimal("0.01")) != totals["outstanding"]:
            r.balance_due = totals["outstanding"]
            dirty = True
        out.append(_pub(r, totals, auth=auth))
    if dirty:
        db.commit()
    return out


@router.post("", response_model=FreightAgentPublic, status_code=201)
def create_freight_agent(body: FreightAgentIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    row = FreightAgent(name=body.name.strip(), notes=(body.notes or "").strip() or None)
    db.add(row)
    db.flush()
    log_from_auth(db, auth, action="create", entity_type="freight_agent", entity_id=row.id, entity_label=row.name)
    db.commit()
    db.refresh(row)
    return _pub(row)


@router.get("/parcels")
def list_all_parcels(
    agent_id: Optional[int] = Query(None),
    status: str = Query("all", pattern="^(all|pending|picked)$"),
    day: str = Query("all", pattern=r"^(all|today|\d{4}-\d{2}-\d{2})$"),
    db: Session = Depends(get_db),
    # Dispatch is the very next step after billing for every non-admin staffer with
    # customer_orders.write — this used to be require_admin, so the parcel list (and
    # pick/reassign below) 403'd for everyone but a full admin account even though
    # nothing else in the bill lifecycle needs admin.
    auth: AuthContext = Depends(require_permission("customer_orders.read")),
):
    """Parcels assigned to freight agents — pending until ticked picked (then dues post)."""
    return list_parcels(db, agent_id=agent_id, status=status, day=day)


@router.post("/parcels/{bill_id}/pick", status_code=201)
def pick_freight_parcel(
    bill_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    bill = pick_parcel(db, bill_id=bill_id, actor_name=auth.actor_name)
    agent = db.get(FreightAgent, bill.freight_agent_id) if bill.freight_agent_id else None
    log_from_auth(
        db, auth, action="freight_pick", entity_type="customer_bill",
        entity_id=bill.id, entity_label=bill.bill_number,
        detail=f"agent {agent.name if agent else bill.freight_agent_id} ₹{bill.freight_charges}",
    )
    db.commit()
    from app.services.whatsapp_notify import schedule_whatsapp
    schedule_whatsapp("dispatched", bill.id)
    return {"ok": True, "bill_id": bill.id, "status": "picked", "freight_agent_id": bill.freight_agent_id}


class DispatchPickIn(BaseModel):
    transport_mode: str
    freight_agent_id: Optional[int] = None
    freight_charges: Optional[str] = None
    transport_receipt_number: Optional[str] = None
    packaging_charges: Optional[str] = None
    additional_charges: list = []
    narration: Optional[str] = None
    pick_narration: Optional[str] = None


class DispatchNoteIn(BaseModel):
    bill_ids: list[int]
    narration: str


@router.post("/parcels/dispatch-note")
def save_dispatch_note(
    body: DispatchNoteIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    text = " ".join((body.narration or "").split())
    if not text:
        raise HTTPException(400, "Enter a narration")
    if not body.bill_ids:
        raise HTTPException(400, "No bill to dispatch")
    now = datetime.now(timezone.utc)
    bills = (
        db.query(CustomerBill)
        .filter(CustomerBill.id.in_(body.bill_ids), CustomerBill.deleted_at.is_(None), CustomerBill.cancelled_at.is_(None))
        .all()
    )
    if len(bills) != len(set(body.bill_ids)):
        raise HTTPException(404, "bill not found")
    for bill in bills:
        if bill.freight_picked_at:
            continue
        bill.dispatch_narration = text[:800]
        bill.dispatch_narration_by = auth.actor_name
        bill.dispatch_narration_at = now
    db.commit()
    return {"ok": True}


@router.post("/parcels/{bill_id}/mark-picked")
def mark_parcel_picked(
    bill_id: int,
    body: DispatchPickIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    bill = save_dispatch_and_pick(
        db,
        bill_id=bill_id,
        transport_mode=body.transport_mode,
        freight_agent_id=body.freight_agent_id,
        freight_charges=body.freight_charges,
        transport_receipt_number=body.transport_receipt_number,
        packaging_charges=body.packaging_charges,
        additional_charges=body.additional_charges,
        narration=body.narration,
        pick_narration=body.pick_narration,
        actor_name=auth.actor_name,
    )
    log_from_auth(
        db, auth, action="picked", entity_type="customer_bill",
        entity_id=bill.id, entity_label=bill.bill_number,
        detail=f"marked picked · {bill.transport_mode}",
    )
    db.commit()
    return {"ok": True, "bill_id": bill.id, "status": "picked"}


@router.get("/parcels/{bill_id}/story")
def parcel_story_endpoint(
    bill_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.read")),
):
    return parcel_story(db, bill_id)


@router.patch("/parcels/{bill_id}")
def reassign_freight_parcel(
    bill_id: int,
    body: FreightReassignIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("customer_orders.write")),
):
    bill = reassign_parcel(
        db,
        bill_id=bill_id,
        freight_agent_id=body.freight_agent_id,
        freight_charges=body.freight_charges,
    )
    agent = db.get(FreightAgent, bill.freight_agent_id) if bill.freight_agent_id else None
    log_from_auth(
        db, auth, action="freight_reassign", entity_type="customer_bill",
        entity_id=bill.id, entity_label=bill.bill_number,
        detail=f"→ agent {agent.name if agent else bill.freight_agent_id} ₹{bill.freight_charges}",
    )
    db.commit()
    return {
        "ok": True,
        "bill_id": bill.id,
        "freight_agent_id": bill.freight_agent_id,
        "freight_charges": format(bill.freight_charges or 0, "f"),
        "status": "pending",
    }


@router.patch("/{agent_id}", response_model=FreightAgentPublic)
def update_freight_agent(agent_id: int, body: FreightAgentIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    row = db.get(FreightAgent, agent_id)
    if not row:
        raise HTTPException(404, "freight agent not found")
    row.name = body.name.strip()
    row.notes = (body.notes or "").strip() or None
    log_from_auth(db, auth, action="update", entity_type="freight_agent", entity_id=row.id, entity_label=row.name)
    db.commit()
    db.refresh(row)
    return _pub(row, agent_freight_totals(db, row.id))


@router.get("/{agent_id}/parcels")
def list_agent_parcels(
    agent_id: int,
    status: str = Query("all", pattern="^(all|pending|picked)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    if not db.get(FreightAgent, agent_id):
        raise HTTPException(404, "freight agent not found")
    return list_parcels(db, agent_id=agent_id, status=status)


@router.get("/{agent_id}/ledger", response_model=List[FreightLedgerOut])
def get_ledger(agent_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    if not db.get(FreightAgent, agent_id):
        raise HTTPException(404, "freight agent not found")
    rows = build_freight_ledger(db, agent_id)
    return [
        FreightLedgerOut(
            id=r["id"],
            entry_type=r["entry_type"],
            amount=r["amount"],
            signed_amount=r.get("signed_amount"),
            running_balance=r.get("running_balance"),
            customer_bill_id=r.get("customer_bill_id"),
            party_label=r.get("party_label"),
            bill_number=r.get("bill_number"),
            expense_id=r.get("expense_id"),
            transaction_ref=r.get("transaction_ref"),
            notes=r.get("notes"),
            head=r.get("head"),
            value_date=r.get("value_date"),
            payment_receipt_url=r.get("payment_receipt_url"),
            has_document=bool(r.get("has_document")),
            created_by_name=r["created_by_name"],
            created_at=r["created_at"] or "",
            display_date=r.get("display_date"),
        )
        for r in rows
    ]


def _pay_freight(
    db: Session,
    *,
    agent: FreightAgent,
    amount: Decimal,
    transaction_ref: str,
    notes: Optional[str],
    payment_receipt_key: Optional[str],
    auth: AuthContext,
    as_advance: bool,
    pay_date: Optional[date] = None,
) -> dict:
    totals = agent_freight_totals(db, agent.id)
    due = totals["due"]
    when = pay_date or today_ist()
    if as_advance:
        entry_type = "advance"
        expense_desc = f"Freight advance — {agent.name}"
        action = "freight_advance"
    else:
        if due <= 0:
            raise HTTPException(400, "no balance due — use Pay advance instead")
        if amount > due:
            raise HTTPException(400, f"cannot settle more than due ₹{due}")
        entry_type = "settlement"
        expense_desc = f"Freight settlement — {agent.name}"
        action = "freight_settle"

    expense = Expense(
        expense_date=when,
        category="transport",
        description=expense_desc,
        amount=amount,
        reference=transaction_ref.strip(),
        freight_agent_id=agent.id,
        created_by_name=auth.actor_name,
    )
    db.add(expense)
    db.flush()

    entry = post_freight_settlement(
        db,
        agent_id=agent.id,
        amount=amount,
        expense_id=expense.id,
        transaction_ref=transaction_ref.strip(),
        notes=notes,
        actor_name=auth.actor_name,
        payment_receipt_key=payment_receipt_key,
        entry_type=entry_type,
        value_date=when,
    )
    _store_payment_pdf(db, agent, entry)
    log_from_auth(
        db,
        auth,
        action=action,
        entity_type="freight_agent",
        entity_id=agent.id,
        entity_label=agent.name,
        detail=f"₹{amount} ref {transaction_ref.strip()}",
    )
    db.commit()
    db.refresh(agent)
    after = agent_freight_totals(db, agent.id)
    return {
        "ok": True,
        "entry_id": entry.id,
        "expense_id": expense.id,
        "balance_due": format(after["due"], "f"),
        "advance_left": format(after["advance_left"], "f"),
        "outstanding": format(after["outstanding"], "f"),
        "has_document": bool(entry.document_key),
        "payment_receipt_url": presigned_url(entry.payment_receipt_key) if entry.payment_receipt_key else None,
    }


@router.post("/{agent_id}/settle", status_code=201)
def settle_freight_agent(
    agent_id: int,
    body: FreightSettleIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    agent = (
        db.query(FreightAgent)
        .filter(FreightAgent.id == agent_id)
        .with_for_update()
        .first()
    )
    if not agent:
        raise HTTPException(404, "freight agent not found")
    amount = body.amount.quantize(Decimal("0.01"))
    return _pay_freight(
        db,
        agent=agent,
        amount=amount,
        transaction_ref=body.transaction_ref,
        notes=body.notes,
        payment_receipt_key=body.payment_receipt_key,
        auth=auth,
        as_advance=False,
        pay_date=body.pay_date,
    )


@router.post("/{agent_id}/advance", status_code=201)
def pay_freight_advance(
    agent_id: int,
    body: FreightAdvanceIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    """Pay prepaid cash to agent — offsets future freight charges."""
    agent = (
        db.query(FreightAgent)
        .filter(FreightAgent.id == agent_id)
        .with_for_update()
        .first()
    )
    if not agent:
        raise HTTPException(404, "freight agent not found")
    amount = body.amount.quantize(Decimal("0.01"))
    return _pay_freight(
        db,
        agent=agent,
        amount=amount,
        transaction_ref=body.transaction_ref,
        notes=body.notes,
        payment_receipt_key=body.payment_receipt_key,
        auth=auth,
        as_advance=True,
        pay_date=body.pay_date,
    )


@router.post("/{agent_id}/adjust", status_code=201)
def adjust_freight_agent(
    agent_id: int,
    body: FreightAdjustIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    agent = db.query(FreightAgent).filter(FreightAgent.id == agent_id).with_for_update().first()
    if not agent:
        raise HTTPException(404, "freight agent not found")
    head = " ".join(body.head.split())
    if not head:
        raise HTTPException(400, "Enter the head")
    owe_less = body.direction == "owe_less"
    amount = body.amount.quantize(Decimal("0.01"))
    when = body.pay_date or today_ist()
    signed = as_signed_decrease(amount) if owe_less else as_signed_increase(amount)
    expense = Expense(
        expense_date=when,
        category=head,
        description=f"Freight adjustment — {agent.name} — {head}",
        amount=amount,
        reference=head,
        freight_agent_id=agent.id,
        is_cash=False,
        created_by_name=auth.actor_name,
    )
    db.add(expense)
    db.flush()
    entry = post_freight_settlement(
        db,
        agent_id=agent.id,
        amount=amount,
        expense_id=expense.id,
        transaction_ref=head,
        notes=body.notes or head,
        actor_name=auth.actor_name,
        entry_type="adjustment",
        value_date=when,
        head=head,
        signed_amount=signed,
    )
    log_from_auth(
        db, auth, action="freight_adjust", entity_type="freight_agent", entity_id=agent.id,
        entity_label=agent.name, detail=f"{head} ₹{amount}",
    )
    db.commit()
    return {"ok": True, "entry_id": entry.id, "expense_id": expense.id}


@router.patch("/entries/{entry_id}")
def edit_freight_entry(
    entry_id: int,
    body: FreightEntryEditIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    entry = db.get(FreightLedgerEntry, entry_id)
    if not entry:
        raise HTTPException(404, "entry not found")
    if entry.entry_type not in ("settlement", "advance", "adjustment"):
        raise HTTPException(400, "Only a payment or an adjustment can be edited")
    agent = db.query(FreightAgent).filter(FreightAgent.id == entry.freight_agent_id).with_for_update().first()
    amount = body.amount.quantize(Decimal("0.01"))
    if entry.entry_type == "settlement":
        due = agent_freight_totals(db, agent.id)["due"]
        room = due + mag(entry.amount)
        if amount > room:
            raise HTTPException(400, f"cannot settle more than due ₹{room}")
        signed = as_signed_decrease(amount)
    elif entry.entry_type == "advance":
        signed = as_signed_decrease(amount)
    else:
        direction = body.direction
        if direction not in ("owe_more", "owe_less"):
            direction = "owe_less" if entry.amount < 0 else "owe_more"
        signed = as_signed_decrease(amount) if direction == "owe_less" else as_signed_increase(amount)
        if body.head:
            entry.head = " ".join(body.head.split())
    entry.amount = signed
    if body.pay_date:
        entry.value_date = body.pay_date
    if body.notes is not None:
        entry.notes = body.notes.strip() or None
    if entry.expense_id:
        expense = db.get(Expense, entry.expense_id)
        if expense:
            expense.amount = amount
            if body.pay_date:
                expense.expense_date = body.pay_date
            if entry.entry_type == "adjustment" and entry.head:
                expense.category = entry.head
                expense.description = f"Freight adjustment — {agent.name} — {entry.head}"
                expense.reference = entry.head
    from app.services.freight_ledger import recompute_balance_due
    recompute_balance_due(db, agent.id)
    db.commit()
    return {"ok": True, "entry_id": entry.id}


@router.post("/upload-payment-receipt")
async def upload_freight_payment_receipt(
    agent_id: int = Form(...),
    payment_ref: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
) -> dict:
    if not storage_configured():
        raise HTTPException(503, "S3 not configured")
    agent = db.get(FreightAgent, agent_id)
    if not agent:
        raise HTTPException(400, "freight agent not found")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "file too large (max 10MB)")
    ext = "pdf"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()[:8]
    slug = vendor_folder_slug(agent.name)
    key = freight_payment_key(slug, payment_ref, ext)
    upload_bytes(key, data, file.content_type or "application/pdf")
    return {"key": key, "url": presigned_url(key)}
