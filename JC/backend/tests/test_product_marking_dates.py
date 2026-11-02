"""Dated markings show only inside their dates."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.catalog_product import CatalogProduct
from app.models.product_marking import ProductMarking
from app.models.vendor import Vendor
from app.services.biz_date import today_ist
from app.services.product_markings import (
    active_marking_text,
    assign_marking,
    delete_marking,
    update_marking,
)

_ = ProductMarking


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


def _product(db, sku="5401"):
    vendor = Vendor(business_name="V", phone="9000000001")
    db.add(vendor)
    db.flush()
    product = CatalogProduct(
        our_product_id=sku,
        vendor_id=vendor.id,
        vendor_product_id=sku,
        buying_price=Decimal("1"),
        selling_price=Decimal("2"),
        is_active=True,
    )
    db.add(product)
    db.flush()
    return product


def test_marking_shows_only_between_its_dates(db):
    product = _product(db)
    today = today_ist()
    assign_marking(db, [product.id], "Monday", today - timedelta(days=1), today + timedelta(days=1))
    db.flush()
    assert active_marking_text(db, product.id) == "Monday"
    assert product.marking == "Monday"

    row = db.query(ProductMarking).one()
    update_marking(db, row.id, text="Monday", starts_on=today - timedelta(days=10), ends_on=today - timedelta(days=1))
    db.flush()
    assert active_marking_text(db, product.id) is None
    assert product.marking is None


def test_two_markings_can_sit_on_one_product(db):
    product = _product(db)
    today = today_ist()
    assign_marking(db, [product.id], "Monday", today, date(2099, 12, 31))
    assign_marking(db, [product.id], "Hold", today, today)
    db.flush()
    assert product.marking == "Hold, Monday"


def test_delete_marking_takes_it_off_the_product(db):
    product = _product(db)
    today = today_ist()
    assign_marking(db, [product.id], "Monday", today, today)
    row = db.query(ProductMarking).one()
    delete_marking(db, row.id)
    db.flush()
    assert product.marking is None
    assert db.query(ProductMarking).count() == 0
