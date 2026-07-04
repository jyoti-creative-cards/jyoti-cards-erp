"""
Generate a professional HTML→PDF order receipt using WeasyPrint (if available) or
fall back to a ReportLab plain-text receipt.
The HTML receipt mirrors the customer portal print layout.
"""
from __future__ import annotations

import urllib.request
import base64
from io import BytesIO
from typing import Any, Dict, List, Optional


def _img_b64(url: str) -> str:
    """Download image and return base64 data URI, or empty string on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            data = r.read()
        ext = (url.split("?")[0].rsplit(".", 1)[-1] or "jpeg").lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"
    except Exception:
        return ""


def _fmt_amount(v) -> str:
    try:
        return f"₹{float(v):,.2f}"
    except Exception:
        return f"₹{v}"


def build_order_receipt_html(
    items: List[Dict[str, Any]],
    image_urls: Dict[int, str],
    order_id: int,
    customer_name: str,
    customer_phone: str = "",
    customer_address: str = "",
    customer_city: str = "",
    customer_gst: str = "",
    order_date: str = "",
    order_status: str = "received",
    total_amount: str = "0",
    customer_note: str = "",
) -> str:
    """Return complete HTML string for the order receipt."""

    rows_html = ""
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        cid = int(it.get("catalog_product_id", 0))
        our_id = str(it.get("our_product_id") or "—")
        name = str(it.get("name") or "")
        category = str(it.get("category") or "")
        qty = it.get("quantity", 1)
        unit_price = str(it.get("unit_price") or "0")
        line_total = str(it.get("line_total") or "0")

        img_src = image_urls.get(cid, "")
        if img_src and not img_src.startswith("data:"):
            img_src = _img_b64(img_src)

        if img_src:
            img_tag = f'<img src="{img_src}" style="width:52px;height:52px;object-fit:contain;border-radius:6px;border:1px solid #e5e7eb;" />'
        else:
            img_tag = '<div style="width:52px;height:52px;border-radius:6px;border:1px solid #e5e7eb;background:#f9fafb;display:flex;align-items:center;justify-content:center;color:#d1d5db;font-size:18px;">✦</div>'

        bg = "#f9fafb" if i % 2 == 1 else "#ffffff"
        rows_html += f"""
        <tr style="background:{bg};">
          <td style="padding:10px 8px;text-align:center;vertical-align:middle;">{img_tag}</td>
          <td style="padding:10px 8px;vertical-align:middle;">
            <div style="font-weight:700;font-size:13px;color:#1f2937;">{our_id}</div>
            <div style="font-size:12px;color:#374151;margin-top:2px;">{name}</div>
            {f'<div style="font-size:11px;color:#9ca3af;margin-top:1px;">{category}</div>' if category else ''}
          </td>
          <td style="padding:10px 8px;text-align:right;vertical-align:middle;font-variant-numeric:tabular-nums;">{qty}</td>
          <td style="padding:10px 8px;text-align:right;vertical-align:middle;font-variant-numeric:tabular-nums;">{_fmt_amount(unit_price)}</td>
          <td style="padding:10px 8px;text-align:right;vertical-align:middle;font-weight:600;font-variant-numeric:tabular-nums;">{_fmt_amount(line_total)}</td>
        </tr>"""

    status_color = {"received": "#92400e", "billed": "#4c1d95", "closed": "#065f46"}.get(order_status.lower(), "#374151")
    status_bg = {"received": "#fef3c7", "billed": "#ede9fe", "closed": "#d1fae5"}.get(order_status.lower(), "#f3f4f6")

    contact_person = ""  # populated in caller if different from company name
    note_html = f"""
    <div style="margin-top:16px;border:1px solid #fde68a;background:#fffbeb;border-radius:8px;padding:12px 14px;">
      <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#b45309;margin-bottom:4px;">Customer Note</div>
      <div style="font-size:13px;color:#374151;">{customer_note}</div>
    </div>""" if customer_note else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Order Receipt #{order_id} — Jyoti Creative Cards</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #111827; background: #fff; padding: 36px; font-size: 13px; }}
    @media print {{ body {{ padding: 16px; }} @page {{ margin: 14mm; }} }}
    .header {{ display: flex; justify-content: space-between; align-items: flex-start; padding-bottom: 18px; margin-bottom: 20px; border-bottom: 3px solid #8B1C0A; }}
    .logo {{ width: 40px; height: 40px; border-radius: 10px; background: linear-gradient(135deg,#8B1C0A,#c0392b); display: inline-flex; align-items: center; justify-content: center; color: white; font-weight: 900; font-size: 14px; margin-right: 12px; vertical-align: middle; }}
    .brand-name {{ font-size: 20px; font-weight: 800; color: #8B1C0A; }}
    .brand-sub {{ font-size: 11px; color: #6b7280; margin-top: 2px; }}
    .meta {{ display: flex; gap: 16px; margin-bottom: 24px; }}
    .meta-card {{ flex: 1; background: #f9fafb; border: 1px solid #f3f4f6; border-radius: 10px; padding: 14px 16px; }}
    .meta-card h4 {{ font-size: 9px; text-transform: uppercase; letter-spacing: 1px; color: #9ca3af; font-weight: 700; margin-bottom: 8px; }}
    .meta-card .primary {{ font-size: 15px; font-weight: 800; color: #111827; margin-bottom: 4px; }}
    .meta-card p {{ font-size: 12px; color: #374151; line-height: 1.6; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 16px; }}
    thead tr {{ background: #111827; }}
    thead th {{ padding: 9px 8px; color: white; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }}
    thead th:nth-child(n+3) {{ text-align: right; }}
    .total-bar {{ display: flex; justify-content: flex-end; margin-top: 4px; }}
    .total-box {{ background: #8B1C0A; color: white; border-radius: 10px; padding: 12px 20px; display: inline-flex; gap: 20px; align-items: center; }}
    .footer {{ margin-top: 28px; border-top: 1px solid #e5e7eb; padding-top: 14px; text-align: center; font-size: 11px; color: #9ca3af; }}
  </style>
</head>
<body>
  <div class="header">
    <div>
      <span class="logo">JC</span>
      <span style="vertical-align:middle;">
        <span class="brand-name">Jyoti Creative Cards</span><br/>
        <span class="brand-sub">Cards, Stationery &amp; Creative Supplies</span>
      </span>
    </div>
    <div style="text-align:right;">
      <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#9ca3af;">Order Receipt</div>
      <div style="font-size:28px;font-weight:900;color:#111827;">#{order_id}</div>
      <div style="font-size:11px;color:#6b7280;margin-top:3px;">{order_date}</div>
    </div>
  </div>

  <div class="meta">
    <div class="meta-card">
      <h4>Bill To</h4>
      <div class="primary">{customer_name or '—'}</div>
      {f'<p>{customer_phone}</p>' if customer_phone else ''}
      {f'<p>{customer_address}</p>' if customer_address else ''}
      {f'<p>{customer_city}</p>' if customer_city else ''}
      {f'<p>GST: {customer_gst}</p>' if customer_gst else ''}
    </div>
    <div class="meta-card">
      <h4>Order Details</h4>
      <p><span style="color:#9ca3af;">Order #</span> <strong>{order_id}</strong></p>
      <p><span style="color:#9ca3af;">Date</span> {order_date}</p>
      <p><span style="color:#9ca3af;">Status</span>
        <span style="display:inline-block;padding:2px 10px;border-radius:20px;font-size:11px;font-weight:700;background:{status_bg};color:{status_color};">{order_status.title()}</span>
      </p>
    </div>
  </div>

  {note_html}

  <table style="margin-top:{('16px' if customer_note else '0')};">
    <thead>
      <tr>
        <th style="width:60px;text-align:center;">Photo</th>
        <th style="text-align:left;">Item</th>
        <th style="text-align:right;">Qty</th>
        <th style="text-align:right;">Unit Price</th>
        <th style="text-align:right;">Amount</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>

  <div class="total-bar">
    <div class="total-box">
      <span style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:rgba(255,255,255,0.7);">Order Total</span>
      <span style="font-size:24px;font-weight:900;font-variant-numeric:tabular-nums;">{_fmt_amount(total_amount)}</span>
    </div>
  </div>

  <div class="footer">
    Jyoti Creative Cards · Cards, Stationery &amp; Creative Supplies<br/>
    Thank you for your order — we will confirm shortly on WhatsApp.
  </div>
</body>
</html>"""


def build_order_items_pdf(
    items: List[Dict[str, Any]],
    image_urls: Dict[int, str],
    order_id: int,
    customer_name: str,
    customer_phone: str = "",
    customer_address: str = "",
    customer_city: str = "",
    customer_gst: str = "",
    order_date: str = "",
    order_status: str = "received",
    total_amount: str = "0",
    customer_note: str = "",
) -> bytes:
    """Return PDF bytes for the order receipt.
    
    Tries WeasyPrint first (high-quality HTML→PDF), falls back to ReportLab.
    """
    html = build_order_receipt_html(
        items=items,
        image_urls=image_urls,
        order_id=order_id,
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_address=customer_address,
        customer_city=customer_city,
        customer_gst=customer_gst,
        order_date=order_date,
        order_status=order_status,
        total_amount=total_amount,
        customer_note=customer_note,
    )
    try:
        from weasyprint import HTML  # type: ignore
        return HTML(string=html).write_pdf()
    except ImportError:
        pass

    # Fallback: ReportLab plain-text receipt
    return _reportlab_fallback(items, order_id, customer_name, total_amount, order_date, customer_note)


def _reportlab_fallback(
    items: List[Dict[str, Any]],
    order_id: int,
    customer_name: str,
    total_amount: str,
    order_date: str,
    customer_note: str,
) -> bytes:
    """Simple ReportLab PDF as fallback when WeasyPrint not installed."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=1.5*cm, bottomMargin=1.5*cm,
                            leftMargin=1.5*cm, rightMargin=1.5*cm)
    styles = getSampleStyleSheet()
    brand_color = colors.HexColor("#8B1C0A")

    title_style = ParagraphStyle("title", parent=styles["Normal"],
                                  fontSize=16, fontName="Helvetica-Bold", textColor=brand_color, spaceAfter=4)
    sub_style = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9, textColor=colors.grey, spaceAfter=12)
    label_style = ParagraphStyle("label", parent=styles["Normal"], fontSize=9, textColor=colors.grey)
    normal = styles["Normal"]
    normal.fontSize = 10

    story = [
        Paragraph("Jyoti Creative Cards", title_style),
        Paragraph("Cards, Stationery &amp; Creative Supplies", sub_style),
        Paragraph(f"<b>Order Receipt #{order_id}</b>", ParagraphStyle("h2", parent=styles["Normal"], fontSize=14, spaceAfter=4)),
        Paragraph(f"Date: {order_date}   Customer: {customer_name}", label_style),
        Spacer(1, 0.4*cm),
    ]

    if customer_note:
        story += [
            Paragraph(f"<b>Customer Note:</b> {customer_note}", ParagraphStyle("note", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#92400e"), backColor=colors.HexColor("#fffbeb"), borderPadding=8)),
            Spacer(1, 0.3*cm),
        ]

    # Items table
    head = [["Item #", "Name / Category", "Qty", "Unit Price", "Total"]]
    data = head[:]
    for it in items:
        if not isinstance(it, dict):
            continue
        cat = str(it.get("category") or "")
        name = str(it.get("name") or "")
        desc = f"{name}\n{cat}" if cat else name
        data.append([
            str(it.get("our_product_id") or ""),
            Paragraph(desc, ParagraphStyle("cell", parent=styles["Normal"], fontSize=9)),
            str(it.get("quantity") or ""),
            f"Rs.{it.get('unit_price','0')}",
            f"Rs.{it.get('line_total','0')}",
        ])
    # totals row
    data.append(["", Paragraph("<b>TOTAL</b>", ParagraphStyle("tot", parent=styles["Normal"], fontSize=10, alignment=TA_RIGHT)), "", "", f"<b>Rs.{total_amount}</b>"])

    tbl = Table(data, colWidths=[2.5*cm, 7.0*cm, 1.5*cm, 2.5*cm, 2.5*cm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("FONTNAME",  (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",  (0, 0), (-1, -1), 9),
        ("BACKGROUND",(0, 0), (-1, 0), brand_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN",     (2, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, -1), (-1, -1), 1, colors.HexColor("#8B1C0A")),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#8B1C0A")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f9fafb")]),
        ("VALIGN",    (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("Thank you for your order. We will confirm shortly on WhatsApp.", sub_style))
    doc.build(story)
    return buf.getvalue()
