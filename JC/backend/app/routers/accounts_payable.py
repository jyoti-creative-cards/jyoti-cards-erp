from __future__ import annotations

from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin
from app.models.vendor import Vendor
from app.schemas.accounts_payable import ApLedgerEntryOut, ApSettlementIn, ApVendorDetail, ApVendorSummary
from app.services.activity import log_from_auth
from app.services.ap_ledger import build_ap_ledger, build_ap_statement, list_ap_vendors, post_payment_entry, vendor_ap_totals, _vendor_label
from app.services.storage import payment_receipt_key, presigned_url, storage_configured, upload_bytes, vendor_folder_slug

router = APIRouter(prefix="/accounts-payable", tags=["accounts-payable"])


@router.get("", response_model=List[ApVendorSummary])
def list_accounts_payable(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return [ApVendorSummary(**row) for row in list_ap_vendors(db)]


@router.get("/vendor/{vendor_id}", response_model=ApVendorDetail)
def get_vendor_ap(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    vendor = db.get(Vendor, vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    statement = build_ap_statement(db, vendor_id)
    return ApVendorDetail(
        vendor_id=vendor_id,
        vendor_label=_vendor_label(db, vendor_id),
        outstanding=statement["outstanding"],
        bill_total=statement["bill_total"],
        debit_note_total=statement["debit_note_total"],
        payment_total=statement["payment_total"],
        entries=[ApLedgerEntryOut(**e) for e in statement["entries"]],
        bills=statement["bills"],
        payments=statement["payments"],
    )


@router.post("/vendor/{vendor_id}/settle", response_model=ApLedgerEntryOut, status_code=status.HTTP_201_CREATED)
def settle_vendor_ap(
    vendor_id: int,
    body: ApSettlementIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    vendor = db.get(Vendor, vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    totals = vendor_ap_totals(db, vendor_id)
    outstanding = totals["outstanding"]
    if outstanding <= 0:
        raise HTTPException(400, "no outstanding balance to settle")
    amount = body.amount.quantize(Decimal("0.01"))
    if amount > outstanding:
        raise HTTPException(400, f"payment cannot exceed outstanding ₹{outstanding}")

    entry = post_payment_entry(
        db,
        vendor_id=vendor_id,
        amount=amount,
        payment_ref=body.payment_ref.strip(),
        payment_receipt_key=body.payment_receipt_key,
        payment_comment=body.comment,
        description=f"Payment {body.payment_ref.strip()} — ₹{amount}",
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        actor_name=auth.actor_name,
    )
    log_from_auth(
        db,
        auth,
        action="ap_payment",
        entity_type="accounts_payable",
        entity_id=vendor_id,
        entity_label=_vendor_label(db, vendor_id),
        detail=f"₹{amount} ref {body.payment_ref.strip()}",
    )
    db.commit()
    db.refresh(entry)
    ledger = build_ap_ledger(db, vendor_id)
    match = next((e for e in ledger if e["id"] == entry.id), None)
    if not match:
        raise HTTPException(500, "payment recorded but ledger entry missing")
    return ApLedgerEntryOut(**match)


@router.post("/upload-payment-receipt")
async def upload_payment_receipt(
    vendor_id: int = Form(...),
    payment_ref: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
) -> dict:
    if not storage_configured():
        raise HTTPException(503, "S3 not configured")
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(400, "vendor not found")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "file too large (max 10MB)")
    ext = "pdf"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()[:8]
    slug = vendor_folder_slug(vendor.business_name)
    key = payment_receipt_key(slug, payment_ref, ext)
    upload_bytes(key, data, file.content_type or "application/pdf")
    return {"key": key, "url": presigned_url(key)}
