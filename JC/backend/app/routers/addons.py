from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context, require_permission
from app.models.addon_product import AddonProduct
from app.models.vendor import Vendor
from app.schemas.addon import AddonCreate, AddonDetail, AddonPublic, AddonUpdate
from app.services.history import TRACKED_FIELDS, diff_summary, list_entity_history, list_price_history, record_entity_history, record_price_change, row_snapshot
from app.services.storage import presigned_urls

router = APIRouter(prefix="/addons", tags=["addons"])


def _to_public(row: AddonProduct, db: Session) -> AddonPublic:
    v = db.get(Vendor, row.vendor_id)
    keys = row.image_keys or []
    return AddonPublic(
        id=row.id,
        our_product_id=row.our_product_id,
        vendor_id=row.vendor_id,
        vendor_name=v.business_name if v else None,
        vendor_product_id=row.vendor_product_id,
        name=row.name,
        description=row.description,
        category=row.category,
        unit=row.unit,
        buying_price=format(row.buying_price, "f"),
        image_keys=keys,
        image_urls=presigned_urls(keys),
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
    )


@router.get("", response_model=List[AddonPublic], dependencies=[Depends(require_permission("addons.read"))])
def list_addons(
    db: Session = Depends(get_db),
    search: Optional[str] = Query(None),
    vendor_id: Optional[int] = Query(None),
) -> List[AddonPublic]:
    q = db.query(AddonProduct).filter(AddonProduct.is_active.is_(True))
    if vendor_id:
        q = q.filter(AddonProduct.vendor_id == vendor_id)
    if search:
        s = f"%{search.lower()}%"
        q = q.filter(or_(
            func.lower(AddonProduct.our_product_id).like(s),
            func.lower(AddonProduct.name).like(s),
            func.lower(AddonProduct.vendor_product_id).like(s),
        ))
    return [_to_public(r, db) for r in q.order_by(AddonProduct.id.desc()).all()]


@router.get("/{addon_id}", response_model=AddonDetail, dependencies=[Depends(require_permission("addons.read"))])
def get_addon(addon_id: int, db: Session = Depends(get_db)) -> AddonDetail:
    row = db.get(AddonProduct, addon_id)
    if not row:
        raise HTTPException(404, "addon not found")
    pub = _to_public(row, db)
    ph = [{"buying_price": format(p.buying_price, "f"), "recorded_at": p.recorded_at.isoformat()} for p in list_price_history(db, "addon_product", addon_id)]
    eh = [{"change_summary": h.change_summary, "valid_from": h.valid_from.isoformat(), "snapshot_json": h.snapshot_json} for h in list_entity_history(db, "addon_product", addon_id)]
    return AddonDetail(**pub.model_dump(), price_history=ph, change_history=eh)


@router.post("", response_model=AddonPublic, status_code=201, dependencies=[Depends(require_permission("addons.write"))])
def create_addon(body: AddonCreate, db: Session = Depends(get_db)) -> AddonPublic:
    if not db.get(Vendor, body.vendor_id):
        raise HTTPException(400, "vendor not found")
    clash = db.query(AddonProduct).filter(
        AddonProduct.our_product_id == body.our_product_id.strip(), AddonProduct.is_active.is_(True)
    ).first()
    if clash:
        raise HTTPException(409, "our_product_id already exists")
    row = AddonProduct(
        our_product_id=body.our_product_id.strip(),
        vendor_id=body.vendor_id,
        vendor_product_id=body.vendor_product_id.strip(),
        name=body.name,
        description=body.description,
        category=body.category,
        unit=body.unit.strip(),
        buying_price=body.buying_price.quantize(Decimal("0.01")),
        image_keys=body.image_keys or [],
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "duplicate our_product_id") from None
    db.refresh(row)
    record_price_change(db, "addon_product", row.id, row.buying_price)
    db.commit()
    return _to_public(row, db)


@router.patch("/{addon_id}", response_model=AddonPublic, dependencies=[Depends(require_permission("addons.write"))])
def update_addon(addon_id: int, body: AddonUpdate, db: Session = Depends(get_db)) -> AddonPublic:
    row = db.get(AddonProduct, addon_id)
    if not row or not row.is_active:
        raise HTTPException(404, "addon not found")
    before = row_snapshot(row, TRACKED_FIELDS["addon_product"])
    data = body.model_dump(exclude_unset=True)
    price_changed = False
    if "buying_price" in data and data["buying_price"] is not None:
        row.buying_price = data["buying_price"].quantize(Decimal("0.01"))
        price_changed = True
        del data["buying_price"]
    for k, v in data.items():
        setattr(row, k, v)
    if price_changed:
        record_price_change(db, "addon_product", row.id, row.buying_price)
    after = row_snapshot(row, TRACKED_FIELDS["addon_product"])
    summary = diff_summary("addon_product", before, after)
    if summary != "updated":
        record_entity_history(db, "addon_product", row.id, before, summary)
    db.commit()
    db.refresh(row)
    return _to_public(row, db)


@router.delete("/{addon_id}", status_code=204, dependencies=[Depends(require_permission("addons.write"))])
def delete_addon(addon_id: int, db: Session = Depends(get_db)) -> None:
    row = db.get(AddonProduct, addon_id)
    if not row or not row.is_active:
        raise HTTPException(404, "addon not found")
    row.is_active = False
    row.deleted_at = datetime.now(timezone.utc)
    db.commit()
