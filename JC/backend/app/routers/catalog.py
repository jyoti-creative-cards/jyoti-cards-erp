from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
from app.services.history import (
    TRACKED_FIELDS,
    diff_summary,
    list_entity_history,
    list_price_history,
    record_entity_history,
    record_price_change,
    row_snapshot,
)
from app.services.storage import image_key, presigned_urls, storage_configured, upload_bytes, vendor_folder_slug

router = APIRouter(prefix="/catalog", tags=["catalog"])

MAX_ALTERNATIVES = 3


def _vendor_info(db: Session, vendor_id: int) -> tuple[Optional[str], Optional[str]]:
    v = db.get(Vendor, vendor_id)
    if not v:
        return None, None
    city_name = None
    if v.city_id:
        c = db.get(City, v.city_id)
        city_name = c.name if c else None
    return v.business_name, city_name


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


def _to_public(
    row: CatalogProduct,
    db: Session,
    *,
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
        addon_count = db.query(CatalogAddonLink).filter(CatalogAddonLink.catalog_product_id == row.id).count()
    if alt_count is None:
        alt_count = db.query(CatalogAlternative).filter(CatalogAlternative.product_id == row.id).count()
    return CatalogProductPublic(
        id=row.id,
        our_product_id=row.our_product_id,
        vendor_id=row.vendor_id,
        vendor_name=vn,
        vendor_city=vc,
        vendor_product_id=row.vendor_product_id,
        category=row.category,
        series=row.series,
        unit=row.unit,
        year_group=row.year_group,
        buying_price=format(row.buying_price, "f"),
        selling_price=format(row.selling_price, "f") if row.selling_price is not None else None,
        image_keys=list(row.image_keys or []),
        image_urls=presigned_urls(keys),
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
        addon_count=int(addon_count or 0),
        alt_count=int(alt_count or 0),
    )


def _count_alts(db: Session, product_id: int) -> int:
    return db.query(CatalogAlternative).filter(CatalogAlternative.product_id == product_id).count()


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


def _sync_addon_links(db: Session, product_id: int, links: list[AddonLinkIn], addon_map: dict[str, int]) -> None:
    db.query(CatalogAddonLink).filter(CatalogAddonLink.catalog_product_id == product_id).delete(synchronize_session=False)
    for link in links:
        aid = addon_map.get(link.addon_our_product_id)
        if not aid:
            addon = db.query(AddonProduct).filter(
                AddonProduct.our_product_id == link.addon_our_product_id,
                AddonProduct.is_active.is_(True),
            ).first()
            aid = addon.id if addon else None
        if not aid:
            raise HTTPException(400, f"addon {link.addon_our_product_id} not found")
        db.add(CatalogAddonLink(catalog_product_id=product_id, addon_product_id=aid, quantity=link.quantity))


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
            )
        )
    return out


@router.post("/products/check-duplicates", response_model=CheckDuplicatesResponse, dependencies=[Depends(require_permission("catalog.read"))])
def check_duplicates(body: CheckDuplicatesRequest, db: Session = Depends(get_db)) -> CheckDuplicatesResponse:
    ids = [i.strip().lower() for i in body.our_product_ids if i.strip()]
    if not ids:
        return CheckDuplicatesResponse(duplicates=[])
    rows = (
        db.query(CatalogProduct.our_product_id)
        .filter(
            func.lower(CatalogProduct.our_product_id).in_(ids),
            CatalogProduct.is_active.is_(True),
            CatalogProduct.deleted_at.is_(None),
        )
        .all()
    )
    return CheckDuplicatesResponse(duplicates=sorted({r[0] for r in rows}))


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


@router.get("/alternatives-board", dependencies=[Depends(require_permission("catalog.read"))])
def alternatives_board(db: Session = Depends(get_db)) -> list[dict]:
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
                "buying_price": format(alt.buying_price, "f"),
                "selling_price": format(alt.selling_price, "f") if alt.selling_price is not None else None,
                "image_urls": presigned_urls((alt.image_keys or [])[:1]),
            })
        out.append({
            "id": p.id,
            "our_product_id": p.our_product_id,
            "vendor_name": vn,
            "vendor_city": vc,
            "buying_price": format(p.buying_price, "f"),
            "selling_price": format(p.selling_price, "f") if p.selling_price is not None else None,
            "image_urls": presigned_urls((p.image_keys or [])[:1]),
            "alt_count": len(alts),
            "alternatives": alts,
        })
    return out


@router.get("/products", response_model=CatalogListResponse, dependencies=[Depends(require_permission("catalog.read"))])
def list_products(
    db: Session = Depends(get_db),
    search: Optional[str] = Query(None),
    vendor_id: Optional[int] = Query(None),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> CatalogListResponse:
    q = db.query(CatalogProduct).filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
    if vendor_id:
        q = q.filter(CatalogProduct.vendor_id == vendor_id)
    if search:
        s = f"%{search.lower()}%"
        q = q.filter(or_(
            func.lower(CatalogProduct.our_product_id).like(s),
            func.lower(CatalogProduct.vendor_product_id).like(s),
            func.lower(CatalogProduct.category).like(s),
        ))
    total = q.count()
    rows = q.order_by(CatalogProduct.id.desc()).offset(offset).limit(limit).all()
    ids = [r.id for r in rows]
    addon_counts: dict[int, int] = {}
    alt_counts: dict[int, int] = {}
    vendor_map = _vendor_info_map(db, [r.vendor_id for r in rows])
    if ids:
        for pid, cnt in (
            db.query(CatalogAddonLink.catalog_product_id, func.count(CatalogAddonLink.id))
            .filter(CatalogAddonLink.catalog_product_id.in_(ids))
            .group_by(CatalogAddonLink.catalog_product_id)
            .all()
        ):
            addon_counts[pid] = int(cnt)
        for pid, cnt in (
            db.query(CatalogAlternative.product_id, func.count(CatalogAlternative.id))
            .filter(CatalogAlternative.product_id.in_(ids))
            .group_by(CatalogAlternative.product_id)
            .all()
        ):
            alt_counts[pid] = int(cnt)
    return CatalogListResponse(
        items=[
            _to_public(
                r,
                db,
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


@router.get("/products/{product_id}", response_model=CatalogDetail, dependencies=[Depends(require_permission("catalog.read"))])
def get_product(product_id: int, db: Session = Depends(get_db)) -> CatalogDetail:
    row = db.get(CatalogProduct, product_id)
    if not row:
        raise HTTPException(404, "product not found")
    pub = _to_public(row, db)
    alts = db.query(CatalogAlternative).filter(CatalogAlternative.product_id == product_id).all()
    alt_pub = []
    for a in alts:
        alt = db.get(CatalogProduct, a.alternative_product_id)
        if alt:
            vn, vc = _vendor_info(db, alt.vendor_id)
            alt_pub.append(AlternativePublic(
                id=a.id, product_id=a.product_id, alternative_product_id=a.alternative_product_id,
                alternative_our_product_id=alt.our_product_id, alternative_vendor_name=vn,
                alternative_vendor_city=vc,
                buying_price=format(alt.buying_price, "f"),
                selling_price=format(alt.selling_price, "f") if alt.selling_price is not None else None,
                image_urls=presigned_urls(alt.image_keys or []),
            ))
    links = db.query(CatalogAddonLink).filter(CatalogAddonLink.catalog_product_id == product_id).all()
    link_pub = []
    for lk in links:
        addon = db.get(AddonProduct, lk.addon_product_id)
        if addon:
            link_pub.append(AddonLinkPublic(
                id=lk.id, catalog_product_id=lk.catalog_product_id, addon_product_id=lk.addon_product_id,
                addon_our_product_id=addon.our_product_id, addon_name=addon.name or addon.our_product_id,
                quantity=lk.quantity, image_urls=presigned_urls(addon.image_keys or []),
            ))
    ph = [{"buying_price": format(p.buying_price, "f"), "selling_price": format(p.selling_price, "f") if p.selling_price else None, "recorded_at": p.recorded_at.isoformat()} for p in list_price_history(db, "catalog_product", product_id)]
    eh = [{"change_summary": h.change_summary, "valid_from": h.valid_from.isoformat(), "snapshot_json": h.snapshot_json} for h in list_entity_history(db, "catalog_product", product_id)]
    return CatalogDetail(**pub.model_dump(), alternatives=alt_pub, addon_links=link_pub, price_history=ph, change_history=eh)


@router.post("/products/bulk", response_model=List[CatalogProductPublic], status_code=201, dependencies=[Depends(require_permission("catalog.write"))])
def bulk_create(body: CatalogBulkCreate, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permission("catalog.write"))) -> List[CatalogProductPublic]:
    vendor = db.get(Vendor, body.vendor_id)
    if not vendor or not vendor.is_active:
        raise HTTPException(400, "vendor not found")

    ids_in_batch = [i.our_product_id.strip() for i in body.items]
    if len(ids_in_batch) != len(set(ids_in_batch)):
        raise HTTPException(400, "duplicate our_product_id in batch")
    for pid in ids_in_batch:
        clash = db.query(CatalogProduct).filter(
            CatalogProduct.our_product_id == pid, CatalogProduct.is_active.is_(True)
        ).first()
        if clash:
            raise HTTPException(409, f"our_product_id {pid} already exists")

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
            year_group=item.year_group,
            buying_price=item.buying_price.quantize(Decimal("0.01")),
            selling_price=item.selling_price.quantize(Decimal("0.01")) if item.selling_price is not None else None,
            image_keys=item.image_keys or [],
        )
        db.add(row)
        created.append(row)

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "duplicate our_product_id") from None

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
            if aid and aid != pid:
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
    for row in created:
        db.refresh(row)
    return [_to_public(r, db) for r in created]


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
        if new_id != row.our_product_id:
            clash = db.query(CatalogProduct).filter(
                CatalogProduct.our_product_id == new_id,
                CatalogProduct.is_active.is_(True),
                CatalogProduct.id != product_id,
            ).first()
            if clash:
                raise HTTPException(409, f"product id {new_id} already exists")
            row.our_product_id = new_id
        del data["our_product_id"]

    price_changed = False
    if "buying_price" in data and data["buying_price"] is not None:
        row.buying_price = data["buying_price"].quantize(Decimal("0.01"))
        price_changed = True
        del data["buying_price"]
    if "selling_price" in data:
        row.selling_price = data["selling_price"].quantize(Decimal("0.01")) if data["selling_price"] is not None else None
        price_changed = True
        del data["selling_price"]

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
    db.refresh(row)
    return _to_public(row, db)


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


@router.post("/upload-image", dependencies=[Depends(require_permission("catalog.write"))])
async def upload_image(
    vendor_id: int = Form(...),
    our_product_id: str = Form(...),
    image_index: int = Form(..., ge=1, le=10),
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
    key = image_key(folder, our_product_id, image_index, ext)
    upload_bytes(key, data, file.content_type or "image/jpeg")
    return {"key": key, "url": presigned_urls([key])[0]}
