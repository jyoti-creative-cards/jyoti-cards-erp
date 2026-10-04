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
from app.services.pdf_parts.render_customer_return_pdf import _items_table, _totals_block, _vendor_order_table

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
    order_receipt_number: str | None = None,
    charge_lines: List[Dict[str, Any]] | None = None,
    lines: List[Dict[str, Any]],
    image_urls: Dict[int, str | None],
    total_billed: str | None,
    debit_notes: List[Dict[str, Any]] | None = None,
    net_payable: str | None = None,
    received_by: str,
    received_at: datetime | None = None,
    gst_included: bool = False,
    gst_rate_pct: Decimal | None = None,
    extra_cash: str | None = None,
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    story: list = []
    bits = []
    if order_receipt_number:
        bits.append(f"Receipt No. {_safe(order_receipt_number, 40)}")
    if bill_number:
        bits.append(f"Bill No. {_safe(bill_number, 40)}")
    bill_lbl = " · ".join(bits) if bits else f"Receipt #{receipt_id}"
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
    if total_billed and gst_included and gst_rate_pct and gst_rate_pct > 0:
        try:
            total_dec = Decimal(str(total_billed))
            rate = Decimal(str(gst_rate_pct))
            taxable = (total_dec / (Decimal("100") + rate) * Decimal("100")).quantize(Decimal("0.01"))
            gst_amt = (total_dec - taxable).quantize(Decimal("0.01"))
            totals.append(["Taxable Value", f"Rs. {taxable:,.2f}"])
            totals.append([f"GST ({rate}%)", f"Rs. {gst_amt:,.2f}"])
        except Exception:
            pass
    for charge in charge_lines or []:
        label = _safe(charge.get("label") or "Charge", 48)
        amount = charge.get("amount")
        if amount is None or str(amount).strip() == "":
            continue
        totals.append([label, f"Rs. {_safe(amount)}"])
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
    if extra_cash:
        try:
            extra_dec = Decimal(str(extra_cash))
            if extra_dec != 0:
                base = Decimal(str(net_payable or total_billed or "0"))
                totals.append(["Extra Cash (untaxed, half-price balance)", f"Rs. {extra_dec:,.2f}"])
                totals.append(["Total Payable (incl. extra cash)", f"Rs. {(base + extra_dec):,.2f}"])
        except Exception:
            pass
    if totals:
        story.append(Spacer(1, 0.3 * cm))
        story.append(_totals_block(totals))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("This is a goods receipt for vendor billing. Please retain for accounts and godown records.", ParagraphStyle(
        "foot", parent=getSampleStyleSheet()["Normal"], fontSize=8, alignment=TA_CENTER, textColor=colors.HexColor("#64748b"),
    )))
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return buf.getvalue()

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
    outstanding: float | None = None,
    source_line: str | None = None,
    ordered_by: str | None = None,
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    story: list = []
    total = sum(float(ln.get("line_total") or (float(ln.get("unit_price") or 0) * int(ln.get("quantity") or 0))) for ln in lines)
    by_bit = f" · By {escape(_safe(ordered_by, 40))}" if ordered_by else ""
    _header(story, "ORDER RECEIPT", f"Customer: {_safe(customer_name, 80)}", f"Order #{placement_id} · {_ist_fmt(placed_at)}{by_bit}")
    styles = getSampleStyleSheet()
    info = [f"<b>Customer:</b> {escape(_safe(customer_name, 80))}"]
    if customer_phone:
        info.append(f"<b>Phone:</b> {escape(_safe(customer_phone, 20))}")
    if customer_address:
        info.append(f"<b>Address:</b> {escape(_safe(customer_address, 120))}")
    if customer_city:
        info.append(f"<b>City:</b> {escape(_safe(customer_city, 60))}")
    info.append(f"<b>Order date:</b> {escape(_ist_fmt(placed_at))}")
    if ordered_by:
        info.append(f"<b>By:</b> {escape(_safe(ordered_by, 40))}")
    if source_line:
        info.append(f"<b>Order from:</b> {escape(_safe(source_line, 80))}")
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
    if outstanding is not None:
        story.append(Paragraph(escape(f"Outstanding: Rs. {outstanding:,.2f}"), ParagraphStyle(
            "outstanding_line", parent=styles["Normal"], fontSize=8.5, fontName="Helvetica-Bold",
            textColor=colors.HexColor("#1d4ed8"), spaceBefore=6, spaceAfter=4,
        )))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Thank you — our team will process your order shortly.", ParagraphStyle(
        "foot", parent=styles["Normal"], fontSize=8, alignment=TA_CENTER, textColor=colors.HexColor("#64748b"),
    )))
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return buf.getvalue()

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
    else:
        recv_sum = sum(int(ln.get("quantity_received") or 0) for ln in lines)
        billed_sum = sum(int(ln.get("quantity_billed") or 0) for ln in lines)
        data.append(["", "", "Total quantity", str(recv_sum), str(billed_sum), "", ""])
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
    last = len(data) - 1
    for i in range(1, last if lines else len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f8fafc")))
    if lines:
        style_cmds.append(("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"))
        style_cmds.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e2e8f0")))
    table.setStyle(TableStyle(style_cmds))
    return table

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
    # line_total is "—" (not a number) when the viewer lacks costs.read — cost_visibility
    # redacts per-line buying-price fields, so summing them here would either crash on the
    # string or (worse, if silently coerced to 0 upstream) render a fake real-looking
    # "Order Total ₹0" instead of an honest redaction.
    try:
        total_str = f"Rs. {sum(float(ln.get('line_total') or 0) for ln in lines):,.2f}"
    except (TypeError, ValueError):
        total_str = "—"
    story.append(Spacer(1, 0.3 * cm))
    story.append(_totals_block([["Order Total", total_str]]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Please supply the above items as per agreed rates. Add-ons are handled separately and are not listed here.", ParagraphStyle(
        "foot", parent=getSampleStyleSheet()["Normal"], fontSize=8, alignment=TA_CENTER, textColor=colors.HexColor("#64748b"),
    )))
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return buf.getvalue()

