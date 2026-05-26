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
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return _to_public(row)


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

    if "buying_price" in data:
        row.buying_price = Decimal(str(data.pop("buying_price")))

    if "selling_price" in data:
        row.selling_price = Decimal(str(data.pop("selling_price")))

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
