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
DEFAULT_YEAR_GROUP = "2026-27"

from app.routers.catalog.router import router

@router.post("/products/bulk", response_model=List[CatalogProductPublic], status_code=201, dependencies=[Depends(require_permission("catalog.write"))])
def bulk_create(body: CatalogBulkCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("catalog.write"))) -> List[CatalogProductPublic]:
    vendor = db.get(Vendor, body.vendor_id)
    if not vendor or not vendor.is_active:
        raise HTTPException(400, "vendor not found")

    # Staff always get default year; only admin may set year_group.
    def _year_for_item(raw: Optional[str]) -> Optional[str]:
        if auth.is_admin:
            return (raw or DEFAULT_YEAR_GROUP) or DEFAULT_YEAR_GROUP
        return DEFAULT_YEAR_GROUP

    batch_keys = [sku_year_label(i.our_product_id.strip(), _year_for_item(i.year_group)) for i in body.items]
    if len(batch_keys) != len(set(k.lower() for k in batch_keys)):
        raise HTTPException(400, "duplicate our_product_id + year_group in batch")
    for item in body.items:
        pid = item.our_product_id.strip()
        yg = _year_for_item(item.year_group)
        clash = find_active_sku_year(db, pid, yg)
        if clash:
            raise HTTPException(409, f"our_product_id {pid} already exists for year group {year_key(yg) or '—'}")

    created: list[CatalogProduct] = []
    id_map: dict[str, int] = {}

    for item in body.items:
        row = CatalogProduct(
            our_product_id=item.our_product_id.strip(),
            vendor_id=body.vendor_id,
            vendor_product_id=item.vendor_product_id.strip(),
            category=item.category,
            series=item.series,
            unit=item.unit,
            year_group=_year_for_item(item.year_group),
            marking=(item.marking.strip() if item.marking else None),
            buying_price=item.buying_price.quantize(Decimal("0.01")),
            selling_price=coerce_selling_price(item.buying_price, item.selling_price),
            image_keys=item.image_keys or [],
        )
        db.add(row)
        created.append(row)

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "duplicate our_product_id for this year group") from None

    for row in created:
        id_map[row.our_product_id] = row.id
        record_price_change(db, "catalog_product", row.id, row.buying_price, row.selling_price)

    linked_pairs: set[tuple[int, int]] = set()
    for item in body.items:
        pid = id_map[item.our_product_id]
        for alt_oid in item.alternative_our_product_ids[:MAX_ALTERNATIVES]:
            aid = id_map.get(alt_oid)
            if not aid:
                existing = db.query(CatalogProduct).filter(
                    CatalogProduct.our_product_id == alt_oid, CatalogProduct.is_active.is_(True)
                ).first()
                aid = existing.id if existing else None
            if not aid:
                # Previously silently dropped — same class of typo as an unmatched
                # addon SKU (_sync_addon_links below), which does report it. The
                # single-alternative endpoint (add_product_alternative) also 404s
                # on this instead of no-op'ing, so match that here too.
                raise HTTPException(
                    400,
                    f"alternative '{alt_oid}' for {item.our_product_id} not found — "
                    f"check the product ID and year group, or add it as its own row in this batch",
                )
            if aid != pid:
                _link_alternative(db, pid, aid, linked=linked_pairs)
                _link_alternative(db, aid, pid, linked=linked_pairs)

        addon_map: dict[str, int] = {}
        _sync_addon_links(db, pid, item.addon_links, addon_map)

    for row in created:
        log_from_auth(
            db, auth, action="create", entity_type="catalog",
            entity_id=row.id, entity_label=row.our_product_id,
            detail=f"Created product {row.our_product_id}",
        )
    db.commit()
    response_cache.invalidate("catalog:")
    response_cache.invalidate("stock:")
    for row in created:
        db.refresh(row)
    return [_to_public(r, db, auth=auth) for r in created]

@router.patch("/products/{product_id}", response_model=CatalogProductPublic, dependencies=[Depends(require_permission("catalog.write"))])
def update_product(
    product_id: int,
    body: CatalogUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("catalog.write")),
) -> CatalogProductPublic:
    row = db.get(CatalogProduct, product_id)
    if not row or not row.is_active:
        raise HTTPException(404, "product not found")

    before = row_snapshot(row, TRACKED_FIELDS["catalog_product"])
    data = body.model_dump(exclude_unset=True)
    alt_ids = data.pop("alternative_our_product_ids", None)
    addon_links = data.pop("addon_links", None)

    if "our_product_id" in data and data["our_product_id"]:
        new_id = data["our_product_id"].strip()
        row.our_product_id = new_id
        del data["our_product_id"]

    if "year_group" in data:
        if not auth.is_admin:
            # Staff cannot change year group
            del data["year_group"]
        else:
            row.year_group = data["year_group"] or None
            del data["year_group"]

    clash = find_active_sku_year(db, row.our_product_id, row.year_group, exclude_id=product_id)
    if clash:
        yg = year_key(row.year_group) or "—"
        raise HTTPException(409, f"product id {row.our_product_id} already exists for year group {yg}")

    price_changed = False
    if "buying_price" in data and data["buying_price"] is not None:
        row.buying_price = data["buying_price"].quantize(Decimal("0.01"))
        price_changed = True
        del data["buying_price"]
    if "selling_price" in data:
        row.selling_price = coerce_selling_price(row.buying_price, data["selling_price"])
        price_changed = True
        del data["selling_price"]
    elif price_changed:
        # buy changed alone — clear accidental sell==buy copy
        coerced = coerce_selling_price(row.buying_price, row.selling_price)
        if coerced != row.selling_price:
            row.selling_price = coerced

    for k, v in data.items():
        setattr(row, k, v)

    if price_changed:
        record_price_change(db, "catalog_product", row.id, row.buying_price, row.selling_price)

    if alt_ids is not None:
        alt_db_ids = []
        for alt_oid in alt_ids[:MAX_ALTERNATIVES]:
            existing = db.query(CatalogProduct).filter(
                CatalogProduct.our_product_id == alt_oid, CatalogProduct.is_active.is_(True)
            ).first()
            if existing and existing.id != product_id:
                alt_db_ids.append(existing.id)
        _sync_alternatives_bidirectional(db, product_id, alt_db_ids)

    if addon_links is not None:
        _sync_addon_links(db, product_id, [AddonLinkIn(**l) if isinstance(l, dict) else l for l in addon_links], {})

    after = row_snapshot(row, TRACKED_FIELDS["catalog_product"])
    summary = diff_summary("catalog_product", before, after)
    if summary != "updated" or alt_ids is not None or addon_links is not None:
        record_entity_history(db, "catalog_product", row.id, before, summary)

    log_from_auth(
        db,
        auth,
        action="update",
        entity_type="catalog",
        entity_id=row.id,
        entity_label=row.our_product_id,
        detail=summary if summary != "updated" else None,
    )
    db.commit()
    response_cache.invalidate("catalog:")
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    db.refresh(row)
    return _to_public(row, db, auth=auth)

def _to_public(
    row: CatalogProduct,
    db: Session,
    *,
    auth: AuthContext,
    addon_count: Optional[int] = None,
    alt_count: Optional[int] = None,
    vendor_name: Optional[str] = None,
    vendor_city: Optional[str] = None,
    max_images: Optional[int] = None,
) -> CatalogProductPublic:
    if vendor_name is None and vendor_city is None:
        vn, vc = _vendor_info(db, row.vendor_id)
    else:
        vn, vc = vendor_name, vendor_city
    keys = list(row.image_keys or [])
    if max_images is not None:
        keys = keys[: max(0, max_images)]
    if addon_count is None:
        addon_count = (
            db.query(CatalogAddonLink)
            .join(AddonProduct, AddonProduct.id == CatalogAddonLink.addon_product_id)
            .filter(
                CatalogAddonLink.catalog_product_id == row.id,
                AddonProduct.is_active.is_(True),
                AddonProduct.deleted_at.is_(None),
            )
            .count()
        )
    if alt_count is None:
        alt_target = aliased(CatalogProduct)
        alt_count = (
            db.query(CatalogAlternative)
            .join(alt_target, alt_target.id == CatalogAlternative.alternative_product_id)
            .filter(
                CatalogAlternative.product_id == row.id,
                alt_target.is_active.is_(True),
                alt_target.deleted_at.is_(None),
            )
            .count()
        )
    return CatalogProductPublic(
        id=row.id,
        our_product_id=row.our_product_id,
        vendor_id=row.vendor_id,
        vendor_name=vn,
        vendor_city=vc,
        vendor_product_id=row.vendor_product_id,
        category=row.category,
        second_category=row.second_category,
        series=row.series,
        unit=row.unit,
        year_group=row.year_group,
        marking=row.marking,
        buying_price=hide_cost(format(row.buying_price, "f") if row.buying_price is not None else None, auth),
        selling_price=(
            format(eff, "f")
            if (eff := effective_selling_price(row.buying_price, row.selling_price)) is not None
            else None
        ),
        image_keys=list(row.image_keys or []),
        image_urls=presigned_urls(keys),
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
        addon_count=int(addon_count or 0),
        alt_count=int(alt_count or 0),
    )

@router.post("/products/{product_id}/alternatives", dependencies=[Depends(require_permission("catalog.write"))])
def add_product_alternative(
    product_id: int,
    body: AlternativeLinkIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("catalog.write")),
) -> dict:
    row = db.get(CatalogProduct, product_id)
    if not row or not row.is_active or row.deleted_at:
        raise HTTPException(404, "product not found")
    alt_oid = (body.alternative_our_product_id or "").strip()
    alt = (
        db.query(CatalogProduct)
        .filter(
            CatalogProduct.our_product_id == alt_oid,
            CatalogProduct.is_active.is_(True),
            CatalogProduct.deleted_at.is_(None),
        )
        .first()
    )
    if not alt:
        raise HTTPException(404, "alternative product not found")
    if alt.id == product_id:
        raise HTTPException(400, "cannot link product to itself")
    existing = (
        db.query(CatalogAlternative)
        .filter(CatalogAlternative.product_id == product_id)
        .all()
    )
    if any(a.alternative_product_id == alt.id for a in existing):
        return {"ok": True, "already_linked": True}
    if len(existing) >= MAX_ALTERNATIVES:
        raise HTTPException(400, f"max {MAX_ALTERNATIVES} alternatives")
    _link_alternative(db, product_id, alt.id)
    _link_alternative(db, alt.id, product_id)
    log_from_auth(
        db, auth, action="update", entity_type="catalog",
        entity_id=row.id, entity_label=row.our_product_id,
        detail=f"Linked alternative {alt.our_product_id}",
    )
    db.commit()
    response_cache.invalidate("catalog:")
    response_cache.invalidate("stock:")
    return {"ok": True, "alternative_our_product_id": alt.our_product_id}

@router.get("/products/{product_id}", response_model=CatalogDetail, dependencies=[Depends(require_permission("catalog.read"))])
def get_product(product_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(get_auth_context)) -> CatalogDetail:
    row = db.get(CatalogProduct, product_id)
    if not row:
        raise HTTPException(404, "product not found")
    pub = _to_public(row, db, auth=auth)
    alts = db.query(CatalogAlternative).filter(CatalogAlternative.product_id == product_id).all()
    alt_pub = []
    for a in alts:
        alt = db.get(CatalogProduct, a.alternative_product_id)
        if alt and alt.is_active and not alt.deleted_at:
            vn, vc = _vendor_info(db, alt.vendor_id)
            alt_pub.append(AlternativePublic(
                id=a.id, product_id=a.product_id, alternative_product_id=a.alternative_product_id,
                alternative_our_product_id=alt.our_product_id, alternative_vendor_name=vn,
                alternative_vendor_city=vc,
                buying_price=hide_cost(format(alt.buying_price, "f"), auth),
                selling_price=format(alt.selling_price, "f") if alt.selling_price is not None else None,
                image_urls=presigned_urls(alt.image_keys or []),
            ))
    links = db.query(CatalogAddonLink).filter(CatalogAddonLink.catalog_product_id == product_id).all()
    link_pub = []
    for lk in links:
        addon = db.get(AddonProduct, lk.addon_product_id)
        if addon and addon.is_active and not addon.deleted_at:
            link_pub.append(AddonLinkPublic(
                id=lk.id, catalog_product_id=lk.catalog_product_id, addon_product_id=lk.addon_product_id,
                addon_our_product_id=addon.our_product_id, addon_name=addon.name or addon.our_product_id,
                quantity=lk.quantity, image_urls=presigned_urls(addon.image_keys or []),
            ))
    ph = [{"buying_price": hide_cost(format(p.buying_price, "f"), auth), "selling_price": format(p.selling_price, "f") if p.selling_price else None, "recorded_at": p.recorded_at.isoformat()} for p in list_price_history(db, "catalog_product", product_id)]
    eh = [
        {
            "change_summary": hide_cost_in_diff_summary(h.change_summary, auth),
            "valid_from": h.valid_from.isoformat(),
            "snapshot_json": hide_cost_in_snapshot_json(h.snapshot_json, auth),
        }
        for h in list_entity_history(db, "catalog_product", product_id)
    ]
    return CatalogDetail(**pub.model_dump(), alternatives=alt_pub, addon_links=link_pub, price_history=ph, change_history=eh)

def _sync_addon_links(db: Session, product_id: int, links: list[AddonLinkIn], addon_map: dict[str, int]) -> None:
    from sqlalchemy import func

    db.query(CatalogAddonLink).filter(CatalogAddonLink.catalog_product_id == product_id).delete(synchronize_session=False)
    seen_aids: dict[int, str] = {}
    for link in links:
        sku = (link.addon_our_product_id or "").strip()
        if not sku:
            continue
        aid = addon_map.get(sku) or addon_map.get(sku.lower())
        if not aid:
            addon = db.query(AddonProduct).filter(
                func.lower(AddonProduct.our_product_id) == sku.lower(),
                AddonProduct.is_active.is_(True),
                AddonProduct.deleted_at.is_(None),
            ).first()
            aid = addon.id if addon else None
        if not aid:
            raise HTTPException(
                400,
                f"add-on '{sku}' not found — create it under Products → Add-ons first (not a catalog SKU)",
            )
        if aid in seen_aids:
            # Would otherwise hit the (catalog_product_id, addon_product_id) unique
            # constraint and 500 — same add-on listed twice (typo/copy-paste), report it.
            raise HTTPException(400, f"add-on '{sku}' is listed more than once for this product — remove the duplicate row")
        seen_aids[aid] = sku
        db.add(CatalogAddonLink(catalog_product_id=product_id, addon_product_id=aid, quantity=link.quantity))

def _link_alternative(db: Session, a_id: int, b_id: int, *, linked: set[tuple[int, int]] | None = None) -> None:
    if a_id == b_id:
        return
    pair = (a_id, b_id)
    if linked is not None:
        if pair in linked:
            return
    if _count_alts(db, a_id) >= MAX_ALTERNATIVES:
        raise HTTPException(400, f"product {a_id} already has {MAX_ALTERNATIVES} alternatives")
    exists = db.query(CatalogAlternative).filter(
        CatalogAlternative.product_id == a_id,
        CatalogAlternative.alternative_product_id == b_id,
    ).first()
    if exists:
        if linked is not None:
            linked.add(pair)
        return
    db.add(CatalogAlternative(product_id=a_id, alternative_product_id=b_id))
    if linked is not None:
        linked.add(pair)

def _sync_alternatives_bidirectional(db: Session, product_id: int, alt_ids: list[int]) -> None:
    db.query(CatalogAlternative).filter(
        or_(
            CatalogAlternative.product_id == product_id,
            CatalogAlternative.alternative_product_id == product_id,
        )
    ).delete(synchronize_session=False)
    for aid in alt_ids[:MAX_ALTERNATIVES]:
        if aid == product_id:
            continue
        _link_alternative(db, product_id, aid)
        _link_alternative(db, aid, product_id)

def _vendor_info(db: Session, vendor_id: int) -> tuple[Optional[str], Optional[str]]:
    v = db.get(Vendor, vendor_id)
    if not v:
        return None, None
    city_name = None
    if v.city_id:
        c = db.get(City, v.city_id)
        city_name = c.name if c else None
    return v.business_name, city_name

def _count_alts(db: Session, product_id: int) -> int:
    return db.query(CatalogAlternative).filter(CatalogAlternative.product_id == product_id).count()

