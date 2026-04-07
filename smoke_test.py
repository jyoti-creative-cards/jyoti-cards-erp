import os

from db.database import DB_PATH, init_db, SessionLocal
from services.customers import create_customer
from services.inventory import get_product_stock
from services.payments import record_customer_payment, record_vendor_payment
from services.products import create_product
from services.purchases import create_purchase_order
from services.sales import create_sales_order
from services.vendors import create_vendor


def reset_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


def main():
    reset_db()
    init_db()
    db = SessionLocal()

    try:
        vendor = create_vendor(
            db,
            name="Test Vendor",
            phone="9999999999",
            address="Vendor Street",
            credit_terms="30 days",
        )
        print("vendor_ok", vendor.id)

        product = create_product(
            db,
            name="Sugar",
            sku="SUG-001",
            category="Grocery",
            vendor_id=vendor.id,
            purchase_price=40,
            selling_price=50,
            unit="kg",
            min_stock_level=10,
        )
        print("product_ok", product.id)

        customer = create_customer(
            db,
            name="Retail Mart",
            phone="8888888888",
            address="Market Road",
            customer_type="retailer",
            payment_mode="credit",
            credit_limit=5000,
        )
        print("customer_ok", customer.id)

        po = create_purchase_order(
            db,
            vendor_id=vendor.id,
            items=[{"product_id": product.id, "quantity": 100, "unit_price": 40}],
            notes="Initial stock inward",
        )
        stock_after_po = get_product_stock(db, product.id)
        assert stock_after_po.quantity_available == 100
        print("po_ok", po.id, stock_after_po.quantity_available)

        so = create_sales_order(
            db,
            customer_id=customer.id,
            items=[{"product_id": product.id, "quantity": 25, "unit_price": 50}],
            notes="Retail sale",
        )
        stock_after_so = get_product_stock(db, product.id)
        assert stock_after_so.quantity_available == 75
        print("so_ok", so.id, stock_after_so.quantity_available)

        customer_payment = record_customer_payment(db, customer.id, 500, "UPI-001", "Part payment")
        vendor_payment = record_vendor_payment(db, vendor.id, 1000, "BANK-001", "Vendor payment")
        print("payment_ok", customer_payment.id, vendor_payment.id)

        db.refresh(customer)
        assert customer.outstanding_balance == 750
        print("customer_outstanding_ok", customer.outstanding_balance)

        print("smoke_test_passed")
    finally:
        db.close()


if __name__ == "__main__":
    main()
