"""Per-file WhatsApp template definitions; merged into `TEMPLATES` for `wa_templates.get_wa_template`."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import account_creation
from . import delivery_update_4
from . import order_booked
from . import order_management_1

def _entry(mod: Any) -> tuple[str, dict[str, Any]]:
    return mod.TEMPLATE_KEY, deepcopy(mod.SPEC)

_raw = (
    _entry(account_creation),
    _entry(order_management_1),
    _entry(delivery_update_4),
    _entry(order_booked),
)
TEMPLATES: dict[str, dict[str, Any]] = dict(_raw)
