from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.addon_product import AddonProduct
from app.models.catalog_addon_link import CatalogAddonLink
from app.services.storage import presigned_urls


def _plate_label(our_product_id: str | None, name: str | None) -> str:
    return f"{our_product_id or ''} {name or ''}".lower().replace("_", " ").replace("-", " ")


def is_name_plate(our_product_id: str | None, name: str | None) -> bool:
    return "name plate" in _plate_label(our_product_id, name)


def is_initial_plate(our_product_id: str | None, name: str | None) -> bool:
    return "initial plate" in _plate_label(our_product_id, name)


def addon_sell_price(addon: AddonProduct) -> Decimal:
    raw = getattr(addon, "selling_price", None)
    if raw is not None and Decimal(str(raw)) > 0:
        return Decimal(str(raw)).quantize(Decimal("0.01"))
    if is_name_plate(addon.our_product_id, addon.name):
        return Decimal("2.00")
    if is_initial_plate(addon.our_product_id, addon.name):
        return Decimal("3.00")
    return Decimal("0.00")


def _addon_row(addon: AddonProduct, qty: int, *, with_images: bool) -> dict:
    img = None
    if with_images:
        img = (presigned_urls(addon.image_keys or []) or [None])[0]
    price = addon_sell_price(addon)
    return {
        "addon_product_id": addon.id,
        "our_product_id": addon.our_product_id,
        "name": addon.name or addon.our_product_id,
        "quantity": int(qty or 1),
        "unit": addon.unit or "pc",
        "image_url": img,
        "selling_price": format(price, "f"),
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
        # An explicit list — including [] — is the order's choice. A removed
        # Name Plate must stay off the bill. Only lines that never stored a
        # snapshot (no "addons" key) fall back to the live catalog.
        if "addons" in row and isinstance(row.get("addons"), list):
            enriched.append(row)
            continue
        live = addon_map.get(cid) if cid else None
        if live:
            row["addons"] = live
        else:
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
        .order_by(CatalogAddonLink.id.asc())
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


def apply_billing_addons_to_totals(totals: dict | None, addon_map: dict, bill_items: list[dict]) -> dict:
    """Stamp the order's kept add-ons onto totals lines before they are saved.

    Empty list means the order removed every add-on. That must win over the
    live catalog links, which attach_addons_to_totals would otherwise copy on.
    """
    if not isinstance(totals, dict):
        return {}
    by_sku: dict[str, int] = {}
    for item in bill_items:
        sku = item.get("our_product_id")
        if sku and item.get("catalog_product_id"):
            by_sku[str(sku)] = int(item["catalog_product_id"])
    lines = []
    for ln in totals.get("lines") or []:
        if not isinstance(ln, dict):
            continue
        row = dict(ln)
        cid = int(row.get("catalog_product_id") or 0)
        if not cid:
            cid = by_sku.get(str(row.get("our_product_id") or ""), 0)
        if cid:
            row["catalog_product_id"] = cid
            row["addons"] = list(addon_map.get(int(cid)) or [])
        lines.append(row)
    return {**totals, "lines": lines}


def priced_addons_by_product(db: Session, catalog_product_ids: list[int]) -> dict[int, list[dict]]:
    snaps = addon_snapshots_map(db, catalog_product_ids)
    out: dict[int, list[dict]] = {}
    for pid, rows in snaps.items():
        priced = [r for r in rows if Decimal(str(r.get("selling_price") or "0")) > 0]
        if priced:
            out[int(pid)] = priced
    return out


def kept_addon_ids(addons_json) -> list[int] | None:
    """None means the line never stored a snapshot (move every linked add-on).
    A list is the exact set that stayed on the order, including an empty list."""
    if addons_json is None or not isinstance(addons_json, list):
        return None
    return [
        int(a["addon_product_id"])
        for a in addons_json
        if isinstance(a, dict) and a.get("addon_product_id")
    ]


def kept_addon_ids_for_customer_product(db: Session, customer_id: int, catalog_product_id: int) -> list[int] | None:
    from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement

    line = (
        db.query(CustomerOrderLine)
        .join(CustomerOrderPlacement, CustomerOrderPlacement.id == CustomerOrderLine.placement_id)
        .join(CustomerOrder, CustomerOrder.id == CustomerOrderPlacement.customer_order_id)
        .filter(
            CustomerOrder.customer_id == customer_id,
            CustomerOrderLine.catalog_product_id == catalog_product_id,
            CustomerOrderLine.addons_json.isnot(None),
            CustomerOrderPlacement.deleted_at.is_(None),
        )
        .order_by(CustomerOrderLine.id.desc())
        .first()
    )
    if line is None:
        return None
    return kept_addon_ids(line.addons_json)


def billing_addons_for_products(
    db: Session,
    customer_id: int,
    product_ids: list[int],
    placement_id: int | None = None,
) -> dict[int, list]:
    """Add-ons that stay on this bill. A removed Name Plate is absent from the order line."""
    live = addon_snapshots_map(db, product_ids)
    chosen: dict[int, list] = {}
    if placement_id and product_ids:
        from app.models.customer_order import CustomerOrderLine

        for ln in (
            db.query(CustomerOrderLine)
            .filter(
                CustomerOrderLine.placement_id == placement_id,
                CustomerOrderLine.catalog_product_id.in_(product_ids),
                CustomerOrderLine.addons_json.isnot(None),
            )
            .all()
        ):
            chosen[int(ln.catalog_product_id)] = list(ln.addons_json or [])
    if product_ids:
        from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement

        rows = (
            db.query(CustomerOrderLine)
            .join(CustomerOrderPlacement, CustomerOrderPlacement.id == CustomerOrderLine.placement_id)
            .join(CustomerOrder, CustomerOrder.id == CustomerOrderPlacement.customer_order_id)
            .filter(
                CustomerOrder.customer_id == customer_id,
                CustomerOrderLine.catalog_product_id.in_(product_ids),
                CustomerOrderLine.quantity > CustomerOrderLine.quantity_billed,
                CustomerOrderLine.addons_json.isnot(None),
                CustomerOrderPlacement.deleted_at.is_(None),
            )
            .order_by(CustomerOrderLine.id.desc())
            .all()
        )
        for ln in rows:
            cid = int(ln.catalog_product_id)
            if cid not in chosen:
                chosen[cid] = list(ln.addons_json or [])
    out: dict[int, list] = {}
    for pid in product_ids:
        out[int(pid)] = chosen.get(int(pid), live.get(int(pid)) or [])
    return out


def _row_sell_price(row: dict) -> Decimal:
    raw = row.get("selling_price")
    if raw is not None and str(raw).strip() != "":
        try:
            price = Decimal(str(raw))
            if price > 0:
                return price
        except Exception:
            pass
    if is_name_plate(row.get("our_product_id"), row.get("name")):
        return Decimal("2")
    if is_initial_plate(row.get("our_product_id"), row.get("name")):
        return Decimal("3")
    return Decimal("0")


def _charge_name(row: dict) -> str:
    if is_name_plate(row.get("our_product_id"), row.get("name")):
        return "Name Plate"
    if is_initial_plate(row.get("our_product_id"), row.get("name")):
        return "Initial Plate"
    return str(row.get("name") or row.get("our_product_id") or "Add-on").strip() or "Add-on"


def _auto_addon_charge(name: str | None) -> bool:
    return is_name_plate(name, None) or is_initial_plate(name, None)


def merge_priced_addon_charges(
    additional: list | None,
    addons_by_product: dict[int, list],
    bill_items: list[dict],
) -> list[dict]:
    """Priced add-ons are part of the bill total, each under its own name."""
    extra = [
        ac for ac in (additional or [])
        if isinstance(ac, dict) and not _auto_addon_charge(ac.get("name"))
    ]
    totals: dict[str, Decimal] = {}
    for item in bill_items:
        cid = int(item.get("catalog_product_id") or 0)
        qty = int(item.get("quantity") or 0)
        if qty <= 0:
            continue
        for addon in addons_by_product.get(cid) or []:
            if not isinstance(addon, dict):
                continue
            price = _row_sell_price(addon)
            if price <= 0:
                continue
            per = int(addon.get("quantity") or 1)
            label = _charge_name(addon)
            totals[label] = totals.get(label, Decimal("0")) + price * per * qty
    for label, total in totals.items():
        if total > 0:
            extra.append({"name": label, "amount": format(total.quantize(Decimal("0.01")), "f")})
    return extra
