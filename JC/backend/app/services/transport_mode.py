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


def _charge(raw: object) -> Decimal:
    if raw is None or str(raw).strip() == "":
        return Decimal("0.00")
    return Decimal(str(raw).strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def bill_totals_match_columns(bill) -> bool:
    """The print reads totals_json. It must still say what the bill row saved."""
    totals = bill.totals_json if isinstance(getattr(bill, "totals_json", None), dict) else {}
    if _charge(totals.get("freight_charges")) != _charge(bill.freight_charges):
        return False
    if _charge(totals.get("packaging_charges")) != _charge(bill.packaging_charges):
        return False
    shown = totals.get("rounded_grand_total") or totals.get("grand_total")
    if _charge(shown) != _charge(bill.grand_total):
        return False
    mode = (bill.transport_mode or "").strip().lower()
    if mode and str(totals.get("transport_mode") or "").strip().lower() != mode:
        return False
    return True


def align_totals_to_bill_charges(totals: dict | None, bill) -> dict:
    """Replace a stale freight/total snapshot with the amounts stored on the bill.

    Changing bus freight 50 to transport 35 updates the bill row. A print that
    still has the earlier snapshot shows 50 and a total 15 rupees too high.
    """
    out = dict(totals or {})
    old_freight = _charge(out.get("freight_charges"))
    old_pack = _charge(out.get("packaging_charges"))
    new_freight = _charge(bill.freight_charges)
    new_pack = _charge(bill.packaging_charges)
    old_grand = _charge(out.get("grand_total"))
    adjusted = (old_grand - old_freight - old_pack + new_freight + new_pack).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    posted = _charge(bill.grand_total)
    out["freight_charges"] = f"{new_freight:.2f}" if new_freight > 0 else None
    out["packaging_charges"] = f"{new_pack:.2f}" if new_pack > 0 else None
    if bill.transport_mode:
        out["transport_mode"] = bill.transport_mode
    out["transport_receipt_number"] = bill.transport_receipt_number
    if not bill.freight_agent_id:
        out.pop("freight_agent_name", None)
    # Trust the posted total. Keep the unrounded grand only when it still rounds to that.
    rounded = adjusted.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if rounded == posted and out.get("grand_total") not in (None, ""):
        out["grand_total"] = f"{adjusted:.2f}"
        round_off = (posted - adjusted).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        out["round_off"] = f"{round_off:.2f}" if round_off != 0 else None
    else:
        out["grand_total"] = f"{posted:.2f}"
        out["round_off"] = None
    out["rounded_grand_total"] = f"{posted:.2f}"
    return out


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
