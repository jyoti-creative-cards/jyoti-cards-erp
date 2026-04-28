#!/usr/bin/env python3
"""Payal seed flow against Postgres. See ``seed_payal_live.py`` for manual seeding.

Requires ``DATABASE_URL``.

Run::

  cd Dashboard && WHATSAPP_DISABLE=1 DATABASE_URL=... python3 e2e_payal_complete_flow.py
"""
from __future__ import annotations

import os
import sys

if not os.environ.get("DATABASE_URL", "").strip():
    print("Set DATABASE_URL (PostgreSQL).", file=sys.stderr)
    raise SystemExit(2)

if os.environ.get("WHATSAPP_DISABLE", "").strip() == "":
    os.environ["WHATSAPP_DISABLE"] = "1"

from payal_seed_lib import run_payal_flow

if __name__ == "__main__":
    rc = run_payal_flow()
    print()
    du = os.environ.get("DATABASE_URL") or ""
    redacted = du.split("@")[-1] if "@" in du else "(set)"
    print("DATABASE_URL host/db:", redacted)
    print("E2E done, exit", rc)
    raise SystemExit(rc)
