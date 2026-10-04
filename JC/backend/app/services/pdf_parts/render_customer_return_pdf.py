from __future__ import annotations
"""Split from app/services/pdf_documents.py."""
"""Order receipts and vendor document PDFs."""

import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.company_info import company_lines

from app.services.pdf_parts.common import _code_pair, _fetch_image, _header, _ist_fmt, _safe, add_page_number

def render_customer_return_pdf(
    *,
    return_id: int,
    return_number: str,
    customer_name: str,
    customer_phone: str | None = None,
    customer_address: str | None = None,
    customer_city: str | None = None,
    lines: List[Dict[str, Any]],
    image_urls: Dict[int, str | None],
    calculated_amount: str,
    credit_amount: str,
    notes: str | None = None,
    bill_numbers: List[str] | None = None,
    created_by: str,
    created_at: datetime | None = None,
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    story: list = []
    bills_lbl = ", ".join(_safe(b, 40) for b in (bill_numbers or [])[:8]) or "—"
    _header(
        story,
        "CREDIT NOTE / RETURN",
        f"Return {_safe(return_number, 40)}",
        f"#{return_id} · {_ist_fmt(created_at)} · By {escape(_safe(created_by, 40))}",
    )
    styles = getSampleStyleSheet()
    info = [f"<b>Customer:</b> {escape(_safe(customer_name, 80))}"]
    if customer_phone:
        info.append(f"<b>Phone:</b> {escape(_safe(customer_phone, 20))}")
    if customer_address:
        info.append(f"<b>Address:</b> {escape(_safe(customer_address, 120))}")
    if customer_city:
        info.append(f"<b>City:</b> {escape(_safe(customer_city, 60))}")
    info.append(f"<b>Against bills:</b> {escape(bills_lbl)}")
    story.append(Paragraph("<br/>".join(info), ParagraphStyle("info", parent=styles["Normal"], fontSize=9, spaceAfter=12, leading=13)))

    # Table with bill column
    head = ["", "Code", "Bill", "Qty", "Sold (Rs.)", "Amount (Rs.)"]
    col_widths = [1.4 * cm, 3.2 * cm, 3.2 * cm, 1.2 * cm, 2.4 * cm, 2.6 * cm]
    data: list[list[Any]] = [head]
    for ln in lines:
        cid = int(ln.get("catalog_product_id") or 0)
        img = _fetch_image(image_urls.get(cid) or "", 1.2 * cm, 1.2 * cm) or ""
        data.append([
            img,
            _safe(ln.get("our_product_id"), 28),
            _safe(ln.get("bill_number"), 28),
            str(int(ln.get("quantity") or 0)),
            _safe(ln.get("unit_price")),
            _safe(ln.get("line_total")),
        ])
    if len(data) < 2:
        data.append(["", "-", "—", "", "", ""])
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("ALIGN", (3, 1), (3, -1), "CENTER"),
        ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f0fdfa")))
    table.setStyle(TableStyle(style_cmds))
    story.append(table)
    story.append(Spacer(1, 0.35 * cm))
    story.append(_totals_block([
        ["Calculated (qty × sold)", f"Rs. {_safe(calculated_amount)}"],
        ["Credit amount (AR)", f"Rs. {_safe(credit_amount)}"],
    ]))
    if notes:
        story.append(Spacer(1, 0.35 * cm))
        story.append(Paragraph(f"<b>Notes:</b> {escape(_safe(notes, 500))}", ParagraphStyle(
            "notes", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#134e4a"),
            backColor=colors.HexColor("#ccfbf1"), borderPadding=8, spaceAfter=8,
        )))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Goods restocked. This credit note reduces customer accounts receivable.", ParagraphStyle(
        "foot", parent=styles["Normal"], fontSize=8, alignment=TA_CENTER, textColor=colors.HexColor("#64748b"),
    )))
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return buf.getvalue()

def _totals_block(
    rows: List[List[str]],
    *,
    highlight_prefixes: tuple[str, ...] = (),
    compact: bool = False,
    content_width: float | None = None,
) -> Table:
    styles = getSampleStyleSheet()
    body = 7 if compact else 9
    last_l = 8 if compact else 10
    last_v = 8.5 if compact else 11
    pad = 1.5 if compact else 7
    side = 5 if compact else 10
    data = []
    for i, (label, value) in enumerate(rows):
        is_last = i == len(rows) - 1
        is_hl = (not is_last) and label.startswith(highlight_prefixes)
        lbl = Paragraph(
            escape(label),
            ParagraphStyle(
                f"tot_l_{i}_{int(compact)}", parent=styles["Normal"],
                fontName="Helvetica-Bold" if (is_last or is_hl) else "Helvetica",
                fontSize=last_l if is_last else body,
                leading=(last_l if is_last else body) + 1,
                textColor=colors.HexColor("#0f172a" if is_last else ("#b45309" if is_hl else "#475569")),
            ),
        )
        val = Paragraph(
            escape(value),
            ParagraphStyle(
                f"tot_v_{i}_{int(compact)}", parent=styles["Normal"],
                fontName="Helvetica-Bold",
                fontSize=last_v if is_last else body,
                leading=(last_v if is_last else body) + 1,
                alignment=TA_RIGHT,
                textColor=colors.HexColor("#1e40af" if is_last else ("#b45309" if is_hl else "#0f172a")),
            ),
        )
        data.append([lbl, val])
    if content_width:
        col_widths = [content_width * 0.72, content_width * 0.28]
    else:
        col_widths = [11 * cm, 5 * cm]
    table = Table(data, colWidths=col_widths)
    style = [
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.6 if compact else 0.8, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), pad),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
        ("LEFTPADDING", (0, 0), (-1, -1), side),
        ("RIGHTPADDING", (0, 0), (-1, -1), side),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i, (label, _value) in enumerate(rows):
        if i != len(rows) - 1 and label.startswith(highlight_prefixes):
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fff7ed")))
    if len(rows) > 1:
        style.append(("LINEABOVE", (0, -1), (-1, -1), 1.2, colors.HexColor("#1e40af")))
        style.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eff6ff")))
    table.setStyle(TableStyle(style))
    return table

def _items_table(
    lines: List[Dict[str, Any]],
    image_urls: Dict[int, str | None],
    *,
    show_amounts: bool = True,
    amount_label: str = "Amount (Rs.)",
) -> Table:
    head = ["", "Code", "Description", "Qty"]
    if show_amounts:
        head += ["Rate (Rs.)", amount_label]
    col_widths = [1.5 * cm, 2.2 * cm, 6.0 * cm, 1.0 * cm]
    if show_amounts:
        col_widths += [2.0 * cm, 2.5 * cm]
    data: list[list[Any]] = [head]
    for i, ln in enumerate(lines):
        cid = int(ln.get("catalog_product_id") or 0)
        img = _fetch_image(image_urls.get(cid) or "", 1.3 * cm, 1.3 * cm) or ""
        qty = int(ln.get("quantity") or 0)
        row: list[Any] = [
            img,
            _safe(ln.get("our_product_id"), 24),
            _safe(ln.get("name") or ln.get("our_product_id"), 56),
            str(qty),
        ]
        if show_amounts:
            row += [
                _safe(ln.get("unit_price") or ln.get("rate_inclusive")),
                _safe(ln.get("line_total") or ln.get("amount")),
            ]
        data.append(row)
        for addon in ln.get("addons") or []:
            if not isinstance(addon, dict):
                continue
            per = int(addon.get("quantity") or 1)
            aq = per * max(qty, 1)
            atxt = f"  + {_safe(addon.get('name') or addon.get('our_product_id'), 40)} × {aq} {_safe(addon.get('unit') or 'pc', 8)} (included)"
            sub: list[Any] = ["", "", atxt, ""]
            if show_amounts:
                sub += ["", ""]
            data.append(sub)
    if len(data) < 2:
        placeholder = ["", "-", "No line items", ""] + (["", ""] if show_amounts else [])
        data.append(placeholder)
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#334155")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if show_amounts:
        style += [
            ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
            ("ALIGN", (3, 1), (3, -1), "CENTER"),
        ]
    table.setStyle(TableStyle(style))
    return table

def _vendor_order_table(
    lines: List[Dict[str, Any]],
    image_urls: Dict[int, str | None],
) -> Table:
    head = ["", "Code", "Description", "Qty", "Rate (Rs.)", "Amount (Rs.)"]
    col_widths = [1.4 * cm, 2.4 * cm, 5.8 * cm, 1.0 * cm, 2.0 * cm, 2.4 * cm]
    data: list[list[Any]] = [head]
    for ln in lines:
        cid = int(ln.get("catalog_product_id") or 0)
        img = _fetch_image(image_urls.get(cid) or "", 1.2 * cm, 1.2 * cm) or ""
        qty = int(ln.get("quantity") or 0)
        data.append([
            img,
            _code_pair(ln.get("vendor_product_id"), ln.get("our_product_id")),
            _safe(ln.get("name") or ln.get("vendor_product_id") or ln.get("our_product_id"), 48),
            str(qty),
            _safe(ln.get("unit_price")),
            _safe(ln.get("line_total")),
        ])
    if len(data) < 2:
        data.append(["", "-", "No line items", "", "", ""])
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

