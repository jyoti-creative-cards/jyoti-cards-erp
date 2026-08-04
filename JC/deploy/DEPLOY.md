# JC production deploy

## Live URLs (only these)

| App | URL |
|---|---|
| Admin tool | https://jc-admin-two.vercel.app |
| Customer order app | https://jyoticards.vercel.app |
| API | https://jc-api-production.up.railway.app |

Do not create or share other public Vercel aliases for JC.

## Repos (org: `jyoti-creative-cards`)

| Local folder | GitHub / Vercel / Railway | Host |
|---|---|---|
| `_publish/jc-api` | `jc-api` | Railway |
| `_publish/jc-admin` | `jc-admin` | Vercel → `jc-admin-two.vercel.app` |
| `web/customer-app` | `customer-app` | Vercel → `jyoticards.vercel.app` |

```bash
cd JC && chmod +x scripts/prepare-publish.sh && ./scripts/prepare-publish.sh
```

## Railway (`jc-api`)

Env from `backend/.env` (never commit `.env`):

- `DATABASE_URL`
- `JWT_SECRET`
- `ADMIN_API_KEY`
- `CORS_ORIGINS=https://jc-admin-two.vercel.app,https://jyoticards.vercel.app`
- `CUSTOMER_PORTAL_URL=https://jyoticards.vercel.app`
- `WHATSAPP_STAFF_NOTIFY_PHONES=` comma-separated staff mobiles for new-order alerts
- WhatsApp / S3 vars as needed

**One customer app only:** `web/customer-app` → `jyoticards.vercel.app`. Legacy `JC/web/portal` removed.

Health: `GET /health`

## Vercel

- **jc-admin**: static admin. Browser calls same-origin `/api/v1/*` → rewrites to Railway.
- **customer-app**: Next.js shop. Production alias must stay `jyoticards.vercel.app`.

After each `customer-app` production deploy, confirm:

```bash
vercel alias ls --scope sourabh18agrawal-8975s-projects | grep jyoticards
```

If the alias drifted, re-point it:

```bash
vercel alias set <latest-customer-deployment> jyoticards.vercel.app --scope sourabh18agrawal-8975s-projects
```
