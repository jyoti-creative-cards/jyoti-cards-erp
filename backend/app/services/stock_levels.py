"""Shared stock status labels for inventory and shop APIs."""

from __future__ import annotations


def stock_status_label(quantity: int, low_stock_threshold: int) -> str:
    if quantity <= 0:
        return "out_of_stock"
    if low_stock_threshold > 0 and quantity <= low_stock_threshold:
        return "low_stock"
    return "in_stock"
