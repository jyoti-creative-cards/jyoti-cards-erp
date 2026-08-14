from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context
from app.services import response_cache
from app.services.dashboard import build_dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    cache_key = f"dashboard:{'admin' if auth.is_admin else auth.actor_id}"
    cached = response_cache.get(cache_key)
    if cached is not None:
        return cached

    data = build_dashboard(db)
    # Staff: filter action cards by permission
    if not auth.is_admin:
        allowed = set()
        if auth.has("customer_orders.read") or auth.has("customer_orders.write"):
            allowed.add("customer_orders")
        if auth.has("vendor_orders.read") or auth.has("vendor_orders.write"):
            allowed.add("vendor_orders")
        if auth.has("returns.read") or auth.has("returns.write"):
            allowed.add("returns")
        data["actions"] = [
            a for a in data["actions"]
            if a["id"] in allowed or (a["id"] == "low_stock" and (auth.has("catalog.read") or auth.has("catalog.write")))
        ]
        if not auth.has("catalog.read") and not auth.has("catalog.write") and not auth.has("addons.read"):
            data["actions"] = [a for a in data["actions"] if a["id"] != "low_stock"]
        data["pulse"] = None
        data["top_collect"] = []
        data["top_pay"] = []
        data["action_total"] = sum(1 for a in data["actions"] if a["count"] > 0)

    response_cache.set(cache_key, data, ttl_seconds=15.0)
    return data
