"""Confirmed orders for one IST day, with item numbers."""

from __future__ import annotations

from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.services.biz_date import ist_day_bounds_utc
from app.services.pdf_documents import add_page_number


def confirmed_order_report(db: Session, on: date) -> dict:
    start, end = ist_day_bounds_utc(on)
    logs = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.created_at >= start,
            ActivityLog.created_at < end,
            ActivityLog.entity_type == "customer_order",
            ActivityLog.action.in_(("confirm", "offline_order")),
        )
        .all()
    )
    placement_ids: set[int] = set()
    customer_ids: set[int] = set()
    for row in logs:
        if not row.entity_id:
            continue
        if row.action == "offline_order":
            placement_ids.add(int(row.entity_id))
        else:
            customer_ids.add(int(row.entity_id))
    if customer_ids:
        open_rows = (
            db.query(CustomerOrderPlacement.id)
            .join(CustomerOrder, CustomerOrder.id == CustomerOrderPlacement.customer_order_id)
            .filter(
                CustomerOrder.customer_id.in_(customer_ids),
                CustomerOrderPlacement.deleted_at.is_(None),
                CustomerOrderPlacement.status == "open",
            )
            .all()
        )
        placement_ids.update(int(row.id) for row in open_rows)
        billed_rows = (
            db.query(CustomerBill.placement_id)
            .filter(
                CustomerBill.customer_id.in_(customer_ids),
                CustomerBill.placement_id.isnot(None),
                CustomerBill.cancelled_at.is_(None),
                CustomerBill.created_at >= start,
                CustomerBill.created_at < end,
            )
            .all()
        )
        placement_ids.update(int(row.placement_id) for row in billed_rows if row.placement_id)
    placed_rows = (
        db.query(CustomerOrderPlacement.id)
        .filter(
            CustomerOrderPlacement.deleted_at.is_(None),
            CustomerOrderPlacement.status.in_(("open", "billed")),
            CustomerOrderPlacement.placed_at >= start,
            CustomerOrderPlacement.placed_at < end,
        )
        .all()
    )
    placement_ids.update(int(row.id) for row in placed_rows)
    if not placement_ids:
        return {"on": on.isoformat(), "orders": [], "rows": []}

    placements = (
        db.query(CustomerOrderPlacement, CustomerOrder, Customer)
        .join(CustomerOrder, CustomerOrder.id == CustomerOrderPlacement.customer_order_id)
        .join(Customer, Customer.id == CustomerOrder.customer_id)
        .filter(CustomerOrderPlacement.id.in_(placement_ids))
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
    for placement, _order, customer in placements:
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
            "placed_at": placement.placed_at.isoformat() if placement.placed_at else "",
            "lines": item_lines,
        })
    return {"on": on.isoformat(), "orders": orders, "rows": flat}


def render_confirmed_orders_pdf(db: Session, on: date) -> bytes:
    data = confirmed_order_report(db, on)
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
        story.append(Paragraph(f"{party_no}{order['party']} · Order #{order['placement_id']}", styles["Heading3"]))
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
