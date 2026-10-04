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

def _code_pair(vendor_code: str | None, our_code: str | None) -> str:
    """Vendor's item number first, ours in brackets — matches vendor's paper bill/challan."""
    v = _safe(vendor_code, 24)
    o = _safe(our_code, 24)
    if v != "-" and o != "-":
        return f"{v} ({o})"
    return v if v != "-" else o

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

def _header(
    story: list,
    title: str,
    subtitle: str,
    meta: str,
    *,
    brand_override: str | None = None,
    compact: bool = False,
    content_width: float | None = None,
) -> None:
    styles = getSampleStyleSheet()
    width = content_width if content_width is not None else 17 * cm
    brand_size = 11 if compact else 14
    brand_bar = Table(
        [[Paragraph(
            escape(brand_override or company_lines()[0]),
            ParagraphStyle(
                "brand", parent=styles["Normal"], fontName="Helvetica-Bold",
                fontSize=brand_size,
                alignment=TA_CENTER, textColor=colors.white, leading=brand_size + 2,
            ),
        )]],
        colWidths=[width],
    )
    brand_pad = 3 if compact else 12
    brand_bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1e40af")),
        ("TOPPADDING", (0, 0), (-1, -1), brand_pad),
        ("BOTTOMPADDING", (0, 0), (-1, -1), brand_pad),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(brand_bar)
    story.append(Spacer(1, 0.08 * cm if compact else 0.35 * cm))
    # Empty title/subtitle/meta are skipped entirely (not just blank) — used by the
    # non-GST "Order Estimate" bill, which shows only the one brand-bar heading, no
    # second "ORDER ESTIMATE" title line underneath it.
    if title:
        story.append(Paragraph(escape(title), ParagraphStyle(
            "doc_title", parent=styles["Normal"], fontName="Helvetica-Bold",
            fontSize=11 if compact else 16,
            alignment=TA_CENTER, textColor=colors.HexColor("#0f172a"),
            spaceAfter=1 if compact else 4, leading=13 if compact else 18,
        )))
    if subtitle:
        story.append(Paragraph(escape(subtitle), ParagraphStyle(
            "doc_sub", parent=styles["Normal"], fontSize=7.5 if compact else 9,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#64748b"), spaceAfter=1 if compact else 6,
            leading=9 if compact else 11,
        )))
    if meta:
        story.append(Paragraph(escape(meta), ParagraphStyle(
            "doc_meta", parent=styles["Normal"], fontSize=7.5 if compact else 8,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#94a3b8"), spaceAfter=1 if compact else 12,
            leading=9 if compact else 10,
        )))
    rule = Table([[""]], colWidths=[width])
    rule.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.6 if compact else 1.5, colors.HexColor("#1e40af")),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1 if compact else 8),
    ]))
    story.append(rule)

def _ist_fmt(dt: datetime | None) -> str:
    from app.services.biz_date import format_ist
    return format_ist(dt)

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

def add_page_number(canvas, doc) -> None:
    """Shared onPage callback — stamps 'Page N' bottom-right of every printed document.

    Multi-line receipts/bills/statements can silently spill onto extra pages with no
    visual cue; this makes page count/order obvious when printed or paged through.
    """
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#94a3b8"))
    canvas.drawRightString(doc.pagesize[0] - 1.2 * cm, 0.8 * cm, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()

