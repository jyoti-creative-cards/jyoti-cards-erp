"""Normalize bill transport mode: bus, transport, or self-pickup."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Optional

from fastapi import HTTPException

MODES = ("bus", "transport", "self_pickup")


def _money(raw: object) -> Decimal:
    try:
        return Decimal(str(raw).strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, AttributeError, TypeError, ValueError) as e:
        raise HTTPException(400, "charges must be a number") from e


def normalize_transport(
    *,
    transport_mode: Optional[str],
    freight_agent_id: Optional[int],
    freight_charges: object,
    transport_receipt_number: Optional[str],
) -> dict[str, Any]:
    mode = (transport_mode or "").strip().lower()
    if mode not in MODES:
        raise HTTPException(400, "select mode of transport")

    receipt = (transport_receipt_number or "").strip() or None

    if mode == "self_pickup":
        return {
            "transport_mode": mode,
            "freight_agent_id": None,
            "freight_charges": None,
            "transport_receipt_number": None,
        }

    if freight_charges is None or str(freight_charges).strip() == "":
        raise HTTPException(
            400,
            "enter transport charges" if mode == "transport" else "enter freight charges",
        )
    amt = _money(freight_charges)
    if amt < 0:
        raise HTTPException(400, "charges cannot be negative")

    if mode == "bus":
        if not freight_agent_id:
            raise HTTPException(400, "select freight agent")
        return {
            "transport_mode": mode,
            "freight_agent_id": int(freight_agent_id),
            "freight_charges": amt,
            "transport_receipt_number": None,
        }

    return {
        "transport_mode": mode,
        "freight_agent_id": None,
        "freight_charges": amt,
        "transport_receipt_number": receipt,
    }


def stamp_transport_on_totals(
    totals: dict,
    transport: dict[str, Any],
    *,
    agent_name: Optional[str] = None,
) -> dict:
    out = dict(totals or {})
    out["transport_mode"] = transport["transport_mode"]
    out["transport_receipt_number"] = transport.get("transport_receipt_number")
    if transport["transport_mode"] == "bus" and agent_name:
        out["freight_agent_name"] = agent_name
    elif "freight_agent_name" in out:
        out.pop("freight_agent_name", None)
    return out
