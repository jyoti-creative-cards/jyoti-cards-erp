"""Add-on stock tracking: receive/adjust via API-level service calls, and auto
deduct/restore when linked products are reserved/restored on customer orders."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.addon_product import AddonProduct
from app.models.catalog_addon_link import CatalogAddonLink
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.expense import Expense
from app.models.stock import StockBalance
from app.models.vendor import Vendor
from app.services.addon_stock import add_addon_stock, deduct_addons_for_product
from app.services.customer_order_flow import create_received_placement, cancel_customer_placement

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


def _setup(db, addon_qty: int = 100, link_qty: int = 2):
    vendor = Vendor(business_name="Card Vendor", phone="9998887771")
    addon_vendor = Vendor(business_name="Sticker Vendor", phone="9998887773")
    db.add_all([vendor, addon_vendor])
    db.flush()
    prod = CatalogProduct(
        our_product_id="CARD1", vendor_id=vendor.id, vendor_product_id="VCARD1",
        buying_price=Decimal("10"), selling_price=Decimal("20"),
    )
    db.add(prod)
    db.flush()
    db.add(StockBalance(catalog_product_id=prod.id, quantity_on_hand=1000))
    addon = AddonProduct(
        our_product_id="STICK1", vendor_id=addon_vendor.id, vendor_product_id="VSTICK1",
        unit="pc", buying_price=Decimal("2"), quantity_on_hand=addon_qty,
    )
    db.add(addon)
    db.flush()
    db.add(CatalogAddonLink(catalog_product_id=prod.id, addon_product_id=addon.id, quantity=link_qty))
    customer = Customer(business_name="Cust", phone="9998887772", password_hash="x")
    db.add(customer)
    db.flush()
    db.commit()
    return customer, prod, addon


def test_receive_stock_increases_quantity(db):
    _, _, addon = _setup(db, addon_qty=10)
    add_addon_stock(db, addon_product_id=addon.id, quantity=50, entry_type="received")
    db.commit()
    db.refresh(addon)
    assert addon.quantity_on_hand == 60


def test_adjust_stock_can_go_negative_and_never_blocks(db):
    _, _, addon = _setup(db, addon_qty=3)
    add_addon_stock(db, addon_product_id=addon.id, quantity=-10, entry_type="adjustment", notes="correction")
    db.commit()
    db.refresh(addon)
    assert addon.quantity_on_hand == -7  # allowed to go negative, never raises


def test_deduct_addons_for_product_scales_by_link_quantity(db):
    _, prod, addon = _setup(db, addon_qty=100, link_qty=3)
    deduct_addons_for_product(db, catalog_product_id=prod.id, units=5, reference_type="test", reference_id=1)
    db.commit()
    db.refresh(addon)
    assert addon.quantity_on_hand == 100 - (3 * 5)


def test_customer_order_placement_auto_deducts_linked_addon_stock(db):
    customer, prod, addon = _setup(db, addon_qty=100, link_qty=2)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 10, "unit_price": "20"}],
    )
    db.commit()
    db.refresh(addon)
    assert addon.quantity_on_hand == 100 - (2 * 10)


def test_cancelling_customer_order_restores_linked_addon_stock(db):
    customer, prod, addon = _setup(db, addon_qty=100, link_qty=2)
    placement = create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 10, "unit_price": "20"}],
    )
    db.commit()
    db.refresh(addon)
    assert addon.quantity_on_hand == 80
    cancel_customer_placement(db, placement_id=placement.id, reason="test cancel", customer_name=customer.business_name)
    db.commit()
    db.refresh(addon)
    assert addon.quantity_on_hand == 100  # fully restored
