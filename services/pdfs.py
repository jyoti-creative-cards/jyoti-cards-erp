from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def build_sales_order_pdf(order):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 20 * mm
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(20 * mm, y, f"Jyoti Cards ERP - Order Receipt SO#{order.id}")
    y -= 10 * mm

    pdf.setFont("Helvetica", 11)
    pdf.drawString(20 * mm, y, f"Customer: {order.customer.name}")
    y -= 7 * mm
    pdf.drawString(20 * mm, y, f"Date: {order.order_date}")
    y -= 7 * mm
    pdf.drawString(20 * mm, y, f"Status: {order.status.value}")
    y -= 10 * mm

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(20 * mm, y, "Product")
    pdf.drawString(95 * mm, y, "Qty")
    pdf.drawString(120 * mm, y, "Price")
    pdf.drawString(155 * mm, y, "Total")
    y -= 6 * mm

    pdf.setFont("Helvetica", 10)
    for item in order.items:
        pdf.drawString(20 * mm, y, item.product.name[:38])
        pdf.drawString(95 * mm, y, str(item.quantity))
        pdf.drawString(120 * mm, y, f"{item.unit_price:,.2f}")
        pdf.drawString(155 * mm, y, f"{item.total_price:,.2f}")
        y -= 6 * mm
        if y < 25 * mm:
            pdf.showPage()
            y = height - 20 * mm

    y -= 8 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(20 * mm, y, f"Subtotal: {order.subtotal_amount:,.2f}")
    y -= 7 * mm
    pdf.drawString(20 * mm, y, f"Discount: {order.discount_amount:,.2f}")
    y -= 7 * mm
    pdf.drawString(20 * mm, y, f"Final Total: {order.total_amount:,.2f}")

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()
