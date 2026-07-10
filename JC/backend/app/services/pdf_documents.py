"""Order receipts and vendor document PDFs."""
from __future__ import annotations

import urllib.request
from datetime import datetime, timezone, timedelta
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
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            data = r.read()
        buf = BytesIO(data)
        img = Image(buf)
        scale = min(max_w / img.drawWidth, max_h / img.drawHeight, 1.0)
        img.drawWidth *= scale
        img.drawHeight *= scale
        return img
    except Exception:
        return None


def _ist_fmt(dt: datetime | None) -> str:
    ts = dt or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ist = ts + timedelta(hours=5, minutes=30)
    return ist.strftime("%d %b %Y, %I:%M %p")


def _code_pair(vendor_code: str | None, our_code: str | None) -> str:
    v = _safe(vendor_code, 24)
    o = _safe(our_code, 24)
    if v != "-" and o != "-":
        return f"{v}/{o}"
    return o if o != "-" else v


def _party_blocks(our_lines: List[str], vendor_lines: List[str]) -> Table:
    styles = getSampleStyleSheet()
    label_style = ParagraphStyle(
        "party_lbl", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=8, textColor=colors.HexColor("#64748b"), spaceAfter=4, leading=10,
    )
    body_style_l = ParagraphStyle("party_l", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#0f172a"))
    body_style_r = ParagraphStyle(
        "party_r", parent=styles["Normal"], fontSize=9, leading=12,
        alignment=TA_RIGHT, textColor=colors.HexColor("#0f172a"),
    )

    def _cell(lines: List[str], right: bool = False) -> list:
        if not lines:
            return [Paragraph("—", body_style_r if right else body_style_l)]
        out = [Paragraph(escape(lines[0]).upper(), label_style)]
        for i, line in enumerate(lines[1:]):
            st = body_style_r if right else body_style_l
            if i == 0:
                st = ParagraphStyle(
                    "party_name", parent=st, fontName="Helvetica-Bold", fontSize=10, leading=13,
                )
            out.append(Paragraph(escape(line), st))
        return out

    left_flow = _cell(our_lines, False)
    right_flow = _cell(vendor_lines, True)
    # Wrap flows in nested tables for padding
    left_tbl = Table([[x] for x in left_flow], colWidths=[7.8 * cm])
    right_tbl = Table([[x] for x in right_flow], colWidths=[7.8 * cm])
    for t in (left_tbl, right_tbl):
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
    tbl = Table([[left_tbl, right_tbl]], colWidths=[8.5 * cm, 8.5 * cm])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f8fafc")),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#eff6ff")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#cbd5e1")),
        ("LINEAFTER", (0, 0), (0, 0), 0.5, colors.HexColor("#e2e8f0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return tbl


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


def _vendor_receipt_table(
    lines: List[Dict[str, Any]],
    image_urls: Dict[int, str | None],
) -> Table:
    head = ["", "Code", "Description", "Recv", "Billed", "Rate (Rs.)", "Amount (Rs.)"]
    col_widths = [1.2 * cm, 2.2 * cm, 4.8 * cm, 0.9 * cm, 0.9 * cm, 1.8 * cm, 2.2 * cm]
    data: list[list[Any]] = [head]
    for ln in lines:
        cid = int(ln.get("catalog_product_id") or 0)
        img = _fetch_image(image_urls.get(cid) or "", 1.1 * cm, 1.1 * cm) or ""
        data.append([
            img,
            _code_pair(ln.get("vendor_product_id"), ln.get("our_product_id")),
            _safe(ln.get("name") or ln.get("vendor_product_id") or ln.get("our_product_id"), 40),
            str(int(ln.get("quantity_received") or 0)),
            str(int(ln.get("quantity_billed") or 0)),
            _safe(ln.get("unit_price")),
            _safe(ln.get("line_total")),
        ])
    if len(data) < 2:
        data.append(["", "-", "No line items", "", "", "", ""])
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
        ("ALIGN", (3, 1), (4, -1), "CENTER"),
        ("ALIGN", (5, 1), (-1, -1), "RIGHT"),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, colors.HexColor("#e2e8f0")),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f8fafc")))
    table.setStyle(TableStyle(style_cmds))
    return table


def _totals_block(rows: List[List[str]]) -> Table:
    styles = getSampleStyleSheet()
    data = []
    for i, (label, value) in enumerate(rows):
        is_last = i == len(rows) - 1
        lbl = Paragraph(
            escape(label),
            ParagraphStyle(
                f"tot_l_{i}", parent=styles["Normal"],
                fontName="Helvetica-Bold" if is_last else "Helvetica",
                fontSize=10 if is_last else 9,
                textColor=colors.HexColor("#0f172a" if is_last else "#475569"),
            ),
        )
        val = Paragraph(
            escape(value),
            ParagraphStyle(
                f"tot_v_{i}", parent=styles["Normal"],
                fontName="Helvetica-Bold",
                fontSize=11 if is_last else 9,
                alignment=TA_RIGHT,
                textColor=colors.HexColor("#1e40af" if is_last else "#0f172a"),
            ),
        )
        data.append([lbl, val])
    table = Table(data, colWidths=[11 * cm, 5 * cm])
    style = [
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if len(rows) > 1:
        style.append(("LINEABOVE", (0, -1), (-1, -1), 1.2, colors.HexColor("#1e40af")))
        style.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eff6ff")))
    table.setStyle(TableStyle(style))
    return table


def _header(story: list, title: str, subtitle: str, meta: str) -> None:
    styles = getSampleStyleSheet()
    brand_bar = Table(
        [[Paragraph(
            "JYOTI CREATIVE CARDS",
            ParagraphStyle(
                "brand", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=14,
                alignment=TA_CENTER, textColor=colors.white, leading=18,
            ),
        )]],
        colWidths=[17 * cm],
    )
    brand_bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1e40af")),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(brand_bar)
    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph(escape(title), ParagraphStyle(
        "doc_title", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=16,
        alignment=TA_CENTER, textColor=colors.HexColor("#0f172a"), spaceAfter=4,
    )))
    story.append(Paragraph(escape(subtitle), ParagraphStyle(
        "doc_sub", parent=styles["Normal"], fontSize=9, alignment=TA_CENTER,
        textColor=colors.HexColor("#64748b"), spaceAfter=6,
    )))
    story.append(Paragraph(escape(meta), ParagraphStyle(
        "doc_meta", parent=styles["Normal"], fontSize=8, alignment=TA_CENTER,
        textColor=colors.HexColor("#94a3b8"), spaceAfter=12,
    )))
    rule = Table([[""]], colWidths=[17 * cm])
    rule.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1.5, colors.HexColor("#1e40af")),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(rule)


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
            aq = int(addon.get("quantity") or 1)
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


def render_customer_order_pdf(
    *,
    placement_id: int,
    customer_name: str,
    customer_phone: str | None = None,
    customer_address: str | None = None,
    customer_city: str | None = None,
    lines: List[Dict[str, Any]],
    image_urls: Dict[int, str | None],
    customer_notes: str | None = None,
    placed_at: datetime | None = None,
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    story: list = []
    total = sum(float(ln.get("line_total") or (float(ln.get("unit_price") or 0) * int(ln.get("quantity") or 0))) for ln in lines)
    _header(story, "ORDER RECEIPT", f"Customer: {_safe(customer_name, 80)}", f"Order #{placement_id} · {_ist_fmt(placed_at)}")
    styles = getSampleStyleSheet()
    info = [f"<b>Customer:</b> {escape(_safe(customer_name, 80))}"]
    if customer_phone:
        info.append(f"<b>Phone:</b> {escape(_safe(customer_phone, 20))}")
    if customer_address:
        info.append(f"<b>Address:</b> {escape(_safe(customer_address, 120))}")
    if customer_city:
        info.append(f"<b>City:</b> {escape(_safe(customer_city, 60))}")
    story.append(Paragraph("<br/>".join(info), ParagraphStyle("info", parent=styles["Normal"], fontSize=9, spaceAfter=12, leading=13)))
    story.append(_items_table(lines, image_urls, show_amounts=True))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Table([["Order Total", f"Rs. {total:,.2f}"]], colWidths=[10 * cm, 6 * cm], style=TableStyle([
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#334155")),
    ])))
    if customer_notes:
        story.append(Spacer(1, 0.35 * cm))
        story.append(Paragraph(f"<b>Customer notes:</b> {escape(_safe(customer_notes, 500))}", ParagraphStyle(
            "notes", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#92400e"),
            backColor=colors.HexColor("#fffbeb"), borderPadding=8, spaceAfter=8,
        )))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Thank you — our team will process your order shortly.", ParagraphStyle(
        "foot", parent=styles["Normal"], fontSize=8, alignment=TA_CENTER, textColor=colors.HexColor("#64748b"),
    )))
    doc.build(story)
    return buf.getvalue()


def render_vendor_placement_pdf(
    *,
    placement_id: int,
    vendor_name: str,
    vendor_phone: str | None = None,
    vendor_address: str | None = None,
    vendor_city: str | None = None,
    vendor_gst: str | None = None,
    vendor_person: str | None = None,
    lines: List[Dict[str, Any]],
    image_urls: Dict[int, str | None],
    placed_by: str,
    placed_at: datetime | None = None,
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    story: list = []
    _header(story, "VENDOR ORDER", "Purchase order — products only", f"Order #{placement_id} · {_ist_fmt(placed_at)} · Placed by {escape(_safe(placed_by, 40))}")
    our = ["From (Buyer)"] + company_lines()
    vendor = ["To (Vendor)", _safe(vendor_name, 80)]
    if vendor_person:
        vendor.append(f"Contact: {_safe(vendor_person, 60)}")
    if vendor_phone:
        vendor.append(f"Phone: {_safe(vendor_phone, 20)}")
    if vendor_address:
        vendor.append(_safe(vendor_address, 120))
    if vendor_city:
        vendor.append(_safe(vendor_city, 60))
    if vendor_gst:
        vendor.append(f"GSTIN: {_safe(vendor_gst, 20)}")
    story.append(_party_blocks(our, vendor))
    story.append(Spacer(1, 0.35 * cm))
    story.append(_vendor_order_table(lines, image_urls))
    total = sum(float(ln.get("line_total") or 0) for ln in lines)
    story.append(Spacer(1, 0.3 * cm))
    story.append(_totals_block([["Order Total", f"Rs. {total:,.2f}"]]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Please supply the above items as per agreed rates. Add-ons are handled separately and are not listed here.", ParagraphStyle(
        "foot", parent=getSampleStyleSheet()["Normal"], fontSize=8, alignment=TA_CENTER, textColor=colors.HexColor("#64748b"),
    )))
    doc.build(story)
    return buf.getvalue()


def render_vendor_receipt_pdf(
    *,
    receipt_id: int,
    vendor_name: str,
    vendor_phone: str | None = None,
    vendor_address: str | None = None,
    vendor_city: str | None = None,
    vendor_gst: str | None = None,
    vendor_person: str | None = None,
    bill_number: str | None,
    lines: List[Dict[str, Any]],
    image_urls: Dict[int, str | None],
    total_billed: str | None,
    debit_notes: List[Dict[str, Any]] | None = None,
    net_payable: str | None = None,
    received_by: str,
    received_at: datetime | None = None,
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    story: list = []
    bill_lbl = f"Bill No. {_safe(bill_number, 40)}" if bill_number else f"Receipt #{receipt_id}"
    _header(story, "GOODS RECEIPT", bill_lbl, f"{_ist_fmt(received_at)} · Received by {escape(_safe(received_by, 40))}")
    our = ["Received by"] + company_lines()
    vendor = ["Vendor", _safe(vendor_name, 80)]
    if vendor_person:
        vendor.append(f"Contact: {_safe(vendor_person, 60)}")
    if vendor_phone:
        vendor.append(f"Phone: {_safe(vendor_phone, 20)}")
    if vendor_address:
        vendor.append(_safe(vendor_address, 120))
    if vendor_city:
        vendor.append(_safe(vendor_city, 60))
    if vendor_gst:
        vendor.append(f"GSTIN: {_safe(vendor_gst, 20)}")
    story.append(_party_blocks(our, vendor))
    story.append(Spacer(1, 0.35 * cm))
    story.append(_vendor_receipt_table(lines, image_urls))
    totals: list[list[str]] = []
    if total_billed:
        totals.append(["Total Bill", f"Rs. {_safe(total_billed)}"])
    dn_rows = debit_notes or []
    if dn_rows:
        story.append(Spacer(1, 0.25 * cm))
        styles = getSampleStyleSheet()
        story.append(Paragraph("<b>Debit Note Adjustments</b>", ParagraphStyle("dnh", parent=styles["Normal"], fontSize=9, spaceAfter=6)))
        dn_data = [["Description", "Comments", "Amount (Rs.)"]]
        dn_total = 0.0
        for dn in dn_rows:
            amt = float(dn.get("amount") or 0)
            dn_total += amt
            label = _safe(dn.get("label"), 48)
            notes = _safe(dn.get("notes"), 80)
            sign = "+" if amt >= 0 else ""
            dn_data.append([label, notes, f"{sign}{amt:,.2f}"])
        dn_table = Table(dn_data, colWidths=[5.5 * cm, 7.5 * cm, 3 * cm])
        dn_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fef3c7")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#fcd34d")),
            ("ALIGN", (2, 1), (2, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(dn_table)
        dn_sign = "+" if dn_total >= 0 else ""
        totals.append(["Debit Notes", f"{dn_sign} Rs. {abs(dn_total):,.2f}"])
    if net_payable:
        totals.append(["Net Payable", f"Rs. {_safe(net_payable)}"])
    elif total_billed and not dn_rows:
        totals.append(["Net Payable", f"Rs. {_safe(total_billed)}"])
    if totals:
        story.append(Spacer(1, 0.3 * cm))
        story.append(_totals_block(totals))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("This is a goods receipt for vendor billing. Please retain for accounts and godown records.", ParagraphStyle(
        "foot", parent=getSampleStyleSheet()["Normal"], fontSize=8, alignment=TA_CENTER, textColor=colors.HexColor("#64748b"),
    )))
    doc.build(story)
    return buf.getvalue()
