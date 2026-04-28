"""Apply Streamlit secrets before ``db.py`` loads (``DATABASE_URL`` for Postgres)."""
from __future__ import annotations

import os

# Keys copied from ``st.secrets`` into ``os.environ`` (Streamlit Cloud has no ``.env`` file).
_SECRET_KEYS = (
    "DATABASE_URL",
    "DATABASE_SSLMODE",
    "DATABASE_CONNECT_TIMEOUT",
    "S3_ENDPOINT_URL",
    "S3_REGION",
    "S3_BUCKET",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_API_VERSION",
    "WHATSAPP_DISABLE",
    "WHATSAPP_ORDER_BOOKED_TEMPLATE_NAME",
    "WHATSAPP_SAVE_ORDER_RECEIPT_PDF",
    "WHATSAPP_SEND_ORDER_RECEIPT_PDF",
    "CUSTOMER_PORTAL_PUBLIC_URL",
    "CUSTOMER_PORTAL_URL_BUTTON_SUFFIX",
)


def apply_streamlit_db_env() -> None:
    """Set env from ``st.secrets`` (must run before ``import db`` / WhatsApp sends)."""
    try:
        import streamlit as st

        for sk in _SECRET_KEYS:
            sv = st.secrets.get(sk)
            if sv is not None and str(sv).strip() != "":
                os.environ[sk] = str(sv).strip()
    except Exception:
        pass
