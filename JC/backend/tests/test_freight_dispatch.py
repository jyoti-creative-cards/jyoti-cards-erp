"""Freight dispatch "Pending pick" is an actionable backlog, not a daily log.
Regression test for the day-scope-hides-backlog bug class (same as customer/vendor
order queues) applied to freight parcels."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.services.freight_parcels import list_parcels


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


def _bill(db, *, transport_mode="road", picked_at=None, created_at=None) -> CustomerBill:
    c = Customer(business_name="Freight Party", phone="8222222222", password_hash="x")
    db.add(c)
    db.flush()
    bill = CustomerBill(
        customer_id=c.id, bill_number=f"B-{c.id}", transport_mode=transport_mode,
        freight_picked_at=picked_at,
        subtotal_inclusive=Decimal("100"), grand_total=Decimal("100"),
        created_by_type="admin", created_by_name="Test",
    )
    db.add(bill)
    db.flush()
    if created_at is not None:
        bill.created_at = created_at
    db.commit()
    return bill


def test_pending_parcel_from_yesterday_still_shows_in_today_dispatch_queue(db):
    yesterday = datetime.now(timezone.utc) - timedelta(days=2)
    bill = _bill(db, created_at=yesterday)

    today_rows = list_parcels(db, status="pending", day="today")
    assert any(r["bill_id"] == bill.id for r in today_rows)
    all_rows = list_parcels(db, status="pending", day="all")
    assert any(r["bill_id"] == bill.id for r in all_rows)


def test_picked_parcel_from_yesterday_is_correctly_scoped_out_of_today(db):
    """Sanity check: "picked" (historical/completed) is still meaningfully day-scoped —
    only "pending" (actionable backlog) is exempt."""
    yesterday = datetime.now(timezone.utc) - timedelta(days=2)
    bill = _bill(db, picked_at=yesterday, created_at=yesterday)

    today_rows = list_parcels(db, status="picked", day="today")
    assert not any(r["bill_id"] == bill.id for r in today_rows)
    all_rows = list_parcels(db, status="picked", day="all")
    assert any(r["bill_id"] == bill.id for r in all_rows)
