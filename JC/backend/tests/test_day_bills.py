"""Day bills report keys off bill_date and does not touch documents."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.city import City
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.services.reports import list_day_bills


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


def test_day_bills_follow_bill_date_and_skip_cancelled_in_the_total(db):
    city = City(name="Ajmer")
    db.add(city)
    db.flush()
    customer = Customer(
        business_name="Maheshwari Graphics",
        phone="8111111111",
        password_hash="x",
        city_id=city.id,
        party_number=42,
    )
    db.add(customer)
    db.flush()
    kept = CustomerBill(
        customer_id=customer.id,
        bill_number="A2",
        bill_date=date(2026, 8, 13),
        subtotal_inclusive=Decimal("100"),
        grand_total=Decimal("100"),
        created_by_type="admin",
        created_by_name="Test",
        created_at=datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc),
    )
    cancelled = CustomerBill(
        customer_id=customer.id,
        bill_number="A3",
        bill_date=date(2026, 8, 13),
        subtotal_inclusive=Decimal("50"),
        grand_total=Decimal("50"),
        cancelled_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
        created_by_type="admin",
        created_by_name="Test",
    )
    other_day = CustomerBill(
        customer_id=customer.id,
        bill_number="A4",
        bill_date=date(2026, 8, 24),
        subtotal_inclusive=Decimal("80"),
        grand_total=Decimal("80"),
        created_by_type="admin",
        created_by_name="Test",
    )
    db.add_all([kept, cancelled, other_day])
    db.commit()

    report = list_day_bills(db, date(2026, 8, 13))
    assert report["count"] == 1
    assert report["cancelled_count"] == 1
    assert report["amount_total"] == "100.00"
    numbers = [row["doc_number"] for row in report["items"]]
    assert numbers == ["A2", "A3"]
    assert report["items"][0]["city_name"] == "Ajmer"
    assert report["items"][0]["party_number"] == 42
    assert "document" not in report["items"][0]
