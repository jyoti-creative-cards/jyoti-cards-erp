from __future__ import annotations

from decimal import Decimal
from typing import Optional


def effective_selling_price(buying_price, selling_price) -> Optional[Decimal]:
    """Sell is unset when null, or when it was copied equal to buy (not a real sell).

    Explicit 0 is a real FOC price, including when buy is also 0.
    """
    if selling_price is None:
        return None
    sell = Decimal(str(selling_price))
    if sell == 0:
        return Decimal("0")
    buy = Decimal(str(buying_price or 0))
    if sell == buy:
        return None
    return sell


def coerce_selling_price(buying_price, selling_price) -> Optional[Decimal]:
    """Normalize inbound sell for storage — equal-to-buy becomes null, except explicit 0."""
    if selling_price is None:
        return None
    sell = Decimal(str(selling_price)).quantize(Decimal("0.01"))
    if sell == 0:
        return sell
    buy = Decimal(str(buying_price or 0)).quantize(Decimal("0.01"))
    if sell == buy:
        return None
    return sell
