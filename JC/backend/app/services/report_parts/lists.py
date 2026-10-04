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

from app.services.report_parts.bounds import _batch_labels, _customer_labels, _payment_in_ist_range, _range_bounds, _vendor_labels

def list_sales(db: Session, from_date: Optional[date] = None, to_date: Optional[date] = None) -> list[dict]:
    q = (
        db.query(CustomerBill)
        .filter(CustomerBill.deleted_at.is_(None))
        .order_by(CustomerBill.created_at.desc(), CustomerBill.id.desc())
    )
    start, end = _range_bounds(from_date, to_date)
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
                "doc_type": "sales_bill",
                "doc_number": b.bill_number,
                "party_id": b.customer_id,
                "party_label": labels.get(b.customer_id) or f"Customer #{b.customer_id}",
                "amount": format(b.grand_total or Decimal("0"), "f"),
                "date": b.created_at.date().isoformat() if b.created_at else None,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
        )
    return out

def list_purchases(db: Session, from_date: Optional[date] = None, to_date: Optional[date] = None) -> list[dict]:
    q = (
        db.query(ApLedgerEntry)
        .filter(
            ApLedgerEntry.entry_type == "bill",
            ApLedgerEntry.receipt_id.isnot(None),
            ApLedgerEntry.deleted_at.is_(None),
        )
        .order_by(ApLedgerEntry.created_at.desc(), ApLedgerEntry.id.desc())
    )
    start, end = _range_bounds(from_date, to_date)
    if start:
        q = q.filter(ApLedgerEntry.created_at >= start)
    if end:
        q = q.filter(ApLedgerEntry.created_at <= end)
    rows = q.limit(500).all()
    receipt_ids = {e.receipt_id for e in rows if e.receipt_id}
    receipts = _batch_labels(db, StockReceipt, receipt_ids)
    vendor_labels = _vendor_labels(db, {e.vendor_id for e in rows})
    out = []
    for e in rows:
        receipt = receipts.get(e.receipt_id) if e.receipt_id else None
        party_label = vendor_labels.get(e.vendor_id)
        out.append(
            {
                "id": e.receipt_id or e.id,
                "ledger_id": e.id,
                "doc_type": "purchase_bill",
                "doc_number": (receipt.bill_number if receipt else None) or f"R-{e.receipt_id}",
                "party_id": e.vendor_id,
                "party_label": party_label or f"Vendor #{e.vendor_id}",
                "amount": format(e.amount, "f"),
                "date": e.created_at.date().isoformat() if e.created_at else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
        )
    return out

def list_payments(db: Session, from_date: Optional[date] = None, to_date: Optional[date] = None) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    out: list[dict] = []

    ar_q = db.query(ArLedgerEntry).filter(
        ArLedgerEntry.entry_type == "payment",
        ArLedgerEntry.deleted_at.is_(None),
        _payment_in_ist_range(ArLedgerEntry, from_date, to_date),
    )
    ar_rows = ar_q.order_by(ArLedgerEntry.created_at.desc()).limit(300).all()
    ar_labels = _customer_labels(db, {e.customer_id for e in ar_rows})
    for e in ar_rows:
        out.append(
            {
                "id": e.id,
                "doc_type": "ar_payment",
                "direction": "in",
                "doc_number": e.payment_ref or f"AR-{e.id}",
                "party_id": e.customer_id,
                "party_label": ar_labels.get(e.customer_id) or f"Customer #{e.customer_id}",
                "amount": format(abs(e.amount), "f"),
                "date": (e.value_date.isoformat() if e.value_date else (e.created_at.date().isoformat() if e.created_at else None)),
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "description": e.description,
            }
        )

    ap_q = db.query(ApLedgerEntry).filter(
        ApLedgerEntry.entry_type == "payment",
        ApLedgerEntry.deleted_at.is_(None),
        _payment_in_ist_range(ApLedgerEntry, from_date, to_date),
    )
    ap_rows = ap_q.order_by(ApLedgerEntry.created_at.desc()).limit(300).all()
    ap_labels = _vendor_labels(db, {e.vendor_id for e in ap_rows})
    for e in ap_rows:
        out.append(
            {
                "id": e.id,
                "doc_type": "ap_payment",
                "direction": "out",
                "doc_number": e.payment_ref or f"AP-{e.id}",
                "party_id": e.vendor_id,
                "party_label": ap_labels.get(e.vendor_id) or f"Vendor #{e.vendor_id}",
                "amount": format(abs(e.amount), "f"),
                "date": (e.value_date.isoformat() if e.value_date else (e.created_at.date().isoformat() if e.created_at else None)),
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "description": e.description,
            }
        )

    fr_q = db.query(FreightLedgerEntry).filter(FreightLedgerEntry.entry_type == "settlement")
    if start:
        fr_q = fr_q.filter(FreightLedgerEntry.created_at >= start)
    if end:
        fr_q = fr_q.filter(FreightLedgerEntry.created_at <= end)
    for e in fr_q.order_by(FreightLedgerEntry.created_at.desc()).limit(200).all():
        out.append(
            {
                "id": e.id,
                "doc_type": "freight_payment",
                "direction": "out",
                "doc_number": e.transaction_ref or f"FR-{e.id}",
                "party_id": e.freight_agent_id,
                "party_label": f"Freight #{e.freight_agent_id}",
                "amount": format(abs(e.amount), "f"),
                "date": e.created_at.date().isoformat() if e.created_at else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "description": e.notes or "Freight settlement",
            }
        )

    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out[:500]
