# Jyoti ERP — Streamlit (Dashboard + customer portal)

Monorepo layout:

| Path | Purpose |
|------|---------|
| `Dashboard/` | Main ERP: inventory, orders, billing, AR/AP, GL |
| `customer_ordering_app/` | Customer ordering portal (reads same DB logic via `dash_db.py`) |

**Database:** PostgreSQL only. Set **`DATABASE_URL`** (e.g. Supabase) in the environment or Streamlit secrets — both apps use the same URL.

Do **not** commit `.env`, tokens, or `Dashboard/uploads/` (gitignored).

## Run locally

```bash
export DATABASE_URL='postgresql://...'
cd Dashboard && python3 -m streamlit run app.py --server.port 8501
```

Portal (second terminal):

```bash
export DATABASE_URL='postgresql://...'
cd customer_ordering_app && python3 -m streamlit run app.py --server.port 8502
```

Install deps:

```bash
pip install -r requirements.txt
```

Optional: copy `Dashboard/.env` from `Dashboard/.env.example` and fill WhatsApp keys. Put **`DATABASE_URL`** in `.env` or export it in the shell.

## Deploy on Streamlit Community Cloud

1. Push this repo to GitHub.

2. **New app → From GitHub** → repo → branch `main`.

3. **Main file path:** `Dashboard/app.py`

4. **Python:** 3.11+ recommended.

5. **Secrets:** add **`DATABASE_URL`** (and any keys `Dashboard/whatsapp_meta.py` needs). Mirror variables from `.env.example` if you use WhatsApp/S3.

### Second app (customer portal)

Create **another** deployment from the **same repo** with main file:

`customer_ordering_app/app.py`

Set the **same** **`DATABASE_URL`** in secrets so ERP and portal share one database.

Both apps load `Dashboard/db.py` via `dash_db.py`; keep the repo layout as committed.

## Security

Never commit `.env`, personal tokens, or production database URLs in client-side code.
