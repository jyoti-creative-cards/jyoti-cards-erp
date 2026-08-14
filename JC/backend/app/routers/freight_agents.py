from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin, require_any_permission
from app.models.expense import Expense
from app.models.freight_agent import FreightAgent, FreightLedgerEntry
from app.services.activity import log_from_auth
from app.services.freight_ledger import (
    agent_freight_totals,
    build_freight_ledger,
    post_freight_settlement,
)
from app.services.freight_parcels import list_parcels, pick_parcel, reassign_parcel
from app.services.report_pdfs import render_freight_payment_pdf
from app.services.storage import (
    freight_payment_key,
    presigned_url,
    storage_configured,
    upload_bytes,
    vendor_folder_slug,
)

router = APIRouter(prefix="/freight-agents", tags=["freight-agents"])


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
    payment_receipt_url: Optional[str] = None
    has_document: bool = False
    created_by_name: str
    created_at: str


class FreightSettleIn(BaseModel):
    amount: Decimal = Field(..., gt=0)
    transaction_ref: str = Field(..., min_length=1, max_length=200)
    notes: Optional[str] = None
    payment_receipt_key: Optional[str] = None


class FreightAdvanceIn(BaseModel):
    amount: Decimal = Field(..., gt=0)
    transaction_ref: str = Field(..., min_length=1, max_length=200)
    notes: Optional[str] = None
    payment_receipt_key: Optional[str] = None


class FreightReassignIn(BaseModel):
    freight_agent_id: int
    freight_charges: Optional[Decimal] = Field(None, ge=0)


def _pub(row: FreightAgent, totals: Optional[dict] = None) -> FreightAgentPublic:
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
    return FreightAgentPublic(
        id=row.id,
        name=row.name,
        balance_due=format(due, "f"),
        advance_left=format(advance, "f"),
        outstanding=format(outstanding, "f"),
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


@router.get("", response_model=List[FreightAgentPublic])
def list_freight_agents(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_any_permission("vendor_orders.read", "customer_orders.read")),
):
    rows = db.query(FreightAgent).order_by(FreightAgent.name.asc()).all()
    dirty = False
    out = []
    for r in rows:
        totals = agent_freight_totals(db, r.id)
        if (r.balance_due or Decimal("0")).quantize(Decimal("0.01")) != totals["outstanding"]:
            r.balance_due = totals["outstanding"]
            dirty = True
        out.append(_pub(r, totals))
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
    day: str = Query("all", pattern="^(all|today)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    """Parcels assigned to freight agents — pending until ticked picked (then dues post)."""
    return list_parcels(db, agent_id=agent_id, status=status, day=day)


@router.post("/parcels/{bill_id}/pick", status_code=201)
def pick_freight_parcel(
    bill_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    bill = pick_parcel(db, bill_id=bill_id, actor_name=auth.actor_name)
    log_from_auth(
        db, auth, action="freight_pick", entity_type="customer_bill",
        entity_id=bill.id, entity_label=bill.bill_number,
        detail=f"agent {bill.freight_agent_id} ₹{bill.freight_charges}",
    )
    db.commit()
    return {"ok": True, "bill_id": bill.id, "status": "picked", "freight_agent_id": bill.freight_agent_id}


@router.patch("/parcels/{bill_id}")
def reassign_freight_parcel(
    bill_id: int,
    body: FreightReassignIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    bill = reassign_parcel(
        db,
        bill_id=bill_id,
        freight_agent_id=body.freight_agent_id,
        freight_charges=body.freight_charges,
    )
    log_from_auth(
        db, auth, action="freight_reassign", entity_type="customer_bill",
        entity_id=bill.id, entity_label=bill.bill_number,
        detail=f"→ agent {bill.freight_agent_id}",
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
            payment_receipt_url=r.get("payment_receipt_url"),
            has_document=bool(r.get("has_document")),
            created_by_name=r["created_by_name"],
            created_at=r["created_at"] or "",
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
) -> dict:
    totals = agent_freight_totals(db, agent.id)
    due = totals["due"]
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
        expense_date=date.today(),
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
    )


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
