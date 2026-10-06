"""Expense heads and sub-heads file each expense, and each has a ledger."""
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.expense import Expense, ExpenseHead, ExpenseSubhead
from app.routers.expenses import ExpenseIn, expense_head_tree, resolve_expense_category
from app.services.reports_extended import expense_ledger_detail


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_head_and_subhead_each_have_a_ledger():
    db = _db()
    head = ExpenseHead(name="Rent")
    db.add(head)
    db.flush()
    office = ExpenseSubhead(head_id=head.id, name="Office")
    shop = ExpenseSubhead(head_id=head.id, name="Shop")
    db.add_all([office, shop])
    db.flush()
    category = resolve_expense_category(db, ExpenseIn(
        expense_date=date(2026, 8, 1), amount=Decimal("85"), head_id=head.id, subhead_id=office.id,
    ))
    assert category == "rent / office"
    by_sub_only = resolve_expense_category(db, ExpenseIn(
        expense_date=date(2026, 8, 1), amount=Decimal("85"), subhead_id=office.id,
    ))
    assert by_sub_only == "rent / office"
    db.add(Expense(
        expense_date=date(2026, 8, 1), category=category, amount=Decimal("85"),
        created_by_name="Admin",
    ))
    db.add(Expense(
        expense_date=date(2026, 8, 2), category="rent / shop", amount=Decimal("15"),
        created_by_name="Admin",
    ))
    db.commit()
    tree = expense_head_tree(db)
    assert tree[0]["name"] == "Rent"
    assert tree[0]["total"] == "100.00"
    assert tree[0]["count"] == 2
    by_name = {s["name"]: s for s in tree[0]["subheads"]}
    assert by_name["Office"]["total"] == "85.00"
    assert by_name["Office"]["category"] == "rent / office"
    office_book = expense_ledger_detail(db, "rent / office")
    assert office_book["outstanding"] == "85.00"
    assert len(office_book["entries"]) == 1
    head_book = expense_ledger_detail(db, "Rent")
    assert head_book["outstanding"] == "100.00"
    assert len(head_book["entries"]) == 2
    db.close()
