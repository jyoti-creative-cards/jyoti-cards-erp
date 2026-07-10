# JC — Customer Management (Production Module)

Fresh customer management for Jyoti Creative Cards.

## Stack
- **Backend**: FastAPI + SQLAlchemy + **PostgreSQL** (Supabase)
- **Tables**: `jc_routes`, `jc_cities`, `jc_customers` (isolated from legacy `portal_*`)
- **Admin UI**: http://127.0.0.1:3011 (API key auth)
- **Customer Portal**: http://127.0.0.1:3012 (mobile + password)
- **API**: http://127.0.0.1:8003

## Quick Start
```bash
cd JC && chmod +x run-local.sh && ./run-local.sh
```

## Features
- Full CRUD: Routes, Cities, Customers (create/edit/delete)
- City → Route mapping (one city, one route; route has many cities)
- Customer wizard: 3-step flow with review + success screen
- Password = last 4 digits of phone
- WhatsApp via `account_creation_confirmation_3` template
- Admin can reset password / resend WhatsApp
- Customer portal login (no self-registration)

## API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/api/v1/routes` | List/create routes |
| GET/PATCH/DELETE | `/api/v1/routes/{id}` | Route CRUD |
| GET/POST | `/api/v1/cities` | List/create cities |
| GET/PATCH/DELETE | `/api/v1/cities/{id}` | City CRUD (route mapping) |
| GET/POST | `/api/v1/customers` | List/create customers |
| GET/PATCH/DELETE | `/api/v1/customers/{id}` | Customer CRUD |
| POST | `/api/v1/customers/{id}/reset-password` | Reset + WhatsApp |
| POST | `/api/v1/customers/{id}/resend-whatsapp` | Resend credentials |
| POST | `/api/v1/auth/login` | Customer login |
| GET | `/api/v1/auth/me` | Customer profile |
| GET | `/health` | Health check |

## WhatsApp Notes
- Template: `account_creation_confirmation_3` (Hindi, named params)
- Button URL is **static** in Meta — do NOT pass full portal URL as button param
- Set `CUSTOMER_PORTAL_URL_BUTTON_SUFFIX` only if template has dynamic `{{1}}` suffix
- Create response includes `whatsapp_sent` and `whatsapp_error` fields
