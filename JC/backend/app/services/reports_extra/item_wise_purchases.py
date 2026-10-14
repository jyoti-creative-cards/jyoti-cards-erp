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

from app.services.reports_extra.gst_purchase_register import _fmt

def item_wise_purchases(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    q = (
        db.query(StockReceiptLine, StockReceipt)
        .join(StockReceipt, StockReceipt.id == StockReceiptLine.receipt_id)
        .filter(
            StockReceiptLine.quantity_billed > 0,
            StockReceipt.deleted_at.is_(None),
        )
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
                "qty": 0,
                "value": Decimal("0"),
                "receipt_count": set(),
                "vendor_ids": set(),
                "lines": [],
            },
        )
        row["qty"] += qty
        row["value"] += value
        row["receipt_count"].add(receipt.id)
        row["vendor_ids"].add(receipt.vendor_id)
        row["lines"].append({"label": ln.our_product_id, "kind": "receipt", "doc_id": receipt.id})
    labels = _product_labels(db, set(agg))
    out = []
    for r in agg.values():
        live = labels.get(r["catalog_product_id"]) or ""
        for ln in r["lines"]:
            if live:
                ln["label"] = live
        out.append(
            {
                "catalog_product_id": r["catalog_product_id"],
                "label": live or f"#{r['catalog_product_id']}",
                "qty": r["qty"],
                "value": _fmt(r["value"]),
                "receipt_count": len(r["receipt_count"]),
                "vendor_count": len(r["vendor_ids"]),
                "lines": r["lines"],
            }
        )
    out.sort(key=lambda x: Decimal(x["value"]), reverse=True)
    return out

def item_wise_sales(db: Session, from_date: Optional[date], to_date: Optional[date]) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    q = (
        db.query(CustomerBillLine, CustomerBill)
        .join(CustomerBill, CustomerBill.id == CustomerBillLine.bill_id)
        .filter(CustomerBillLine.status == "billed", CustomerBill.deleted_at.is_(None))
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
                "qty": 0,
                "value": Decimal("0"),
                "bill_count": set(),
                "customer_ids": set(),
                "lines": [],
            },
        )
        row["qty"] += int(ln.quantity_shipped or 0)
        row["value"] += Decimal(str(ln.line_total or 0))
        row["bill_count"].add(bill.id)
        row["customer_ids"].add(bill.customer_id)
        row["lines"].append({"label": ln.our_product_id, "kind": "bill", "doc_id": bill.id})
    labels = _product_labels(db, set(agg))
    out = []
    for r in agg.values():
        live = labels.get(r["catalog_product_id"]) or ""
        for ln in r["lines"]:
            if live:
                ln["label"] = live
        out.append(
            {
                "catalog_product_id": r["catalog_product_id"],
                "label": live or f"#{r['catalog_product_id']}",
                "qty": r["qty"],
                "value": _fmt(r["value"]),
                "bill_count": len(r["bill_count"]),
                "customer_count": len(r["customer_ids"]),
                "lines": r["lines"],
            }
        )
    out.sort(key=lambda x: Decimal(x["value"]), reverse=True)
    return out

def billed_item_outward(db: Session, from_date: Optional[date], to_date: Optional[date]) -> dict:
    """Items with at least one live bill: bill count, qty sold, rate, and stock left."""
    q = (
        db.query(
            CustomerBillLine.catalog_product_id,
            func.max(CustomerBillLine.our_product_id),
            func.count(func.distinct(CustomerBill.id)),
            func.coalesce(func.sum(CustomerBillLine.quantity_shipped), 0),
            func.coalesce(func.sum(CustomerBillLine.line_total), 0),
        )
        .join(CustomerBill, CustomerBill.id == CustomerBillLine.bill_id)
        .filter(
            CustomerBill.deleted_at.is_(None),
            CustomerBill.cancelled_at.is_(None),
            CustomerBillLine.quantity_shipped > 0,
        )
    )
    if from_date is not None or to_date is not None:
        start, end = _range_bounds(from_date, to_date)
        bill_parts = []
        if from_date is not None:
            bill_parts.append(CustomerBill.bill_date >= from_date)
        if to_date is not None:
            bill_parts.append(CustomerBill.bill_date <= to_date)
        created_parts = [CustomerBill.bill_date.is_(None)]
        if start is not None:
            created_parts.append(CustomerBill.created_at >= start)
        if end is not None:
            created_parts.append(CustomerBill.created_at <= end)
        q = q.filter(or_(and_(*bill_parts), and_(*created_parts)))
    rows = q.group_by(CustomerBillLine.catalog_product_id).all()
    ids = [int(pid) for pid, *_rest in rows if pid]
    products = {
        p.id: p for p in db.query(CatalogProduct).filter(CatalogProduct.id.in_(ids)).all()
    } if ids else {}
    balances = {
        b.catalog_product_id: int(b.quantity_on_hand or 0)
        for b in db.query(StockBalance).filter(StockBalance.catalog_product_id.in_(ids)).all()
    } if ids else {}
    items = []
    for pid, line_name, bills, qty, value in rows:
        if not pid or int(bills or 0) < 1:
            continue
        product = products.get(int(pid))
        qty_n = int(qty or 0)
        value_d = Decimal(str(value or 0))
        rate = (value_d / Decimal(qty_n)).quantize(Decimal("0.01")) if qty_n else Decimal("0.00")
        on_hand = balances.get(int(pid), 0)
        buy = Decimal(str(product.buying_price or 0)) if product else Decimal("0")
        closing_value = (buy * Decimal(on_hand)).quantize(Decimal("0.01"))
        items.append(
            {
                "id": int(pid),
                "label": (product.our_product_id if product else None) or line_name or f"#{pid}",
                "bills": int(bills or 0),
                "out_qty": qty_n,
                "rate": _fmt(rate),
                "closing_qty": on_hand,
                "closing_value": _fmt(closing_value),
            }
        )
    items.sort(key=lambda row: (-row["bills"], row["label"]))
    return {"items": items}

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

def _product_labels(db: Session, product_ids: set[int]) -> dict[int, str]:
    if not product_ids:
        return {}
    return {
        pid: name
        for pid, name in db.query(CatalogProduct.id, CatalogProduct.our_product_id)
        .filter(CatalogProduct.id.in_(product_ids))
        .all()
    }

