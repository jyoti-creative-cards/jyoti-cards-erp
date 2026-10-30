"""A new category name stays in the product list before any product uses it."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.catalog_product import CatalogProduct
from app.models.saved_category import SavedCategory
from app.models.vendor import Vendor
from app.services.catalog_categories import add_category_name, list_category_names


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_existing_product_categories_and_a_new_name():
    db = _db()
    vendor = Vendor(business_name="Paper Co", phone="9000000001", alias="Paper")
    db.add(vendor)
    db.flush()
    db.add(CatalogProduct(
        our_product_id="A1",
        vendor_id=vendor.id,
        vendor_product_id="V1",
        category="ALBUM NO. 01",
        second_category="BOX NO. 09",
        buying_price=Decimal("1"),
        selling_price=Decimal("2"),
    ))
    db.commit()

    assert list_category_names(db) == ["ALBUM NO. 01", "BOX NO. 09"]

    name, created = add_category_name(db, "  GIFT SET  ")
    db.commit()
    assert created is True
    assert name == "GIFT SET"
    assert list_category_names(db) == ["ALBUM NO. 01", "BOX NO. 09", "GIFT SET"]

    again, created_again = add_category_name(db, "album no. 01")
    assert created_again is False
    assert again == "ALBUM NO. 01"
    assert db.query(SavedCategory).count() == 1
    db.close()
