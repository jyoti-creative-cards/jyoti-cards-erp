#!/usr/bin/env bash
# Build clean publish folders for GitHub → Railway / Vercel.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/_publish"
rm -rf "$OUT"
mkdir -p "$OUT/jc-api" "$OUT/jc-admin"

# API (Railway)
rsync -a --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '.env' --exclude 'jc.db' --exclude '*.db' \
  --exclude '.DS_Store' \
  "$ROOT/backend/" "$OUT/jc-api/"

# Admin (Vercel static)
rsync -a --delete --exclude '.DS_Store' "$ROOT/web/admin/" "$OUT/jc-admin/"

# Seed git repos
for d in jc-api jc-admin; do
  (
    cd "$OUT/$d"
    git init -b main >/dev/null
    git add -A
    # Author must be a Vercel team member email or Hobby blocks the deploy.
    git -c user.email="sourabh18agrawal@gmail.com" -c user.name="Sourabh" commit -m "Publish JC $(date -u +%Y-%m-%dT%H:%MZ)" >/dev/null
  )
done

cat <<EOF
Prepared:
  $OUT/jc-api      → Railway (repo root)
  $OUT/jc-admin    → Vercel → https://jc-admin-two.vercel.app

Customer app is separate Vercel project (customer-app) → https://jyoticards.vercel.app

Next: set GitHub remotes under jyoti-creative-cards and push.
EOF
