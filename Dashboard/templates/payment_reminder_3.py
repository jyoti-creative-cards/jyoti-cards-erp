"""`payment_reminder_3` · Hindi — six numbered body variables {{1}}…{{6}} (utility)."""
from __future__ import annotations

TEMPLATE_KEY = "payment_reminder"

# Order matches Meta body: name, order #, amount due, qty, item #, order date.
SPEC: dict = {
    "name": "payment_reminder_3",
    "language": "hi",
    "param_style": "positional",
    "body_keys": (
        "name",
        "order_id",
        "amount_due",
        "quantity",
        "item_id",
        "order_date",
    ),
}
