from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.ap_bill import APBill
from app.models.ar_invoice import ARInvoice
from app.models.customer import Customer
from app.models.journal_entry import JournalEntry, JournalLine
from app.models.vendor import Vendor
from app.schemas.accounting import (
    APBillPublic,
    ARInvoicePublic,
    CustomerARSummaryPublic,
    DashboardPublic,
    GLAccountRowPublic,
    JournalEntryPublic,
    JournalLinePublic,
    PnLReportPublic,
    VendorAPSummaryPublic,
)
from app.services.accounting import (
    amount_paid_on_ap,
    amount_paid_on_ar,
    count_open_ap,
    count_open_ar,
    ensure_ap_for_vendor_bill,
    gl_activity,
    monthly_pnl_series,
    pnl_for_range,
    record_ap_payment,
    record_ar_payment,
    seed_chart_accounts,
)
from app.services.catalog_storage import presigned_url, storage_configured, upload_bytes

router = APIRouter(prefix="/accounting", tags=["accounting"])

_RECEIPT_PREFIX = "accounting_receipts"


def _save_receipt_upload(file: Optional[UploadFile]) -> Optional[str]:
    if file is None or not getattr(file, "filename", None):
        return None
    if not storage_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 storage not configured — cannot upload receipt",
        )
    raw = file.file.read()
    if not raw:
        return None
    suf = Path(file.filename or "upload").suffix.lower()
    if suf not in (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"):
        suf = ".bin"
    mime = file.content_type or "application/octet-stream"
    key = f"{_RECEIPT_PREFIX}/{uuid.uuid4().hex}{suf}"
    upload_bytes(key, raw, mime)
    return key


def _accounting_http(e: ValueError) -> HTTPException:
    msg = str(e)
    if msg.startswith("Cannot post:"):
        return HTTPException(status.HTTP_409_CONFLICT, detail=msg)
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=msg)


def _range_utc(d0: date, d1: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d0, time.min).replace(tzinfo=timezone.utc)
    end = datetime.combine(d1, time.min).replace(tzinfo=timezone.utc) + timedelta(days=1)
    return start, end


def _ar_pub(db: Session, row: ARInvoice) -> ARInvoicePublic:
    url = presigned_url(row.payment_receipt_key) if row.payment_receipt_key else None
    q = Decimal("0.01")
    paid = amount_paid_on_ar(db, row)
    total = Decimal(str(row.amount)).quantize(q)
    bal = (total - paid).quantize(q)
    if bal < 0:
        bal = Decimal("0")
    return ARInvoicePublic(
        id=row.id,
        customer_bill_id=row.customer_bill_id,
        customer_id=row.customer_id,
        amount=str(total),
        amount_paid=str(paid.quantize(q)),
        balance=str(bal),
        status=row.status,
        journal_entry_id=row.journal_entry_id,
        payment_transaction_id=row.payment_transaction_id,
        payment_date=row.payment_date,
        payment_receipt_key=row.payment_receipt_key,
        payment_receipt_url=url,
        payment_journal_entry_id=row.payment_journal_entry_id,
        paid_at=row.paid_at,
        created_at=row.created_at,
    )


def _ap_pub(db: Session, row: APBill) -> APBillPublic:
    url = presigned_url(row.payment_receipt_key) if row.payment_receipt_key else None
    q = Decimal("0.01")
    paid = amount_paid_on_ap(db, row)
    total = Decimal(str(row.amount)).quantize(q)
    bal = (total - paid).quantize(q)
    if bal < 0:
        bal = Decimal("0")
    return APBillPublic(
        id=row.id,
        vendor_bill_id=row.vendor_bill_id,
        vendor_id=row.vendor_id,
        purchase_order_id=row.purchase_order_id,
        amount=str(total),
        amount_paid=str(paid.quantize(q)),
        balance=str(bal),
        status=row.status,
        journal_entry_id=row.journal_entry_id,
        payment_transaction_id=row.payment_transaction_id,
        payment_date=row.payment_date,
        payment_receipt_key=row.payment_receipt_key,
        payment_receipt_url=url,
        payment_journal_entry_id=row.payment_journal_entry_id,
        paid_at=row.paid_at,
        created_at=row.created_at,
    )


@router.get("/dashboard", response_model=DashboardPublic, dependencies=[Depends(require_admin)])
def dashboard(
    db: Session = Depends(get_db),
    date_from: date = Query(..., description="inclusive"),
    date_to: date = Query(..., description="inclusive"),
) -> DashboardPublic:
    if date_to < date_from:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="date_to before date_from")
    seed_chart_accounts(db)
    start, end = _range_utc(date_from, date_to)
    rev, exp, net = pnl_for_range(db, start, end)
    series = monthly_pnl_series(db, start, end)
    q = Decimal("0.01")
    return DashboardPublic(
        date_from=date_from,
        date_to=date_to,
        revenue_total=str(rev.quantize(q)),
        expense_total=str(exp.quantize(q)),
        net_pnl=str(net.quantize(q)),
        open_ar_count=count_open_ar(db),
        open_ap_count=count_open_ap(db),
        monthly_pnl=series,
    )


@router.get("/pnl", response_model=PnLReportPublic, dependencies=[Depends(require_admin)])
def pnl_report(
    db: Session = Depends(get_db),
    date_from: date = Query(...),
    date_to: date = Query(...),
) -> PnLReportPublic:
    if date_to < date_from:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="date_to before date_from")
    seed_chart_accounts(db)
    start, end = _range_utc(date_from, date_to)
    rev, exp, net = pnl_for_range(db, start, end)
    q = Decimal("0.01")
    return PnLReportPublic(
        date_from=date_from,
        date_to=date_to,
        revenue_total=str(rev.quantize(q)),
        expense_total=str(exp.quantize(q)),
        net_pnl=str(net.quantize(q)),
    )


@router.get("/gl", response_model=list[GLAccountRowPublic], dependencies=[Depends(require_admin)])
def gl_report(
    db: Session = Depends(get_db),
    date_from: date = Query(...),
    date_to: date = Query(...),
) -> list[GLAccountRowPublic]:
    if date_to < date_from:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="date_to before date_from")
    seed_chart_accounts(db)
    start, end = _range_utc(date_from, date_to)
    rows = gl_activity(db, start, end)
    q = Decimal("0.01")
    out: list[GLAccountRowPublic] = []
    for code, name, kind, deb, cred in rows:
        out.append(
            GLAccountRowPublic(
                account_code=code,
                name=name,
                kind=kind,
                debit_total=str(deb.quantize(q)),
                credit_total=str(cred.quantize(q)),
            )
        )
    return out


@router.get("/journal", response_model=list[JournalEntryPublic], dependencies=[Depends(require_admin)])
def journal_list(
    db: Session = Depends(get_db),
    date_from: date = Query(...),
    date_to: date = Query(...),
    limit: int = Query(200, ge=1, le=1000),
) -> list[JournalEntryPublic]:
    if date_to < date_from:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="date_to before date_from")
    start, end = _range_utc(date_from, date_to)
    q = (
        db.query(JournalEntry)
        .filter(JournalEntry.posted_at >= start, JournalEntry.posted_at < end)
        .order_by(JournalEntry.posted_at.desc())
        .limit(limit)
    )
    dq = Decimal("0.01")
    out: list[JournalEntryPublic] = []
    for je in q.all():
        lines = db.query(JournalLine).filter(JournalLine.journal_entry_id == je.id).all()
        out.append(
            JournalEntryPublic(
                id=je.id,
                posted_at=je.posted_at,
                memo=je.memo or "",
                ref_type=je.ref_type,
                ref_id=je.ref_id,
                lines=[
                    JournalLinePublic(
                        account_code=ln.account_code,
                        debit=str(Decimal(str(ln.debit)).quantize(dq)),
                        credit=str(Decimal(str(ln.credit)).quantize(dq)),
                    )
                    for ln in lines
                ],
            )
        )
    return out


@router.get("/ar", response_model=list[ARInvoicePublic], dependencies=[Depends(require_admin)])
def list_ar(db: Session = Depends(get_db)) -> list[ARInvoicePublic]:
    rows = db.query(ARInvoice).order_by(ARInvoice.id.desc()).limit(500).all()
    return [_ar_pub(db, r) for r in rows]


@router.get("/ap", response_model=list[APBillPublic], dependencies=[Depends(require_admin)])
def list_ap(db: Session = Depends(get_db)) -> list[APBillPublic]:
    rows = db.query(APBill).order_by(APBill.id.desc()).limit(500).all()
    return [_ap_pub(db, r) for r in rows]


@router.post("/ap/from-vendor-bill/{vendor_bill_id}", response_model=APBillPublic, dependencies=[Depends(require_admin)])
def create_ap_from_vendor_bill(vendor_bill_id: int, db: Session = Depends(get_db)) -> APBillPublic:
    from app.models.vendor_bill import VendorBill
    from app.models.vendor_purchase_order import VendorPurchaseOrder

    vb = db.get(VendorBill, vendor_bill_id)
    if vb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor bill not found")
    po = db.get(VendorPurchaseOrder, vb.purchase_order_id)
    if po is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="purchase order missing")
    st = (po.status or "").strip().lower()
    if st not in ("closed", "disputed"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="AP only when PO is closed or disputed",
        )
    try:
        seed_chart_accounts(db)
        row = ensure_ap_for_vendor_bill(db, vb=vb, po=po)
        if row is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="could not create AP (amount zero?)")
        db.commit()
    except ValueError as e:
        db.rollback()
        raise _accounting_http(e) from e
    db.refresh(row)
    return _ap_pub(db, row)


@router.post("/ar/{ar_id}/pay", response_model=ARInvoicePublic, dependencies=[Depends(require_admin)])
def pay_ar(
    ar_id: int,
    db: Session = Depends(get_db),
    receipt: Optional[UploadFile] = File(None),
    transaction_id: Optional[str] = Form(None),
    payment_date: Optional[str] = Form(None),
    amount: Optional[str] = Form(None),
) -> ARInvoicePublic:
    row = db.get(ARInvoice, ar_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="AR not found")
    pd: Optional[date] = None
    if payment_date and str(payment_date).strip():
        try:
            pd = date.fromisoformat(str(payment_date).strip()[:10])
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid payment_date") from e
    key = _save_receipt_upload(receipt)
    pay_amt: Optional[Decimal] = None
    if amount is not None and str(amount).strip():
        try:
            pay_amt = Decimal(str(amount).strip())
        except Exception as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid amount") from e
    try:
        seed_chart_accounts(db)
        record_ar_payment(
            db,
            row,
            receipt_key=key,
            transaction_id=transaction_id,
            payment_date=pd,
            amount=pay_amt,
        )
        db.commit()
    except ValueError as e:
        db.rollback()
        raise _accounting_http(e) from e
    db.refresh(row)
    return _ar_pub(db, row)


@router.post("/ap/{ap_id}/pay", response_model=APBillPublic, dependencies=[Depends(require_admin)])
def pay_ap(
    ap_id: int,
    db: Session = Depends(get_db),
    receipt: Optional[UploadFile] = File(None),
    transaction_id: Optional[str] = Form(None),
    payment_date: Optional[str] = Form(None),
    amount: Optional[str] = Form(None),
) -> APBillPublic:
    row = db.get(APBill, ap_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="AP not found")
    pd: Optional[date] = None
    if payment_date and str(payment_date).strip():
        try:
            pd = date.fromisoformat(str(payment_date).strip()[:10])
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid payment_date") from e
    key = _save_receipt_upload(receipt)
    pay_amt: Optional[Decimal] = None
    if amount is not None and str(amount).strip():
        try:
            pay_amt = Decimal(str(amount).strip())
        except Exception as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid amount") from e
    try:
        seed_chart_accounts(db)
        record_ap_payment(
            db,
            row,
            receipt_key=key,
            transaction_id=transaction_id,
            payment_date=pd,
            amount=pay_amt,
        )
        db.commit()
    except ValueError as e:
        db.rollback()
        raise _accounting_http(e) from e
    db.refresh(row)
    return _ap_pub(db, row)


@router.get("/ap/vendor/{vendor_id}", response_model=VendorAPSummaryPublic, dependencies=[Depends(require_admin)])
def vendor_ap_summary(vendor_id: int, db: Session = Depends(get_db)) -> VendorAPSummaryPublic:
    """Consolidated AP for a vendor: total billed, total paid, balance."""
    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    rows = (
        db.query(APBill)
        .filter(APBill.vendor_id == vendor_id)
        .order_by(APBill.id.desc())
        .all()
    )
    dq = Decimal("0.01")
    total_billed = Decimal("0")
    total_paid = Decimal("0")
    bills = []
    for r in rows:
        pub = _ap_pub(db, r)
        total_billed += Decimal(pub.amount)
        total_paid += Decimal(pub.amount_paid)
        bills.append(pub)
    balance = total_billed - total_paid
    return VendorAPSummaryPublic(
        vendor_id=vendor_id,
        vendor_name=vendor.name or "",
        total_billed=str(total_billed.quantize(dq)),
        total_paid=str(total_paid.quantize(dq)),
        balance=str(balance.quantize(dq)),
        bills=bills,
    )


@router.post("/ap/vendor/{vendor_id}/pay", response_model=VendorAPSummaryPublic, dependencies=[Depends(require_admin)])
def pay_vendor_ap(
    vendor_id: int,
    db: Session = Depends(get_db),
    receipt: Optional[UploadFile] = File(None),
    transaction_id: Optional[str] = Form(None),
    payment_date: Optional[str] = Form(None),
    amount: str = Form(...),
) -> VendorAPSummaryPublic:
    """Record a payment against a vendor's total outstanding AP balance (distributes oldest first)."""
    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    try:
        pay_amt = Decimal(str(amount).strip())
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid amount") from e
    pd: Optional[date] = None
    if payment_date and str(payment_date).strip():
        try:
            pd = date.fromisoformat(str(payment_date).strip()[:10])
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid payment_date") from e
    key = _save_receipt_upload(receipt)
    open_bills = (
        db.query(APBill)
        .filter(APBill.vendor_id == vendor_id, APBill.status != "paid")
        .order_by(APBill.id.asc())
        .all()
    )
    remaining = pay_amt
    try:
        seed_chart_accounts(db)
        for bill in open_bills:
            if remaining <= 0:
                break
            paid = amount_paid_on_ap(db, bill)
            bill_balance = Decimal(str(bill.amount)) - paid
            if bill_balance <= 0:
                continue
            apply = min(remaining, bill_balance)
            record_ap_payment(db, bill, receipt_key=key, transaction_id=transaction_id, payment_date=pd, amount=apply)
            remaining -= apply
        db.commit()
    except ValueError as e:
        db.rollback()
        raise _accounting_http(e) from e
    return vendor_ap_summary(vendor_id, db)


@router.get("/ar/customer/{customer_id}", response_model=CustomerARSummaryPublic, dependencies=[Depends(require_admin)])
def customer_ar_summary(customer_id: int, db: Session = Depends(get_db)) -> CustomerARSummaryPublic:
    """Consolidated AR for a customer: total billed, total paid, balance."""
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    rows = (
        db.query(ARInvoice)
        .filter(ARInvoice.customer_id == customer_id)
        .order_by(ARInvoice.id.desc())
        .all()
    )
    dq = Decimal("0.01")
    total_billed = Decimal("0")
    total_paid = Decimal("0")
    invoices = []
    for r in rows:
        pub = _ar_pub(db, r)
        total_billed += Decimal(pub.amount)
        total_paid += Decimal(pub.amount_paid)
        invoices.append(pub)
    balance = total_billed - total_paid
    return CustomerARSummaryPublic(
        customer_id=customer_id,
        customer_name=customer.name or "",
        total_billed=str(total_billed.quantize(dq)),
        total_paid=str(total_paid.quantize(dq)),
        balance=str(balance.quantize(dq)),
        invoices=invoices,
    )


@router.post("/ar/customer/{customer_id}/pay", response_model=CustomerARSummaryPublic, dependencies=[Depends(require_admin)])
def pay_customer_ar(
    customer_id: int,
    db: Session = Depends(get_db),
    receipt: Optional[UploadFile] = File(None),
    transaction_id: Optional[str] = Form(None),
    payment_date: Optional[str] = Form(None),
    amount: str = Form(...),
) -> CustomerARSummaryPublic:
    """Record a payment against a customer's total outstanding AR balance (distributes oldest first)."""
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    try:
        pay_amt = Decimal(str(amount).strip())
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid amount") from e
    pd: Optional[date] = None
    if payment_date and str(payment_date).strip():
        try:
            pd = date.fromisoformat(str(payment_date).strip()[:10])
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid payment_date") from e
    key = _save_receipt_upload(receipt)
    open_invoices = (
        db.query(ARInvoice)
        .filter(ARInvoice.customer_id == customer_id, ARInvoice.status != "paid")
        .order_by(ARInvoice.id.asc())
        .all()
    )
    remaining = pay_amt
    try:
        seed_chart_accounts(db)
        for inv in open_invoices:
            if remaining <= 0:
                break
            paid = amount_paid_on_ar(db, inv)
            inv_balance = Decimal(str(inv.amount)) - paid
            if inv_balance <= 0:
                continue
            apply = min(remaining, inv_balance)
            record_ar_payment(db, inv, receipt_key=key, transaction_id=transaction_id, payment_date=pd, amount=apply)
            remaining -= apply
        db.commit()
    except ValueError as e:
        db.rollback()
        raise _accounting_http(e) from e
    return customer_ar_summary(customer_id, db)
