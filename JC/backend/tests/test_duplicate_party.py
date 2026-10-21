"""A second party with the same name in the same city is rejected."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.city import City
from app.models.customer import Customer
from app.routers.customers.writing import _assert_unique_party


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


def test_same_name_and_city_is_rejected(db):
    city = City(name="Khargone")
    db.add(city)
    db.flush()
    db.add(Customer(business_name="Smruti Flex and Printers", phone="9000000001", password_hash="x", city_id=city.id))
    db.flush()
    with pytest.raises(HTTPException) as caught:
        _assert_unique_party(db, "  smruti   flex and printers ", city.id)
    assert caught.value.status_code == 409


def test_same_name_in_another_city_is_allowed(db):
    a = City(name="Khargone")
    b = City(name="Indore")
    db.add_all([a, b])
    db.flush()
    db.add(Customer(business_name="Smruti Flex and Printers", phone="9000000001", password_hash="x", city_id=a.id))
    db.flush()
    _assert_unique_party(db, "Smruti Flex and Printers", b.id)
