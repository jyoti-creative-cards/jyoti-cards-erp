"""Confirmed orders for one IST day, with item numbers."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.models.city import City
from app.models.customer import Customer
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.services.biz_date import ist_day_bounds_utc
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


def confirmed_order_report(
    db: Session,
    on: Optional[date] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> dict:
    start, end = _report_bounds(on, from_date, to_date)
    label = "all" if start is None else (on.isoformat() if on else f"{(from_date or to_date).isoformat()} to {(to_date or from_date).isoformat()}")
    placed = db.query(CustomerOrderPlacement.id).filter(
        CustomerOrderPlacement.deleted_at.is_(None),
        CustomerOrderPlacement.status.in_(("open", "billed")),
    )
    if start is not None:
        placed = placed.filter(CustomerOrderPlacement.placed_at >= start, CustomerOrderPlacement.placed_at < end)
    placement_ids = {int(row.id) for row in placed.all()}
    if not placement_ids:
        return {"on": label, "orders": [], "rows": []}

    placements = (
        db.query(CustomerOrderPlacement, CustomerOrder, Customer, City.name)
        .join(CustomerOrder, CustomerOrder.id == CustomerOrderPlacement.customer_order_id)
        .join(Customer, Customer.id == CustomerOrder.customer_id)
        .outerjoin(City, City.id == Customer.city_id)
        .filter(CustomerOrderPlacement.id.in_(placement_ids), Customer.deleted_at.is_(None))
        .order_by(Customer.business_name.asc(), CustomerOrderPlacement.id.asc())
        .all()
    )
    lines = (
        db.query(CustomerOrderLine)
        .filter(
            CustomerOrderLine.placement_id.in_(placement_ids),
            CustomerOrderLine.status == "active",
        )
        .order_by(CustomerOrderLine.id.asc())
        .all()
    )
    by_placement: dict[int, list] = {}
    for line in lines:
        by_placement.setdefault(int(line.placement_id), []).append(line)

    orders = []
    flat = []
    for placement, order, customer, city_name in placements:
        item_lines = []
        for line in by_placement.get(int(placement.id), []):
            qty = int(line.quantity or 0)
            if qty <= 0:
                continue
            rate = format(line.unit_price or 0, "f")
            item_lines.append({
                "item_no": line.our_product_id,
                "qty": qty,
                "rate": rate,
            })
            flat.append({
                "party_number": customer.party_number,
                "party": customer.business_name,
                "city": city_name or "",
                "marking": (order.marking or placement.customer_notes or "") or "",
                "order_id": int(placement.id),
                "item_no": line.our_product_id,
                "qty": qty,
                "rate": rate,
            })
        if not item_lines:
            continue
        orders.append({
            "placement_id": int(placement.id),
            "customer_id": int(customer.id),
            "party_number": customer.party_number,
            "party": customer.business_name,
            "city": city_name or "",
            "marking": (order.marking or placement.customer_notes or "") or "",
            "placed_at": placement.placed_at.isoformat() if placement.placed_at else "",
            "lines": item_lines,
        })
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
        mark = f" · {order['marking']}" if order.get("marking") else ""
        story.append(Paragraph(f"{party_no}{order['party']}{city}{mark} · Order #{order['placement_id']}", styles["Heading3"]))
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
