from __future__ import annotations


def stock_status_label(quantity: int, threshold: int) -> str:
    """Customer-storefront label — out_of_stock covers both 0 and negative on-hand.

    Do not add a distinct negative value here: shop.py does exact string
    comparisons against "out_of_stock" to hide/gate products, and a dealer
    should never be able to tell an oversold (negative) product apart from a
    plain zero-stock one. Admin views want that distinction — see
    admin_stock_status_label below.
    """
    if quantity <= 0:
        return "out_of_stock"
    if quantity < max(threshold, 1):
        return "low_stock"
    return "in_stock"


def admin_stock_status_label(quantity: int, threshold: int) -> str:
    """Admin-facing label — same as stock_status_label but flags negative
    on-hand (oversold via admin offline/allow-negative paths) separately from
    a plain zero, matching addons.py's _stock_status. Admin needs to know
    "this needs a correction" (negative) vs "just empty" (zero).
    """
    if quantity < 0:
        return "negative_stock"
    return stock_status_label(quantity, threshold)
