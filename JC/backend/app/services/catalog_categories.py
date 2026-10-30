"""Product categories. Names already on products, plus names saved before a product uses them."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.saved_category import SavedCategory


def list_category_names(db: Session) -> list[str]:
    rows = (
        db.query(CatalogProduct.category, CatalogProduct.second_category, CatalogProduct.category_3)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
        .all()
    )
    found: set[str] = set()
    for category, second, third in rows:
        for value in (category, second, third):
            text = (value or "").strip()
            if text:
                found.add(text)
    for (value,) in db.query(SavedCategory.value).all():
        text = (value or "").strip()
        if text:
            found.add(text)
    return sorted(found, key=str.lower)


def add_category_name(db: Session, raw: str) -> tuple[str, bool]:
    val = " ".join((raw or "").split())
    if not val:
        raise ValueError("Enter a category name")
    if len(val) > 120:
        raise ValueError("Category name is too long")
    for name in list_category_names(db):
        if name.lower() == val.lower():
            return name, False
    row = SavedCategory(value=val)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        for name in list_category_names(db):
            if name.lower() == val.lower():
                return name, False
        raise
    return val, True
