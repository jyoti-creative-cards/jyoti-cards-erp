"""Professional customer tax invoice PDF — matches vendor order style."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.company_info import company_lines
from app.services.pdf_documents import _fetch_image, _header, _ist_fmt, _party_blocks, _safe, _totals_block

COPY_LABELS = ["ORIGINAL", "DUPLICATE", "TRIPLICATE", "QUADRUPLICATE"]


def _prefetch_images_parallel(
    img_map: Dict[int, str | None],
    max_w: float,
    max_h: float,
) -> Dict[int, Optional[Image]]:
    result: Dict[int, Optional[Image]] = {}
    entries = [(k, v) for k, v in img_map.items() if v]
    if not entries:
        return result
    with ThreadPoolExecutor(max_workers=min(len(entries), 8)) as ex:
        futs = {ex.submit(_fetch_image, url, max_w, max_h): k for k, url in entries}
        for fut in as_completed(futs):
            k = futs[fut]
            try:
                result[k] = fut.result()
            except Exception:
                result[k] = None
    return result


def _money(v: object) -> str:
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return _safe(v)


def _bill_items_table(
    lines: List[Dict[str, Any]],
    image_urls: Dict[int, str | None],
    gst_on: bool,
    gst_label: str,
) -> Table:
    prefetched = _prefetch_images_parallel(image_urls or {}, 1.2 * cm, 1.2 * cm)

    if gst_on:
        head = ["", "Code", "Description", "Qty", "Rate", "Taxable", f"GST ({gst_label})", "Total"]
        col_widths = [1.3 * cm, 1.8 * cm, 4.0 * cm, 1.0 * cm, 1.8 * cm, 2.0 * cm, 2.0 * cm, 2.1 * cm]
    else:
        head = ["", "Code", "Description", "Qty", "Rate", "Disc.", "Amount"]
        col_widths = [1.3 * cm, 2.0 * cm, 5.2 * cm, 1.0 * cm, 2.0 * cm, 1.8 * cm, 2.7 * cm]

    data: list[list[Any]] = [head]
    for ln in lines:
        if not isinstance(ln, dict):
            continue
        cid = int(ln.get("catalog_product_id") or 0)
        img = prefetched.get(cid) or ""
        qty = int(ln.get("quantity") or 0)
        code = _safe(ln.get("our_product_id"), 24)
        desc = _safe(ln.get("name") or ln.get("our_product_id"), 48)
        rate = _money(ln.get("rate_inclusive") or ln.get("unit_price") or ln.get("base_unit_price"))
        total = _money(ln.get("line_total") or ln.get("line_inclusive_after_discount"))
        disc = ln.get("line_discount")
        disc_pct = ln.get("item_discount_percent")
        disc_lbl = ""
        try:
            if disc and float(disc) > 0:
                disc_lbl = f"-{_money(disc)}"
                if disc_pct:
                    disc_lbl += f" ({_safe(disc_pct)}%)"
        except (TypeError, ValueError):
            disc_lbl = ""

        if gst_on:
            data.append([
                img,
                code,
                desc,
                str(qty),
                rate,
                _money(ln.get("line_taxable_value")),
                _money(ln.get("line_gst_amount") or "0.00"),
                total,
            ])
        else:
            data.append([img, code, desc, str(qty), rate, disc_lbl or "—", total])

        for addon in ln.get("addons") or []:
            if not isinstance(addon, dict):
                continue
            aq = int(addon.get("quantity") or 1)
            txt = f"+ {_safe(addon.get('name') or addon.get('our_product_id'), 36)} × {aq} {_safe(addon.get('unit') or 'pc', 8)}"
            row = [""] * len(head)
            row[2] = txt
            data.append(row)

    if len(data) < 2:
        empty = [""] * len(head)
        empty[1] = "-"
        empty[2] = "No line items"
        data.append(empty)

    table = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (3, 1), (3, -1), "CENTER"),
        ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, colors.HexColor("#e2e8f0")),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f8fafc")))
    table.setStyle(TableStyle(style_cmds))
    return table


def _build_summary_rows(totals: Dict[str, Any], gst_on: bool, gst_label: str) -> list[list[str]]:
    rows: list[list[str]] = []
    sub = totals.get("subtotal_inclusive")
    if sub is not None:
        rows.append(["Subtotal", f"Rs. {_money(sub)}"])

    disc_amt = totals.get("discount_amount")
    dp = totals.get("discount_percent")
    try:
        disc_n = float(disc_amt or 0)
    except (TypeError, ValueError):
        disc_n = 0.0
    if disc_n > 0:
        label = f"Discount ({_safe(dp)}%)" if dp else "Discount"
        rows.append([label, f"- Rs. {_money(disc_amt)}"])

    after = totals.get("after_discount_inclusive")
    if after is not None and disc_n > 0:
        rows.append(["After discount", f"Rs. {_money(after)}"])

    if gst_on:
        rows.append(["Taxable value", f"Rs. {_money(totals.get('taxable_value'))}"])
        rows.append([f"GST ({gst_label})", f"Rs. {_money(totals.get('gst_amount'))}"])

    freight = totals.get("freight_charges")
    if freight:
        try:
            if float(freight) > 0:
                rows.append(["Freight charges", f"Rs. {_money(freight)}"])
        except (TypeError, ValueError):
            pass

    packaging = totals.get("packaging_charges")
    if packaging:
        try:
            if float(packaging) > 0:
                rows.append(["Packaging charges", f"Rs. {_money(packaging)}"])
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


def _build_bill_story(
    *,
    bill_id: int,
    order_id: int,
    bill_number: str | None = None,
    customer_name: str,
    customer_company: str | None,
    customer_phone: str | None = None,
    customer_address: str | None = None,
    customer_city: str | None = None,
    totals: Dict[str, Any],
    generated_at: datetime | None = None,
    printed_at: datetime | None = None,
    customer_notes: str | None = None,
    narration: str | None = None,
    item_image_urls: Dict[int, str | None] | None = None,
    order_created_at: datetime | None = None,
    copy_label: str | None = None,
    credit_limit: float | None = None,
    outstanding: float | None = None,
) -> list:
    styles = getSampleStyleSheet()
    story: list = []

    if copy_label:
        label_style = ParagraphStyle(
            "copy_label",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            alignment=TA_RIGHT,
            textColor=colors.white,
        )
        label_table = Table([[Paragraph(f"  {copy_label} COPY  ", label_style)]], colWidths=["100%"])
        label_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1d4ed8")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ]))
        story.append(label_table)
        story.append(Spacer(1, 0.25 * cm))

    bill_lbl = _safe(bill_number, 40) if bill_number else f"#{bill_id}"
    meta = (
        f"Bill {bill_lbl} · Order #{order_id} · "
        f"Order {_ist_fmt(order_created_at or generated_at)} · "
        f"Billed {_ist_fmt(generated_at)} · Printed {_ist_fmt(printed_at)}"
    )
    _header(story, "TAX INVOICE", "Customer bill — GST inclusive rates", meta)

    our = ["From (Seller)"] + company_lines()
    bill_to = ["Bill to", _safe(customer_name, 80)]
    if customer_company:
        bill_to.append(_safe(customer_company, 80))
    if customer_phone:
        bill_to.append(f"Phone: {_safe(customer_phone, 24)}")
    if customer_address:
        bill_to.append(_safe(customer_address, 120))
    if customer_city:
        bill_to.append(_safe(customer_city, 60))
    story.append(_party_blocks(our, bill_to))
    story.append(Spacer(1, 0.35 * cm))

    lines = totals.get("lines") if isinstance(totals.get("lines"), list) else []
    gst_on = bool(totals.get("gst_enabled"))
    gst_label = str(totals.get("gst_rate_label") or totals.get("gst_rate_percent") or "")
    story.append(_bill_items_table(lines, item_image_urls or {}, gst_on, gst_label))
    story.append(Spacer(1, 0.35 * cm))
    story.append(_totals_block(_build_summary_rows(totals, gst_on, gst_label)))
    story.append(Spacer(1, 0.4 * cm))

    notes_style = ParagraphStyle(
        "cnotes", parent=styles["Normal"], fontSize=9,
        textColor=colors.HexColor("#0f172a"), spaceAfter=6, leading=12,
    )
    if narration:
        story.append(Paragraph(f"<b>Narration:</b> {escape(_safe(narration, 1000))}", notes_style))
    if customer_notes:
        story.append(Paragraph(f"<b>Customer notes:</b> {escape(_safe(customer_notes, 500))}", notes_style))

    if credit_limit is not None and outstanding is not None:
        try:
            bill_total = float(totals.get("rounded_grand_total") or totals.get("grand_total") or 0)
        except (TypeError, ValueError):
            bill_total = 0.0
        pending_after = outstanding + bill_total
        remaining = credit_limit - pending_after
        cl_color = "#dc2626" if remaining < 0 else "#1d4ed8"
        cl_text = (
            f"Credit Limit: Rs.{credit_limit:,.2f}  |  "
            f"Pending (incl. this bill): Rs.{pending_after:,.2f}  |  "
            f"Available: Rs.{remaining:,.2f}"
        )
        story.append(Paragraph(escape(cl_text), ParagraphStyle(
            "credit_line", parent=styles["Normal"], fontSize=8,
            textColor=colors.HexColor(cl_color), spaceBefore=6, spaceAfter=4,
        )))

    foot = (
        "Amounts in Indian Rupees (Rs.). Rates are GST-inclusive; taxable value and GST are derived per line."
        if gst_on
        else "Amounts in Indian Rupees (Rs.). Thank you for your business!"
    )
    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph(escape(foot), ParagraphStyle(
        "foot", parent=styles["Normal"], fontSize=8, alignment=TA_CENTER, textColor=colors.HexColor("#64748b"),
    )))
    return story


def render_customer_bill_pdf(
    *,
    bill_id: int,
    order_id: int,
    customer_name: str,
    customer_company: str | None,
    customer_phone: str | None = None,
    customer_address: str | None = None,
    customer_city: str | None = None,
    totals: Dict[str, Any],
    generated_at: datetime | None = None,
    printed_at: datetime | None = None,
    customer_notes: str | None = None,
    narration: str | None = None,
    item_image_urls: Dict[int, str | None] | None = None,
    order_created_at: datetime | None = None,
    credit_limit: float | None = None,
    outstanding: float | None = None,
    bill_number: str | None = None,
) -> bytes:
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
        totals=totals,
        generated_at=generated_at,
        printed_at=printed_at,
        customer_notes=customer_notes,
        narration=narration,
        item_image_urls=item_image_urls,
        order_created_at=order_created_at,
        with_labels=False,
        credit_limit=credit_limit,
        outstanding=outstanding,
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
    totals: Dict[str, Any],
    generated_at: datetime | None = None,
    printed_at: datetime | None = None,
    customer_notes: str | None = None,
    narration: str | None = None,
    item_image_urls: Dict[int, str | None] | None = None,
    order_created_at: datetime | None = None,
    credit_limit: float | None = None,
    outstanding: float | None = None,
) -> bytes:
    copies = max(1, min(copies, 4))
    now = datetime.now(timezone.utc)
    kwargs = dict(
        bill_id=bill_id,
        order_id=order_id,
        bill_number=bill_number,
        customer_name=customer_name,
        customer_company=customer_company,
        customer_phone=customer_phone,
        customer_address=customer_address,
        customer_city=customer_city,
        totals=totals,
        generated_at=generated_at,
        printed_at=printed_at or now,
        customer_notes=customer_notes,
        narration=narration,
        item_image_urls=item_image_urls,
        order_created_at=order_created_at,
        credit_limit=credit_limit,
        outstanding=outstanding,
    )
    combined: list = []
    for i in range(copies):
        label = COPY_LABELS[i] if with_labels else None
        story = _build_bill_story(copy_label=label, **kwargs)
        combined.extend(story)
        if i < copies - 1:
            combined.append(PageBreak())

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
    )
    doc.build(combined)
    return buf.getvalue()
