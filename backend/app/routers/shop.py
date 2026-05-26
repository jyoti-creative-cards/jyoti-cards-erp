from __future__ import annotations

import unicodedata
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.session import get_db, legacy_active_value, sql_is_active_true
from app.deps import get_current_customer
from app.models.catalog_product import CatalogProduct
from app.models.catalog_product_alternative import CatalogProductAlternative
from app.models.customer import Customer
from app.models.stock_balance import StockBalance
from app.schemas.shop import ShopProductAlternativePublic, ShopProductPublic, ShopSuggestionPublic
from app.services.catalog_storage import presigned_urls
from app.services.stock_levels import stock_status_label

router = APIRouter(prefix="/shop", tags=["shop"])


def _norm_shop_q(q: str) -> str:
    """Trim, NFKC, collapse whitespace — avoids invisible chars breaking SKU search."""
    s = unicodedata.normalize("NFKC", (q or "").strip())
    return " ".join(s.split())


def _catalog_match_clause(raw: str):
    """Exact + substring on internal SKU, vendor SKU, and display name."""
    term = f"%{raw}%"
    return or_(
        CatalogProduct.our_product_id == raw,
        CatalogProduct.vendor_product_id == raw,
        CatalogProduct.our_product_id.ilike(term),
        CatalogProduct.name.ilike(term),
        CatalogProduct.vendor_product_id.ilike(term),
    )


def _qty_threshold(db: Session, catalog_product_id: int) -> tuple[int, int]:
    bal = db.get(StockBalance, catalog_product_id)
    if bal is None:
        return 0, 0
    return int(bal.quantity), int(bal.low_stock_threshold or 0)


def _first_image_url(db: Session, p: CatalogProduct) -> str:
    keys = p.image_keys if isinstance(p.image_keys, list) else []
    keys_str = [str(k) for k in keys]
    urls = presigned_urls(keys_str)
    return urls[0] if urls else ""


def _alternatives_in_stock_only(db: Session, parent_id: int) -> List[ShopProductAlternativePublic]:
    """Return alternatives that have stock (in_stock or low_stock). Query both directions."""
    rows = (
        db.query(CatalogProductAlternative)
        .filter(
            or_(
                CatalogProductAlternative.catalog_product_id == parent_id,
                CatalogProductAlternative.alternative_catalog_product_id == parent_id,
            )
        )
        .order_by(CatalogProductAlternative.id.asc())
        .all()
    )
    seen: set[int] = set()
    out: List[ShopProductAlternativePublic] = []
    for r in rows:
        # The "other" side of the relationship
        aid = r.alternative_catalog_product_id if r.catalog_product_id == parent_id else r.catalog_product_id
        if aid in seen:
            continue
        seen.add(aid)
        qty, th = _qty_threshold(db, aid)
        lbl = stock_status_label(qty, th)
        if lbl == "out_of_stock":
            continue
        p = db.get(CatalogProduct, aid)
        if p is None or not legacy_active_value(p.is_active):
            continue
        out.append(
            ShopProductAlternativePublic(
                catalog_product_id=p.id,
                our_product_id=p.our_product_id,
                image_url=_first_image_url(db, p),
            )
        )
    return out


@router.get("/products/suggestions", response_model=List[ShopSuggestionPublic])
def product_suggestions(
    q: str = Query(..., min_length=1, max_length=200),
    db: Session = Depends(get_db),
    _customer: Customer = Depends(get_current_customer),
) -> List[ShopSuggestionPublic]:
    raw = _norm_shop_q(q)
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="search text empty")
    rows = (
        db.query(CatalogProduct)
        .filter(
            sql_is_active_true(CatalogProduct.is_active),
            _catalog_match_clause(raw),
        )
        .order_by(CatalogProduct.our_product_id.asc())
        .limit(25)
        .all()
    )
    return [
        ShopSuggestionPublic(catalog_product_id=r.id, our_product_id=r.our_product_id) for r in rows
    ]


@router.get("/products/search", response_model=List[ShopProductPublic])
def product_search(
    q: str = Query(..., min_length=1, max_length=200),
    stock_status: Optional[str] = Query(
        None,
        description="Filter: in_stock | low_stock | out_of_stock (omit for all)",
    ),
    db: Session = Depends(get_db),
    _customer: Customer = Depends(get_current_customer),
) -> List[ShopProductPublic]:
    st_filter = (stock_status or "").strip().lower()
    if st_filter and st_filter not in ("in_stock", "low_stock", "out_of_stock"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="stock_status must be in_stock, low_stock, or out_of_stock",
        )

    raw = _norm_shop_q(q)
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="search text empty")
    rows = (
        db.query(CatalogProduct)
        .filter(
            sql_is_active_true(CatalogProduct.is_active),
            _catalog_match_clause(raw),
        )
        .order_by(CatalogProduct.our_product_id.asc())
        .limit(80)
        .all()
    )

    out: List[ShopProductPublic] = []
    for p in rows:
        qty, th = _qty_threshold(db, p.id)
        label = stock_status_label(qty, th)
        if st_filter and label != st_filter:
            continue
        alts: List[ShopProductAlternativePublic] = []
        # Show alternatives when primary is low or out of stock
        if label in ("out_of_stock", "low_stock"):
            alts = _alternatives_in_stock_only(db, p.id)
        sp = p.selling_price
        try:
            sp_str = format(Decimal(str(sp)), "f") if sp is not None else "0"
        except (ValueError, InvalidOperation, ArithmeticError):
            sp_str = "0"
        out.append(
            ShopProductPublic(
                catalog_product_id=p.id,
                our_product_id=p.our_product_id,
                image_url=_first_image_url(db, p),
                selling_price=sp_str,
                stock_status=label,
                alternatives=alts,
            )
        )
    return out
