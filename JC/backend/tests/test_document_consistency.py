from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.bill_series import BillSeries
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBillLine
from app.models.customer_order import CustomerOrder, CustomerOrderPlacement
from app.models.stock import StockBalance
from app.models.vendor import Vendor
from app.services.customer_bill_process import close_bill_line, process_customer_bill
from app.services.customer_order_flow import confirm_received_order, create_received_placement
from app.services.document_present import is_locked, present


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


def _vendor(db) -> Vendor:
    vendor = Vendor(business_name="V1", phone="9998887771")
    db.add(vendor)
    db.flush()
    return vendor


def _setup(db, on_hand: int = 100) -> tuple[Customer, CatalogProduct, Vendor]:
    vendor = _vendor(db)
    prod = CatalogProduct(
        our_product_id="P1",
        vendor_id=vendor.id,
        vendor_product_id="VP1",
        buying_price=Decimal("10"),
        selling_price=Decimal("20"),
    )
    db.add(prod)
    db.flush()
    db.add(StockBalance(catalog_product_id=prod.id, quantity_on_hand=on_hand))
    customer = Customer(business_name="C1", phone="9998887772", password_hash="x")
    db.add(customer)
    db.flush()
    return customer, prod, vendor


def _bill_series(db, name="T", prefix="T") -> BillSeries:
    series = BillSeries(name=name, prefix=prefix, start_num=1, end_num=999, current_num=0, is_active=True)
    db.add(series)
    db.flush()
    return series


def test_saved_customer_bill_keeps_card_after_rename(db):
    customer, prod, _ = _setup(db)
    create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    confirm_received_order(db, customer.id)
    bill = process_customer_bill(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines_in=[{"catalog_product_id": prod.id, "quantity_to_ship": 2}],
        overall_discount_percent=None,
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        freight_agent_id=None,
        freight_charges=None,
        packaging_charges=None,
        additional_charges=None,
        bill_series_id=_bill_series(db).id,
        narration=None,
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        transport_mode="self_pickup",
    )
    db.flush()
    before = present(db, "customer_bill", bill)
    prod.our_product_id = "RENAMED"
    prod.category = "NEW-CAT"
    db.flush()
    after = present(db, "customer_bill", bill)
    assert after["locked"] is True
    assert after["lines"][0]["our_product_id"] == before["lines"][0]["our_product_id"]
    assert after["lines"][0]["our_product_id"] != "RENAMED"
    assert after["lines"][0].get("category") != "NEW-CAT"


def test_open_order_follows_rename(db):
    customer, prod, _ = _setup(db)
    placement = create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    db.flush()
    prod.our_product_id = "RENAMED"
    db.flush()
    view = present(db, "customer_order", placement)
    assert view["locked"] is False
    assert view["lines"][0]["our_product_id"] == "RENAMED"


def test_closed_customer_order_locks_by_parent_bucket(db):
    customer, prod, _ = _setup(db)
    placement = create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    order = db.get(CustomerOrder, placement.customer_order_id)
    order.bucket = "closed"
    db.flush()
    assert is_locked("customer_order", placement) is True


def test_closed_bill_line_freezes_customer_order_card(db):
    customer, prod, _ = _setup(db)
    create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    confirm_received_order(db, customer.id)
    bill = process_customer_bill(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines_in=[{"catalog_product_id": prod.id, "quantity_to_ship": 2}],
        overall_discount_percent=None,
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        freight_agent_id=None,
        freight_charges=None,
        packaging_charges=None,
        additional_charges=None,
        bill_series_id=_bill_series(db).id,
        narration=None,
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        transport_mode="self_pickup",
    )
    db.flush()
    bill_line = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id).one()
    close_bill_line(db, bill_line.id, "dispatched")
    db.flush()

    closed_order = (
        db.query(CustomerOrder)
        .filter(CustomerOrder.customer_id == customer.id, CustomerOrder.bucket == "closed")
        .one()
    )
    placement = (
        db.query(CustomerOrderPlacement)
        .filter_by(customer_order_id=closed_order.id, status="closed")
        .one()
    )
    before = present(db, "customer_order", placement)
    prod.our_product_id = "RENAMED"
    prod.category = "NEW-CAT"
    db.flush()
    after = present(db, "customer_order", placement)
    assert before["status"] == "closed"
    assert after["status"] == "closed"
    assert after["locked"] is True
    assert after["lines"][0]["our_product_id"] == before["lines"][0]["our_product_id"]
    assert after["lines"][0]["our_product_id"] != "RENAMED"
    assert after["lines"][0]["category"] == before["lines"][0]["category"]
    assert after["lines"][0]["category"] != "NEW-CAT"


def test_is_locked_covers_document_kinds():
    assert is_locked("customer_bill", SimpleNamespace(id=1)) is True
    assert is_locked("vendor_bill", SimpleNamespace(bill_status="billed")) is True
    assert is_locked("vendor_order", SimpleNamespace(status="open", order=SimpleNamespace(bucket="closed"))) is True
    assert is_locked("customer_receipt", SimpleNamespace()) is False
    assert is_locked("debit_note", SimpleNamespace()) is False
    assert is_locked("expense", SimpleNamespace()) is False
    assert is_locked("payment", SimpleNamespace()) is False
    assert is_locked("freight", SimpleNamespace()) is False
    assert is_locked("customer_return", SimpleNamespace()) is False
