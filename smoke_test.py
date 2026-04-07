import os

from db.database import DB_PATH, SessionLocal, init_db
from db.models import PurchaseOrderStatus, SalesStatus, WhatsAppLog
from services.customers import create_customer
from services.discounts import create_discount_rule
from services.inventory import get_product_stock
from services.payments import record_customer_payment, record_vendor_payment
from services.products import create_product
from services.purchases import add_vendor_bill, create_purchase_order, receive_purchase_order, run_three_way_match
from services.sales import create_sales_order, create_sales_order_from_names, update_sales_status
from services.vendors import create_vendor


def reset_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


def main():
    reset_db()
    init_db()
    db = SessionLocal()
    try:
        vendor = create_vendor(db, name="Test Vendor", phone="9999999999", gst_percent=18, gst_number="22AAAAA0000A1Z5", default_shipment_mode="road", transporter_name="FastTrans", transporter_contact="9000000000")
        print("vendor_ok", vendor.id)

        product = create_product(db, name="Sugar", sku="SUG-001", category="Grocery", vendor_id=vendor.id, purchase_price=40, selling_price=50, min_stock_level=10, reorder_level=20)
        print("product_ok", product.id)

        customer = create_customer(db, name="Retail Mart", phone="8888888888", whatsapp_phone="8888888888", customer_type="retailer", payment_mode="credit", credit_limit=5000, default_discount_percent=5)
        print("customer_ok", customer.id)

        create_discount_rule(db, name="Sugar Retail Discount", customer_id=customer.id, product_id=product.id, discount_percent=10, active=True)
        print("discount_ok")

        po = create_purchase_order(db, vendor_id=vendor.id, items=[{"product_id": product.id, "quantity": 100, "unit_price": 40, "gst_percent": 18}], shipment_mode="road", transport_name="FastTrans", transport_contact="9000000000", notes="Initial stock inward")
        assert po.status == PurchaseOrderStatus.CREATED
        stock_before_receipt = get_product_stock(db, product.id)
        assert stock_before_receipt.quantity_available == 0
        print("po_created_ok", po.id, stock_before_receipt.quantity_available)

        receive_purchase_order(db, po.id, receipt_number="GRN-1")
        stock_after_receipt = get_product_stock(db, product.id)
        assert stock_after_receipt.quantity_available == 100
        print("po_receive_ok", po.id, stock_after_receipt.quantity_available)

        add_vendor_bill(db, po.id, "BILL-1", po.order_date, po.total_amount, po.gst_amount, "")
        match = run_three_way_match(db, po.id)
        print("match_ok", match.status.value)

        so = create_sales_order(db, customer_id=customer.id, items=[{"product_id": product.id, "quantity": 25, "unit_price": 50}], notes="Retail sale", discount_percent=5)
        stock_after_so = get_product_stock(db, product.id)
        assert stock_after_so.quantity_available == 75
        print("manual_so_ok", so.id, stock_after_so.quantity_available)

        wa_so = create_sales_order_from_names(db, "8888888888", [{"name": "Sugar", "quantity": 5}], notes="WhatsApp order")
        stock_after_wa_so = get_product_stock(db, product.id)
        assert stock_after_wa_so.quantity_available == 70
        print("whatsapp_so_ok", wa_so.id, stock_after_wa_so.quantity_available)

        update_sales_status(db, wa_so.id, SalesStatus.DISPATCHED)
        print("dispatch_ok")

        customer_payment = record_customer_payment(db, customer.id, 500, "UPI-001", "Part payment")
        vendor_payment = record_vendor_payment(db, vendor.id, 1000, "BANK-001", "Vendor payment")
        print("payment_ok", customer_payment.id, vendor_payment.id)

        db.refresh(customer)
        assert customer.outstanding_balance > 0
        print("customer_outstanding_ok", round(customer.outstanding_balance, 2))

        outbound_logs = db.query(WhatsAppLog).count()
        assert outbound_logs > 0
        print("whatsapp_logs_ok", outbound_logs)

        print("smoke_test_passed")
    finally:
        db.close()


if __name__ == "__main__":
    main()
