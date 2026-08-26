"""One-time: create 3 accountant-role staff accounts (Nikhil, Fiza, Raj).

Login is by phone number in this app; since these are internal staff (not real
customer-facing numbers), we use placeholder 10-digit phone numbers as login IDs
and set a unique, randomly generated password for each directly (bypassing the
default "last 4 digits of phone" scheme). WhatsApp delivery will fail for these
placeholder numbers — that's expected; credentials are printed here instead.

Permission set = the "Accountant" preset (see JC/web/admin/js/staff.js ROLE_PRESETS):
day-to-day ops (customers, vendors read, catalog/addons read, vendor & customer
orders, returns, stock) + finance.write (record payments/expenses, no totals) —
but NOT costs.read (no buying price) and NOT any delete-capable admin action
(void/purge/adjust-stock are hard-gated to admin regardless of permissions).

Usage:
    python3 scripts/create_accountant_staff.py            # dry run
    python3 scripts/create_accountant_staff.py --execute  # write
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal
from app.models.staff import Staff
from app.services.passwords import generate_portal_password, hash_password
from app.services.permissions import dump_permissions

ACCOUNTANT_PERMS = [
    # No customers.write / vendors.write / catalog.write / addons.write / setup.write / recycle.*:
    # those also gate "Delete" buttons in this app — read-only master data keeps this role delete-free.
    "customers.read", "vendors.read",
    "catalog.read", "addons.read", "setup.read",
    "vendor_orders.read", "vendor_orders.write",
    "customer_orders.read", "customer_orders.write",
    "returns.read", "returns.write",
    "stock.read", "stock.write",
    "finance.write",
]

STAFF = [
    {"name": "Nikhil", "phone": "9000000101"},
    {"name": "Fiza", "phone": "9000000102"},
    {"name": "Raj", "phone": "9000000103"},
]


def main() -> None:
    execute = "--execute" in sys.argv
    db = SessionLocal()
    try:
        perms = dump_permissions(ACCOUNTANT_PERMS)
        created = []
        for s in STAFF:
            existing = db.query(Staff).filter(Staff.phone == s["phone"]).first()
            if existing:
                print(f"  SKIP {s['name']} — phone {s['phone']} already registered (staff #{existing.id})")
                continue
            password = generate_portal_password(8)
            print(f"  {s['name']}: phone={s['phone']} password={password}")
            if execute:
                row = Staff(
                    name=s["name"],
                    phone=s["phone"],
                    password_hash=hash_password(password),
                    permissions_json=perms,
                )
                db.add(row)
                created.append((s["name"], s["phone"], password))
        if execute:
            db.commit()
            print(f"\nCreated {len(created)} staff account(s).")
        else:
            print("\n[dry run] Re-run with --execute to write.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
