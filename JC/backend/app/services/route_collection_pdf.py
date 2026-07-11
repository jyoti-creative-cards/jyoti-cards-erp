"""Route collection sheet PDF for agents."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.company_info import company_lines
from app.services.pdf_documents import _ist_fmt, _safe


def _money(v: object) -> str:
    try:
        return f"₹{float(v):,.2f}"
    except (TypeError, ValueError):
        return _safe(v)


def render_route_collection_pdf(payload: Dict[str, Any]) -> bytes:
    """
    payload keys:
      route_name, generated_at, total_outstanding, customers: [
        { business_name, person_name, phone, city_name, outstanding, ledger: [
            { date, entry_type, description, amount, running_balance }
        ]}
      ]
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.4 * cm,
        rightMargin=1.4 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.4 * cm,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "RCTitle",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=4,
    )
    sub = ParagraphStyle(
        "RCSub",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=8,
    )
    h2 = ParagraphStyle(
        "RCH2",
        parent=styles["Heading2"],
        fontSize=12,
        textColor=colors.HexColor("#1e40af"),
        spaceBefore=12,
        spaceAfter=6,
    )
    small = ParagraphStyle(
        "RCSmall",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#334155"),
    )
    right = ParagraphStyle("RCRight", parent=small, alignment=TA_RIGHT)

    story: list = []
    company = company_lines()
    story.append(Paragraph(escape(company[0] if company else "Jyoti Creative"), title))
    for line in (company or [])[1:3]:
        story.append(Paragraph(escape(line), sub))

    route_name = _safe(payload.get("route_name"), 80)
    gen = payload.get("generated_at") or datetime.now(timezone.utc)
    story.append(Paragraph(f"Route Collection — {escape(route_name)}", title))
    story.append(
        Paragraph(
            f"Generated {_ist_fmt(gen)} · Total outstanding <b>{escape(_money(payload.get('total_outstanding')))}</b>",
            sub,
        )
    )
    story.append(
        Paragraph(
            "Share with route agent: collect outstanding from each customer below.",
            sub,
        )
    )
    story.append(Spacer(1, 0.3 * cm))

    customers: List[Dict[str, Any]] = payload.get("customers") or []
    if not customers:
        story.append(Paragraph("No customers with outstanding on this route.", small))
    else:
        # Summary table
        sum_data = [["#", "Customer", "City", "Phone", "Outstanding"]]
        for i, c in enumerate(customers, 1):
            sum_data.append([
                str(i),
                _safe(c.get("business_name"), 36),
                _safe(c.get("city_name") or "—", 18),
                _safe(c.get("phone") or "—", 14),
                _money(c.get("outstanding")),
            ])
        sum_tbl = Table(sum_data, colWidths=[1.0 * cm, 6.0 * cm, 3.2 * cm, 3.0 * cm, 3.0 * cm])
        sum_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(sum_tbl)

        for c in customers:
            name = _safe(c.get("business_name"), 60)
            person = _safe(c.get("person_name") or "", 40)
            phone = _safe(c.get("phone") or "—", 14)
            city = _safe(c.get("city_name") or "—", 24)
            story.append(Paragraph(
                f"{escape(name)}"
                + (f" · {escape(person)}" if person else "")
                + f" · {escape(city)} · {escape(phone)} · Due {_money(c.get('outstanding'))}",
                h2,
            ))
            ledger = c.get("ledger") or []
            if not ledger:
                story.append(Paragraph("No ledger entries.", small))
                continue
            led_data = [["When", "Type", "Detail", "Amount", "Balance"]]
            for e in ledger:
                et = (e.get("entry_type") or "").title()
                when = e.get("created_at")
                when_s = _ist_fmt(when) if when else "—"
                led_data.append([
                    when_s,
                    et,
                    Paragraph(escape(_safe(e.get("description") or "—", 48)), small),
                    _money(e.get("signed_amount") or e.get("amount")),
                    _money(e.get("running_balance")),
                ])
            led_tbl = Table(led_data, colWidths=[3.2 * cm, 1.8 * cm, 6.0 * cm, 2.4 * cm, 2.4 * cm])
            led_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (-2, 0), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(led_tbl)

    story.append(Spacer(1, 0.8 * cm))
    story.append(Paragraph("Agent signature: ______________________ &nbsp;&nbsp; Date: __________", right))

    doc.build(story)
    return buf.getvalue()
