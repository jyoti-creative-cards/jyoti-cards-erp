"""Unit tests — signed money convention (no DB)."""
from decimal import Decimal

from app.services.money import as_signed_decrease, as_signed_increase, mag


def test_mag():
    assert mag(-12.5) == Decimal("12.50")
    assert mag("3") == Decimal("3.00")


def test_signed_increase():
    assert as_signed_increase(Decimal("100")) == Decimal("100.00")
    assert as_signed_increase(Decimal("-50")) == Decimal("50.00")


def test_signed_decrease():
    assert as_signed_decrease(Decimal("100")) == Decimal("-100.00")
    assert as_signed_decrease(Decimal("-50")) == Decimal("-50.00")


def test_outstanding_formula_example():
    """AR/AP/Freight: outstanding = Σ signed amounts."""
    opening = as_signed_increase(Decimal("1000"))
    bill = as_signed_increase(Decimal("500"))
    payment = as_signed_decrease(Decimal("300"))
    credit = as_signed_decrease(Decimal("50"))
    outstanding = opening + bill + payment + credit
    assert outstanding == Decimal("1150.00")
