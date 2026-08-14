"""Professional customer tax invoice PDF — matches vendor order style."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.company_info import company_lines
from app.services.customer_bill_math import fmt_discount_pct
from app.services.pdf_documents import _fetch_image, _header, _party_blocks, _safe, _totals_block

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
    """Indian grouping, 2 decimals. Fits rate cells without US-style overflow."""
    try:
        from decimal import Decimal, ROUND_HALF_UP

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


def _cell(text: str, *, right: bool = False, muted: bool = False, size: int = 8) -> Paragraph:
    styles = getSampleStyleSheet()
    key = f"bill_cell_{'r' if right else 'l'}_{'m' if muted else 't'}_{size}"
    return Paragraph(
        escape(text or ""),
        ParagraphStyle(
            key,
            parent=styles["Normal"],
            fontSize=size,
            leading=size + 2,
            alignment=TA_RIGHT if right else TA_LEFT,
            textColor=colors.HexColor("#64748b" if muted else "#0f172a"),
            wordWrap="CJK",
        ),
    )


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
    try:
        per = int(addon.get("per_unit") or addon.get("quantity") or 1)
    except (TypeError, ValueError):
        per = 1
    if per < 1:
        per = 1
    return per * max(line_qty, 1)


def bill_item_headers(gst_on: bool, gst_label: str = "") -> list[str]:
    if gst_on:
        return ["", "Code", "Description", "Qty", "Rate", "Disc.", "Net", "Taxable", f"GST ({gst_label})", "Total"]
    return ["", "Code", "Description", "Qty", "Rate", "Disc.", "Net", "Amount"]


def _bill_items_table(
    lines: List[Dict[str, Any]],
    image_urls: Dict[int, str | None],
    gst_on: bool,
    gst_label: str,
    overall_disc_pct: object = None,
) -> Table:
    prefetched = _prefetch_images_parallel(image_urls or {}, 1.1 * cm, 1.1 * cm)

    if gst_on:
        head = bill_item_headers(True, gst_label)
        col_widths = [0.9 * cm, 1.4 * cm, 2.6 * cm, 1.0 * cm, 1.6 * cm, 1.2 * cm, 1.6 * cm, 1.6 * cm, 1.5 * cm, 1.6 * cm]
    else:
        head = bill_item_headers(False)
        col_widths = [1.1 * cm, 1.6 * cm, 3.4 * cm, 1.2 * cm, 2.0 * cm, 1.5 * cm, 2.0 * cm, 2.2 * cm]

    dash = _cell("—", right=True, muted=True)
    data: list[list[Any]] = [head]
    for ln in lines:
        if not isinstance(ln, dict):
            continue
        cid = int(ln.get("catalog_product_id") or 0)
        img = prefetched.get(cid) or ""
        qty = _line_qty(ln)
        code = _cell(_safe(ln.get("our_product_id"), 24))
        desc = _cell(_safe(ln.get("name") or ln.get("our_product_id"), 60))
        rate = _cell(
            _money(ln.get("rate_inclusive") or ln.get("unit_price") or ln.get("base_unit_price")),
            right=True,
        )
        total = _cell(_money(ln.get("line_total") or ln.get("line_inclusive_after_discount")), right=True)
        disc_pct = fmt_discount_pct(ln.get("item_discount_percent") or overall_disc_pct)
        disc = ln.get("line_discount")
        disc_lbl = "—"
        try:
            if disc and float(disc) > 0 and disc_pct:
                disc_lbl = f"{disc_pct}%"
            elif disc and float(disc) > 0:
                disc_lbl = f"-{_money(disc)}"
        except (TypeError, ValueError):
            disc_lbl = "—"
        net = _cell(
            _money(ln.get("net_rate") or ln.get("effective_price") or ln.get("rate_inclusive") or ln.get("unit_price")),
            right=True,
        )
        disc_cell = _cell(disc_lbl, right=True)

        if gst_on:
            data.append([
                img,
                code,
                desc,
                _cell(str(qty), right=True),
                rate,
                disc_cell,
                net,
                _cell(_money(ln.get("line_taxable_value")), right=True),
                _cell(_money(ln.get("line_gst_amount") or "0.00"), right=True),
                total,
            ])
        else:
            data.append([
                img,
                code,
                desc,
                _cell(str(qty), right=True),
                rate,
                disc_cell,
                net,
                total,
            ])

        for addon in ln.get("addons") or []:
            if not isinstance(addon, dict):
                continue
            aq = _addon_qty(addon, qty)
            label = _addon_label(addon)
            unit = _safe(addon.get("unit") or "pc", 8)
            if not unit or unit == "-":
                unit = "pc"
            row = [""] * len(head)
            row[2] = _cell(f"+ {label}", muted=True)
            row[3] = _cell(f"{aq} {unit}", right=True, muted=True)
            for i in range(4, len(head)):
                row[i] = dash
            data.append(row)

    if len(data) < 2:
        empty = [""] * len(head)
        empty[1] = _cell("-")
        empty[2] = _cell("No line items")
        data.append(empty)

    table = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
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
    invoice_date=None,
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

    from app.services.biz_date import format_ist, format_ist_day

    bill_lbl = _safe(bill_number, 40) if bill_number else f"#{bill_id}"
    _header(story, "TAX INVOICE", "Customer bill — GST inclusive rates", f"Bill {bill_lbl}")
    stamp_style = ParagraphStyle(
        "bill_stamp",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#334155"),
    )
    stamp_lbl = ParagraphStyle(
        "bill_stamp_lbl",
        parent=stamp_style,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#64748b"),
    )
    stamp = Table(
        [
            [
                Paragraph("BILL DATE", stamp_lbl),
                Paragraph("ENTERED", stamp_lbl),
                Paragraph("PRINTED", stamp_lbl),
            ],
            [
                Paragraph(escape(format_ist_day(invoice_date or generated_at)), stamp_style),
                Paragraph(escape(format_ist(generated_at)), stamp_style),
                Paragraph(escape(format_ist(printed_at)), stamp_style),
            ],
        ],
        colWidths=[5.6 * cm, 5.7 * cm, 5.7 * cm],
    )
    stamp.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(stamp)
    story.append(Spacer(1, 0.3 * cm))

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
    story.append(_bill_items_table(
        lines, item_image_urls or {}, gst_on, gst_label,
        overall_disc_pct=totals.get("discount_percent"),
    ))
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
    invoice_date=None,
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
        invoice_date=invoice_date,
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
    invoice_date=None,
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
        invoice_date=invoice_date,
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
