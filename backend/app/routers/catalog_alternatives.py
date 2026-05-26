from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.catalog_product import CatalogProduct
from app.models.catalog_product_alternative import CatalogProductAlternative
from app.schemas.alternative import (
    ProductAlternativeCreate,
    ProductAlternativePublic,
    ProductAlternativeUpdate,
)

router = APIRouter(prefix="/catalog", tags=["catalog-alternatives"])


def _to_public(db: Session, row: CatalogProductAlternative) -> ProductAlternativePublic:
    alt = db.get(CatalogProduct, row.alternative_catalog_product_id)
    return ProductAlternativePublic(
        id=row.id,
        catalog_product_id=row.catalog_product_id,
        alternative_catalog_product_id=row.alternative_catalog_product_id,
        alternative_our_product_id=alt.our_product_id if alt else "",
        alternative_name=alt.name if alt else "",
        alternative_category=alt.category if alt else "",
        alternative_vendor_id=alt.vendor_id if alt else 0,
        created_at=row.created_at,
    )


def _parent_or_404(db: Session, product_id: int) -> CatalogProduct:
    row = db.get(CatalogProduct, product_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found")
    return row


@router.get(
    "/{product_id}/alternatives",
    response_model=List[ProductAlternativePublic],
    dependencies=[Depends(require_admin)],
)
def list_alternatives(product_id: int, db: Session = Depends(get_db)) -> List[ProductAlternativePublic]:
    _parent_or_404(db, product_id)
    rows = (
        db.query(CatalogProductAlternative)
        .filter(CatalogProductAlternative.catalog_product_id == product_id)
        .order_by(CatalogProductAlternative.id.asc())
        .all()
    )
    return [_to_public(db, r) for r in rows]


@router.post(
    "/{product_id}/alternatives",
    response_model=ProductAlternativePublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def add_alternative(
    product_id: int,
    body: ProductAlternativeCreate,
    db: Session = Depends(get_db),
) -> ProductAlternativePublic:
    _parent_or_404(db, product_id)
    aid = body.alternative_catalog_product_id
    if aid == product_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="a product cannot be an alternative of itself",
        )
    alt = db.get(CatalogProduct, aid)
    if alt is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="alternative product not found")

    row = CatalogProductAlternative(
        catalog_product_id=product_id,
        alternative_catalog_product_id=aid,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="this alternative is already linked to this product",
        ) from None
    db.refresh(row)

    # Auto-create reverse mapping (B→A) if not already present
    reverse = (
        db.query(CatalogProductAlternative)
        .filter(
            CatalogProductAlternative.catalog_product_id == aid,
            CatalogProductAlternative.alternative_catalog_product_id == product_id,
        )
        .first()
    )
    if reverse is None:
        db.add(CatalogProductAlternative(catalog_product_id=aid, alternative_catalog_product_id=product_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()

    return _to_public(db, row)


@router.patch(
    "/{product_id}/alternatives/{row_id}",
    response_model=ProductAlternativePublic,
    dependencies=[Depends(require_admin)],
)
def update_alternative(
    product_id: int,
    row_id: int,
    body: ProductAlternativeUpdate,
    db: Session = Depends(get_db),
) -> ProductAlternativePublic:
    _parent_or_404(db, product_id)
    row = db.get(CatalogProductAlternative, row_id)
    if row is None or row.catalog_product_id != product_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="alternative row not found")

    aid = body.alternative_catalog_product_id
    if aid == product_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="a product cannot be an alternative of itself",
        )
    if db.get(CatalogProduct, aid) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="alternative product not found")

    row.alternative_catalog_product_id = aid
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="this alternative is already linked to this product",
        ) from None
    db.refresh(row)
    return _to_public(db, row)


@router.delete(
    "/{product_id}/alternatives/{row_id}",
    dependencies=[Depends(require_admin)],
)
def delete_alternative(product_id: int, row_id: int, db: Session = Depends(get_db)) -> dict:
    _parent_or_404(db, product_id)
    row = db.get(CatalogProductAlternative, row_id)
    if row is None or row.catalog_product_id != product_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="alternative row not found")
    aid = row.alternative_catalog_product_id
    db.delete(row)
    # Remove reverse mapping too
    reverse = (
        db.query(CatalogProductAlternative)
        .filter(
            CatalogProductAlternative.catalog_product_id == aid,
            CatalogProductAlternative.alternative_catalog_product_id == product_id,
        )
        .first()
    )
    if reverse is not None:
        db.delete(reverse)
    db.commit()
    return {"ok": True, "id": row_id}
