"""
Order **booked** (portal placed) — Meta **`order_booking`**: four numbered variables {{1}}…{{4}}
(1) customer name, (2) order #, (3) item/SKU line, (4) quantity.
Different from **`order_confirmed`** (`order_management_1`). Override name via env if needed.
"""
from __future__ import annotations

import os

TEMPLATE_KEY = "order_booked"

_SPEC_NAME = (
    (os.environ.get("WHATSAPP_ORDER_BOOKED_TEMPLATE_NAME") or "").strip()
    or "order_booking"
)

SPEC: dict = {
    "name": _SPEC_NAME,
    "language": "hi",
    "param_style": "positional",
    "body_keys": ("name", "order_id", "item_id", "quantity"),
}
