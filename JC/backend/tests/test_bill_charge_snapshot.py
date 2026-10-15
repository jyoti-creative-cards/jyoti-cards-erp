"""Print uses the freight saved on the bill, not an older snapshot."""
from decimal import Decimal
from types import SimpleNamespace

from app.services.customer_bill_pdf import render_customer_bill_pdf
from app.services.transport_mode import align_totals_to_bill_charges, bill_totals_match_columns


def _pdf_text(pdf: bytes) -> str:
    import zlib
    from base64 import a85decode

    parts = []
    rest = pdf.replace(b"\r\n", b"\n")
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


def _bill():
    return SimpleNamespace(
        freight_charges=Decimal("35.00"),
        packaging_charges=Decimal("35.00"),
        grand_total=Decimal("3158.00"),
        transport_mode="transport",
        transport_receipt_number=None,
        freight_agent_id=None,
        totals_json={
            "lines": [{
                "catalog_product_id": 1,
                "our_product_id": "JC-1",
                "name": "Card",
                "quantity": 10,
                "rate_inclusive": "308.80",
                "unit_price": "308.80",
                "line_total": "3088.00",
                "line_inclusive_before_discount": "3088.00",
                "item_discount_percent": None,
            }],
            "freight_charges": "50.00",
            "packaging_charges": "35.00",
            "transport_mode": "bus",
            "freight_agent_name": "Old Bus",
            "grand_total": "3172.50",
            "rounded_grand_total": "3173.00",
            "round_off": "0.50",
            "discount_amount": "0",
        },
    )


def test_stale_freight_snapshot_does_not_match_the_bill():
    bill = _bill()
    assert bill_totals_match_columns(bill) is False


def test_print_uses_transport_35_not_the_old_freight_50():
    bill = _bill()
    totals = align_totals_to_bill_charges(bill.totals_json, bill)
    assert totals["freight_charges"] == "35.00"
    assert totals["rounded_grand_total"] == "3158.00"
    assert totals["transport_mode"] == "transport"
    assert "freight_agent_name" not in totals
    pdf = render_customer_bill_pdf(
        bill_id=101,
        order_id=101,
        bill_number="B101",
        customer_name="Patel Graphics",
        customer_company=None,
        payment_type="CREDIT",
        totals=totals,
        copies=1,
        with_labels=False,
    )
    text = _pdf_text(pdf)
    assert "Transport Charges" in text
    assert "Freight Charges" not in text
    assert "35" in text
    assert "3,158" in text or "3158" in text
    assert "3,173" not in text and "3173" not in text
