from types import SimpleNamespace

from app.services.doc_gen import customer_order_source_line
from app.services.pdf_documents import render_customer_order_pdf


def test_order_source_line_app_and_offline():
    app = SimpleNamespace(id=1, order_source="app", placed_by_name=None, customer_notes=None)
    assert customer_order_source_line(None, app) == "From party (our app)"

    staff = SimpleNamespace(id=2, order_source="offline", placed_by_name="Ravi", customer_notes=None)
    assert customer_order_source_line(None, staff) == "Offline order by Ravi"

    admin = SimpleNamespace(id=3, order_source="offline", placed_by_name="Admin", customer_notes=None)
    assert customer_order_source_line(None, admin) == "Offline order by Admin"


def test_order_receipt_pdf_includes_source():
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
        source_line="Offline order by Ravi",
    )
    import zlib
    from base64 import a85decode
    start = pdf.index(b"stream\n") + len(b"stream\n")
    blob = pdf[start:pdf.index(b"endstream")].strip()
    text = zlib.decompress(a85decode(blob, adobe=True)).decode("latin1")
    assert "Offline order by Ravi" in text
