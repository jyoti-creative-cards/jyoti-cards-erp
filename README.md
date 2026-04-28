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

## Security

Never commit `.env`, personal tokens, or production `business.db`.
