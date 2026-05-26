"""FastAPI entry — wraps ``Dashboard/db.py`` + ``Dashboard/gl.py``."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db_import import load_dashboard_db
from app.routes.accounting import router as accounting_router
from app.routes import (
    analytics,
    billing,
    customer_orders,
    customers,
    dashboard,
    documents,
    inventory,
    integrations_pdf,
    integrations_whatsapp,
    purchase_orders,
    stock,
    vendor_products,
    vendors,
    warehouses,
)

# Import db once so startup fails fast if Dashboard/ missing
load_dashboard_db()

_origins = [o.strip() for o in (os.environ.get("CORS_ORIGINS") or "*").split(",") if o.strip()]

app = FastAPI(title="Jyoti ERP API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins if _origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(customers.router, prefix="/api/v1")
app.include_router(vendors.router, prefix="/api/v1")
app.include_router(vendor_products.router, prefix="/api/v1")
app.include_router(purchase_orders.router, prefix="/api/v1")
app.include_router(stock.router, prefix="/api/v1")
app.include_router(customer_orders.router, prefix="/api/v1")
app.include_router(inventory.router, prefix="/api/v1")
app.include_router(accounting_router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(warehouses.router, prefix="/api/v1")
app.include_router(integrations_whatsapp.router, prefix="/api/v1")
app.include_router(integrations_pdf.router, prefix="/api/v1")


@app.get("/")
def root():
    return {
        "service": "jyoti-erp-api",
        "health": "/api/health",
        "openapi": "/docs",
        "v1_prefix": "/api/v1",
        "whatsapp_status": "/api/v1/integrations/whatsapp/status",
    }


@app.get("/api/health")
def health():
    return {"ok": True}
