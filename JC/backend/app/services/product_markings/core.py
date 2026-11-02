"""Staff markings on catalog products. Each one has a start and an end date."""
from __future__ import annotations

from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.product_marking import ProductMarking
from app.models.vendor import Vendor
from app.services.biz_date import today_ist

MARKING_MAX = 200
OPEN_END = date(2099, 12, 31)


def clean_marking(value: str | None) -> str | None:
    text = " ".join((value or "").split())
    if not text:
        return None
    if len(text) > MARKING_MAX:
        raise ValueError("marking is too long")
    return text


def _active_rows(db: Session, product_id: int, on: date | None = None) -> list[ProductMarking]:
    day = on or today_ist()
    return (
        db.query(ProductMarking)
        .filter(
            ProductMarking.catalog_product_id == product_id,
            ProductMarking.starts_on <= day,
            ProductMarking.ends_on >= day,
        )
        .order_by(ProductMarking.text.asc(), ProductMarking.id.asc())
        .all()
    )


def marking_labels(db: Session, product_ids: list[int]) -> dict[int, str | None]:
    """Products that have dated markings. The value is the text active today, or None."""
    ids = [int(pid) for pid in product_ids if pid]
    if not ids:
        return {}
    rows = (
        db.query(ProductMarking)
        .filter(ProductMarking.catalog_product_id.in_(ids))
        .all()
    )
    today = today_ist()
    grouped: dict[int, list[ProductMarking]] = {}
    for row in rows:
        grouped.setdefault(int(row.catalog_product_id), []).append(row)
    out = {}
    for pid, marks in grouped.items():
        names = []
        seen = set()
        for mark in marks:
            if mark.starts_on <= today <= mark.ends_on and mark.text.casefold() not in seen:
                seen.add(mark.text.casefold())
                names.append(mark.text)
        names.sort(key=str.casefold)
        out[pid] = ", ".join(names) or None
    return out


def display_marking(db: Session, product: CatalogProduct | None) -> str | None:
    if product is None:
        return None
    labels = marking_labels(db, [product.id])
    if product.id in labels:
        return labels[product.id]
    return product.marking or None


def active_marking_text(db: Session, product_id: int, on: date | None = None) -> str | None:
    names = []
    seen = set()
    for row in _active_rows(db, product_id, on):
        key = row.text.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(row.text)
    return ", ".join(names) or None


def refresh_product_marking(db: Session, product: CatalogProduct) -> None:
    product.marking = active_marking_text(db, product.id)


def _products(db: Session, product_ids: list[int]) -> list[CatalogProduct]:
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
    return rows


def _check_dates(starts_on: date, ends_on: date) -> None:
    if ends_on < starts_on:
        raise ValueError("the end date is before the start date")


def assign_marking(db: Session, product_ids: list[int], marking: str, starts_on: date, ends_on: date) -> int:
    cleaned = clean_marking(marking)
    if not cleaned:
        raise ValueError("type the marking")
    _check_dates(starts_on, ends_on)
    rows = _products(db, product_ids)
    for product in rows:
        db.add(ProductMarking(
            catalog_product_id=product.id,
            text=cleaned,
            starts_on=starts_on,
            ends_on=ends_on,
        ))
    db.flush()
    for product in rows:
        refresh_product_marking(db, product)
    return len(rows)


def update_marking(db: Session, marking_id: int, *, text: str, starts_on: date, ends_on: date) -> ProductMarking:
    row = db.get(ProductMarking, marking_id)
    if not row:
        raise ValueError("marking not found")
    cleaned = clean_marking(text)
    if not cleaned:
        raise ValueError("type the marking")
    _check_dates(starts_on, ends_on)
    row.text = cleaned
    row.starts_on = starts_on
    row.ends_on = ends_on
    db.flush()
    product = db.get(CatalogProduct, row.catalog_product_id)
    if product:
        refresh_product_marking(db, product)
    return row


def delete_marking(db: Session, marking_id: int) -> None:
    row = db.get(ProductMarking, marking_id)
    if not row:
        raise ValueError("marking not found")
    product_id = row.catalog_product_id
    db.delete(row)
    db.flush()
    product = db.get(CatalogProduct, product_id)
    if product:
        refresh_product_marking(db, product)


def list_assignments(db: Session, *, q: str | None = None) -> list[dict]:
    query = (
        db.query(ProductMarking, CatalogProduct, Vendor)
        .join(CatalogProduct, CatalogProduct.id == ProductMarking.catalog_product_id)
        .join(Vendor, Vendor.id == CatalogProduct.vendor_id)
        .filter(CatalogProduct.deleted_at.is_(None))
    )
    text = " ".join((q or "").split())
    if text:
        like = f"%{text}%"
        query = query.filter(or_(
            ProductMarking.text.ilike(like),
            CatalogProduct.our_product_id.ilike(like),
            CatalogProduct.vendor_product_id.ilike(like),
            Vendor.business_name.ilike(like),
        ))
    rows = query.order_by(ProductMarking.ends_on.desc(), CatalogProduct.our_product_id.asc()).limit(2000).all()
    today = today_ist()
    out = []
    for mark, product, vendor in rows:
        out.append({
            "id": mark.id,
            "product_id": product.id,
            "our_product_id": product.our_product_id,
            "vendor_name": vendor.business_name or "",
            "text": mark.text,
            "starts_on": mark.starts_on.isoformat(),
            "ends_on": mark.ends_on.isoformat(),
            "active": mark.starts_on <= today <= mark.ends_on,
        })
    return out


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
    rows = _products(db, product_ids)
    for product in rows:
        db.query(ProductMarking).filter(ProductMarking.catalog_product_id == product.id).delete()
        if cleaned:
            db.add(ProductMarking(
                catalog_product_id=product.id,
                text=cleaned,
                starts_on=today_ist(),
                ends_on=OPEN_END,
            ))
    db.flush()
    for product in rows:
        refresh_product_marking(db, product)
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
        db.query(ProductMarking)
        .filter(ProductMarking.text == source)
        .all()
    )
    product_ids = {row.catalog_product_id for row in rows}
    for row in rows:
        row.text = target
    db.flush()
    for product_id in product_ids:
        product = db.get(CatalogProduct, product_id)
        if product:
            refresh_product_marking(db, product)
    db.commit()
    return len(rows)
