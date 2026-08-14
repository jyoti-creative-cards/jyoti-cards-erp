"""Extended reports: item/party/ageing/stock/tax/books + extra ledgers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
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
from app.models.stock import StockBalance, StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.services.ap_ledger import _vendor_label, vendor_ap_totals
from app.services.ar_ledger import _customer_label, customer_ar_totals
from app.services.reports import _range_bounds, list_payments


def _fmt(v: Decimal | int | float | None) -> str:
    if v is None:
        return "0.00"
    return format(Decimal(str(v)).quantize(Decimal("0.01")), "f")


def _entry_date(e) -> date:
    if getattr(e, "value_date", None):
        return e.value_date
    created = getattr(e, "created_at", None)
    if created:
        return created.date() if hasattr(created, "date") else created
    return date.today()


def item_wise_sales(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    q = (
        db.query(CustomerBillLine, CustomerBill)
        .join(CustomerBill, CustomerBill.id == CustomerBillLine.bill_id)
        .filter(CustomerBillLine.status == "billed")
    )
    if start:
        q = q.filter(CustomerBill.created_at >= start)
    if end:
        q = q.filter(CustomerBill.created_at <= end)
    agg: dict[int, dict] = {}
    for ln, bill in q.all():
        row = agg.setdefault(
            ln.catalog_product_id,
            {
                "catalog_product_id": ln.catalog_product_id,
                "our_product_id": ln.our_product_id,
                "qty": 0,
                "value": Decimal("0"),
                "bill_count": set(),
                "customer_ids": set(),
            },
        )
        row["qty"] += int(ln.quantity_shipped or 0)
        row["value"] += Decimal(str(ln.line_total or 0))
        row["bill_count"].add(bill.id)
        row["customer_ids"].add(bill.customer_id)
        row["our_product_id"] = ln.our_product_id
    out = []
    for r in agg.values():
        out.append(
            {
                "catalog_product_id": r["catalog_product_id"],
                "label": r["our_product_id"],
                "qty": r["qty"],
                "value": _fmt(r["value"]),
                "bill_count": len(r["bill_count"]),
                "customer_count": len(r["customer_ids"]),
            }
        )
    out.sort(key=lambda x: Decimal(x["value"]), reverse=True)
    return out


def item_wise_purchases(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    q = (
        db.query(StockReceiptLine, StockReceipt)
        .join(StockReceipt, StockReceipt.id == StockReceiptLine.receipt_id)
        .filter(StockReceiptLine.quantity_billed > 0)
    )
    if start:
        q = q.filter(StockReceipt.created_at >= start)
    if end:
        q = q.filter(StockReceipt.created_at <= end)
    agg: dict[int, dict] = {}
    for ln, receipt in q.all():
        qty = int(ln.quantity_billed or 0)
        if qty <= 0:
            continue
        value = Decimal(str(ln.billed_amount or 0))
        if value == 0 and ln.buying_price is not None:
            value = Decimal(str(ln.buying_price)) * qty
        row = agg.setdefault(
            ln.catalog_product_id,
            {
                "catalog_product_id": ln.catalog_product_id,
                "our_product_id": ln.our_product_id,
                "qty": 0,
                "value": Decimal("0"),
                "receipt_count": set(),
                "vendor_ids": set(),
            },
        )
        row["qty"] += qty
        row["value"] += value
        row["receipt_count"].add(receipt.id)
        row["vendor_ids"].add(receipt.vendor_id)
        row["our_product_id"] = ln.our_product_id
    out = []
    for r in agg.values():
        out.append(
            {
                "catalog_product_id": r["catalog_product_id"],
                "label": r["our_product_id"],
                "qty": r["qty"],
                "value": _fmt(r["value"]),
                "receipt_count": len(r["receipt_count"]),
                "vendor_count": len(r["vendor_ids"]),
            }
        )
    out.sort(key=lambda x: Decimal(x["value"]), reverse=True)
    return out


def customer_wise_sales(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    q = db.query(CustomerBill)
    if start:
        q = q.filter(CustomerBill.created_at >= start)
    if end:
        q = q.filter(CustomerBill.created_at <= end)
    agg: dict[int, dict] = {}
    for b in q.all():
        row = agg.setdefault(
            b.customer_id,
            {"customer_id": b.customer_id, "bill_count": 0, "value": Decimal("0")},
        )
        row["bill_count"] += 1
        row["value"] += Decimal(str(b.grand_total or 0))
    out = []
    for cid, r in agg.items():
        totals = customer_ar_totals(db, cid)
        out.append(
            {
                "id": cid,
                "label": _customer_label(db, cid),
                "bill_count": r["bill_count"],
                "value": _fmt(r["value"]),
                "outstanding": _fmt(totals["outstanding"]),
            }
        )
    out.sort(key=lambda x: Decimal(x["value"]), reverse=True)
    return out


def vendor_wise_purchases(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    q = db.query(ApLedgerEntry).filter(ApLedgerEntry.entry_type == "bill")
    if start:
        q = q.filter(ApLedgerEntry.created_at >= start)
    if end:
        q = q.filter(ApLedgerEntry.created_at <= end)
    agg: dict[int, dict] = {}
    for e in q.all():
        row = agg.setdefault(
            e.vendor_id,
            {"vendor_id": e.vendor_id, "bill_count": 0, "value": Decimal("0")},
        )
        row["bill_count"] += 1
        row["value"] += Decimal(str(e.amount or 0))
    out = []
    for vid, r in agg.items():
        totals = vendor_ap_totals(db, vid)
        out.append(
            {
                "id": vid,
                "label": _vendor_label(db, vid),
                "bill_count": r["bill_count"],
                "value": _fmt(r["value"]),
                "outstanding": _fmt(totals["outstanding"]),
            }
        )
    out.sort(key=lambda x: Decimal(x["value"]), reverse=True)
    return out


def _age_bucket(as_of: date, d: date) -> str:
    days = (as_of - d).days
    if days <= 30:
        return "0-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"


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


def ageing_ar(db: Session, as_of: Optional[date] = None) -> dict:
    """Bulk-load AR ledger once — no per-customer queries."""
    as_of = as_of or date.today()
    customers = {
        c.id: c
        for c in db.query(Customer).filter(Customer.deleted_at.is_(None), Customer.is_active.is_(True)).all()
    }
    if not customers:
        return {"as_of": as_of.isoformat(), "totals": {k: "0.00" for k in ("0-30", "31-60", "61-90", "90+")}, "items": []}
    city_ids = {c.city_id for c in customers.values() if c.city_id}
    cities = {
        c.id: c.name
        for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
    }
    entries = (
        db.query(ArLedgerEntry)
        .filter(ArLedgerEntry.customer_id.in_(list(customers.keys())))
        .order_by(ArLedgerEntry.customer_id.asc(), ArLedgerEntry.created_at.asc(), ArLedgerEntry.id.asc())
        .all()
    )
    by_cid: dict[int, list] = {}
    for e in entries:
        by_cid.setdefault(e.customer_id, []).append(e)

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
    """Bulk-load AP ledger once — no per-vendor queries."""
    as_of = as_of or date.today()
    vendors = {
        v.id: v
        for v in db.query(Vendor).filter(Vendor.deleted_at.is_(None), Vendor.is_active.is_(True)).all()
    }
    if not vendors:
        return {"as_of": as_of.isoformat(), "totals": {k: "0.00" for k in ("0-30", "31-60", "61-90", "90+")}, "items": []}
    city_ids = {v.city_id for v in vendors.values() if v.city_id}
    cities = {
        c.id: c.name
        for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
    }
    entries = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.vendor_id.in_(list(vendors.keys())))
        .order_by(ApLedgerEntry.vendor_id.asc(), ApLedgerEntry.created_at.asc(), ApLedgerEntry.id.asc())
        .all()
    )
    by_vid: dict[int, list] = {}
    for e in entries:
        by_vid.setdefault(e.vendor_id, []).append(e)

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


def stock_valuation(db: Session) -> dict:
    rows = (
        db.query(CatalogProduct, StockBalance)
        .outerjoin(StockBalance, StockBalance.catalog_product_id == CatalogProduct.id)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
        .order_by(CatalogProduct.our_product_id.asc())
        .all()
    )
    items = []
    total_buy = Decimal("0")
    total_sell = Decimal("0")
    for p, bal in rows:
        qty = int(bal.quantity_on_hand) if bal else 0
        if qty == 0:
            continue
        buy = Decimal(str(p.buying_price or 0))
        sell = Decimal(str(p.selling_price)) if p.selling_price is not None else None
        buy_val = buy * qty
        sell_val = (sell * qty) if sell is not None else None
        total_buy += buy_val
        if sell_val is not None:
            total_sell += sell_val
        items.append(
            {
                "id": p.id,
                "label": p.our_product_id,
                "qty": qty,
                "buying_price": _fmt(buy),
                "selling_price": _fmt(sell) if sell is not None else None,
                "buy_value": _fmt(buy_val),
                "sell_value": _fmt(sell_val) if sell_val is not None else None,
            }
        )
    return {
        "items": items,
        "totals": {"buy_value": _fmt(total_buy), "sell_value": _fmt(total_sell), "sku_count": len(items)},
    }


def stock_movers(db: Session, from_date: Optional[date], to_date: Optional[date]) -> dict:
    sales = item_wise_sales(db, from_date, to_date)
    sold_map = {s["catalog_product_id"]: s for s in sales}
    bals = {b.catalog_product_id: int(b.quantity_on_hand) for b in db.query(StockBalance).all()}
    products = (
        db.query(CatalogProduct)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
        .all()
    )
    items = []
    for p in products:
        sold = sold_map.get(p.id, {})
        qty_sold = int(sold.get("qty") or 0)
        on_hand = bals.get(p.id, 0)
        if qty_sold == 0 and on_hand == 0:
            continue
        items.append(
            {
                "id": p.id,
                "label": p.our_product_id,
                "qty_sold": qty_sold,
                "sales_value": sold.get("value") or "0.00",
                "on_hand": on_hand,
                "speed": "fast" if qty_sold >= 20 else ("medium" if qty_sold >= 5 else "slow"),
            }
        )
    fast = sorted([i for i in items if i["qty_sold"] > 0], key=lambda x: x["qty_sold"], reverse=True)[:50]
    slow = sorted([i for i in items if i["on_hand"] > 0], key=lambda x: (x["qty_sold"], -x["on_hand"]))[:50]
    return {"fast": fast, "slow": slow}


def low_stock(db: Session, threshold: Optional[int] = None) -> list[dict]:
    """Low-stock rows. Prefer SQL filter when a fixed threshold is given."""
    default_threshold = 10 if threshold is None else int(threshold)
    q = (
        db.query(CatalogProduct, StockBalance)
        .outerjoin(StockBalance, StockBalance.catalog_product_id == CatalogProduct.id)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
    )
    if threshold is not None:
        q = q.filter(func.coalesce(StockBalance.quantity_on_hand, 0) <= int(threshold))
    rows = q.all()
    items = []
    for p, bal in rows:
        qty = int(bal.quantity_on_hand) if bal else 0
        limit = (
            int(threshold)
            if threshold is not None
            else (int(bal.low_stock_threshold) if bal and bal.low_stock_threshold is not None else default_threshold)
        )
        if qty <= limit:
            items.append(
                {
                    "id": p.id,
                    "label": p.our_product_id,
                    "qty": qty,
                    "threshold": limit,
                    "buying_price": _fmt(p.buying_price),
                    "selling_price": _fmt(p.selling_price) if p.selling_price is not None else None,
                }
            )
    items.sort(key=lambda x: x["qty"])
    return items


def low_stock_count(db: Session, threshold: int = 10) -> int:
    """Fast count for dashboard — SQL only, no row materialization."""
    return int(
        db.query(func.count(CatalogProduct.id))
        .outerjoin(StockBalance, StockBalance.catalog_product_id == CatalogProduct.id)
        .filter(
            CatalogProduct.is_active.is_(True),
            CatalogProduct.deleted_at.is_(None),
            func.coalesce(StockBalance.quantity_on_hand, 0) <= int(threshold),
        )
        .scalar()
        or 0
    )


def returns_register(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    q = db.query(CustomerReturn).order_by(CustomerReturn.created_at.desc())
    if start:
        q = q.filter(CustomerReturn.created_at >= start)
    if end:
        q = q.filter(CustomerReturn.created_at <= end)
    out = []
    for r in q.limit(500).all():
        lines = db.query(CustomerReturnLine).filter(CustomerReturnLine.return_id == r.id).all()
        out.append(
            {
                "id": r.id,
                "doc_number": r.return_number,
                "date": r.created_at.date().isoformat() if r.created_at else None,
                "party_label": _customer_label(db, r.customer_id),
                "customer_id": r.customer_id,
                "credit_amount": _fmt(r.credit_amount),
                "calculated_amount": _fmt(r.calculated_amount),
                "line_count": len(lines),
                "qty": sum(int(ln.quantity_returned or 0) for ln in lines),
            }
        )
    return out


def debit_note_register(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    q = db.query(DebitNote).order_by(DebitNote.created_at.desc())
    if start:
        q = q.filter(DebitNote.created_at >= start)
    if end:
        q = q.filter(DebitNote.created_at <= end)
    out = []
    for d in q.limit(500).all():
        out.append(
            {
                "id": d.id,
                "date": d.created_at.date().isoformat() if d.created_at else None,
                "party_label": _vendor_label(db, d.vendor_id),
                "vendor_id": d.vendor_id,
                "note_type": d.note_type,
                "direction": d.direction,
                "our_product_id": d.our_product_id,
                "quantity": d.quantity,
                "amount": _fmt(d.amount),
                "notes": d.notes,
            }
        )
    return out


def gst_sales_register(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    q = db.query(CustomerBill).order_by(CustomerBill.created_at.desc())
    if start:
        q = q.filter(CustomerBill.created_at >= start)
    if end:
        q = q.filter(CustomerBill.created_at <= end)
    out = []
    for b in q.limit(500).all():
        out.append(
            {
                "id": b.id,
                "date": b.created_at.date().isoformat() if b.created_at else None,
                "doc_number": b.bill_number,
                "party_label": _customer_label(db, b.customer_id),
                "gst_enabled": bool(b.gst_enabled),
                "gst_rate": _fmt(b.gst_rate_percent),
                "taxable_value": _fmt(b.taxable_value),
                "gst_amount": _fmt(b.gst_amount),
                "grand_total": _fmt(b.grand_total),
            }
        )
    return out


def gst_purchase_register(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    """Purchases have no GST fields yet — register shows bill totals with blank tax columns."""
    start, end = _range_bounds(from_date, to_date)
    q = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.entry_type == "bill", ApLedgerEntry.receipt_id.isnot(None))
        .order_by(ApLedgerEntry.created_at.desc())
    )
    if start:
        q = q.filter(ApLedgerEntry.created_at >= start)
    if end:
        q = q.filter(ApLedgerEntry.created_at <= end)
    out = []
    for e in q.limit(500).all():
        receipt = db.get(StockReceipt, e.receipt_id) if e.receipt_id else None
        out.append(
            {
                "id": e.receipt_id or e.id,
                "date": e.created_at.date().isoformat() if e.created_at else None,
                "doc_number": (receipt.bill_number if receipt else None) or f"R-{e.receipt_id}",
                "party_label": _vendor_label(db, e.vendor_id),
                "gst_enabled": False,
                "gst_rate": "0.00",
                "taxable_value": _fmt(e.amount),
                "gst_amount": "0.00",
                "grand_total": _fmt(e.amount),
                "note": "Purchase GST not captured on receipts yet",
            }
        )
    return out


def cashbook(db: Session, from_date: Optional[date], to_date: Optional[date]) -> dict:
    payments = list_payments(db, from_date, to_date)
    start, end = _range_bounds(from_date, to_date)
    rows: list[dict] = []
    for p in payments:
        signed = Decimal(str(p["amount"])) if p["direction"] == "in" else -Decimal(str(p["amount"]))
        rows.append(
            {
                "date": p.get("date"),
                "kind": p["doc_type"],
                "party": p.get("party_label"),
                "label": p.get("description") or p.get("doc_number"),
                "in_amount": p["amount"] if p["direction"] == "in" else "0.00",
                "out_amount": p["amount"] if p["direction"] == "out" else "0.00",
                "signed": _fmt(signed),
                "created_at": p.get("created_at"),
            }
        )
    exp_q = db.query(Expense)
    if from_date:
        exp_q = exp_q.filter(Expense.expense_date >= from_date)
    if to_date:
        exp_q = exp_q.filter(Expense.expense_date <= to_date)
    for ex in exp_q.all():
        rows.append(
            {
                "date": ex.expense_date.isoformat(),
                "kind": "expense",
                "party": ex.category,
                "label": ex.description or ex.category,
                "in_amount": "0.00",
                "out_amount": _fmt(ex.amount),
                "signed": _fmt(-ex.amount),
                "created_at": ex.created_at.isoformat() if ex.created_at else ex.expense_date.isoformat(),
            }
        )
    rows.sort(key=lambda r: r.get("created_at") or r.get("date") or "")
    running = Decimal("0")
    for r in rows:
        running += Decimal(r["signed"])
        r["balance"] = _fmt(running)
    cash_in = sum((Decimal(r["in_amount"]) for r in rows), Decimal("0"))
    cash_out = sum((Decimal(r["out_amount"]) for r in rows), Decimal("0"))
    return {
        "entries": rows,
        "totals": {"cash_in": _fmt(cash_in), "cash_out": _fmt(cash_out), "net": _fmt(cash_in - cash_out), "count": len(rows)},
    }


def expense_by_category(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    q = db.query(Expense)
    if from_date:
        q = q.filter(Expense.expense_date >= from_date)
    if to_date:
        q = q.filter(Expense.expense_date <= to_date)
    agg: dict[str, dict] = {}
    for e in q.all():
        cat = e.category or "misc"
        row = agg.setdefault(cat, {"category": cat, "count": 0, "amount": Decimal("0")})
        row["count"] += 1
        row["amount"] += Decimal(str(e.amount))
    out = [{"category": k, "count": v["count"], "amount": _fmt(v["amount"])} for k, v in agg.items()]
    out.sort(key=lambda x: Decimal(x["amount"]), reverse=True)
    return out


def pnl_detail(db: Session, from_date: Optional[date], to_date: Optional[date]) -> dict:
    start, end = _range_bounds(from_date, to_date)
    # Accrual-ish sales
    sales_q = db.query(CustomerBill)
    if start:
        sales_q = sales_q.filter(CustomerBill.created_at >= start)
    if end:
        sales_q = sales_q.filter(CustomerBill.created_at <= end)
    sales_bills = sales_q.all()
    sales_total = sum((Decimal(str(b.grand_total or 0)) for b in sales_bills), Decimal("0"))
    gst_total = sum((Decimal(str(b.gst_amount or 0)) for b in sales_bills), Decimal("0"))

    # COGS approx = purchase billed in period
    ap_q = db.query(ApLedgerEntry).filter(ApLedgerEntry.entry_type == "bill")
    if start:
        ap_q = ap_q.filter(ApLedgerEntry.created_at >= start)
    if end:
        ap_q = ap_q.filter(ApLedgerEntry.created_at <= end)
    cogs = sum((Decimal(str(e.amount or 0)) for e in ap_q.all()), Decimal("0"))

    exp_q = db.query(Expense)
    if from_date:
        exp_q = exp_q.filter(Expense.expense_date >= from_date)
    if to_date:
        exp_q = exp_q.filter(Expense.expense_date <= to_date)
    expenses = sum((Decimal(str(e.amount)) for e in exp_q.all()), Decimal("0"))

    fr_q = db.query(FreightLedgerEntry).filter(FreightLedgerEntry.entry_type == "settlement")
    if start:
        fr_q = fr_q.filter(FreightLedgerEntry.created_at >= start)
    if end:
        fr_q = fr_q.filter(FreightLedgerEntry.created_at <= end)
    # Freight settle posts an Expense(transport) — do not subtract freight_paid again
    freight_paid = sum((abs(Decimal(str(e.amount))) for e in fr_q.all()), Decimal("0"))

    loss_q = db.query(ManualLoss)
    if from_date:
        loss_q = loss_q.filter(ManualLoss.loss_date >= from_date)
    if to_date:
        loss_q = loss_q.filter(ManualLoss.loss_date <= to_date)
    losses = sum((Decimal(str(l.amount)) for l in loss_q.all()), Decimal("0"))

    # Cash collections for contrast (payments stored signed negative)
    ar_pay = db.query(ArLedgerEntry).filter(ArLedgerEntry.entry_type == "payment")
    if start:
        ar_pay = ar_pay.filter(ArLedgerEntry.created_at >= start)
    if end:
        ar_pay = ar_pay.filter(ArLedgerEntry.created_at <= end)
    cash_in = sum((abs(Decimal(str(p.amount))) for p in ar_pay.all()), Decimal("0"))

    gross = sales_total - cogs
    # expenses already includes freight settlements linked as transport expenses
    net = gross - expenses - losses
    return {
        "sales_billed": _fmt(sales_total),
        "gst_on_sales": _fmt(gst_total),
        "cogs_purchases": _fmt(cogs),
        "gross_profit": _fmt(gross),
        "expenses": _fmt(expenses),
        "freight_paid": _fmt(freight_paid),
        "manual_losses": _fmt(losses),
        "net_profit": _fmt(net),
        "note": "Management approx — freight settle counted once via expenses (not again via freight_paid)",
        "cash_collected": _fmt(cash_in),
        "bill_count": len(sales_bills),
    }


# —— Extra ledgers ——


def list_ledger_staff(db: Session) -> list[dict]:
    staff = db.query(Staff).filter(Staff.deleted_at.is_(None)).order_by(Staff.name.asc()).all()
    out = []
    for s in staff:
        count = (
            db.query(func.count(ActivityLog.id))
            .filter(ActivityLog.actor_type == "staff", ActivityLog.actor_id == s.id)
            .scalar()
            or 0
        )
        out.append({"id": s.id, "label": s.name, "phone": s.phone, "is_active": s.is_active, "activity_count": int(count)})
    # Also include admin-named actors that aren't staff
    admin_names = (
        db.query(ActivityLog.actor_name)
        .filter(ActivityLog.actor_type == "admin")
        .distinct()
        .limit(20)
        .all()
    )
    for (name,) in admin_names:
        count = db.query(func.count(ActivityLog.id)).filter(ActivityLog.actor_type == "admin", ActivityLog.actor_name == name).scalar() or 0
        out.append({"id": 0, "label": f"Admin · {name}", "phone": None, "is_active": True, "activity_count": int(count), "actor_type": "admin", "actor_name": name})
    return out


def staff_activity_ledger(db: Session, staff_id: Optional[int] = None, actor_name: Optional[str] = None, actor_type: str = "staff") -> dict:
    q = db.query(ActivityLog).order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
    label = "Staff"
    if actor_type == "admin" and actor_name:
        q = q.filter(ActivityLog.actor_type == "admin", ActivityLog.actor_name == actor_name)
        label = f"Admin · {actor_name}"
    elif staff_id:
        s = db.get(Staff, staff_id)
        if not s or s.deleted_at:
            return {}
        label = s.name
        q = q.filter(ActivityLog.actor_type == "staff", ActivityLog.actor_id == staff_id)
    else:
        return {}
    entries = q.limit(500).all()
    return {
        "party_type": "staff",
        "party_id": staff_id or 0,
        "party_label": label,
        "activity_count": len(entries),
        "entries": [
            {
                "id": e.id,
                "action": e.action,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "entity_label": e.entity_label,
                "detail": e.detail,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
    }


def list_ledger_freight(db: Session) -> list[dict]:
    agents = db.query(FreightAgent).order_by(FreightAgent.name.asc()).all()
    return [
        {
            "id": a.id,
            "label": a.name,
            "outstanding": _fmt(a.balance_due or 0),
        }
        for a in agents
    ]


def freight_ledger_detail(db: Session, agent_id: int) -> dict:
    agent = db.get(FreightAgent, agent_id)
    if not agent:
        return {}
    entries = (
        db.query(FreightLedgerEntry)
        .filter(FreightLedgerEntry.freight_agent_id == agent_id)
        .order_by(FreightLedgerEntry.created_at.desc(), FreightLedgerEntry.id.desc())
        .limit(300)
        .all()
    )
    return {
        "party_type": "freight",
        "party_id": agent_id,
        "party_label": agent.name,
        "outstanding": _fmt(agent.balance_due or 0),
        "entries": [
            {
                "id": e.id,
                "entry_type": e.entry_type,
                "amount": _fmt(abs(Decimal(str(e.amount)))),
                "signed_amount": _fmt(e.amount),
                "description": e.notes or e.transaction_ref or e.entry_type,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "created_by_name": e.created_by_name,
            }
            for e in entries
        ],
    }


def list_ledger_expenses(db: Session) -> list[dict]:
    rows = (
        db.query(Expense.category, func.count(Expense.id), func.coalesce(func.sum(Expense.amount), 0))
        .group_by(Expense.category)
        .order_by(func.sum(Expense.amount).desc())
        .all()
    )
    return [{"id": i + 1, "label": cat or "misc", "category": cat or "misc", "count": int(cnt), "outstanding": _fmt(total)} for i, (cat, cnt, total) in enumerate(rows)]


def expense_ledger_detail(db: Session, category: str, from_date: Optional[date] = None, to_date: Optional[date] = None) -> dict:
    q = db.query(Expense).filter(Expense.category == category).order_by(Expense.expense_date.desc(), Expense.id.desc())
    if from_date:
        q = q.filter(Expense.expense_date >= from_date)
    if to_date:
        q = q.filter(Expense.expense_date <= to_date)
    entries = q.limit(500).all()
    total = sum((Decimal(str(e.amount)) for e in entries), Decimal("0"))
    running = Decimal("0")
    chrono = list(reversed(entries))
    built = []
    for e in chrono:
        running += Decimal(str(e.amount))
        built.append(
            {
                "id": e.id,
                "entry_type": "expense",
                "amount": _fmt(e.amount),
                "signed_amount": _fmt(e.amount),
                "description": e.description or e.reference or category,
                "value_date": e.expense_date.isoformat(),
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "created_by_name": e.created_by_name,
                "running_balance": _fmt(running),
            }
        )
    built.reverse()
    return {
        "party_type": "expense",
        "party_id": 0,
        "party_label": f"Expense · {category}",
        "outstanding": _fmt(total),
        "bill_total": _fmt(total),
        "payment_total": "0.00",
        "opening_total": "0.00",
        "entries": built,
    }


def list_ledger_routes(db: Session) -> list[dict]:
    routes = db.query(Route).filter(Route.deleted_at.is_(None), Route.is_active.is_(True)).order_by(Route.name.asc()).all()
    out = []
    for r in routes:
        city_ids = [c.id for c in db.query(City).filter(City.route_id == r.id, City.is_active.is_(True)).all()]
        if not city_ids:
            out.append({"id": r.id, "label": r.name, "outstanding": "0.00", "customer_count": 0})
            continue
        customers = db.query(Customer).filter(Customer.city_id.in_(city_ids), Customer.deleted_at.is_(None), Customer.is_active.is_(True)).all()
        due = sum((customer_ar_totals(db, c.id)["outstanding"] for c in customers), Decimal("0"))
        out.append({"id": r.id, "label": r.name, "outstanding": _fmt(due), "customer_count": len(customers)})
    return out


def route_ledger_detail(db: Session, route_id: int) -> dict:
    route = db.get(Route, route_id)
    if not route or route.deleted_at:
        return {}
    city_ids = [c.id for c in db.query(City).filter(City.route_id == route_id).all()]
    customers = (
        db.query(Customer)
        .filter(Customer.city_id.in_(city_ids), Customer.deleted_at.is_(None))
        .order_by(Customer.business_name.asc())
        .all()
        if city_ids
        else []
    )
    entries = []
    total = Decimal("0")
    for c in customers:
        t = customer_ar_totals(db, c.id)
        due = t["outstanding"]
        total += due
        entries.append(
            {
                "id": c.id,
                "entry_type": "customer_due",
                "amount": _fmt(due),
                "signed_amount": _fmt(due),
                "description": c.business_name,
                "running_balance": _fmt(total),
                "created_at": None,
                "value_date": None,
            }
        )
    return {
        "party_type": "route",
        "party_id": route_id,
        "party_label": route.name,
        "outstanding": _fmt(total),
        "entries": entries,
        "customer_count": len(customers),
    }


def cash_ledger_detail(db: Session, from_date: Optional[date] = None, to_date: Optional[date] = None) -> dict:
    book = cashbook(db, from_date, to_date)
    entries = []
    for i, r in enumerate(book["entries"]):
        entries.append(
            {
                "id": i + 1,
                "entry_type": r["kind"],
                "amount": r["in_amount"] if Decimal(r["in_amount"]) > 0 else r["out_amount"],
                "signed_amount": r["signed"],
                "description": f"{r.get('party') or ''} — {r.get('label') or ''}".strip(" —"),
                "value_date": r.get("date"),
                "created_at": r.get("created_at"),
                "running_balance": r.get("balance"),
            }
        )
    return {
        "party_type": "cash",
        "party_id": 0,
        "party_label": "Cash",
        "outstanding": book["totals"]["net"],
        "opening_total": "0.00",
        "bill_total": book["totals"]["cash_in"],
        "payment_total": book["totals"]["cash_out"],
        "entries": list(reversed(entries)),
        "totals": book["totals"],
    }
