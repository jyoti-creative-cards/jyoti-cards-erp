"""Bill totals — entered discount % must print and calculate, not derived 9.91."""
from decimal import Decimal

from app.services.customer_bill_math import (
    compute_bill_totals,
    fmt_discount_pct,
    prepare_totals_for_pdf,
    snap_discount_pct,
)


def test_entered_percent_wins_over_derived_net():
    totals = compute_bill_totals(
        [{
            "catalog_product_id": 1,
            "our_product_id": "X",
            "name": "X",
            "quantity": 1,
            "unit_price": "113.00",
        }],
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        discount_percent=None,
        item_overrides=[{
            "catalog_product_id": 1,
            "override_price": "101.80",
            "discount_percent": 10,
        }],
    )
    assert totals["lines"][0]["item_discount_percent"] == "10"
    assert totals["lines"][0]["line_total"] == "101.70"
    assert totals["discount_percent"] is None


def test_overall_ten_percent_stays_ten():
    totals = compute_bill_totals(
        [{
            "catalog_product_id": 1,
            "our_product_id": "X",
            "name": "X",
            "quantity": 800,
            "unit_price": "113.00",
        }],
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        discount_percent=Decimal("10"),
    )
    assert totals["discount_percent"] == "10"
    assert totals["lines"][0]["item_discount_percent"] == "10"
    assert totals["discount_amount"] == "9040.00"
    assert totals["lines"][0]["line_total"] == "81360.00"


def test_snap_rounding_artifact_to_ten():
    assert snap_discount_pct("9.91") == Decimal("10")
    assert fmt_discount_pct("9.91") == "10"
    assert fmt_discount_pct("7.50") == "7.50"


def test_pdf_summary_transport_label():
    from app.services.customer_bill_pdf import _build_summary_rows

    rows = _build_summary_rows(
        {
            "subtotal_inclusive": "100.00",
            "discount_amount": "0",
            "freight_charges": "25.00",
            "transport_mode": "transport",
            "transport_receipt_number": "LR-9",
            "grand_total": "125.00",
        },
        gst_on=False,
        gst_label="",
    )
    labels = [r[0] for r in rows]
    assert "Transport charges" in labels
    assert "Transport receipt" in labels
    assert "Freight charges" not in labels


def test_pdf_item_headers_include_rate_disc_net():
    from app.services.customer_bill_pdf import bill_item_headers

    plain = bill_item_headers(False)
    assert plain[4:7] == ["Rate", "Disc.", "Net"]
    gst = bill_item_headers(True, "18%")
    assert gst[4:7] == ["Rate", "Disc.", "Net"]


def test_pdf_addon_qty_scales_with_line():
    from app.services.customer_bill_pdf import _addon_qty, _money

    assert _addon_qty({"quantity": 1}, 800) == 800
    assert _addon_qty({"per_unit": 1, "quantity": 1}, 800) == 800
    assert _money("113") == "113.00"
    assert _money("81360") == "81,360.00"


def test_overall_percent_fills_line_net_rate():
    totals = compute_bill_totals(
        [{
            "catalog_product_id": 1,
            "our_product_id": "X",
            "name": "X",
            "quantity": 1,
            "unit_price": "113.00",
        }],
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        discount_percent=Decimal("10"),
    )
    line = totals["lines"][0]
    assert line["rate_inclusive"] == "113.00"
    assert line["item_discount_percent"] == "10"
    assert line["net_rate"] == "101.70"


def test_line_discount_percent_fills_net_rate():
    totals = compute_bill_totals(
        [{
            "catalog_product_id": 1,
            "our_product_id": "X",
            "name": "X",
            "quantity": 2,
            "unit_price": "100.00",
        }],
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        discount_percent=None,
        item_overrides=[{"catalog_product_id": 1, "discount_percent": 10}],
    )
    line = totals["lines"][0]
    assert line["rate_inclusive"] == "100.00"
    assert line["item_discount_percent"] == "10"
    assert line["net_rate"] == "90.00"
    assert line["line_total"] == "180.00"


def test_line_net_rate_derives_discount():
    totals = compute_bill_totals(
        [{
            "catalog_product_id": 1,
            "our_product_id": "X",
            "name": "X",
            "quantity": 1,
            "unit_price": "100.00",
        }],
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        discount_percent=None,
        item_overrides=[{"catalog_product_id": 1, "override_price": "85"}],
    )
    line = totals["lines"][0]
    assert line["rate_inclusive"] == "100.00"
    assert line["net_rate"] == "85.00"
    assert line["item_discount_percent"] == "15"
    assert line["line_total"] == "85.00"


def test_no_discount_net_equals_rate():
    totals = compute_bill_totals(
        [{
            "catalog_product_id": 1,
            "our_product_id": "X",
            "name": "X",
            "quantity": 1,
            "unit_price": "50.00",
        }],
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        discount_percent=None,
    )
    line = totals["lines"][0]
    assert line["net_rate"] == "50.00"
    assert line["item_discount_percent"] is None


def test_pdf_stamp_overrides_stale_nine_nine_one():
    stamped = prepare_totals_for_pdf(
        {
            "discount_percent": "9.91",
            "lines": [{"catalog_product_id": 1, "item_discount_percent": "9.91"}],
        },
        overall_percent=Decimal("10"),
    )
    assert stamped["discount_percent"] == "10"
    assert stamped["lines"][0]["item_discount_percent"] == "10"
