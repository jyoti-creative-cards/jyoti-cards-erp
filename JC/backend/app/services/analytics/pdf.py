"""Landscape tables for the admin analytics screens."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.services.analytics.core import party_activity_report, sale_balance_report, stock_report, threshold_list
from app.services.pdf_documents import add_page_number


def stock_pdf(db: Session, *, from_date: Optional[date], categories: list[str], year_group: str) -> bytes:
    data = stock_report(db, from_date=from_date, categories=categories, year_group=year_group)
    headers = [
        "Item", "Alias", "Party", "Category 1", "Category 2", "Category 3",
        "Bills", "Inward", "Outward", "Closing stock", "Closing value", "%", "Last received",
    ]
    rows = [[
        row["item"], row["alias"], row["party"], row["category_1"], row["category_2"], row["category_3"],
        row["bills"], row["inward"], row["outward"], row["closing_stock"], row["closing_value"],
        row["percent"], row["last_received"],
    ] for row in data["items"]]
    title = "Stock management"
    note = f"{data['from_date'] or 'Start'} to {data['to_date']}. Closing stock is today's godown quantity, valued at the purchase rate."
    return _table(title, note, headers, rows, wide=True)


def sale_pdf(db: Session, *, from_date: Optional[date], to_date: Optional[date]) -> bytes:
    data = sale_balance_report(db, from_date=from_date, to_date=to_date)
    headers = ["Party", "City", "Sale", "Balance", "Collected %", "Last payment", "Receipts"]
    rows = [[
        row["party"], row["city"], row["sale"], row["balance"], row["collected_percent"],
        row["last_payment"], row["receipts"],
    ] for row in data["items"]]
    note = f"{data['from_date'] or 'Start'} to {data['to_date']}. Collected % is money already received, divided by sale."
    return _table("Sale to balance", note, headers, rows, wide=True)


def party_pdf(db: Session, *, from_date: Optional[date], to_date: Optional[date]) -> bytes:
    data = party_activity_report(db, from_date=from_date, to_date=to_date)
    headers = ["Party", "City", "Bills", "Sale", "Albums sent", "Balance", "Last payment"]
    rows = [[
        row["party"], row["city"], row["bills"], row["sale"], row["albums"], row["balance"], row["last_payment"],
    ] for row in data["items"]]
    note = f"{data['from_date'] or 'Start'} to {data['to_date']}. Active parties only. Last payment is the latest receipt."
    return _table("Parties", note, headers, rows, wide=True)


def threshold_pdf(db: Session, *, q: str = "") -> bytes:
    data = threshold_list(db, q=q)
    headers = ["Item", "Alias", "Party", "Received", "Closing stock", "Alert %", "Below"]
    rows = [[
        row["item"], row["alias"], row["party"], row["inward"], row["closing_stock"],
        row["percent"], "Yes" if row["below"] else "",
    ] for row in data["items"]]
    return _table("Item threshold", "Today's stock under the alert percent of everything received so far.", headers, rows, wide=True)


def _table(title: str, note: str, headers: list, rows: list, *, wide: bool) -> bytes:
    styles = getSampleStyleSheet()
    small = styles["Normal"].clone("an")
    small.fontName = "Helvetica"
    small.fontSize = 7
    small.leading = 9
    head = styles["Normal"].clone("anh")
    head.fontName = "Helvetica-Bold"
    head.fontSize = 7
    head.leading = 9
    body = []
    body.append(Paragraph(escape(title), styles["Heading2"]))
    body.append(Paragraph(escape(note), small))
    body.append(Spacer(1, 3 * mm))
    grid = [[Paragraph(escape(str(cell)), head) for cell in headers]]
    for row in rows:
        grid.append([Paragraph(escape(str(cell if cell is not None else "")), small) for cell in row])
    if len(grid) == 1:
        grid.append([Paragraph("Nothing in this list.", small)] + [""] * (len(headers) - 1))
    table = Table(grid, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("GRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    body.append(table)
    buf = BytesIO()
    page = landscape(A4) if wide else A4
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=8 * mm, rightMargin=8 * mm, topMargin=10 * mm, bottomMargin=10 * mm)
    doc.build(body, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return buf.getvalue()
