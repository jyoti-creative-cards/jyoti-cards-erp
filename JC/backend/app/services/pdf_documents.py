"""Implementation lives in app.services.pdf_parts."""
from app.services.pdf_parts.actions import _party_block_single
from app.services.pdf_parts.common import _code_pair, _fetch_image, _header, _ist_fmt, _safe, add_page_number
from app.services.pdf_parts.render_customer_return_pdf import render_customer_return_pdf, _totals_block, _items_table, _vendor_order_table
from app.services.pdf_parts.render_vendor_receipt_pdf import render_vendor_receipt_pdf, render_customer_order_pdf, _party_blocks, _vendor_receipt_table, render_vendor_placement_pdf

__all__ = [
    "_code_pair",
    "_fetch_image",
    "_header",
    "_ist_fmt",
    "_items_table",
    "_party_block_single",
    "_party_blocks",
    "_safe",
    "_totals_block",
    "_vendor_order_table",
    "_vendor_receipt_table",
    "add_page_number",
    "render_customer_order_pdf",
    "render_customer_return_pdf",
    "render_vendor_placement_pdf",
    "render_vendor_receipt_pdf",
]
