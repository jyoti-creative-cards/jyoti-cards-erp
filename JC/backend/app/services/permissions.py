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
    ("Recycle Bin", [("recycle.read", "View recycle bin"), ("recycle.write", "Restore / permanently delete")]),
    ("Vendor Orders", [("vendor_orders.read", "View vendor orders"), ("vendor_orders.write", "Place & edit vendor orders")]),
    ("Customer Orders", [("customer_orders.read", "View customer orders"), ("customer_orders.write", "Place & bill customer orders")]),
    ("Returns", [("returns.read", "View customer returns"), ("returns.write", "Create customer returns")]),
    ("Stock", [("stock.read", "View stock"), ("stock.write", "Receive stock & edit prices")]),
    ("Costs", [("costs.read", "See our buying price / cost & margins")]),
    ("Finance", [("finance.write", "Record vendor/customer payments & add expenses — no totals or reports")]),
]

ALL_STAFF_PERMISSIONS: List[str] = [p for _, perms in PERMISSION_GROUPS for p, _ in perms]


def _migrate_legacy_order_perms(perms: set[str]) -> set[str]:
    """Old staff JSON used vendor_orders to gate selling + returns. Expand once."""
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
            raw_set = {str(x) for x in data if str(x) in ALL_STAFF_PERMISSIONS}
            # Legacy rows only had vendor_orders; expand until staff is re-saved with split keys.
            has_split = any(
                p.startswith("customer_orders.") or p.startswith("returns.")
                for p in raw_set
            )
            return raw_set if has_split else _migrate_legacy_order_perms(raw_set)
    except json.JSONDecodeError:
        pass
    return set()


def dump_permissions(perms: List[str]) -> str:
    valid = [p for p in perms if p in ALL_STAFF_PERMISSIONS]
    return json.dumps(sorted(set(valid)))
