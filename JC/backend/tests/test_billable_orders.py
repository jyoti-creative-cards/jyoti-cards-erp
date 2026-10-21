"""The bill screen lists only orders that still have quantity to bill, with their marking."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_order import CustomerOpenLine
from app.models.stock import StockBalance
from app.models.vendor import Vendor
from app.services.customer_bills.read import billable_orders
from app.services.customer_order_flow import confirm_received_order, create_received_placement


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _setup(db):
    vendor = Vendor(business_name="V1", phone="9998887771")
    db.add(vendor)
    db.flush()
    prod = CatalogProduct(
        our_product_id="P1", vendor_id=vendor.id, vendor_product_id="VP1",
        buying_price=Decimal("10"), selling_price=Decimal("20"),
    )
    db.add(prod)
    db.flush()
    db.add(StockBalance(catalog_product_id=prod.id, quantity_on_hand=100))
    customer = Customer(business_name="Atharv Cards", phone="9998887772", password_hash="x")
    db.add(customer)
    db.flush()
    return customer, prod


def _place(db, customer, prod, qty, when, note=None):
    return create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": qty}],
        customer_notes=note,
        placed_on=when,
        allow_negative_stock=True,
    )


def test_unbilled_orders_keep_their_marking(db):
    customer, prod = _setup(db)
    older = _place(db, customer, prod, 10, date.today() - timedelta(days=2), "Do not bill. Reserve only.")
    newer = _place(db, customer, prod, 4, date.today() - timedelta(days=1))
    confirm_received_order(db, customer.id)
    rows = billable_orders(db, customer.id)
    assert [row["placement_id"] for row in rows] == [older.id, newer.id]
    assert rows[0]["customer_notes"] == "Do not bill. Reserve only."
    assert rows[0]["lines"][0]["quantity"] == 10
    assert rows[1]["lines"][0]["quantity"] == 4


def test_already_billed_orders_are_left_off_the_bill_list(db):
    """A past bill reduced the open tally but never marked the old order line billed."""
    customer, prod = _setup(db)
    older = _place(db, customer, prod, 10, date.today() - timedelta(days=3))
    hold = _place(db, customer, prod, 6, date.today() - timedelta(days=2), "Bill after 5 days. Not home.")
    current = _place(db, customer, prod, 4, date.today() - timedelta(days=1))
    confirm_received_order(db, customer.id)
    open_row = db.query(CustomerOpenLine).filter(CustomerOpenLine.customer_id == customer.id).one()
    open_row.quantity_billed = 10
    open_row.quantity_open = 10
    db.flush()

    rows = billable_orders(db, customer.id)
    assert [row["placement_id"] for row in rows] == [hold.id, current.id]
    assert rows[0]["customer_notes"] == "Bill after 5 days. Not home."
    assert older.id not in {row["placement_id"] for row in rows}
    assert sum(ln["quantity"] for row in rows for ln in row["lines"]) == 10
