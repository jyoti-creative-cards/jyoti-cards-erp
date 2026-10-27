"""A bill can include an item that was never a confirmed order.

That line is sold from stock and written as a billed order line.
A booked line on the same bill still only consumes the open quantity.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.accounts_receivable import ArLedgerEntry
from app.models.addon_product import AddonProduct
from app.models.addon_stock_ledger import AddonStockLedger
from app.models.bill_series import BillSeries
from app.models.catalog_addon_link import CatalogAddonLink
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBillLine
from app.models.customer_order import CustomerOpenLine, CustomerOrderLine
from app.models.stock import StockBalance, StockLedger
from app.models.vendor import Vendor
from app.services.customer_bill_process import process_customer_bill
from app.services.customer_order_flow import confirm_received_order, create_received_placement

_ = (AddonProduct, AddonStockLedger, CatalogAddonLink, ArLedgerEntry)


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


def _product(db, sku, on_hand, sell="20"):
    vendor = db.query(Vendor).first()
    if vendor is None:
        vendor = Vendor(business_name="V1", phone="9998887771")
        db.add(vendor)
        db.flush()
    prod = CatalogProduct(
        our_product_id=sku,
        vendor_id=vendor.id,
        vendor_product_id=sku,
        buying_price=Decimal("10"),
        selling_price=Decimal(sell),
        is_active=True,
    )
    db.add(prod)
    db.flush()
    db.add(StockBalance(catalog_product_id=prod.id, quantity_on_hand=on_hand))
    db.flush()
    return prod


def _customer(db):
    customer = Customer(business_name="C1", phone="9998887772", password_hash="x")
    db.add(customer)
    db.flush()
    return customer


def _series(db):
    series = BillSeries(name="T", prefix="T", start_num=1, end_num=999, current_num=0, is_active=True)
    db.add(series)
    db.flush()
    return series


def _bill(db, customer, lines, placement_ids=None):
    return process_customer_bill(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines_in=lines,
        overall_discount_percent=None,
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        freight_agent_id=None,
        freight_charges=None,
        packaging_charges=None,
        additional_charges=None,
        bill_series_id=_series(db).id,
        narration=None,
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        transport_mode="self_pickup",
    ) if placement_ids is None else process_customer_bill(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines_in=lines,
        overall_discount_percent=None,
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        freight_agent_id=None,
        freight_charges=None,
        packaging_charges=None,
        additional_charges=None,
        bill_series_id=_series(db).id,
        narration=None,
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        transport_mode="self_pickup",
        placement_ids=placement_ids,
    )


def test_direct_item_bills_without_a_confirmed_order(db):
    customer = _customer(db)
    prod = _product(db, "P-DIRECT", 10)
    bill = _bill(db, customer, [{
        "catalog_product_id": prod.id,
        "quantity_to_ship": 3,
        "direct": True,
    }])
    db.flush()

    line = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id).one()
    assert line.quantity_shipped == 3
    assert line.unit_price == Decimal("20.00")
    order_line = db.query(CustomerOrderLine).filter(CustomerOrderLine.catalog_product_id == prod.id).one()
    assert order_line.status == "billed"
    assert order_line.quantity == 3
    assert db.query(StockBalance).filter(StockBalance.catalog_product_id == prod.id).one().quantity_on_hand == 7
    sold = db.query(StockLedger).filter(StockLedger.catalog_product_id == prod.id, StockLedger.entry_type == "sold").one()
    assert sold.quantity_delta == -3
    assert db.query(CustomerOpenLine).count() == 0


def test_booked_line_and_direct_line_on_one_bill(db):
    customer = _customer(db)
    booked = _product(db, "P-BOOKED", 10)
    extra = _product(db, "P-EXTRA", 5)
    placement = create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": booked.id, "quantity": 2}],
    )
    confirm_received_order(db, customer.id)
    booked_stock = db.query(StockBalance).filter(StockBalance.catalog_product_id == booked.id).one().quantity_on_hand

    bill = _bill(
        db, customer,
        [
            {"catalog_product_id": booked.id, "quantity_to_ship": 2},
            {"catalog_product_id": extra.id, "quantity_to_ship": 1, "direct": True},
        ],
        placement_ids=[placement.id],
    )
    db.flush()

    lines = {ln.our_product_id: ln for ln in db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id)}
    assert set(lines) == {"P-BOOKED", "P-EXTRA"}
    assert lines["P-EXTRA"].quantity_shipped == 1
    open_row = db.query(CustomerOpenLine).filter(CustomerOpenLine.catalog_product_id == booked.id).one()
    assert open_row.quantity_open == 0
    assert open_row.quantity_billed == 2
    assert db.query(StockBalance).filter(StockBalance.catalog_product_id == booked.id).one().quantity_on_hand == booked_stock
    assert db.query(StockBalance).filter(StockBalance.catalog_product_id == extra.id).one().quantity_on_hand == 4
    billed_extra = db.query(CustomerOrderLine).filter(
        CustomerOrderLine.catalog_product_id == extra.id, CustomerOrderLine.status == "billed"
    ).one()
    assert billed_extra.quantity == 1


def test_direct_refuses_an_item_that_is_already_booked(db):
    customer = _customer(db)
    booked = _product(db, "P-BOOKED", 10)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": booked.id, "quantity": 2}],
    )
    confirm_received_order(db, customer.id)
    with pytest.raises(HTTPException) as caught:
        _bill(db, customer, [{"catalog_product_id": booked.id, "quantity_to_ship": 2, "direct": True}])
    assert "already booked" in str(caught.value.detail)


def test_bill_can_ship_more_than_the_open_order(db):
    customer = _customer(db)
    booked = _product(db, "P-BOOKED", 20)
    placement = create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": booked.id, "quantity": 2}],
    )
    confirm_received_order(db, customer.id)
    before = db.query(StockBalance).filter(StockBalance.catalog_product_id == booked.id).one().quantity_on_hand
    bill = _bill(
        db, customer,
        [{"catalog_product_id": booked.id, "quantity_to_ship": 5}],
        placement_ids=[placement.id],
    )
    db.flush()
    line = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id).one()
    assert line.quantity_shipped == 5
    open_row = db.query(CustomerOpenLine).filter(CustomerOpenLine.catalog_product_id == booked.id).one()
    assert open_row.quantity_open == 0
    assert open_row.quantity_billed == 2
    assert db.query(StockBalance).filter(StockBalance.catalog_product_id == booked.id).one().quantity_on_hand == before - 3


def test_same_day_bill_warns_before_a_second_bill(db):
    customer = _customer(db)
    prod = _product(db, "P-DIRECT", 10)
    lines = [{"catalog_product_id": prod.id, "quantity_to_ship": 2, "direct": True}]
    _bill(db, customer, lines)
    with pytest.raises(HTTPException) as caught:
        process_customer_bill(
            db,
            customer_id=customer.id,
            customer_name=customer.business_name,
            lines_in=lines,
            overall_discount_percent=None,
            gst_enabled=False,
            gst_rate_percent=Decimal("0"),
            freight_agent_id=None,
            freight_charges=None,
            packaging_charges=None,
            additional_charges=None,
            bill_series_id=_series(db).id,
            narration=None,
            actor_type="admin",
            actor_id=1,
            actor_name="Test",
            transport_mode="self_pickup",
            confirm_duplicate=False,
        )
    assert caught.value.status_code == 409
    assert caught.value.detail["matches"][0]["same_items"] == ["P-DIRECT"]


def test_direct_bill_can_take_stock_below_zero(db):
    customer = _customer(db)
    prod = _product(db, "P-DIRECT", 1)
    _bill(db, customer, [{"catalog_product_id": prod.id, "quantity_to_ship": 4, "direct": True}])
    assert db.query(StockBalance).filter(StockBalance.catalog_product_id == prod.id).one().quantity_on_hand == -3
