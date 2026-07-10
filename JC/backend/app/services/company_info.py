"""Our company details for printed documents."""
from __future__ import annotations

import os

COMPANY_NAME = os.environ.get("COMPANY_NAME", "JYOTI CREATIVE CARDS")
COMPANY_ADDRESS = os.environ.get("COMPANY_ADDRESS", "")
COMPANY_PHONE = os.environ.get("COMPANY_PHONE", "")
COMPANY_GST = os.environ.get("COMPANY_GST", "")


def company_lines() -> list[str]:
    lines = [COMPANY_NAME]
    if COMPANY_ADDRESS:
        lines.append(COMPANY_ADDRESS)
    if COMPANY_PHONE:
        lines.append(f"Phone: {COMPANY_PHONE}")
    if COMPANY_GST:
        lines.append(f"GSTIN: {COMPANY_GST}")
    return lines
