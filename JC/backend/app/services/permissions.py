from __future__ import annotations

import json
from typing import List

# Assignable staff permissions
PERMISSION_GROUPS = [
    ("Customers", [("customers.read", "View customers"), ("customers.write", "Create / edit / delete customers")]),
    ("Vendors", [("vendors.read", "View vendors"), ("vendors.write", "Create / edit / delete vendors")]),
    ("Catalog", [("catalog.read", "View catalog products"), ("catalog.write", "Create / edit / delete catalog")]),
    ("Add-ons", [("addons.read", "View add-ons"), ("addons.write", "Create / edit / delete add-ons")]),
    ("Setup", [("setup.read", "View routes, cities, product options"), ("setup.write", "Manage setup data")]),
    # Label intentionally doesn't say "permanently delete" — every purge endpoint is
    # hard-gated to require_admin server-side regardless of this permission (see
    # recycle_bin.py), so recycle.write only ever grants restore, never purge.
    ("Recycle Bin", [("recycle.read", "View recycle bin"), ("recycle.write", "Restore routes/cities/customers/vendors/catalog & add-ons only — money-relevant restores (bills, receipts, debit notes, staff) and permanent delete are always admin-only")]),
    ("Vendor Orders", [("vendor_orders.read", "View vendor orders"), ("vendor_orders.write", "Place & edit vendor orders")]),
    ("Customer Orders", [("customer_orders.read", "View customer orders"), ("customer_orders.write", "Place & bill customer orders")]),
    ("Returns", [("returns.read", "View customer returns"), ("returns.write", "Create customer returns")]),
    ("Stock", [("stock.read", "View stock"), ("stock.write", "Receive, edit & bill stock (stock adjustment and selling-price edits are always owner/admin-only)")]),
    ("Costs", [("costs.read", "See our buying price / cost & margins")]),
    ("Finance", [("finance.write", "Record vendor/customer payments & add expenses — no totals or reports")]),
    ("Accounts Receivable", [
        ("ar.read", "See customer outstanding, ledger & statements"),
        ("ar.write", "Collect customer payments with full figures"),
    ]),
    ("Accounts Payable", [
        ("ap.read", "See vendor outstanding, bills & statements"),
        ("ap.write", "Pay vendors & upload payment receipts"),
    ]),
]

ALL_STAFF_PERMISSIONS: List[str] = [p for _, perms in PERMISSION_GROUPS for p, _ in perms]


def _migrate_legacy_order_perms(perms: set[str]) -> set[str]:
    """Old staff JSON used vendor_orders to gate selling + returns too. One-time
    expansion, applied to existing rows by the DB migration in db/session.py
    (_migrate_legacy_staff_permissions) — kept here only so that migration can
    reuse the exact same expansion rule. NOT called on every parse anymore:
    doing so silently granted customer_orders/returns access to any *new* staff
    account that was deliberately given only vendor_orders.read, with no way to
    opt out (see JC audit, Staff/Permissions module)."""
    out = set(perms)
    if "vendor_orders.read" in out:
        out.add("customer_orders.read")
        out.add("returns.read")
    if "vendor_orders.write" in out:
        out.add("customer_orders.write")
        out.add("returns.write")
    return {p for p in out if p in ALL_STAFF_PERMISSIONS}


def parse_permissions(raw: str | None) -> set[str]:
    if not raw:
        return set()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return {str(x) for x in data if str(x) in ALL_STAFF_PERMISSIONS}
    except json.JSONDecodeError:
        pass
    return set()


def dump_permissions(perms: List[str]) -> str:
    valid = [p for p in perms if p in ALL_STAFF_PERMISSIONS]
    return json.dumps(sorted(set(valid)))
