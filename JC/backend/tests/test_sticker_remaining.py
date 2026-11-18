"""Packed bills with no sticker after the bill stay on the remaining list."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.sticker_print import StickerPrint
from app.services.sticker_labels import list_unprinted_packed

WHEN = datetime(2026, 11, 18, 4, 0, tzinfo=timezone.utc)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _bill(db, customer, number, created, mode="bus", picked=False):
    bill = CustomerBill(
        customer_id=customer.id,
        bill_number=number,
        subtotal_inclusive=Decimal("10"),
        discount_amount=0,
        taxable_value=0,
        gst_amount=0,
        grand_total=Decimal("10"),
        created_by_type="admin",
        created_by_name="Test",
        transport_mode=mode,
        freight_picked_at=created if picked else None,
        created_at=created,
    )
    db.add(bill)
    db.flush()
    return bill


def test_remaining_is_packed_bills_without_a_later_sticker():
    db = _db()
    waiting = Customer(business_name="Waiting Press", phone="9000000001", password_hash="x")
    done = Customer(business_name="Done Press", phone="9000000002", password_hash="x")
    db.add_all([waiting, done])
    db.flush()
    _bill(db, waiting, "W1", WHEN, "bus")
    _bill(db, done, "D1", WHEN, "transport")
    db.add(StickerPrint(
        customer_id=done.id,
        business_name=done.business_name,
        printed_by="Pandit",
        printed_at=WHEN + timedelta(hours=1),
        carry="transport",
    ))
    db.commit()
    rows = list_unprinted_packed(db)
    assert [row["business_name"] for row in rows] == ["Waiting Press"]
    bus = list_unprinted_packed(db, carry="bus")
    assert [row["business_name"] for row in bus] == ["Waiting Press"]
    transport = list_unprinted_packed(db, carry="transport")
    assert transport == []
    db.close()
