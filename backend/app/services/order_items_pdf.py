"""Build a simple PDF with all order item images — for order_confirmation WA template."""
from __future__ import annotations

import urllib.request
from io import BytesIO
from typing import Any, Dict, List

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer
from reportlab.lib.styles import getSampleStyleSheet


def build_order_items_pdf(
    items: List[Dict[str, Any]],
    image_urls: Dict[int, str],
    order_id: int,
    customer_name: str,
) -> bytes:
    """Return PDF bytes with one image+name block per order item."""
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=1.5*cm, bottomMargin=1.5*cm,
                            leftMargin=1.5*cm, rightMargin=1.5*cm)
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    normal_style = styles["Normal"]

    story = []
    story.append(Paragraph(f"Order #{order_id} — {customer_name}", title_style))
    story.append(Spacer(1, 0.5*cm))

    for item in items:
        if not isinstance(item, dict):
            continue
        cid = int(item.get("catalog_product_id", 0))
        name = str(item.get("name") or item.get("our_product_id") or "")
        qty = item.get("quantity", 1)
        price = item.get("unit_price", "")

        img_url = image_urls.get(cid)
        if img_url:
            try:
                with urllib.request.urlopen(img_url, timeout=10) as r:
                    img_data = r.read()
                img = Image(BytesIO(img_data), width=8*cm, height=8*cm)
                img.hAlign = "LEFT"
                story.append(img)
            except Exception as e:
                print(f"order_items_pdf: could not fetch image for {cid}: {e}")

        label = f"<b>{name}</b>  ×{qty}"
        if price:
            label += f"  @ ₹{price}"
        story.append(Paragraph(label, normal_style))
        story.append(Spacer(1, 0.5*cm))

    doc.build(story)
    return buf.getvalue()
