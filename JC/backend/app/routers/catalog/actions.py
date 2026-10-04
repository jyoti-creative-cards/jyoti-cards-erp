from __future__ import annotations
"""Split from app/routers/catalog.py."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context, require_permission
from app.models.addon_product import AddonProduct
from app.models.catalog_addon_link import CatalogAddonLink
from app.models.catalog_alternative import CatalogAlternative
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.vendor import Vendor
from app.schemas.catalog import (
    AddonLinkIn,
    AddonLinkPublic,
    AlternativePublic,
    CatalogBulkCreate,
    CatalogDetail,
    CatalogListResponse,
    CatalogProductPublic,
    CatalogUpdate,
    CheckDuplicatesRequest,
    CheckDuplicatesResponse,
    VendorOption,
)
from app.services.activity import log_from_auth
from app.services.cost_visibility import (
    can_see_cost,
    hide_cost,
    hide_cost_in_diff_summary,
    hide_cost_in_snapshot_json,
)
from app.services.pricing import coerce_selling_price, effective_selling_price
from app.services.history import (
    TRACKED_FIELDS,
    diff_summary,
    list_entity_history,
    list_price_history,
    record_entity_history,
    record_price_change,
    row_snapshot,
)
from app.services import response_cache
from app.services.catalog_identity import find_active_sku_year, sku_year_label, year_key
from app.services.storage import image_key, presigned_urls, storage_configured, upload_bytes, vendor_folder_slug


MAX_ALTERNATIVES = 3

from app.routers.catalog.router import router

@router.get("/vendors", response_model=List[VendorOption], dependencies=[Depends(require_permission("catalog.read"))])
def list_vendors_for_catalog(db: Session = Depends(get_db)) -> List[VendorOption]:
    rows = (
        db.query(Vendor)
        .filter(Vendor.is_active.is_(True), Vendor.deleted_at.is_(None))
        .order_by(Vendor.business_name.asc())
        .all()
    )
    out: list[VendorOption] = []
    for v in rows:
        city_name = None
        if v.city_id:
            city = db.get(City, v.city_id)
            city_name = city.name if city else None
        out.append(
            VendorOption(
                id=v.id,
                business_name=v.business_name,
                city_name=city_name,
                alias=v.alias,
                is_active=v.is_active,
                vendor_number=v.vendor_number,
                phone=v.phone,
            )
        )
    return out

@router.post("/products/check-duplicates", response_model=CheckDuplicatesResponse, dependencies=[Depends(require_permission("catalog.read"))])
def check_duplicates(body: CheckDuplicatesRequest, db: Session = Depends(get_db)) -> CheckDuplicatesResponse:
    pairs: list[tuple[str, str]] = []
    for item in body.items or []:
        sku = (item.our_product_id or "").strip()
        if sku:
            pairs.append((sku, year_key(item.year_group)))
    if not pairs:
        for raw in body.our_product_ids or []:
            sku = (raw or "").strip()
            if sku:
                pairs.append((sku, ""))
    if not pairs:
        return CheckDuplicatesResponse(duplicates=[])
    found: set[str] = set()
    for sku, yg in pairs:
        clash = find_active_sku_year(db, sku, yg or None)
        if clash:
            found.add(sku_year_label(clash.our_product_id, clash.year_group))
    return CheckDuplicatesResponse(duplicates=sorted(found))

@router.get("/product-options", dependencies=[Depends(require_permission("catalog.read"))])
def product_options(db: Session = Depends(get_db)) -> list[dict]:
    """Lightweight id + SKU list for alternative dropdowns (no images)."""
    rows = (
        db.query(CatalogProduct.id, CatalogProduct.our_product_id)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
        .order_by(CatalogProduct.our_product_id.asc())
        .limit(2000)
        .all()
    )
    return [{"id": int(r.id), "our_product_id": r.our_product_id} for r in rows]

@router.get("/categories", dependencies=[Depends(require_permission("catalog.read"))])
def list_product_categories(db: Session = Depends(get_db)) -> list[str]:
    """Category dropdown values, taken from the products themselves."""
    rows = (
        db.query(CatalogProduct.category, CatalogProduct.second_category)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
        .all()
    )
    found: set[str] = set()
    for category, second in rows:
        for value in (category, second):
            text = (value or "").strip()
            if text:
                found.add(text)
    return sorted(found, key=str.lower)

@router.get("/year-groups", dependencies=[Depends(require_permission("catalog.read"))])
def list_product_year_groups(db: Session = Depends(get_db)) -> list[str]:
    """Year dropdown values, taken from the products themselves."""
    rows = (
        db.query(CatalogProduct.year_group)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
        .all()
    )
    found = {(value or "").strip() for (value,) in rows if (value or "").strip()}
    found.add("2026-27")
    return sorted(found)

@router.delete(
    "/products/{product_id}/alternatives/{alt_our_product_id}",
    dependencies=[Depends(require_permission("catalog.write"))],
)
def remove_product_alternative(
    product_id: int,
    alt_our_product_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("catalog.write")),
) -> dict:
    row = db.get(CatalogProduct, product_id)
    if not row or not row.is_active:
        raise HTTPException(404, "product not found")
    alt = (
        db.query(CatalogProduct)
        .filter(CatalogProduct.our_product_id == alt_our_product_id)
        .first()
    )
    if not alt:
        raise HTTPException(404, "alternative product not found")
    db.query(CatalogAlternative).filter(
        ((CatalogAlternative.product_id == product_id) & (CatalogAlternative.alternative_product_id == alt.id))
        | ((CatalogAlternative.product_id == alt.id) & (CatalogAlternative.alternative_product_id == product_id))
    ).delete(synchronize_session=False)
    log_from_auth(
        db, auth, action="update", entity_type="catalog",
        entity_id=row.id, entity_label=row.our_product_id,
        detail=f"Unlinked alternative {alt.our_product_id}",
    )
    db.commit()
    response_cache.invalidate("catalog:")
    response_cache.invalidate("stock:")
    return {"ok": True}

@router.delete("/products/{product_id}", status_code=204, dependencies=[Depends(require_permission("catalog.write"))])
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("catalog.write")),
) -> None:
    row = db.get(CatalogProduct, product_id)
    if not row or not row.is_active:
        raise HTTPException(404, "product not found")
    row.is_active = False
    row.deleted_at = datetime.now(timezone.utc)
    log_from_auth(db, auth, action="delete", entity_type="catalog", entity_id=row.id, entity_label=row.our_product_id)
    db.commit()
    response_cache.invalidate("catalog:")
    response_cache.invalidate("stock:")

@router.post("/upload-image", dependencies=[Depends(require_permission("catalog.write"))])
async def upload_image(
    vendor_id: int = Form(...),
    our_product_id: str = Form(...),
    image_index: int = Form(..., ge=1, le=10),
    year_group: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    if not storage_configured():
        raise HTTPException(503, "S3 not configured")
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(400, "vendor not found")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "file too large (max 5MB)")
    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    content_type = (file.content_type or "").lower()
    if content_type and content_type not in allowed:
        raise HTTPException(400, f"unsupported file type: {content_type}")
    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()[:5]
    folder = vendor_folder_slug(vendor.business_name)
    key = image_key(folder, our_product_id, image_index, ext, year_group=year_group)
    upload_bytes(key, data, file.content_type or "image/jpeg")
    return {"key": key, "url": presigned_urls([key])[0]}

