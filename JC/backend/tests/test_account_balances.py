"""Each payment account has its own balance. A subcategory has its own total."""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.accounts_payable import ApLedgerEntry
from app.models.accounts_receivable import ArLedgerEntry
from app.models.expense import Expense, ExpenseHead, ExpenseSource, ExpenseSubhead
from app.models.freight_agent import FreightLedgerEntry
from app.models.payment_mode import PaymentMode
from app.routers.expenses import ExpenseBatchIn, ExpenseBatchLine, create_expenses_batch
from app.services.account_balance import account_balances
from app.services.reports.extended import expense_lines


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _modes(db):
    cash = PaymentMode(name="Cash")
    bank = PaymentMode(name="ICICI")
    nc = PaymentMode(name="NC")
    db.add_all([cash, bank, nc])
    db.flush()
    return cash, bank, nc


def _pay(model, party_field, mode, amount, entry_type="payment"):
    row = model(
        entry_type=entry_type,
        amount=Decimal(amount),
        description="pay",
        payment_mode=mode,
        created_by_type="staff",
        created_by_name="Anita",
    )
    setattr(row, party_field, 1)
    return row


def _bal(data, name):
    return next(row["balance"] for row in data["accounts"] if row["name"] == name)


def test_each_account_stands_alone_and_uses_payment_amounts():
    db = _db()
    cash, bank, nc = _modes(db)
    register = ExpenseSource(name="Cash Register")
    icici_old = ExpenseSource(name="ICICI")
    nc_old = ExpenseSource(name="NC Saving Account")
    loose = ExpenseSource(name="Petty tin")
    head = ExpenseHead(name="Kitchen")
    db.add_all([register, icici_old, nc_old, loose, head])
    db.flush()
    tea = ExpenseSubhead(head_id=head.id, name="Tea")
    db.add(tea)
    db.flush()
    db.add_all([
        _pay(ArLedgerEntry, "customer_id", "Cash", "-100"),
        _pay(ArLedgerEntry, "customer_id", "  cash ", "-25"),
        _pay(ApLedgerEntry, "vendor_id", "Cash", "-40"),
        _pay(ArLedgerEntry, "customer_id", "ICICI", "-200"),
        Expense(
            expense_date=date(2026, 1, 15), category="kitchen / tea", description="Milk",
            amount=Decimal("15"), source_id=register.id, created_by_name="Anita",
        ),
        Expense(
            expense_date=date(2026, 1, 15), category="kitchen / tea", description="Sample",
            amount=Decimal("7"), source_id=register.id, is_cash=False, created_by_name="Anita",
        ),
        Expense(
            expense_date=date(2026, 1, 15), category="kitchen / tea", description="Old bank",
            amount=Decimal("5"), source_id=icici_old.id, is_cash=None, created_by_name="Anita",
        ),
        Expense(
            expense_date=date(2026, 1, 15), category="kitchen / tea", description="Old nc",
            amount=Decimal("3"), source_id=nc_old.id, created_by_name="Anita",
        ),
        Expense(
            expense_date=date(2026, 1, 15), category="kitchen / tea", description="Loose",
            amount=Decimal("9"), source_id=loose.id, created_by_name="Anita",
        ),
        FreightLedgerEntry(
            freight_agent_id=1, entry_type="settlement", amount=Decimal("-500"),
            created_by_name="Anita",
        ),
    ])
    gone = _pay(ArLedgerEntry, "customer_id", "Cash", "-80")
    gone.deleted_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.add(gone)
    reversed_pay = _pay(ArLedgerEntry, "customer_id", "ICICI", "-60")
    db.add(reversed_pay)
    db.flush()
    db.add(_pay(ArLedgerEntry, "customer_id", "ICICI", "60", entry_type="payment_reversal"))
    db.query(ArLedgerEntry).filter(ArLedgerEntry.entry_type == "payment_reversal").one().reverses_entry_id = reversed_pay.id
    db.commit()

    data = account_balances(db)
    assert _bal(data, "Cash") == "70.00"
    assert _bal(data, "ICICI") == "195.00"
    assert _bal(data, "NC") == "-3.00"
    tea_total = next(row["balance"] for row in data["categories"] if row["subhead_id"] == tea.id)
    assert tea_total == "39.00"
    loose_row = next(row for row in data["unmatched"] if row["name"] == "Petty tin")
    assert loose_row["balance"] == "-9.00"
    db.close()


def test_a_new_expense_uses_the_picked_account_and_can_exceed_the_balance():
    db = _db()
    cash, bank, _nc = _modes(db)
    head = ExpenseHead(name="Kitchen")
    db.add(head)
    db.flush()
    tea = ExpenseSubhead(head_id=head.id, name="Tea")
    db.add(tea)
    db.flush()
    db.add(_pay(ArLedgerEntry, "customer_id", "Cash", "-10"))
    db.flush()
    rows = create_expenses_batch(db, ExpenseBatchIn(
        expense_date=date(2026, 1, 15),
        lines=[ExpenseBatchLine(payment_mode_id=cash.id, subhead_id=tea.id, description="Milk", amount=Decimal("40"))],
    ), "Anita")
    db.commit()
    assert rows[0].payment_mode_id == cash.id
    data = account_balances(db)
    assert _bal(data, "Cash") == "-30.00"
    assert _bal(data, "ICICI") == "0.00"
    report = expense_lines(db, date(2026, 1, 1), date(2026, 1, 31), "kitchen / tea", payment_mode_id=cash.id)
    assert [row["description"] for row in report["items"]] == ["Milk"]
    assert report["items"][0]["source_name"] == "Cash"
    db.close()


def test_an_old_expense_is_found_under_the_matched_payment_account():
    db = _db()
    cash, _bank, _nc = _modes(db)
    register = ExpenseSource(name="cash register")
    db.add(register)
    db.flush()
    db.add(Expense(
        expense_date=date(2026, 1, 15), category="kitchen / tea", description="Milk",
        amount=Decimal("40"), source_id=register.id, created_by_name="Anita",
    ))
    db.commit()
    report = expense_lines(db, date(2026, 1, 1), date(2026, 1, 31), "", payment_mode_id=cash.id)
    assert [row["description"] for row in report["items"]] == ["Milk"]
    assert report["items"][0]["source_name"] == "Cash"
    db.close()
