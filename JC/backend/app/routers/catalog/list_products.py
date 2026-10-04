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
from app.routers.catalog.bulk_create import _to_public

@router.get("/products", response_model=CatalogListResponse, dependencies=[Depends(require_permission("catalog.read"))])
def list_products(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
    search: Optional[str] = Query(None),
    vendor_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    series: Optional[str] = Query(None),
    price_min: Optional[Decimal] = Query(None, ge=0),
    price_max: Optional[Decimal] = Query(None, ge=0),
    no_sell_price: bool = Query(False),
    no_addons: bool = Query(False),
    year_group: Optional[str] = Query(None),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> CatalogListResponse:
    cache_key = (
        f"catalog:products:v3:{search or ''}:{vendor_id or ''}:{category or ''}:"
        f"{series or ''}:{year_group or ''}:{price_min}:{price_max}:{int(no_sell_price)}:{int(no_addons)}:{limit}:{offset}"
        f":cost={int(can_see_cost(auth))}"
    )
    cached = response_cache.get(cache_key)
    if cached is not None:
        return CatalogListResponse(**cached) if isinstance(cached, dict) else cached

    q = db.query(CatalogProduct).filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
    if vendor_id:
        q = q.filter(CatalogProduct.vendor_id == vendor_id)
    if category:
        q = q.filter(or_(
            CatalogProduct.category == category,
            CatalogProduct.second_category == category,
        ))
    if series:
        q = q.filter(CatalogProduct.series == series)
    if year_group:
        q = q.filter(CatalogProduct.year_group == year_group)
    if no_sell_price:
        # Null sell, or sell copied equal to buy (common seed / import mistake)
        q = q.filter(
            or_(
                CatalogProduct.selling_price.is_(None),
                CatalogProduct.selling_price == CatalogProduct.buying_price,
            )
        )
    if no_addons:
        linked_ids = db.query(CatalogAddonLink.catalog_product_id).distinct()
        q = q.filter(~CatalogProduct.id.in_(linked_ids))
    if price_min is not None:
        q = q.filter(func.coalesce(CatalogProduct.selling_price, CatalogProduct.buying_price) >= price_min)
    if price_max is not None:
        q = q.filter(func.coalesce(CatalogProduct.selling_price, CatalogProduct.buying_price) <= price_max)
    if search:
        s = f"%{search.lower()}%"
        q = q.outerjoin(Vendor, Vendor.id == CatalogProduct.vendor_id).outerjoin(City, City.id == Vendor.city_id)
        q = q.filter(or_(
            func.lower(CatalogProduct.our_product_id).like(s),
            func.lower(CatalogProduct.vendor_product_id).like(s),
            func.lower(func.coalesce(CatalogProduct.category, "")).like(s),
            func.lower(func.coalesce(CatalogProduct.second_category, "")).like(s),
            func.lower(func.coalesce(CatalogProduct.series, "")).like(s),
            func.lower(func.coalesce(CatalogProduct.year_group, "")).like(s),
            func.lower(func.coalesce(Vendor.business_name, "")).like(s),
            func.lower(func.coalesce(City.name, "")).like(s),
        ))
    total = q.count()
    rows = (
        q.order_by(CatalogProduct.our_product_id.asc(), CatalogProduct.year_group.asc().nullsfirst(), CatalogProduct.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    ids = [r.id for r in rows]
    addon_counts: dict[int, int] = {}
    alt_counts: dict[int, int] = {}
    vendor_map = _vendor_info_map(db, [r.vendor_id for r in rows])
    if ids:
        for pid, cnt in (
            db.query(CatalogAddonLink.catalog_product_id, func.count(CatalogAddonLink.id))
            .join(AddonProduct, AddonProduct.id == CatalogAddonLink.addon_product_id)
            .filter(
                CatalogAddonLink.catalog_product_id.in_(ids),
                AddonProduct.is_active.is_(True),
                AddonProduct.deleted_at.is_(None),
            )
            .group_by(CatalogAddonLink.catalog_product_id)
            .all()
        ):
            addon_counts[pid] = int(cnt)
        alt_target = aliased(CatalogProduct)
        for pid, cnt in (
            db.query(CatalogAlternative.product_id, func.count(CatalogAlternative.id))
            .join(alt_target, alt_target.id == CatalogAlternative.alternative_product_id)
            .filter(
                CatalogAlternative.product_id.in_(ids),
                alt_target.is_active.is_(True),
                alt_target.deleted_at.is_(None),
            )
            .group_by(CatalogAlternative.product_id)
            .all()
        ):
            alt_counts[pid] = int(cnt)
    result = CatalogListResponse(
        items=[
            _to_public(
                r,
                db,
                auth=auth,
                addon_count=addon_counts.get(r.id, 0),
                alt_count=alt_counts.get(r.id, 0),
                vendor_name=vendor_map.get(r.vendor_id, (None, None))[0],
                vendor_city=vendor_map.get(r.vendor_id, (None, None))[1],
                max_images=1,
            )
            for r in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
    response_cache.set(cache_key, result.model_dump(), 25.0)
    return result

@router.get("/alternatives-board", dependencies=[Depends(require_permission("catalog.read"))])
def alternatives_board(db: Session = Depends(get_db), auth: AuthContext = Depends(get_auth_context)) -> list[dict]:
    """Products with enriched alternatives for the manage-alternatives UI."""
    products = (
        db.query(CatalogProduct)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
        .order_by(CatalogProduct.our_product_id.asc())
        .all()
    )
    if not products:
        return []
    ids = [p.id for p in products]
    alt_rows = db.query(CatalogAlternative).filter(CatalogAlternative.product_id.in_(ids)).all()
    by_product: dict[int, list] = {}
    for a in alt_rows:
        by_product.setdefault(a.product_id, []).append(a)

    alt_ids = sorted({a.alternative_product_id for a in alt_rows})
    alt_products = {
        p.id: p
        for p in (
            db.query(CatalogProduct).filter(CatalogProduct.id.in_(alt_ids)).all() if alt_ids else []
        )
    }
    vendor_map = _vendor_info_map(
        db,
        [p.vendor_id for p in products] + [p.vendor_id for p in alt_products.values()],
    )

    out = []
    for p in products:
        vn, vc = vendor_map.get(p.vendor_id, (None, None))
        alts = []
        for a in by_product.get(p.id, []):
            alt = alt_products.get(a.alternative_product_id)
            if not alt or not alt.is_active or alt.deleted_at:
                continue
            avn, avc = vendor_map.get(alt.vendor_id, (None, None))
            alts.append({
                "id": a.id,
                "alternative_product_id": alt.id,
                "our_product_id": alt.our_product_id,
                "vendor_name": avn,
                "vendor_city": avc,
                "buying_price": hide_cost(format(alt.buying_price, "f") if alt.buying_price is not None else None, auth),
                "selling_price": format(alt.selling_price, "f") if alt.selling_price is not None else None,
                "image_urls": presigned_urls((alt.image_keys or [])[:1]),
            })
        out.append({
            "id": p.id,
            "our_product_id": p.our_product_id,
            "vendor_name": vn,
            "vendor_city": vc,
            "buying_price": hide_cost(format(p.buying_price, "f") if p.buying_price is not None else None, auth),
            "selling_price": format(p.selling_price, "f") if p.selling_price is not None else None,
            "image_urls": presigned_urls((p.image_keys or [])[:1]),
            "alt_count": len(alts),
            "alternatives": alts,
        })
    return out

def _vendor_info_map(db: Session, vendor_ids: list[int]) -> dict[int, tuple[Optional[str], Optional[str]]]:
    """Batch vendor + city names (avoids N+1 on list endpoints)."""
    ids = sorted({int(v) for v in vendor_ids if v})
    if not ids:
        return {}
    vendors = db.query(Vendor).filter(Vendor.id.in_(ids)).all()
    city_ids = sorted({v.city_id for v in vendors if v.city_id})
    cities = {
        c.id: c.name
        for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
    }
    return {
        v.id: (v.business_name, cities.get(v.city_id) if v.city_id else None)
        for v in vendors
    }

