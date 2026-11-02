"""Freight payments keep a date, can be edited, and adjustments land on expenses."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.expense import Expense
from app.models.freight_agent import FreightAgent, FreightLedgerEntry
from app.routers.freight_agents import FreightAdjustIn, FreightEntryEditIn, adjust_freight_agent, edit_freight_entry
from app.services.freight_ledger import post_freight_charge

_ = FreightLedgerEntry


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


def _auth():
    return AuthContext(actor_type="admin", actor_id=1, actor_name="Test")


def test_adjustment_uses_the_head_on_the_ledger_and_the_expense(db):
    agent = FreightAgent(name="Vishnu", balance_due=Decimal("0"))
    db.add(agent)
    db.flush()
    post_freight_charge(db, agent_id=agent.id, amount=Decimal("100"), customer_bill_id=None, notes="bill", actor_name="Test")
    db.commit()
    adjust_freight_agent(
        agent.id,
        FreightAdjustIn(head="Short", amount=Decimal("20"), direction="owe_less", pay_date=date(2026, 11, 1)),
        db,
        _auth(),
    )
    entry = db.query(FreightLedgerEntry).filter(FreightLedgerEntry.entry_type == "adjustment").one()
    expense = db.get(Expense, entry.expense_id)
    assert entry.head == "Short"
    assert entry.value_date == date(2026, 11, 1)
    assert entry.amount == Decimal("-20.00")
    assert expense.category == "Short"
    assert expense.expense_date == date(2026, 11, 1)
    assert "Short" in expense.description
    assert agent.balance_due == Decimal("80.00")


def test_editing_a_payment_changes_the_amount_and_the_date(db):
    agent = FreightAgent(name="Vishnu", balance_due=Decimal("0"))
    db.add(agent)
    db.flush()
    post_freight_charge(db, agent_id=agent.id, amount=Decimal("100"), customer_bill_id=None, notes="bill", actor_name="Test")
    from app.routers.freight_agents import FreightSettleIn, settle_freight_agent
    settle_freight_agent(
        agent.id,
        FreightSettleIn(amount=Decimal("40"), transaction_ref="UTR1", pay_date=date(2026, 11, 1)),
        db,
        _auth(),
    )
    entry = db.query(FreightLedgerEntry).filter(FreightLedgerEntry.entry_type == "settlement").one()
    edit_freight_entry(
        entry.id,
        FreightEntryEditIn(amount=Decimal("55"), pay_date=date(2026, 10, 31)),
        db,
        _auth(),
    )
    db.refresh(entry)
    db.refresh(agent)
    expense = db.get(Expense, entry.expense_id)
    assert entry.amount == Decimal("-55.00")
    assert entry.value_date == date(2026, 10, 31)
    assert expense.amount == Decimal("55.00")
    assert expense.expense_date == date(2026, 10, 31)
    assert db.query(FreightLedgerEntry).filter(FreightLedgerEntry.entry_type == "settlement").count() == 1
    assert agent.balance_due == Decimal("45.00")
