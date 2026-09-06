"""A bill whose lines are all closed must (a) drop out of the 'Billed' backlog and
(b) remain voidable. Regression test for the round-2 audit CRITICAL finding: previously
neither happened — close_bill_line never touched the parent bill, and
cancel_customer_bill hard-blocked on any closed line (including "all closed", which has
nothing left to reverse)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.services.ar_ledger import post_bill_entry
from app.services.customer_bill_process import close_bill_line
from app.services.void_service import void_customer_bill

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


def _bill_with_lines(db, customer_id: int, n_lines: int = 2) -> CustomerBill:
    b = CustomerBill(
        customer_id=customer_id, bill_number=f"B-{customer_id}-1", subtotal_inclusive=Decimal("200"),
        grand_total=Decimal("200"), created_by_type="admin", created_by_name="Test",
    )
    db.add(b)
    db.flush()
    for i in range(n_lines):
        db.add(CustomerBillLine(
            bill_id=b.id, catalog_product_id=i + 1, our_product_id=f"P{i + 1}",
            quantity_shipped=0, unit_price=Decimal("10"), line_total=Decimal("100"),
        ))
    db.flush()
    post_bill_entry(
        db, customer_id=customer_id, bill_id=b.id, amount=Decimal("200"), description="Bill",
        actor_type="admin", actor_id=1, actor_name="Test",
    )
    db.commit()
    return b


def test_bill_stays_open_until_every_line_closed(db):
    customer = _customer(db)
    bill = _bill_with_lines(db, customer.id, n_lines=2)
    lines = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id).order_by(CustomerBillLine.id).all()

    close_bill_line(db, lines[0].id, "dispatched")
    db.commit()
    db.refresh(bill)
    assert bill.closed_at is None, "bill must stay in the Billed backlog while any line is still open"

    close_bill_line(db, lines[1].id, "dispatched")
    db.commit()
    db.refresh(bill)
    assert bill.closed_at is not None, "bill must leave the Billed backlog once every line is closed"


def test_fully_closed_bill_can_still_be_voided(db):
    customer = _customer(db)
    bill = _bill_with_lines(db, customer.id, n_lines=1)
    line = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id).first()

    close_bill_line(db, line.id, "dispatched")
    db.commit()
    db.refresh(bill)
    assert bill.closed_at is not None

    # Previously: cancel_customer_bill's blanket "any closed line" guard raised 400 here,
    # so a fully-settled bill had no way to be voided/corrected by an admin.
    result = void_customer_bill(db, AUTH, bill.id, "correcting a mistake")
    assert result["ok"] is True
    db.refresh(bill)
    assert bill.deleted_at is not None
    assert bill.cancelled_at is not None


def test_partially_closed_bill_still_blocks_cancel(db):
    customer = _customer(db)
    bill = _bill_with_lines(db, customer.id, n_lines=2)
    lines = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id).order_by(CustomerBillLine.id).all()

    close_bill_line(db, lines[0].id, "dispatched")
    db.commit()

    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        void_customer_bill(db, AUTH, bill.id, "trying to void mid-dispatch")
