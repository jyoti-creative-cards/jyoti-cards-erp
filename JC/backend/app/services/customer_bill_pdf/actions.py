from __future__ import annotations
"""Split from app/services/customer_bill_pdf.py."""
"""Customer bill PDF in the Tally invoice layout.

One bordered goods table (Sl, Description, Sl, Quantity, Rate, per, Disc. %, Amount).
Transport, packing, and a bill-level cash discount sit inside that table.
Item photos sit under the total, on the last page only. A long list continues
onto the next page with the same header and "continued ...".
"""

import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from math import ceil
from typing import Any, Dict, List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.services.biz_date import to_ist
from app.services.company_info import COMPANY_NAME
from app.services.customer_bill_math import fmt_discount_pct
from app.services.pdf_documents import _safe

PAGE_W, PAGE_H = A4  # 595 x 841

# Column edges measured from the sample invoices.
COLS = [33.0, 47.0, 250.0, 276.0, 333.0, 390.0, 415.0, 453.0, 537.0]
LEFT = COLS[0]
RIGHT = COLS[-1]

# Closing page: table border ends just above "Amount Chargeable".
BOX_BOTTOM = 603.0
# Continued page: border runs down to the "continued" line.
BOX_BOTTOM_CONT = 753.0

HEAD_H = 26.0
ROW_H = 12.0
CHARGE_H = 13.0
TOTAL_H = 16.0

COPY_LABELS = ["ORIGINAL", "DUPLICATE", "TRIPLICATE", "QUADRUPLICATE"]

DECLARATION = (
    "We declare that this invoice shows the actual price of the goods "
    "described and that all particulars are true and correct. "
    "300 PCS QUANTITY TAK PACKING CHARGE NHI LAGEGA USKE UPAR CHARGES APPLICABLE HAI."
)

_BELOW_20 = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
    "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
    "Eighteen", "Nineteen",
]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def bill_item_headers(gst_on: bool, gst_label: str = "") -> list[str]:
    # Same columns on a GST bill and a non-GST bill. Tax stays inside the line amount.
    del gst_on, gst_label
    return ["Sl No.", "Description of Goods", "Sl No.", "Quantity", "Rate", "per", "Disc. %", "Amount"]

