"""Round-2 audit CRITICAL finding: GET /customers and GET /customers/{id} returned every
customer's exact AR outstanding_balance/available_credit/credit_limit to *any* staffer
with plain customers.read (or even just the offline-order customer picker), completely
bypassing the dedicated ar.read permission that's supposed to gate that figure."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.accounts_receivable import ArLedgerEntry
from app.models.customer import Customer
from app.routers.customers import _to_public

ADMIN = AuthContext(actor_type="admin", actor_id=1, actor_name="Admin")
AR_STAFF = AuthContext(actor_type="staff", actor_id=2, actor_name="Accountant", permissions={"ar.read", "customers.read"})
PLAIN_STAFF = AuthContext(actor_type="staff", actor_id=3, actor_name="Sales", permissions={"customers.read"})


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
    c = Customer(business_name="Test Customer", phone="8888888888", password_hash="x", credit_limit=Decimal("50000"))
    db.add(c)
    db.flush()
    db.add(ArLedgerEntry(
        customer_id=c.id, entry_type="bill", amount=Decimal("12345"), description="Bill",
        created_by_type="admin", created_by_name="Test",
    ))
    db.commit()
    return c


def test_ar_read_staff_and_admin_see_outstanding(db):
    c = _customer(db)
    for auth in (ADMIN, AR_STAFF):
        pub = _to_public(c, db, auth=auth)
        assert pub.outstanding_balance is not None
        assert Decimal(pub.outstanding_balance) == Decimal("12345")
        assert pub.credit_limit is not None


def test_plain_customers_read_staff_cannot_see_outstanding(db):
    c = _customer(db)
    pub = _to_public(c, db, auth=PLAIN_STAFF)
    assert pub.outstanding_balance is None
    assert pub.available_credit is None
    assert pub.credit_limit is None


def test_no_auth_defaults_to_hidden_not_leaked(db):
    c = _customer(db)
    pub = _to_public(c, db)  # auth omitted entirely — must fail safe, not leak
    assert pub.outstanding_balance is None
    assert pub.credit_limit is None
