"""Sales analytics — same helpers as Streamlit insights."""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.db_import import load_dashboard_db

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/sales-revenue-series")
def sales_revenue_series(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    grain: str = Query("day"),
):
    db = load_dashboard_db()
    return db.sales_revenue_series(start[:10], end[:10], grain)


@router.get("/top-categories")
def top_categories(
    start: str = Query(...),
    end: str = Query(...),
    n: int = Query(12, ge=1, le=100),
):
    db = load_dashboard_db()
    return db.top_categories_by_revenue(start[:10], end[:10], n)


@router.get("/top-products")
def top_products(
    start: str = Query(...),
    end: str = Query(...),
    n: int = Query(12, ge=1, le=100),
):
    db = load_dashboard_db()
    return db.top_products_by_revenue(start[:10], end[:10], n)


@router.get("/customers-by-category")
def customers_category(
    category: str = Query(..., min_length=1),
    start: str = Query(...),
    end: str = Query(...),
):
    db = load_dashboard_db()
    return db.customers_who_bought_category(category.strip(), start[:10], end[:10])
