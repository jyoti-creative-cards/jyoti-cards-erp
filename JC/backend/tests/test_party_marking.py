"""A product marking reaches the customer bill only when show to party is on."""

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.catalog_product import CatalogProduct
from app.models.product_marking import ProductMarking
from app.models.vendor import Vendor
from app.services.product_markings import active_party_flag, list_assignments, narration_for_party


def test_hidden_marking_stays_off_the_bill():
    text = narration_for_party("18 nov 1200 ayga", [("18 nov 1200 ayga", False)])
    assert text == ""


def test_shown_marking_is_on_the_bill():
    text = narration_for_party("", [("18 nov 1200 ayga", True)])
    assert text == "18 nov 1200 ayga"


def test_other_narration_stays_when_marking_is_hidden():
    text = narration_for_party("Handle with care · 18 nov 1200 ayga", [("18 nov 1200 ayga", False)])
    assert text == "Handle with care"


def test_on_product_is_not_the_same_as_show_to_customer():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    vendor = Vendor(business_name="V", phone="9000001056")
    db.add(vendor)
    db.flush()
    product = CatalogProduct(
        our_product_id="1056 PATRIKA", vendor_id=vendor.id, vendor_product_id="1056",
        buying_price=Decimal("1"), selling_price=Decimal("2"),
    )
    db.add(product)
    db.flush()
    db.add(ProductMarking(
        catalog_product_id=product.id, text="keep aside", show_to_party=False,
        starts_on=date(2026, 1, 1), ends_on=date(2099, 12, 31),
    ))
    db.commit()
    row = list_assignments(db, q="1056")[0]
    assert row["active"] is True
    assert row["show_to_party"] is False
    assert active_party_flag(db, product.id)["show_to_party"] is False
    db.close()
