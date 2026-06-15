"""Professional invoice PDF with product images, freight/packaging charges."""
from __future__ import annotations

import urllib.request
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, Optional
from xml.sax.saxutils import escape

from concurrent.futures import ThreadPoolExecutor, as_completed

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

COPY_LABELS = ["ORIGINAL", "DUPLICATE", "TRIPLICATE", "QUADRUPLICATE"]


def _safe(s: object, max_len: int = 80) -> str:
    t = str(s or "")
    out = []
    for c in t[:max_len]:
        if ord(c) < 128 and (c.isprintable() or c == " "):
            out.append(c)
        elif c in "\r\n\t":
            out.append(" ")
        else:
            out.append(" ")
    return "".join(out).strip() or "-"


def _fetch_image(url: str, max_w: float, max_h: float) -> Optional[Image]:
    """Download image from URL and return a reportlab Image scaled to fit."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as r:  # reduced timeout: 3s
            data = r.read()
        buf = BytesIO(data)
        img = Image(buf)
        iw, ih = img.drawWidth, img.drawHeight
        scale = min(max_w / iw, max_h / ih, 1.0)
        img.drawWidth = iw * scale
        img.drawHeight = ih * scale
        return img
    except Exception:
        return None


def _prefetch_images_parallel(
    img_map: Dict[int, str | None],
    max_w: float,
    max_h: float,
) -> Dict[int, Optional[Image]]:
    """Fetch all item images in parallel, returning {product_id: Image|None}."""
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


def _build_bill_story(
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
    copy_label: str | None = None,
    credit_limit: float | None = None,
    outstanding: float | None = None,
) -> list:
    """Build the reportlab story (list of Flowables) for one bill copy."""
    from datetime import timedelta
    ts = generated_at or datetime.now(timezone.utc)
    printed_ts = printed_at or datetime.now(timezone.utc)
    order_ts = order_created_at or ts
    ist_offset = timedelta(hours=5, minutes=30)
    order_ts_ist = order_ts.astimezone(timezone.utc).replace(tzinfo=timezone.utc) + ist_offset
    bill_ts_ist = ts.astimezone(timezone.utc).replace(tzinfo=timezone.utc) + ist_offset
    printed_ts_ist = printed_ts.astimezone(timezone.utc).replace(tzinfo=timezone.utc) + ist_offset

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "inv_title",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        alignment=TA_CENTER,
        spaceAfter=6,
        textColor=colors.HexColor("#1a1a1a"),
    )
    subtitle_style = ParagraphStyle(
        "inv_subtitle",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#555555"),
        alignment=TA_CENTER,
        spaceAfter=14,
    )
    story: list = []

    # Copy label banner (ORIGINAL / DUPLICATE / TRIPLICATE / QUADRUPLICATE)
    if copy_label:
        label_style = ParagraphStyle(
            "copy_label",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            alignment=TA_RIGHT,
            spaceAfter=2,
            textColor=colors.HexColor("#ffffff"),
        )
        label_table = Table(
            [[Paragraph(f"  {copy_label} COPY  ", label_style)]],
            colWidths=["100%"],
        )
        label_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1d4ed8")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ]))
        story.append(label_table)
        story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph("JYOTI CREATIVE CARDS", title_style))
    story.append(Paragraph("TAX INVOICE", ParagraphStyle(
        "inv_sub2", parent=styles["Normal"], fontSize=11,
        alignment=TA_CENTER, spaceAfter=4, textColor=colors.HexColor("#444444"),
        fontName="Helvetica-Bold",
    )))
    story.append(
        Paragraph(
            escape(
                f"Bill #{bill_id}   |   Order #{order_id}   |   "
                f"Order Date: {order_ts_ist.strftime('%d %b %Y %I:%M %p')} IST   |   "
                f"Bill Generated: {bill_ts_ist.strftime('%d %b %Y %I:%M %p')} IST   |   "
                f"Printed: {printed_ts_ist.strftime('%d %b %Y %I:%M %p')} IST"
            ),
            subtitle_style,
        )
    )

    bill_to_lines = ["<b>Bill to</b>", escape(_safe(customer_name, 120))]
    if customer_company:
        bill_to_lines.append(escape(_safe(customer_company, 120)))
    if customer_phone:
        bill_to_lines.append(f"Ph: {escape(_safe(customer_phone, 32))}")
    if customer_address:
        bill_to_lines.append(escape(_safe(customer_address, 200)))
    if customer_city:
        bill_to_lines.append(escape(_safe(customer_city, 100)))
    story.append(
        Paragraph(
            "<br/>".join(bill_to_lines),
            ParagraphStyle("billto", parent=styles["Normal"], fontSize=10, spaceAfter=14, leading=14),
        )
    )

    lines = totals.get("lines") if isinstance(totals.get("lines"), list) else []
    gst_on = bool(totals.get("gst_enabled"))
    gst_label = str(totals.get("gst_rate_label") or totals.get("gst_rate_percent") or "")

    # Pre-fetch all product images in parallel (much faster than sequential)
    img_map: Dict[int, str | None] = item_image_urls or {}
    prefetched: Dict[int, Optional[Image]] = _prefetch_images_parallel(img_map, 1.4 * cm, 1.4 * cm)
    img_keys = list(img_map.keys())

    def _get_img_cell(line_idx: int) -> Any:
        if line_idx < len(img_keys):
            k = img_keys[line_idx]
            img = prefetched.get(k)
            if img:
                return img
        return ""

    def _rate(ln: dict) -> str:
        """Return the rate cell value, falling back across field names for older bills."""
        return _safe(
            ln.get("rate_inclusive") or ln.get("unit_price") or ln.get("effective_price") or ln.get("base_unit_price")
        )

    def _amount(ln: dict) -> str:
        return _safe(
            ln.get("line_total") or ln.get("line_inclusive_after_discount") or ln.get("line_total_inclusive")
        )

    if gst_on:
        head = ["", "Code", "Description", "Qty", "Rate (Rs.)", "Taxable (Rs.)", f"GST ({gst_label})", "Total (Rs.)"]
        col_widths = [1.6 * cm, 2.0 * cm, 4.2 * cm, 1.0 * cm, 1.9 * cm, 2.0 * cm, 2.0 * cm, 2.1 * cm]
        data: list[list[Any]] = [head]
        for i, ln in enumerate(lines):
            if not isinstance(ln, dict):
                continue
            qty = int(ln.get("quantity") or 0)
            data.append([
                _get_img_cell(i),
                _safe(ln.get("our_product_id"), 24),
                _safe(ln.get("name"), 48),
                str(qty) if qty else _safe(ln.get("quantity")),
                _rate(ln),
                _safe(ln.get("line_taxable_value") or ln.get("line_total")),
                _safe(ln.get("line_gst_amount") or "0.00"),
                _amount(ln),
            ])
    else:
        head = ["", "Code", "Description", "Qty", "Rate (Rs.)", "Amount (Rs.)"]
        col_widths = [1.6 * cm, 2.2 * cm, 6.5 * cm, 1.0 * cm, 2.2 * cm, 3.3 * cm]
        data = [head]
        for i, ln in enumerate(lines):
            if not isinstance(ln, dict):
                continue
            qty = int(ln.get("quantity") or 0)
            data.append([
                _get_img_cell(i),
                _safe(ln.get("our_product_id"), 24),
                _safe(ln.get("name"), 56),
                str(qty) if qty else _safe(ln.get("quantity")),
                _rate(ln),
                _amount(ln),
            ])

    if len(data) < 2:
        placeholder = ["", "-", "No line items", "", "", ""] if not gst_on else ["", "-", "No line items", "", "", "", "", ""]
        data.append(placeholder)

    items_table = Table(data, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#222222")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
            ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#333333")),
            ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (3, 1), (3, -1), "CENTER"),
            ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
            ("ALIGN", (4, 0), (-1, 0), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(items_table)
    story.append(Spacer(1, 0.45 * cm))

    # Summary table
    sub = _safe(totals.get("subtotal_inclusive"))
    disc_amt = _safe(totals.get("discount_amount"))
    dp = totals.get("discount_percent")
    taxable = _safe(totals.get("taxable_value"))
    gst_amt = _safe(totals.get("gst_amount"))
    freight = totals.get("freight_charges")
    packaging = totals.get("packaging_charges")
    grand = _safe(totals.get("grand_total"))

    right_style = ParagraphStyle("r", parent=styles["Normal"], fontSize=10, alignment=TA_RIGHT)
    additional_charges = totals.get("additional_charges")
    round_off = totals.get("round_off")
    rounded_grand = totals.get("rounded_grand_total") or grand
    summary_rows: list[list[Any]] = [["Subtotal (incl.)", f"Rs. {sub}"]]
    if dp:
        summary_rows.append([f"Discount ({_safe(dp)}%)", f"- Rs. {disc_amt}"])
    if gst_on:
        summary_rows.append(["Taxable value", f"Rs. {taxable}"])
        summary_rows.append([f"GST ({gst_label})", f"Rs. {gst_amt}"])
    if freight:
        summary_rows.append(["Freight charges", f"Rs. {_safe(freight)}"])
    if packaging:
        summary_rows.append(["Packaging charges", f"Rs. {_safe(packaging)}"])
    if additional_charges and isinstance(additional_charges, list):
        for ac in additional_charges:
            if isinstance(ac, dict) and ac.get("name") and ac.get("amount"):
                summary_rows.append([_safe(ac["name"]), f"Rs. {_safe(ac['amount'])}"])
    if round_off and round_off not in ("0.00", "0"):
        try:
            ro_val = float(round_off)
            if ro_val != 0:
                sign = "+" if ro_val > 0 else ""
                summary_rows.append(["Round Off", f"{sign}Rs. {_safe(round_off)}"])
        except (ValueError, TypeError):
            pass
    summary_rows.append(["Grand Total", f"Rs. {_safe(rounded_grand)}"])

    sum_table = Table(summary_rows, colWidths=[9 * cm, 6 * cm])
    sum_table.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (-1, -2), "Helvetica"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("TEXTCOLOR", (0, -1), (-1, -1), colors.HexColor("#111111")),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f8f8f8")),
            ("LINEABOVE", (0, -1), (-1, -1), 1.2, colors.HexColor("#333333")),
            ("TOPPADDING", (0, -1), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])
    )
    story.append(sum_table)
    story.append(Spacer(1, 0.5 * cm))

    foot = ParagraphStyle(
        "foot", parent=styles["Normal"], fontSize=8,
        textColor=colors.HexColor("#666666"), alignment=TA_CENTER,
    )
    notes_style = ParagraphStyle(
        "cnotes", parent=styles["Normal"], fontSize=9,
        textColor=colors.HexColor("#222222"), spaceAfter=8,
    )
    if narration:
        story.append(Paragraph(f"<b>Narration:</b> {escape(_safe(narration, 1000))}", notes_style))
        story.append(Spacer(1, 0.15 * cm))
    if customer_notes:
        story.append(
            Paragraph(f"<b>Customer notes:</b> {escape(_safe(customer_notes, 500))}", notes_style)
        )
        story.append(Spacer(1, 0.2 * cm))

    # Credit limit footer
    if credit_limit is not None and outstanding is not None:
        bill_total = float(totals.get("grand_total") or totals.get("subtotal") or 0)
        pending_after = outstanding + bill_total
        remaining = credit_limit - pending_after
        cl_color = "#dc2626" if remaining < 0 else "#1d4ed8"
        cl_text = (
            f"Credit Limit: Rs.{credit_limit:,.2f}  |  "
            f"Total Pending (incl. this bill): Rs.{pending_after:,.2f}  |  "
            f"Available Credit: Rs.{remaining:,.2f}"
        )
        cl_style = ParagraphStyle(
            "credit_line", parent=styles["Normal"], fontSize=8,
            textColor=colors.HexColor(cl_color), spaceAfter=4,
        )
        story.append(Paragraph(escape(cl_text), cl_style))
        story.append(Spacer(1, 0.1 * cm))

    note = (
        "Amounts in Indian Rupees (Rs.). Rates are GST-inclusive; taxable value and GST are derived."
        if gst_on
        else "Amounts in Indian Rupees (Rs.). Thank you for your business!"
    )
    story.append(Paragraph(escape(note), foot))
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
) -> bytes:
    """Render a single-copy bill PDF (no copy label)."""
    return render_copies_pdf(
        copies=1,
        bill_id=bill_id,
        order_id=order_id,
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
    """Render N copies of the bill in one PDF.
    Each copy gets a ORIGINAL / DUPLICATE / TRIPLICATE / QUADRUPLICATE banner.
    """
    copies = max(1, min(copies, 4))
    now = datetime.now(timezone.utc)
    kwargs = dict(
        bill_id=bill_id, order_id=order_id,
        customer_name=customer_name, customer_company=customer_company,
        customer_phone=customer_phone, customer_address=customer_address,
        customer_city=customer_city,
        totals=totals, generated_at=generated_at,
        printed_at=printed_at or now,
        customer_notes=customer_notes, narration=narration,
        item_image_urls=item_image_urls, order_created_at=order_created_at,
        credit_limit=credit_limit, outstanding=outstanding,
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
        rightMargin=1.8 * cm,
        leftMargin=1.8 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )
    doc.build(combined)
    return buf.getvalue()
