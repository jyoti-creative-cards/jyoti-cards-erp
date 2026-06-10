from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.session import init_db
from app.routers import (
    accounting,
    addons,
    audit,
    auth,
    bank,
    bill_series,
    catalog,
    catalog_alternatives,
    credit_notes,
    customer_bills,
    customer_orders,
    customers,
    expenses,
    fiscal_years,
    freight_vendors,
    inventory,
    notes,
    product_prices,
    purchase_orders,
    reports,
    routes,
    shop,
    staff,
    vendor_bills,
    vendor_orders,
    vendors,
)

# UI is served separately (e.g. python -m http.server on port 8080).
_cors = (os.environ.get("CORS_ORIGINS") or "").strip()
if not _cors or _cors == "*":
    _allow_origins = ["*"]
    _allow_cred = False
else:
    _allow_origins = [x.strip() for x in _cors.split(",") if x.strip()]
    _allow_cred = True

app = FastAPI(title="Customer backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_cred,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(customers.router, prefix="/api/v1")
app.include_router(vendors.router, prefix="/api/v1")
app.include_router(catalog.router, prefix="/api/v1")
app.include_router(catalog_alternatives.router, prefix="/api/v1")
app.include_router(purchase_orders.router, prefix="/api/v1")
app.include_router(inventory.router, prefix="/api/v1")
app.include_router(shop.router, prefix="/api/v1")
app.include_router(customer_orders.shop_order_router, prefix="/api/v1")
app.include_router(customer_orders.admin_customer_order_router, prefix="/api/v1")
app.include_router(vendor_bills.router, prefix="/api/v1")
app.include_router(customer_bills.router, prefix="/api/v1")
app.include_router(accounting.router, prefix="/api/v1")
app.include_router(notes.router, prefix="/api/v1")
app.include_router(fiscal_years.router, prefix="/api/v1")
app.include_router(bank.router, prefix="/api/v1")
app.include_router(expenses.router, prefix="/api/v1")
app.include_router(routes.router, prefix="/api/v1")
app.include_router(routes.city_router, prefix="/api/v1")
app.include_router(product_prices.router, prefix="/api/v1")
app.include_router(addons.router, prefix="/api/v1")
app.include_router(freight_vendors.router, prefix="/api/v1")
app.include_router(bill_series.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(credit_notes.router, prefix="/api/v1")
app.include_router(staff.router, prefix="/api/v1")
app.include_router(vendor_orders.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")


@app.on_event("startup")
def startup() -> None:
    from app.db.session import engine

    u = engine.url
    # Help debug “portal empty but admin has rows” (wrong DATABASE_URL vs UI).
    if u.drivername.startswith("sqlite"):
        loc = u.database or ""
        print(f"[backend] database=sqlite ({loc})")
    else:
        host = u.host or ""
        dbn = u.database or ""
        print(f"[backend] database={u.drivername} host={host} db={dbn}")
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "api": "v1", "ui_hint": "serve backend/ui on another port (e.g. 8080)"}
