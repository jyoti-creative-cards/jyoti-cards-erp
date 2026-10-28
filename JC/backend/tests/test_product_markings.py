"""Search, set, and rename product markings."""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.catalog_product import CatalogProduct
from app.models.vendor import Vendor
from app.services.product_markings import apply_marking, list_product_markings, rename_marking


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


def _product(db, our, vendor_item, marking=None, category="ENVELOPE", alias="Mill"):
    vendor = Vendor(business_name=f"Vendor {our}", phone=f"9{our[-6:]}", alias=alias)
    db.add(vendor)
    db.flush()
    row = CatalogProduct(
        our_product_id=our,
        vendor_id=vendor.id,
        vendor_product_id=vendor_item,
        category=category,
        buying_price=Decimal("1"),
        selling_price=Decimal("2"),
        marking=marking,
    )
    db.add(row)
    db.flush()
    return row


def test_search_and_rename_markings(db):
    fragile = _product(db, "PSC 01", "V-01", marking="Fragile", alias="Paper")
    plain = _product(db, "RPE 02", "V-02", marking=None, category="BOX")
    db.commit()

    marked = list_product_markings(db, q="", marked="marked")
    assert [item["our_product_id"] for item in marked["items"]] == ["PSC 01"]
    assert marked["markings"] == ["Fragile"]

    found = list_product_markings(db, q="Paper", marked="all")
    assert [item["id"] for item in found["items"]] == [fragile.id]

    blank = list_product_markings(db, q="BOX", marked="unmarked")
    assert [item["id"] for item in blank["items"]] == [plain.id]

    assert apply_marking(db, [plain.id], "Check quality") == 1
    db.refresh(plain)
    assert plain.marking == "Check quality"

    assert rename_marking(db, "Fragile", "Handle with care") == 1
    db.refresh(fragile)
    assert fragile.marking == "Handle with care"

    assert apply_marking(db, [plain.id], "  ") == 1
    db.refresh(plain)
    assert plain.marking is None
