"""Editing a placed vendor line must not 500 when the item has no buying price."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.catalog_product import CatalogProduct
from app.models.vendor import Vendor
from app.models.vendor_open_line import VendorOpenLine
from app.routers.vendor_orders.build_detail import create_placement, update_line
from app.schemas.vendor_order import PlacementCreate, VendorOrderLineIn, VendorOrderLineUpdate

AUTH = AuthContext(actor_type="admin", actor_id=1, actor_name="Admin")


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


def test_raising_placed_qty_without_a_buying_price(db):
    vendor = Vendor(business_name="Press", phone="9998887601")
    db.add(vendor)
    db.flush()
    prod = CatalogProduct(
        our_product_id="7556", vendor_id=vendor.id, vendor_product_id="VP7556",
        buying_price=None, selling_price=Decimal("5"),
    )
    db.add(prod)
    db.commit()

    detail = create_placement(
        PlacementCreate(vendor_id=vendor.id, lines=[VendorOrderLineIn(catalog_product_id=prod.id, quantity=2)]),
        db,
        AUTH,
    )
    line_id = detail.aggregated_lines[0].breakdown[0].line_id
    updated = update_line(line_id, VendorOrderLineUpdate(quantity=5), db, AUTH)
    assert updated.aggregated_lines[0].breakdown[0].quantity == 5
    open_row = db.query(VendorOpenLine).filter(VendorOpenLine.catalog_product_id == prod.id).one()
    assert open_row.quantity == 5
    assert open_row.buying_price == Decimal("0")
