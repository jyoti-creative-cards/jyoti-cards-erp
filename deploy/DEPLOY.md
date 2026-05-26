# Deploy backend + customer portal + ERP admin

Use **Supabase** only for Postgres (and optional Storage/S3). This FastAPI app reads **`DATABASE_URL`**; it does not use the Supabase JS client.

## What I need from you to deploy

1. **GitHub**: repo pushed to GitHub (Railway/Vercel import from Git).
2. **Supabase**: Postgres connection URI → becomes **`DATABASE_URL`** on Railway (and in `backend/.env` locally). Password must be URL-encoded if it has `@#:` etc.
3. **Secrets** (generate random strings; store in Railway variables, not in chat):
   - **`JWT_SECRET`**
   - **`ADMIN_API_KEY`** (you paste this into the admin Next app header field, or session storage picks it up after first entry — same value Railway uses for `X-Admin-Key`).
4. **Accounts**: log in once in a terminal so CLIs work:
   - `railway login`
   - `vercel login` (or use Vercel dashboard only).
5. **After first deploy**: Railway gives **`https://…up.railway.app`**. Put that exact origin (no trailing slash) into **both** Vercel projects as **`BACKEND_URL`** and **`NEXT_PUBLIC_API_URL`**. Then set **`CORS_ORIGINS`** on Railway to your two Vercel **`https://…vercel.app`** URLs, comma-separated, and restart/redeploy the API.

Optional: **`WHATSAPP_*`**, **`S3_*`** when you are ready (see `backend/.env.example`).

## 0. Supabase (database)

1. Create a project → **Settings → Database**.
2. Copy **URI** (direct `db.<project>.supabase.co:5432` is fine for Railway; use the **pooler** URI if you hit connection limits).
3. Put it in `backend/.env` as `DATABASE_URL=postgresql://...` (password URL-encoded if it has special characters).
4. Local check against that DB (from repo root):

```bash
chmod +x scripts/verify-cloud-db.sh   # once
./scripts/verify-cloud-db.sh
```

If this times out from your laptop, fix network/VPN/firewall or try the **pooler** host/port from Supabase. The app appends `sslmode=require` and `connect_timeout=15` for Supabase hosts when missing.

---

After you connect Railway + Vercel, you get URLs like:

| Service | Example URL |
|--------|----------------|
| API | `https://<your-service>.up.railway.app` |
| Customer portal | `https://<customer-project>.vercel.app` |
| ERP admin | `https://<admin-project>.vercel.app` |

## 1. Railway — FastAPI (`backend/`)

1. Install CLI (optional): [Railway CLI](https://docs.railway.com/develop/cli). Or use the web dashboard only.
2. New project → **Deploy from GitHub** → set **root directory** to **`backend`** (matches `backend/railway.toml`).
3. **Variables** (same values as a good `backend/.env`, without quotes issues):

| Variable | Example / notes |
|----------|------------------|
| `DATABASE_URL` | Supabase Postgres URI (same as local prod `.env`). |
| `JWT_SECRET` | Long random string. |
| `ADMIN_API_KEY` | Long random string; admin UI sends `X-Admin-Key`. |
| `CORS_ORIGINS` | Comma-separated **https** origins: customer + admin Vercel URLs, no trailing slashes. |
| `WHATSAPP_DISABLE` | `1` until Meta templates are verified. |
| `S3_*` | Optional; only if you use catalog uploads / receipt files. |

4. Railway sets **`PORT`**; `railway.toml` already runs `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Healthcheck: **`GET /api/health`**.
5. Copy the service **public HTTPS URL** → that is **`BACKEND_URL`** for both Next apps.

**CLI sketch** (after `railway login` and linking the repo):

```bash
cd backend
railway link
railway variables set DATABASE_URL="postgresql://..." JWT_SECRET="..." ADMIN_API_KEY="..." CORS_ORIGINS="https://....vercel.app,https://....vercel.app"
railway up
```

## 2. Vercel — customer app

1. [Vercel CLI](https://vercel.com/docs/cli) (optional): `npm i -g vercel`, then `cd web/customer-app && vercel` and follow prompts; production: `vercel --prod`.
2. Or dashboard: **Add New → Project** → import Git repo → **Root Directory** `web/customer-app`.
3. **Environment variables** (Production + Preview if you use previews):  
   - `BACKEND_URL` = Railway API URL (no trailing slash)  
   - `NEXT_PUBLIC_API_URL` = same as `BACKEND_URL`

Browser calls `/api/proxy/*`; Next rewrites to `BACKEND_URL`.

4. After both Vercel URLs exist, go back to Railway and set **`CORS_ORIGINS`** to those two `https://…` origins (comma-separated), then redeploy or restart the service.

## 3. Vercel — ERP admin

1. Second project (or `cd web/admin-app && vercel`), root **`web/admin-app`**.
2. Same **`BACKEND_URL`** / **`NEXT_PUBLIC_API_URL`** as the customer app (same Railway API).

## Local verification

Run from repo root:

```bash
./scripts/verify-all.sh
```

Runs `backend/scripts/verify_api.py` (read paths + shop auth), then `backend/scripts/e2e_api.py` (vendor, catalog, stock, customer shop order, admin order status, PO, full GRN, adjustment). Sets `WHATSAPP_DISABLE=1` inside E2E to skip Meta sends.

Optional full UI + browser check (Chromium, starts local API + both Next apps on 8002 / 3000 / 3010, uses **sqlite** `backend/dev.db` — not your cloud `DATABASE_URL` from `.env` unless you set `E2E_UI_DATABASE_URL`):

```bash
./scripts/e2e-ui.sh
```

Playwright covers: all **admin-app** sidebar screens (with `X-Admin-Key`), **customer-app** login + three portal tabs, and **OpenAPI** path smoke for `backend/`.

`web/frontend` is a separate Next app (defaults to **`web/api`** on port 8000 via `API_PROXY_TARGET`). It is not part of `e2e-ui.sh`; exercise it manually or add another Playwright project pointed at that stack.
