"""Staff markings on catalog products. Search, set, and rename them."""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.vendor import Vendor

MARKING_MAX = 200


def clean_marking(value: str | None) -> str | None:
    text = " ".join((value or "").split())
    if not text:
        return None
    if len(text) > MARKING_MAX:
        raise ValueError("marking is too long")
    return text


def list_product_markings(db: Session, *, q: str | None, marked: str) -> dict:
    query = (
        db.query(CatalogProduct, Vendor)
        .join(Vendor, Vendor.id == CatalogProduct.vendor_id)
        .filter(CatalogProduct.deleted_at.is_(None), CatalogProduct.is_active.is_(True))
    )
    scope = (marked or "all").strip().lower()
    if scope == "marked":
        query = query.filter(CatalogProduct.marking.isnot(None), CatalogProduct.marking != "")
    elif scope == "unmarked":
        query = query.filter(or_(CatalogProduct.marking.is_(None), CatalogProduct.marking == ""))
    text = " ".join((q or "").split())
    if text:
        like = f"%{text}%"
        query = query.filter(or_(
            CatalogProduct.our_product_id.ilike(like),
            CatalogProduct.vendor_product_id.ilike(like),
            CatalogProduct.marking.ilike(like),
            CatalogProduct.category.ilike(like),
            CatalogProduct.second_category.ilike(like),
            CatalogProduct.category_3.ilike(like),
            Vendor.business_name.ilike(like),
            Vendor.alias.ilike(like),
        ))
    rows = query.order_by(CatalogProduct.our_product_id.asc(), CatalogProduct.id.asc()).limit(2000).all()
    names = (
        db.query(CatalogProduct.marking)
        .filter(
            CatalogProduct.deleted_at.is_(None),
            CatalogProduct.is_active.is_(True),
            CatalogProduct.marking.isnot(None),
            CatalogProduct.marking != "",
        )
        .distinct()
        .all()
    )
    markings = sorted({(name or "").strip() for (name,) in names if (name or "").strip()}, key=str.casefold)
    items = []
    for product, vendor in rows:
        items.append({
            "id": product.id,
            "our_product_id": product.our_product_id,
            "vendor_product_id": product.vendor_product_id or "",
            "vendor_name": vendor.business_name or "",
            "vendor_alias": vendor.alias or "",
            "category": product.category or "",
            "second_category": product.second_category or "",
            "category_3": product.category_3 or "",
            "year_group": product.year_group or "",
            "marking": product.marking or "",
        })
    return {"items": items, "markings": markings, "shown": len(items)}


def apply_marking(db: Session, product_ids: list[int], marking: str | None) -> int:
    cleaned = clean_marking(marking)
    ids = sorted({int(pid) for pid in product_ids})
    if not ids:
        raise ValueError("pick at least one product")
    rows = (
        db.query(CatalogProduct)
        .filter(CatalogProduct.id.in_(ids), CatalogProduct.deleted_at.is_(None), CatalogProduct.is_active.is_(True))
        .all()
    )
    if len(rows) != len(ids):
        raise ValueError("one of those products was not found")
    for row in rows:
        row.marking = cleaned
    db.commit()
    return len(rows)


def rename_marking(db: Session, old: str, new: str) -> int:
    source = clean_marking(old)
    target = clean_marking(new)
    if not source:
        raise ValueError("pick the marking to rename")
    if not target:
        raise ValueError("type the new marking")
    if source == target:
        return 0
    rows = (
        db.query(CatalogProduct)
        .filter(
            CatalogProduct.deleted_at.is_(None),
            CatalogProduct.is_active.is_(True),
            CatalogProduct.marking == source,
        )
        .all()
    )
    for row in rows:
        row.marking = target
    db.commit()
    return len(rows)
