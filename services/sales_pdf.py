"""Generate sales order PDF receipts with product images."""

import os
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER

from config import APP_NAME


PDF_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "sales_orders")
os.makedirs(PDF_DIR, exist_ok=True)

THUMB_W = 18 * mm
THUMB_H = 18 * mm


def _product_image(item):
    product = item.product if item.product else None
    if not product:
        return "—"
    img_path = getattr(product, "image_path", None)
    if img_path and os.path.isfile(img_path):
        try:
            return Image(img_path, width=THUMB_W, height=THUMB_H, kind="proportional")
        except Exception:
            return "—"
    return "—"


def generate_sales_order_pdf(order) -> str:
    filename = f"SO_{order.id}.pdf"
    filepath = os.path.join(PDF_DIR, filename)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Heading1"], fontSize=16, alignment=TA_CENTER, spaceAfter=2 * mm)
    sub_style = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9, alignment=TA_CENTER, textColor=colors.grey)
    heading = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11, spaceBefore=4 * mm, spaceAfter=2 * mm)
    normal = styles["Normal"]
    cell_style = ParagraphStyle("cell", parent=normal, fontSize=8)

    customer = order.customer
    customer_name = customer.name if customer else "Customer"
    customer_phone = (customer.whatsapp_phone or customer.phone) if customer else ""

    elements = [
        Paragraph(APP_NAME, title_style),
        Paragraph(f"Sales Order #{order.id}", sub_style),
        Spacer(1, 4 * mm),
        Paragraph("Customer Details", heading),
        Paragraph(f"<b>Name:</b> {customer_name}", normal),
        Paragraph(f"<b>Phone:</b> {customer_phone or '—'}", normal),
        Paragraph(f"<b>Status:</b> {order.status.value if hasattr(order.status, 'value') else order.status}", normal),
        Paragraph(f"<b>Order Date:</b> {order.order_date}", normal),
        Spacer(1, 4 * mm),
        Paragraph("Order Items", heading),
    ]

    has_images = any(_product_image(item) != "—" for item in order.items)
    if has_images:
        header = ["#", "Image", "SKU", "Item", "Qty", "Rate", "Amount"]
        widths = [8 * mm, 20 * mm, 22 * mm, 58 * mm, 12 * mm, 20 * mm, 24 * mm]
    else:
        header = ["#", "SKU", "Item", "Qty", "Rate", "Amount"]
        widths = [8 * mm, 24 * mm, 82 * mm, 14 * mm, 24 * mm, 24 * mm]

    rows = [header]
    for idx, item in enumerate(order.items, 1):
        sku = item.product.sku if item.product else "—"
        name = item.product.name if item.product else "—"
        qty = f"{item.quantity:g}"
        rate = f"{item.unit_price:,.2f}"
        amt = f"{item.total_price:,.2f}"
        if has_images:
            rows.append([str(idx), _product_image(item), sku, Paragraph(name, cell_style), qty, rate, amt])
        else:
            rows.append([str(idx), sku, name, qty, rate, amt])

    if has_images:
        rows.append(["", "", "", "", "", Paragraph("<b>Total</b>", cell_style), f"{order.total_amount:,.2f}"])
    else:
        rows.append(["", "", "", "", Paragraph("<b>Total</b>", cell_style), f"{order.total_amount:,.2f}"])

    table = Table(rows, colWidths=widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1f2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -2), 0.5, colors.HexColor("#e2e6ef")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8f9fc")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
    ]
    qty_col_start = 4 if has_images else 3
    style_cmds.append(("ALIGN", (qty_col_start, 0), (-1, -1), "RIGHT"))
    table.setStyle(TableStyle(style_cmds))
    elements.append(table)
    elements.append(Spacer(1, 4 * mm))
    elements.append(Paragraph("Thank you for ordering with Jyoti Cards.", normal))

    doc.build(elements)
    with open(filepath, "wb") as f:
        f.write(buf.getvalue())
    return filepath
