from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.session import init_db
from app.routers import addons, activity, auth, catalog, customers, lookups, recycle_bin, routes, staff, stats, stock, vendor_orders, vendors, debit_notes, accounts_payable, shop, customer_orders, bill_series, freight_agents, expenses, accounts_receivable, documents, finance

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

_cors = (os.environ.get("CORS_ORIGINS") or "").strip()
if not _cors or _cors == "*":
    _allow_origins = ["*"]
    _allow_cred = False
else:
    _allow_origins = [x.strip() for x in _cors.split(",") if x.strip()]
    _allow_cred = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="JC Customer API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_cred,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(customers.router, prefix="/api/v1")
app.include_router(routes.router, prefix="/api/v1")
app.include_router(routes.city_router, prefix="/api/v1")
app.include_router(vendors.router, prefix="/api/v1")
app.include_router(lookups.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")
app.include_router(catalog.router, prefix="/api/v1")
app.include_router(addons.router, prefix="/api/v1")
app.include_router(recycle_bin.router, prefix="/api/v1")
app.include_router(staff.router, prefix="/api/v1")
app.include_router(activity.router, prefix="/api/v1")
app.include_router(vendor_orders.router, prefix="/api/v1")
app.include_router(stock.router, prefix="/api/v1")
app.include_router(debit_notes.router, prefix="/api/v1")
app.include_router(accounts_payable.router, prefix="/api/v1")
app.include_router(shop.router, prefix="/api/v1")
app.include_router(customer_orders.router, prefix="/api/v1")
app.include_router(bill_series.router, prefix="/api/v1")
app.include_router(freight_agents.router, prefix="/api/v1")
app.include_router(expenses.router, prefix="/api/v1")
app.include_router(accounts_receivable.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(finance.router, prefix="/api/v1")


@app.get("/health")
def health() -> dict:
    from app.config import get_settings
    s = get_settings()
    return {
        "ok": True,
        "db": "postgresql" if "postgresql" in s.database_url else "sqlite",
        "whatsapp_configured": bool(s.whatsapp_access_token and s.whatsapp_phone_number_id),
        "whatsapp_disabled": s.whatsapp_disable,
    }


@app.get("/api/v1/ping")
def ping() -> dict:
    return {"ok": True}
