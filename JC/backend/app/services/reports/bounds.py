from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from app.models.accounts_payable import ApLedgerEntry
from app.models.accounts_receivable import ArLedgerEntry
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.expense import Expense
from app.models.freight_agent import FreightLedgerEntry
from app.models.stock import StockBalance, StockLedger, StockReceipt
from app.models.catalog_product import CatalogProduct
from app.models.vendor import Vendor
from app.models.city import City
from app.services.biz_date import ist_day_bounds_utc, ist_range_bounds_utc

def _day_bounds(d: date) -> tuple[datetime, datetime]:
    """IST calendar day → UTC bounds (aligns with plain-Date columns like expense_date)."""
    return ist_day_bounds_utc(d)

def _range_bounds(from_date: Optional[date], to_date: Optional[date]) -> tuple[Optional[datetime], Optional[datetime]]:
    return ist_range_bounds_utc(from_date, to_date)

def _payment_on_ist_day(model, day: date):
    return _payment_in_range(model, day, day)

def _payment_in_range(model, from_date: Optional[date], to_date: Optional[date]):
    """Value date wins. Rows with no value date fall back to created_at in the IST range."""
    if from_date is None and to_date is None:
        return True
    start, end = _range_bounds(from_date, to_date)
    value_parts = []
    if from_date is not None:
        value_parts.append(model.value_date >= from_date)
    if to_date is not None:
        value_parts.append(model.value_date <= to_date)
    created_parts = [model.value_date.is_(None)]
    if start is not None:
        created_parts.append(model.created_at >= start)
    if end is not None:
        created_parts.append(model.created_at <= end)
    return or_(and_(*value_parts), and_(*created_parts))

def _payment_in_ist_range(model, from_date: Optional[date], to_date: Optional[date]):
    start, end = _range_bounds(from_date, to_date)
    created_clause = True
    if start is not None:
        created_clause = and_(created_clause, model.created_at >= start)
    if end is not None:
        created_clause = and_(created_clause, model.created_at <= end)
    value_clause = True
    if from_date is not None:
        value_clause = and_(value_clause, model.value_date >= from_date)
    if to_date is not None:
        value_clause = and_(value_clause, model.value_date <= to_date)
    if from_date is None and to_date is None:
        return True
    return or_(
        and_(model.value_date.isnot(None), value_clause),
        and_(model.value_date.is_(None), created_clause),
    )

def _batch_labels(db: Session, model, ids: set[int]) -> dict[int, "object"]:
    if not ids:
        return {}
    return {row.id: row for row in db.query(model).filter(model.id.in_(ids)).all()}

def _vendor_labels(db: Session, vendor_ids: set[int]) -> dict[int, str]:
    if not vendor_ids:
        return {}
    vendors = {v.id: v for v in db.query(Vendor).filter(Vendor.id.in_(vendor_ids)).all()}
    city_ids = {v.city_id for v in vendors.values() if v.city_id}
    cities = {c.id: c.name for c in db.query(City).filter(City.id.in_(city_ids)).all()} if city_ids else {}
    out = {}
    for vid in vendor_ids:
        v = vendors.get(vid)
        if not v:
            out[vid] = f"Vendor #{vid}"
            continue
        city_name = cities.get(v.city_id) if v.city_id else None
        out[vid] = f"{v.business_name} — {city_name}" if city_name else v.business_name
    return out

def _customer_labels(db: Session, customer_ids: set[int]) -> dict[int, str]:
    if not customer_ids:
        return {}
    customers = {c.id: c for c in db.query(Customer).filter(Customer.id.in_(customer_ids)).all()}
    city_ids = {c.city_id for c in customers.values() if c.city_id}
    cities = {c.id: c.name for c in db.query(City).filter(City.id.in_(city_ids)).all()} if city_ids else {}
    out = {}
    for cid in customer_ids:
        c = customers.get(cid)
        if not c:
            out[cid] = f"Customer #{cid}"
            continue
        city_name = cities.get(c.city_id) if c.city_id else None
        out[cid] = f"{c.business_name} — {city_name}" if city_name else c.business_name
    return out
