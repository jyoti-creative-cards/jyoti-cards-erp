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
    *, billed_qty: int, received_qty: int, buying_price: Decimal, billing_pct: Decimal | None = None,
) -> Optional[dict]:
    """Value-type debit note for a line's billed-vs-received mismatch, at the FULL
    (real) item price — never scaled by billing_pct.

    NOTE on billing_pct: that setting only controls what fraction of the value goes on
    the vendor's *paper* invoice (for tax) vs. paid as untaxed "extra cash" — it does not
    make the goods actually worth less. A missing/extra unit is still worth the full
    buying_price, so the debit note (which corrects the real money owed to/from the
    vendor) must use the full price. `billing_pct` is accepted but intentionally unused
    here — kept only so callers don't need special-casing.

    billed > received → vendor's paper claims more than physically arrived → 'over' → reduces payable.
    received > billed → vendor billed less than arrived → 'under' → increases payable.
    """
    diff = billed_qty - received_qty
    if diff == 0:
        return None
    amount_abs = (abs(Decimal(diff)) * buying_price).quantize(_CENTS)
    direction = "over" if diff > 0 else "under"
    amount = -amount_abs if direction == "over" else amount_abs
    return {"direction": direction, "amount": amount}


def line_value_deviation_debit_note(
    *, billed_amount: Decimal, received_qty: int, buying_price: Decimal, billing_pct: Decimal | None = None,
) -> Optional[dict]:
    """Value-type debit note for a line's actual billed amount vs the expected value for
    the received qty (received_qty * buying_price) — at the FULL (real) item price.

    NOTE on billing_pct: billing_pct is a tax-invoice split only (how much of the value
    appears on the vendor's paper bill vs. is paid as untaxed "extra cash" — see
    compute_bill_totals). It does NOT reduce the real value of the goods. So a quantity
    or rate mismatch must always be debited/credited at the full buying_price, never at
    the billing_pct-reduced paper rate — otherwise a 50%-billing vendor short-shipping 10
    units of a ₹10 item would only get debited ₹50 instead of the real ₹100 owed back.
    `billing_pct` is accepted but intentionally unused here — kept only so callers don't
    need special-casing.

    Generalizes the old qty-only check: `billed_amount` is the raw (pre-billing_pct) value
    the vendor's paper bill states for this line — qty x their rate. When it equals
    quantity_billed x our catalog buying_price (the default, no manual override), this is
    numerically identical to the old qty-deviation check. It also catches a pure rate
    mismatch (same qty, different price) or both at once.

    billed > expected → vendor's paper bill charges more than it should → 'over' → reduces payable.
    billed < expected → vendor's paper bill charges less than it should → 'under' → increases payable.
    """
    expected = Decimal(received_qty) * buying_price
    diff = billed_amount - expected
    if diff == 0:
        return None
    amount_abs = abs(diff).quantize(_CENTS)
    if amount_abs == 0:
        return None
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
