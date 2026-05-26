from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db, sql_is_active_true
from app.deps import require_admin
from app.models.bank_reconciliation import BankAccount, BankReconciliation
from app.services.catalog_storage import presigned_url, storage_configured, upload_bytes

router = APIRouter(prefix="/bank", tags=["bank"])

_STMT_PREFIX = "bank_statements"


class BankAccountCreate(BaseModel):
    name: str = Field(..., min_length=1)
    account_number: Optional[str] = None
    bank_name: Optional[str] = None
    ifsc: Optional[str] = None


class BankAccountPublic(BaseModel):
    id: int
    name: str
    account_number: Optional[str]
    bank_name: Optional[str]
    ifsc: Optional[str]
    is_active: bool

    model_config = {"from_attributes": True}


class ReconciliationPublic(BaseModel):
    id: int
    bank_account_id: int
    period_start: date
    period_end: date
    opening_balance: str
    closing_balance_bank: str
    closing_balance_books: str
    difference: str
    notes: Optional[str]
    statement_url: Optional[str]
    is_finalised: bool
    created_at: str

    model_config = {"from_attributes": True}


def _recon_pub(row: BankReconciliation) -> ReconciliationPublic:
    url = presigned_url(row.statement_key) if row.statement_key else None
    return ReconciliationPublic(
        id=row.id,
        bank_account_id=row.bank_account_id,
        period_start=row.period_start,
        period_end=row.period_end,
        opening_balance=str(row.opening_balance),
        closing_balance_bank=str(row.closing_balance_bank),
        closing_balance_books=str(row.closing_balance_books),
        difference=str(row.difference),
        notes=row.notes,
        statement_url=url,
        is_finalised=row.is_finalised,
        created_at=row.created_at.isoformat(),
    )


@router.get("/accounts", response_model=List[BankAccountPublic], dependencies=[Depends(require_admin)])
def list_bank_accounts(db: Session = Depends(get_db)) -> List[BankAccountPublic]:
    return db.query(BankAccount).filter(sql_is_active_true(BankAccount.is_active)).order_by(BankAccount.id).all()


@router.post("/accounts", response_model=BankAccountPublic, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_bank_account(body: BankAccountCreate, db: Session = Depends(get_db)) -> BankAccountPublic:
    row = BankAccount(
        name=body.name.strip(),
        account_number=(body.account_number or "").strip() or None,
        bank_name=(body.bank_name or "").strip() or None,
        ifsc=(body.ifsc or "").strip() or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/reconciliations", response_model=List[ReconciliationPublic], dependencies=[Depends(require_admin)])
def list_reconciliations(
    db: Session = Depends(get_db),
    bank_account_id: Optional[int] = Query(None, ge=1),
) -> List[ReconciliationPublic]:
    q = db.query(BankReconciliation).order_by(BankReconciliation.id.desc())
    if bank_account_id:
        q = q.filter(BankReconciliation.bank_account_id == bank_account_id)
    return [_recon_pub(r) for r in q.limit(200).all()]


@router.post("/reconciliations", response_model=ReconciliationPublic, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_reconciliation(
    db: Session = Depends(get_db),
    bank_account_id: int = Form(...),
    period_start: str = Form(...),
    period_end: str = Form(...),
    opening_balance: str = Form("0"),
    closing_balance_bank: str = Form("0"),
    closing_balance_books: str = Form("0"),
    notes: Optional[str] = Form(None),
    statement: Optional[UploadFile] = File(None),
) -> ReconciliationPublic:
    ba = db.get(BankAccount, bank_account_id)
    if ba is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="bank account not found")

    try:
        ps = date.fromisoformat(period_start.strip()[:10])
        pe = date.fromisoformat(period_end.strip()[:10])
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"invalid date: {e}") from e

    from decimal import Decimal
    ob = Decimal(opening_balance or "0")
    cbb = Decimal(closing_balance_bank or "0")
    cbbooks = Decimal(closing_balance_books or "0")
    diff = cbb - cbbooks

    stmt_key: Optional[str] = None
    if statement and getattr(statement, "filename", None):
        if not storage_configured():
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="S3 not configured")
        raw = statement.file.read()
        if raw:
            suf = Path(statement.filename or "").suffix.lower() or ".bin"
            if suf not in (".pdf", ".png", ".jpg", ".jpeg", ".xlsx", ".csv"):
                suf = ".bin"
            stmt_key = f"{_STMT_PREFIX}/{uuid.uuid4().hex}{suf}"
            upload_bytes(stmt_key, raw, statement.content_type or "application/octet-stream")

    row = BankReconciliation(
        bank_account_id=bank_account_id,
        period_start=ps,
        period_end=pe,
        opening_balance=ob,
        closing_balance_bank=cbb,
        closing_balance_books=cbbooks,
        difference=diff,
        notes=(notes or "").strip() or None,
        statement_key=stmt_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _recon_pub(row)


@router.post("/reconciliations/{rec_id}/finalise", dependencies=[Depends(require_admin)])
def finalise_reconciliation(rec_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(BankReconciliation, rec_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="reconciliation not found")
    row.is_finalised = True
    db.add(row)
    db.commit()
    return {"ok": True, "id": rec_id}
