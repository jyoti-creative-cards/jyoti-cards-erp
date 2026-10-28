"""Printed daily stock summary. Same columns as the Tally stock group summary, plus vendor."""

from __future__ import annotations

import html
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.services.company_info import COMPANY_NAME
from app.services.reports.stock_group_summary import stock_group_summary


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


def _whole(value: Decimal) -> str:
    negative = value < 0
    whole = f"{abs(int(value.to_integral_value()))}"
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
    return f"(-){grouped}" if negative else grouped


def _qty(raw, *, always: bool = False) -> str:
    if raw is None or raw == "":
        return "0 pcs" if always else ""
    number = Decimal(str(raw))
    if number == 0 and not always:
        return ""
    return f"{_whole(number)} pcs"


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


_FRAME_W = landscape(A4)[0] - 16 * mm
_FRAME_H = landscape(A4)[1] - 16 * mm
_NUM_HEADERS = ["Sales", "Quantity", "Rate", "Value", "Quantity", "Rate", "Value", "Quantity", "Rate", "Value"]


def render_stock_summary_pdf(
    db: Session,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    year_group: Optional[str] = None,
    page_rows: Optional[int] = None,
) -> bytes:
    data = stock_group_summary(db, from_date, to_date, year_group=year_group)
    return render_stock_summary_pdf_from(data, page_rows=page_rows)


def render_stock_summary_pdf_from(data: dict, page_rows: Optional[int] = None) -> bytes:
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
    items = data.get("items") or []
    totals = data.get("totals") or {}
    widths, name_size = _column_widths(items, totals)
    cell = ParagraphStyle("sum-cell", fontName="Helvetica", fontSize=name_size, leading=8)
    cell_bold = ParagraphStyle("sum-cell-b", fontName="Helvetica-Bold", fontSize=name_size, leading=8)
    pages = _pack_pages(items, totals, widths, cell, cell_bold, page_rows)
    story = []
    carried_qty = {"in": Decimal("0"), "out": Decimal("0"), "close": Decimal("0")}
    carried_val = {"in": Decimal("0"), "out": Decimal("0"), "close": Decimal("0")}

    for index, page_items in enumerate(pages):
        story.append(Paragraph(f"Printed on {data.get('printed_on') or ''}", meta))
        story.append(Paragraph(COMPANY_NAME, title))
        story.append(Paragraph("Stock Summary", sub))
        period = data.get("period") or ""
        if data.get("year_group"):
            period = f"{period} · Year {data['year_group']}"
        story.append(Paragraph(f"{period} · Page {index + 1}", sub))
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
            widths=widths,
        ))
        if not last:
            story.append(Spacer(1, 4))
            story.append(Paragraph("continued ...", continued))
            story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()


def _line_values(item, *, always: bool = False) -> list[str]:
    return [
        _count(item.get("sales_count")),
        _qty(item.get("in_qty"), always=always),
        _amt(item.get("in_rate"), always=always),
        _amt(item.get("in_value"), always=always),
        _qty(item.get("out_qty"), always=always),
        _amt(item.get("out_rate"), always=always),
        _amt(item.get("out_value"), always=always),
        _qty(item.get("close_qty"), always=always),
        _amt(item.get("close_rate"), always=always),
        _amt(item.get("close_value"), always=always),
    ]


def _column_widths(items, totals) -> tuple[list[float], float]:
    """Give the vendor and the item one line each. Number columns stay wide enough for the totals."""
    nums = [stringWidth(header, "Helvetica-Bold", 7) + 8 for header in _NUM_HEADERS]
    for item in items:
        for index, text in enumerate(_line_values(item)):
            nums[index] = max(nums[index], stringWidth(text, "Helvetica", 7) + 8)
    if totals:
        for index, text in enumerate(_line_values(totals, always=True)):
            nums[index] = max(nums[index], stringWidth(text, "Helvetica-Bold", 7) + 8)
    vendor_need = stringWidth("Vendor", "Helvetica-Bold", 7) + 8
    part_need = stringWidth("Particulars", "Helvetica-Bold", 7) + 8
    part_need = max(part_need, stringWidth("Brought Forward", "Helvetica-Bold", 7) + 8)
    part_need = max(part_need, stringWidth("Grand Total", "Helvetica-Bold", 7) + 8)
    for item in items:
        vendor_need = max(vendor_need, stringWidth(item.get("vendor_name") or "", "Helvetica", 7) + 8)
        part_need = max(part_need, stringWidth(item.get("particular") or "", "Helvetica", 7) + 8)
    room = _FRAME_W - sum(nums)
    if vendor_need + part_need <= room:
        extra = room - vendor_need - part_need
        return [part_need + extra, vendor_need, *nums], 7
    size = 7
    while size > 5.5 and (vendor_need + part_need) * (size / 7) > room:
        size = round(size - 0.25, 2)
    scale = size / 7
    vendor_w = vendor_need * scale
    part_w = max(room - vendor_w, 40)
    widths = [part_w, vendor_w, *nums]
    widths[-1] += _FRAME_W - sum(widths)
    return widths, size


def _one_line(text, width, style) -> Paragraph:
    raw = " ".join((text or "").split())
    limit = max(width - 6, 8)
    if stringWidth(raw, style.fontName, style.fontSize) > limit:
        while raw and stringWidth(raw + "…", style.fontName, style.fontSize) > limit:
            raw = raw[:-1]
        raw = raw.rstrip() + "…"
    return Paragraph(html.escape(raw), style)


def _table_height(table: Table) -> float:
    return table.wrap(_FRAME_W, 4000)[1]


def _pack_pages(items, totals, widths, cell, cell_bold, page_rows: Optional[int]) -> list[list]:
    """Fill each sheet. A fixed row count left a gap when later rows did not wrap."""
    if not items:
        return [[]]
    cap = int(page_rows) if page_rows else len(items)
    cap = max(cap, 1)
    zeros = ({"in": 0, "out": 0, "close": 0}, {"in": 0, "out": 0, "close": 0})
    base = _table_height(_table([], brought=None, carried=None, grand=None, cell=cell, cell_bold=cell_bold, widths=widths))
    one = _table_height(_table(items[:1], brought=None, carried=None, grand=None, cell=cell, cell_bold=cell_bold, widths=widths))
    brought_h = _table_height(_table([], brought=zeros, carried=None, grand=None, cell=cell, cell_bold=cell_bold, widths=widths)) - base
    carried_h = _table_height(_table([], brought=None, carried=zeros, grand=None, cell=cell, cell_bold=cell_bold, widths=widths)) - base
    grand_h = _table_height(_table([], brought=None, carried=None, grand=totals, cell=cell, cell_bold=cell_bold, widths=widths)) - base
    row_h = max(one - base, 8)
    head = 10 + 14 + 12 + 12 + 4
    cont = 4 + 10
    cont_budget = _FRAME_H - head - cont - 6
    last_budget = _FRAME_H - head - 6

    def height(count, first, kind) -> float:
        total = base + count * row_h
        if not first:
            total += brought_h
        if kind == "carry":
            total += carried_h
        elif kind == "grand":
            total += grand_h
        return total

    pages = []
    index = 0
    total_items = len(items)
    while index < total_items:
        first = not pages
        remaining = total_items - index
        if remaining <= cap and height(remaining, first, "grand") <= last_budget:
            pages.append(items[index:])
            break
        count = min(cap, remaining)
        while count > 1 and height(count, first, "carry") > cont_budget:
            count -= 1
        pages.append(items[index:index + count])
        index += count
    return pages


def _table(items, *, brought, carried, grand, cell, cell_bold, widths) -> Table:
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
        rows.append(_total_row("Brought Forward", brought[0], brought[1], cell_bold, widths[0]))
    for item in items:
        rows.append([
            _one_line(item.get("particular") or "", widths[0], cell),
            _one_line(item.get("vendor_name") or "", widths[1], cell),
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
        rows.append(_total_row("Carried Over", carried[0], carried[1], cell_bold, widths[0]))
    if grand:
        rows.append(_total_row("Grand Total", {
            "in": grand.get("in_qty"),
            "out": grand.get("out_qty"),
            "close": grand.get("close_qty"),
        }, {
            "in": grand.get("in_value"),
            "out": grand.get("out_value"),
            "close": grand.get("close_value"),
        }, cell_bold, widths[0], always=True))

    table = Table(rows, colWidths=widths, repeatRows=2)
    table.splitByRow = 0
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


def _total_row(label, qty, value, cell_bold, width, always: bool = False):
    return [
        _one_line(label, width, cell_bold),
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
