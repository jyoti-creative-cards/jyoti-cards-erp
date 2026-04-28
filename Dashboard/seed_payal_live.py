#!/usr/bin/env python3
"""Seed Payal demo into **your** database from ``Dashboard/.env``.

Loads ``DATABASE_URL`` (Postgres), ``S3_*``, WhatsApp/Meta vars **before** importing ``db``.

Usage::

  cd Dashboard && python3 seed_payal_live.py

Unset ``WHATSAPP_DISABLE`` or set ``WHATSAPP_DISABLE=0`` in ``.env`` to attempt real WhatsApp sends.

If the Payal phone already exists, exits with code 2 (no duplicate rows).
"""
from __future__ import annotations

import os
import sys

_D = os.path.dirname(os.path.abspath(__file__))
_ENV = os.path.join(_D, ".env")

try:
    from dotenv import load_dotenv

    load_dotenv(_ENV, override=True)
except ImportError:
    if os.path.isfile(_ENV):
        with open(_ENV, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, rest = line.partition("=")
                k, v = k.strip(), rest.strip().strip('"').strip("'")
                if k:
                    os.environ.setdefault(k, v)

if __name__ == "__main__":
    # Import after dotenv so DATABASE_URL is set before db loads
    from payal_seed_lib import run_payal_flow

    raise SystemExit(run_payal_flow())
