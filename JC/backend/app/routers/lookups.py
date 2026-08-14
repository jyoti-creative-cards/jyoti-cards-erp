from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_permission
from app.models.addon_product import AddonProduct
from app.models.catalog_lookup import CatalogLookup
from app.models.catalog_product import CatalogProduct
from app.schemas.lookup import LookupCreate, LookupPublic, LookupUpdate
from app.services.activity import log_from_auth

router = APIRouter(prefix="/lookups", tags=["lookups"])

VALID_TYPES = {"category", "series", "unit", "year_group"}

_PRODUCT_FIELD = {
    "category": CatalogProduct.category,
    "series": CatalogProduct.series,
    "unit": CatalogProduct.unit,
    "year_group": CatalogProduct.year_group,
}


@router.get("", response_model=List[LookupPublic], dependencies=[Depends(require_permission("setup.read"))])
def list_lookups(
    lookup_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> List[LookupPublic]:
    q = db.query(CatalogLookup).filter(CatalogLookup.is_active.is_(True))
    if lookup_type:
        if lookup_type not in VALID_TYPES:
            raise HTTPException(400, "invalid lookup_type")
        q = q.filter(CatalogLookup.lookup_type == lookup_type)
    rows = q.order_by(CatalogLookup.lookup_type, CatalogLookup.value).all()
    return [LookupPublic(id=r.id, lookup_type=r.lookup_type, value=r.value, is_active=r.is_active, created_at=r.created_at) for r in rows]


@router.post("", response_model=LookupPublic, status_code=201, dependencies=[Depends(require_permission("setup.write"))])
def create_lookup(body: LookupCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("setup.write"))) -> LookupPublic:
    if body.lookup_type not in VALID_TYPES:
        raise HTTPException(400, "invalid lookup_type")
    val = body.value.strip()
    if not val:
        raise HTTPException(400, "value required")
    row = CatalogLookup(lookup_type=body.lookup_type, value=val)
    db.add(row)
    try:
        log_from_auth(
            db,
            auth,
            action="create",
            entity_type="lookup",
            entity_id=row.id,
            entity_label=row.value,
            detail=row.lookup_type,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "value already exists for this type") from None
    db.refresh(row)
    return LookupPublic(id=row.id, lookup_type=row.lookup_type, value=row.value, is_active=row.is_active, created_at=row.created_at)


@router.patch("/{lookup_id}", response_model=LookupPublic, dependencies=[Depends(require_permission("setup.write"))])
def update_lookup(lookup_id: int, body: LookupUpdate, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("setup.write"))) -> LookupPublic:
    row = db.get(CatalogLookup, lookup_id)
    if not row or not row.is_active:
        raise HTTPException(404, "lookup not found")
    new_val = body.value.strip()
    if not new_val:
        raise HTTPException(400, "value required")
    old_val = row.value
    if new_val == old_val:
        return LookupPublic(id=row.id, lookup_type=row.lookup_type, value=row.value, is_active=row.is_active, created_at=row.created_at)

    dup = (
        db.query(CatalogLookup)
        .filter(
            CatalogLookup.lookup_type == row.lookup_type,
            CatalogLookup.value == new_val,
            CatalogLookup.is_active.is_(True),
            CatalogLookup.id != row.id,
        )
        .first()
    )
    if dup:
        raise HTTPException(409, "value already exists for this type")

    row.value = new_val
    col = _PRODUCT_FIELD.get(row.lookup_type)
    if col is not None:
        db.query(CatalogProduct).filter(col == old_val).update({col: new_val}, synchronize_session=False)
    if row.lookup_type == "category":
        db.query(AddonProduct).filter(AddonProduct.category == old_val).update(
            {AddonProduct.category: new_val}, synchronize_session=False
        )
    elif row.lookup_type == "unit":
        db.query(AddonProduct).filter(AddonProduct.unit == old_val).update(
            {AddonProduct.unit: new_val}, synchronize_session=False
        )
    try:
        log_from_auth(
            db,
            auth,
            action="update",
            entity_type="lookup",
            entity_id=row.id,
            entity_label=row.value,
            detail=f"{row.lookup_type} (was {old_val})",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "value already exists for this type") from None
    db.refresh(row)
    return LookupPublic(id=row.id, lookup_type=row.lookup_type, value=row.value, is_active=row.is_active, created_at=row.created_at)


@router.delete("/{lookup_id}", status_code=204, dependencies=[Depends(require_permission("setup.write"))])
def delete_lookup(lookup_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("setup.write"))) -> None:
    row = db.get(CatalogLookup, lookup_id)
    if not row or not row.is_active:
        raise HTTPException(404, "lookup not found")
    row.is_active = False
    log_from_auth(
        db,
        auth,
        action="delete",
        entity_type="lookup",
        entity_id=row.id,
        entity_label=row.value,
        detail=row.lookup_type,
    )
    db.commit()
