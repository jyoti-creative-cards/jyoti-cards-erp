# Jyoti ERP — Next.js + FastAPI (Supabase unchanged)

```
Next.js (Vercel)  →  FastAPI (Railway)  →  Supabase Postgres + Storage
```

The API **reuses** `../Dashboard/db.py` (same business logic as Streamlit). Set **`DATABASE_URL`** (and optional WhatsApp/S3 env vars) on Railway like today.

## Layout

| Path | Purpose |
|------|---------|
| `api/` | FastAPI app (`app.main:app`) |
| `frontend/` | Next.js 15 App Router |

## API — local

```bash
cd web/api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set DATABASE_URL (same as Dashboard)
uvicorn app.main:app --reload --port 8000
```

`app/db_import` walks up until it finds `Dashboard/db.py` (must live in the same git repo).

## Frontend — local

```bash
cd web/frontend
cp .env.local.example .env.local
# NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
npm install
npm run dev
```

## Deploy

1. **Railway (FastAPI)**  
   - Use the **repository root** as the service root so `Dashboard/` is present (do **not** deploy only `web/api` alone).  
   - Install: `pip install -r web/api/requirements.txt`  
   - Start: `cd web/api && uvicorn app.main:app --host 0.0.0.0 --port $PORT`  
   - Env: `DATABASE_URL`, `CORS_ORIGINS=https://your-app.vercel.app` (comma-separated if several)

2. **Vercel (Next.js)**  
   - Root: `web/frontend`  
   - Env: `NEXT_PUBLIC_API_URL=https://<railway-host>`

3. **Supabase**  
   - Unchanged (Postgres + Storage).

## API routes (`/api/v1`)

| Area | Methods | Path |
|------|---------|------|
| Health | GET | `/api/health` |
| Dashboard | GET | `/dashboard/stats`, `/documents/stats` |
| Customers | GET, POST | `/customers` |
| Customers | GET, PATCH, DELETE | `/customers/{id}` |
| Vendors | GET, POST | `/vendors` |
| Vendors | GET, PATCH, DELETE | `/vendors/{id}` |
| Vendor products | GET, POST | `/vendor-products`, `/vendor-products?vendor_id=` |
| Vendor products | GET, PATCH, DELETE | `/vendor-products/{id}` |
| Purchase orders | GET, POST | `/purchase-orders`, `/purchase-orders/status-counts` |
| Purchase orders | GET, PATCH, DELETE | `/purchase-orders/{id}` |
| Stock receipts | GET, POST | `/stock-receipts` |
| Stock receipts | GET, PATCH, DELETE | `/stock-receipts/{id}` |
| Customer orders | GET | `/customer-orders`, `/customer-orders?customer_id=` |
| Customer orders | GET, POST | `/customer-orders`, `/customer-orders/{id}` |
| Customer orders | PATCH, DELETE | `/customer-orders/{id}` |
| Inventory | GET | `/inventory/aggregated`, `/inventory/catalog`, `/inventory/positions`, `/inventory/products/{id}/alternatives` |

### Accounting & analytics

| Area | Prefix |
|------|--------|
| GL (accounts, trial balance, journals, P&amp;L) | `/api/v1/accounting/gl/...` |
| AR / AP ledgers, balances, payments | `/api/v1/accounting/ar/...`, `/api/v1/accounting/ap/...` |
| Documents (PO, GRN, vendor bills, SO, deliveries, invoices, history) | `/api/v1/documents/...` |
| Billing rows (customer order bills, PO bills) | `/api/v1/billing/...` |
| Sales analytics (same as Streamlit insights helpers) | `/api/v1/analytics/...` |
| Warehouses | `/api/v1/warehouses` |

See `/docs` on the API for the full list. Remaining Streamlit-only flows (PDF generation, AI, upload widgets, **Operations** queue UI) still live in `Dashboard/app.py` until ported.

### Frontend navigation

Sidebar uses **in-app** routes (`/` … `/accounting/…`). Open **`http://localhost:3000`** after `npm run dev` — **not** a `file://` path. Set **`NEXT_PUBLIC_API_URL`** to your FastAPI origin (no `/api` suffix).

Add more routers under `api/app/routers/` calling `Dashboard/db.py` (and `Dashboard/gl.py` for GL).
