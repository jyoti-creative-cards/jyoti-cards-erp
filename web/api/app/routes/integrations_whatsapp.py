"""WhatsApp/Meta integration — status only; sends happen inside ``Dashboard/db.py``."""
from __future__ import annotations

import os

from fastapi import APIRouter

router = APIRouter(prefix="/integrations/whatsapp", tags=["integrations-whatsapp"])


@router.get("/status")
def whatsapp_status():
    """Whether outbound WhatsApp is disabled; same env as Streamlit."""
    disabled = (os.environ.get("WHATSAPP_DISABLE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    return {
        "whatsapp_disabled": disabled,
        "note": "Templates fire from db.insert_customer, insert_customer_order, "
        "update_customer_order (status), insert_customer_order_shipment, "
        "send_customer_order_payment_reminder_wa, document flows — "
        "when WHATSAPP_DISABLE is unset.",
        "fastapi_parity": "POST customer / customer-order / patch order "
        "calls the same Dashboard/db.py code paths as Streamlit.",
    }
