from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.addon_product import AddonProduct
from app.models.catalog_addon_link import CatalogAddonLink
from app.services.storage import presigned_urls


def addon_snapshots_for_product(db: Session, catalog_product_id: int) -> list[dict]:
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
        img = (presigned_urls(addon.image_keys or []) or [None])[0]
        out.append(
            {
                "addon_product_id": addon.id,
                "our_product_id": addon.our_product_id,
                "name": addon.name or addon.our_product_id,
                "quantity": int(link.quantity or 1),
                "unit": addon.unit or "pc",
                "image_url": img,
            }
        )
    return out


def addon_snapshots_map(db: Session, catalog_product_ids: list[int]) -> dict[int, list[dict]]:
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
        img = (presigned_urls(addon.image_keys or []) or [None])[0]
        grouped.setdefault(link.catalog_product_id, []).append(
            {
                "addon_product_id": addon.id,
                "our_product_id": addon.our_product_id,
                "name": addon.name or addon.our_product_id,
                "quantity": int(link.quantity or 1),
                "unit": addon.unit or "pc",
                "image_url": img,
            }
        )
    return grouped
