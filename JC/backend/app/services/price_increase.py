from __future__ import annotations

"""7% on the stock-item total of a customer bill, from 20 Nov 2026.

The percent is of the item total after discount. Freight, packing, transport,
add-ons, and other charges are not part of the base. The amount is one extra
charge on the bill, and the printed bill carries a fixed note.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

START = date(2026, 11, 20)
RATE = Decimal("7")
NAME = "Increased charges"
NOTE = "7% increase price due to new rule"


def applies(bill_date: date | None) -> bool:
    return bill_date is not None and bill_date >= START


def amount_for(goods_after_discount: Decimal) -> Decimal:
    goods = goods_after_discount if goods_after_discount > 0 else Decimal("0")
    return (goods * RATE / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def without_increase(charges: list | None) -> list:
    kept = []
    for row in charges or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("name") or "").strip().lower() == NAME.lower():
            continue
        kept.append(row)
    return kept


def with_increase(charges: list | None, goods_after_discount: Decimal, bill_date: date | None) -> list:
    kept = without_increase(charges)
    if not applies(bill_date):
        return kept
    amount = amount_for(goods_after_discount)
    if amount <= 0:
        return kept
    kept.append({"name": NAME, "amount": format(amount, "f")})
    return kept
