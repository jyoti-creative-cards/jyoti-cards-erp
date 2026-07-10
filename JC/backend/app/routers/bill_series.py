from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin, require_permission
from app.models.bill_series import BillSeries
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOrderPlacement
from app.services.bill_series_alloc import bill_series_preview
from app.services.storage import presigned_url, storage_configured

router = APIRouter(prefix="/bill-series", tags=["bill-series"])


class BillSeriesCreate(BaseModel):
    name: str
    prefix: str
    start_num: int = 1
    end_num: int


class BillSeriesPublic(BaseModel):
    id: int
    name: str
    prefix: str
    start_num: int
    end_num: int
    current_num: int
    is_active: bool
    created_at: datetime


class BillSeriesBillSummary(BaseModel):
    id: int
    bill_number: str
    customer_id: int
    customer_name: str
    grand_total: str
    placement_id: Optional[int] = None
    created_at: datetime
    created_by_name: str


class BillSeriesDetailPublic(BaseModel):
    id: int
    name: str
    prefix: str
    start_num: int
    end_num: int
    current_num: int
    is_active: bool
    created_at: datetime
    total_capacity: int
    used_count: int
    remaining: int
    next_bill_number: Optional[str] = None
    exhausted: bool
    bills: List[BillSeriesBillSummary] = []


class BillDetailLineOut(BaseModel):
    id: int
    our_product_id: str
    quantity_shipped: int
    unit_price: str
    line_total: str
    status: str


class BillDetailPublic(BaseModel):
    id: int
    bill_number: str
    bill_series_id: Optional[int] = None
    bill_series_name: Optional[str] = None
    customer_id: int
    customer_name: str
    placement_id: Optional[int] = None
    placement_at: Optional[datetime] = None
    narration: Optional[str] = None
    gst_enabled: bool
    gst_rate_percent: str
    discount_amount: str
    taxable_value: str
    gst_amount: str
    grand_total: str
    subtotal_inclusive: str
    created_at: datetime
    created_by_name: str
    document_url: Optional[str] = None
    lines: List[BillDetailLineOut] = []


def _to_public(row: BillSeries) -> BillSeriesPublic:
    return BillSeriesPublic(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        start_num=row.start_num,
        end_num=row.end_num,
        current_num=row.current_num,
        is_active=row.is_active,
        created_at=row.created_at,
    )


def _fmt_money(val: Decimal) -> str:
    return format(val, "f")


def _series_stats(db: Session, row: BillSeries) -> dict:
    total_capacity = row.end_num - row.start_num + 1
    used_count = max(0, row.current_num - row.start_num + 1) if row.current_num >= row.start_num else 0
    peek = bill_series_preview(db, row.id)
    return {
        "total_capacity": total_capacity,
        "used_count": used_count,
        "next_bill_number": peek.get("next_bill_number"),
        "remaining": peek.get("remaining", 0),
        "exhausted": peek.get("exhausted", False),
    }


@router.get("", response_model=List[BillSeriesPublic])
def list_bill_series(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("vendor_orders.read"))):
    rows = db.query(BillSeries).filter(BillSeries.is_active.is_(True)).order_by(BillSeries.id.asc()).all()
    return [_to_public(r) for r in rows]


@router.post("", response_model=BillSeriesPublic, status_code=201)
def create_bill_series(body: BillSeriesCreate, db: Session = Depends(get_db), auth=Depends(require_admin)):
    if body.end_num <= body.start_num:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="end_num must be greater than start_num")
    row = BillSeries(
        name=body.name.strip(),
        prefix=body.prefix.strip(),
        start_num=body.start_num,
        end_num=body.end_num,
        current_num=0,
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_public(row)


@router.get("/bills/{bill_id}", response_model=BillDetailPublic)
def get_bill_detail(bill_id: int, db: Session = Depends(get_db), auth=Depends(require_admin)):
    bill = db.get(CustomerBill, bill_id)
    if not bill:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="bill not found")
    customer = db.get(Customer, bill.customer_id)
    if not customer:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found")
    series = db.get(BillSeries, bill.bill_series_id) if bill.bill_series_id else None
    placement = db.get(CustomerOrderPlacement, bill.placement_id) if bill.placement_id else None
    lines = (
        db.query(CustomerBillLine)
        .filter(CustomerBillLine.bill_id == bill.id)
        .order_by(CustomerBillLine.id.asc())
        .all()
    )
    doc_url = presigned_url(bill.document_key) if bill.document_key and storage_configured() else None
    return BillDetailPublic(
        id=bill.id,
        bill_number=bill.bill_number,
        bill_series_id=bill.bill_series_id,
        bill_series_name=series.name if series else None,
        customer_id=bill.customer_id,
        customer_name=customer.business_name,
        placement_id=bill.placement_id,
        placement_at=placement.placed_at if placement else None,
        narration=bill.narration,
        gst_enabled=bill.gst_enabled,
        gst_rate_percent=_fmt_money(bill.gst_rate_percent),
        discount_amount=_fmt_money(bill.discount_amount),
        taxable_value=_fmt_money(bill.taxable_value),
        gst_amount=_fmt_money(bill.gst_amount),
        grand_total=_fmt_money(bill.grand_total),
        subtotal_inclusive=_fmt_money(bill.subtotal_inclusive),
        created_at=bill.created_at,
        created_by_name=bill.created_by_name,
        document_url=doc_url,
        lines=[
            BillDetailLineOut(
                id=ln.id,
                our_product_id=ln.our_product_id,
                quantity_shipped=ln.quantity_shipped,
                unit_price=_fmt_money(ln.unit_price),
                line_total=_fmt_money(ln.line_total),
                status=ln.status,
            )
            for ln in lines
        ],
    )


@router.get("/{series_id}", response_model=BillSeriesDetailPublic)
def get_bill_series_detail(series_id: int, db: Session = Depends(get_db), auth=Depends(require_admin)):
    row = db.get(BillSeries, series_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="series not found")
    stats = _series_stats(db, row)
    bills = (
        db.query(CustomerBill, Customer)
        .join(Customer, Customer.id == CustomerBill.customer_id)
        .filter(CustomerBill.bill_series_id == series_id)
        .order_by(CustomerBill.created_at.desc())
        .all()
    )
    bills_out = [
        BillSeriesBillSummary(
            id=b.id,
            bill_number=b.bill_number,
            customer_id=b.customer_id,
            customer_name=c.business_name,
            grand_total=_fmt_money(b.grand_total),
            placement_id=b.placement_id,
            created_at=b.created_at,
            created_by_name=b.created_by_name,
        )
        for b, c in bills
    ]
    return BillSeriesDetailPublic(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        start_num=row.start_num,
        end_num=row.end_num,
        current_num=row.current_num,
        is_active=row.is_active,
        created_at=row.created_at,
        total_capacity=stats["total_capacity"],
        used_count=stats["used_count"],
        remaining=stats["remaining"],
        next_bill_number=stats["next_bill_number"],
        exhausted=stats["exhausted"],
        bills=bills_out,
    )


@router.delete("/{series_id}")
def delete_bill_series(series_id: int, db: Session = Depends(get_db), auth=Depends(require_admin)):
    row = db.get(BillSeries, series_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="series not found")
    row.is_active = False
    db.commit()
    return {"ok": True, "id": series_id}


@router.get("/{series_id}/next")
def peek_next_bill_id(series_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("vendor_orders.read"))):
    return bill_series_preview(db, series_id)
