"""Items that are not in album 1, 2, or 3."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.stock import StockBalance, StockLedger
from app.services.biz_date import ist_range_bounds_utc
from app.services.pdf_documents import add_page_number
from app.services.reports.stock_group_summary import _INWARD_TYPES, _dated_or_created, period_label

_BLANK = ""


def _empty(column):
    return or_(column.is_(None), func.trim(column) == _BLANK)


def _num(value) -> str:
    return format(Decimal(str(value or 0)).quantize(Decimal("0.01")), "f")


def items_without_album(
    db: Session,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> dict:
    products = (
        db.query(CatalogProduct)
        .filter(
            CatalogProduct.deleted_at.is_(None),
            CatalogProduct.is_active.is_(True),
            _empty(CatalogProduct.category),
            _empty(CatalogProduct.second_category),
            _empty(CatalogProduct.category_3),
        )
        .order_by(CatalogProduct.our_product_id.asc(), CatalogProduct.id.asc())
        .all()
    )
    ids = [int(p.id) for p in products]
    stock = {}
    inward = {}
    outward = {}
    bills = {}
    last_sale = {}
    if ids:
        for pid, qty in (
            db.query(StockBalance.catalog_product_id, StockBalance.quantity_on_hand)
            .filter(StockBalance.catalog_product_id.in_(ids))
            .all()
        ):
            stock[int(pid)] = int(qty or 0)
        start, end = ist_range_bounds_utc(from_date, to_date)
        in_q = (
            db.query(StockLedger.catalog_product_id, func.sum(StockLedger.quantity_delta))
            .filter(
                StockLedger.catalog_product_id.in_(ids),
                StockLedger.entry_type.in_(_INWARD_TYPES),
                StockLedger.quantity_delta > 0,
            )
        )
        if start is not None:
            in_q = in_q.filter(StockLedger.created_at >= start)
        if end is not None:
            in_q = in_q.filter(StockLedger.created_at < end)
        for pid, qty in in_q.group_by(StockLedger.catalog_product_id).all():
            inward[int(pid)] = int(qty or 0)

        sale_q = (
            db.query(
                CustomerBillLine.catalog_product_id,
                func.sum(CustomerBillLine.quantity_shipped),
                func.count(func.distinct(CustomerBill.id)),
                func.max(CustomerBill.bill_date),
            )
            .join(CustomerBill, CustomerBill.id == CustomerBillLine.bill_id)
            .filter(
                CustomerBillLine.catalog_product_id.in_(ids),
                CustomerBill.deleted_at.is_(None),
                CustomerBill.cancelled_at.is_(None),
                CustomerBillLine.status != "cancelled",
                CustomerBillLine.quantity_shipped > 0,
            )
        )
        sale_q = sale_q.filter(
            _dated_or_created(CustomerBill.bill_date, CustomerBill.created_at, from_date, to_date)
        )
        for pid, qty, bill_count, last_day in sale_q.group_by(CustomerBillLine.catalog_product_id).all():
            outward[int(pid)] = int(qty or 0)
            bills[int(pid)] = int(bill_count or 0)
            last_sale[int(pid)] = last_day.isoformat() if last_day else ""

    rows = []
    for product in products:
        pid = int(product.id)
        on_hand = stock.get(pid, 0)
        price = Decimal(str(product.selling_price or 0)).quantize(Decimal("0.01"))
        amount = (Decimal(on_hand) * price).quantize(Decimal("0.01"))
        sold = outward.get(pid, 0)
        rows.append({
            "id": pid,
            "item": product.our_product_id,
            "stock": on_hand,
            "price": _num(price),
            "inward": inward.get(pid, 0),
            "outward": sold,
            "last_sale": last_sale.get(pid, ""),
            "total_bills": bills.get(pid, 0),
            "total_sales": sold,
            "total_amount": _num(amount),
        })
    return {
        "period": period_label(from_date, to_date),
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": to_date.isoformat() if to_date else None,
        "items": rows,
    }


def render_items_without_album_pdf(
    db: Session,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> bytes:
    data = items_without_album(db, from_date, to_date)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Items without album — {data['period']}", styles["Heading2"]),
        Paragraph(f"{len(data['items'])} items", styles["Normal"]),
        Spacer(1, 6),
    ]
    table_rows = [[
        "Item", "Stock", "Price", "Inward", "Outward", "Last sale", "Total bills", "Total sales", "Total amount",
    ]]
    for row in data["items"]:
        table_rows.append([
            row["item"],
            str(row["stock"]),
            row["price"],
            str(row["inward"]),
            str(row["outward"]),
            row["last_sale"] or "—",
            str(row["total_bills"]),
            str(row["total_sales"]),
            row["total_amount"],
        ])
    table = Table(table_rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("ALIGN", (5, 1), (5, -1), "LEFT"),
    ]))
    story.append(table)
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return buf.getvalue()
