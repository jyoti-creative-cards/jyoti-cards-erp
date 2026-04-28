"""
WhatsApp template index. Definitions live in `templates/*.py` (one file per template).
"""
from __future__ import annotations

import os
import sys
from copy import deepcopy
from typing import Any, Optional

# Ensure `import templates` resolves to `Dashboard/templates/`
_dash = os.path.dirname(os.path.abspath(__file__))
if _dash not in sys.path:
    sys.path.insert(0, _dash)

from templates import TEMPLATES  # noqa: E402


def get_wa_template(key: str) -> Optional[dict[str, Any]]:
    t = TEMPLATES.get(key)
    return deepcopy(t) if t is not None else None


def list_wa_template_keys() -> list[str]:
    return sorted(TEMPLATES.keys())
