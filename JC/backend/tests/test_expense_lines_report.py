"""The expense report filters by date, subcategory, and paid from, and the PDF is that list."""
from datetime import date
from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.expense import Expense, ExpenseSource
from app.services.reports.extended import expense_lines
from app.services.reports.pdfs import render_expense_lines_pdf


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_filters_return_every_match_and_the_pdf_is_that_list():
    db = _db()
    cash = ExpenseSource(name="Cash Register")
    bank = ExpenseSource(name="ICICI")
    db.add_all([cash, bank])
    db.flush()
    db.add_all([
        Expense(expense_date=date(2026, 1, 15), category="kitchen / tea", description="Milk", reference="morning", amount=Decimal("40"), source_id=cash.id, created_by_name="Anita"),
        Expense(expense_date=date(2026, 1, 15), category="kitchen / tea", description="Sugar", amount=Decimal("10"), source_id=bank.id, created_by_name="Anita"),
        Expense(expense_date=date(2026, 2, 1), category="kitchen / tea", description="Biscuits", amount=Decimal("20"), source_id=cash.id, created_by_name="Anita"),
    ])
    db.commit()
    data = expense_lines(db, date(2026, 1, 1), date(2026, 1, 31), "kitchen / tea", cash.id)
    assert [row["description"] for row in data["items"]] == ["Milk"]
    assert data["items"][0]["date"] == "2026-01-15"
    assert data["items"][0]["source_name"] == "Cash Register"
    assert data["items"][0]["reference"] == "morning"
    assert data["total"] == "40.00"
    pdf = render_expense_lines_pdf(db, date(2026, 1, 1), date(2026, 1, 31), "kitchen / tea", cash.id)
    text = "\n".join((page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages)
    assert "Milk" in text
    assert "Sugar" not in text
    assert "2026-01-15" in text
    db.close()
