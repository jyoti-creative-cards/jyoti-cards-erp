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

from app.services.bill_pdf_parts.common import _dec, _money, _txt
from app.services.bill_pdf_parts.draw_header import _draw_header, _draw_page, _paginate

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
    order_by: str | None = None,
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
        order_at=order_created_at,
        order_by=order_by,
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
        order_at=order_created_at,
        order_by=order_by,
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
    order_by: str | None = None,
    invoice_date=None,
    credit_limit: float | None = None,
    outstanding: float | None = None,
    bill_number: str | None = None,
) -> bytes:
    del credit_limit, outstanding
    return render_copies_pdf(
        copies=2,
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
        order_by=order_by,
        invoice_date=invoice_date,
        with_labels=True,
    )

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

def _addon_qty(addon: Dict[str, Any], line_qty: int) -> int:
    # Addon snapshots only set "quantity" (per parent unit). There is no "per_unit" key.
    try:
        per = int(addon.get("quantity") or 1)
    except (TypeError, ValueError):
        per = 1
    if per < 1:
        per = 1
    return per * max(line_qty, 1)

def _line_gross(ln: Dict[str, Any]) -> Decimal | None:
    before = ln.get("line_inclusive_before_discount")
    if before not in (None, ""):
        return _dec(before)
    disc = ln.get("line_discount")
    total = ln.get("line_total")
    if disc not in (None, "", "0", "0.00", "0.0") and total not in (None, ""):
        return (_dec(total) + _dec(disc)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return None

def _addon_label(addon: Dict[str, Any]) -> str:
    name = _safe(addon.get("name"), 40)
    sku = _safe(addon.get("our_product_id"), 24)
    if name and name != "-":
        return name
    if sku and sku != "-":
        return sku
    return "Addon"

def _description(ln: Dict[str, Any]) -> str:
    code = _txt(ln.get("our_product_id"), 40)
    name = _txt(ln.get("name"), 80)
    if name and name != code:
        if code and code not in name:
            return f"{code} {name}"
        return name
    return code or name or "Item"

