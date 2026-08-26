"""void/restore/purge — AR + stock correctness for customer bills, placements, and returns."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.accounts_receivable import ArLedgerEntry
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.customer_return import CustomerReturn, CustomerReturnLine
from app.models.stock import StockBalance
from app.services.ar_ledger import post_bill_entry, post_credit_note_entry
from app.services.void_service import (
    purge_customer_bill,
    purge_customer_placement,
    purge_customer_return,
    restore_customer_bill,
    restore_customer_placement,
    restore_customer_return,
    void_customer_bill,
    void_customer_placement,
    void_customer_return,
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


def _customer(db) -> Customer:
    c = Customer(business_name="Test Customer", phone="8888888888", password_hash="x")
    db.add(c)
    db.flush()
    return c


def _bill(db, customer_id: int, amount=Decimal("100"), qty_shipped: int = 0) -> CustomerBill:
    """qty_shipped=0 keeps cancel_customer_bill's stock/open-line/freight paths untouched —
    it only needs to close the (already unshipped) line, so this exercises the AR + soft-delete
    plumbing without dragging in the full offline-bill stock machinery."""
    b = CustomerBill(
        customer_id=customer_id, bill_number=f"B-{customer_id}-1", subtotal_inclusive=amount,
        grand_total=amount, created_by_type="admin", created_by_name="Test",
    )
    db.add(b)
    db.flush()
    ln = CustomerBillLine(
        bill_id=b.id, catalog_product_id=1, our_product_id="P1",
        quantity_shipped=qty_shipped, unit_price=Decimal("10"), line_total=amount,
    )
    db.add(ln)
    db.flush()
    post_bill_entry(
        db, customer_id=customer_id, bill_id=b.id, amount=amount, description="Bill",
        actor_type="admin", actor_id=1, actor_name="Test",
    )
    db.commit()
    return b


def _return(db, customer_id: int, bill: CustomerBill, qty: int = 2, amount=Decimal("20")) -> CustomerReturn:
    bline = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id).first()
    r = CustomerReturn(
        customer_id=customer_id, return_number=f"CN-{customer_id}-1",
        calculated_amount=amount, credit_amount=amount,
        created_by_type="admin", created_by_name="Test",
    )
    db.add(r)
    db.flush()
    rln = CustomerReturnLine(
        return_id=r.id, bill_id=bill.id, bill_line_id=bline.id, catalog_product_id=1,
        our_product_id="P1", quantity_returned=qty, sold_unit_price=Decimal("10"), line_calculated=amount,
    )
    db.add(rln)
    db.flush()
    from app.services.stock_receipt import add_stock

    add_stock(db, catalog_product_id=1, our_product_id="P1", quantity=qty, entry_type="return",
              reference_type="customer_return", reference_id=r.id)
    post_credit_note_entry(
        db, customer_id=customer_id, return_id=r.id, amount=amount, description="Return",
        actor_type="admin", actor_id=1, actor_name="Test",
    )
    db.commit()
    return r


# ── CustomerBill ──────────────────────────────────────────────────────────────


def test_void_already_cancelled_bill_just_hides(db):
    customer = _customer(db)
    bill = _bill(db, customer.id)
    bill.cancelled_at = datetime.now(timezone.utc)
    bill.cancel_reason = "business cancel"
    db.commit()

    void_customer_bill(db, AUTH, bill.id, "mistake — hide it")

    b2 = db.get(CustomerBill, bill.id)
    assert b2.deleted_at is not None
    active_ar = db.query(ArLedgerEntry).filter(ArLedgerEntry.bill_id == bill.id, ArLedgerEntry.deleted_at.is_(None)).all()
    assert active_ar == []  # soft-deleted alongside the bill


def test_void_active_bill_cancels_then_hides(db):
    customer = _customer(db)
    bill = _bill(db, customer.id, amount=Decimal("100"))
    active_before = db.query(ArLedgerEntry).filter(ArLedgerEntry.bill_id == bill.id, ArLedgerEntry.deleted_at.is_(None)).all()
    assert len(active_before) == 1
    assert active_before[0].amount == Decimal("100.00")

    void_customer_bill(db, AUTH, bill.id, "wrong bill")

    b2 = db.get(CustomerBill, bill.id)
    assert b2.cancelled_at is not None  # void wraps cancel
    assert b2.deleted_at is not None
    active_after = db.query(ArLedgerEntry).filter(ArLedgerEntry.bill_id == bill.id, ArLedgerEntry.deleted_at.is_(None)).all()
    assert active_after == []


def test_restore_bill_unhides_only_stays_cancelled(db):
    customer = _customer(db)
    bill = _bill(db, customer.id)
    void_customer_bill(db, AUTH, bill.id, "oops")

    restore_customer_bill(db, AUTH, bill.id)

    b2 = db.get(CustomerBill, bill.id)
    assert b2.deleted_at is None
    assert b2.cancelled_at is not None  # restore does NOT un-cancel
    active_ar = db.query(ArLedgerEntry).filter(ArLedgerEntry.bill_id == bill.id, ArLedgerEntry.deleted_at.is_(None)).all()
    assert len(active_ar) == 1


def test_purge_bill_requires_void_first_and_blocks_on_returns(db):
    customer = _customer(db)
    bill = _bill(db, customer.id)

    with pytest.raises(Exception):
        purge_customer_bill(db, AUTH, bill.id)  # not voided yet

    void_customer_bill(db, AUTH, bill.id, None)
    ret = _return(db, customer.id, bill)

    with pytest.raises(Exception):
        purge_customer_bill(db, AUTH, bill.id)  # return still references it

    void_customer_return(db, AUTH, ret.id, None)
    purge_customer_return(db, AUTH, ret.id)
    # purge_customer_return relies on the DB's ON DELETE CASCADE (postgres) to drop the
    # CustomerReturnLine row along with it — sqlite in tests doesn't enforce that FK, so
    # simulate it here rather than asserting on a sqlite-only quirk.
    from app.models.customer_return import CustomerReturnLine

    db.query(CustomerReturnLine).filter(CustomerReturnLine.bill_id == bill.id).delete(synchronize_session=False)
    db.commit()

    purge_customer_bill(db, AUTH, bill.id)
    assert db.get(CustomerBill, bill.id) is None


# ── CustomerOrderPlacement ────────────────────────────────────────────────────


def test_void_fully_billed_placement_just_hides(db):
    customer = _customer(db)
    order = CustomerOrder(customer_id=customer.id, bucket="received", status="received")
    db.add(order)
    db.flush()
    placement = CustomerOrderPlacement(customer_order_id=order.id, status="received")
    db.add(placement)
    db.flush()
    line = CustomerOrderLine(
        placement_id=placement.id, catalog_product_id=1, our_product_id="P1",
        quantity=5, quantity_billed=5, unit_price=Decimal("10"),
    )
    db.add(line)
    db.commit()

    void_customer_placement(db, AUTH, placement.id, "hide fully-billed order")

    p2 = db.get(CustomerOrderPlacement, placement.id)
    assert p2.deleted_at is not None
    assert p2.status == "received"  # nothing left to cancel — untouched


def test_restore_placement_unhides(db):
    customer = _customer(db)
    order = CustomerOrder(customer_id=customer.id, bucket="received", status="received")
    db.add(order)
    db.flush()
    placement = CustomerOrderPlacement(customer_order_id=order.id, status="received")
    db.add(placement)
    db.commit()

    void_customer_placement(db, AUTH, placement.id, "oops")
    restore_customer_placement(db, AUTH, placement.id)

    p2 = db.get(CustomerOrderPlacement, placement.id)
    assert p2.deleted_at is None


def test_purge_placement_requires_void_first(db):
    customer = _customer(db)
    order = CustomerOrder(customer_id=customer.id, bucket="received", status="received")
    db.add(order)
    db.flush()
    placement = CustomerOrderPlacement(customer_order_id=order.id, status="received")
    db.add(placement)
    db.commit()

    with pytest.raises(Exception):
        purge_customer_placement(db, AUTH, placement.id)

    void_customer_placement(db, AUTH, placement.id, None)
    purge_customer_placement(db, AUTH, placement.id)
    assert db.get(CustomerOrderPlacement, placement.id) is None


# ── CustomerReturn — full symmetric void/restore (mirrors DebitNote) ─────────


def test_void_return_reverses_stock_and_ar(db):
    customer = _customer(db)
    bill = _bill(db, customer.id, qty_shipped=2)
    ret = _return(db, customer.id, bill, qty=2, amount=Decimal("20"))

    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == 1).one()
    assert bal.quantity_on_hand == 2  # +2 from the return
    active_ar = db.query(ArLedgerEntry).filter(ArLedgerEntry.return_id == ret.id, ArLedgerEntry.deleted_at.is_(None)).all()
    assert len(active_ar) == 1

    void_customer_return(db, AUTH, ret.id, "wrong return")
    db.refresh(bal)
    assert bal.quantity_on_hand == 0  # reversed back
    active_ar_after = db.query(ArLedgerEntry).filter(ArLedgerEntry.return_id == ret.id, ArLedgerEntry.deleted_at.is_(None)).all()
    assert active_ar_after == []


def test_restore_return_reapplies_stock_and_ar(db):
    customer = _customer(db)
    bill = _bill(db, customer.id, qty_shipped=2)
    ret = _return(db, customer.id, bill, qty=2, amount=Decimal("20"))

    void_customer_return(db, AUTH, ret.id, "oops")
    restore_customer_return(db, AUTH, ret.id)

    r2 = db.get(CustomerReturn, ret.id)
    assert r2.deleted_at is None
    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == 1).one()
    assert bal.quantity_on_hand == 2
    active_ar = db.query(ArLedgerEntry).filter(ArLedgerEntry.return_id == ret.id, ArLedgerEntry.deleted_at.is_(None)).all()
    assert len(active_ar) == 1


def test_purge_return_requires_void_first(db):
    customer = _customer(db)
    bill = _bill(db, customer.id, qty_shipped=2)
    ret = _return(db, customer.id, bill, qty=2, amount=Decimal("20"))

    with pytest.raises(Exception):
        purge_customer_return(db, AUTH, ret.id)

    void_customer_return(db, AUTH, ret.id, None)
    purge_customer_return(db, AUTH, ret.id)
    assert db.get(CustomerReturn, ret.id) is None
