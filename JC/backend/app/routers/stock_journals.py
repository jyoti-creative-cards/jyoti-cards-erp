from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin
from app.models.catalog_product import CatalogProduct
from app.models.stock import StockBalance
from app.models.vendor import Vendor
from app.schemas.stock_journal import JournalIn, JournalOut, JournalVoidIn
from app.services import stock_journal as journal_svc

router = APIRouter(prefix="/stock-journals", tags=["stock-journals"])


@router.get("/products")
def search_journal_products(
    q: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
) -> list[dict]:
    """Small product picker for the journal form. Does not load the whole catalog."""
    needle = q.replace("\x00", "").strip().lower()
    like = f"%{needle}%"
    rows = (
        db.query(CatalogProduct, StockBalance, Vendor)
        .outerjoin(StockBalance, StockBalance.catalog_product_id == CatalogProduct.id)
        .outerjoin(Vendor, Vendor.id == CatalogProduct.vendor_id)
        .filter(
            CatalogProduct.is_active.is_(True),
            CatalogProduct.deleted_at.is_(None),
            or_(
                func.lower(CatalogProduct.our_product_id).like(like),
                func.lower(func.coalesce(CatalogProduct.category, "")).like(like),
                func.lower(func.coalesce(CatalogProduct.second_category, "")).like(like),
                func.lower(func.coalesce(CatalogProduct.series, "")).like(like),
                func.lower(func.coalesce(Vendor.business_name, "")).like(like),
            ),
        )
        .order_by(CatalogProduct.our_product_id.asc(), CatalogProduct.id.asc())
        .limit(8)
        .all()
    )
    out = []
    for product, balance, vendor in rows:
        out.append({
            "catalog_product_id": product.id,
            "our_product_id": product.our_product_id,
            "category": product.category,
            "buying_price": format(product.buying_price, "f") if product.buying_price is not None else None,
            "quantity_on_hand": int(balance.quantity_on_hand) if balance else 0,
            "vendor_name": vendor.business_name if vendor else "",
        })
    return out


@router.post("/preview", response_model=JournalOut)
def preview_journal(
    body: JournalIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return journal_svc.preview_journal(db, body)


@router.post("", response_model=JournalOut)
def create_journal(
    body: JournalIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return journal_svc.post_journal(db, body, auth)


@router.get("", response_model=List[JournalOut])
def list_journals(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return journal_svc.list_journals(db, from_date, to_date)


@router.get("/{journal_id}", response_model=JournalOut)
def get_journal(
    journal_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return journal_svc.get_journal(db, journal_id)


@router.post("/{journal_id}/void", response_model=JournalOut)
def void_journal(
    journal_id: int,
    body: JournalVoidIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return journal_svc.void_journal(db, journal_id, body.reason, auth)
