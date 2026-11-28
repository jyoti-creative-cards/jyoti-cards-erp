"""Many expenses save together on the chosen date, or not at all."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.expense import Expense, ExpenseHead, ExpenseSource, ExpenseSubhead
from app.routers.expenses import ExpenseBatchIn, ExpenseBatchLine, create_expenses_batch
from app.services.reports.daybook import daybook


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _seed(db):
    source = ExpenseSource(name="Cash Register")
    head = ExpenseHead(name="Kitchen")
    db.add_all([source, head])
    db.flush()
    sub = ExpenseSubhead(head_id=head.id, name="Tea")
    db.add(sub)
    db.flush()
    return source, sub


def test_batch_stores_the_chosen_date_and_the_day_book_uses_it():
    db = _db()
    source, sub = _seed(db)
    rows = create_expenses_batch(db, ExpenseBatchIn(
        expense_date=date(2026, 1, 15),
        lines=[
            ExpenseBatchLine(source_id=source.id, subhead_id=sub.id, description="Milk", amount=Decimal("40"), reference="morning"),
            ExpenseBatchLine(source_id=source.id, subhead_id=sub.id, description="Sugar", amount=Decimal("10")),
        ],
    ), "Anita")
    db.commit()
    assert [r.expense_date for r in rows] == [date(2026, 1, 15), date(2026, 1, 15)]
    assert rows[0].description == "Milk"
    assert rows[0].reference == "morning"
    assert rows[0].category == "kitchen / tea"
    assert rows[0].source_id == source.id
    assert rows[1].reference is None
    book = daybook(db, from_date=date(2026, 1, 15), to_date=date(2026, 1, 15))
    labels = [r["label"] for r in book["entries"] if r["kind"] == "expense"]
    assert set(labels) == {"Milk", "Sugar"}
    assert all(r["at"] == "2026-01-15" for r in book["entries"] if r["kind"] == "expense")
    db.close()


def test_one_bad_row_saves_nothing():
    db = _db()
    source, sub = _seed(db)
    with pytest.raises(HTTPException):
        create_expenses_batch(db, ExpenseBatchIn(
            expense_date=date(2026, 1, 15),
            lines=[
                ExpenseBatchLine(source_id=source.id, subhead_id=sub.id, description="Milk", amount=Decimal("40")),
                ExpenseBatchLine(source_id=source.id, subhead_id=sub.id, description="Sugar", amount=Decimal("0")),
            ],
        ), "Anita")
    db.rollback()
    assert db.query(Expense).count() == 0
    db.close()