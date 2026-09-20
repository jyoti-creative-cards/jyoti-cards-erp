"""Regression tests for the stock/ledger accuracy fixes:

1. Reserved-by-party breakdown on the stock detail screen.
2. Duplicate "Placed" rows in customer Activity after billing.
3. Backdated orders / vendor receives not carrying their business date onto the
   StockLedger row (always stamped "now" instead).
4. Cancelling a customer bill not releasing stock back to on-hand.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.bill_series import BillSeries
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_order import CustomerOpenLine, CustomerOrderPlacement
from app.models.stock import StockBalance, StockLedger
from app.models.vendor import Vendor
from app.services.customer_bill_process import cancel_customer_bill, process_customer_bill
from app.services.customer_order_flow import confirm_received_order, create_received_placement
from app.services.ledger import build_customer_ledger
from app.services.order_summary import reserved_by_party
from app.services.stock_receipt import add_stock
from app.services.vendor_receive_bill import receive_vendor_goods
from app.schemas.stock import VendorReceiveCreate, VendorReceiptLineIn

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


def _vendor(db) -> Vendor:
    v = Vendor(business_name="V1", phone="9998887771")
    db.add(v)
    db.flush()
    return v


def _setup(db, on_hand: int = 100) -> tuple[Customer, CatalogProduct]:
    vendor = _vendor(db)
    prod = CatalogProduct(
        our_product_id="P1", vendor_id=vendor.id, vendor_product_id="VP1",
        buying_price=Decimal("10"), selling_price=Decimal("20"),
    )
    db.add(prod)
    db.flush()
    db.add(StockBalance(catalog_product_id=prod.id, quantity_on_hand=on_hand))
    customer = Customer(business_name="C1", phone="9998887772", password_hash="x")
    db.add(customer)
    db.flush()
    return customer, prod


def _bill_series(db, name="T", prefix="T") -> BillSeries:
    series = BillSeries(name=name, prefix=prefix, start_num=1, end_num=999, current_num=0, is_active=True)
    db.add(series)
    db.flush()
    return series


def _naive(dt: datetime) -> datetime:
    """sqlite (test-only backend) drops tzinfo on round-trip; Postgres (prod) keeps it.
    Normalize to naive UTC for comparisons so these tests aren't sqlite-specific."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------------------
# 3. Backdated business date must land on the StockLedger row.
# ---------------------------------------------------------------------------

def test_backdated_customer_order_reservation_uses_business_date(db):
    customer, prod = _setup(db)
    backdate = date.today() - timedelta(days=5)

    placement = create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 5}],
        placed_on=backdate,
    )
    db.flush()

    ledger_row = (
        db.query(StockLedger)
        .filter(StockLedger.reference_type == "customer_placement", StockLedger.reference_id == placement.id)
        .one()
    )
    assert _naive(ledger_row.created_at) == _naive(placement.placed_at)
    assert ledger_row.created_at.date() != datetime.now(timezone.utc).date()


def test_real_time_customer_order_reservation_still_uses_now(db):
    """No placed_on given → ledger still stamps real time (no regression)."""
    customer, prod = _setup(db)
    before = _naive(datetime.now(timezone.utc))
    placement = create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 5}],
    )
    db.flush()
    after = _naive(datetime.now(timezone.utc))

    ledger_row = (
        db.query(StockLedger)
        .filter(StockLedger.reference_type == "customer_placement", StockLedger.reference_id == placement.id)
        .one()
    )
    assert before <= _naive(ledger_row.created_at) <= after


def test_backdated_vendor_receive_uses_business_date(db):
    vendor = _vendor(db)
    prod = CatalogProduct(
        our_product_id="VP1", vendor_id=vendor.id, vendor_product_id="V-VP1",
        buying_price=Decimal("10"), selling_price=Decimal("20"),
    )
    db.add(prod)
    db.flush()
    backdate = date.today() - timedelta(days=10)

    body = VendorReceiveCreate(
        vendor_id=vendor.id,
        lines=[VendorReceiptLineIn(catalog_product_id=prod.id, quantity_received=20)],
        order_receipt_number="RCPT-1",
        received_on=backdate,
    )
    result = receive_vendor_goods(db, AUTH, body, offline=True)
    db.flush()

    ledger_row = (
        db.query(StockLedger)
        .filter(StockLedger.reference_type == "stock_receipt", StockLedger.entry_type == "received")
        .one()
    )
    assert ledger_row.created_at.date() == backdate
    assert ledger_row.created_at.date() != datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# 2. No duplicate "Placed" rows in customer Activity after billing.
# ---------------------------------------------------------------------------

def test_ledger_has_one_placed_row_after_bill(db):
    customer, prod = _setup(db)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 5}],
    )
    confirm_received_order(db, customer.id)
    series = _bill_series(db)
    process_customer_bill(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines_in=[{"catalog_product_id": prod.id, "quantity_to_ship": 5}],
        overall_discount_percent=None,
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        freight_agent_id=None,
        freight_charges=None,
        packaging_charges=None,
        additional_charges=None,
        bill_series_id=series.id,
        narration=None,
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        transport_mode="self_pickup",
    )
    db.commit()

    entries = build_customer_ledger(db, customer.id)
    placed_entries = [e for e in entries if e.event_type in ("order_placed", "order_cancelled")]
    bill_entries = [e for e in entries if e.event_type == "customer_bill"]

    assert len(placed_entries) == 1, f"expected exactly one Placed row, got {len(placed_entries)}"
    assert len(bill_entries) == 1


# ---------------------------------------------------------------------------
# 4. Cancelling a bill releases stock and does not silently re-open it.
# ---------------------------------------------------------------------------

def test_cancel_bill_releases_stock_and_does_not_reopen_to_bill(db):
    customer, prod = _setup(db, on_hand=100)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 10}],
    )
    confirm_received_order(db, customer.id)
    db.flush()

    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == prod.id).one()
    assert bal.quantity_on_hand == 90  # reserved at order time

    series = _bill_series(db)
    bill = process_customer_bill(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines_in=[{"catalog_product_id": prod.id, "quantity_to_ship": 10}],
        overall_discount_percent=None,
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        freight_agent_id=None,
        freight_charges=None,
        packaging_charges=None,
        additional_charges=None,
        bill_series_id=series.id,
        narration=None,
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        transport_mode="self_pickup",
    )
    db.flush()

    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == prod.id).one()
    assert bal.quantity_on_hand == 90  # billing itself doesn't move stock (already reserved)

    cancel_customer_bill(db, bill_id=bill.id, reason="customer backed out", actor_name="Test")
    db.flush()

    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == prod.id).one()
    assert bal.quantity_on_hand == 100, "stock must be released back to on-hand"

    open_row = (
        db.query(CustomerOpenLine)
        .filter(CustomerOpenLine.customer_id == customer.id, CustomerOpenLine.catalog_product_id == prod.id)
        .one()
    )
    assert open_row.quantity_open == 0, "cancelled qty must NOT reopen for re-billing"
    assert open_row.quantity_billed == 0


# ---------------------------------------------------------------------------
# 1. Reserved-by-party breakdown.
# ---------------------------------------------------------------------------

def test_reserved_by_party_breakdown(db):
    customer_a, prod = _setup(db, on_hand=200)
    customer_b = Customer(business_name="C2", phone="9998887773", password_hash="x")
    db.add(customer_b)
    db.flush()

    # Customer A: 5 unconfirmed (still "New")
    create_received_placement(
        db, customer_id=customer_a.id, customer_name=customer_a.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 5}],
    )
    # Customer B: 8 confirmed-but-unbilled, then bill 3 of them (billed, not dispatched)
    create_received_placement(
        db, customer_id=customer_b.id, customer_name=customer_b.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 8}],
    )
    confirm_received_order(db, customer_b.id)
    series = _bill_series(db)
    process_customer_bill(
        db,
        customer_id=customer_b.id,
        customer_name=customer_b.business_name,
        lines_in=[{"catalog_product_id": prod.id, "quantity_to_ship": 3}],
        overall_discount_percent=None,
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        freight_agent_id=None,
        freight_charges=None,
        packaging_charges=None,
        additional_charges=None,
        bill_series_id=series.id,
        narration=None,
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        transport_mode="self_pickup",
    )
    db.flush()

    rows = reserved_by_party(db, prod.id)
    by_name = {r["customer_name"]: r for r in rows}

    assert by_name["C1"]["unconfirmed"] == 5
    assert by_name["C1"]["to_bill"] == 0
    assert by_name["C1"]["billed_not_dispatched"] == 0

    assert by_name["C2"]["to_bill"] == 5  # 8 confirmed - 3 billed
    assert by_name["C2"]["billed_not_dispatched"] == 3
    assert by_name["C2"]["total_held"] == 8
