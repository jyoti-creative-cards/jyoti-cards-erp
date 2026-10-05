from __future__ import annotations
"""Split from app/services/reports_extended.py."""
"""Extended reports: item/party/ageing/stock/tax/books + extra ledgers."""


from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, case, func, or_
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


def gst_purchase_register(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    """Purchases have no GST fields yet — register shows bill totals with blank tax columns."""
    start, end = _range_bounds(from_date, to_date)
    q = (
        db.query(ApLedgerEntry)
        .filter(
            ApLedgerEntry.entry_type == "bill",
            ApLedgerEntry.receipt_id.isnot(None),
            ApLedgerEntry.deleted_at.is_(None),
        )
        .order_by(ApLedgerEntry.created_at.desc())
    )
    if start:
        q = q.filter(ApLedgerEntry.created_at >= start)
    if end:
        q = q.filter(ApLedgerEntry.created_at <= end)
    rows = q.limit(500).all()
    labels = _vendor_labels(db, {e.vendor_id for e in rows})
    receipt_ids = {e.receipt_id for e in rows if e.receipt_id}
    receipts = {
        r.id: r for r in db.query(StockReceipt).filter(StockReceipt.id.in_(receipt_ids)).all()
    } if receipt_ids else {}
    out = []
    for e in rows:
        receipt = receipts.get(e.receipt_id) if e.receipt_id else None
        party_label = labels.get(e.vendor_id) or f"Vendor #{e.vendor_id}"
        out.append(
            {
                "id": e.receipt_id or e.id,
                "date": e.created_at.date().isoformat() if e.created_at else None,
                "doc_number": (receipt.bill_number if receipt else None) or f"R-{e.receipt_id}",
                "party_label": party_label,
                "gst_enabled": False,
                "gst_rate": "0.00",
                "taxable_value": _fmt(e.amount),
                "gst_amount": "0.00",
                "grand_total": _fmt(e.amount),
                "note": "Purchase GST not captured on receipts yet",
            }
        )
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
    dues = batch_customer_outstanding(db, [c.id for c in customers])
    for c in customers:
        due = dues.get(c.id, Decimal("0"))
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

def expense_ledger_detail(db: Session, category: str, from_date: Optional[date] = None, to_date: Optional[date] = None) -> dict:
    needle = (category or "").strip().lower()
    col = func.lower(Expense.category)
    if " / " in needle:
        match = col == needle
    else:
        match = or_(col == needle, col.like(needle + " / %"))
    q = db.query(Expense).filter(match).order_by(Expense.expense_date.desc(), Expense.id.desc())
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

def vendor_wise_purchases(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    q = db.query(ApLedgerEntry).filter(ApLedgerEntry.entry_type == "bill", ApLedgerEntry.deleted_at.is_(None))
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
    labels = _vendor_labels(db, set(agg))
    due_rows = (
        db.query(ApLedgerEntry.vendor_id, func.sum(ApLedgerEntry.amount))
        .filter(ApLedgerEntry.vendor_id.in_(list(agg)), ApLedgerEntry.deleted_at.is_(None))
        .group_by(ApLedgerEntry.vendor_id)
        .all()
    ) if agg else []
    dues = {vid: Decimal(str(total or 0)) for vid, total in due_rows}
    out = []
    for vid, r in agg.items():
        out.append(
            {
                "id": vid,
                "label": labels.get(vid) or f"Vendor #{vid}",
                "bill_count": r["bill_count"],
                "value": _fmt(r["value"]),
                "outstanding": _fmt(dues.get(vid, Decimal("0"))),
            }
        )
    out.sort(key=lambda x: Decimal(x["value"]), reverse=True)
    return out

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

def returns_register(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    q = db.query(CustomerReturn).filter(CustomerReturn.deleted_at.is_(None)).order_by(CustomerReturn.created_at.desc())
    if start:
        q = q.filter(CustomerReturn.created_at >= start)
    if end:
        q = q.filter(CustomerReturn.created_at <= end)
    rows = q.limit(500).all()
    return_ids = [r.id for r in rows]
    lines_by: dict[int, list] = {}
    if return_ids:
        for ln in db.query(CustomerReturnLine).filter(CustomerReturnLine.return_id.in_(return_ids)).all():
            lines_by.setdefault(ln.return_id, []).append(ln)
    labels = _customer_labels(db, {r.customer_id for r in rows})
    out = []
    for r in rows:
        lines = lines_by.get(r.id) or []
        out.append(
            {
                "id": r.id,
                "doc_number": r.return_number,
                "date": r.created_at.date().isoformat() if r.created_at else None,
                "party_label": labels.get(r.customer_id) or f"Customer #{r.customer_id}",
                "customer_id": r.customer_id,
                "credit_amount": _fmt(r.credit_amount),
                "calculated_amount": _fmt(r.calculated_amount),
                "line_count": len(lines),
                "qty": sum(int(ln.quantity_returned or 0) for ln in lines),
            }
        )
    return out

def customer_wise_sales(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    q = db.query(CustomerBill).filter(CustomerBill.deleted_at.is_(None))
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
    labels = _customer_labels(db, set(agg))
    dues = batch_customer_outstanding(db, list(agg))
    out = []
    for cid, r in agg.items():
        out.append(
            {
                "id": cid,
                "label": labels.get(cid) or f"Customer #{cid}",
                "bill_count": r["bill_count"],
                "value": _fmt(r["value"]),
                "outstanding": _fmt(dues.get(cid, Decimal("0"))),
            }
        )
    out.sort(key=lambda x: Decimal(x["value"]), reverse=True)
    return out

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

def debit_note_register(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    q = db.query(DebitNote).filter(DebitNote.deleted_at.is_(None)).order_by(DebitNote.created_at.desc())
    if start:
        q = q.filter(DebitNote.created_at >= start)
    if end:
        q = q.filter(DebitNote.created_at <= end)
    notes = q.limit(500).all()
    labels = _vendor_labels(db, {d.vendor_id for d in notes})
    out = []
    for d in notes:
        out.append(
            {
                "id": d.id,
                "date": d.created_at.date().isoformat() if d.created_at else None,
                "party_label": labels.get(d.vendor_id) or f"Vendor #{d.vendor_id}",
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
    q = db.query(CustomerBill).filter(CustomerBill.deleted_at.is_(None)).order_by(CustomerBill.created_at.desc())
    if start:
        q = q.filter(CustomerBill.created_at >= start)
    if end:
        q = q.filter(CustomerBill.created_at <= end)
    bills = q.limit(500).all()
    labels = _customer_labels(db, {b.customer_id for b in bills})
    out = []
    for b in bills:
        out.append(
            {
                "id": b.id,
                "date": b.created_at.date().isoformat() if b.created_at else None,
                "doc_number": b.bill_number,
                "party_label": labels.get(b.customer_id) or f"Customer #{b.customer_id}",
                "gst_enabled": bool(b.gst_enabled),
                "gst_rate": _fmt(b.gst_rate_percent),
                "taxable_value": _fmt(b.taxable_value),
                "gst_amount": _fmt(b.gst_amount),
                "grand_total": _fmt(b.grand_total),
            }
        )
    return out

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

def list_ledger_routes(db: Session) -> list[dict]:
    routes = db.query(Route).filter(Route.deleted_at.is_(None), Route.is_active.is_(True)).order_by(Route.name.asc()).all()
    out = []
    for r in routes:
        city_ids = [c.id for c in db.query(City).filter(City.route_id == r.id, City.is_active.is_(True)).all()]
        if not city_ids:
            out.append({"id": r.id, "label": r.name, "outstanding": "0.00", "customer_count": 0})
            continue
        customers = db.query(Customer.id).filter(Customer.city_id.in_(city_ids), Customer.deleted_at.is_(None), Customer.is_active.is_(True)).all()
        dues = batch_customer_outstanding(db, [c.id for c in customers])
        due = sum(dues.values(), Decimal("0"))
        out.append({"id": r.id, "label": r.name, "outstanding": _fmt(due), "customer_count": len(customers)})
    return out

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

def list_ledger_expenses(db: Session) -> list[dict]:
    rows = (
        db.query(Expense.category, func.count(Expense.id), func.coalesce(func.sum(Expense.amount), 0))
        .group_by(Expense.category)
        .order_by(func.sum(Expense.amount).desc())
        .all()
    )
    return [{"id": i + 1, "label": cat or "misc", "category": cat or "misc", "count": int(cnt), "outstanding": _fmt(total)} for i, (cat, cnt, total) in enumerate(rows)]

def _fmt(v: Decimal | int | float | None) -> str:
    if v is None:
        return "0.00"
    return format(Decimal(str(v)).quantize(Decimal("0.01")), "f")

