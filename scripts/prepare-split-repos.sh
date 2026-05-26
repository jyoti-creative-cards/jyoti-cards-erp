#!/usr/bin/env bash
# Build two standalone git trees under _publish/ for separate GitHub repos:
#   _publish/jyoti-backend-repo/   — FastAPI (Railway root = repo root)
#   _publish/jyoti-frontend-repo/  — admin-app + customer-app (two Vercel projects)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
B="${ROOT}/_publish/jyoti-backend-repo"
F="${ROOT}/_publish/jyoti-frontend-repo"

rm -rf "$B" "$F"
mkdir -p "$B" "$F"

echo "== Backend export =="
rsync -a \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '.env' \
  --exclude 'dev.db' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  "${ROOT}/backend/" "$B/"

cat > "$B/README.md" <<'EOF'
# Jyoti ERP — API (FastAPI)

Deploy on **Railway** with **service root = this repository root** (contains `app/`, `requirements.txt`, `railway.toml`).

## Required env vars

See `.env.example`. Minimum: `DATABASE_URL`, `JWT_SECRET`, `ADMIN_API_KEY`, `CORS_ORIGINS` (comma-separated `https://` origins of both Next apps).

## Local

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill values
uvicorn app.main:app --reload --port 8002
```
EOF

if [[ ! -f "$B/.gitignore" ]]; then
  echo "missing backend .gitignore" >&2
  exit 1
fi

echo "== Frontend export =="
rsync -a \
  --exclude 'node_modules/' \
  --exclude '.next/' \
  --exclude '.env' \
  --exclude '.env.local' \
  --exclude '.DS_Store' \
  "${ROOT}/web/admin-app/" "${F}/admin-app/"
rsync -a \
  --exclude 'node_modules/' \
  --exclude '.next/' \
  --exclude '.env' \
  --exclude '.env.local' \
  --exclude '.DS_Store' \
  "${ROOT}/web/customer-app/" "${F}/customer-app/"

cat > "$F/README.md" <<'EOF'
# Jyoti ERP — Web (Next.js)

Two apps (deploy as **two Vercel projects** from this one repo):

| Vercel “Root directory” | App |
|-------------------------|-----|
| `admin-app` | ERP admin |
| `customer-app` | Customer shop |

Set **`BACKEND_URL`** and **`NEXT_PUBLIC_API_URL`** on each project to the same Railway API URL (no trailing slash).

Local dev:

```bash
cd admin-app && npm i && npm run dev    # port 3010
cd customer-app && npm i && npm run dev # port 3000
```
EOF

cat > "$F/.gitignore" <<'EOF'
node_modules/
.next/
.env
.env*.local
npm-debug.log*
*.tsbuildinfo
.DS_Store
EOF

echo "== git init backend =="
( cd "$B" && git init -b main && git add -A && git status )
( cd "$B" && git commit -m "Initial import: FastAPI backend (Jyoti ERP)" )

echo "== git init frontend =="
( cd "$F" && git init -b main && git add -A && git status )
( cd "$F" && git commit -m "Initial import: Next.js admin + customer apps (Jyoti ERP)" )

echo ""
echo "Done. Trees:"
echo "  $B"
echo "  $F"
