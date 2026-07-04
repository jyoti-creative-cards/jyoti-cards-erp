"""Dashboard summary endpoint — cached, fast."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.customer_order import CustomerOrder
from app.models.vendor_order import VendorOrder
from app.services.cache import cache_get, cache_set

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_CACHE_KEY = "dashboard:summary"
_CACHE_TTL = 30  # seconds


@router.get("/summary", dependencies=[Depends(require_admin)])
def dashboard_summary(db: Session = Depends(get_db)) -> dict:
    """Returns open order counts + pending values, cached for 30s."""
    hit = cache_get(_CACHE_KEY)
    if hit is not None:
        return hit

    open_customer = db.query(func.count(CustomerOrder.id)).filter(
        CustomerOrder.status.in_(["received", "billed"]),
        CustomerOrder.deleted_at.is_(None),
    ).scalar() or 0

    pending_value = db.query(func.sum(CustomerOrder.total_amount)).filter(
        CustomerOrder.status.in_(["received", "billed"]),
        CustomerOrder.deleted_at.is_(None),
    ).scalar() or 0

    open_vendor = db.query(func.count(VendorOrder.id)).filter(
        VendorOrder.status == "open"
    ).scalar() or 0

    result = {
        "open_customer_orders": open_customer,
        "pending_customer_value": float(pending_value),
        "open_vendor_orders": open_vendor,
    }
    cache_set(_CACHE_KEY, result, _CACHE_TTL)
    return result
