"""A voided portal order must not collect the next order the dealer places."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.customer import Customer
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.services.customer_selling.confirm import get_open_unbilled_placement

WHEN = datetime(2026, 11, 27, 8, 20, tzinfo=timezone.utc)


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


def test_voided_placement_is_not_reused_for_the_next_portal_add(db):
    customer = Customer(business_name="Jyoti", phone="9000000099", password_hash="x")
    db.add(customer)
    db.flush()
    order = CustomerOrder(customer_id=customer.id, bucket="received", status="received", is_open=True)
    db.add(order)
    db.flush()
    placement = CustomerOrderPlacement(
        customer_order_id=order.id,
        status="received",
        placed_at=WHEN,
        order_source="app",
        deleted_at=WHEN,
    )
    db.add(placement)
    db.flush()
    db.add(CustomerOrderLine(
        placement_id=placement.id,
        catalog_product_id=1,
        our_product_id="7520 PATRIKA",
        quantity=300,
        quantity_billed=0,
        unit_price=1,
        status="active",
    ))
    db.commit()

    assert get_open_unbilled_placement(db, customer.id) is None
