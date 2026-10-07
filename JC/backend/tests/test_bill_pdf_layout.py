"""Customer bill PDF follows the Tally invoice page breaks."""
import re

from app.services.customer_bill_pdf import render_customer_bill_pdf


def _pages(pdf: bytes) -> int:
    return len(re.findall(br"/Type\s*/Page(?!s)", pdf))


def _lines(n: int, *, gst: bool) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        row = {
            "catalog_product_id": i,
            "our_product_id": f"JC-{i:04d}",
            "name": f"Greeting card design {i}",
            "quantity": 12,
            "rate_inclusive": "25.00",
            "unit_price": "25.00",
            "net_rate": "22.50",
            "line_total": "270.00",
            "line_discount": "30.00",
            "line_inclusive_before_discount": "300.00",
            "item_discount_percent": "10",
        }
        if gst:
            row["line_taxable_value"] = "228.81"
            row["line_gst_amount"] = "41.19"
        rows.append(row)
    return rows


def _totals(n: int, *, gst: bool) -> dict:
    totals = {
        "gst_enabled": gst,
        "gst_rate_label": "18%" if gst else "",
        "lines": _lines(n, gst=gst),
        "subtotal_inclusive": "7500.00",
        "discount_percent": "10",
        "discount_amount": "750.00",
        "after_discount_inclusive": "6750.00",
        "packaging_charges": "40.00",
        "freight_charges": "80.00",
        "transport_mode": "bus",
        "freight_agent_name": "Rajasthan Roadways",
        "round_off": "0.50",
        "rounded_grand_total": "6870.50",
        "grand_total": "6870.00",
    }
    if gst:
        totals["taxable_value"] = "5720.34"
        totals["gst_amount"] = "1029.66"
    return totals


def _render(n: int, *, gst: bool) -> bytes:
    return render_customer_bill_pdf(
        bill_id=18,
        order_id=18,
        bill_number="EST-18",
        customer_name="Sharma Gift House",
        customer_company="Sharma Traders",
        customer_phone="9812345678",
        customer_address="12 Market Road, Near Bus Stand, Ward 4",
        customer_city="JODHPUR",
        customer_party_number=42,
        totals=_totals(n, gst=gst),
        narration="Send by evening bus",
        customer_notes="Call before dispatch",
        outstanding=12500.0,
        item_image_urls={i: None for i in range(1, n + 1)},
    )


def test_short_bill_is_one_page():
    for n in (1, 2, 9):
        pdf = _render(n, gst=False)
        assert pdf.startswith(b"%PDF")
        assert _pages(pdf) == 2, n


def test_long_bill_continues_onto_second_page():
    pdf = _render(29, gst=False)
    assert pdf.startswith(b"%PDF")
    assert _pages(pdf) == 4


def test_gst_bill_uses_the_same_page_breaks():
    assert _pages(_render(9, gst=True)) == 2
    assert _pages(_render(29, gst=True)) == 4


def _pdf_text(pdf: bytes) -> str:
    import zlib
    from base64 import a85decode

    parts = []
    rest = pdf
    while b"stream\n" in rest:
        start = rest.index(b"stream\n") + len(b"stream\n")
        end = rest.find(b"endstream", start)
        if end < 0:
            break
        blob = rest[start:end].strip()
        rest = rest[end + len(b"endstream"):]
        for attempt in (
            lambda: zlib.decompress(blob).decode("latin1"),
            lambda: zlib.decompress(a85decode(blob, adobe=True)).decode("latin1"),
        ):
            try:
                parts.append(attempt())
                break
            except Exception:
                continue
    return "\n".join(parts)


def test_every_bill_is_original_and_duplicate():
    text = _pdf_text(_render(1, gst=False))
    assert text.count("ORIGINAL") == 1
    assert text.count("DUPLICATE") == 1
    assert "TRIPLICATE" not in text
    assert "12 pcs" in text
    assert "12.00 pcs" not in text
