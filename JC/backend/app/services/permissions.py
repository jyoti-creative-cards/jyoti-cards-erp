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
    ("Stock", [("stock.read", "View stock"), ("stock.write", "Receive stock & edit prices")]),
]

ALL_STAFF_PERMISSIONS: List[str] = [p for _, perms in PERMISSION_GROUPS for p, _ in perms]


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
