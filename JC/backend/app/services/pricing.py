from __future__ import annotations

from decimal import Decimal
from typing import Optional


def effective_selling_price(buying_price, selling_price) -> Optional[Decimal]:
    """Sell is unset when null, or when it was copied equal to buy (not a real sell)."""
    if selling_price is None:
        return None
    buy = Decimal(str(buying_price or 0))
    sell = Decimal(str(selling_price))
    if sell == buy:
        return None
    return sell


def coerce_selling_price(buying_price, selling_price) -> Optional[Decimal]:
    """Normalize inbound sell for storage — equal-to-buy becomes null."""
    if selling_price is None:
        return None
    sell = Decimal(str(selling_price)).quantize(Decimal("0.01"))
    buy = Decimal(str(buying_price or 0)).quantize(Decimal("0.01"))
    if sell == buy:
        return None
    return sell
