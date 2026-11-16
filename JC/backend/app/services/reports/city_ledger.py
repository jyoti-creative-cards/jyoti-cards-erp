"""Parties in one city, and their customer ledgers together."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from pypdf import PdfReader, PdfWriter
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.city import City
from app.models.customer import Customer
from app.services.ar_ledger import build_ar_ledger, list_ar_customers
from app.services.reports.pdfs import render_ar_statement_pdf


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())


def parties_in_city(db: Session, city_query: str) -> dict:
    query = _clean(city_query)
    if not query:
        return {"city": None, "cities": [], "parties": []}
    cities = (
        db.query(City)
        .filter(City.deleted_at.is_(None), City.name.ilike(f"%{query}%"))
        .order_by(City.name.asc())
        .limit(30)
        .all()
    )
    exact = [row for row in cities if row.name.casefold() == query.casefold()]
    chosen = exact[0] if len(exact) == 1 else (cities[0] if len(cities) == 1 else None)
    if chosen is None:
        return {
            "city": None,
            "cities": [{"id": row.id, "name": row.name} for row in cities],
            "parties": [],
        }
    dues = {
        int(row["customer_id"]): Decimal(str(row["outstanding"] or 0))
        for row in list_ar_customers(db)
    }
    parties = (
        db.query(Customer)
        .filter(
            Customer.city_id == chosen.id,
            Customer.deleted_at.is_(None),
            Customer.is_active.is_(True),
        )
        .order_by(func.lower(Customer.business_name).asc(), Customer.id.asc())
        .all()
    )
    return {
        "city": {"id": chosen.id, "name": chosen.name},
        "cities": [],
        "parties": [
            {
                "id": party.id,
                "business_name": party.business_name,
                "phone": party.phone or "",
                "party_number": party.party_number,
                "outstanding": format(dues.get(party.id, Decimal("0.00")), "f"),
            }
            for party in parties
        ],
    }


def _city_or_error(db: Session, city_id: int) -> City:
    city = db.get(City, city_id)
    if city is None or city.deleted_at:
        raise ValueError("city not found")
    return city


def _parties(db: Session, city_id: int) -> list[Customer]:
    return (
        db.query(Customer)
        .filter(
            Customer.city_id == city_id,
            Customer.deleted_at.is_(None),
            Customer.is_active.is_(True),
        )
        .order_by(func.lower(Customer.business_name).asc(), Customer.id.asc())
        .all()
    )


def city_ledgers_pdf(
    db: Session,
    city_id: int,
    from_date: date | None,
    to_date: date | None,
) -> tuple[bytes, str]:
    city = _city_or_error(db, city_id)
    writer = PdfWriter()
    pages = 0
    for party in _parties(db, city.id):
        data = render_ar_statement_pdf(
            db, party.id, from_date=from_date, to_date=to_date,
        )
        reader = PdfReader(BytesIO(data))
        if not reader.pages:
            continue
        for page in reader.pages:
            writer.add_page(page)
            pages += 1
    if pages == 0:
        raise ValueError("no ledgers for this city")
    out = BytesIO()
    writer.write(out)
    return out.getvalue(), city.name


def city_ledgers_xlsx(
    db: Session,
    city_id: int,
    from_date: date | None,
    to_date: date | None,
) -> tuple[bytes, str]:
    from app.services.reports.pdfs import _entry_in_span

    city = _city_or_error(db, city_id)
    dues = {
        int(row["customer_id"]): Decimal(str(row["outstanding"] or 0))
        for row in list_ar_customers(db)
    }
    book = Workbook()
    summary = book.active
    summary.title = "Parties"
    summary.append(["Party", "Phone", "Number", "Balance"])
    lines = book.create_sheet("Ledgers")
    lines.append(["Party", "Date", "Type", "Particulars", "Amount", "Balance"])
    for party in _parties(db, city.id):
        summary.append([
            party.business_name,
            party.phone or "",
            party.party_number or "",
            float(dues.get(party.id, Decimal("0.00"))),
        ])
        entries = build_ar_ledger(db, party.id)
        entries = [row for row in entries if not row.get("on_agent")]
        entries = [row for row in entries if _entry_in_span(row, from_date, to_date)]
        for row in entries:
            when = row.get("value_date") or row.get("display_date") or row.get("created_at")
            when_text = when.isoformat()[:10] if hasattr(when, "isoformat") else str(when or "")[:10]
            amount = row.get("display_amount")
            if amount in (None, ""):
                amount = row.get("signed_amount")
            lines.append([
                party.business_name,
                when_text,
                row.get("entry_type") or "",
                row.get("display_name") or row.get("description") or "",
                float(amount or 0),
                float(row.get("running_balance") or 0),
            ])
    buf = BytesIO()
    book.save(buf)
    return buf.getvalue(), city.name
