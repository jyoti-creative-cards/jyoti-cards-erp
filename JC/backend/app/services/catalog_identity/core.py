"""Helpers for catalog SKU uniqueness scoped by year_group."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct


def normalize_year_group(year_group: Optional[str]) -> str:
    return (year_group or "").strip()


def year_key(year_group: Optional[str]) -> str:
    return normalize_year_group(year_group)


def sku_year_label(our_product_id: str, year_group: Optional[str]) -> str:
    yg = year_key(year_group)
    return f"{our_product_id}|{yg}" if yg else our_product_id


def find_active_sku_year(
    db: Session,
    our_product_id: str,
    year_group: Optional[str],
    *,
    exclude_id: Optional[int] = None,
) -> Optional[CatalogProduct]:
    sku = (our_product_id or "").strip()
    if not sku:
        return None
    yg = year_key(year_group)
    q = db.query(CatalogProduct).filter(
        func.lower(CatalogProduct.our_product_id) == sku.lower(),
        CatalogProduct.is_active.is_(True),
        CatalogProduct.deleted_at.is_(None),
        func.coalesce(CatalogProduct.year_group, "") == yg,
    )
    if exclude_id is not None:
        q = q.filter(CatalogProduct.id != exclude_id)
    return q.first()
