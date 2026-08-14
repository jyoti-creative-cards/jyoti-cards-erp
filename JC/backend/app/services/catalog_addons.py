from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.addon_product import AddonProduct
from app.models.catalog_addon_link import CatalogAddonLink
from app.services.storage import presigned_urls


def _addon_row(addon: AddonProduct, qty: int, *, with_images: bool) -> dict:
    img = None
    if with_images:
        img = (presigned_urls(addon.image_keys or []) or [None])[0]
    return {
        "addon_product_id": addon.id,
        "our_product_id": addon.our_product_id,
        "name": addon.name or addon.our_product_id,
        "quantity": int(qty or 1),
        "unit": addon.unit or "pc",
        "image_url": img,
    }


def addon_snapshots_for_product(
    db: Session, catalog_product_id: int, *, with_images: bool = False
) -> list[dict]:
    links = (
        db.query(CatalogAddonLink)
        .filter(CatalogAddonLink.catalog_product_id == catalog_product_id)
        .order_by(CatalogAddonLink.id.asc())
        .all()
    )
    out: list[dict] = []
    for link in links:
        addon = db.get(AddonProduct, link.addon_product_id)
        if not addon or not addon.is_active or addon.deleted_at:
            continue
        out.append(_addon_row(addon, link.quantity, with_images=with_images))
    return out


def attach_addons_to_totals(db: Session, totals: dict | None) -> dict:
    """Copy live catalog addons onto bill totals lines (by product id or SKU)."""
    if not isinstance(totals, dict):
        return {}
    lines = totals.get("lines")
    if not isinstance(lines, list):
        return totals
    from app.models.catalog_product import CatalogProduct

    cids: list[int] = []
    skus: list[str] = []
    for ln in lines:
        if not isinstance(ln, dict):
            continue
        cid = int(ln.get("catalog_product_id") or 0)
        if cid:
            cids.append(cid)
        elif ln.get("our_product_id"):
            skus.append(str(ln["our_product_id"]))
    sku_map: dict[str, int] = {}
    if skus:
        found = (
            db.query(CatalogProduct)
            .filter(CatalogProduct.our_product_id.in_(skus))
            .all()
        )
        sku_map = {p.our_product_id: p.id for p in found}
        cids.extend(sku_map.values())
    addon_map = addon_snapshots_map(db, cids, with_images=False) if cids else {}
    enriched = []
    for ln in lines:
        if not isinstance(ln, dict):
            continue
        row = dict(ln)
        cid = int(row.get("catalog_product_id") or 0)
        if not cid and row.get("our_product_id"):
            cid = int(sku_map.get(str(row["our_product_id"])) or 0)
            if cid:
                row["catalog_product_id"] = cid
        live = addon_map.get(cid) if cid else None
        if live:
            row["addons"] = live
        elif not row.get("addons"):
            row["addons"] = []
        enriched.append(row)
    return {**totals, "lines": enriched}


def addon_snapshots_map(
    db: Session, catalog_product_ids: list[int], *, with_images: bool = False
) -> dict[int, list[dict]]:
    if not catalog_product_ids:
        return {}
    links = (
        db.query(CatalogAddonLink)
        .filter(CatalogAddonLink.catalog_product_id.in_(catalog_product_ids))
        .all()
    )
    addon_ids = {ln.addon_product_id for ln in links}
    addons = {a.id: a for a in db.query(AddonProduct).filter(AddonProduct.id.in_(addon_ids)).all()} if addon_ids else {}
    grouped: dict[int, list[dict]] = {pid: [] for pid in catalog_product_ids}
    for link in links:
        addon = addons.get(link.addon_product_id)
        if not addon or not addon.is_active or addon.deleted_at:
            continue
        grouped.setdefault(link.catalog_product_id, []).append(
            _addon_row(addon, link.quantity, with_images=with_images)
        )
    return grouped
