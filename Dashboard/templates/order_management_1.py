"""
`order_management_1` · Hindi (Utility) — 5 **numbered** body variables {{1}}…{{5}} in Meta
("Type of variable: Number" in the editor = positional in API).

Order of values: (1) customer name, (2) order no., (3) item / SKU ref, (4) quantity, (5) line amount/price.
"""
from __future__ import annotations

TEMPLATE_KEY = "order_confirmed"

SPEC: dict = {
    "name": "order_management_1",
    "language": "hi",
    "param_style": "positional",
    # Logical keys; send dict must include all, in this order = {{1}}..{{5}}
    "body_keys": (
        "name",
        "order_id",
        "item_id",
        "quantity",
        "amount",
    ),
}
