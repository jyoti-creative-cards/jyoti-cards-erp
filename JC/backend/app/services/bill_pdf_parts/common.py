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

def _dec(v: object) -> Decimal:
    try:
        return Decimal(str(v if v not in (None, "") else "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")

def _draw_amount(c: canvas.Canvas, top: float, text: str, *, bold: bool = True) -> None:
    font = "Helvetica-Bold" if bold else "Helvetica"
    c.setFont(font, 9)
    c.drawRightString(RIGHT - 6, _y(top + 10), text)

def _draw_charge(c: canvas.Canvas, row: dict, top: float) -> None:
    c.setFillColorRGB(0, 0, 0)
    if row["kind"] == "subtotal":
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(0.6)
        c.line(COLS[7] + 2, _y(top), RIGHT - 3, _y(top))
        _draw_amount(c, top, _money(row["amount"]), bold=False)
        return
    if row["kind"] == "less":
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(COLS[1] + 2, _y(top + 10), "Less :")
        c.setFont("Helvetica-BoldOblique", 9)
        c.drawRightString(COLS[2] - 6, _y(top + 10), row["label"])
        if row.get("pct"):
            c.setFont("Helvetica-Oblique", 9)
            c.drawCentredString((COLS[6] + COLS[7]) / 2, _y(top + 10), f"(-){row['pct']} %")
        _draw_amount(c, top, f"(-){_money(row['amount'])}")
        return
    if row["kind"] == "round":
        c.setFont("Helvetica-BoldOblique", 9)
        c.drawRightString(COLS[2] - 6, _y(top + 10), "Round Off")
        _draw_amount(c, top, _money(row["amount"]))
        return
    c.setFont("Helvetica-BoldOblique", 9)
    label = row["label"]
    size = _fit(c, label, "Helvetica-BoldOblique", 9, COLS[2] - COLS[1] - 10)
    c.setFont("Helvetica-BoldOblique", size)
    c.drawRightString(COLS[2] - 6, _y(top + 10), label)
    _draw_amount(c, top, _money(row["amount"]))

def _draw_footer(
    c: canvas.Canvas,
    *,
    grand: object,
    remarks: str,
    printed: datetime | None,
    continued: bool,
) -> None:
    c.setFillColorRGB(0, 0, 0)
    if continued:
        c.setFont("Helvetica", 9)
        c.drawRightString(RIGHT, _y(778), "continued ...")
    else:
        c.setFont("Helvetica", 8)
        c.drawString(LEFT, _y(618), "Amount Chargeable (in words)")
        c.setFont("Helvetica-Oblique", 8)
        c.drawRightString(RIGHT, _y(618), "E. & O.E")
        c.setFont("Helvetica-Bold", 9.5)
        words = _inr_words(grand)
        size = _fit(c, words, "Helvetica-Bold", 9.5, RIGHT - LEFT - 8, minimum=7)
        c.setFont("Helvetica-Bold", size)
        c.drawString(LEFT, _y(632), words)

        c.setFont("Helvetica-Oblique", 8)
        c.drawString(LEFT, _y(652), "Remarks:")
        if remarks:
            c.setFont("Helvetica", 9)
            c.drawString(LEFT, _y(666), remarks[:90])
        c.setFont("Helvetica-Bold", 7)
        c.drawRightString(RIGHT, _y(652), "SCAN TO PAY")

        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(0.4)
        c.line(LEFT, _y(744), LEFT + 48, _y(744))
        c.setFont("Helvetica", 8)
        c.drawString(LEFT, _y(742), "Declaration")
        lines = _wrap(c, DECLARATION, "Helvetica", 8, 300)
        y = 756
        c.setFont("Helvetica", 8)
        for line in lines[:4]:
            c.drawString(LEFT, _y(y), line)
            y += 11

        for_line = f"for {COMPANY_NAME}"
        size = _fit(c, for_line, "Helvetica-Bold", 9, 180)
        c.setFont("Helvetica-Bold", size)
        c.drawRightString(RIGHT, _y(742), for_line)
        c.setFont("Helvetica", 8)
        c.drawString(288, _y(786), "Prepared by")
        c.drawString(372, _y(786), "Verified by")
        c.drawRightString(RIGHT, _y(786), "Authorised Signatory")

    c.setFont("Helvetica", 8)
    c.drawCentredString(PAGE_W / 2, _y(802), "This is a Computer Generated Invoice")
    if printed is not None:
        c.drawCentredString(PAGE_W / 2, _y(818), f"Printed on {_printed_token(printed)}")
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.6)
    c.line(208, _y(808), 357, _y(808))

def _draw_item(c: canvas.Canvas, row: dict, top: float, *, show_disc: bool) -> None:
    c.setFillColorRGB(0, 0, 0)
    mid_sl = (COLS[0] + COLS[1]) / 2
    mid_sl2 = (COLS[2] + COLS[3]) / 2
    c.setFont("Helvetica", 9)
    c.drawCentredString(mid_sl, _y(top + 10), str(row["sl"]))
    c.drawCentredString(mid_sl2, _y(top + 10), str(row["sl"]))
    desc = row["desc"]
    size = _fit(c, desc, "Helvetica-Bold", 9, COLS[2] - COLS[1] - 8)
    c.setFont("Helvetica-Bold", size)
    c.drawString(COLS[1] + 3, _y(top + 10), desc)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(COLS[3] + 8, _y(top + 10), _qty_text(row["qty"]))
    if row["kind"] == "item":
        c.setFont("Helvetica", 8)
        c.drawRightString(COLS[5] - 4, _y(top + 10), row["rate"])
        c.drawString(COLS[5] + 6, _y(top + 10), "pcs")
        if show_disc and row["disc"]:
            c.drawCentredString((COLS[6] + COLS[7]) / 2, _y(top + 10), row["disc"])
        shown = row["gross"] if not show_disc and row["gross"] is not None else row["amount"]
        _draw_amount(c, top, _money(shown))

def _draw_photos(c: canvas.Canvas, photos: list[dict], top: float, height: float) -> None:
    n = len(photos)
    if n <= 0 or height <= 0:
        return
    cols, iw, ih, pitch = _photo_layout(n)
    # Honour a shrunk block by scaling the pitch down.
    rows = ceil(n / cols)
    natural = rows * pitch
    scale = min(1.0, (height - 4) / natural) if natural else 1.0
    iw *= scale
    ih *= scale
    pitch *= scale
    gap = 10.0
    row_w = cols * iw + (cols - 1) * gap
    x_origin = LEFT + 1
    if row_w < (RIGHT - LEFT):
        # Few photos stay left, matching the samples.
        x_origin = LEFT + 1
    for i, photo in enumerate(photos):
        r, col = divmod(i, cols)
        x = x_origin + col * (iw + gap)
        y_top = top + r * pitch
        c.drawImage(
            photo["image"],
            x,
            _y(y_top + ih),
            width=iw,
            height=ih,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )
        cap = photo["caption"]
        size = _fit(c, cap, "Helvetica", 7, iw)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica", size)
        c.drawString(x, _y(y_top + ih + 9 * scale + 2), cap)

def _draw_total(c: canvas.Canvas, top: float, qty: Decimal, grand: object) -> None:
    bottom = top + TOTAL_H
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.8)
    c.line(LEFT, _y(top), RIGHT, _y(top))
    c.line(LEFT, _y(bottom), RIGHT, _y(bottom))
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 8)
    c.drawRightString(COLS[3] - 4, _y(top + 11), "Total")
    c.setFont("Helvetica-Bold", 8)
    c.drawString(COLS[3] + 8, _y(top + 11), _qty_text(qty))
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(RIGHT - 6, _y(top + 11), f"Rs. {_money(grand)}")

def _draw_verticals(c: canvas.Canvas, y0: float, y1: float, *, outer_only: bool = False) -> None:
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.6)
    xs = (LEFT, RIGHT) if outer_only else COLS
    for x in xs:
        c.line(x, _y(y0), x, _y(y1))

def _fit(c: canvas.Canvas, text: str, font: str, size: float, width: float, minimum: float = 6.0) -> float:
    s = size
    while s > minimum and c.stringWidth(text, font, s) > width:
        s -= 0.4
    return s

def _indian_words(n: int) -> str:
    if n == 0:
        return "Zero"
    if n < 0:
        return f"Minus {_indian_words(-n)}"
    parts: list[str] = []
    if n >= 10000000:
        parts.append(f"{_indian_words(n // 10000000)} Crore")
        n %= 10000000
    if n >= 100000:
        parts.append(f"{_two_digits(n // 100000)} Lakh")
        n %= 100000
    if n >= 1000:
        parts.append(f"{_two_digits(n // 1000)} Thousand")
        n %= 1000
    if n:
        parts.append(_under_1000(n))
    return " ".join(p for p in parts if p)

def _inr_words(amount: object) -> str:
    d = _dec(amount)
    rupees = int(d)
    paise = int((d - Decimal(rupees)) * 100)
    words = _indian_words(rupees)
    if paise:
        words += f" and {_two_digits(paise)} paise"
    return f"INR {words} Only"

def _money(v: object) -> str:
    """Indian grouping, 2 decimals. Fits rate cells without US-style overflow."""
    try:
        d = Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return _safe(v)
    neg = d < 0
    d = abs(d)
    rupees, paise = format(d, "f").split(".")
    if len(rupees) <= 3:
        grouped = rupees
    else:
        last3 = rupees[-3:]
        rest = rupees[:-3]
        chunks: list[str] = []
        while rest:
            chunks.append(rest[-2:])
            rest = rest[:-2]
        grouped = ",".join(reversed(chunks)) + "," + last3
    out = f"{grouped}.{paise}"
    return f"-{out}" if neg else out

def _photo_height(n: int) -> float:
    if n <= 0:
        return 0.0
    cols, _w, _h, pitch = _photo_layout(n)
    return ceil(n / cols) * pitch + 6.0

def _photo_layout(n: int) -> tuple[int, float, float, float]:
    """Columns, image width, image height, row pitch (image + caption)."""
    if n <= 0:
        return 1, 0.0, 0.0, 0.0
    if n <= 2:
        return n, 71.0, 58.0, 74.0
    if n <= 8:
        return n, 56.0, 56.0, 72.0
    return 8, 52.0, 52.0, 78.0

def _printed_token(dt: datetime | None) -> str:
    ist = to_ist(dt)
    return f"{ist.day}-{ist.strftime('%b')}-{ist.strftime('%y')} at {ist.strftime('%H:%M')}"

def _qty_text(qty: int) -> str:
    try:
        n = int(qty)
    except (TypeError, ValueError):
        n = 0
    return f"{n} pcs"

def _two_digits(n: int) -> str:
    if n < 20:
        return _BELOW_20[n]
    ten, one = divmod(n, 10)
    return _TENS[ten] + (f" {_BELOW_20[one]}" if one else "")

def _txt(v: object, n: int = 80) -> str:
    t = _safe(v, n)
    return "" if t == "-" else t

def _under_1000(n: int) -> str:
    hundred, rest = divmod(n, 100)
    bits: list[str] = []
    if hundred:
        bits.append(f"{_BELOW_20[hundred]} Hundred")
    if rest:
        bits.append(_two_digits(rest))
    return " ".join(bits)

def _wrap(c: canvas.Canvas, text: str, font: str, size: float, width: float) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if c.stringWidth(trial, font, size) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines

def _y(top: float) -> float:
    return PAGE_H - top

