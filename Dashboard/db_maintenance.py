#!/usr/bin/env python3
"""Offline Postgres DDL: tables + migrations. Not run by Streamlit.

Usage::

  cd Dashboard && DATABASE_URL=... python3 db_maintenance.py

Or put ``DATABASE_URL`` in ``Dashboard/.env`` (local).
"""
from __future__ import annotations

import os
import sys

_D = os.path.dirname(os.path.abspath(__file__))
if _D not in sys.path:
    sys.path.insert(0, _D)

_ENV = os.path.join(_D, ".env")
try:
    from dotenv import load_dotenv

    load_dotenv(_ENV, override=False)
except ImportError:
    pass


def main() -> int:
    if not (os.environ.get("DATABASE_URL") or "").strip():
        print("Set DATABASE_URL first.", file=sys.stderr)
        return 2
    import db

    db.run_schema_maintenance()
    print("OK: schema maintenance finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
