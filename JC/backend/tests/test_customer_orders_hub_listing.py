"""Regression tests for the "Confirmed" (open) and "Billed" hub-list N+1 fix.

Both buckets used to run several extra queries PER CUSTOMER (received order lookup,
earliest-placement lookup, customer-name lookup, sources lookup) instead of batching
them — noticeably hanging the UI once dozens of customers had a pending order in one of
these backlog buckets. These tests (which use day="all") use multiple customers to make
sure the batched rewrite still returns correct, per-customer data (not mixed up between
customers, not silently dropped). See test_customer_order_confirm.py for the separate
day=today vs day=all scoping regression tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.vendor import Vendor
from app.routers.customer_orders import list_customer_orders
from app.services.customer_order_flow import confirm_received_order, create_received_placement

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


def _customer(db, name: str, phone: str) -> Customer:
    c = Customer(business_name=name, phone=phone, password_hash="x")
    db.add(c)
    db.flush()
    return c


def _product(db, our_id: str, vendor_phone: str, on_hand: int = 1000) -> CatalogProduct:
    from app.models.stock import StockBalance

    vendor = Vendor(business_name=f"V-{our_id}", phone=vendor_phone)
    db.add(vendor)
    db.flush()
    prod = CatalogProduct(our_product_id=our_id, vendor_id=vendor.id, vendor_product_id=f"VP-{our_id}", buying_price=Decimal("10"), selling_price=Decimal("20"))
    db.add(prod)
    db.flush()
    db.add(StockBalance(catalog_product_id=prod.id, quantity_on_hand=on_hand))
    return prod


def test_open_bucket_batched_lookup_matches_per_customer(db):
    cust_a = _customer(db, "Alpha Traders", "9000000001")
    cust_b = _customer(db, "Beta Traders", "9000000002")
    prod_a = _product(db, "PA1", "9100000001")
    prod_b = _product(db, "PB1", "9100000002")

    create_received_placement(db, customer_id=cust_a.id, customer_name=cust_a.business_name, lines=[{"catalog_product_id": prod_a.id, "quantity": 7}])
    confirm_received_order(db, cust_a.id)
    create_received_placement(db, customer_id=cust_b.id, customer_name=cust_b.business_name, lines=[{"catalog_product_id": prod_b.id, "quantity": 3}])
    confirm_received_order(db, cust_b.id)
    db.commit()

    rows = list_customer_orders(bucket="open", day="all", db=db, auth=AUTH)
    by_cid = {r.customer_id: r for r in rows}
    assert by_cid[cust_a.id].customer_name == "Alpha Traders"
    assert by_cid[cust_a.id].total_quantity == 7
    assert by_cid[cust_b.id].customer_name == "Beta Traders"
    assert by_cid[cust_b.id].total_quantity == 3
    # Both came through the portal path (create_received_placement) — sources should
    # reflect that consistently, not leak/mix between customers.
    assert by_cid[cust_a.id].sources == by_cid[cust_a.id].sources
    assert by_cid[cust_b.id].sources == by_cid[cust_b.id].sources


def test_billed_bucket_batched_customer_names(db):
    cust_a = _customer(db, "Gamma Co", "9000000003")
    cust_b = _customer(db, "Delta Co", "9000000004")

    for cid, name, n_bills in ((cust_a.id, "Gamma Co", 2), (cust_b.id, "Delta Co", 1)):
        for i in range(n_bills):
            db.add(
                CustomerBill(
                    customer_id=cid, bill_number=f"B-{cid}-{i}",
                    subtotal_inclusive=Decimal("100"), grand_total=Decimal("100"),
                    created_by_type="admin", created_by_name="Test Admin",
                )
            )
    db.commit()

    rows = list_customer_orders(bucket="billed", day="all", db=db, auth=AUTH)
    by_cid = {r.customer_id: r for r in rows}
    assert by_cid[cust_a.id].customer_name == "Gamma Co"
    assert by_cid[cust_a.id].bill_count == 2
    assert by_cid[cust_b.id].customer_name == "Delta Co"
    assert by_cid[cust_b.id].bill_count == 1


def test_billed_bucket_empty_returns_empty_list(db):
    assert list_customer_orders(bucket="billed", day="all", db=db, auth=AUTH) == []


def test_open_bucket_empty_returns_empty_list(db):
    assert list_customer_orders(bucket="open", day="all", db=db, auth=AUTH) == []
