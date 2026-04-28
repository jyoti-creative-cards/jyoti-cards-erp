"""Login check using same SQLite + hashing as Dashboard/db.py."""
from __future__ import annotations

import re

from dash_db import get_dashboard_db


def _norm10(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    if len(d) >= 10:
        return d[-10:]
    return d


def try_login(phone: str, password: str) -> tuple[bool, str, int | None]:
    db = get_dashboard_db()
    db.init_db()
    p = _norm10(phone)
    if len(p) < 10:
        return False, "Enter a 10-digit mobile number", None
    if not (password or "").strip():
        return False, "Enter your password", None
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT id, phone, password_hash, name FROM customers"
        ).fetchall()
        for row in rows:
            if _norm10(row["phone"]) == p and db.verify_password(
                row["password_hash"], password
            ):
                return (
                    True,
                    (row["name"] or "").strip() or "Customer",
                    int(row["id"]),
                )
        n_customers = len(rows)
    msg = "Wrong mobile or password"
    if n_customers == 0:
        msg += (
            ". This app has no customer rows yet. "
            "On Streamlit Cloud the portal app uses its **own** database file unless both apps share "
            "the same path via secrets — see README (Customer portal vs ERP)."
        )
    return False, msg, None
