from __future__ import annotations

import datetime as _dt
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.catalog_category_label import CatalogCategoryLabel
from app.models.catalog_lookup import CatalogLookup
from app.models.catalog_product import CatalogProduct
from app.models.vendor import Vendor
from app.schemas.catalog import (
    CatalogProductCreate,
    BulkCatalogProductCreate,
    CatalogProductPublic,
    CatalogProductUpdate,
    CategoryLabelCreate,
    ImageDeleteBody,
    LookupCreate,
    LookupPublic,
)
from app.services.catalog_storage import (
    delete_keys,
    next_image_key,
    presigned_urls,
    safe_catalog_stem,
    storage_configured,
    upload_bytes,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _default_year_group(db: Session) -> str:
    """Returns the current year group from DB, or computes from today's date."""
    row = (
        db.query(CatalogLookup)
        .filter(CatalogLookup.lookup_type == "year_group", CatalogLookup.is_current.is_(True))
        .first()
    )
    if row:
        return row.value
    # Fallback: compute from today (April = new fiscal year)
    now = _dt.datetime.now()
    y1 = now.year if now.month >= 4 else now.year - 1
    return f"{y1}-{str(y1 + 1)[-2:]}"


def _merged_categories(db: Session) -> List[str]:
    from_labels = {r[0] for r in db.query(CatalogCategoryLabel.name).all() if r[0] and r[0].strip()}
    from_products = {
        r[0].strip()
        for r in db.query(CatalogProduct.category).distinct().all()
        if r[0] and str(r[0]).strip()
    }
    return sorted(from_labels | from_products, key=str.casefold)


def _ensure_category_label(db: Session, name: str) -> None:
    n = name.strip()
    if not n:
        return
    exists = db.query(CatalogCategoryLabel).filter(CatalogCategoryLabel.name == n).first()
    if exists:
        return
    db.add(CatalogCategoryLabel(name=n))


def _to_public(row: CatalogProduct) -> CatalogProductPublic:
    keys = row.image_keys if isinstance(row.image_keys, list) else []
    keys_str = [str(k) for k in keys]
    bp = row.buying_price
    sp = row.selling_price
    return CatalogProductPublic(
        id=row.id,
        our_product_id=row.our_product_id,
        vendor_id=row.vendor_id,
        name=row.name,
        vendor_product_id=row.vendor_product_id or "",
        category=row.category,
        series=row.series,
        year_group=row.year_group,
        unit=row.unit if row.unit else "pcs",
        buying_price=float(bp) if bp is not None else 0.0,
        selling_price=float(sp) if sp is not None else None,
        image_keys=keys_str,
        image_urls=presigned_urls(keys_str),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/categories", dependencies=[Depends(require_admin)])
def categories(db: Session = Depends(get_db)) -> dict:
    return {"categories": _merged_categories(db)}


@router.post("/categories", dependencies=[Depends(require_admin)])
def add_category(body: CategoryLabelCreate, db: Session = Depends(get_db)) -> dict:
    n = body.name.strip()
    if not n:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="empty name")
    exists = db.query(CatalogCategoryLabel).filter(CatalogCategoryLabel.name == n).first()
    if exists:
        return {"ok": True, "name": n}
    db.add(CatalogCategoryLabel(name=n))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="category already exists") from None
    return {"ok": True, "name": n}


@router.delete("/categories/{name}", dependencies=[Depends(require_admin)])
def delete_category(name: str, db: Session = Depends(get_db)) -> dict:
    row = db.query(CatalogCategoryLabel).filter(CatalogCategoryLabel.name == name).first()
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


# ── Unified lookup endpoints (units / series / year_groups) ──────────────────

def _lookup_list(lookup_type: str, db: Session) -> list[dict]:
    rows = (
        db.query(CatalogLookup)
        .filter(CatalogLookup.lookup_type == lookup_type)
        .order_by(CatalogLookup.value)
        .all()
    )
    return [{"id": r.id, "value": r.value, "is_current": r.is_current} for r in rows]


def _lookup_add(lookup_type: str, body: LookupCreate, db: Session) -> dict:
    v = body.value.strip()
    if not v:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="empty value")
    # If marking as current, clear existing current
    if body.is_current:
        db.query(CatalogLookup).filter(
            CatalogLookup.lookup_type == lookup_type, CatalogLookup.is_current.is_(True)
        ).update({"is_current": False})
    row = db.query(CatalogLookup).filter(
        CatalogLookup.lookup_type == lookup_type, CatalogLookup.value == v
    ).first()
    if row:
        if body.is_current:
            row.is_current = True
            db.commit()
        return {"ok": True, "id": row.id, "value": v, "is_current": row.is_current}
    new_row = CatalogLookup(lookup_type=lookup_type, value=v, is_current=body.is_current)
    db.add(new_row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="already exists") from None
    db.refresh(new_row)
    return {"ok": True, "id": new_row.id, "value": v, "is_current": new_row.is_current}


def _lookup_delete(lookup_type: str, item_id: int, db: Session) -> dict:
    row = db.query(CatalogLookup).filter(
        CatalogLookup.lookup_type == lookup_type, CatalogLookup.id == item_id
    ).first()
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


@router.get("/units", dependencies=[Depends(require_admin)])
def list_units(db: Session = Depends(get_db)) -> dict:
    rows = _lookup_list("unit", db)
    # Include any unit values from existing products not yet in lookup table
    from_products = {
        r[0].strip()
        for r in db.query(CatalogProduct.unit).distinct().all()
        if r[0] and str(r[0]).strip()
    }
    stored = {r["value"] for r in rows}
    extras = sorted(from_products - stored, key=str.casefold)
    return {"units": rows, "extra_values": extras}


@router.post("/units", dependencies=[Depends(require_admin)])
def add_unit(body: LookupCreate, db: Session = Depends(get_db)) -> dict:
    return _lookup_add("unit", body, db)


@router.delete("/units/{item_id}", dependencies=[Depends(require_admin)])
def delete_unit(item_id: int, db: Session = Depends(get_db)) -> dict:
    return _lookup_delete("unit", item_id, db)


@router.get("/series", dependencies=[Depends(require_admin)])
def list_series(db: Session = Depends(get_db)) -> dict:
    rows = _lookup_list("series", db)
    return {"series": rows}


@router.post("/series", dependencies=[Depends(require_admin)])
def add_series(body: LookupCreate, db: Session = Depends(get_db)) -> dict:
    return _lookup_add("series", body, db)


@router.delete("/series/{item_id}", dependencies=[Depends(require_admin)])
def delete_series(item_id: int, db: Session = Depends(get_db)) -> dict:
    return _lookup_delete("series", item_id, db)


@router.get("/year-groups", dependencies=[Depends(require_admin)])
def list_year_groups(db: Session = Depends(get_db)) -> dict:
    rows = _lookup_list("year_group", db)
    current = _default_year_group(db)
    return {"year_groups": rows, "current": current}


@router.post("/year-groups", dependencies=[Depends(require_admin)])
def add_year_group(body: LookupCreate, db: Session = Depends(get_db)) -> dict:
    return _lookup_add("year_group", body, db)


@router.post("/year-groups/{item_id}/set-current", dependencies=[Depends(require_admin)])
def set_current_year_group(item_id: int, db: Session = Depends(get_db)) -> dict:
    """Mark this year group as the default for new products."""
    row = db.query(CatalogLookup).filter(
        CatalogLookup.lookup_type == "year_group", CatalogLookup.id == item_id
    ).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="year group not found")
    db.query(CatalogLookup).filter(
        CatalogLookup.lookup_type == "year_group", CatalogLookup.is_current.is_(True)
    ).update({"is_current": False})
    row.is_current = True
    db.commit()
    return {"ok": True, "current": row.value}


@router.delete("/year-groups/{item_id}", dependencies=[Depends(require_admin)])
def delete_year_group(item_id: int, db: Session = Depends(get_db)) -> dict:
    return _lookup_delete("year_group", item_id, db)


def _list_products_impl(
    db: Session,
    q: Optional[str] = None,
    vendor_id: Optional[int] = None,
    category: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    deleted: bool = False,
) -> dict:
    query = db.query(CatalogProduct)
    if deleted:
        query = query.filter(CatalogProduct.deleted_at.isnot(None))
    else:
        query = query.filter(CatalogProduct.deleted_at.is_(None))
    if vendor_id is not None:
        query = query.filter(CatalogProduct.vendor_id == vendor_id)
    if category:
        query = query.filter(CatalogProduct.category == category.strip())
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            or_(
                CatalogProduct.name.ilike(term),
                CatalogProduct.vendor_product_id.ilike(term),
                CatalogProduct.our_product_id.ilike(term),
            )
        )
    total = query.count()
    rows = query.order_by(CatalogProduct.id.asc()).offset(offset).limit(limit).all()
    return {"items": [_to_public(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("", dependencies=[Depends(require_admin)])
def list_products(
    q: Optional[str] = None,
    vendor_id: Optional[int] = None,
    category: Optional[str] = None,
    limit: int = Query(200, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    deleted: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict:
    """List / search catalog with server-side pagination. Returns {items, total, limit, offset}."""
    return _list_products_impl(db, q=q, vendor_id=vendor_id, category=category, limit=limit, offset=offset, deleted=deleted)


@router.get("/{product_id}", response_model=CatalogProductPublic, dependencies=[Depends(require_admin)])
def get_product(product_id: int, db: Session = Depends(get_db)) -> CatalogProductPublic:
    row = db.get(CatalogProduct, product_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found")
    return _to_public(row)


@router.post("", response_model=CatalogProductPublic, dependencies=[Depends(require_admin)])
def create_product(body: CatalogProductCreate, db: Session = Depends(get_db)) -> CatalogProductPublic:
    oid = body.our_product_id.strip()
    if not oid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="our_product_id required")
    stem = safe_catalog_stem(oid)
    if not stem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="our_product_id invalid")

    vend = db.get(Vendor, body.vendor_id)
    if vend is None or vend.deleted_at is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="vendor not found or inactive")

    cat = body.category.strip()
    yg = (body.year_group.strip() if body.year_group else None) or _default_year_group(db)
    vpid = body.vendor_product_id.strip()
    display_name = (body.name.strip() if body.name else None) or cat
    sp = Decimal(str(body.selling_price)) if body.selling_price is not None else None

    row = CatalogProduct(
        our_product_id=oid,
        vendor_id=body.vendor_id,
        name=display_name,
        vendor_product_id=vpid,
        category=cat,
        series=(body.series.strip() if body.series else None),
        year_group=yg,
        unit=(body.unit or "pcs"),
        buying_price=Decimal(str(body.buying_price)),
        selling_price=sp,
        image_keys=[],
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        err = str(e.orig) if getattr(e, "orig", None) else ""
        if "our_product_id" in err or "uq_catalog_our_product_id" in err:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="our_product_id already in use",
            ) from None
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="duplicate product (our_product_id or vendor+vendor_product_id)",
        ) from None
    db.refresh(row)
    _ensure_category_label(db, cat)
    # Record initial price history always on create
    from app.routers.product_prices import record_price_change
    try:
        record_price_change(db, row.id, Decimal(str(body.buying_price)), sp)
        db.commit()
    except Exception as exc:
        db.rollback()
        import logging
        logging.getLogger(__name__).warning("Price history failed for new product %s: %s", oid, exc)
        # Re-fetch row since rollback cleared session; product still exists from prior commit
        db.refresh(row)
    return _to_public(row)


@router.post("/bulk", dependencies=[Depends(require_admin)])
def bulk_create_products(body: list[BulkCatalogProductCreate], db: Session = Depends(get_db)) -> dict:
    """Create multiple catalog products with optional inline add-on and alternative links."""
    from app.routers.product_prices import record_price_change
    from app.models.addon_product import AddonProduct, CatalogProductAddon
    from app.models.catalog_product_alternative import CatalogProductAlternative
    default_yg = _default_year_group(db)
    created = []
    errors = []
    for i, item in enumerate(body):
        oid = item.our_product_id.strip()
        if not oid or not safe_catalog_stem(oid):
            errors.append({"row": i, "error": f"Invalid our_product_id: {oid}"})
            continue
        v = db.get(Vendor, item.vendor_id)
        if v is None or v.deleted_at is not None:
            errors.append({"row": i, "error": f"Vendor {item.vendor_id} not found or inactive"})
            continue
        cat = item.category.strip()
        yg = (item.year_group.strip() if item.year_group else None) or default_yg
        vpid = item.vendor_product_id.strip()
        display_name = (item.name.strip() if item.name else None) or cat
        sp = Decimal(str(item.selling_price)) if item.selling_price is not None else None
        row = CatalogProduct(
            our_product_id=oid,
            vendor_id=item.vendor_id,
            name=display_name,
            vendor_product_id=vpid,
            category=cat,
            series=(item.series.strip() if item.series else None),
            year_group=yg,
            unit=(item.unit or "pcs"),
            buying_price=Decimal(str(item.buying_price)),
            selling_price=sp,
            image_keys=[],
        )
        db.add(row)
        try:
            db.flush()
            _ensure_category_label(db, cat)
            record_price_change(db, row.id, Decimal(str(item.buying_price)), sp)
            # Link add-ons
            for al in item.addon_links:
                if db.get(AddonProduct, al.addon_product_id):
                    exists = db.query(CatalogProductAddon).filter_by(
                        catalog_product_id=row.id, addon_product_id=al.addon_product_id
                    ).first()
                    if not exists:
                        db.add(CatalogProductAddon(
                            catalog_product_id=row.id,
                            addon_product_id=al.addon_product_id,
                            quantity_per_unit=al.quantity_per_unit,
                        ))
            # Link alternatives (bidirectional)
            for alt_id in item.alt_ids:
                if alt_id and db.get(CatalogProduct, alt_id):
                    for a_id, b_id in [(row.id, alt_id), (alt_id, row.id)]:
                        exists = db.query(CatalogProductAlternative).filter_by(
                            catalog_product_id=a_id,
                            alternative_catalog_product_id=b_id,
                        ).first()
                        if not exists:
                            db.add(CatalogProductAlternative(
                                catalog_product_id=a_id,
                                alternative_catalog_product_id=b_id,
                            ))
            db.commit()
            created.append({"row": i, "our_product_id": oid, "id": row.id})
        except IntegrityError:
            db.rollback()
            errors.append({"row": i, "error": f"Duplicate product ID or vendor SKU: {oid}"})
        except Exception as exc:
            db.rollback()
            errors.append({"row": i, "error": f"Unexpected error: {exc}"})
    return {"created": len(created), "errors": errors, "items": created}


@router.patch("/{product_id}", response_model=CatalogProductPublic, dependencies=[Depends(require_admin)])
def update_product(
    product_id: int,
    body: CatalogProductUpdate,
    db: Session = Depends(get_db),
) -> CatalogProductPublic:
    row = db.get(CatalogProduct, product_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found")

    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no fields to update")

    keys_now = row.image_keys if isinstance(row.image_keys, list) else []
    has_images = len(keys_now) > 0

    if "our_product_id" in data:
        new_oid = str(data.pop("our_product_id")).strip()
        if not new_oid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="our_product_id empty")
        if new_oid != row.our_product_id:
            if has_images:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail="cannot change our_product_id while images exist; remove images first",
                )
            row.our_product_id = new_oid

    if "vendor_id" in data:
        vid = data.pop("vendor_id")
        if db.get(Vendor, vid) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="vendor not found")
        row.vendor_id = vid

    if "name" in data:
        row.name = str(data.pop("name")).strip()

    if "vendor_product_id" in data:
        v = data.pop("vendor_product_id")
        row.vendor_product_id = str(v).strip() if v else row.vendor_product_id

    if "category" in data:
        cat = str(data.pop("category")).strip()
        row.category = cat
        _ensure_category_label(db, cat)

    if "series" in data:
        v = data.pop("series")
        row.series = str(v).strip() or None if v else None

    if "year_group" in data:
        v = data.pop("year_group")
        row.year_group = str(v).strip() or None if v else None

    if "unit" in data:
        row.unit = str(data.pop("unit")).strip() or "pcs"

    if "buying_price" in data:
        new_bp = Decimal(str(data.pop("buying_price")))
        if new_bp != row.buying_price:
            from app.routers.product_prices import record_price_change
            record_price_change(db, row.id, new_bp, row.selling_price)
        row.buying_price = new_bp

    if "selling_price" in data:
        v = data.pop("selling_price")
        new_sp = Decimal(str(v)) if v is not None else None
        if new_sp != row.selling_price:
            from app.routers.product_prices import record_price_change
            record_price_change(db, row.id, row.buying_price, new_sp)
        row.selling_price = new_sp

    if data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"unknown fields: {list(data.keys())}")

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        err = str(e.orig) if getattr(e, "orig", None) else ""
        if "our_product_id" in err or "uq_catalog_our_product_id" in err:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="our_product_id already in use",
            ) from None
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="vendor already has this vendor_product_id",
        ) from None
    db.refresh(row)
    return _to_public(row)


@router.delete("/{product_id}", dependencies=[Depends(require_admin)])
def delete_product(product_id: int, db: Session = Depends(get_db)) -> dict:
    """Soft-delete: moves product to recycle bin. Use /permanent to hard-delete."""
    row = db.get(CatalogProduct, product_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found")
    row.deleted_at = datetime.now(timezone.utc)
    row.is_active = False
    db.commit()
    return {"ok": True, "id": product_id, "soft_deleted": True}


@router.post("/{product_id}/restore", dependencies=[Depends(require_admin)])
def restore_product(product_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(CatalogProduct, product_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found")
    row.deleted_at = None
    row.is_active = True
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="cannot restore: our_product_id or vendor SKU already in use by an active product",
        ) from None
    return {"ok": True, "id": product_id, "restored": True}


@router.delete("/{product_id}/permanent", dependencies=[Depends(require_admin)])
def permanently_delete_product(product_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(CatalogProduct, product_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found")
    keys = row.image_keys if isinstance(row.image_keys, list) else []
    db.delete(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="cannot permanently delete: product has associated orders or stock entries",
        ) from None
    delete_keys([str(k) for k in keys])
    return {"ok": True, "id": product_id, "permanently_deleted": True}


def _key_belongs_to_product(row: CatalogProduct, key: str) -> bool:
    stem = safe_catalog_stem(row.our_product_id)
    base = f"product_images/{stem}"
    return key == f"{base}.png" or (
        key.startswith(f"{base}_") and key.endswith(".png")
    )


@router.post("/{product_id}/images", response_model=CatalogProductPublic, dependencies=[Depends(require_admin)])
async def upload_images(
    product_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> CatalogProductPublic:
    if not storage_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 storage not configured (set S3_* env vars)",
        )
    row = db.get(CatalogProduct, product_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found")

    stem = safe_catalog_stem(row.our_product_id)
    keys = list(row.image_keys) if isinstance(row.image_keys, list) else []
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no files")

    for uf in files:
        raw = await uf.read()
        if not raw:
            continue
        ct = uf.content_type or "application/octet-stream"
        key = next_image_key(stem, keys)
        upload_bytes(key, raw, ct)
        keys.append(key)

    row.image_keys = keys
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_public(row)


@router.delete("/{product_id}/images", response_model=CatalogProductPublic, dependencies=[Depends(require_admin)])
def delete_image(
    product_id: int,
    body: ImageDeleteBody,
    db: Session = Depends(get_db),
) -> CatalogProductPublic:
    row = db.get(CatalogProduct, product_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found")

    key = body.key.strip()
    if not _key_belongs_to_product(row, key):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="key does not belong to this product")

    keys = list(row.image_keys) if isinstance(row.image_keys, list) else []
    str_keys = [str(k) for k in keys]
    if key not in str_keys:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="image key not on this product")

    new_keys = [k for k in str_keys if k != key]
    row.image_keys = new_keys
    db.add(row)
    db.commit()
    db.refresh(row)
    delete_keys([key])
    return _to_public(row)
