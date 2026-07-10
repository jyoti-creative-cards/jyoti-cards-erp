#!/usr/bin/env bash
# Build clean publish folders for GitHub → Railway / Vercel.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/_publish"
rm -rf "$OUT"
mkdir -p "$OUT/jc-api" "$OUT/jc-admin" "$OUT/jc-portal"

# API (Railway)
rsync -a --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '.env' --exclude 'jc.db' --exclude '*.db' \
  --exclude '.DS_Store' \
  "$ROOT/backend/" "$OUT/jc-api/"

# Admin (Vercel static)
rsync -a --delete --exclude '.DS_Store' "$ROOT/web/admin/" "$OUT/jc-admin/"

# Portal (Vercel static)
rsync -a --delete --exclude '.DS_Store' "$ROOT/web/portal/" "$OUT/jc-portal/"

# Seed git repos
for d in jc-api jc-admin jc-portal; do
  (
    cd "$OUT/$d"
    git init -b main >/dev/null
    git add -A
    git -c user.email="deploy@jyoticreativecards.local" -c user.name="JC Deploy" commit -m "Initial JC deploy" >/dev/null
  )
done

cat <<EOF
Prepared:
  $OUT/jc-api      → Railway (repo root)
  $OUT/jc-admin    → Vercel (static + /api rewrite)
  $OUT/jc-portal   → Vercel (static + /api rewrite)

Next: set GitHub remotes under jyoti-creative-cards and push.
EOF
