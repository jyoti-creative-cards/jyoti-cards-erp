"""A second payment with the same party, amount, date, and bank is flagged."""
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.accounts_receivable import ArLedgerEntry
from app.models.customer import Customer
from app.services.ar_ledger import post_payment_entry
from app.services.payment_duplicates import same_payment_clashes


def test_same_party_amount_date_and_bank_is_a_duplicate():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    customer = Customer(business_name="Party", phone="9000000001", password_hash="x")
    db.add(customer)
    db.flush()
    day = date(2026, 10, 27)
    post_payment_entry(
        db, customer_id=customer.id, amount=Decimal("5000"), payment_ref="U1",
        payment_comment=None, description="Payment", actor_type="admin", actor_id=1,
        actor_name="Test", payment_mode="ICICI", value_date=day,
    )
    db.commit()
    clashes = same_payment_clashes(
        db, ArLedgerEntry, party_field="customer_id", party_id=customer.id,
        amount=Decimal("5000.00"), pay_day=day, payment_mode="ICICI",
    )
    assert len(clashes) == 1
    assert clashes[0]["mode"] == "ICICI"
    other_bank = same_payment_clashes(
        db, ArLedgerEntry, party_field="customer_id", party_id=customer.id,
        amount=Decimal("5000"), pay_day=day, payment_mode="Cash",
    )
    assert other_bank == []
    db.close()
