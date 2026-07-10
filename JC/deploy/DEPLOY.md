# JC production deploy

## Repos (org: `jyoti-creative-cards`)

| Local folder | GitHub repo | Host |
|---|---|---|
| `_publish/jc-api` | `jc-api` | Railway |
| `_publish/jc-admin` | `jc-admin` | Vercel |
| `_publish/jc-portal` | `jc-portal` | Vercel |

```bash
cd JC && chmod +x scripts/prepare-publish.sh && ./scripts/prepare-publish.sh
```

## Railway (`jc-api`)

Env from `backend/.env` (never commit `.env`):

- `DATABASE_URL`
- `JWT_SECRET`
- `ADMIN_API_KEY`
- `CORS_ORIGINS` (admin + portal Vercel URLs)
- WhatsApp / S3 vars as needed

Health: `GET /health`

After Railway URL is known, update both `vercel.json` rewrite destinations, then redeploy Vercel.

## Vercel (`jc-admin`, `jc-portal`)

Static sites. Browser calls same-origin `/api/v1/*` which rewrites to Railway.
