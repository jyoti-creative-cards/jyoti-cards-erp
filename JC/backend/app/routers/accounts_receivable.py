from __future__ import annotations

from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin
from app.models.customer import Customer
from app.schemas.accounts_receivable import (
    ArCustomerDetail,
    ArCustomerSummary,
    ArLedgerEntryOut,
    ArSettlementIn,
    OpeningBalanceIn,
)
from app.services.activity import log_from_auth
from app.services.ar_ledger import (
    build_ar_ledger,
    customer_ar_totals,
    get_opening_balance,
    list_ar_customers,
    lock_ar_account,
    post_payment_entry,
    set_opening_balance,
)
from app.services.payment_reverse import reverse_ar_payment
from pydantic import BaseModel, Field

router = APIRouter(prefix="/accounts-receivable", tags=["accounts-receivable"])


def _customer_label(db: Session, customer_id: int) -> str:
    c = db.get(Customer, customer_id)
    return c.business_name if c else f"Customer #{customer_id}"


@router.get("", response_model=List[ArCustomerSummary])
def list_accounts_receivable(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    return [ArCustomerSummary(**row) for row in list_ar_customers(db)]


@router.get("/customer/{customer_id}", response_model=ArCustomerDetail)
def get_customer_ar(customer_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    customer = db.get(Customer, customer_id)
    if not customer or customer.deleted_at:
        raise HTTPException(404, "customer not found")
    totals = customer_ar_totals(db, customer_id)
    entries = build_ar_ledger(db, customer_id)
    opening = get_opening_balance(db, customer_id)
    from app.services.credit_limit import credit_status

    credit = credit_status(db, customer_id, totals=totals)
    return ArCustomerDetail(
        customer_id=customer_id,
        customer_label=_customer_label(db, customer_id),
        outstanding=format(totals["outstanding"], "f"),
        opening_total=format(totals["opening_total"], "f"),
        opening_as_on=opening.value_date.isoformat() if opening and opening.value_date else None,
        bill_total=format(totals["bill_total"], "f"),
        payment_total=format(totals["payment_total"], "f"),
        credit_total=format(totals["credit_total"], "f"),
        credit_limit=credit.get("credit_limit"),
        credit_left=credit.get("left"),
        credit_override=bool(credit.get("credit_override")),
        credit_unlimited=bool(credit.get("unlimited")),
        entries=[ArLedgerEntryOut(**e) for e in entries],
    )


@router.post("/customer/{customer_id}/opening-balance")
def set_customer_opening_balance(
    customer_id: int,
    body: OpeningBalanceIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    customer = db.get(Customer, customer_id)
    if not customer or customer.deleted_at:
        raise HTTPException(404, "customer not found")
    set_opening_balance(
        db,
        customer_id=customer_id,
        amount=body.amount,
        as_on=body.as_on,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        actor_name=auth.actor_name,
    )
    log_from_auth(
        db, auth, action="opening_balance", entity_type="accounts_receivable",
        entity_id=customer_id, entity_label=customer.business_name,
        detail=f"₹{body.amount} as on {body.as_on.isoformat()}",
    )
    db.commit()
    totals = customer_ar_totals(db, customer_id)
    return {"ok": True, "outstanding": format(totals["outstanding"], "f"), "opening_total": format(totals["opening_total"], "f")}


class PaymentReverseIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=400)


@router.post("/customer/{customer_id}/settle", response_model=ArLedgerEntryOut, status_code=status.HTTP_201_CREATED)
def settle_customer_ar(
    customer_id: int,
    body: ArSettlementIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    customer = db.get(Customer, customer_id)
    if not customer or customer.deleted_at:
        raise HTTPException(404, "customer not found")
    lock_ar_account(db, customer_id)
    totals = customer_ar_totals(db, customer_id)
    outstanding = totals["outstanding"]
    if outstanding <= 0:
        raise HTTPException(400, "no outstanding balance to settle")
    amount = body.amount.quantize(Decimal("0.01"))
    if amount > outstanding:
        raise HTTPException(400, f"payment cannot exceed outstanding ₹{outstanding}")

    from app.models.payment_mode import PaymentMode

    mode_name = None
    if body.payment_mode_id:
        mode = db.get(PaymentMode, body.payment_mode_id)
        if not mode or not mode.is_active:
            raise HTTPException(400, "invalid payment mode")
        mode_name = mode.name
    else:
        active_modes = db.query(PaymentMode).filter(PaymentMode.is_active.is_(True)).count()
        if active_modes:
            raise HTTPException(400, "select a payment mode")

    ref = (body.payment_ref or "").strip() or (mode_name or "Payment")
    desc_bits = [f"Payment {ref}"]
    if mode_name:
        desc_bits.append(f"via {mode_name}")
    desc_bits.append(f"— ₹{amount}")

    entry = post_payment_entry(
        db,
        customer_id=customer_id,
        amount=amount,
        payment_ref=ref,
        payment_mode=mode_name,
        payment_comment=body.comment,
        description=" ".join(desc_bits),
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        actor_name=auth.actor_name,
    )
    log_from_auth(
        db,
        auth,
        action="ar_payment",
        entity_type="accounts_receivable",
        entity_id=customer_id,
        entity_label=customer.business_name,
        detail=f"₹{amount} {mode_name or ''} ref {ref}".strip(),
    )
    db.commit()
    db.refresh(entry)
    ledger = build_ar_ledger(db, customer_id)
    match = next((e for e in ledger if e["id"] == entry.id), None)
    if not match:
        raise HTTPException(500, "payment recorded but ledger entry missing")
    return ArLedgerEntryOut(**match)


def _ar_payment_out(db: Session, customer_id: int, entry_id: int) -> ArLedgerEntryOut:
    ledger = build_ar_ledger(db, customer_id)
    match = next((e for e in ledger if e["id"] == entry_id), None)
    if not match:
        raise HTTPException(500, "ledger entry missing")
    return ArLedgerEntryOut(**match)


@router.post("/payments/{entry_id}/reverse", response_model=ArLedgerEntryOut, status_code=status.HTTP_201_CREATED)
def reverse_ar_payment_endpoint(
    entry_id: int,
    body: PaymentReverseIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    from app.models.accounts_receivable import ArLedgerEntry

    orig = db.get(ArLedgerEntry, entry_id)
    if not orig or orig.entry_type != "payment":
        raise HTTPException(404, "AR payment not found")
    lock_ar_account(db, orig.customer_id)
    entry = reverse_ar_payment(
        db,
        entry_id=entry_id,
        reason=body.reason,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        actor_name=auth.actor_name,
        void=False,
    )
    customer = db.get(Customer, orig.customer_id)
    log_from_auth(
        db, auth, action="ar_payment_reverse", entity_type="accounts_receivable",
        entity_id=orig.customer_id, entity_label=customer.business_name if customer else str(orig.customer_id),
        detail=f"reverse #{entry_id} — {body.reason}"[:500],
    )
    db.commit()
    return _ar_payment_out(db, orig.customer_id, entry.id)


@router.post("/payments/{entry_id}/void", response_model=ArLedgerEntryOut, status_code=status.HTTP_201_CREATED)
def void_ar_payment_endpoint(
    entry_id: int,
    body: PaymentReverseIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    from app.models.accounts_receivable import ArLedgerEntry

    orig = db.get(ArLedgerEntry, entry_id)
    if not orig or orig.entry_type != "payment":
        raise HTTPException(404, "AR payment not found")
    lock_ar_account(db, orig.customer_id)
    entry = reverse_ar_payment(
        db,
        entry_id=entry_id,
        reason=body.reason,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        actor_name=auth.actor_name,
        void=True,
    )
    customer = db.get(Customer, orig.customer_id)
    log_from_auth(
        db, auth, action="ar_payment_void", entity_type="accounts_receivable",
        entity_id=orig.customer_id, entity_label=customer.business_name if customer else str(orig.customer_id),
        detail=f"void #{entry_id} — {body.reason}"[:500],
    )
    db.commit()
    return _ar_payment_out(db, orig.customer_id, entry.id)
