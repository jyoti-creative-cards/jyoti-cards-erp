from __future__ import annotations

from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin
from app.models.customer import Customer
from app.schemas.accounts_receivable import ArCustomerDetail, ArCustomerSummary, ArLedgerEntryOut, ArSettlementIn
from app.services.activity import log_from_auth
from app.services.ar_ledger import build_ar_ledger, customer_ar_totals, list_ar_customers, post_payment_entry

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
    if not customer:
        raise HTTPException(404, "customer not found")
    totals = customer_ar_totals(db, customer_id)
    entries = build_ar_ledger(db, customer_id)
    return ArCustomerDetail(
        customer_id=customer_id,
        customer_label=_customer_label(db, customer_id),
        outstanding=format(totals["outstanding"], "f"),
        bill_total=format(totals["bill_total"], "f"),
        payment_total=format(totals["payment_total"], "f"),
        entries=[ArLedgerEntryOut(**e) for e in entries],
    )


@router.post("/customer/{customer_id}/settle", response_model=ArLedgerEntryOut, status_code=status.HTTP_201_CREATED)
def settle_customer_ar(
    customer_id: int,
    body: ArSettlementIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "customer not found")
    totals = customer_ar_totals(db, customer_id)
    outstanding = totals["outstanding"]
    if outstanding <= 0:
        raise HTTPException(400, "no outstanding balance to settle")
    amount = body.amount.quantize(Decimal("0.01"))
    if amount > outstanding:
        raise HTTPException(400, f"payment cannot exceed outstanding ₹{outstanding}")

    entry = post_payment_entry(
        db,
        customer_id=customer_id,
        amount=amount,
        payment_ref=body.payment_ref.strip(),
        payment_comment=body.comment,
        description=f"Payment {body.payment_ref.strip()} — ₹{amount}",
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
        detail=f"₹{amount} ref {body.payment_ref.strip()}",
    )
    db.commit()
    db.refresh(entry)
    ledger = build_ar_ledger(db, customer_id)
    match = next((e for e in ledger if e["id"] == entry.id), None)
    if not match:
        raise HTTPException(500, "payment recorded but ledger entry missing")
    return ArLedgerEntryOut(**match)
