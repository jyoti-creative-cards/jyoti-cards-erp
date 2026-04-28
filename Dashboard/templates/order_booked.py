"""
Order **booked** (portal placed) — 5 **numbered** body variables {{1}}…{{5}} in Meta, same order as `order_management_1`:
(1) customer name, (2) order #, (3) item, (4) quantity, (5) line amount.
Create/approve a template in Meta (e.g. `order_placed_1`); set `name` below to match.
"""
from __future__ import annotations

TEMPLATE_KEY = "order_booked"

SPEC: dict = {
    "name": "order_placed_1",
    "language": "hi",
    "param_style": "positional",
    "body_keys": ("name", "order_id", "item_id", "quantity", "amount"),
}
