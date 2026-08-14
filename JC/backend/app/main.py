from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.db.session import init_db
from app.routers import addons, activity, auth, catalog, customers, lookups, recycle_bin, routes, staff, stats, stock, vendor_orders, vendors, debit_notes, accounts_payable, shop, customer_orders, customer_returns, bill_series, freight_agents, expenses, accounts_receivable, documents, finance, reports, dashboard, share, export, payment_modes

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
    # Yield immediately so Railway healthcheck passes while migrations run.
    # Blocking init_db() here made deploys fail and left old (slow) code live.
    import threading

    threading.Thread(target=init_db, daemon=True, name="jc-init-db").start()
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
app.include_router(customer_returns.router, prefix="/api/v1")
app.include_router(bill_series.router, prefix="/api/v1")
app.include_router(payment_modes.router, prefix="/api/v1")
app.include_router(freight_agents.router, prefix="/api/v1")
app.include_router(expenses.router, prefix="/api/v1")
app.include_router(accounts_receivable.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(finance.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(share.router, prefix="/api/v1")
app.include_router(export.router, prefix="/api/v1")


@app.get("/health")
def health() -> dict:
    from sqlalchemy import text

    from app.config import get_settings
    from app.db.session import engine, is_db_ready

    s = get_settings()
    db_ping = False
    db_err = None
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ping = True
    except Exception as e:
        db_err = str(e)[:200]
    ready = is_db_ready()
    # Liveness: DB reachable. Readiness (`db_ready`) may lag while migrations run —
    # Railway health must not wait on init_db or deploys flap.
    out = {
        "ok": db_ping,
        "db": "postgresql" if "postgresql" in s.database_url else "sqlite",
        "db_ping": db_ping,
        "db_ready": ready,
        "whatsapp_configured": bool(s.whatsapp_access_token and s.whatsapp_phone_number_id),
        "whatsapp_disabled": s.whatsapp_disable,
    }
    if db_err:
        out["db_error"] = db_err
    return out


@app.get("/api/v1/ping")
def ping() -> dict:
    return {"ok": True}


# Local admin UI (same process as API) — avoids flaky :3011 http.server
_ADMIN_DIR = Path(__file__).resolve().parents[2] / "web" / "admin"
if _ADMIN_DIR.is_dir():
    app.mount(
        "/admin",
        StaticFiles(directory=str(_ADMIN_DIR), html=True),
        name="admin_ui",
    )
