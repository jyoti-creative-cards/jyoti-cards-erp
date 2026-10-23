"""Daily stock summary counts a bill or an unbilled confirmed order, never both."""
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.customer_return import CustomerReturn, CustomerReturnLine
from app.models.stock import StockLedger, StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.services.reports_extra.stock_group_summary import stock_group_summary
from app.services.stock_summary_pdf import render_stock_summary_pdf, render_stock_summary_pdf_from

DAY = date(2026, 10, 19)
OTHER = date(2026, 10, 18)
WHEN = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)
OTHER_WHEN = datetime(2026, 10, 18, 6, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _world(db):
    vendor = Vendor(business_name="Myra Prints", phone="9990001111")
    db.add(vendor)
    db.flush()
    product = CatalogProduct(
        our_product_id="5215 PATRIKA",
        vendor_id=vendor.id,
        vendor_product_id="2259 RJ",
        buying_price=Decimal("4.40"),
        selling_price=Decimal("7.00"),
    )
    db.add(product)
    db.flush()
    customer = Customer(business_name="Atharv Cards", phone="9990002222", password_hash="x")
    db.add(customer)
    db.flush()
    return vendor, product, customer


def _order(db, customer, product, qty, billed, status, when, price="7.00"):
    order = CustomerOrder(customer_id=customer.id, bucket="open" if status == "open" else "billed", status=status)
    db.add(order)
    db.flush()
    placement = CustomerOrderPlacement(
        customer_order_id=order.id, status=status, placed_at=when, created_at=when,
    )
    db.add(placement)
    db.flush()
    line = CustomerOrderLine(
        placement_id=placement.id,
        catalog_product_id=product.id,
        our_product_id=product.our_product_id,
        quantity=qty,
        quantity_billed=billed,
        unit_price=Decimal(price),
        status="active",
        created_at=when,
    )
    db.add(line)
    db.flush()
    return placement


def _bill(db, customer, product, qty, total, day, when, number):
    bill = CustomerBill(
        customer_id=customer.id,
        bill_number=number,
        subtotal_inclusive=Decimal(total),
        discount_amount=0,
        taxable_value=Decimal(total),
        gst_amount=0,
        grand_total=Decimal(total),
        created_by_type="admin",
        created_by_name="Test",
        bill_date=day,
        created_at=when,
    )
    db.add(bill)
    db.flush()
    line = CustomerBillLine(
        bill_id=bill.id,
        catalog_product_id=product.id,
        our_product_id=product.our_product_id,
        quantity_shipped=qty,
        unit_price=(Decimal(total) / Decimal(qty)),
        line_total=Decimal(total),
        status="billed",
    )
    db.add(line)
    db.flush()
    return bill, line


def _ledger(db, product, delta, kind, when, reference_type=None, reference_id=None):
    db.add(StockLedger(
        catalog_product_id=product.id,
        entry_type=kind,
        quantity_delta=delta,
        balance_after=0,
        reference_type=reference_type,
        reference_id=reference_id,
        created_at=when,
    ))


def test_bill_and_unbilled_order_are_not_both_counted(db):
    vendor, product, customer = _world(db)
    receipt = StockReceipt(
        receipt_type="vendor_order",
        vendor_id=vendor.id,
        bill_status="pending_bill",
        received_by_type="admin",
        received_by_name="Test",
        received_at=WHEN,
        created_at=WHEN,
    )
    db.add(receipt)
    db.flush()
    db.add(StockReceiptLine(
        receipt_id=receipt.id,
        catalog_product_id=product.id,
        our_product_id=product.our_product_id,
        quantity_received=100,
        quantity_billed=0,
        billed_amount=0,
        buying_price=Decimal("4.40"),
    ))
    _ledger(db, product, 100, "received", WHEN, "stock_receipt", receipt.id)
    _order(db, customer, product, 20, 20, "billed", WHEN)
    _ledger(db, product, -20, "reserved", WHEN, "customer_placement", 1)
    bill, bill_line = _bill(db, customer, product, 20, "138.00", DAY, WHEN, "A1")
    _order(db, customer, product, 10, 0, "open", WHEN)
    _ledger(db, product, -10, "reserved", WHEN, "customer_placement", 2)
    _bill(db, customer, product, 5, "40.00", OTHER, OTHER_WHEN, "A0")
    _ledger(db, product, 50, "received", OTHER_WHEN, "stock_receipt", 999)
    ret = CustomerReturn(
        customer_id=customer.id,
        return_number="R1",
        calculated_amount=Decimal("13.80"),
        credit_amount=Decimal("13.80"),
        created_by_type="admin",
        created_by_name="Test",
        created_at=WHEN,
    )
    db.add(ret)
    db.flush()
    db.add(CustomerReturnLine(
        return_id=ret.id,
        bill_id=bill.id,
        bill_line_id=bill_line.id,
        catalog_product_id=product.id,
        our_product_id=product.our_product_id,
        quantity_returned=2,
        sold_unit_price=Decimal("6.90"),
        line_calculated=Decimal("13.80"),
    ))
    _ledger(db, product, 2, "customer_return", WHEN, "customer_return", ret.id)
    db.commit()

    report = stock_group_summary(db, DAY, DAY)
    assert report["period"] == "For 19-Oct-26"
    assert len(report["items"]) == 1
    row = report["items"][0]
    assert row["particular"] == "5215 PATRIKA (2259 RJ)"
    assert row["vendor_name"] == "Myra Prints"
    assert row["sales_count"] == 2
    assert row["in_qty"] == "100.00"
    assert row["in_rate"] == "4.40"
    assert row["in_value"] == "440.00"
    assert row["out_qty"] == "28.00"
    assert row["out_value"] == "194.20"
    assert row["out_rate"] == "6.94"
    # The 18 Oct receipt is still on hand at the end of 19 Oct. It is not an inward of the 19th.
    assert row["close_qty"] == "122.00"
    assert row["close_rate"] == "4.40"
    assert row["close_value"] == "536.80"
    assert report["totals"]["in_qty"] == "100.00"
    assert report["totals"]["out_qty"] == "28.00"
    assert report["totals"]["close_value"] == "536.80"


def test_pdf_carries_the_page_total_and_closes_on_the_last_page():
    items = []
    for i in range(3):
        items.append({
            "particular": f"ITEM {i}",
            "vendor_name": "Myra Prints",
            "sales_count": 1,
            "in_qty": "10.00",
            "in_rate": "2.00",
            "in_value": "20.00",
            "out_qty": "1.00",
            "out_rate": "5.00",
            "out_value": "5.00",
            "close_qty": "9.00",
            "close_rate": "2.00",
            "close_value": "18.00",
        })
    pdf = render_stock_summary_pdf_from({
        "period": "For 19-Oct-26",
        "printed_on": "19-Oct-26 at 20:08",
        "items": items,
        "totals": {
            "in_qty": "30.00",
            "in_value": "60.00",
            "out_qty": "3.00",
            "out_value": "15.00",
            "close_qty": "27.00",
            "close_value": "54.00",
        },
    }, page_rows=2)
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 2
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "Carried Over" in text
    assert "continued" in text
    assert "Brought Forward" in text
    assert "Grand Total" in text
    assert "Myra Prints" in text
    assert "Vendor" in text


def test_long_vendor_stays_on_one_line_and_the_sheet_fills():
    items = []
    for i in range(50):
        items.append({
            "particular": f"ITEM {i}",
            "vendor_name": "DEV PRINT & PACK PRIVATE LIMITED",
            "sales_count": 1,
            "in_qty": None,
            "in_rate": None,
            "in_value": None,
            "out_qty": "20.00",
            "out_rate": "5.00",
            "out_value": "100.00",
            "close_qty": "9.00",
            "close_rate": "2.00",
            "close_value": "18.00",
        })
    pdf = render_stock_summary_pdf_from({
        "period": "For 19-Oct-26",
        "printed_on": "19-Oct-26 at 20:08",
        "items": items,
        "totals": {
            "sales_count": 50,
            "in_qty": "0.00",
            "in_value": "0.00",
            "out_qty": "1000.00",
            "out_value": "5000.00",
            "close_qty": "450.00",
            "close_value": "900.00",
        },
    })
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) >= 2
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "DEV PRINT & PACK PRIVATE LIMITED" in text
    bottoms = []
    for page in reader.pages[:-1]:
        ys = []
        def visitor(text, cm, tm, fontDict, fontSize, ys=ys):
            if (text or "").strip():
                ys.append(cm[1] * tm[4] + cm[3] * tm[5] + cm[5])
        page.extract_text(visitor_text=visitor)
        bottoms.append(min(ys))
    assert max(bottoms) - min(bottoms) < 8
    assert max(bottoms) < 50


def test_one_day_pdf_names_the_item(db):
    vendor, product, customer = _world(db)
    _bill(db, customer, product, 4, "28.00", DAY, WHEN, "B1")
    _ledger(db, product, -4, "reserved", WHEN)
    db.commit()
    pdf = render_stock_summary_pdf(db, DAY, DAY, page_rows=10)
    text = "\n".join((page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages)
    assert "5215 PATRIKA (2259 RJ)" in text
    assert "Myra Prints" in text
    assert "Grand Total" in text
    assert "continued" not in text
