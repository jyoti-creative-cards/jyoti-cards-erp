"""Broader business validation for ERP + customer portal semantics.

Requires ``DATABASE_URL`` (PostgreSQL).

Run:
  cd Dashboard && DATABASE_URL=... python3 e2e_business_validation.py
"""
from __future__ import annotations

import os
import sys

_D = os.path.dirname(os.path.abspath(__file__))
if not os.environ.get("DATABASE_URL", "").strip():
    print("Set DATABASE_URL (PostgreSQL).", file=sys.stderr)
    raise SystemExit(2)
os.environ["WHATSAPP_DISABLE"] = "1"
_ROOT = os.path.abspath(os.path.join(_D, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_CAPP = os.path.join(_ROOT, "Customer_Ordering_App")
if _CAPP not in sys.path:
    sys.path.insert(0, _CAPP)

import db  # noqa: E402
from login import try_login  # noqa: E402


def main() -> int:
    db.init_db()

    # Vendors and products
    own_vid = db.insert_vendor("Default Vendor", "Own Products", "9111111111", None, 0, 100, "Own stock vendor")
    ext_vid = db.insert_vendor(
        "External Vendor",
        "Supply Co",
        "9222222222",
        None,
        30,
        50,
        "External supply vendor",
        "My Business",
        "1 Trade St",
        "Mumbai 400001",
        "27ABCDE1234F1Z5",
        "9000000000",
        "owner@example.com",
    )
    low_pid = db.insert_vendor_product(ext_vid, "V-LOW-1", "LOW-1", "Low Stock Main", "Main", 100.0, 18.0, 0, low_stock_threshold=15.0)
    alt_pid = db.insert_vendor_product(own_vid, "OWN-ALT-1", "ALT-1", "Alternative Item", "Main", 90.0, 18.0, 0, low_stock_threshold=5.0)
    manual_pid = db.insert_vendor_product(own_vid, "OWN-MAN-1", "MAN-1", "Manual Stock Item", "Own", 80.0, 18.0, 0, low_stock_threshold=3.0)

    # Manual stock without PO
    db.insert_stock_receipt(manual_pid, None, 7.0, "OWN-BATCH", "OWN-GRN", 118.0, "manual own stock")
    assert abs(db.product_receipts_total(manual_pid) - 7.0) < 0.01

    # PO lifecycle on document flow
    po_id = db.create_purchase_order_document(
        ext_vid,
        [{"product_id": low_pid, "quantity": 12.0, "unit_cost": 100.0}],
        notes="Lifecycle validation",
    )
    po = db.get_purchase_order_document(po_id)
    assert po and po["status"] == "open"
    po_lines = db.list_purchase_order_document_lines(po_id)
    db.create_goods_receipt_document(po_id, [{"po_line_id": po_lines[0]["id"], "quantity": 4.0}], vendor_receipt_ref="PART-1", grn_number="GRN-P1")
    po = db.get_purchase_order_document(po_id)
    assert po and po["status"] == "in_progress"
    db.create_goods_receipt_document(po_id, [{"po_line_id": po_lines[0]["id"], "quantity": 8.0}], vendor_receipt_ref="PART-2", grn_number="GRN-P2")
    po = db.get_purchase_order_document(po_id)
    assert po and po["status"] == "closed"
    vb_id = db.create_vendor_bill_document(
        po_id,
        [{"po_line_id": po_lines[0]["id"], "quantity": 12.0, "unit_cost": 102.0}],
        vendor_invoice_ref="VEND-INV-1",
    )
    vb = db.get_vendor_bill_document(vb_id)
    assert vb and vb["match_status"] == "dispute"
    po = db.get_purchase_order_document(po_id)
    assert po and po["status"] == "disputed"

    # Alternative and low-stock visibility
    db.insert_stock_receipt(alt_pid, None, 20.0, "ALT-LOT", "ALT-GRN", 118.0, "alt stock")
    db.set_product_alternatives(low_pid, [alt_pid])
    portal_rows = db.search_all_products_prefix("LOW", 20)
    low_row = next(x for x in portal_rows if x["our_product_id"] == "LOW-1")
    assert low_row["stock_status"] == "low_stock"
    alts = db.instock_alternative_for_portal(low_pid, 10)
    assert any(a["our_product_id"] == "ALT-1" for a in alts)

    # Customer creation and login
    cid = db.insert_customer("Portal Buyer", "Buyer Co", "9333333333", None, "Pune", "pw123")
    ok, _name, got_cid = try_login("9333333333", "pw123")
    assert ok and got_cid == cid

    # Portal browse and legacy order flow
    manual_search = db.search_all_products_prefix("MAN", 10)
    assert any(x["our_product_id"] == "MAN-1" for x in manual_search)
    coid = db.insert_customer_order(cid, manual_pid, 2.0, unit_price=118.0, notes="Door delivery")
    order = db.get_customer_order(coid)
    assert order and order.status == "placed"
    db.update_customer_order(coid, status="confirmed", notes="Confirmed by shop")
    db.update_customer_order(
        coid,
        status="shipped",
        delivery_receipt_number="REC-1",
        delivery_contact="Carrier 99999",
        delivery_notes="Arriving tomorrow",
        notes="Confirmed by shop",
    )
    order = db.get_customer_order(coid)
    assert order and order.status == "shipped"
    assert order.delivery_receipt_number == "REC-1"
    db.update_customer_order(coid, status="delivered", notes="Customer received")
    order = db.get_customer_order(coid)
    assert order and order.status == "delivered"
    elig = db.list_customer_order_ids_eligible_new_billing()
    assert coid in elig
    cob_id = db.insert_customer_order_billing(coid)
    cob = db.get_customer_order_billing(cob_id)
    assert cob and abs(float(cob.raw_line_total) - 236.0) < 0.01

    # New document sales flow and inclusive GST invoice
    so_id = db.create_sales_order_document(cid, [{"product_id": alt_pid, "quantity": 1.0, "unit_price_incl_gst": 118.0}], notes="Doc sales")
    so_lines = db.list_sales_order_document_lines(so_id)
    assert abs(float(so_lines[0]["line_base_total"]) - 100.0) < 0.01
    assert abs(float(so_lines[0]["line_gst_total"]) - 18.0) < 0.01
    dn_id = db.create_delivery_document(so_id, [{"sales_order_line_id": so_lines[0]["id"], "quantity": 1.0}], delivery_receipt_number="DOC-REC", delivery_contact="Transport 88888")
    inv_id = db.create_customer_invoice_document(so_id, delivery_doc_id=dn_id)
    inv = next(x for x in db.list_customer_invoice_documents() if int(x["id"]) == inv_id)
    assert abs(float(inv["base_total"]) - 100.0) < 0.01
    assert abs(float(inv["gst_total"]) - 18.0) < 0.01
    assert inv["pdf_path"]

    # AP / AR balances and payments
    assert db.get_ap_open_balance(vendor_bill_doc_id=vb_id) > 0
    assert db.get_ar_open_balance(customer_invoice_id=inv_id) > 0
    db.insert_ap_payment(None, float(vb["grand_total"]), "bank", "vendor bill clear", vendor_bill_doc_id=vb_id)
    db.insert_ar_payment(None, float(inv["grand_total"]), "upi", "invoice collect", customer_invoice_id=inv_id)
    assert abs(db.get_ap_open_balance(vendor_bill_doc_id=vb_id)) < 0.01
    assert abs(db.get_ar_open_balance(customer_invoice_id=inv_id)) < 0.01

    # Inventory and history
    hist = db.get_document_history("product", alt_pid)
    assert hist["sales_orders"] and hist["customer_invoices"]
    stock_rows = db.list_stock_positions_v2()
    assert any(r["our_product_id"] == "LOW-1" and r["reorder_recommended"] for r in stock_rows)

    print("Business validation OK.")
    print("DB:", db.get_db_path())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
