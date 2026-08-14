"""PDF builders for statements, daybook, ageing."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.services.ap_ledger import build_ap_ledger, vendor_ap_totals, _vendor_label
from app.services.ar_ledger import build_ar_ledger, customer_ar_totals, _customer_label
from app.services.reports import daybook
from app.services.reports_extended import ageing_ap, ageing_ar


def _money(v) -> str:
    try:
        n = Decimal(str(v or 0))
    except Exception:
        return str(v)
    return f"Rs.{n:,.2f}"


def _doc() -> tuple[SimpleDocTemplate, list, object]:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm)
    styles = getSampleStyleSheet()
    return doc, buf, styles


def render_ar_statement_pdf(db: Session, customer_id: int) -> bytes:
    doc, buf, styles = _doc()
    totals = customer_ar_totals(db, customer_id)
    entries = build_ar_ledger(db, customer_id)
    story = [
        Paragraph("Customer statement (AR)", styles["Heading1"]),
        Paragraph(_customer_label(db, customer_id), styles["Heading3"]),
        Spacer(1, 6),
        Paragraph(
            f"Opening {_money(totals['opening_total'])} · Bills {_money(totals['bill_total'])} · "
            f"Payments {_money(totals['payment_total'])} · Credits {_money(totals['credit_total'])} · "
            f"<b>Due {_money(totals['outstanding'])}</b>",
            styles["Normal"],
        ),
        Spacer(1, 10),
    ]
    rows = [["Date", "Type", "Particulars", "Amount", "Balance"]]
    for e in reversed(entries):
        rows.append([
            e.get("value_date") or (e.get("created_at") or "")[:10],
            e.get("entry_type") or "",
            (e.get("description") or "")[:48],
            _money(e.get("signed_amount") or e.get("amount")),
            _money(e.get("running_balance")),
        ])
    t = Table(rows, colWidths=[70, 70, 200, 80, 80])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(t)
    doc.build(story)
    return buf.getvalue()


def render_ap_statement_pdf(db: Session, vendor_id: int) -> bytes:
    doc, buf, styles = _doc()
    totals = vendor_ap_totals(db, vendor_id)
    entries = build_ap_ledger(db, vendor_id)
    story = [
        Paragraph("Vendor statement (AP)", styles["Heading1"]),
        Paragraph(_vendor_label(db, vendor_id), styles["Heading3"]),
        Spacer(1, 6),
        Paragraph(
            f"Opening {_money(totals['opening_total'])} · Bills {_money(totals['bill_total'])} · "
            f"Paid {_money(totals['payment_total'])} · DN {_money(totals['debit_note_total'])} · "
            f"<b>Due {_money(totals['outstanding'])}</b>",
            styles["Normal"],
        ),
        Spacer(1, 10),
    ]
    rows = [["Date", "Type", "Particulars", "Amount", "Balance"]]
    for e in reversed(entries):
        rows.append([
            e.get("value_date") or (e.get("created_at") or "")[:10],
            e.get("entry_type") or "",
            (e.get("description") or "")[:48],
            _money(e.get("signed_amount") or e.get("amount")),
            _money(e.get("running_balance")),
        ])
    t = Table(rows, colWidths=[70, 70, 200, 80, 80])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    story.append(t)
    doc.build(story)
    return buf.getvalue()


def render_daybook_pdf(db: Session, day: date) -> bytes:
    data = daybook(db, day)
    doc, buf, styles = _doc()
    t = data.get("totals") or {}
    story = [
        Paragraph(f"Daybook — {day.isoformat()}", styles["Heading1"]),
        Paragraph(
            f"Entries {t.get('count', 0)} · Cash in {_money(t.get('cash_in'))} · Cash out {_money(t.get('cash_out'))} · "
            f"Sales {t.get('sales_count', 0)} · Purchases {t.get('purchase_count', 0)}",
            styles["Normal"],
        ),
        Spacer(1, 10),
    ]
    rows = [["Time", "Type", "Party", "Particulars", "Amount"]]
    for e in data.get("entries") or []:
        rows.append([
            (e.get("at") or "")[:16].replace("T", " "),
            e.get("kind") or "",
            (e.get("party") or "")[:28],
            (e.get("label") or "")[:40],
            _money(e.get("amount")),
        ])
    table = Table(rows, colWidths=[90, 70, 100, 150, 70])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    story.append(table)
    doc.build(story)
    return buf.getvalue()


def render_ageing_pdf(db: Session, side: str, as_of: Optional[date] = None) -> bytes:
    data = ageing_ar(db, as_of) if side == "ar" else ageing_ap(db, as_of)
    doc, buf, styles = _doc()
    title = "AR ageing (customers)" if side == "ar" else "AP ageing (vendors)"
    tot = data.get("totals") or {}
    story = [
        Paragraph(title, styles["Heading1"]),
        Paragraph(f"As on {data.get('as_of')}", styles["Normal"]),
        Paragraph(
            f"0–30 {_money(tot.get('0-30'))} · 31–60 {_money(tot.get('31-60'))} · "
            f"61–90 {_money(tot.get('61-90'))} · 90+ {_money(tot.get('90+'))}",
            styles["Normal"],
        ),
        Spacer(1, 10),
    ]
    rows = [["Party", "Total", "0–30", "31–60", "61–90", "90+"]]
    for it in data.get("items") or []:
        rows.append([
            (it.get("label") or "")[:36],
            _money(it.get("outstanding")),
            _money(it.get("b0_30")),
            _money(it.get("b31_60")),
            _money(it.get("b61_90")),
            _money(it.get("b90_plus")),
        ])
    table = Table(rows, colWidths=[160, 70, 60, 60, 60, 60])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    story.append(table)
    doc.build(story)
    return buf.getvalue()


def render_freight_statement_pdf(db: Session, agent_id: int) -> bytes:
    from app.models.freight_agent import FreightAgent
    from app.services.freight_ledger import agent_freight_totals, build_freight_ledger

    agent = db.get(FreightAgent, agent_id)
    if not agent:
        raise ValueError("freight agent not found")
    totals = agent_freight_totals(db, agent_id)
    entries = build_freight_ledger(db, agent_id)
    doc, buf, styles = _doc()
    story = [
        Paragraph("Freight agent statement", styles["Heading1"]),
        Paragraph(agent.name, styles["Heading3"]),
        Spacer(1, 6),
        Paragraph(
            f"Charges {_money(totals['charge_total'])} · Paid {_money(totals['settlement_total'])} · "
            f"Due {_money(totals['due'])} · Advance left {_money(totals['advance_left'])}",
            styles["Normal"],
        ),
        Spacer(1, 10),
    ]
    rows = [["Date", "Type", "Party", "Amount", "Balance"]]
    for e in reversed(entries):
        party = e.get("party_label") or e.get("transaction_ref") or (e.get("notes") or "")[:40]
        rows.append([
            (e.get("created_at") or "")[:10],
            e.get("entry_type") or "",
            (party or "")[:40],
            _money(e.get("signed_amount") or e.get("amount")),
            _money(e.get("running_balance")),
        ])
    t = Table(rows, colWidths=[70, 70, 200, 80, 80])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    story.append(t)
    doc.build(story)
    return buf.getvalue()


def render_freight_payment_pdf(
    db: Session,
    *,
    agent_id: int,
    entry_id: int,
) -> bytes:
    from app.models.freight_agent import FreightAgent, FreightLedgerEntry
    from app.services.freight_ledger import agent_freight_totals, open_freight_charges

    agent = db.get(FreightAgent, agent_id)
    entry = db.get(FreightLedgerEntry, entry_id)
    if not agent or not entry or entry.freight_agent_id != agent_id:
        raise ValueError("freight payment not found")
    totals = agent_freight_totals(db, agent_id)
    charges = open_freight_charges(db, agent_id)
    kind = "Advance paid" if entry.entry_type == "advance" else "Freight payment"
    doc, buf, styles = _doc()
    story = [
        Paragraph(kind, styles["Heading1"]),
        Paragraph(agent.name, styles["Heading3"]),
        Spacer(1, 6),
        Paragraph(f"Amount {_money(abs(entry.amount))}", styles["Normal"]),
        Paragraph(f"Ref: {entry.transaction_ref or '—'}", styles["Normal"]),
        Paragraph(f"Date: {(entry.created_at.isoformat() if entry.created_at else '')[:10]}", styles["Normal"]),
        Paragraph(f"By: {entry.created_by_name or '—'}", styles["Normal"]),
    ]
    if entry.notes:
        story.append(Paragraph(f"Notes: {entry.notes}", styles["Normal"]))
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            f"Balance after — Due {_money(totals['due'])} · Advance left {_money(totals['advance_left'])}",
            styles["Normal"],
        )
    )
    if charges and entry.entry_type == "settlement":
        story.append(Spacer(1, 10))
        story.append(Paragraph("Parties (recent freight jobs)", styles["Heading3"]))
        rows = [["Party", "Bill", "Freight"]]
        for c in charges[:15]:
            rows.append([
                (c.get("party_label") or "—")[:36],
                (c.get("bill_number") or "—")[:16],
                _money(c.get("amount")),
            ])
        t = Table(rows, colWidths=[220, 100, 80])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ]))
        story.append(t)
    doc.build(story)
    return buf.getvalue()
