"""One-off: create test customer sourabh (phone login = password). Run from Dashboard/:
  WHATSAPP_ACCESS_TOKEN=... python3 create_sourabh_test_customer.py
Or put token in `.env` (see `.env.example`).
"""
from __future__ import annotations

import db

def main() -> None:
    db.init_db()
    cid = db.insert_customer(
        "sourabh",
        "",
        "8952839355",
        "",
        "",
        "8952839355",
    )
    print("Created customer id:", cid)


if __name__ == "__main__":
    main()
