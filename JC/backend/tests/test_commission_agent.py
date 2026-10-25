"""A commission agent's parties keep the order, and the bill due sits on the agent."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.accounts_receivable import ArLedgerEntry
from app.models.commission_agent import CommissionAgent
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.services.ar_ledger import customer_ar_totals
from app.services.commission_ledger import agent_outstanding, post_customer_bill_due, receive_agent_payment, sync_bill_due
from app.services.customer_bill_pdf import render_customer_bill_pdf

DAY = date(2026, 10, 23)
WHEN = datetime(2026, 10, 23, 6, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_bill_due_sits_on_the_agent_and_a_lump_payment_is_not_split(db):
    agent = CommissionAgent(name="Mohd Bhai", phone="9000001111")
    db.add(agent)
    db.flush()
    party = Customer(
        business_name="Paliwal", phone="9000002222", password_hash="x", commission_agent_id=agent.id,
    )
    db.add(party)
    db.flush()
    bill = CustomerBill(
        customer_id=party.id, bill_number="B1", subtotal_inclusive=500, discount_amount=0,
        taxable_value=500, gst_amount=0, grand_total=500, created_by_type="admin",
        created_by_name="T", bill_date=DAY, created_at=WHEN,
    )
    db.add(bill)
    db.flush()

    post_customer_bill_due(
        db, bill=bill, customer=party, amount=Decimal("500"),
        description="Bill B1", actor_type="admin", actor_id=None, actor_name="T",
        value_date=DAY, created_at=WHEN,
    )
    db.commit()

    assert bill.commission_agent_id == agent.id
    assert customer_ar_totals(db, party.id)["outstanding"] == Decimal("0")
    assert agent_outstanding(db, agent.id) == Decimal("500.00")

    receive_agent_payment(
        db, agent_id=agent.id, amount=Decimal("500"), note=None,
        actor_type="admin", actor_id=None, actor_name="T", value_date=DAY,
    )
    db.commit()
    assert agent_outstanding(db, agent.id) == Decimal("0.00")
    assert customer_ar_totals(db, party.id)["outstanding"] == Decimal("0")


def test_direct_bill_stays_on_the_party_even_when_an_agent_is_mapped(db):
    agent = CommissionAgent(name="Collector", phone="9000004444")
    db.add(agent)
    db.flush()
    party = Customer(
        business_name="Direct Shop", phone="9000005555", password_hash="x", commission_agent_id=agent.id,
    )
    db.add(party)
    db.flush()
    bill = CustomerBill(
        customer_id=party.id, bill_number="B9", subtotal_inclusive=120, discount_amount=0,
        taxable_value=120, gst_amount=0, grand_total=120, created_by_type="admin",
        created_by_name="T", bill_date=DAY, created_at=WHEN,
    )
    db.add(bill)
    db.flush()
    post_customer_bill_due(
        db, bill=bill, customer=party, amount=Decimal("120"),
        description="Bill B9", actor_type="admin", actor_id=None, actor_name="T",
        on_agent=False,
    )
    db.commit()
    assert bill.commission_agent_id is None
    assert customer_ar_totals(db, party.id)["outstanding"] == Decimal("120.00")
    assert agent_outstanding(db, agent.id) == Decimal("0.00")


def test_agent_bill_shows_on_the_party_ledger_without_adding_to_the_balance(db):
    from app.services.ar_ledger import build_ar_ledger

    agent = CommissionAgent(name="Collector", phone="9000006666")
    db.add(agent)
    db.flush()
    party = Customer(
        business_name="Shown Shop", phone="9000007777", password_hash="x", commission_agent_id=agent.id,
    )
    db.add(party)
    db.flush()
    bill = CustomerBill(
        customer_id=party.id, bill_number="B10", subtotal_inclusive=40, discount_amount=0,
        taxable_value=40, gst_amount=0, grand_total=40, created_by_type="admin",
        created_by_name="T", bill_date=DAY, created_at=WHEN,
    )
    db.add(bill)
    db.flush()
    post_customer_bill_due(
        db, bill=bill, customer=party, amount=Decimal("40"),
        description="Bill B10", actor_type="admin", actor_id=None, actor_name="T",
    )
    db.commit()
    rows = build_ar_ledger(db, party.id)
    shown = [row for row in rows if row.get("bill_id") == bill.id]
    assert len(shown) == 1
    assert shown[0]["signed_amount"] == "0.00"
    assert shown[0]["display_amount"] == "40.00"
    assert "Collector" in shown[0]["display_name"]
    assert customer_ar_totals(db, party.id)["outstanding"] == Decimal("0")


def test_moving_a_party_ledger_does_not_double_the_money(db):
    from app.services.commission_ledger import move_party_ledger_to_agent

    agent = CommissionAgent(name="Collector", phone="9000008888")
    db.add(agent)
    db.flush()
    party = Customer(business_name="Old Agent Party", phone="9000009999", password_hash="x")
    db.add(party)
    db.flush()
    bill = CustomerBill(
        customer_id=party.id, bill_number="B11", subtotal_inclusive=70, discount_amount=0,
        taxable_value=70, gst_amount=0, grand_total=70, created_by_type="admin",
        created_by_name="T", bill_date=DAY, created_at=WHEN,
    )
    db.add(bill)
    db.flush()
    db.add_all([
        ArLedgerEntry(
            customer_id=party.id, entry_type="opening_balance", amount=Decimal("30.00"),
            description="Opening", created_by_type="admin", created_by_name="T", value_date=DAY,
        ),
        ArLedgerEntry(
            customer_id=party.id, entry_type="bill", amount=Decimal("70.00"), bill_id=bill.id,
            description="Bill B11", created_by_type="admin", created_by_name="T", value_date=DAY,
        ),
        ArLedgerEntry(
            customer_id=party.id, entry_type="payment", amount=Decimal("-20.00"),
            description="Received", created_by_type="admin", created_by_name="T", value_date=DAY,
        ),
    ])
    db.commit()
    first = move_party_ledger_to_agent(db, customer_id=party.id, agent_id=agent.id)
    db.commit()
    assert first["before_party"] == "80.00"
    assert first["after_party"] == "0.00"
    assert first["after_agent"] == "80.00"
    assert bill.commission_agent_id == agent.id
    second = move_party_ledger_to_agent(db, customer_id=party.id, agent_id=agent.id)
    db.commit()
    assert second["moved"] == 0
    assert agent_outstanding(db, agent.id) == Decimal("80.00")
    assert customer_ar_totals(db, party.id)["outstanding"] == Decimal("0")


def test_a_party_without_an_agent_still_owes_the_bill(db):
    party = Customer(business_name="Direct", phone="9000003333", password_hash="x")
    db.add(party)
    db.flush()
    bill = CustomerBill(
        customer_id=party.id, bill_number="B2", subtotal_inclusive=80, discount_amount=0,
        taxable_value=80, gst_amount=0, grand_total=80, created_by_type="admin",
        created_by_name="T", bill_date=DAY, created_at=WHEN,
    )
    db.add(bill)
    db.flush()
    post_customer_bill_due(
        db, bill=bill, customer=party, amount=Decimal("80"),
        description="Bill B2", actor_type="admin", actor_id=None, actor_name="T",
        value_date=DAY, created_at=WHEN,
    )
    db.commit()
    assert bill.commission_agent_id is None
    assert customer_ar_totals(db, party.id)["outstanding"] == Decimal("80.00")


def test_cancelling_an_agent_bill_clears_his_due(db):
    agent = CommissionAgent(name="Mohd Bhai", phone="9000001111")
    db.add(agent)
    db.flush()
    party = Customer(
        business_name="Paliwal", phone="9000004444", password_hash="x", commission_agent_id=agent.id,
    )
    db.add(party)
    db.flush()
    bill = CustomerBill(
        customer_id=party.id, bill_number="B3", subtotal_inclusive=500, discount_amount=0,
        taxable_value=500, gst_amount=0, grand_total=500, created_by_type="admin",
        created_by_name="T", bill_date=DAY, created_at=WHEN,
    )
    db.add(bill)
    db.flush()
    post_customer_bill_due(
        db, bill=bill, customer=party, amount=Decimal("500"),
        description="Bill B3", actor_type="admin", actor_id=None, actor_name="T",
        value_date=DAY, created_at=WHEN,
    )
    sync_bill_due(db, bill=bill, amount=Decimal("0"), description="cancelled")
    db.commit()
    assert agent_outstanding(db, agent.id) == Decimal("0.00")


def test_agent_bill_prints_his_name_large_and_the_party_small():
    from datetime import datetime, timezone
    from io import BytesIO
    from pypdf import PdfReader
    pdf = render_customer_bill_pdf(
        bill_id=1,
        order_id=1,
        bill_number="B9",
        customer_name="Paliwal Printing",
        customer_company=None,
        customer_city="Kasrawad",
        totals={
            "gst_enabled": False,
            "lines": [{
                "catalog_product_id": 1,
                "our_product_id": "9443",
                "name": "9443",
                "quantity": 10,
                "rate_inclusive": "50.00",
                "unit_price": "50.00",
                "line_total": "500.00",
            }],
            "subtotal_inclusive": "500.00",
            "grand_total": "500.00",
            "rounded_grand_total": "500.00",
        },
        generated_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
        invoice_date=date(2026, 10, 23),
        agent_name="Mohd Bhai",
        agent_phone="9000001111",
    )
    text = "\n".join((page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages)
    assert "Mohd Bhai" in text
    assert "Party : Paliwal Printing, Kasrawad" in text
