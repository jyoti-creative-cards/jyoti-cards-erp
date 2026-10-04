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

from app.services.bill_pdf_parts.common import _money

def _build_summary_rows(totals: Dict[str, Any], gst_on: bool, gst_label: str) -> list[list[str]]:
    rows: list[list[str]] = []
    sub = totals.get("subtotal_inclusive")
    if sub is not None:
        rows.append(["Subtotal", f"Rs. {_money(sub)}"])

    disc_amt = totals.get("discount_amount")
    dp = fmt_discount_pct(totals.get("discount_percent"))
    try:
        disc_n = float(disc_amt or 0)
    except (TypeError, ValueError):
        disc_n = 0.0
    if disc_n > 0:
        label = f"Discount ({dp}%)" if dp else "Discount"
        rows.append([label, f"- Rs. {_money(disc_amt)}"])

    after = totals.get("after_discount_inclusive")
    if after is not None and disc_n > 0:
        rows.append(["After discount", f"Rs. {_money(after)}"])

    if gst_on:
        rows.append(["Taxable value", f"Rs. {_money(totals.get('taxable_value'))}"])
        rows.append([f"GST ({gst_label})", f"Rs. {_money(totals.get('gst_amount'))}"])

    packaging = totals.get("packaging_charges")
    if packaging:
        try:
            if float(packaging) > 0:
                rows.append(["Packaging charges", f"Rs. {_money(packaging)}"])
        except (TypeError, ValueError):
            pass

    freight = totals.get("freight_charges")
    mode = (totals.get("transport_mode") or "").strip().lower()
    if not mode:
        mode = "bus" if freight else "self_pickup"
    if freight:
        try:
            if float(freight) > 0:
                if mode == "transport":
                    rows.append(["Transport charges", f"Rs. {_money(freight)}"])
                    receipt = (totals.get("transport_receipt_number") or "").strip()
                    if receipt:
                        rows.append(["Transport receipt", _safe(receipt, 40)])
                else:
                    rows.append(["Freight charges", f"Rs. {_money(freight)}"])
                    agent = (totals.get("freight_agent_name") or "").strip()
                    if agent:
                        rows.append(["Freight agent", _safe(agent, 40)])
        except (TypeError, ValueError):
            pass

    additional = totals.get("additional_charges")
    if isinstance(additional, list):
        for ac in additional:
            if isinstance(ac, dict) and ac.get("name") and ac.get("amount"):
                rows.append([_safe(ac["name"], 40), f"Rs. {_money(ac['amount'])}"])

    round_off = totals.get("round_off")
    if round_off and str(round_off) not in ("0.00", "0", "0.0"):
        try:
            ro = float(round_off)
            if ro != 0:
                sign = "+" if ro > 0 else ""
                rows.append(["Round off", f"{sign}Rs. {_money(round_off)}"])
        except (TypeError, ValueError):
            pass

    grand = totals.get("rounded_grand_total") or totals.get("grand_total")
    rows.append(["Grand Total", f"Rs. {_money(grand)}"])
    return rows

