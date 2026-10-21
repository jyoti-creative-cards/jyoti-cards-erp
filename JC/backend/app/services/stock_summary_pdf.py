"""Printed daily stock summary. Same columns as the Tally stock group summary, plus vendor."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.services.company_info import COMPANY_NAME
from app.services.reports_extra.stock_group_summary import split_summary_pages, stock_group_summary


def _indian(value: Decimal) -> str:
    negative = value < 0
    whole, frac = f"{abs(value):.2f}".split(".")
    if len(whole) <= 3:
        grouped = whole
    else:
        head, tail = whole[:-3], whole[-3:]
        parts: list[str] = []
        while len(head) > 2:
            parts.append(head[-2:])
            head = head[:-2]
        if head:
            parts.append(head)
        grouped = ",".join(reversed(parts)) + "," + tail
    text = f"{grouped}.{frac}"
    return f"(-){text}" if negative else text


def _qty(raw, *, always: bool = False) -> str:
    if raw is None or raw == "":
        return "0.00 pcs" if always else ""
    number = Decimal(str(raw))
    if number == 0 and not always:
        return ""
    return f"{_indian(number)} pcs"


def _amt(raw, *, always: bool = False) -> str:
    if raw is None or raw == "":
        return "0.00" if always else ""
    number = Decimal(str(raw))
    if number == 0 and not always:
        return ""
    return _indian(number)


def _count(raw) -> str:
    number = int(raw or 0)
    return str(number) if number else ""


def render_stock_summary_pdf(
    db: Session,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    page_rows: int = 22,
) -> bytes:
    data = stock_group_summary(db, from_date, to_date)
    return render_stock_summary_pdf_from(data, page_rows=page_rows)


def render_stock_summary_pdf_from(data: dict, page_rows: int = 22) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=8 * mm,
        rightMargin=8 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
        title="Stock Summary",
    )
    title = ParagraphStyle("sum-title", fontName="Helvetica-Bold", fontSize=12, alignment=TA_CENTER, leading=14)
    sub = ParagraphStyle("sum-sub", fontName="Helvetica-Bold", fontSize=10, alignment=TA_CENTER, leading=12)
    meta = ParagraphStyle("sum-meta", fontName="Helvetica", fontSize=8, alignment=TA_RIGHT, leading=10)
    continued = ParagraphStyle("sum-cont", fontName="Helvetica-Oblique", fontSize=8, alignment=TA_RIGHT, leading=10)
    cell = ParagraphStyle("sum-cell", fontName="Helvetica", fontSize=7, leading=8)
    cell_bold = ParagraphStyle("sum-cell-b", fontName="Helvetica-Bold", fontSize=7, leading=8)

    items = data.get("items") or []
    pages = split_summary_pages(items, page_rows)
    totals = data.get("totals") or {}
    story = []
    carried_qty = {"in": Decimal("0"), "out": Decimal("0"), "close": Decimal("0")}
    carried_val = {"in": Decimal("0"), "out": Decimal("0"), "close": Decimal("0")}

    for index, page_items in enumerate(pages):
        story.append(Paragraph(f"Printed on {data.get('printed_on') or ''}", meta))
        story.append(Paragraph(COMPANY_NAME, title))
        story.append(Paragraph("Stock Summary", sub))
        story.append(Paragraph(f"{data.get('period') or ''} · Page {index + 1}", sub))
        story.append(Spacer(1, 4))
        brought = None
        if index > 0:
            brought = (carried_qty.copy(), carried_val.copy())
        for item in page_items:
            for key, field in (("in", "in_qty"), ("out", "out_qty"), ("close", "close_qty")):
                carried_qty[key] += Decimal(str(item.get(field) or 0))
            for key, field in (("in", "in_value"), ("out", "out_value"), ("close", "close_value")):
                carried_val[key] += Decimal(str(item.get(field) or 0))
        last = index == len(pages) - 1
        story.append(_table(
            page_items,
            brought=brought,
            carried=None if last else (carried_qty, carried_val),
            grand=totals if last else None,
            cell=cell,
            cell_bold=cell_bold,
        ))
        if not last:
            story.append(Spacer(1, 4))
            story.append(Paragraph("continued ...", continued))
            story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()


def _table(items, *, brought, carried, grand, cell, cell_bold) -> Table:
    header = [
        [
            "Particulars", "Vendor", "Total\nSales",
            "Inwards", "", "",
            "Outwards", "", "",
            "Closing Balance", "", "",
        ],
        [
            "", "", "",
            "Quantity", "Rate", "Value",
            "Quantity", "Rate", "Value",
            "Quantity", "Rate", "Value",
        ],
    ]
    rows = header[:]
    spans = [
        ("SPAN", (0, 0), (0, 1)),
        ("SPAN", (1, 0), (1, 1)),
        ("SPAN", (2, 0), (2, 1)),
        ("SPAN", (3, 0), (5, 0)),
        ("SPAN", (6, 0), (8, 0)),
        ("SPAN", (9, 0), (11, 0)),
    ]
    if brought:
        rows.append(_total_row("Brought Forward", brought[0], brought[1], cell_bold))
    for item in items:
        rows.append([
            Paragraph(item.get("particular") or "", cell),
            Paragraph(item.get("vendor_name") or "", cell),
            _count(item.get("sales_count")),
            _qty(item.get("in_qty")),
            _amt(item.get("in_rate")),
            _amt(item.get("in_value")),
            _qty(item.get("out_qty")),
            _amt(item.get("out_rate")),
            _amt(item.get("out_value")),
            _qty(item.get("close_qty")),
            _amt(item.get("close_rate")),
            _amt(item.get("close_value")),
        ])
    if carried:
        rows.append(_total_row("Carried Over", carried[0], carried[1], cell_bold))
    if grand:
        rows.append(_total_row("Grand Total", {
            "in": grand.get("in_qty"),
            "out": grand.get("out_qty"),
            "close": grand.get("close_qty"),
        }, {
            "in": grand.get("in_value"),
            "out": grand.get("out_value"),
            "close": grand.get("close_value"),
        }, cell_bold, always=True))

    widths = [52 * mm, 32 * mm, 14 * mm, 22 * mm, 14 * mm, 20 * mm, 22 * mm, 14 * mm, 20 * mm, 24 * mm, 14 * mm, 22 * mm]
    table = Table(rows, colWidths=widths, repeatRows=2)
    style = [
        ("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 1), 7),
        ("FONTSIZE", (0, 2), (-1, -1), 7),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (3, 0), (5, 0), "CENTER"),
        ("ALIGN", (6, 0), (8, 0), "CENTER"),
        ("ALIGN", (9, 0), (11, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#94a3b8")),
        ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#f8fafc")),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]
    style.extend(spans)
    if grand or carried or brought:
        style.append(("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"))
    table.setStyle(TableStyle(style))
    return table


def _total_row(label, qty, value, cell_bold, always: bool = False):
    return [
        Paragraph(label, cell_bold),
        "",
        "",
        _qty(qty["in"], always=always),
        "",
        _amt(value["in"], always=always),
        _qty(qty["out"], always=always),
        "",
        _amt(value["out"], always=always),
        _qty(qty["close"], always=always),
        "",
        _amt(value["close"], always=always),
    ]
