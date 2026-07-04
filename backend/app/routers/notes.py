from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.credit_debit_note import CreditNote, DebitNote
from app.models.customer_order import CustomerOrder
from app.services.accounting import ACC_AP, ACC_AR, ACC_REV, ACC_PUR, create_journal, seed_chart_accounts
from app.services.catalog_storage import presigned_url, storage_configured, upload_bytes

router = APIRouter(prefix="/notes", tags=["notes"])
_NOTE_PREFIX = "credit_debit_notes"


def _apply_debit_to_ap(db: Session, vendor_order_id: int, vendor_id: int, amount: Decimal) -> None:
    """Reduce open AP bills for a vendor order by debit note amount (FIFO)."""
    from app.models.ap_bill import APBill
    from app.models.vendor_bill import VendorBill
    remaining = amount
    # Find all open APBills for this vendor order (oldest first)
    ap_bills = (
        db.query(APBill)
        .join(VendorBill, APBill.vendor_bill_id == VendorBill.id)
        .filter(
            VendorBill.vendor_order_id == vendor_order_id,
            APBill.status == "open",
        )
        .order_by(APBill.id.asc())
        .all()
    )
    for ap in ap_bills:
        if remaining <= 0:
            break
        ap_balance = Decimal(str(ap.amount))
        if ap_balance <= remaining:
            remaining -= ap_balance
            ap.amount = Decimal("0")
            ap.status = "paid"
        else:
            ap.amount = ap_balance - remaining
            remaining = Decimal("0")
        db.add(ap)


def _upload_doc(file: Optional[UploadFile]) -> Optional[str]:
    if not file or not getattr(file, "filename", None):
        return None
    if not storage_configured():
        return None
    raw = file.file.read()
    if not raw:
        return None
    suf = Path(file.filename or "").suffix.lower() or ".bin"
    if suf not in (".pdf", ".png", ".jpg", ".jpeg"):
        suf = ".bin"
    key = f"{_NOTE_PREFIX}/{uuid.uuid4().hex}{suf}"
    upload_bytes(key, raw, file.content_type or "application/octet-stream")
    return key


class CreditNotePublic(BaseModel):
    id: int
    customer_order_id: int
    customer_id: int
    amount: str
    reason: Optional[str]
    status: str
    document_url: Optional[str]
    note_date: Optional[date]
    created_at: str


class DebitNotePublic(BaseModel):
    id: int
    vendor_order_id: Optional[int]
    vendor_id: int
    amount: str
    reason: Optional[str]
    status: str
    note_type: str
    items: Optional[list]
    document_url: Optional[str]
    note_date: Optional[date]
    created_at: str


def _cn_pub(row: CreditNote) -> CreditNotePublic:
    url = presigned_url(row.document_key) if row.document_key else None
    return CreditNotePublic(
        id=row.id,
        customer_order_id=row.customer_order_id,
        customer_id=row.customer_id,
        amount=str(row.amount),
        reason=row.reason,
        status=row.status,
        document_url=url,
        note_date=row.note_date,
        created_at=row.created_at.isoformat(),
    )


def _dn_pub(row: DebitNote) -> DebitNotePublic:
    url = presigned_url(row.document_key) if row.document_key else None
    return DebitNotePublic(
        id=row.id,
        vendor_order_id=getattr(row, "vendor_order_id", None),
        vendor_id=row.vendor_id,
        amount=str(row.amount),
        reason=row.reason,
        status=row.status,
        note_type=getattr(row, "note_type", "value") or "value",
        items=getattr(row, "items", None),
        document_url=url,
        note_date=row.note_date,
        created_at=row.created_at.isoformat(),
    )


@router.get("/credit", response_model=List[CreditNotePublic], dependencies=[Depends(require_admin)])
def list_credit_notes(db: Session = Depends(get_db)) -> List[CreditNotePublic]:
    return [_cn_pub(r) for r in db.query(CreditNote).order_by(CreditNote.id.desc()).limit(500).all()]


@router.post("/credit", response_model=CreditNotePublic, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_credit_note(
    db: Session = Depends(get_db),
    customer_order_id: int = Form(...),
    amount: str = Form(...),
    reason: Optional[str] = Form(None),
    note_date: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
) -> CreditNotePublic:
    order = db.get(CustomerOrder, customer_order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
    amt = Decimal(amount)
    if amt <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="amount must be positive")
    nd: Optional[date] = None
    if note_date:
        try:
            nd = date.fromisoformat(str(note_date).strip()[:10])
        except ValueError:
            pass
    doc_key = _upload_doc(file)
    seed_chart_accounts(db)
    row = CreditNote(
        customer_order_id=customer_order_id,
        customer_id=order.customer_id,
        amount=amt,
        reason=(reason or "").strip() or None,
        document_key=doc_key,
        note_date=nd,
        status="open",
    )
    db.add(row)
    db.flush()
    nd_date = nd or date.today()
    posted_at = datetime.combine(nd_date, time(12, 0, 0), tzinfo=timezone.utc)
    try:
        je = create_journal(
            db,
            memo=f"Credit note #{row.id}",
            ref_type="credit_note",
            ref_id=row.id,
            lines=[
                (ACC_REV, amt, Decimal("0")),
                (ACC_AR, Decimal("0"), amt),
            ],
            posted_at=posted_at,
        )
    except ValueError as e:
        if str(e).startswith("Cannot post:"):
            raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e)) from e
        raise
    row.journal_entry_id = je.id
    db.commit()
    db.refresh(row)
    return _cn_pub(row)


@router.get("/debit", response_model=List[DebitNotePublic], dependencies=[Depends(require_admin)])
def list_debit_notes(
    db: Session = Depends(get_db),
    vendor_order_id: Optional[int] = None,
) -> List[DebitNotePublic]:
    q = db.query(DebitNote).order_by(DebitNote.id.desc())
    if vendor_order_id is not None:
        q = q.filter(DebitNote.vendor_order_id == vendor_order_id)
    return [_dn_pub(r) for r in q.limit(500).all()]


@router.post("/debit", response_model=DebitNotePublic, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_debit_note(
    db: Session = Depends(get_db),
    vendor_order_id: int = Form(...),
    amount: str = Form(...),
    note_type: str = Form("value"),
    items_json: Optional[str] = Form(None),
    reason: Optional[str] = Form(None),
    note_date: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
) -> DebitNotePublic:
    from app.models.vendor_order import VendorOrder as VendorOrderModel
    vo = db.get(VendorOrderModel, vendor_order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    vendor_id: int = vo.vendor_id

    amt = Decimal(amount)
    if amt <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="amount must be positive")
    nd: Optional[date] = None
    if note_date:
        try:
            nd = date.fromisoformat(str(note_date).strip()[:10])
        except ValueError:
            pass

    items_data = None
    if items_json:
        import json as _json
        try:
            items_data = _json.loads(items_json)
        except Exception:
            pass

    doc_key = _upload_doc(file)
    seed_chart_accounts(db)
    row = DebitNote(
        purchase_order_id=None,
        vendor_order_id=vendor_order_id,
        vendor_id=vendor_id,
        amount=amt,
        reason=(reason or "").strip() or None,
        document_key=doc_key,
        note_date=nd,
        note_type=note_type if note_type in ("value", "item") else "value",
        items=items_data,
        status="open",
    )
    db.add(row)
    db.flush()
    nd_date = nd or date.today()
    posted_at = datetime.combine(nd_date, time(12, 0, 0), tzinfo=timezone.utc)
    try:
        je = create_journal(
            db,
            memo=f"Debit note #{row.id}",
            ref_type="debit_note",
            ref_id=row.id,
            lines=[
                (ACC_AP, amt, Decimal("0")),
                (ACC_PUR, Decimal("0"), amt),
            ],
            posted_at=posted_at,
        )
    except ValueError as e:
        if str(e).startswith("Cannot post:"):
            raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e)) from e
        raise
    row.journal_entry_id = je.id

    # Wire debit note to reduce open AP bills for this vendor order
    _apply_debit_to_ap(db, vendor_order_id=vendor_order_id, vendor_id=vendor_id, amount=amt)

    db.commit()
    db.refresh(row)
    return _dn_pub(row)
