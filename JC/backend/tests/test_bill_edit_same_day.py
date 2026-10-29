"""Staff edit a customer bill only on the IST day it was created. Admin edits any day."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.session import Base
from app.deps import AuthContext
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.routers.customer_orders.billing import (
    _staff_may_edit_bill,
    patch_bill_number,
    preview_edit_bill_endpoint,
    update_bill_endpoint,
)
from app.schemas.customer_order import EditBillIn, EditBillLineIn, PatchBillNumberIn
from app.services.cancel_key import cancel_actor, require_cancel_key

STAFF = AuthContext(actor_type="staff", actor_id=2, actor_name="Nikhil")
ADMIN = AuthContext(actor_type="admin", actor_id=None, actor_name="Admin")
OLD = datetime(2024, 1, 2, 8, 0, tzinfo=timezone.utc)


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


def _bill(db, when: datetime) -> CustomerBill:
    customer = Customer(business_name="C1", phone="9998887701", password_hash="x")
    db.add(customer)
    db.flush()
    bill = CustomerBill(
        customer_id=customer.id,
        bill_number="B-OLD",
        subtotal_inclusive=Decimal("80"),
        discount_amount=0,
        taxable_value=Decimal("80"),
        gst_amount=0,
        grand_total=Decimal("80"),
        created_by_type="staff",
        created_by_name="Nikhil",
        created_at=when,
    )
    db.add(bill)
    db.commit()
    return bill


def _edit_body() -> EditBillIn:
    return EditBillIn(
        lines=[EditBillLineIn(catalog_product_id=1, quantity=50)],
        transport_mode="self_pickup",
    )


def test_staff_cannot_edit_a_bill_from_another_day(db):
    bill = _bill(db, OLD)
    with pytest.raises(HTTPException) as err:
        update_bill_endpoint(bill.id, _edit_body(), db, STAFF)
    assert err.value.status_code == 403
    with pytest.raises(HTTPException) as preview:
        preview_edit_bill_endpoint(bill.id, _edit_body(), db, STAFF)
    assert preview.value.status_code == 403
    with pytest.raises(HTTPException) as number:
        patch_bill_number(bill.id, PatchBillNumberIn(bill_number="B-NEW"), db, STAFF)
    assert number.value.status_code == 403


def test_staff_can_edit_a_bill_made_today(db):
    bill = _bill(db, datetime.now(timezone.utc))
    _staff_may_edit_bill(STAFF, bill)


def test_admin_can_edit_an_old_bill(db):
    bill = _bill(db, datetime.now(timezone.utc) - timedelta(days=40))
    _staff_may_edit_bill(ADMIN, bill)


def test_admin_login_cancels_without_a_cancel_key(db):
    settings = get_settings()
    old_login = settings.admin_api_key
    object.__setattr__(settings, "admin_api_key", "login-test-key")
    try:
        assert require_cancel_key("", "login-test-key", db) is None
        assert cancel_actor.get() is None
        with pytest.raises(HTTPException) as staff_try:
            require_cancel_key("", "", db)
        assert staff_try.value.status_code == 400
    finally:
        object.__setattr__(settings, "admin_api_key", old_login)
        cancel_actor.set(None)
