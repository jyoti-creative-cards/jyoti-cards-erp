from __future__ import annotations
"""Split from app/services/reports_extended.py."""
"""Extended reports: item/party/ageing/stock/tax/books + extra ledgers."""


from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session

from app.models.accounts_payable import ApLedgerEntry
from app.models.accounts_receivable import ArLedgerEntry
from app.models.activity_log import ActivityLog
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_return import CustomerReturn, CustomerReturnLine
from app.models.debit_note import DebitNote
from app.models.expense import Expense
from app.models.freight_agent import FreightAgent, FreightLedgerEntry
from app.models.manual_loss import ManualLoss
from app.models.route import Route
from app.models.staff import Staff
from app.models.stock import StockBalance, StockLedger, StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.services.ar_ledger import batch_customer_outstanding
from app.services.reports import _customer_labels, _range_bounds, _vendor_labels, list_payments

from app.services.reports_extra.gst_purchase_register import _fmt

def ageing_ar(db: Session, as_of: Optional[date] = None) -> dict:
    """Two queries: ledger columns, then names for parties that have rows."""
    as_of = as_of or date.today()
    by_cid = _grouped_age_entries(db, ArLedgerEntry, ArLedgerEntry.customer_id, Customer)
    if not by_cid:
        return {"as_of": as_of.isoformat(), "totals": {k: "0.00" for k in ("0-30", "31-60", "61-90", "90+")}, "items": []}
    customers = _parties(db, Customer, set(by_cid))
    city_ids = {c.city_id for c in customers.values() if c.city_id}
    cities = {
        c.id: c.name
        for c in (db.query(City.id, City.name).filter(City.id.in_(city_ids)).all() if city_ids else [])
    }

    buckets = {"0-30": Decimal("0"), "31-60": Decimal("0"), "61-90": Decimal("0"), "90+": Decimal("0")}
    items = []

    def _inc(e, amt):
        return e.entry_type in ("bill", "opening_balance")

    def _dec(e, amt):
        return e.entry_type in ("payment", "credit_note")

    for cid, rows in by_cid.items():
        c = customers.get(cid)
        if not c:
            continue
        party_buckets, total = _fifo_age_buckets(rows, as_of, is_increase=_inc, is_decrease=_dec)
        if total <= 0:
            continue
        for k, v in party_buckets.items():
            buckets[k] += v
        city_name = cities.get(c.city_id) if c.city_id else None
        label = f"{c.business_name} — {city_name}" if city_name else c.business_name
        items.append(
            {
                "id": c.id,
                "label": label,
                "business_name": c.business_name,
                "person_name": c.person_name,
                "alias": c.alias,
                "phone": c.phone,
                "city_name": city_name,
                "outstanding": _fmt(total),
                "b0_30": _fmt(party_buckets["0-30"]),
                "b31_60": _fmt(party_buckets["31-60"]),
                "b61_90": _fmt(party_buckets["61-90"]),
                "b90_plus": _fmt(party_buckets["90+"]),
            }
        )
    items.sort(key=lambda x: Decimal(x["outstanding"]), reverse=True)
    return {
        "as_of": as_of.isoformat(),
        "totals": {k: _fmt(v) for k, v in buckets.items()},
        "items": items,
    }

def ageing_ap(db: Session, as_of: Optional[date] = None) -> dict:
    """Two queries: ledger columns, then names for parties that have rows."""
    as_of = as_of or date.today()
    by_vid = _grouped_age_entries(db, ApLedgerEntry, ApLedgerEntry.vendor_id, Vendor)
    if not by_vid:
        return {"as_of": as_of.isoformat(), "totals": {k: "0.00" for k in ("0-30", "31-60", "61-90", "90+")}, "items": []}
    vendors = _parties(db, Vendor, set(by_vid))
    city_ids = {v.city_id for v in vendors.values() if v.city_id}
    cities = {
        c.id: c.name
        for c in (db.query(City.id, City.name).filter(City.id.in_(city_ids)).all() if city_ids else [])
    }

    buckets = {"0-30": Decimal("0"), "31-60": Decimal("0"), "61-90": Decimal("0"), "90+": Decimal("0")}
    items = []

    def _inc(e, amt):
        return e.entry_type in ("bill", "opening_balance") or (e.entry_type == "debit_note" and amt > 0)

    def _dec(e, amt):
        return e.entry_type == "payment" or (e.entry_type == "debit_note" and amt < 0)

    for vid, rows in by_vid.items():
        v = vendors.get(vid)
        if not v:
            continue
        party_buckets, total = _fifo_age_buckets(rows, as_of, is_increase=_inc, is_decrease=_dec)
        if total <= 0:
            continue
        for k, val in party_buckets.items():
            buckets[k] += val
        city_name = cities.get(v.city_id) if v.city_id else None
        label = f"{v.business_name} — {city_name}" if city_name else v.business_name
        items.append(
            {
                "id": v.id,
                "label": label,
                "outstanding": _fmt(total),
                "b0_30": _fmt(party_buckets["0-30"]),
                "b31_60": _fmt(party_buckets["31-60"]),
                "b61_90": _fmt(party_buckets["61-90"]),
                "b90_plus": _fmt(party_buckets["90+"]),
            }
        )
    items.sort(key=lambda x: Decimal(x["outstanding"]), reverse=True)
    return {
        "as_of": as_of.isoformat(),
        "totals": {k: _fmt(v) for k, v in buckets.items()},
        "items": items,
    }

def _fifo_age_buckets(
    entries: list,
    as_of: date,
    *,
    is_increase,
    is_decrease,
) -> tuple[dict[str, Decimal], Decimal]:
    """Apply payments/credits FIFO against open increases; return party buckets + total."""
    open_parts: list[tuple[date, Decimal]] = []
    for e in entries:
        d = _entry_date(e)
        amt = Decimal(str(e.amount))
        if is_increase(e, amt):
            open_parts.append((d, abs(amt)))
        elif is_decrease(e, amt):
            left = abs(amt)
            while left > 0 and open_parts:
                od, oamt = open_parts[0]
                take = min(oamt, left)
                oamt -= take
                left -= take
                if oamt <= 0:
                    open_parts.pop(0)
                else:
                    open_parts[0] = (od, oamt)
    party_buckets = {"0-30": Decimal("0"), "31-60": Decimal("0"), "61-90": Decimal("0"), "90+": Decimal("0")}
    total = Decimal("0")
    for od, amt in open_parts:
        if amt <= 0:
            continue
        b = _age_bucket(as_of, od)
        party_buckets[b] += amt
        total += amt
    return party_buckets, total

def _grouped_age_entries(db: Session, model, party_col, party_model) -> dict[int, list]:
    """Ledger columns for active parties only. FIFO still needs each party's history."""
    rows = (
        db.query(party_col, model.entry_type, model.amount, model.value_date, model.created_at)
        .join(party_model, party_model.id == party_col)
        .filter(party_model.deleted_at.is_(None), party_model.is_active.is_(True), model.deleted_at.is_(None))
        .order_by(party_col.asc(), model.created_at.asc(), model.id.asc())
        .all()
    )
    grouped: dict[int, list] = {}
    for pid, entry_type, amount, value_date, created_at in rows:
        grouped.setdefault(int(pid), []).append(_AgeEntry(entry_type, amount, value_date, created_at))
    return grouped

def _parties(db: Session, model, party_ids: set[int]) -> dict[int, _Party]:
    if not party_ids:
        return {}
    rows = (
        db.query(model.id, model.business_name, model.person_name, model.alias, model.phone, model.city_id)
        .filter(model.id.in_(party_ids))
        .all()
    )
    return {int(r.id): _Party(r.id, r.business_name, r.person_name, r.alias, r.phone, r.city_id) for r in rows}

def _age_bucket(as_of: date, d: date) -> str:
    days = (as_of - d).days
    if days <= 30:
        return "0-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"

def _entry_date(e) -> date:
    if getattr(e, "value_date", None):
        return e.value_date
    created = getattr(e, "created_at", None)
    if created:
        return created.date() if hasattr(created, "date") else created
    return date.today()

