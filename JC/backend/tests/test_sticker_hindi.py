"""A5 sticker stores a Hindi name and city, and leaves the phone as stored."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.city import City
from app.models.customer import Customer
from app.models.sticker_label import StickerLabel
from app.models.sticker_print import StickerPrint
from app.routers.customers.listing import get_customer_sticker, list_customer_sticker_prints, post_customer_sticker_print
from app.services.sticker_hindi import hindi_city, hindi_name
from app.services.sticker_labels import english_print_stamp

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


def test_print_stamp_is_english():
    stamp = english_print_stamp(datetime(2026, 10, 8, 8, 17, tzinfo=timezone.utc))
    assert stamp == "8 Oct 2026, 1:47 pm"
    assert "अ" not in stamp


def test_print_is_recorded_with_english_time(db):
    city = City(name="Anjad")
    db.add(city)
    db.flush()
    customer = Customer(
        business_name="Shri Natraj Studio",
        phone="9811111111",
        password_hash="x",
        city_id=city.id,
        party_number=6004,
    )
    db.add(customer)
    db.commit()

    saved = post_customer_sticker_print(customer.id, db=db, auth=AUTH)
    assert saved["name_hi"] == "श्री नटराज स्टूडियो"
    assert saved["city_hi"] == "अंजाड़"
    assert saved["phone"] == "9811111111"
    assert saved["printed_label"].endswith("am") or saved["printed_label"].endswith("pm")
    assert "Oct" in saved["printed_label"] or any(m in saved["printed_label"] for m in (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Nov", "Dec",
    ))
    assert db.query(StickerPrint).count() == 1

    post_customer_sticker_print(customer.id, db=db, auth=AUTH)
    rows = list_customer_sticker_prints(q="6004", db=db, auth=AUTH)
    assert len(rows) == 2
    assert rows[0]["party_number"] == 6004
    assert rows[0]["business_name"] == "Shri Natraj Studio"
