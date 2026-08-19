"""Product price history — SCD Type 2."""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.catalog_product import CatalogProduct
from app.models.product_price import ProductPrice

router = APIRouter(prefix="/product-prices", tags=["product-prices"])


class ProductPriceIn(BaseModel):
    catalog_product_id: int
    buying_price: Decimal
    selling_price: Optional[Decimal] = None
    start_date: _dt.date


class ProductPricePublic(BaseModel):
    id: int
    catalog_product_id: int
    buying_price: str
    selling_price: Optional[str] = None
    start_date: _dt.date
    end_date: Optional[_dt.date] = None
    is_current: bool
    model_config = {"from_attributes": False}


def _to_public(r: ProductPrice) -> ProductPricePublic:
    return ProductPricePublic(
        id=r.id,
        catalog_product_id=r.catalog_product_id,
        buying_price=format(r.buying_price, "f"),
        selling_price=format(r.selling_price, "f") if r.selling_price is not None else None,
        start_date=r.start_date,
        end_date=r.end_date,
        is_current=r.is_current,
    )


def record_price_change(
    db: Session,
    catalog_product_id: int,
    buying_price: Decimal,
    selling_price: Optional[Decimal],
    start_date: Optional[_dt.date] = None,
) -> None:
    """Close previous price record and insert new one. Call before saving new prices."""
    today = start_date or _dt.date.today()
    # Close current price record
    prev = (
        db.query(ProductPrice)
        .filter(ProductPrice.catalog_product_id == catalog_product_id, ProductPrice.is_current.is_(True))
        .first()
    )
    if prev:
        prev.is_current = False
        if not prev.end_date:
            prev.end_date = today - _dt.timedelta(days=1)
        db.add(prev)
    # Insert new
    row = ProductPrice(
        catalog_product_id=catalog_product_id,
        buying_price=buying_price,
        selling_price=selling_price,
        start_date=today,
        is_current=True,
    )
    db.add(row)


@router.get("/{catalog_product_id}", response_model=List[ProductPricePublic], dependencies=[Depends(require_admin)])
def get_price_history(catalog_product_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(ProductPrice)
        .filter(ProductPrice.catalog_product_id == catalog_product_id)
        .order_by(ProductPrice.start_date.desc())
        .all()
    )
    return [_to_public(r) for r in rows]


@router.post("", response_model=ProductPricePublic, status_code=201, dependencies=[Depends(require_admin)])
def set_price(body: ProductPriceIn, db: Session = Depends(get_db)):
    """Create new price record and close previous (SCD Type 2)."""
    prod = db.get(CatalogProduct, body.catalog_product_id)
    if not prod or prod.deleted_at is not None:
        raise HTTPException(404, "product not found")
    record_price_change(db, body.catalog_product_id, body.buying_price, body.selling_price, body.start_date)
    # Also update live price on the product
    prod.buying_price = body.buying_price
    prod.selling_price = body.selling_price
    db.add(prod)
    db.commit()
    latest = (
        db.query(ProductPrice)
        .filter(ProductPrice.catalog_product_id == body.catalog_product_id, ProductPrice.is_current.is_(True))
        .first()
    )
    return _to_public(latest)
