"""A5 sticker stores a Hindi name and city, and leaves the phone as stored."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.city import City
from app.models.customer import Customer
from app.models.sticker_label import StickerLabel
from app.routers.customers.listing import get_customer_sticker
from app.services.sticker_hindi import hindi_city, hindi_name

AUTH = AuthContext(actor_type="admin", actor_id=1, actor_name="Test Admin")


def test_known_parties_and_cities_are_hindi():
    assert hindi_name("Payal Computer") == "पायल कम्प्यूटर"
    assert hindi_name("Khandelwal Stores") == "खंडेलवाल स्टोर्स"
    assert hindi_name("Maheshwari Graphics") == "माहेश्वरी ग्राफिक्स"
    assert hindi_name("Shri Natraj Studio") == "श्री नटराज स्टूडियो"
    assert hindi_city("Indore") == "इंदौर"
    assert hindi_city("Mandsaur") == "मंदसौर"
    assert hindi_city("Anjad") == "अंजाड़"
    assert hindi_city("Ajmer") == "अजमेर"
    assert hindi_city("Ujjain") == "उज्जैन"
    assert "प" in hindi_name("Payal Computer")
    assert hindi_name("Shop 12").endswith("12")


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


def test_sticker_row_stores_hindi_and_keeps_phone(db):
    city = City(name="Mandsaur")
    db.add(city)
    db.flush()
    customer = Customer(
        business_name="Payal Computer",
        phone="9876543210",
        password_hash="x",
        city_id=city.id,
    )
    db.add(customer)
    db.commit()

    out = get_customer_sticker(customer.id, db=db, auth=AUTH)
    assert out["name_hi"] == "पायल कम्प्यूटर"
    assert out["city_hi"] == "मंदसौर"
    assert out["phone"] == "9876543210"
    assert db.query(StickerLabel).count() == 1

    again = get_customer_sticker(customer.id, db=db, auth=AUTH)
    assert again["name_hi"] == out["name_hi"]
    assert db.query(StickerLabel).count() == 1

    customer.business_name = "Shri Natraj Studio"
    db.commit()
    changed = get_customer_sticker(customer.id, db=db, auth=AUTH)
    assert changed["name_hi"] == "श्री नटराज स्टूडियो"
    assert changed["city_hi"] == "मंदसौर"
    assert changed["phone"] == "9876543210"
