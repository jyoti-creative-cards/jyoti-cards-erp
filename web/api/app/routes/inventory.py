from __future__ import annotations

from typing import Optional

from fastapi import APIRouter

from app.db_import import load_dashboard_db

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/aggregated")
def inventory_aggregated():
    db = load_dashboard_db()
    return db.list_inventory_aggregated()


@router.get("/catalog")
def catalog_stock(search: Optional[str] = None, vendor_id: Optional[int] = None):
    db = load_dashboard_db()
    return db.list_catalog_stock_rows(name_sub=search or "", vendor_id=vendor_id)


@router.get("/positions")
def stock_positions():
    db = load_dashboard_db()
    return db.list_stock_positions_v2()


@router.get("/products/{product_id}/alternatives")
def product_alternatives(product_id: int):
    db = load_dashboard_db()
    return {"product_ids": db.list_product_alternative_ids(product_id)}
