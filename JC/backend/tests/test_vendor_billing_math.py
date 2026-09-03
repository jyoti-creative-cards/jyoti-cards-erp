from decimal import Decimal
from app.services.vendor_billing_math import (
    compute_bill_totals, qty_deviation_debit_note, amount_deviation_debit_note,
    line_value_deviation_debit_note,
)

def test_100pct_no_discount_with_gst():
    # Singhal-style: 100 units @ 10 = 1000 actual value, 0 discount, 0 charge, 18% gst
    bill_total, extra_cash = compute_bill_totals(
        total_actual_value=Decimal("1000"), billing_pct=Decimal("100"),
        additional_charge=Decimal("0"), discount_pct=Decimal("0"),
        gst_included=True, gst_rate_pct=Decimal("18"),
    )
    assert bill_total == Decimal("1180.00")
    assert extra_cash == Decimal("0.00")

def test_garg_discount_charge_gst():
    # 1000 actual value, 6% discount, +100 charge, 18% gst
    bill_total, extra_cash = compute_bill_totals(
        total_actual_value=Decimal("1000"), billing_pct=Decimal("100"),
        additional_charge=Decimal("100"), discount_pct=Decimal("6"),
        gst_included=True, gst_rate_pct=Decimal("18"),
    )
    # after_discount = 940, base = 1040, gst = 187.20, total = 1227.20
    assert bill_total == Decimal("1227.20")
    assert extra_cash == Decimal("0.00")

def test_veepee_half_billing_with_packing_and_extra_cash():
    # 100 units @ 10 = 1000 actual value, 50% billing, +100 packing, 18% gst, no discount
    bill_total, extra_cash = compute_bill_totals(
        total_actual_value=Decimal("1000"), billing_pct=Decimal("50"),
        additional_charge=Decimal("100"), discount_pct=Decimal("0"),
        gst_included=True, gst_rate_pct=Decimal("18"),
    )
    # on_paper = 500, base = 600, gst = 108, bill_total = 708; extra_cash = 500
    assert bill_total == Decimal("708.00")
    assert extra_cash == Decimal("500.00")

def test_qty_deviation_billed_more_than_received_is_over():
    dn = qty_deviation_debit_note(
        billed_qty=110, received_qty=100, buying_price=Decimal("10"), billing_pct=Decimal("100"),
    )
    assert dn == {"direction": "over", "amount": Decimal("-100.00")}

def test_qty_deviation_received_more_than_billed_is_under():
    dn = qty_deviation_debit_note(
        billed_qty=90, received_qty=100, buying_price=Decimal("10"), billing_pct=Decimal("100"),
    )
    assert dn == {"direction": "under", "amount": Decimal("100.00")}

def test_qty_deviation_none_when_equal():
    assert qty_deviation_debit_note(
        billed_qty=100, received_qty=100, buying_price=Decimal("10"), billing_pct=Decimal("100"),
    ) is None

def test_qty_deviation_applies_billing_pct():
    # VEE PEE: 10 unit gap at 50% billing → only half the value is disputed
    dn = qty_deviation_debit_note(
        billed_qty=110, received_qty=100, buying_price=Decimal("10"), billing_pct=Decimal("50"),
    )
    assert dn == {"direction": "over", "amount": Decimal("-50.00")}

def test_amount_deviation_entered_more_than_expected_is_over():
    dn = amount_deviation_debit_note(
        expected_bill_total=Decimal("1180.00"), entered_bill_total=Decimal("1200.00"),
    )
    assert dn == {"direction": "over", "amount": Decimal("-20.00")}

def test_amount_deviation_none_when_equal():
    assert amount_deviation_debit_note(
        expected_bill_total=Decimal("1180.00"), entered_bill_total=Decimal("1180.00"),
    ) is None

def test_line_value_deviation_matches_qty_deviation_when_default():
    # No manual override: billed_amount defaults to billed_qty * buying_price — same as qty check.
    dn = line_value_deviation_debit_note(
        billed_amount=Decimal("110") * Decimal("10"), received_qty=100,
        buying_price=Decimal("10"), billing_pct=Decimal("100"),
    )
    assert dn == {"direction": "over", "amount": Decimal("-100.00")}

def test_line_value_deviation_catches_pure_rate_mismatch():
    # Same qty (100) received & billed, but vendor billed at 4.2 instead of catalog rate 4.1.
    dn = line_value_deviation_debit_note(
        billed_amount=Decimal("100") * Decimal("4.2"), received_qty=100,
        buying_price=Decimal("4.1"), billing_pct=Decimal("100"),
    )
    assert dn == {"direction": "over", "amount": Decimal("-10.00")}

def test_line_value_deviation_none_when_matches_expected():
    dn = line_value_deviation_debit_note(
        billed_amount=Decimal("1000"), received_qty=100,
        buying_price=Decimal("10"), billing_pct=Decimal("100"),
    )
    assert dn is None

def test_line_value_deviation_applies_billing_pct():
    dn = line_value_deviation_debit_note(
        billed_amount=Decimal("110") * Decimal("10"), received_qty=100,
        buying_price=Decimal("10"), billing_pct=Decimal("50"),
    )
    assert dn == {"direction": "over", "amount": Decimal("-50.00")}
