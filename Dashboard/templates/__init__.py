"""Per-file WhatsApp template definitions; merged into `TEMPLATES` for `wa_templates.get_wa_template`."""
from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

_dash = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_dash, ".env"), override=True)
except ImportError:
    pass

from . import account_creation
from . import delivery_update_4
from . import order_booked
from . import order_management_1
from . import payment_reminder_3

def _entry(mod: Any) -> tuple[str, dict[str, Any]]:
    return mod.TEMPLATE_KEY, deepcopy(mod.SPEC)

_raw = (
    _entry(account_creation),
    _entry(order_management_1),
    _entry(delivery_update_4),
    _entry(order_booked),
    _entry(payment_reminder_3),
)
TEMPLATES: dict[str, dict[str, Any]] = dict(_raw)
