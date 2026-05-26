#!/usr/bin/env python3
"""
Drop public-schema Postgres tables that are not used by current models.

KEEP list matches SQLAlchemy models in backend/app/models/.
Also preserves alembic_version if present.

Usage (from repo root or backend/):
  python3 scripts/prune_unused_tables.py

Requires DATABASE_URL in backend/.env
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Tables required by current FastAPI/SQLAlchemy models — do not drop.
KEEP = frozenset(
    {
        "portal_customers",
        "portal_vendors",
        "portal_catalog_products",
        "portal_catalog_category_labels",
        "portal_vendor_purchase_orders",
    }
)

SKIP_ALWAYS = frozenset({"alembic_version"})


def load_database_url() -> str:
    env_file = BACKEND_DIR / ".env"
    if not env_file.is_file():
        raise SystemExit(f"Missing {env_file}")
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("DATABASE_URL="):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            if v:
                return v
    raise SystemExit("DATABASE_URL= not found in .env")


def main() -> None:
    url = load_database_url()
    if "supabase" in url.lower() and "sslmode=" not in url.lower():
        url += "&sslmode=require" if "?" in url else "?sslmode=require"

    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
        ).fetchall()

    tables = [r[0] for r in rows]
    to_drop = [t for t in tables if t not in KEEP and t not in SKIP_ALWAYS]

    if not to_drop:
        print("Nothing to drop; only expected tables (or none extra).")
        print("Existing:", tables)
        return

    print("Will DROP CASCADE:", to_drop)
    for name in to_drop:
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))
        print("Dropped:", name)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
        ).fetchall()
    print("Remaining:", [r[0] for r in rows])


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Error:", e, file=sys.stderr)
        sys.exit(1)
