from __future__ import annotations


def stock_status_label(quantity: int, threshold: int) -> str:
    if quantity <= 0:
        return "out_of_stock"
    if quantity < max(threshold, 1):
        return "low_stock"
    return "in_stock"
