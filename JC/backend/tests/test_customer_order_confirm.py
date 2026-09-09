"""A fresh customer order must only ever show under "New" (received bucket) — never
also under "Confirmed" (CustomerOpenLine / open bucket) — until explicitly confirmed.
Regression test for the New+Confirmed duplicate-listing bug."""

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
from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.stock import StockBalance
from app.models.vendor import Vendor
from app.services.customer_order_flow import (
    cancel_customer_placement,
    confirm_received_order,
    create_received_placement,
    edit_customer_placement_line_qty,
    get_open_customer_order,
)

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


def _setup(db, on_hand: int = 100) -> tuple[Customer, CatalogProduct]:
    vendor = Vendor(business_name="V", phone="9998887771")
    db.add(vendor)
    db.flush()
    prod = CatalogProduct(
        our_product_id="P1", vendor_id=vendor.id, vendor_product_id="VP1",
        buying_price=Decimal("10"), selling_price=Decimal("20"),
    )
    db.add(prod)
    db.flush()
    db.add(StockBalance(catalog_product_id=prod.id, quantity_on_hand=on_hand))
    customer = Customer(business_name="C", phone="9998887772", password_hash="x")
    db.add(customer)
    db.flush()
    return customer, prod


def _open_qty(db, customer_id: int, catalog_product_id: int) -> int:
    row = (
        db.query(CustomerOpenLine)
        .filter(CustomerOpenLine.customer_id == customer_id, CustomerOpenLine.catalog_product_id == catalog_product_id)
        .first()
    )
    return int(row.quantity_open) if row else 0


def test_new_order_does_not_appear_in_confirmed_until_confirmed(db):
    customer, prod = _setup(db)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 5}],
    )
    db.flush()

    # Still "New" only — nothing in the Confirmed (open) tally yet.
    assert get_open_customer_order(db, customer.id, "received") is not None
    assert get_open_customer_order(db, customer.id, "open") is None
    assert _open_qty(db, customer.id, prod.id) == 0

    ok = confirm_received_order(db, customer.id)
    assert ok is True

    # Now moved to Confirmed, and "New" no longer has an open received order.
    received = get_open_customer_order(db, customer.id, "received")
    assert received is None or received.is_open is False
    assert get_open_customer_order(db, customer.id, "open") is not None
    assert _open_qty(db, customer.id, prod.id) == 5


def test_editing_received_line_does_not_touch_open_tally(db):
    customer, prod = _setup(db)
    placement = create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 5}],
    )
    db.flush()
    line = db.query(CustomerOrderLine).filter(CustomerOrderLine.placement_id == placement.id).first()
    edit_customer_placement_line_qty(db, line.id, 8, customer.business_name)
    db.flush()
    assert _open_qty(db, customer.id, prod.id) == 0  # still nothing confirmed

    confirm_received_order(db, customer.id)
    assert _open_qty(db, customer.id, prod.id) == 8  # confirms the edited qty


def test_cancelling_received_placement_does_not_touch_open_tally(db):
    customer, prod = _setup(db)
    placement = create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 5}],
    )
    db.flush()
    cancel_customer_placement(db, placement_id=placement.id, reason="test", customer_name=customer.business_name)
    db.flush()
    assert _open_qty(db, customer.id, prod.id) == 0
    # Nothing left to confirm.
    assert confirm_received_order(db, customer.id) is False


def test_second_order_after_confirm_stacks_but_stays_unconfirmed_until_confirmed_again(db):
    customer, prod = _setup(db)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 5}],
    )
    confirm_received_order(db, customer.id)
    db.flush()
    assert _open_qty(db, customer.id, prod.id) == 5

    # A second, brand-new order — must not bump the Confirmed tally yet.
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 3}],
    )
    db.flush()
    assert _open_qty(db, customer.id, prod.id) == 5
    assert get_open_customer_order(db, customer.id, "received") is not None

    confirm_received_order(db, customer.id)
    assert _open_qty(db, customer.id, prod.id) == 8


def test_fresh_new_order_shows_in_today_and_all_new_queues(db):
    """A brand-new "New" (received) order — placed just now — must show under both the
    default "Today" queue and the "Past"/all-history view."""
    from app.routers.customer_orders import list_customer_orders

    customer, prod = _setup(db)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 5}],
    )
    db.commit()

    today_rows = list_customer_orders(bucket="received", day="today", db=db, auth=AUTH)
    assert any(r.customer_id == customer.id for r in today_rows)
    all_rows = list_customer_orders(bucket="received", day="all", db=db, auth=AUTH)
    assert any(r.customer_id == customer.id for r in all_rows)


def test_old_untouched_new_order_moves_from_today_to_past_queue(db):
    """Regression: the "New" hub tab used to be re-sorted by party_number and never
    day-scoped, so a genuinely old, still-unconfirmed order was easy to miss in a long
    list and cluttered "Today" forever. Now: an order not touched today drops out of
    "Today" but must still be fully visible (never lost) under "Past"/all-history, so
    staff can still find and confirm/bill it."""
    from datetime import timedelta

    from app.models.customer_order import CustomerOrder
    from app.routers.customer_orders import list_customer_orders

    customer, prod = _setup(db)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 5}],
    )
    db.commit()

    # Simulate this order having sat untouched since two days ago.
    order = db.query(CustomerOrder).filter(CustomerOrder.customer_id == customer.id).first()
    order.updated_at = datetime.now(timezone.utc) - timedelta(days=2)
    db.commit()

    today_rows = list_customer_orders(bucket="received", day="today", db=db, auth=AUTH)
    assert not any(r.customer_id == customer.id for r in today_rows)
    all_rows = list_customer_orders(bucket="received", day="all", db=db, auth=AUTH)
    assert any(r.customer_id == customer.id for r in all_rows)


def test_freshly_confirmed_order_shows_in_today_confirmed_queue(db):
    """A customer confirmed just now must show under the "Confirmed" (bucket=open)
    Today queue."""
    from app.routers.customer_orders import list_customer_orders

    customer, prod = _setup(db)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 5}],
    )
    confirm_received_order(db, customer.id)
    db.commit()

    today_rows = list_customer_orders(bucket="open", day="today", db=db, auth=AUTH)
    assert any(r.customer_id == customer.id for r in today_rows)


def test_old_untouched_confirmed_order_moves_from_today_to_past_queue(db):
    """Consistent with "New": a customer confirmed days ago and still not billed drops
    out of the "Confirmed" Today queue, but is never lost — still visible under "Past"
    (day=all), matched by CustomerOpenLine.updated_at."""
    from datetime import timedelta

    from app.routers.customer_orders import list_customer_orders

    customer, prod = _setup(db)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 5}],
    )
    confirm_received_order(db, customer.id)
    db.commit()

    old_line = (
        db.query(CustomerOpenLine)
        .filter(CustomerOpenLine.customer_id == customer.id, CustomerOpenLine.catalog_product_id == prod.id)
        .first()
    )
    old_line.updated_at = datetime.now(timezone.utc) - timedelta(days=2)
    db.commit()

    today_rows = list_customer_orders(bucket="open", day="today", db=db, auth=AUTH)
    assert not any(r.customer_id == customer.id for r in today_rows)
    all_rows = list_customer_orders(bucket="open", day="all", db=db, auth=AUTH)
    assert any(r.customer_id == customer.id for r in all_rows)


def test_fresh_bill_shows_in_today_billed_queue(db):
    """A bill created just now must show under the "Billed" Today queue."""
    from app.models.customer_bill import CustomerBill
    from app.routers.customer_orders import list_customer_orders

    customer, prod = _setup(db)
    db.add(CustomerBill(
        customer_id=customer.id, bill_number="B-FRESH-1",
        subtotal_inclusive=Decimal("100"), grand_total=Decimal("100"),
        created_by_type="admin", created_by_name="Test Admin",
    ))
    db.commit()

    today_rows = list_customer_orders(bucket="billed", day="today", db=db, auth=AUTH)
    assert any(r.customer_id == customer.id for r in today_rows)


def test_old_bill_moves_from_today_to_past_billed_queue(db):
    """A bill created days ago and still not closed drops out of the "Billed" Today
    queue, but is never lost — still visible under "Past" (day=all)."""
    from datetime import timedelta

    from app.models.customer_bill import CustomerBill
    from app.routers.customer_orders import list_customer_orders

    customer, prod = _setup(db)
    bill = CustomerBill(
        customer_id=customer.id, bill_number="B-OLD-1",
        subtotal_inclusive=Decimal("100"), grand_total=Decimal("100"),
        created_by_type="admin", created_by_name="Test Admin",
    )
    db.add(bill)
    db.flush()
    bill.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    db.commit()

    today_rows = list_customer_orders(bucket="billed", day="today", db=db, auth=AUTH)
    assert not any(r.customer_id == customer.id for r in today_rows)
    all_rows = list_customer_orders(bucket="billed", day="all", db=db, auth=AUTH)
    assert any(r.customer_id == customer.id for r in all_rows)
