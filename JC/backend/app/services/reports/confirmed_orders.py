"""Confirmed orders for one IST day, with item numbers."""

from __future__ import annotations

from datetime import date, datetime, timezone
from io import BytesIO
from typing import Optional
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.models.city import City
from app.models.customer import Customer
from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderPlacement
from app.services.biz_date import ist_day_bounds_utc
from app.services.customer_selling.marking import single_mark
from app.services.pdf_documents import add_page_number


def _report_bounds(on: Optional[date], from_date: Optional[date], to_date: Optional[date]):
    if on is not None:
        return ist_day_bounds_utc(on)
    if from_date is None and to_date is None:
        return None, None
    start_day = from_date or to_date
    end_day = to_date or from_date
    start, _ = ist_day_bounds_utc(start_day)
    _, end = ist_day_bounds_utc(end_day)
    if end < start:
        start, end = end, start
    return start, end


def _ist_day(value: datetime | None) -> date | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("Asia/Kolkata")).date()


def confirmed_order_report(
    db: Session,
    on: Optional[date] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> dict:
    """Still-confirmed orders only. A bill that already took the qty is not listed."""
    start, end = _report_bounds(on, from_date, to_date)
    label = "all" if start is None else (on.isoformat() if on else f"{(from_date or to_date).isoformat()} to {(to_date or from_date).isoformat()}")
    open_lines = (
        db.query(CustomerOpenLine, Customer, City.name)
        .join(Customer, Customer.id == CustomerOpenLine.customer_id)
        .outerjoin(City, City.id == Customer.city_id)
        .filter(
            CustomerOpenLine.status == "open",
            CustomerOpenLine.quantity_open > 0,
            Customer.deleted_at.is_(None),
        )
        .order_by(Customer.business_name.asc(), CustomerOpenLine.id.asc())
        .all()
    )
    if not open_lines:
        return {"on": label, "orders": [], "rows": []}

    by_customer: dict[int, dict] = {}
    for line, customer, city_name in open_lines:
        cid = int(customer.id)
        bucket = by_customer.get(cid)
        if bucket is None:
            bucket = {"customer": customer, "city": city_name or "", "lines": [], "touched": line.updated_at}
            by_customer[cid] = bucket
        elif line.updated_at and (bucket["touched"] is None or line.updated_at > bucket["touched"]):
            bucket["touched"] = line.updated_at
        bucket["lines"].append(line)

    customer_ids = list(by_customer)
    latest: dict[int, tuple] = {}
    placed_rows = (
        db.query(
            CustomerOrder.customer_id,
            CustomerOrder.marking,
            CustomerOrderPlacement.id,
            CustomerOrderPlacement.placed_at,
            CustomerOrderPlacement.customer_notes,
        )
        .join(CustomerOrderPlacement, CustomerOrderPlacement.customer_order_id == CustomerOrder.id)
        .filter(
            CustomerOrder.customer_id.in_(customer_ids),
            CustomerOrder.bucket == "open",
            CustomerOrder.is_open.is_(True),
            CustomerOrderPlacement.deleted_at.is_(None),
            CustomerOrderPlacement.status == "open",
        )
        .all()
    )
    for customer_id, marking, placement_id, placed_at, notes in placed_rows:
        cid = int(customer_id)
        prev = latest.get(cid)
        stamp = placed_at or datetime.min.replace(tzinfo=timezone.utc)
        if prev is None or stamp >= prev[0]:
            latest[cid] = (stamp, int(placement_id), marking, notes)

    orders = []
    flat = []
    for cid, bucket in by_customer.items():
        customer = bucket["customer"]
        placed = latest.get(cid)
        when = placed[0] if placed else bucket["touched"]
        if when is not None and when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if start is not None and (when is None or not (start <= when < end)):
            continue
        confirmed_on = _ist_day(when)
        marking = ""
        placement_id = 0
        if placed:
            placement_id = placed[1]
            marking = single_mark(placed[2], placed[3]) or ""
        item_lines = []
        for line in bucket["lines"]:
            qty = int(line.quantity_open or 0)
            if qty <= 0:
                continue
            rate = format(line.unit_price or 0, "f")
            item_lines.append({"item_no": line.our_product_id, "qty": qty, "rate": rate})
            flat.append({
                "party_number": customer.party_number,
                "party": customer.business_name,
                "city": bucket["city"],
                "confirmed_on": confirmed_on.isoformat() if confirmed_on else "",
                "marking": marking,
                "order_id": placement_id,
                "item_no": line.our_product_id,
                "qty": qty,
                "rate": rate,
            })
        if not item_lines:
            continue
        orders.append({
            "placement_id": placement_id,
            "customer_id": cid,
            "party_number": customer.party_number,
            "party": customer.business_name,
            "city": bucket["city"],
            "marking": marking,
            "confirmed_on": confirmed_on.isoformat() if confirmed_on else "",
            "placed_at": when.isoformat() if when else "",
            "lines": item_lines,
        })
    orders.sort(key=lambda row: (row["confirmed_on"], row["party"].lower()), reverse=True)
    return {"on": label, "orders": orders, "rows": flat}


def render_confirmed_orders_pdf(
    db: Session,
    on: Optional[date] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> bytes:
    data = confirmed_order_report(db, on=on, from_date=from_date, to_date=to_date)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=14 * mm
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Confirmed orders — {data['on']}", styles["Heading1"]),
        Paragraph(f"{len(data['orders'])} orders", styles["Normal"]),
        Spacer(1, 8),
    ]
    if not data["orders"]:
        story.append(Paragraph("No confirmed orders on this date.", styles["Normal"]))
    for order in data["orders"]:
        party_no = f"#{order['party_number']} " if order.get("party_number") else ""
        city = f" · {order['city']}" if order.get("city") else ""
        when = f"{order['confirmed_on']} · " if order.get("confirmed_on") else ""
        mark = f" · {order['marking']}" if order.get("marking") else ""
        story.append(Paragraph(f"{when}{party_no}{order['party']}{city}{mark}", styles["Heading3"]))
        table_rows = [["Item", "Qty", "Rate"]]
        for line in order["lines"]:
            table_rows.append([line["item_no"], str(line["qty"]), line["rate"]])
        table = Table(table_rows, colWidths=[90 * mm, 30 * mm, 40 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ]))
        story.append(table)
        story.append(Spacer(1, 8))
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return buf.getvalue()
