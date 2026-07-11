from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_auth_context


class StatsResponse(BaseModel):
    routes: int
    cities: int
    customers: int
    vendors: int
    catalog_products: int
    addons: int
    stock_on_hand: int = 0


router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=StatsResponse, dependencies=[Depends(get_auth_context)])
def get_stats(db: Session = Depends(get_db)) -> StatsResponse:
    # One round-trip instead of 7 sequential COUNT queries (each ~200–400ms to Supabase).
    row = db.execute(
        text(
            """
            SELECT
              (SELECT COUNT(*) FROM jc_routes WHERE is_active IS TRUE AND deleted_at IS NULL) AS routes,
              (SELECT COUNT(*) FROM jc_cities WHERE is_active IS TRUE AND deleted_at IS NULL) AS cities,
              (SELECT COUNT(*) FROM jc_customers WHERE is_active IS TRUE AND deleted_at IS NULL) AS customers,
              (SELECT COUNT(*) FROM jc_vendors WHERE is_active IS TRUE AND deleted_at IS NULL) AS vendors,
              (SELECT COUNT(*) FROM jc_catalog_products WHERE is_active IS TRUE AND deleted_at IS NULL) AS catalog_products,
              (SELECT COUNT(*) FROM jc_addon_products WHERE is_active IS TRUE AND deleted_at IS NULL) AS addons,
              (SELECT COALESCE(SUM(quantity_on_hand), 0) FROM jc_stock_balances) AS stock_on_hand
            """
        )
    ).one()
    return StatsResponse(
        routes=int(row.routes or 0),
        cities=int(row.cities or 0),
        customers=int(row.customers or 0),
        vendors=int(row.vendors or 0),
        catalog_products=int(row.catalog_products or 0),
        addons=int(row.addons or 0),
        stock_on_hand=int(row.stock_on_hand or 0),
    )
