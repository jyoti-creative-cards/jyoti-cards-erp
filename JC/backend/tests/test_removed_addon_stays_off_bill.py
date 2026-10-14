"""A Name Plate removed on the order must not come back on the bill."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.addon_product import AddonProduct
from app.models.catalog_addon_link import CatalogAddonLink
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.vendor import Vendor
from app.services.catalog_addons import (
    apply_billing_addons_to_totals,
    attach_addons_to_totals,
    billing_addons_for_products,
    merge_priced_addon_charges,
)
from app.services.customer_bills.read import get_process_lines


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


def test_removed_name_plate_is_absent_from_the_bill(db):
    vendor = Vendor(business_name="V", phone="9998887701")
    db.add(vendor)
    db.flush()
    prod = CatalogProduct(
        our_product_id="2165", vendor_id=vendor.id, vendor_product_id="V2165",
        buying_price=Decimal("10"), selling_price=Decimal("20"),
    )
    db.add(prod)
    db.flush()
    plate = AddonProduct(
        our_product_id="NAME PLATE LEDGER", name="NAME PLATE LEDGER", vendor_id=vendor.id,
        vendor_product_id="NP", unit="pc", buying_price=Decimal("1"), selling_price=Decimal("2"),
        quantity_on_hand=100,
    )
    db.add(plate)
    db.flush()
    db.add(CatalogAddonLink(catalog_product_id=prod.id, addon_product_id=plate.id, quantity=1))
    customer = Customer(business_name="C", phone="9998887702", password_hash="x")
    db.add(customer)
    db.flush()
    order = CustomerOrder(customer_id=customer.id, bucket="received", status="received", is_open=True)
    db.add(order)
    db.flush()
    placement = CustomerOrderPlacement(customer_order_id=order.id, status="received")
    db.add(placement)
    db.flush()
    db.add(CustomerOrderLine(
        placement_id=placement.id, catalog_product_id=prod.id, our_product_id="2165",
        quantity=4, quantity_billed=0, unit_price=Decimal("20"), addons_json=[], status="active",
    ))
    db.add(CustomerOpenLine(
        customer_id=customer.id, catalog_product_id=prod.id, our_product_id="2165",
        quantity_received=4, quantity_open=4, quantity_billed=0, unit_price=Decimal("20"), status="open",
    ))
    db.commit()

    lines = get_process_lines(db, customer.id)["lines"]
    assert lines[0]["addons"] == []

    chosen = billing_addons_for_products(db, customer.id, [prod.id])
    charges = merge_priced_addon_charges([], chosen, [{"catalog_product_id": prod.id, "quantity": 4}])
    assert charges == []

    totals = apply_billing_addons_to_totals(
        {"lines": [{"our_product_id": "2165", "quantity": 4}]},
        chosen,
        [{"catalog_product_id": prod.id, "our_product_id": "2165", "quantity": 4}],
    )
    saved = attach_addons_to_totals(db, totals)
    assert saved["lines"][0]["addons"] == []


def test_removed_free_addon_stays_off_the_bill(db):
    vendor = Vendor(business_name="V2", phone="9998887711")
    db.add(vendor)
    db.flush()
    prod = CatalogProduct(
        our_product_id="5416 PATRIKA", vendor_id=vendor.id, vendor_product_id="V5416",
        buying_price=Decimal("10"), selling_price=Decimal("20"),
    )
    db.add(prod)
    db.flush()
    flower = AddonProduct(
        our_product_id="FLOWER", name="FLOWER", vendor_id=vendor.id,
        vendor_product_id="FL", unit="pc", buying_price=Decimal("0"), selling_price=Decimal("0"),
        quantity_on_hand=100,
    )
    plate = AddonProduct(
        our_product_id="NAME PLATE LEDGER", name="NAME PLATE LEDGER", vendor_id=vendor.id,
        vendor_product_id="NP2", unit="pc", buying_price=Decimal("1"), selling_price=Decimal("2"),
        quantity_on_hand=100,
    )
    db.add_all([flower, plate])
    db.flush()
    db.add(CatalogAddonLink(catalog_product_id=prod.id, addon_product_id=flower.id, quantity=1))
    db.add(CatalogAddonLink(catalog_product_id=prod.id, addon_product_id=plate.id, quantity=1))
    customer = Customer(business_name="C2", phone="9998887712", password_hash="x")
    db.add(customer)
    db.flush()
    order = CustomerOrder(customer_id=customer.id, bucket="received", status="received", is_open=True)
    db.add(order)
    db.flush()
    placement = CustomerOrderPlacement(customer_order_id=order.id, status="received")
    db.add(placement)
    db.flush()
    kept = [{
        "addon_product_id": plate.id,
        "our_product_id": "NAME PLATE LEDGER",
        "name": "NAME PLATE LEDGER",
        "selling_price": "2.00",
        "quantity": 1,
    }]
    db.add(CustomerOrderLine(
        placement_id=placement.id, catalog_product_id=prod.id, our_product_id="5416 PATRIKA",
        quantity=2, quantity_billed=0, unit_price=Decimal("20"), addons_json=kept, status="active",
    ))
    db.add(CustomerOpenLine(
        customer_id=customer.id, catalog_product_id=prod.id, our_product_id="5416 PATRIKA",
        quantity_received=2, quantity_open=2, quantity_billed=0, unit_price=Decimal("20"), status="open",
    ))
    db.commit()

    chosen = billing_addons_for_products(db, customer.id, [prod.id])
    ids = [a["addon_product_id"] for a in chosen[prod.id]]
    assert ids == [plate.id]
    totals = apply_billing_addons_to_totals(
        {"lines": [{"catalog_product_id": prod.id, "our_product_id": "5416 PATRIKA", "quantity": 2}]},
        chosen,
        [{"catalog_product_id": prod.id, "our_product_id": "5416 PATRIKA", "quantity": 2}],
    )
    saved = attach_addons_to_totals(db, totals)
    assert [a["addon_product_id"] for a in saved["lines"][0]["addons"]] == [plate.id]
