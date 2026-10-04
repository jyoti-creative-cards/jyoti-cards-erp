from __future__ import annotations
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy.orm import Session
from app.models.accounts_receivable import ArLedgerEntry, CustomerArAccount
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.city import City
from app.services.money import as_signed_decrease, as_signed_increase, mag

def _doc_status(row) -> str:
    if row is None:
        return "open"
    if getattr(row, "deleted_at", None):
        return "voided"
    if getattr(row, "cancelled_at", None) or getattr(row, "status", None) == "cancelled":
        return "cancelled"
    return "open"

def _customer_label(db: Session, customer_id: int) -> str:
    c = db.get(Customer, customer_id)
    if not c:
        return f"Customer #{customer_id}"
    city_name = None
    if c.city_id:
        city = db.get(City, c.city_id)
        city_name = city.name if city else None
    return f"{c.business_name} — {city_name}" if city_name else c.business_name
