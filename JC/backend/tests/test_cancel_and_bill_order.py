"""Cancelled bills stay visible but do not inflate sales, and bill lines keep punch order."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.staff import Staff
from app.models.vendor import Vendor
from app.services.cancel_key import set_cancel_key, staff_for_key
from app.services.customer_bills.cancel import _drop_sale_from_orders
from app.services.customer_bills.read import get_process_lines
from app.services.passwords import hash_password
from app.services.report_parts.lists import list_sales
from app.services.reports_extra.stock_group_summary import stock_group_summary

DAY = date(2026, 10, 19)
WHEN = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)


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


def _party(db):
    vendor = Vendor(business_name="V", phone="9000000001")
    db.add(vendor)
    db.flush()
    customer = Customer(business_name="Atharv", phone="9000000002", password_hash="x")
    db.add(customer)
    db.flush()
    return vendor, customer


def _product(db, vendor, code, year):
    row = CatalogProduct(
        our_product_id=code,
        vendor_id=vendor.id,
        vendor_product_id=code,
        year_group=year,
        buying_price=Decimal("4"),
        selling_price=Decimal("8"),
    )
    db.add(row)
    db.flush()
    return row


def _bill(db, customer, product, number, cancelled=False):
    bill = CustomerBill(
        customer_id=customer.id,
        bill_number=number,
        subtotal_inclusive=Decimal("80"),
        discount_amount=0,
        taxable_value=Decimal("80"),
        gst_amount=0,
        grand_total=Decimal("80"),
        created_by_type="admin",
        created_by_name="Test",
        bill_date=DAY,
        created_at=WHEN,
        cancelled_at=WHEN if cancelled else None,
    )
    db.add(bill)
    db.flush()
    db.add(CustomerBillLine(
        bill_id=bill.id,
        catalog_product_id=product.id,
        our_product_id=product.our_product_id,
        quantity_shipped=10,
        unit_price=Decimal("8"),
        line_total=Decimal("80"),
        status="closed" if cancelled else "billed",
    ))
    db.flush()
    return bill


def test_cancelled_qty_leaves_the_order(db):
    vendor, customer = _party(db)
    product = _product(db, vendor, "C-ITEM", "2026")
    order = CustomerOrder(customer_id=customer.id, bucket="open", status="open")
    db.add(order)
    db.flush()
    placement = CustomerOrderPlacement(customer_order_id=order.id, status="open", placed_at=WHEN)
    db.add(placement)
    db.flush()
    line = CustomerOrderLine(
        placement_id=placement.id,
        catalog_product_id=product.id,
        our_product_id=product.our_product_id,
        quantity=10,
        quantity_billed=10,
        unit_price=Decimal("8"),
        status="active",
    )
    db.add(line)
    db.commit()
    _drop_sale_from_orders(db, customer.id, product.id, 10, None)
    db.flush()
    db.refresh(line)
    assert line.quantity_billed == 0
    assert line.quantity == 0
    assert line.status == "cancelled"


def test_bill_lines_stay_in_punch_order(db):
    vendor, customer = _party(db)
    later = _product(db, vendor, "A-FIRST", "2026")
    earlier = _product(db, vendor, "C-SECOND", "2026")
    db.add(CustomerOpenLine(
        customer_id=customer.id, catalog_product_id=earlier.id, our_product_id="C-SECOND",
        quantity_received=5, quantity_open=5, quantity_billed=0, unit_price=Decimal("8"), status="open",
    ))
    db.add(CustomerOpenLine(
        customer_id=customer.id, catalog_product_id=later.id, our_product_id="A-FIRST",
        quantity_received=5, quantity_open=5, quantity_billed=0, unit_price=Decimal("8"), status="open",
    ))
    db.commit()
    lines = get_process_lines(db, customer.id)["lines"]
    assert [row["our_product_id"] for row in lines] == ["C-SECOND", "A-FIRST"]


def test_sales_book_keeps_the_cancelled_number(db):
    vendor, customer = _party(db)
    product = _product(db, vendor, "P", "2026")
    _bill(db, customer, product, "A20")
    _bill(db, customer, product, "A22")
    _bill(db, customer, product, "A21", cancelled=True)
    db.commit()
    rows = list_sales(db, DAY, DAY)
    assert [row["doc_number"] for row in rows] == ["A20", "A21", "A22"]
    assert rows[1]["status"] == "cancelled"
    assert rows[0]["status"] == "open"


def test_stock_export_can_be_one_year(db):
    vendor, customer = _party(db)
    this_year = _product(db, vendor, "NOW", "2026")
    old = _product(db, vendor, "OLD", "2015-25")
    _bill(db, customer, this_year, "B1")
    _bill(db, customer, old, "B2")
    db.commit()
    report = stock_group_summary(db, DAY, DAY, year_group="2026")
    assert [row["particular"] for row in report["items"]] == ["NOW"]
    assert report["year_group"] == "2026"


def test_each_person_has_their_own_cancel_key(db):
    nikhil = Staff(name="Nikhil", phone="9000000101", password_hash=hash_password("0101"), permissions_json="[]")
    raj = Staff(name="Raj", phone="9000000103", password_hash=hash_password("0103"), permissions_json="[]")
    db.add_all([nikhil, raj])
    db.flush()
    set_cancel_key(db, nikhil, "aa")
    set_cancel_key(db, raj, "bb")
    db.commit()
    assert staff_for_key(db, "aa").name == "Nikhil"
    assert staff_for_key(db, "bb").name == "Raj"
    with pytest.raises(HTTPException) as bad:
        staff_for_key(db, "nope")
    assert bad.value.status_code == 403
    with pytest.raises(HTTPException) as dup:
        set_cancel_key(db, raj, "aa")
    assert dup.value.status_code == 409
