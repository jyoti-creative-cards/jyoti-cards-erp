"""Customer bill PDF in the Tally invoice layout.

One bordered goods table (Sl, Description, Sl, Quantity, Rate, per, Disc. %, Amount).
Transport, packing, and a bill-level cash discount sit inside that table.
Item photos sit under the total, on the last page only. A long list continues
onto the next page with the same header and "continued ...".
"""
from __future__ import annotations

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


def _dec(v: object) -> Decimal:
    try:
        return Decimal(str(v if v not in (None, "") else "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def _txt(v: object, n: int = 80) -> str:
    t = _safe(v, n)
    return "" if t == "-" else t


def _line_qty(ln: Dict[str, Any]) -> int:
    for key in ("quantity", "quantity_shipped", "qty"):
        raw = ln.get(key)
        if raw is None or raw == "":
            continue
        try:
            n = int(raw)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    return 0


def _addon_label(addon: Dict[str, Any]) -> str:
    name = _safe(addon.get("name"), 40)
    sku = _safe(addon.get("our_product_id"), 24)
    if name and name != "-":
        return name
    if sku and sku != "-":
        return sku
    return "Addon"


def _addon_qty(addon: Dict[str, Any], line_qty: int) -> int:
    # Addon snapshots only set "quantity" (per parent unit). There is no "per_unit" key.
    try:
        per = int(addon.get("quantity") or 1)
    except (TypeError, ValueError):
        per = 1
    if per < 1:
        per = 1
    return per * max(line_qty, 1)


def bill_item_headers(gst_on: bool, gst_label: str = "") -> list[str]:
    # Same columns on a GST bill and a non-GST bill. Tax stays inside the line amount.
    del gst_on, gst_label
    return ["Sl No.", "Description of Goods", "Sl No.", "Quantity", "Rate", "per", "Disc. %", "Amount"]


def _two_digits(n: int) -> str:
    if n < 20:
        return _BELOW_20[n]
    ten, one = divmod(n, 10)
    return _TENS[ten] + (f" {_BELOW_20[one]}" if one else "")


def _under_1000(n: int) -> str:
    hundred, rest = divmod(n, 100)
    bits: list[str] = []
    if hundred:
        bits.append(f"{_BELOW_20[hundred]} Hundred")
    if rest:
        bits.append(_two_digits(rest))
    return " ".join(bits)


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


def _day_token(d: date) -> str:
    return f"{d.day}-{d.strftime('%b')}-{d.strftime('%y')}"


def _creation_token(dt: datetime | None) -> str:
    ist = to_ist(dt)
    hour = ist.strftime("%I").lstrip("0") or "12"
    return f"{ist.day}-{ist.strftime('%b')}-{ist.strftime('%y')} {hour}:{ist.strftime('%M %p')}"


def _printed_token(dt: datetime | None) -> str:
    ist = to_ist(dt)
    return f"{ist.day}-{ist.strftime('%b')}-{ist.strftime('%y')} at {ist.strftime('%H:%M')}"


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return to_ist(value).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _qty_text(qty: int) -> str:
    return f"{qty:.2f} pcs"


def _disc_text(pct: object) -> str:
    label = fmt_discount_pct(pct)
    if not label or label in ("0", "0.00"):
        return ""
    try:
        if Decimal(str(label)) <= 0:
            return ""
    except Exception:
        return ""
    if "." in label:
        label = label.rstrip("0").rstrip(".")
    return f"{label} %"


def _description(ln: Dict[str, Any]) -> str:
    code = _txt(ln.get("our_product_id"), 40)
    name = _txt(ln.get("name"), 80)
    if name and name != code:
        if code and code not in name:
            return f"{code} {name}"
        return name
    return code or name or "Item"


def _line_gross(ln: Dict[str, Any]) -> Decimal | None:
    before = ln.get("line_inclusive_before_discount")
    if before not in (None, ""):
        return _dec(before)
    disc = ln.get("line_discount")
    total = ln.get("line_total")
    if disc not in (None, "", "0", "0.00", "0.0") and total not in (None, ""):
        return (_dec(total) + _dec(disc)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return None


def _fetch_reader(url: str) -> Optional[ImageReader]:
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = resp.read()
        return ImageReader(BytesIO(data))
    except Exception:
        return None


def _load_images(urls: Dict[int, str | None]) -> Dict[int, ImageReader]:
    entries = [(k, v) for k, v in (urls or {}).items() if v]
    if not entries:
        return {}
    out: Dict[int, ImageReader] = {}
    with ThreadPoolExecutor(max_workers=min(len(entries), 8)) as pool:
        futs = {pool.submit(_fetch_reader, url): key for key, url in entries}
        for fut in as_completed(futs):
            img = fut.result()
            if img is not None:
                out[futs[fut]] = img
    return out


def _build_rows(lines: List[Dict[str, Any]]) -> tuple[list[dict], Decimal]:
    """Numbered item and addon rows. Returns rows and the total quantity."""
    rows: list[dict] = []
    total_qty = 0
    sl = 0
    for ln in lines:
        if not isinstance(ln, dict):
            continue
        sl += 1
        qty = _line_qty(ln)
        total_qty += qty
        cid = ln.get("catalog_product_id")
        try:
            cid_i = int(cid) if cid is not None else None
        except (TypeError, ValueError):
            cid_i = None
        rows.append({
            "kind": "item",
            "sl": sl,
            "desc": _description(ln),
            "qty": qty,
            "rate": _money(ln.get("rate_inclusive") or ln.get("unit_price") or ln.get("base_unit_price")),
            "disc": _disc_text(ln.get("item_discount_percent")),
            "amount": _dec(ln.get("line_total") or ln.get("line_inclusive_after_discount")),
            "gross": _line_gross(ln),
            "image_id": cid_i,
            "source": ln,
        })
        for addon in ln.get("addons") or []:
            if not isinstance(addon, dict):
                continue
            sl += 1
            aq = _addon_qty(addon, qty)
            total_qty += aq
            rows.append({
                "kind": "addon",
                "sl": sl,
                "desc": _addon_label(addon),
                "qty": aq,
                "rate": "",
                "disc": "",
                "amount": None,
                "gross": None,
                "image_id": None,
                "source": addon,
            })
    return rows, Decimal(total_qty)


def _cash_discount_mode(item_rows: list[dict], totals: Dict[str, Any]) -> bool:
    """Bill-level cash discount (gross lines + a Less row) when every priced line shares it.

    A single discounted line keeps the percent in the Disc. % column, matching the
    one-line sample. Several lines at the same percent use the Less row, matching
    the long sample.
    """
    priced = [r for r in item_rows if r["kind"] == "item"]
    if len(priced) < 2:
        return False
    if _dec(totals.get("discount_amount")) <= 0:
        return False
    if any(r["gross"] is None for r in priced):
        return False
    pcts = []
    for r in priced:
        label = (r["disc"] or "").replace("%", "").strip()
        pcts.append(_dec(label) if label else Decimal("0"))
    if not pcts or any(p != pcts[0] for p in pcts) or pcts[0] <= 0:
        return False
    return True


def _running_and_closing(
    item_rows: list[dict],
    totals: Dict[str, Any],
    cash: bool,
) -> tuple[list[dict], list[dict], Decimal]:
    if cash:
        goods = sum((r["gross"] or Decimal("0") for r in item_rows if r["kind"] == "item"), Decimal("0"))
    else:
        goods = sum((r["amount"] or Decimal("0") for r in item_rows if r["kind"] == "item"), Decimal("0"))
    goods = goods.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    running: list[dict] = list(item_rows)
    charges: list[dict] = []

    freight = _dec(totals.get("freight_charges"))
    if freight > 0:
        receipt = _txt(totals.get("transport_receipt_number"), 24)
        label = "Transport Charges" + (f" ({receipt})" if receipt else "")
        charges.append({"kind": "charge", "label": label, "amount": freight})

    packaging = _dec(totals.get("packaging_charges"))
    if packaging > 0:
        charges.append({"kind": "charge", "label": "PACKING MATERIAL CHARGES", "amount": packaging})

    additional = totals.get("additional_charges")
    if isinstance(additional, list):
        for ac in additional:
            if isinstance(ac, dict) and ac.get("name") and _dec(ac.get("amount")) > 0:
                charges.append({
                    "kind": "charge",
                    "label": _txt(ac["name"], 40) or "Charge",
                    "amount": _dec(ac["amount"]),
                })

    closing: list[dict] = []
    if cash:
        pct = fmt_discount_pct(totals.get("discount_percent"))
        if pct and "." in pct:
            pct = pct.rstrip("0").rstrip(".")
        closing.append({
            "kind": "less",
            "label": "CASH DISCOUNT",
            "pct": pct or "",
            "amount": _dec(totals.get("discount_amount")),
        })

    round_off = totals.get("round_off")
    if round_off and str(round_off) not in ("0", "0.0", "0.00"):
        ro = _dec(round_off)
        if ro != 0:
            closing.append({"kind": "round", "amount": ro})
    if charges or closing:
        running.append({"kind": "subtotal", "amount": goods})
        running.extend(charges)
    return running, closing, goods


def _row_height(row: dict) -> float:
    if row["kind"] == "item" or row["kind"] == "addon":
        return ROW_H
    return CHARGE_H


def _photo_layout(n: int) -> tuple[int, float, float, float]:
    """Columns, image width, image height, row pitch (image + caption)."""
    if n <= 0:
        return 1, 0.0, 0.0, 0.0
    if n <= 2:
        return n, 71.0, 58.0, 74.0
    if n <= 8:
        return n, 56.0, 56.0, 72.0
    return 8, 52.0, 52.0, 78.0


def _photo_height(n: int) -> float:
    if n <= 0:
        return 0.0
    cols, _w, _h, pitch = _photo_layout(n)
    return ceil(n / cols) * pitch + 6.0


def _photos_for(rows: list[dict], images: Dict[int, ImageReader]) -> list[dict]:
    photos = []
    for row in rows:
        if row["kind"] != "item":
            continue
        img = images.get(row["image_id"]) if row["image_id"] is not None else None
        if img is None:
            continue
        photos.append({"image": img, "caption": row["desc"]})
    return photos


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


def _y(top: float) -> float:
    return PAGE_H - top


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


def _fit(c: canvas.Canvas, text: str, font: str, size: float, width: float, minimum: float = 6.0) -> float:
    s = size
    while s > minimum and c.stringWidth(text, font, s) > width:
        s -= 0.4
    return s


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
    c.drawString(LEFT, _y(66), "Ref. No.")

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
        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(RIGHT, _y(32), copy_label)

    return top


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


def _draw_verticals(c: canvas.Canvas, y0: float, y1: float, *, outer_only: bool = False) -> None:
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.6)
    xs = (LEFT, RIGHT) if outer_only else COLS
    for x in xs:
        c.line(x, _y(y0), x, _y(y1))


def _draw_amount(c: canvas.Canvas, top: float, text: str, *, bold: bool = True) -> None:
    font = "Helvetica-Bold" if bold else "Helvetica"
    c.setFont(font, 9)
    c.drawRightString(RIGHT - 6, _y(top + 10), text)


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
    c.drawString(COLS[3] + 8, _y(top + 11), f"{qty:.2f} pcs")
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(RIGHT - 6, _y(top + 11), f"Rs. {_money(grand)}")


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


def _build_summary_rows(totals: Dict[str, Any], gst_on: bool, gst_label: str) -> list[list[str]]:
    rows: list[list[str]] = []
    sub = totals.get("subtotal_inclusive")
    if sub is not None:
        rows.append(["Subtotal", f"Rs. {_money(sub)}"])

    disc_amt = totals.get("discount_amount")
    dp = fmt_discount_pct(totals.get("discount_percent"))
    try:
        disc_n = float(disc_amt or 0)
    except (TypeError, ValueError):
        disc_n = 0.0
    if disc_n > 0:
        label = f"Discount ({dp}%)" if dp else "Discount"
        rows.append([label, f"- Rs. {_money(disc_amt)}"])

    after = totals.get("after_discount_inclusive")
    if after is not None and disc_n > 0:
        rows.append(["After discount", f"Rs. {_money(after)}"])

    if gst_on:
        rows.append(["Taxable value", f"Rs. {_money(totals.get('taxable_value'))}"])
        rows.append([f"GST ({gst_label})", f"Rs. {_money(totals.get('gst_amount'))}"])

    packaging = totals.get("packaging_charges")
    if packaging:
        try:
            if float(packaging) > 0:
                rows.append(["Packaging charges", f"Rs. {_money(packaging)}"])
        except (TypeError, ValueError):
            pass

    freight = totals.get("freight_charges")
    mode = (totals.get("transport_mode") or "").strip().lower()
    if not mode:
        mode = "bus" if freight else "self_pickup"
    if freight:
        try:
            if float(freight) > 0:
                if mode == "transport":
                    rows.append(["Transport charges", f"Rs. {_money(freight)}"])
                    receipt = (totals.get("transport_receipt_number") or "").strip()
                    if receipt:
                        rows.append(["Transport receipt", _safe(receipt, 40)])
                else:
                    rows.append(["Freight charges", f"Rs. {_money(freight)}"])
                    agent = (totals.get("freight_agent_name") or "").strip()
                    if agent:
                        rows.append(["Freight agent", _safe(agent, 40)])
        except (TypeError, ValueError):
            pass

    additional = totals.get("additional_charges")
    if isinstance(additional, list):
        for ac in additional:
            if isinstance(ac, dict) and ac.get("name") and ac.get("amount"):
                rows.append([_safe(ac["name"], 40), f"Rs. {_money(ac['amount'])}"])

    round_off = totals.get("round_off")
    if round_off and str(round_off) not in ("0.00", "0", "0.0"):
        try:
            ro = float(round_off)
            if ro != 0:
                sign = "+" if ro > 0 else ""
                rows.append(["Round off", f"{sign}Rs. {_money(round_off)}"])
        except (TypeError, ValueError):
            pass

    grand = totals.get("rounded_grand_total") or totals.get("grand_total")
    rows.append(["Grand Total", f"Rs. {_money(grand)}"])
    return rows


def render_customer_bill_pdf(
    *,
    bill_id: int,
    order_id: int,
    customer_name: str,
    customer_company: str | None,
    customer_phone: str | None = None,
    customer_address: str | None = None,
    customer_city: str | None = None,
    customer_party_number: int | str | None = None,
    totals: Dict[str, Any],
    generated_at: datetime | None = None,
    printed_at: datetime | None = None,
    customer_notes: str | None = None,
    narration: str | None = None,
    item_image_urls: Dict[int, str | None] | None = None,
    order_created_at: datetime | None = None,
    invoice_date=None,
    credit_limit: float | None = None,
    outstanding: float | None = None,
    bill_number: str | None = None,
) -> bytes:
    del credit_limit, outstanding
    return render_copies_pdf(
        copies=1,
        bill_id=bill_id,
        order_id=order_id,
        bill_number=bill_number,
        customer_name=customer_name,
        customer_company=customer_company,
        customer_phone=customer_phone,
        customer_address=customer_address,
        customer_city=customer_city,
        customer_party_number=customer_party_number,
        totals=totals,
        generated_at=generated_at,
        printed_at=printed_at,
        customer_notes=customer_notes,
        narration=narration,
        item_image_urls=item_image_urls,
        order_created_at=order_created_at,
        invoice_date=invoice_date,
        with_labels=False,
    )


def render_copies_pdf(
    *,
    copies: int = 1,
    with_labels: bool = True,
    bill_id: int,
    order_id: int,
    bill_number: str | None = None,
    customer_name: str,
    customer_company: str | None,
    customer_phone: str | None = None,
    customer_address: str | None = None,
    customer_city: str | None = None,
    customer_party_number: int | str | None = None,
    totals: Dict[str, Any],
    generated_at: datetime | None = None,
    printed_at: datetime | None = None,
    customer_notes: str | None = None,
    narration: str | None = None,
    item_image_urls: Dict[int, str | None] | None = None,
    order_created_at: datetime | None = None,
    invoice_date=None,
    credit_limit: float | None = None,
    outstanding: float | None = None,
) -> bytes:
    del credit_limit, outstanding, order_id
    copies = max(1, min(int(copies or 1), 4))
    now = datetime.now(timezone.utc)
    created = generated_at or order_created_at or now
    printed = printed_at or now
    invoice_day = _as_date(invoice_date) or to_ist(created).date()
    lines = [ln for ln in (totals.get("lines") or []) if isinstance(ln, dict)]
    item_rows, qty_total = _build_rows(lines)
    cash = _cash_discount_mode(item_rows, totals)
    running, closing, _goods = _running_and_closing(item_rows, totals, cash)
    images = _load_images(item_image_urls or {})
    photos = _photos_for(item_rows, images)
    grand = totals.get("rounded_grand_total") or totals.get("grand_total") or "0.00"
    remarks = _txt(narration, 90) or _txt(customer_notes, 90)
    invoice_no = _txt(bill_number, 20) or str(bill_id)

    # Header height depends on which party lines we have. Measure it once.
    measure = canvas.Canvas(BytesIO(), pagesize=A4)
    table_top = _draw_header(
        measure,
        page_no=1,
        show_printed=True,
        copy_label=None,
        invoice_no=invoice_no,
        created=created,
        printed=printed,
        invoice_day=invoice_day,
        customer_name=customer_name,
        customer_company=customer_company,
        customer_phone=customer_phone,
        customer_address=customer_address,
        customer_city=customer_city,
        customer_party_number=customer_party_number,
    )
    pages = _paginate(running, closing, len(photos), table_top)

    header_kw = dict(
        copy_label=None,
        invoice_no=invoice_no,
        created=created,
        printed=printed,
        invoice_day=invoice_day,
        customer_name=customer_name,
        customer_company=customer_company,
        customer_phone=customer_phone,
        customer_address=customer_address,
        customer_city=customer_city,
        customer_party_number=customer_party_number,
    )
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Invoice {invoice_no}")
    for copy_i in range(copies):
        label = COPY_LABELS[copy_i] if with_labels else None
        kw = dict(header_kw)
        kw["copy_label"] = label
        for i, page in enumerate(pages, start=1):
            _draw_page(
                c,
                page,
                page_no=i,
                table_top=table_top,
                show_disc=not cash,
                qty_total=qty_total,
                grand=grand,
                photos=photos if page["last"] else [],
                remarks=remarks,
                printed=printed,
                header_kw=kw,
            )
            c.showPage()
    c.save()
    return buf.getvalue()
