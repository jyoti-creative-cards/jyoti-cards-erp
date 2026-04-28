"""Document-model flow: PO -> goods receipt -> vendor bill 3-way match -> sales order -> delivery -> invoice.

Requires ``DATABASE_URL`` (PostgreSQL).

Run:
  cd Dashboard && DATABASE_URL=... python3 e2e_document_flow_test.py
"""
from __future__ import annotations

import os
import sys

_D = os.path.dirname(os.path.abspath(__file__))
if not os.environ.get("DATABASE_URL", "").strip():
    print("Set DATABASE_URL (PostgreSQL).", file=sys.stderr)
    raise SystemExit(2)

import db  # noqa: E402


def main() -> int:
    db.run_schema_maintenance()
    wh = db.get_default_warehouse()
    assert wh.code == "MAIN"

    vid = db.insert_vendor(
        "Doc Vendor",
        "Vendor Co",
        "9100001111",
        None,
        30,
        100,
        "Document flow vendor",
        "My Business",
        "1 Trade St",
        "Mumbai 400001",
        "27ABCDE1234F1Z5",
        "9100009999",
        "owner@example.com",
    )
    pid = db.insert_vendor_product(
        vid, "V-DOC-1", "DOC-SKU-1", "Document Product", "Demo", 100.0, 18.0, 0
    )
    cid = db.insert_customer("Doc Customer", "Buyer Co", "9200001111", None, "Pune", "pw123")

    po_id = db.create_purchase_order_document(
        vid,
        [{"product_id": pid, "quantity": 10.0, "unit_cost": 100.0}],
        notes="PO doc test",
    )
    po = db.get_purchase_order_document(po_id)
    assert po and po["pdf_path"], "PO PDF should be generated"
    po_lines = db.list_purchase_order_document_lines(po_id)
    assert len(po_lines) == 1
    assert abs(float(po_lines[0]["line_base_total"]) - 1000.0) < 0.01
    assert abs(float(po_lines[0]["line_gst_total"]) - 180.0) < 0.01

    grn_id = db.create_goods_receipt_document(
        po_id,
        [{"po_line_id": po_lines[0]["id"], "quantity": 10.0}],
        vendor_receipt_ref="VR-1",
        grn_number="GRN-1",
    )
    assert grn_id
    assert abs(db.stock_on_hand_v2(pid) - 10.0) < 0.01

    vb_id = db.create_vendor_bill_document(
        po_id,
        [{"po_line_id": po_lines[0]["id"], "quantity": 10.0, "unit_cost": 100.0}],
        goods_receipt_id=grn_id,
        vendor_invoice_ref="INV-V-1",
    )
    vb = db.get_vendor_bill_document(vb_id)
    assert vb and vb["match_status"] == "matched", vb

    so_id = db.create_sales_order_document(
        cid,
        [{"product_id": pid, "quantity": 2.0, "unit_price_incl_gst": 118.0}],
        notes="SO doc test",
    )
    so_lines = db.list_sales_order_document_lines(so_id)
    assert len(so_lines) == 1
    assert abs(float(so_lines[0]["line_base_total"]) - 200.0) < 0.01
    assert abs(float(so_lines[0]["line_gst_total"]) - 36.0) < 0.01
    assert abs(float(so_lines[0]["line_grand_total"]) - 236.0) < 0.01

    dn_id = db.create_delivery_document(
        so_id,
        [{"sales_order_line_id": so_lines[0]["id"], "quantity": 2.0}],
        delivery_receipt_number="DL-1",
        delivery_contact="Driver",
    )
    assert dn_id
    assert abs(db.stock_on_hand_v2(pid) - 8.0) < 0.01

    inv_id = db.create_customer_invoice_document(so_id, delivery_doc_id=dn_id)
    invoices = db.list_customer_invoice_documents()
    assert any(int(x["id"]) == inv_id for x in invoices)
    hist = db.get_document_history("product", pid)
    assert hist["purchase_orders"] and hist["customer_invoices"]

    stats = db.get_document_dashboard_stats()
    assert stats["purchase_orders"] == 1
    assert stats["three_way_disputes"] == 0
    print("Document flow OK.")
    print("DB:", db.get_db_path())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
