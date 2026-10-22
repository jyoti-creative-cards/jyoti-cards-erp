"""BizAnalyst-style phone books."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context
from app.services import biz_analyst as biz

router = APIRouter(prefix="/biz", tags=["biz"])


def _reader(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if getattr(auth, "is_lookup_only", lambda: False)():
        raise HTTPException(403, "permission denied")
    return auth


def _rate(raw: Optional[str]) -> Optional[Decimal]:
    text = (raw or "").strip()
    if not text:
        return None
    return Decimal(text)


@router.get("/home")
def biz_home(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(_reader),
):
    return biz.home(db, from_date, to_date)


@router.get("/drill")
def biz_drill(
    metric: str = Query("sales"),
    group: str = Query("party"),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    rate_min: Optional[str] = Query(None),
    rate_max: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(_reader),
):
    return biz.drill(db, metric, group, from_date, to_date, _rate(rate_min), _rate(rate_max))


@router.get("/items")
def biz_items(
    q: str = Query(""),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(_reader),
):
    return {"items": biz.search_items(db, q)}


@router.get("/items/{product_id}")
def biz_item(
    product_id: int,
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(_reader),
):
    row = biz.item_summary(db, product_id, from_date, to_date)
    if not row:
        raise HTTPException(404, "item not found")
    return row


@router.get("/items/{product_id}/customers")
def biz_item_customers(
    product_id: int,
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(_reader),
):
    return {"rows": biz.item_customers(db, product_id, from_date, to_date)}


@router.get("/items/{product_id}/suppliers")
def biz_item_suppliers(
    product_id: int,
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(_reader),
):
    return {"rows": biz.item_suppliers(db, product_id, from_date, to_date)}


@router.get("/bills/{bill_id}")
def biz_bill(
    bill_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(_reader),
):
    row = biz.customer_bill(db, bill_id)
    if not row:
        raise HTTPException(404, "bill not found")
    return row


@router.get("/receipts/{receipt_id}")
def biz_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(_reader),
):
    row = biz.supplier_receipt(db, receipt_id)
    if not row:
        raise HTTPException(404, "receipt not found")
    return row
