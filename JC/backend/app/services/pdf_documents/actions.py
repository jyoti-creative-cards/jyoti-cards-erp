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


def _party_block_single(lines: List[str], *, bold_idxs: set[int] | None = None) -> Table:
    """Full-width 'Bill to' block with no 'From' column — used on non-GST customer
    estimates, which intentionally omit our own name/address (see Order Estimate PDF).

    bold_idxs: indices into lines[1:] (0 = the party name, already always bold) that
    should also render in the same bold/larger style — e.g. the city, since the
    transport company reads it off this printout to route the goods."""
    bold_idxs = bold_idxs or set()
    styles = getSampleStyleSheet()
    label_style = ParagraphStyle(
        "party_lbl_s", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=8, textColor=colors.HexColor("#64748b"), spaceAfter=4, leading=10,
    )
    body_style = ParagraphStyle("party_l_s", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#0f172a"))

    if not lines:
        flow = [Paragraph("—", body_style)]
    else:
        flow = [Paragraph(escape(lines[0]).upper(), label_style)]
        for i, line in enumerate(lines[1:]):
            st = body_style
            if i == 0 or i in bold_idxs:
                st = ParagraphStyle(f"party_name_s_{i}", parent=st, fontName="Helvetica-Bold", fontSize=10, leading=13)
            flow.append(Paragraph(escape(line), st))

    inner = Table([[x] for x in flow], colWidths=[16 * cm])
    inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    tbl = Table([[inner]], colWidths=[17 * cm])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eff6ff")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return tbl

