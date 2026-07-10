from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context, require_permission
from app.models.catalog_lookup import CatalogLookup
from app.schemas.lookup import LookupCreate, LookupPublic

router = APIRouter(prefix="/lookups", tags=["lookups"])

VALID_TYPES = {"category", "series", "unit", "year_group"}


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
def create_lookup(body: LookupCreate, db: Session = Depends(get_db)) -> LookupPublic:
    if body.lookup_type not in VALID_TYPES:
        raise HTTPException(400, "invalid lookup_type")
    val = body.value.strip()
    if not val:
        raise HTTPException(400, "value required")
    row = CatalogLookup(lookup_type=body.lookup_type, value=val)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "value already exists for this type") from None
    db.refresh(row)
    return LookupPublic(id=row.id, lookup_type=row.lookup_type, value=row.value, is_active=row.is_active, created_at=row.created_at)


@router.delete("/{lookup_id}", status_code=204, dependencies=[Depends(require_permission("setup.write"))])
def delete_lookup(lookup_id: int, db: Session = Depends(get_db)) -> None:
    row = db.get(CatalogLookup, lookup_id)
    if not row or not row.is_active:
        raise HTTPException(404, "lookup not found")
    row.is_active = False
    db.commit()
