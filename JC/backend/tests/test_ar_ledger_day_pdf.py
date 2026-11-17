"""Party ledger PDF can print only one chosen date."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
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


def test_ar_pdf_hides_cancelled_bills(db):
    cust = Customer(business_name="Party 224", phone="9876500224", password_hash="x")
    db.add(cust)
    db.flush()
    kept = CustomerBill(
        customer_id=cust.id, bill_number="KEEP9", subtotal_inclusive=Decimal("80"),
        discount_amount=0, taxable_value=0, gst_amount=0, grand_total=Decimal("80"),
        created_by_type="admin", created_by_name="Test",
    )
    gone = CustomerBill(
        customer_id=cust.id, bill_number="GONE9", subtotal_inclusive=Decimal("20"),
        discount_amount=0, taxable_value=0, gst_amount=0, grand_total=Decimal("20"),
        created_by_type="admin", created_by_name="Test",
        cancelled_at=datetime.now(timezone.utc),
    )
    db.add_all([kept, gone])
    db.flush()
    post_bill_entry(
        db, customer_id=cust.id, bill_id=kept.id, amount=Decimal("80"), description="Bill KEEP9",
        actor_type="admin", actor_id=1, actor_name="Test", value_date=date(2026, 11, 2),
    )
    post_bill_entry(
        db, customer_id=cust.id, bill_id=gone.id, amount=Decimal("0"), description="Bill GONE9 cancelled",
        actor_type="admin", actor_id=1, actor_name="Test", value_date=date(2026, 11, 3),
    )
    db.commit()
    from io import BytesIO
    from pypdf import PdfReader

    text = "".join((page.extract_text() or "") for page in PdfReader(BytesIO(render_ar_statement_pdf(db, cust.id))).pages)
    assert "KEEP9" in text
    assert "GONE9" not in text
