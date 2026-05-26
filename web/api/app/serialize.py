"""JSON helpers for ``db.py`` dataclasses."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def model_to_json(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return dict(obj)
    raise TypeError(f"Unsupported type {type(obj)}")


def customer_public(c: Any) -> dict[str, Any]:
    d = model_to_json(c)
    d.pop("password_hash", None)
    return d
