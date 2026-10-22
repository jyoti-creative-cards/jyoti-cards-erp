"""Phone books: cancelled bills stay out of sales, and cash is receipt minus payment minus expenses."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.accounts_payable import ApLedgerEntry
from app.models.accounts_receivable import ArLedgerEntry
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.expense import Expense
from app.models.vendor import Vendor
from app.services.biz_analyst import home

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


def test_home_figures_skip_a_cancelled_bill(db):
    customer = Customer(business_name="Atharv", phone="9000002222", password_hash="x")
    vendor = Vendor(business_name="Myra", phone="9000003333")
    db.add_all([customer, vendor])
    db.flush()
    db.add(CustomerBill(
        customer_id=customer.id, bill_number="A1", subtotal_inclusive=100, discount_amount=0,
        taxable_value=100, gst_amount=0, grand_total=100, created_by_type="admin",
        created_by_name="T", bill_date=DAY, created_at=WHEN,
    ))
    db.add(CustomerBill(
        customer_id=customer.id, bill_number="A2", subtotal_inclusive=40, discount_amount=0,
        taxable_value=40, gst_amount=0, grand_total=40, created_by_type="admin",
        created_by_name="T", bill_date=DAY, created_at=WHEN, cancelled_at=WHEN,
    ))
    db.add(ArLedgerEntry(
        customer_id=customer.id, entry_type="payment", amount=Decimal("-30"),
        description="Received", value_date=DAY, created_by_type="admin", created_by_name="T", created_at=WHEN,
    ))
    db.add(ApLedgerEntry(
        vendor_id=vendor.id, entry_type="payment", amount=Decimal("-12"),
        description="Paid", value_date=DAY, created_by_type="admin", created_by_name="T", created_at=WHEN,
    ))
    db.add(Expense(expense_date=DAY, category="Rent", amount=Decimal("5"), created_by_name="T", is_cash=True))
    db.commit()
    row = home(db, DAY, DAY)
    assert row["sales"] == "100.00"
    assert row["receipt"] == "30.00"
    assert row["payment"] == "12.00"
    assert row["expenses"] == "5.00"
    assert row["cash"] == "13.00"
    assert row["expense_heads"] == [{"name": "Rent", "amount": "5.00"}]
