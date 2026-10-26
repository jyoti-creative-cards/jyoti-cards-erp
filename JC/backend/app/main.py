from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.db.session import init_db
from app.routers import addons, activity, auth, biz, catalog, customers, recycle_bin, routes, staff, stats, stock, stock_journals, vendor_orders, vendors, debit_notes, accounts_payable, shop, customer_orders, customer_returns, bill_series, freight_agents, commission_agents, expenses, accounts_receivable, documents, finance, reports, dashboard, share, export, payment_modes, whatsapp_inbox, items_lookup, runtime_settings
from app.services.observability import setup_observability

# Real format (with request-id correlation) is installed by setup_observability()
# below, once the app object exists.

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

setup_observability(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_cred,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def block_item_lookup_account(request, call_next):
    """The item-lookup staff account can call only its search."""
    path = request.url.path
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer ") and not path.startswith("/api/v1/items/lookup"):
        token = header.split(" ", 1)[1].strip()
        try:
            from app.db.session import SessionLocal
            from app.models.staff import Staff
            from app.services.permissions import parse_permissions
            from app.services.tokens import decode_access_token, token_staff_id

            payload = decode_access_token(token)
            if payload.get("type") == "staff":
                db = SessionLocal()
                try:
                    row = db.get(Staff, token_staff_id(payload))
                    perms = parse_permissions(row.permissions_json) if row and row.is_active else set()
                finally:
                    db.close()
                if perms == {"items.lookup"}:
                    from starlette.responses import JSONResponse
                    return JSONResponse({"detail": "permission denied"}, status_code=403)
                if perms == {"stickers.print"} and not _sticker_allowed(request.method, path):
                    from starlette.responses import JSONResponse
                    return JSONResponse({"detail": "permission denied"}, status_code=403)
                order_only = {"customers.read", "customer_orders.read", "customer_orders.write", "stock.read"}
                if perms and "customer_orders.write" in perms and perms <= order_only:
                    if not _order_taker_allowed(request.method, path):
                        from starlette.responses import JSONResponse
                        return JSONResponse({"detail": "permission denied"}, status_code=403)
        except Exception:
            pass
    return await call_next(request)


def _sticker_allowed(method: str, path: str) -> bool:
    """Search a party number, print its sticker, and see the prints already given."""
    if path.startswith("/api/v1/auth"):
        return True
    if method == "GET" and path in ("/api/v1/customers/sticker-search", "/api/v1/customers/sticker-prints"):
        return True
    if method == "GET" and path.startswith("/api/v1/customers/") and path.endswith("/sticker"):
        return True
    if method == "POST" and path.startswith("/api/v1/customers/") and path.endswith("/sticker-prints"):
        return True
    return False


def _order_taker_allowed(method: str, path: str) -> bool:
    """Book a customer order. Search the customer and the item. Nothing else."""
    if path.startswith("/api/v1/auth"):
        return True
    if method == "GET" and path.startswith("/api/v1/customers"):
        return True
    if method == "GET" and path.startswith("/api/v1/stock/entry-items"):
        return True
    if method == "GET" and path.startswith("/api/v1/customer-orders/customer/"):
        return "/bills/" not in path and "/process" not in path
    if method == "POST" and path.startswith("/api/v1/customer-orders/customer/"):
        return path.endswith("/offline") or path.endswith("/offline/preview")
    return False

app.include_router(auth.router, prefix="/api/v1")
app.include_router(customers.router, prefix="/api/v1")
app.include_router(routes.router, prefix="/api/v1")
app.include_router(routes.city_router, prefix="/api/v1")
app.include_router(vendors.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")
app.include_router(catalog.router, prefix="/api/v1")
app.include_router(addons.router, prefix="/api/v1")
app.include_router(recycle_bin.router, prefix="/api/v1")
app.include_router(staff.router, prefix="/api/v1")
app.include_router(activity.router, prefix="/api/v1")
app.include_router(vendor_orders.router, prefix="/api/v1")
app.include_router(stock.router, prefix="/api/v1")
app.include_router(stock_journals.router, prefix="/api/v1")
app.include_router(debit_notes.router, prefix="/api/v1")
app.include_router(accounts_payable.router, prefix="/api/v1")
app.include_router(shop.router, prefix="/api/v1")
app.include_router(customer_orders.router, prefix="/api/v1")
app.include_router(customer_returns.router, prefix="/api/v1")
app.include_router(bill_series.router, prefix="/api/v1")
app.include_router(payment_modes.router, prefix="/api/v1")
app.include_router(freight_agents.router, prefix="/api/v1")
app.include_router(commission_agents.router, prefix="/api/v1")
app.include_router(expenses.router, prefix="/api/v1")
app.include_router(accounts_receivable.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(finance.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(biz.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(share.router, prefix="/api/v1")
app.include_router(export.router, prefix="/api/v1")
app.include_router(whatsapp_inbox.router, prefix="/api/v1")
app.include_router(items_lookup.router, prefix="/api/v1")
app.include_router(runtime_settings.router, prefix="/api/v1")

_books = Path(__file__).resolve().parent / "static" / "biz"
if _books.is_dir():
    app.mount("/books", StaticFiles(directory=_books, html=True), name="books")


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
