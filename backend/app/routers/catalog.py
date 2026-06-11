from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.catalog_category_label import CatalogCategoryLabel
from app.models.catalog_product import CatalogProduct
from app.models.vendor import Vendor
from app.schemas.catalog import (
    CatalogProductCreate,
    CatalogProductPublic,
    CatalogProductUpdate,
    CategoryLabelCreate,
    ImageDeleteBody,
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
        vendor_product_id=row.vendor_product_id,
        category=row.category,
        series=row.series,
        year_group=row.year_group,
        unit=row.unit if row.unit else "pcs",
        buying_price=float(bp) if bp is not None else 0.0,
        selling_price=float(sp) if sp is not None else 0.0,
        image_keys=keys_str,
        image_urls=presigned_urls(keys_str),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/categories", dependencies=[Depends(require_admin)])
def categories(db: Session = Depends(get_db)) -> dict:
    return {"categories": _merged_categories(db)}


@router.get("/series", dependencies=[Depends(require_admin)])
def list_series(db: Session = Depends(get_db)) -> dict:
    rows = db.query(CatalogProduct.series).distinct().filter(CatalogProduct.series.isnot(None)).all()
    vals = sorted({r[0].strip() for r in rows if r[0] and r[0].strip()})
    return {"series": vals}


@router.get("/year-groups", dependencies=[Depends(require_admin)])
def list_year_groups(db: Session = Depends(get_db)) -> dict:
    rows = db.query(CatalogProduct.year_group).distinct().filter(CatalogProduct.year_group.isnot(None)).all()
    vals = sorted({r[0].strip() for r in rows if r[0] and r[0].strip()}, reverse=True)
    return {"year_groups": vals}


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


@router.post("/series", dependencies=[Depends(require_admin)])
def add_series(body: CategoryLabelCreate) -> dict:
    return {"ok": True, "name": body.name.strip()}


@router.delete("/series/{name}", dependencies=[Depends(require_admin)])
def delete_series(name: str) -> dict:
    return {"ok": True}


def _list_products_impl(
    db: Session,
    q: Optional[str] = None,
    vendor_id: Optional[int] = None,
    category: Optional[str] = None,
) -> List[CatalogProductPublic]:
    query = db.query(CatalogProduct)
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
    rows = query.order_by(CatalogProduct.id.asc()).all()
    return [_to_public(r) for r in rows]


@router.get("", response_model=List[CatalogProductPublic], dependencies=[Depends(require_admin)])
def list_products(
    q: Optional[str] = None,
    vendor_id: Optional[int] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
) -> List[CatalogProductPublic]:
    """List / search catalog; full rows include presigned image URLs."""
    return _list_products_impl(db, q=q, vendor_id=vendor_id, category=category)


@router.get("/{product_id}", response_model=CatalogProductPublic, dependencies=[Depends(require_admin)])
def get_product(product_id: int, db: Session = Depends(get_db)) -> CatalogProductPublic:
    row = db.get(CatalogProduct, product_id)
    if row is None:
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

    if db.get(Vendor, body.vendor_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="vendor not found")

    cat = body.category.strip()
    row = CatalogProduct(
        our_product_id=oid,
        vendor_id=body.vendor_id,
        name=body.name.strip(),
        vendor_product_id=body.vendor_product_id.strip(),
        category=cat,
        series=(body.series.strip() if body.series else None),
        year_group=(body.year_group.strip() if body.year_group else None),
        unit=(body.unit or "pcs"),
        buying_price=Decimal(str(body.buying_price)),
        selling_price=Decimal(str(body.selling_price)),
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
            detail="vendor already has this vendor_product_id",
        ) from None
    db.refresh(row)
    _ensure_category_label(db, cat)
    # Link addon if provided
    if body.addon_id:
        from app.models.addon_product import AddonProduct, CatalogProductAddon
        if db.get(AddonProduct, body.addon_id):
            existing_link = db.query(CatalogProductAddon).filter_by(
                catalog_product_id=row.id, addon_product_id=body.addon_id
            ).first()
            if not existing_link:
                db.add(CatalogProductAddon(
                    catalog_product_id=row.id,
                    addon_product_id=body.addon_id,
                    quantity_per_card=1,
                ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return _to_public(row)


@router.post("/bulk", dependencies=[Depends(require_admin)])
def bulk_create_products(body: list[CatalogProductCreate], db: Session = Depends(get_db)) -> dict:
    """Create multiple catalog products in one request. Returns created list + any errors."""
    created = []
    errors = []
    for i, item in enumerate(body):
        oid = item.our_product_id.strip()
        if not oid or not safe_catalog_stem(oid):
            errors.append({"row": i, "error": f"Invalid our_product_id: {oid}"})
            continue
        if db.get(Vendor, item.vendor_id) is None:
            errors.append({"row": i, "error": f"Vendor {item.vendor_id} not found"})
            continue
        cat = item.category.strip()
        row = CatalogProduct(
            our_product_id=oid,
            vendor_id=item.vendor_id,
            name=item.name.strip(),
            vendor_product_id=item.vendor_product_id.strip(),
            category=cat,
            series=(item.series.strip() if item.series else None),
            year_group=(item.year_group.strip() if item.year_group else None),
            unit=(item.unit or "pcs"),
            buying_price=Decimal(str(item.buying_price)),
            selling_price=Decimal(str(item.selling_price)),
            image_keys=[],
        )
        db.add(row)
        try:
            db.flush()
            _ensure_category_label(db, cat)
            created.append({"row": i, "our_product_id": oid})
        except IntegrityError:
            db.rollback()
            errors.append({"row": i, "error": f"Duplicate product ID: {oid}"})
    db.commit()
    return {"created": len(created), "errors": errors, "items": created}


@router.patch("/{product_id}", response_model=CatalogProductPublic, dependencies=[Depends(require_admin)])
def update_product(
    product_id: int,
    body: CatalogProductUpdate,
    db: Session = Depends(get_db),
) -> CatalogProductPublic:
    row = db.get(CatalogProduct, product_id)
    if row is None:
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
        row.vendor_product_id = str(data.pop("vendor_product_id")).strip()

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
        row.buying_price = Decimal(str(data.pop("buying_price")))

    if "selling_price" in data:
        row.selling_price = Decimal(str(data.pop("selling_price")))

    addon_id = data.pop("addon_id", None)

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
    # Handle addon link update
    if addon_id is not None:
        from app.models.addon_product import AddonProduct, CatalogProductAddon
        if addon_id == 0:
            # Remove all existing links
            db.query(CatalogProductAddon).filter_by(catalog_product_id=row.id).delete()
        elif db.get(AddonProduct, addon_id):
            existing_link = db.query(CatalogProductAddon).filter_by(
                catalog_product_id=row.id, addon_product_id=addon_id
            ).first()
            if not existing_link:
                db.add(CatalogProductAddon(
                    catalog_product_id=row.id,
                    addon_product_id=addon_id,
                    quantity_per_card=1,
                ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    db.refresh(row)
    return _to_public(row)


@router.delete("/{product_id}", dependencies=[Depends(require_admin)])
def delete_product(product_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(CatalogProduct, product_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found")
    keys = row.image_keys if isinstance(row.image_keys, list) else []
    db.delete(row)
    db.commit()
    delete_keys([str(k) for k in keys])
    return {"ok": True, "id": product_id}


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
