"""Apply Streamlit secrets before `db.py` loads so ERP and portal can share one DB path."""
from __future__ import annotations

import os


def apply_streamlit_db_env() -> None:
    """Set ``DASHBOARD_E2E_DB`` from ``st.secrets`` (must run before ``import db``)."""
    try:
        import streamlit as st

        v = st.secrets.get("DASHBOARD_E2E_DB") or st.secrets.get("BUSINESS_DB_PATH")
        if v:
            os.environ["DASHBOARD_E2E_DB"] = str(v).strip()
    except Exception:
        pass
