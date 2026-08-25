from __future__ import annotations

from decimal import Decimal
from typing import Optional

_CENTS = Decimal("0.01")
_HUNDRED = Decimal("100")


def compute_bill_totals(
    *,
    total_actual_value: Decimal,
    billing_pct: Decimal,
    additional_charge: Decimal,
    discount_pct: Decimal,
    gst_included: bool,
    gst_rate_pct: Decimal,
) -> tuple[Decimal, Decimal]:
    """Returns (bill_total, extra_cash) per the vendor billing formula.

    bill_total is the paper-invoice amount (Entry 1 in AP).
    extra_cash is the untaxed remainder for split-billing vendors (0 when billing_pct == 100).
    """
    on_paper = (total_actual_value * billing_pct / _HUNDRED).quantize(_CENTS)
    after_discount = (on_paper * (_HUNDRED - discount_pct) / _HUNDRED).quantize(_CENTS)
    base = after_discount + additional_charge
    gst_amount = (base * gst_rate_pct / _HUNDRED).quantize(_CENTS) if gst_included else Decimal("0.00")
    bill_total = (base + gst_amount).quantize(_CENTS)
    extra_cash = (total_actual_value * (_HUNDRED - billing_pct) / _HUNDRED).quantize(_CENTS)
    return bill_total, extra_cash


def qty_deviation_debit_note(
    *, billed_qty: int, received_qty: int, buying_price: Decimal, billing_pct: Decimal,
) -> Optional[dict]:
    """Value-type debit note for a line's billed-vs-received mismatch, scaled by billing_pct.

    billed > received → vendor's paper claims more than physically arrived → 'over' → reduces payable.
    received > billed → vendor billed less than arrived → 'under' → increases payable.
    """
    diff = billed_qty - received_qty
    if diff == 0:
        return None
    amount_abs = (abs(Decimal(diff)) * buying_price * billing_pct / _HUNDRED).quantize(_CENTS)
    direction = "over" if diff > 0 else "under"
    amount = -amount_abs if direction == "over" else amount_abs
    return {"direction": direction, "amount": amount}


def amount_deviation_debit_note(
    *, expected_bill_total: Decimal, entered_bill_total: Decimal,
) -> Optional[dict]:
    """Value-type debit note for the whole-bill total vs the rule-calculated expectation."""
    diff = (entered_bill_total - expected_bill_total).quantize(_CENTS)
    if diff == 0:
        return None
    direction = "over" if diff > 0 else "under"
    amount = -abs(diff) if direction == "over" else abs(diff)
    return {"direction": direction, "amount": amount}
