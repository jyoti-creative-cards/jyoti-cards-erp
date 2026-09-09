"""Regression test: the bill-review screen's process-context endpoint must surface the
customer's city (requested alongside customer name/bill number/date on that screen)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.city import City
from app.models.customer import Customer
from app.routers.customer_orders import get_process_context

AUTH = AuthContext(actor_type="admin", actor_id=1, actor_name="Test Admin")


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


def test_process_context_includes_city_name(db):
    city = City(name="Indore")
    db.add(city)
    db.flush()
    customer = Customer(business_name="Alpha Traders", phone="9000000009", password_hash="x", city_id=city.id)
    db.add(customer)
    db.commit()

    out = get_process_context(customer.id, db=db, auth=AUTH)
    assert out.city_name == "Indore"


def test_process_context_city_name_none_when_no_city(db):
    customer = Customer(business_name="Beta Traders", phone="9000000010", password_hash="x")
    db.add(customer)
    db.commit()

    out = get_process_context(customer.id, db=db, auth=AUTH)
    assert out.city_name is None
