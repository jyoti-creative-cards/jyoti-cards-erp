"""Print all invoice must keep the PDF that was just rendered for that day."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.routers import share


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


def _pdf() -> bytes:
    buf = BytesIO()
    sheet = canvas.Canvas(buf)
    sheet.drawString(72, 720, "duplicate")
    sheet.save()
    return buf.getvalue()


class _OpenSession:
    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        if name == "close":
            return lambda: None
        return getattr(self._session, name)


def test_duplicate_day_job_keeps_the_rendered_pdf(db, monkeypatch):
    customer = Customer(business_name="Print Co", phone="9333333333", password_hash="x")
    db.add(customer)
    db.flush()
    bill = CustomerBill(
        customer_id=customer.id,
        bill_number="B-PRINT-1",
        subtotal_inclusive=Decimal("100"),
        grand_total=Decimal("100"),
        created_by_type="admin",
        created_by_name="Test",
    )
    db.add(bill)
    db.commit()
    bill_id = int(bill.id)
    db.expunge_all()
    pdf = _pdf()

    def fake_generate(session, bill_id, **kwargs):
        row = session.get(CustomerBill, bill_id)
        row._pdf_bytes = pdf
        return None

    monkeypatch.setattr("app.db.session.SessionLocal", lambda: _OpenSession(db))
    monkeypatch.setattr("app.services.doc_gen.generate_customer_bill_document", fake_generate)
    job_id = "dup-test"
    with share._dup_guard:
        share._dup_jobs[job_id] = {
            "state": "running",
            "done": 0,
            "total": 1,
            "failed": [],
            "pdf": None,
            "created": 0,
            "filename": "duplicates.pdf",
        }
    try:
        share._build_duplicate_day(job_id, [bill_id])
        job = share._dup_job(job_id)
        assert job["state"] == "ready"
        assert job["pdf"].startswith(b"%PDF")
    finally:
        with share._dup_guard:
            share._dup_jobs.pop(job_id, None)
