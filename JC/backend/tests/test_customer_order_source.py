from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.customer_bill_pdf import render_customer_bill_pdf
from app.services.doc_gen import customer_order_by_label, customer_order_source_line
from app.services.pdf_documents import render_customer_order_pdf


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


def test_order_source_line_app_and_offline():
    app = SimpleNamespace(id=1, order_source="app", placed_by_name=None, customer_notes=None)
    assert customer_order_source_line(None, app) == "From party (our app)"
    assert customer_order_by_label(None, app) == "Party (app)"

    staff = SimpleNamespace(id=2, order_source="offline", placed_by_name="Ravi", customer_notes=None)
    assert customer_order_source_line(None, staff) == "Offline order by Ravi"
    assert customer_order_by_label(None, staff) == "Ravi"

    admin = SimpleNamespace(id=3, order_source="offline", placed_by_name="Admin", customer_notes=None)
    assert customer_order_source_line(None, admin) == "Offline order by Admin"
    assert customer_order_by_label(None, admin) == "Admin"


def test_order_receipt_pdf_includes_source_date_and_who():
    placed = datetime(2026, 9, 30, 6, 24, tzinfo=timezone.utc)
    pdf = render_customer_order_pdf(
        placement_id=9,
        customer_name="Sharma Cards",
        lines=[{
            "catalog_product_id": 1,
            "our_product_id": "A1",
            "name": "A1",
            "quantity": 50,
            "unit_price": "10.00",
            "line_total": "500.00",
        }],
        image_urls={},
        placed_at=placed,
        source_line="Offline order by Ravi",
        ordered_by="Ravi",
    )
    text = _pdf_text(pdf)
    assert "Offline order by Ravi" in text
    assert "30 Sep 2026, 11:54 AM IST" in text
    assert "By: Ravi" in text or "By Ravi" in text


def test_bill_pdf_includes_order_date_and_who():
    placed = datetime(2026, 9, 30, 6, 24, tzinfo=timezone.utc)
    pdf = render_customer_bill_pdf(
        bill_id=1,
        order_id=9,
        bill_number="L1",
        customer_name="Sharma Cards",
        customer_company=None,
        totals={
            "gst_enabled": False,
            "lines": [{
                "catalog_product_id": 1,
                "our_product_id": "A1",
                "name": "A1",
                "quantity": 2,
                "rate_inclusive": "20.00",
                "unit_price": "20.00",
                "net_rate": "20.00",
                "line_total": "40.00",
            }],
            "subtotal_inclusive": "40.00",
            "grand_total": "40.00",
            "rounded_grand_total": "40.00",
        },
        generated_at=datetime(2026, 9, 30, 7, 0, tzinfo=timezone.utc),
        order_created_at=placed,
        order_by="Ravi",
        invoice_date=placed.date(),
    )
    text = _pdf_text(pdf)
    assert "Order :" in text
    assert "30-Sep-26" in text
    assert "11:54 AM" in text
    assert "By : Ravi" in text
