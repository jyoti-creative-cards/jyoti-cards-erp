"""Party ledger PDF can print only one chosen date."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.customer import Customer
from app.services.ar_ledger import post_bill_entry, post_payment_entry
from app.services.reports.pdfs import render_ar_statement_pdf


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


def test_ar_pdf_one_day_omits_other_dates(db):
    cust = Customer(business_name="Party 223", phone="9876500223", password_hash="x")
    db.add(cust)
    db.flush()
    post_bill_entry(
        db,
        customer_id=cust.id,
        bill_id=1,
        amount=Decimal("100"),
        description="Bill Nov 1",
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        value_date=date(2026, 11, 1),
    )
    post_payment_entry(
        db,
        customer_id=cust.id,
        amount=Decimal("40"),
        payment_ref="CASH",
        payment_comment=None,
        description="Pay Nov 8",
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        value_date=date(2026, 11, 8),
    )
    db.commit()
    from io import BytesIO
    from pypdf import PdfReader

    def pdf_text(data: bytes) -> str:
        return "".join((page.extract_text() or "") for page in PdfReader(BytesIO(data)).pages)

    full = pdf_text(render_ar_statement_pdf(db, cust.id))
    one = pdf_text(render_ar_statement_pdf(db, cust.id, day=date(2026, 11, 8)))
    span = pdf_text(render_ar_statement_pdf(db, cust.id, from_date=date(2026, 11, 1), to_date=date(2026, 11, 1)))
    assert "2026-11-01" in full
    assert "2026-11-08" in one
    assert "2026-11-01" not in one
    assert "2026-11-08" in full
    assert "2026-11-01" in span
    assert "2026-11-08" not in span
