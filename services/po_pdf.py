"""Generate a professional PO PDF with vendor item codes and product images."""

import os
from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

from config import APP_NAME

PDF_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "pos")
os.makedirs(PDF_DIR, exist_ok=True)

THUMB_W = 18 * mm
THUMB_H = 18 * mm


def _product_image(item):
    """Return a reportlab Image for the product thumbnail, or '—' if none."""
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


def generate_po_pdf(po) -> str:
    """Build PDF for a PurchaseOrder and return the file path."""
    filename = f"PO_{po.id}_v{po.version_number}.pdf"
    filepath = os.path.join(PDF_DIR, filename)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("po_title", parent=styles["Heading1"], fontSize=16, alignment=TA_CENTER, spaceAfter=2 * mm)
    subtitle_style = ParagraphStyle("po_sub", parent=styles["Normal"], fontSize=9, alignment=TA_CENTER, textColor=colors.grey)
    heading = ParagraphStyle("po_h2", parent=styles["Heading2"], fontSize=11, spaceBefore=4 * mm, spaceAfter=2 * mm)
    normal = styles["Normal"]
    small = ParagraphStyle("small", parent=normal, fontSize=8, textColor=colors.grey)
    bold_right = ParagraphStyle("bold_right", parent=normal, fontSize=10, alignment=TA_RIGHT, fontName="Helvetica-Bold")
    cell_style = ParagraphStyle("cell", parent=normal, fontSize=8)

    elements = []

    # ── header ────────────────────────────────────────────────────────────────
    elements.append(Paragraph(APP_NAME, title_style))
    elements.append(Paragraph(f"Purchase Order #{po.id} &nbsp; v{po.version_number}", subtitle_style))
    elements.append(Spacer(1, 4 * mm))

    # ── vendor + dates ────────────────────────────────────────────────────────
    vendor = po.vendor
    vendor_name = vendor.firm_name or vendor.name
    vendor_owner = vendor.owner_name or ""
    vendor_phone = vendor.phone or ""
    vendor_addr = vendor.address or ""
    vendor_gst = vendor.gst_number or ""

    info_data = [
        [Paragraph("<b>To:</b>", normal), Paragraph(f"<b>{vendor_name}</b>", normal),
         Paragraph("<b>Order Date:</b>", normal), Paragraph(str(po.order_date or date.today()), normal)],
        [Paragraph("", normal), Paragraph(vendor_owner, small),
         Paragraph("<b>Expected:</b>", normal), Paragraph(str(po.expected_date or "—"), normal)],
        [Paragraph("", normal), Paragraph(vendor_phone, small),
         Paragraph("<b>Committed:</b>", normal), Paragraph(str(po.vendor_committed_date or "—"), normal)],
        [Paragraph("", normal), Paragraph(vendor_addr, small),
         Paragraph("<b>Shipment:</b>", normal), Paragraph(po.shipment_mode or "—", normal)],
    ]
    if vendor_gst:
        info_data.append([Paragraph("", normal), Paragraph(f"GST: {vendor_gst}", small), Paragraph("", normal), Paragraph("", normal)])

    info_table = Table(info_data, colWidths=[12 * mm, 75 * mm, 30 * mm, 55 * mm])
    info_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 4 * mm))

    # ── items table (vendor codes + product images) ───────────────────────────
    elements.append(Paragraph("Order Items", heading))

    has_images = any(_product_image(item) != "—" for item in po.items)

    if has_images:
        header_row = ["#", "Image", "Vendor Code", "Description", "Qty", "Rate", "Bill %", "PO Rate", "Amount"]
        col_widths = [7 * mm, 20 * mm, 20 * mm, 40 * mm, 13 * mm, 18 * mm, 13 * mm, 18 * mm, 22 * mm]
    else:
        header_row = ["#", "Vendor Code", "Description", "Qty", "Rate", "Bill %", "PO Rate", "Amount"]
        col_widths = [8 * mm, 25 * mm, 55 * mm, 15 * mm, 20 * mm, 15 * mm, 20 * mm, 22 * mm]

    table_data = [header_row]

    for idx, item in enumerate(po.items, 1):
        vendor_code = item.vendor_product_code or "—"
        item_name = item.product.name if item.product else "—"
        qty = f"{item.quantity_ordered:g}"
        base = f"{item.base_unit_price:,.2f}"
        bill_pct = f"{item.billing_percent:g}%"
        po_rate = f"{item.unit_price:,.2f}"
        total = f"{item.total_price:,.2f}"

        if has_images:
            img = _product_image(item)
            table_data.append([str(idx), img, vendor_code, Paragraph(item_name, cell_style), qty, base, bill_pct, po_rate, total])
        else:
            table_data.append([str(idx), vendor_code, item_name, qty, base, bill_pct, po_rate, total])

    # total row
    if has_images:
        table_data.append(["", "", "", "", "", "", "", Paragraph("<b>Total</b>", bold_right), f"{po.final_amount:,.2f}"])
    else:
        table_data.append(["", "", "", "", "", "", Paragraph("<b>Total</b>", bold_right), f"{po.final_amount:,.2f}"])

    items_table = Table(table_data, colWidths=col_widths, repeatRows=1)

    align_start_col = 4 if has_images else 3
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1f2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (align_start_col, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -2), 0.5, colors.HexColor("#e2e6ef")),
        ("LINEBELOW", (0, -1), (-1, -1), 1, colors.HexColor("#1a1f2e")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8f9fc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    items_table.setStyle(TableStyle(style_cmds))
    elements.append(items_table)
    elements.append(Spacer(1, 4 * mm))

    # ── product images gallery (larger, below table) ──────────────────────────
    image_items = [(item, item.product) for item in po.items
                   if item.product and getattr(item.product, "image_path", None)
                   and os.path.isfile(item.product.image_path)]

    if image_items:
        elements.append(Paragraph("Product Reference Images", heading))
        gallery_data = []
        gallery_row = []
        for item, product in image_items:
            try:
                img = Image(product.image_path, width=40 * mm, height=40 * mm, kind="proportional")
                label = Paragraph(f"<b>{item.vendor_product_code or product.sku}</b><br/>{product.name}", cell_style)
                cell = Table([[img], [label]], colWidths=[42 * mm])
                cell.setStyle(TableStyle([
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                ]))
                gallery_row.append(cell)
            except Exception:
                continue
            if len(gallery_row) == 4:
                gallery_data.append(gallery_row)
                gallery_row = []
        if gallery_row:
            while len(gallery_row) < 4:
                gallery_row.append("")
            gallery_data.append(gallery_row)

        if gallery_data:
            gallery_table = Table(gallery_data, colWidths=[44 * mm] * 4)
            gallery_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            elements.append(gallery_table)
        elements.append(Spacer(1, 4 * mm))

    # ── notes ─────────────────────────────────────────────────────────────────
    if po.notes:
        elements.append(Paragraph("Notes", heading))
        elements.append(Paragraph(po.notes.replace("\n", "<br/>"), normal))
        elements.append(Spacer(1, 3 * mm))

    # ── transport ─────────────────────────────────────────────────────────────
    if po.transport_name or po.transport_contact:
        elements.append(Paragraph("Transport", heading))
        transport_info = f"{po.transport_name or '—'} &nbsp;|&nbsp; {po.transport_contact or '—'}"
        elements.append(Paragraph(transport_info, normal))
        elements.append(Spacer(1, 3 * mm))

    # ── billing condition ─────────────────────────────────────────────────────
    billing = vendor.billing_condition or "100%"
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(f"Billing Condition: {billing}", small))
    elements.append(Paragraph(f"Generated by {APP_NAME}", small))

    doc.build(elements)

    with open(filepath, "wb") as f:
        f.write(buf.getvalue())

    return filepath
