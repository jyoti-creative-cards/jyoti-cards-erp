"""Product price history — SCD Type 2."""
from __future__ import annotations

from datetime import date
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
    selling_price: Decimal
    start_date: date
    end_date: Optional[date] = None


class ProductPricePublic(BaseModel):
    id: int
    catalog_product_id: int
    buying_price: str
    selling_price: str
    start_date: date
    end_date: Optional[date] = None
    is_current: bool
    model_config = {"from_attributes": False}


def _to_public(r: ProductPrice) -> ProductPricePublic:
    return ProductPricePublic(
        id=r.id,
        catalog_product_id=r.catalog_product_id,
        buying_price=format(r.buying_price, "f"),
        selling_price=format(r.selling_price, "f"),
        start_date=r.start_date,
        end_date=r.end_date,
        is_current=r.is_current,
    )


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
    """Create new price record. Closes previous current price (sets end_date + is_current=False)."""
    prod = db.get(CatalogProduct, body.catalog_product_id)
    if not prod:
        raise HTTPException(404, "product not found")

    # Close previous current price
    prev = (
        db.query(ProductPrice)
        .filter(ProductPrice.catalog_product_id == body.catalog_product_id, ProductPrice.is_current.is_(True))
        .first()
    )
    if prev:
        prev.is_current = False
        if not prev.end_date:
            from datetime import timedelta
            prev.end_date = body.start_date - timedelta(days=1)
        db.add(prev)

    # Create new price row
    row = ProductPrice(
        catalog_product_id=body.catalog_product_id,
        buying_price=body.buying_price,
        selling_price=body.selling_price,
        start_date=body.start_date,
        end_date=body.end_date,
        is_current=body.end_date is None,
    )
    db.add(row)

    # Also update the current price on the product itself
    prod.buying_price = body.buying_price
    prod.selling_price = body.selling_price
    db.add(prod)
    db.commit(); db.refresh(row)
    return _to_public(row)
