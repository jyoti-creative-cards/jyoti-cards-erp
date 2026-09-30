"""Stock-ledger voucher fields, sales/receipt books, and order source."""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.accounts_receivable import ArLedgerEntry
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.stock import StockBalance, StockLedger, StockReceipt
from app.models.vendor import Vendor
from app.services.customer_order_flow import create_received_placement
from app.services.doc_gen import customer_order_source_line
from app.services.reports import daybook, list_payments, list_sales
from app.services.reports_extended import stock_wise
from app.services.stock_receipt import annotate_stock_ledger


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_stock_ledger_carries_bill_and_party():
    db = _db()
    vendor = Vendor(business_name="Paper House", phone="9000000001")
    db.add(vendor)
    db.flush()
    prod = CatalogProduct(
        our_product_id="5151", vendor_id=vendor.id, vendor_product_id="V5151",
        buying_price=Decimal("10"), selling_price=Decimal("20"), category="ALBUM",
    )
    db.add(prod)
    db.flush()
    db.add(StockBalance(catalog_product_id=prod.id, quantity_on_hand=50))
    customer = Customer(business_name="Sharma Cards", phone="9000000002", password_hash="x")
    db.add(customer)
    db.flush()
    bill = CustomerBill(
        customer_id=customer.id, bill_number="JC-100",
        subtotal_inclusive=Decimal("200"), discount_amount=Decimal("0"),
        taxable_value=Decimal("200"), gst_amount=Decimal("0"), grand_total=Decimal("200"),
        created_by_type="admin", created_by_name="Admin", bill_date=date.today(),
    )
    db.add(bill)
    db.flush()
    db.add(CustomerBillLine(
        bill_id=bill.id, catalog_product_id=prod.id, our_product_id="5151",
        quantity_shipped=10, unit_price=Decimal("20"), line_total=Decimal("200"),
    ))
    receipt = StockReceipt(
        vendor_id=vendor.id, receipt_type="vendor_order", bill_number="VB-9",
        order_receipt_number="OR-9", received_by_type="admin", received_by_name="Admin",
        bill_status="billed",
    )
    db.add(receipt)
    db.flush()
    db.add(StockLedger(
        catalog_product_id=prod.id, entry_type="sold", quantity_delta=-10, balance_after=40,
        reference_type="customer_bill", reference_id=bill.id, party="Sharma Cards",
        notes="Offline bill JC-100",
    ))
    db.add(StockLedger(
        catalog_product_id=prod.id, entry_type="received", quantity_delta=50, balance_after=50,
        reference_type="stock_receipt", reference_id=receipt.id, party="Paper House",
    ))
    db.flush()
    rows = annotate_stock_ledger(db, db.query(StockLedger).order_by(StockLedger.id.asc()).all())
    sale, recv = rows
    assert sale["party"] == "Sharma Cards"
    assert sale["bill_number"] == "JC-100"
    assert sale["voucher_kind"] == "customer_bill"
    assert sale["voucher_id"] == bill.id
    assert sale["quantity_delta"] == -10
    assert recv["bill_number"] == "VB-9"
    assert recv["voucher_kind"] == "stock_receipt"
    db.close()


def test_sales_receipt_and_daybook_totals():
    db = _db()
    customer = Customer(business_name="Sharma Cards", phone="9000000003", password_hash="x")
    db.add(customer)
    db.flush()
    today = date.today()
    bill = CustomerBill(
        customer_id=customer.id, bill_number="JC-200",
        subtotal_inclusive=Decimal("500"), discount_amount=Decimal("0"),
        taxable_value=Decimal("500"), gst_amount=Decimal("0"), grand_total=Decimal("500"),
        created_by_type="admin", created_by_name="Admin", bill_date=today,
        created_at=datetime.now(timezone.utc),
    )
    db.add(bill)
    db.flush()
    db.add(ArLedgerEntry(
        customer_id=customer.id, entry_type="payment", amount=Decimal("-150"),
        payment_ref="CASH-1", description="Payment CASH-1", value_date=today,
        created_by_type="staff", created_by_name="Ravi",
        created_at=datetime.now(timezone.utc),
    ))
    db.commit()
    sales = list_sales(db, today, today)
    assert len(sales) == 1
    assert sales[0]["doc_number"] == "JC-200"
    assert sales[0]["amount"] == "500.00"
    payments = [p for p in list_payments(db, today, today) if p["direction"] == "in"]
    assert len(payments) == 1
    assert payments[0]["amount"] == "150.00"
    book = daybook(db, today)
    assert book["totals"]["sales_count"] >= 1
    assert any(e["kind"] == "sales" and e["ref_id"] == bill.id for e in book["entries"])
    db.close()


def test_offline_order_stores_who_placed_it():
    db = _db()
    vendor = Vendor(business_name="Paper House", phone="9000000004")
    db.add(vendor)
    db.flush()
    prod = CatalogProduct(
        our_product_id="5151", vendor_id=vendor.id, vendor_product_id="V5151",
        buying_price=Decimal("10"), selling_price=Decimal("20"),
    )
    db.add(prod)
    db.flush()
    db.add(StockBalance(catalog_product_id=prod.id, quantity_on_hand=100))
    customer = Customer(business_name="Sharma Cards", phone="9000000005", password_hash="x")
    db.add(customer)
    db.flush()
    placement = create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 50}],
        order_source="offline", placed_by_name="Ravi",
    )
    db.flush()
    assert placement.order_source == "offline"
    assert placement.placed_by_name == "Ravi"
    assert customer_order_source_line(db, placement) == "Offline order by Ravi"
    db.close()


def test_stock_wise_opening_in_and_out():
    db = _db()
    vendor = Vendor(business_name="Paper House", phone="9000000006")
    db.add(vendor)
    db.flush()
    prod = CatalogProduct(
        our_product_id="5151", vendor_id=vendor.id, vendor_product_id="V5151",
        buying_price=Decimal("10"), selling_price=Decimal("20"), category="ALBUM",
    )
    idle = CatalogProduct(
        our_product_id="9999", vendor_id=vendor.id, vendor_product_id="V9999",
        buying_price=Decimal("1"), selling_price=Decimal("2"),
    )
    db.add_all([prod, idle])
    db.flush()
    day = date(2026, 9, 30)
    db.add(StockLedger(
        catalog_product_id=prod.id, entry_type="received", quantity_delta=40, balance_after=40,
        created_at=datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc),
    ))
    db.add(StockLedger(
        catalog_product_id=prod.id, entry_type="received", quantity_delta=10, balance_after=50,
        created_at=datetime(2026, 9, 30, 4, 0, tzinfo=timezone.utc),
    ))
    db.add(StockLedger(
        catalog_product_id=prod.id, entry_type="sold", quantity_delta=-5, balance_after=45,
        created_at=datetime(2026, 9, 30, 6, 0, tzinfo=timezone.utc),
    ))
    db.add(StockLedger(
        catalog_product_id=prod.id, entry_type="received", quantity_delta=100, balance_after=145,
        created_at=datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc),
    ))
    db.commit()
    data = stock_wise(db, day, day)
    assert data["totals"]["sku_count"] == 1
    row = data["items"][0]
    assert row["label"] == "5151"
    assert row["opening"] == 40
    assert row["inward"] == 10
    assert row["outward"] == 5
    assert row["closing"] == 45
    db.close()
