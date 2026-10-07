from __future__ import annotations
"""Split from app/services/customer_bill_pdf.py."""
"""Customer bill PDF in the Tally invoice layout.

One bordered goods table (Sl, Description, Sl, Quantity, Rate, per, Disc. %, Amount).
Transport, packing, and a bill-level cash discount sit inside that table.
Item photos sit under the total, on the last page only. A long list continues
onto the next page with the same header and "continued ...".
"""

import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from math import ceil
from typing import Any, Dict, List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.services.biz_date import to_ist
from app.services.company_info import COMPANY_NAME
from app.services.customer_bill_math import fmt_discount_pct
from app.services.pdf_documents import _safe

PAGE_W, PAGE_H = A4  # 595 x 841

# Column edges measured from the sample invoices.
COLS = [33.0, 47.0, 250.0, 276.0, 333.0, 390.0, 415.0, 453.0, 537.0]
LEFT = COLS[0]
RIGHT = COLS[-1]

# Closing page: table border ends just above "Amount Chargeable".
BOX_BOTTOM = 603.0
# Continued page: border runs down to the "continued" line.
BOX_BOTTOM_CONT = 753.0

HEAD_H = 26.0
ROW_H = 12.0
CHARGE_H = 13.0
TOTAL_H = 16.0

COPY_LABELS = ["ORIGINAL", "DUPLICATE", "TRIPLICATE", "QUADRUPLICATE"]

DECLARATION = (
    "We declare that this invoice shows the actual price of the goods "
    "described and that all particulars are true and correct. "
    "300 PCS QUANTITY TAK PACKING CHARGE NHI LAGEGA USKE UPAR CHARGES APPLICABLE HAI."
)

_BELOW_20 = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
    "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
    "Eighteen", "Nineteen",
]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

from app.services.bill_pdf_parts.common import _draw_charge, _draw_footer, _draw_item, _draw_photos, _draw_total, _draw_verticals, _photo_height, _printed_token, _txt, _y

def _draw_header(
    c: canvas.Canvas,
    *,
    page_no: int,
    show_printed: bool,
    copy_label: str | None,
    invoice_no: str,
    created: datetime | None,
    printed: datetime | None,
    invoice_day: date | None,
    customer_name: str,
    customer_company: str | None,
    customer_phone: str | None,
    customer_address: str | None,
    customer_city: str | None,
    customer_party_number: object,
    order_at: datetime | None = None,
    order_by: str | None = None,
) -> float:
    """Draw the Tally header. Returns the table-top y measured from the top of the page."""
    if show_printed and printed is not None:
        c.setFont("Helvetica-Oblique", 8)
        c.drawRightString(RIGHT, _y(22), f"Printed on {_printed_token(printed)}")
    c.setFont("Helvetica-BoldOblique", 7.5)
    c.drawString(LEFT, _y(32), f"Creation Dt & Time : {_creation_token(created)}")

    c.setFont("Helvetica", 9)
    c.drawString(LEFT, _y(52), "Invoice No.")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(LEFT + 54, _y(52), invoice_no or "")
    if invoice_day is not None:
        dated = _day_token(invoice_day)
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(RIGHT, _y(52), dated)
        c.setFont("Helvetica", 9)
        c.drawRightString(RIGHT - c.stringWidth(dated, "Helvetica-Bold", 9) - 8, _y(52), "Dated")
    c.setFont("Helvetica", 9)
    if order_at is not None:
        c.drawString(LEFT, _y(66), f"Order : {_creation_token(order_at)}")
    else:
        c.drawString(LEFT, _y(66), "Ref. No.")
    who = _txt(order_by, 28)
    if who:
        by = f"By : {who}"
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(RIGHT, _y(66), by)

    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(PAGE_W / 2, _y(82), COMPANY_NAME)
    title = "INVOICE" if page_no <= 1 else f"INVOICE(Page  {page_no})"
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(PAGE_W / 2, _y(98), title)

    party_lines: list[tuple[str, str, bool]] = []
    name = _txt(customer_name, 90) or "Customer"
    party_lines.append(("Party : ", name, True))
    phone = _txt(customer_phone, 40)
    if phone:
        party_lines.append(("", phone, False))
    person = _txt(customer_company, 60)
    if person and person != name:
        party_lines.append(("", person, False))
    addr_bits = [b for b in (_txt(customer_address, 80), _txt(customer_city, 40)) if b]
    if addr_bits:
        party_lines.append(("", ", ".join(addr_bits), False))
    if customer_party_number not in (None, ""):
        party_lines.append(("", f"No. ({customer_party_number})", False))

    top = 116.0
    for prefix, text, bold in party_lines:
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont("Helvetica", 9)
        pw = c.stringWidth(prefix, "Helvetica", 9) if prefix else 0
        c.setFont(font, 9)
        tw = c.stringWidth(text, font, 9)
        x = (PAGE_W - (pw + tw)) / 2
        if prefix:
            c.setFont("Helvetica", 9)
            c.drawString(x, _y(top), prefix)
        c.setFont(font, 9)
        c.drawString(x + pw, _y(top), text)
        top += 13

    top += 6
    if phone:
        c.setFont("Helvetica", 9)
        label = "Contact : "
        c.setFont("Helvetica", 8)
        value = phone
        block = c.stringWidth(label, "Helvetica", 9) + c.stringWidth(value, "Helvetica", 8)
        x = (PAGE_W - block) / 2
        c.setFont("Helvetica", 9)
        c.drawString(x, _y(top), label)
        c.setFont("Helvetica", 8)
        c.drawString(x + c.stringWidth(label, "Helvetica", 9), _y(top), value)
        top += 12
    c.setFont("Helvetica", 9)
    c.drawCentredString(PAGE_W / 2, _y(top), "E-Mail :")
    top += 16

    if copy_label:
        label = str(copy_label)
        size = 13
        c.setFont("Helvetica-Bold", size)
        tw = c.stringWidth(label, "Helvetica-Bold", size)
        cx = PAGE_W / 2
        text_y = _y(20)
        c.setFillColorRGB(1, 0.93, 0.45)
        c.rect(cx - tw / 2 - 10, text_y - 4, tw + 20, 18, fill=1, stroke=0)
        c.setFillColorRGB(0.35, 0.18, 0)
        c.setFont("Helvetica-Bold", size)
        c.drawCentredString(cx, text_y, label)
        c.setFillColorRGB(0, 0, 0)

    return top

def _paginate(
    running: list[dict],
    closing: list[dict],
    photo_n: int,
    table_top: float,
) -> list[dict]:
    """Split running rows across pages. Closing rows, total, and photos stay on the last page."""
    body_top = table_top + HEAD_H
    close_h = sum(_row_height(r) for r in closing)

    def one_page_room(photo_h: float) -> float:
        total_top = BOX_BOTTOM - photo_h - TOTAL_H
        return max(0.0, total_top - body_top)

    def fits_one_page(photo_h: float) -> bool:
        need = sum(_row_height(r) for r in running) + close_h
        return need <= one_page_room(photo_h) + 0.5

    photo_h = _photo_height(photo_n)
    if fits_one_page(photo_h):
        return [{"running": running, "closing": closing, "last": True, "photo_h": photo_h}]

    # Shrink photos until the closing rows themselves fit on the last page.
    while photo_n and close_h > one_page_room(photo_h) + 0.5 and photo_h > 40:
        photo_h *= 0.85
    if close_h > one_page_room(photo_h) + 0.5:
        photo_h = 0.0

    last_room = one_page_room(photo_h) - close_h
    cont_room = BOX_BOTTOM_CONT - body_top

    pages: list[dict] = []
    idx = 0
    n = len(running)
    while idx < n:
        remain_h = sum(_row_height(running[j]) for j in range(idx, n))
        if remain_h <= last_room + 0.5:
            pages.append({
                "running": running[idx:],
                "closing": closing,
                "last": True,
                "photo_h": photo_h,
            })
            return pages
        used = 0.0
        take = 0
        while idx + take < n and used + _row_height(running[idx + take]) <= cont_room + 0.5:
            used += _row_height(running[idx + take])
            take += 1
        take = max(take, 1)
        pages.append({
            "running": running[idx:idx + take],
            "closing": [],
            "last": False,
            "photo_h": 0.0,
        })
        idx += take
    if not pages or not pages[-1]["last"]:
        pages.append({"running": [], "closing": closing, "last": True, "photo_h": photo_h})
    return pages

def _draw_page(
    c: canvas.Canvas,
    page: dict,
    *,
    page_no: int,
    table_top: float,
    show_disc: bool,
    qty_total: Decimal,
    grand: object,
    photos: list[dict],
    remarks: str,
    printed: datetime | None,
    header_kw: dict,
) -> None:
    _draw_header(c, page_no=page_no, show_printed=(page_no == 1), **header_kw)
    _draw_table_head(c, table_top)
    cursor = table_top + HEAD_H
    for row in page["running"] + page["closing"]:
        if row["kind"] in ("item", "addon"):
            _draw_item(c, row, cursor, show_disc=show_disc)
        else:
            _draw_charge(c, row, cursor)
        cursor += _row_height(row)

    if page["last"]:
        photo_h = page["photo_h"]
        total_top = BOX_BOTTOM - photo_h - TOTAL_H
        if cursor > total_top:
            total_top = cursor
        _draw_verticals(c, table_top, total_top + TOTAL_H)
        _draw_total(c, total_top, qty_total, grand)
        photo_top = total_top + TOTAL_H
        _draw_verticals(c, photo_top, BOX_BOTTOM, outer_only=True)
        _draw_photos(c, photos, photo_top + 2, max(0.0, BOX_BOTTOM - photo_top - 4))
        _draw_footer(c, grand=grand, remarks=remarks, printed=printed, continued=False)
    else:
        _draw_verticals(c, table_top, BOX_BOTTOM_CONT)
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(0.6)
        c.line(LEFT, _y(BOX_BOTTOM_CONT), RIGHT, _y(BOX_BOTTOM_CONT))
        _draw_footer(c, grand=grand, remarks=remarks, printed=printed, continued=True)

def _draw_table_head(c: canvas.Canvas, top: float) -> None:
    bottom = top + HEAD_H
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.6)
    c.line(LEFT, _y(top), RIGHT, _y(top))
    c.line(LEFT, _y(bottom), RIGHT, _y(bottom))
    labels = [
        (0, "Sl", "No."),
        (1, "Description of Goods", ""),
        (2, "Sl", "No."),
        (3, "Quantity", ""),
        (4, "Rate", ""),
        (5, "per", ""),
        (6, "Disc. %", ""),
        (7, "Amount", ""),
    ]
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 8)
    for idx, line1, line2 in labels:
        x0, x1 = COLS[idx], COLS[idx + 1]
        mid = (x0 + x1) / 2
        if line2:
            c.drawCentredString(mid, _y(top + 11), line1)
            c.setFont("Helvetica", 7)
            c.drawCentredString(mid, _y(top + 21), line2)
            c.setFont("Helvetica", 8)
        else:
            c.drawCentredString(mid, _y(top + 14), line1)

def _creation_token(dt: datetime | None) -> str:
    ist = to_ist(dt)
    hour = ist.strftime("%I").lstrip("0") or "12"
    return f"{ist.day}-{ist.strftime('%b')}-{ist.strftime('%y')} {hour}:{ist.strftime('%M %p')}"

def _row_height(row: dict) -> float:
    if row["kind"] == "item" or row["kind"] == "addon":
        return ROW_H
    return CHARGE_H

def _day_token(d: date) -> str:
    return f"{d.day}-{d.strftime('%b')}-{d.strftime('%y')}"

