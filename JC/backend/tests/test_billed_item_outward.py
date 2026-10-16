"""Items with a live bill show bill count, qty sold, rate, and stock left."""

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.stock import StockBalance
from app.models.vendor import Vendor
from app.services.reports_extended import billed_item_outward


def test_staff_is_not_blocked_by_permissions():
    auth = AuthContext(actor_type="staff", actor_id=1, actor_name="Raj", permissions=set())
    assert auth.has("catalog.write")
    assert auth.has("stickers.print")


def test_item_lookup_account_only_sees_photo_and_stock():
    from app.routers.items_lookup import _matches

    auth = AuthContext(actor_type="staff", actor_id=9, actor_name="anshul", permissions={"items.lookup"})
    assert auth.is_lookup_only()
    assert auth.has("items.lookup")
    assert not auth.has("catalog.read")
    assert not auth.has("stock.read")
    assert _matches("6734 BOX PATRIKA", "6734")
    assert not _matches("67340 BOX", "6734")
    assert not _matches("16734 CARD", "6734")


def test_billed_items_count_bills_qty_rate_and_closing():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        vendor = Vendor(business_name="Mill", phone="9000000091")
        db.add(vendor)
        db.flush()
        product = CatalogProduct(
            our_product_id="RX 07 ENVELOPE",
            vendor_id=vendor.id,
            vendor_product_id="RX07",
            buying_price=Decimal("2.00"),
            selling_price=Decimal("3.00"),
        )
        unsold = CatalogProduct(
            our_product_id="NEVER SOLD",
            vendor_id=vendor.id,
            vendor_product_id="NS",
            buying_price=Decimal("1.00"),
            selling_price=Decimal("1.00"),
        )
        db.add_all([product, unsold])
        db.flush()
        db.add(StockBalance(catalog_product_id=product.id, quantity_on_hand=500))
        customer = Customer(business_name="Press", phone="9000000092", password_hash="x")
        db.add(customer)
        db.flush()
        bill = CustomerBill(
            customer_id=customer.id,
            bill_number="A1",
            subtotal_inclusive=Decimal("300"),
            discount_amount=Decimal("0"),
            taxable_value=Decimal("300"),
            gst_amount=Decimal("0"),
            grand_total=Decimal("300"),
            created_by_type="staff",
            created_by_name="Raj",
            bill_date=date(2026, 10, 1),
        )
        cancelled = CustomerBill(
            customer_id=customer.id,
            bill_number="A2",
            subtotal_inclusive=Decimal("100"),
            discount_amount=Decimal("0"),
            taxable_value=Decimal("100"),
            gst_amount=Decimal("0"),
            grand_total=Decimal("100"),
            created_by_type="staff",
            created_by_name="Raj",
            bill_date=date(2026, 10, 2),
        )
        db.add_all([bill, cancelled])
        db.flush()
        cancelled.cancelled_at = bill.created_at
        db.add(CustomerBillLine(
            bill_id=bill.id, catalog_product_id=product.id, our_product_id="RX 07 ENVELOPE",
            quantity_shipped=100, unit_price=Decimal("3.00"), line_total=Decimal("300.00"),
        ))
        db.add(CustomerBillLine(
            bill_id=cancelled.id, catalog_product_id=product.id, our_product_id="RX 07 ENVELOPE",
            quantity_shipped=40, unit_price=Decimal("3.00"), line_total=Decimal("120.00"),
        ))
        db.commit()
        rows = billed_item_outward(db, None, None)["items"]
        assert len(rows) == 1
        row = rows[0]
        assert row["label"] == "RX 07 ENVELOPE"
        assert row["date"] == "2026-10-01"
        assert row["bills"] == 1
        assert row["out_qty"] == 100
        assert row["rate"] == "3.00"
        assert row["closing_qty"] == 500
        assert row["closing_value"] == "1000.00"
    finally:
        db.close()
        engine.dispose()
