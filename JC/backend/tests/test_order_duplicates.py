"""Same party and same day warns on a shared item or the same total."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.customer import Customer
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.services.order_duplicates import same_day_order_clashes

DAY = date(2026, 10, 25)
WHEN = datetime(2026, 10, 25, 6, 30, tzinfo=timezone.utc)


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


def _book(db, customer_id, product_id, qty, price, name):
    order = CustomerOrder(customer_id=customer_id, bucket="open", status="open", is_open=True)
    db.add(order)
    db.flush()
    placement = CustomerOrderPlacement(
        customer_order_id=order.id, status="open", placed_at=WHEN, order_source="offline",
    )
    db.add(placement)
    db.flush()
    db.add(CustomerOrderLine(
        placement_id=placement.id, catalog_product_id=product_id, our_product_id=name,
        quantity=qty, unit_price=Decimal(price), status="active",
    ))
    db.commit()
    return placement


def test_same_item_or_same_amount_on_the_same_day_is_a_clash(db):
    party = Customer(business_name="Twice", phone="9100001111", password_hash="x")
    db.add(party)
    db.flush()
    _book(db, party.id, 11, 2, "50.00", "9405")

    same_item = same_day_order_clashes(
        db, customer_id=party.id, placed_on=DAY,
        lines=[{"catalog_product_id": 11, "quantity": 1, "unit_price": "10.00"}],
    )
    assert len(same_item) == 1
    assert same_item[0]["same_items"] == ["9405"]
    assert same_item[0]["same_amount"] is False

    same_total = same_day_order_clashes(
        db, customer_id=party.id, placed_on=DAY,
        lines=[{"catalog_product_id": 99, "quantity": 1, "unit_price": "100.00"}],
    )
    assert same_total[0]["same_amount"] is True
    assert same_total[0]["same_items"] == []

    other_day = same_day_order_clashes(
        db, customer_id=party.id, placed_on=date(2026, 10, 24),
        lines=[{"catalog_product_id": 11, "quantity": 2, "unit_price": "50.00"}],
    )
    assert other_day == []
