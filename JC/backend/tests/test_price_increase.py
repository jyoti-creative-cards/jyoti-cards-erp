"""From 20 Nov 2026 a customer bill adds 7% of the stock-item total."""

from datetime import date
from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader

from app.services.customer_bill_math import compute_bill_totals
from app.services.customer_bill_pdf import render_customer_bill_pdf
from app.services.price_increase import NAME, NOTE


def _items(price="100.00"):
    return [{
        "catalog_product_id": 1,
        "our_product_id": "1001 CARD",
        "name": "1001 CARD",
        "quantity": 1,
        "unit_price": price,
    }]


def test_bill_before_the_rule_has_no_increase():
    totals = compute_bill_totals(
        _items(),
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        discount_percent=None,
        freight_charges=Decimal("10"),
        additional_charges=[{"name": "Cover", "amount": "0"}],
        bill_date=date(2026, 11, 19),
    )
    assert totals["additional_charges"] in (None, [])
    assert Decimal(totals["rounded_grand_total"]) == Decimal("110")


def test_seven_percent_is_only_on_the_item_total():
    totals = compute_bill_totals(
        _items(),
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        discount_percent=None,
        freight_charges=Decimal("10"),
        additional_charges=[{"name": "Cover", "amount": "5.00"}],
        bill_date=date(2026, 11, 20),
    )
    charges = {row["name"]: Decimal(row["amount"]) for row in totals["additional_charges"]}
    assert charges["Cover"] == Decimal("5.00")
    assert charges[NAME] == Decimal("7.00")
    # 100 items + 7 increase + 10 freight + 5 cover = 122
    assert Decimal(totals["rounded_grand_total"]) == Decimal("122")


def test_increase_is_not_added_twice():
    totals = compute_bill_totals(
        _items(),
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        discount_percent=None,
        additional_charges=[{"name": NAME, "amount": "99.00"}],
        bill_date=date(2026, 11, 20),
    )
    names = [row["name"] for row in totals["additional_charges"]]
    assert names.count(NAME) == 1
    assert Decimal(totals["additional_charges"][0]["amount"]) == Decimal("7.00")


def test_printed_bill_shows_the_charge_and_the_note():
    totals = compute_bill_totals(
        _items(),
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        discount_percent=None,
        freight_charges=Decimal("10"),
        bill_date=date(2026, 11, 20),
    )
    pdf = render_customer_bill_pdf(
        bill_id=1,
        order_id=1,
        customer_name="Raj Cards",
        customer_company=None,
        totals=totals,
        bill_number="T1",
        invoice_date=date(2026, 11, 20),
        copies=1,
        with_labels=False,
    )
    text = "\n".join((page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages)
    assert NAME in text
    assert "117" in text
    assert NOTE in text
    old = dict(totals)
    old["additional_charges"] = [{"name": "Increased charges", "amount": "7.00"}]
    old_pdf = render_customer_bill_pdf(
        bill_id=1,
        order_id=1,
        customer_name="Raj Cards",
        customer_company=None,
        totals=old,
        bill_number="T1",
        invoice_date=date(2026, 11, 20),
        copies=1,
        with_labels=False,
    )
    old_text = "\n".join((page.extract_text() or "") for page in PdfReader(BytesIO(old_pdf)).pages)
    assert "7% increased charges" in old_text
    assert "Increased charges" not in old_text.replace("7% increased charges", "")
