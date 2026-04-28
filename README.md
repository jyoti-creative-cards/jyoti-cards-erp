# Jyoti ERP — Streamlit (Dashboard + customer portal)

Monorepo layout:

| Path | Purpose |
|------|---------|
| `Dashboard/` | Main ERP: inventory, orders, billing, AR/AP, GL |
| `customer_ordering_app/` | Customer ordering portal (reads same DB logic via `dash_db.py`) |

Database: SQLite `Dashboard/business.db` (created on first run). **Do not commit** the live DB or `Dashboard/uploads/` — both are gitignored.

## Run locally

```bash
cd Dashboard && python3 -m streamlit run app.py --server.port 8501
```

Portal (second terminal):

```bash
cd customer_ordering_app && python3 -m streamlit run app.py --server.port 8502
```

Install deps:

```bash
pip install -r requirements.txt
```

Optional: copy `Dashboard/.env` from `Dashboard/.env.example` and fill WhatsApp keys.

## Deploy on Streamlit Community Cloud

1. Push this repo to GitHub (**create a new empty repo** — do not overwrite the unrelated [stock Excel app](https://github.com/jyoti-creative-cards/jyoti-cards-stock-management-streamlit-app) unless you intend to replace it).

2. **New app → From GitHub** → pick repo → branch `main`.

3. **Main file path:** `Dashboard/app.py`

4. **Python:** 3.11+ recommended.

5. **Secrets** (app sidebar shows `DB` path): add any keys your `Dashboard/whatsapp_meta.py` expects under `[secrets]` — mirror variables from `.env.example` if you use WhatsApp.

6. **Persistent SQLite:** Community Cloud filesystem is ephemeral unless you attach storage — for production data you typically attach a **persistent volume** or later migrate to hosted Postgres. For demos, `init_db()` creates a fresh DB each redeploy unless you upload a seed DB via other means.

### Second app (customer portal)

Create **another** Streamlit Cloud deployment from the **same repo** with main file:

`customer_ordering_app/app.py`

Both apps resolve `Dashboard/db.py` via paths inside `dash_db.py`; repository layout must stay as committed.

### Customer portal login vs ERP (important)

Locally, ERP and portal both use **`Dashboard/business.db`** on disk — customers you add in the ERP appear in the portal.

On **Streamlit Community Cloud**, each deployed app has its **own isolated filesystem**. The ERP app’s SQLite file is **not** the same file as the portal app’s. So customers created in the hosted ERP **will not exist** in the hosted portal’s database — login fails even with the correct password.

**What to do:**

| Situation | Approach |
|-----------|----------|
| Local dev | Run both apps from this repo; they share `Dashboard/business.db`. |
| Two Cloud apps | Use a **hosted database** both apps connect to (Postgres, Turso/libSQL, etc.) and point them at it — SQLite-on-disk alone cannot be shared across two Cloud runners. |
| Single Cloud app only | Add customer-facing UI as another Streamlit **page** under `Dashboard/pages/` (same process → one DB) — optional future layout. |

Optional secrets (applied **before** `db.py` loads): `DASHBOARD_E2E_DB` or `BUSINESS_DB_PATH` — absolute path to a SQLite file **when** that path is visible to the app (e.g. attached volume or local dev). Same key should be set in **both** apps if they ever share a mounted volume.

## Security

Never commit `.env`, personal tokens, or production `business.db`.
