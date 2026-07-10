from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_auth_context
from app.models.addon_product import AddonProduct
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.customer import Customer
from app.models.route import Route
from app.models.stock import StockBalance
from app.models.vendor import Vendor
from pydantic import BaseModel


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
    return StatsResponse(
        routes=db.query(func.count(Route.id)).filter(Route.is_active.is_(True)).scalar() or 0,
        cities=db.query(func.count(City.id)).filter(City.is_active.is_(True)).scalar() or 0,
        customers=db.query(func.count(Customer.id)).filter(Customer.is_active.is_(True)).scalar() or 0,
        vendors=db.query(func.count(Vendor.id)).filter(Vendor.is_active.is_(True)).scalar() or 0,
        catalog_products=db.query(func.count(CatalogProduct.id)).filter(CatalogProduct.is_active.is_(True)).scalar() or 0,
        addons=db.query(func.count(AddonProduct.id)).filter(AddonProduct.is_active.is_(True)).scalar() or 0,
        stock_on_hand=db.query(func.count(StockBalance.id)).filter(StockBalance.quantity_on_hand > 0).scalar() or 0,
    )
