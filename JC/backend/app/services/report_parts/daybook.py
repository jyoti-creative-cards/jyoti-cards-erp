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

from app.services.report_parts.bounds import _customer_labels, _payment_in_range, _range_bounds, _vendor_labels

def daybook(
    db: Session,
    day: date | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict:
    """One day (`day`) or a custom range (`from_date` / `to_date`). Omit both for all time."""
    if from_date is None and to_date is None and day is not None:
        from_date = to_date = day
    if from_date is not None and to_date is not None and from_date > to_date:
        from_date, to_date = to_date, from_date
    start, end = _range_bounds(from_date, to_date)
    rows: list[dict] = []

    bill_q = db.query(CustomerBill).filter(CustomerBill.deleted_at.is_(None))
    if start is not None:
        bill_q = bill_q.filter(CustomerBill.created_at >= start)
    if end is not None:
        bill_q = bill_q.filter(CustomerBill.created_at <= end)
    bills = bill_q.all()
    bill_parties = _customer_labels(db, {b.customer_id for b in bills})
    for b in bills:
        rows.append(
            {
                "kind": "sales",
                "label": f"Sales bill {b.bill_number}",
                "party": bill_parties.get(b.customer_id) or f"#{b.customer_id}",
                "amount": format(b.grand_total or Decimal("0"), "f"),
                "signed": format(b.grand_total or Decimal("0"), "f"),
                "ref_id": b.id,
                "at": b.created_at.isoformat() if b.created_at else None,
            }
        )

    purchase_q = db.query(ApLedgerEntry).filter(
        ApLedgerEntry.entry_type == "bill",
        ApLedgerEntry.deleted_at.is_(None),
    )
    if start is not None:
        purchase_q = purchase_q.filter(ApLedgerEntry.created_at >= start)
    if end is not None:
        purchase_q = purchase_q.filter(ApLedgerEntry.created_at <= end)
    purchase_rows = purchase_q.all()
    purchase_parties = _vendor_labels(db, {e.vendor_id for e in purchase_rows})
    for e in purchase_rows:
        party = purchase_parties.get(e.vendor_id) or f"Vendor #{e.vendor_id}"
        rows.append(
            {
                "kind": "purchase",
                "label": e.description,
                "party": party,
                "amount": format(e.amount, "f"),
                "signed": format(e.amount, "f"),
                "ref_id": e.receipt_id or e.id,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
        )

    ar_pays = db.query(ArLedgerEntry).filter(
        ArLedgerEntry.entry_type == "payment",
        ArLedgerEntry.deleted_at.is_(None),
        _payment_in_range(ArLedgerEntry, from_date, to_date),
    ).all()
    ar_pay_labels = _customer_labels(db, {e.customer_id for e in ar_pays})
    for e in ar_pays:
        rows.append(
            {
                "kind": "payment_in",
                "label": e.description,
                "party": ar_pay_labels.get(e.customer_id) or f"Customer #{e.customer_id}",
                "amount": format(abs(e.amount), "f"),
                "signed": format(e.amount, "f"),
                "ref_id": e.id,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
        )

    ap_pays = db.query(ApLedgerEntry).filter(
        ApLedgerEntry.entry_type == "payment",
        ApLedgerEntry.deleted_at.is_(None),
        _payment_in_range(ApLedgerEntry, from_date, to_date),
    ).all()
    ap_pay_labels = _vendor_labels(db, {e.vendor_id for e in ap_pays})
    for e in ap_pays:
        rows.append(
            {
                "kind": "payment_out",
                "label": e.description,
                "party": ap_pay_labels.get(e.vendor_id) or f"Vendor #{e.vendor_id}",
                "amount": format(abs(e.amount), "f"),
                "signed": format(e.amount, "f"),
                "ref_id": e.id,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
        )

    ar_other_q = db.query(ArLedgerEntry).filter(
        ArLedgerEntry.entry_type.in_(("opening_balance", "credit_note")),
        ArLedgerEntry.deleted_at.is_(None),
    )
    if start is not None:
        ar_other_q = ar_other_q.filter(ArLedgerEntry.created_at >= start)
    if end is not None:
        ar_other_q = ar_other_q.filter(ArLedgerEntry.created_at <= end)
    ar_other = ar_other_q.all()
    ar_other_labels = _customer_labels(db, {e.customer_id for e in ar_other})
    for e in ar_other:
        rows.append(
            {
                "kind": e.entry_type,
                "label": e.description,
                "party": ar_other_labels.get(e.customer_id) or f"Customer #{e.customer_id}",
                "amount": format(abs(e.amount), "f"),
                "signed": format(e.amount, "f"),
                "ref_id": e.id,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
        )

    ap_other_q = db.query(ApLedgerEntry).filter(
        ApLedgerEntry.entry_type.in_(("opening_balance", "debit_note")),
        ApLedgerEntry.deleted_at.is_(None),
    )
    if start is not None:
        ap_other_q = ap_other_q.filter(ApLedgerEntry.created_at >= start)
    if end is not None:
        ap_other_q = ap_other_q.filter(ApLedgerEntry.created_at <= end)
    ap_other = ap_other_q.all()
    ap_other_labels = _vendor_labels(db, {e.vendor_id for e in ap_other})
    for e in ap_other:
        rows.append(
            {
                "kind": e.entry_type,
                "label": e.description,
                "party": ap_other_labels.get(e.vendor_id) or f"Vendor #{e.vendor_id}",
                "amount": format(abs(e.amount), "f"),
                "signed": format(e.amount, "f"),
                "ref_id": e.id,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
        )

    expense_q = db.query(Expense)
    if from_date is not None:
        expense_q = expense_q.filter(Expense.expense_date >= from_date)
    if to_date is not None:
        expense_q = expense_q.filter(Expense.expense_date <= to_date)
    for ex in expense_q.all():
        cash = ex.is_cash is not False
        rows.append(
            {
                "kind": "expense" if cash else "stock_journal",
                "label": ex.description or ex.category,
                "party": ex.category,
                "amount": format(ex.amount, "f"),
                "signed": format(-ex.amount, "f"),
                "ref_id": ex.id,
                "at": ex.expense_date.isoformat() if ex.expense_date else None,
                "cash": cash,
            }
        )

    freight_q = db.query(FreightLedgerEntry).filter(FreightLedgerEntry.entry_type == "settlement")
    if start is not None:
        freight_q = freight_q.filter(FreightLedgerEntry.created_at >= start)
    if end is not None:
        freight_q = freight_q.filter(FreightLedgerEntry.created_at <= end)
    for e in freight_q.all():
        rows.append(
            {
                "kind": "freight_payment",
                "label": e.notes or f"Freight settle {e.transaction_ref or e.id}",
                "party": f"Freight #{e.freight_agent_id}",
                "amount": format(abs(e.amount), "f"),
                "signed": format(e.amount, "f"),
                "ref_id": e.id,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
        )

    rows.sort(key=lambda r: r.get("at") or "")
    cash_in = sum((Decimal(r["amount"]) for r in rows if r["kind"] == "payment_in"), Decimal("0"))
    # Freight settle already creates an Expense — count expense only (avoid double cash-out)
    cash_out = sum(
        (Decimal(r["amount"]) for r in rows if r["kind"] in ("payment_out", "expense")),
        Decimal("0"),
    )
    span = None
    if from_date and to_date and from_date != to_date:
        span = f"{from_date.isoformat()} to {to_date.isoformat()}"
    elif from_date:
        span = from_date.isoformat()
    elif to_date:
        span = to_date.isoformat()
    return {
        "date": (from_date or to_date).isoformat() if (from_date or to_date) and from_date == to_date else span,
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": to_date.isoformat() if to_date else None,
        "entries": rows,
        "totals": {
            "count": len(rows),
            "cash_in": format(cash_in, "f"),
            "cash_out": format(cash_out, "f"),
            "sales_count": sum(1 for r in rows if r["kind"] == "sales"),
            "purchase_count": sum(1 for r in rows if r["kind"] == "purchase"),
        },
    }

def list_ledger_customers(db: Session) -> list[dict]:
    """Reuse AR aggregate list — one SQL group-by, no N+1."""
    from app.services.ar_ledger import list_ar_customers

    return [
        {
            "id": r["customer_id"],
            "label": r["customer_label"],
            "business_name": r.get("business_name") or "",
            "person_name": r.get("person_name"),
            "alias": r.get("alias"),
            "phone": r.get("phone"),
            "city_name": r.get("city_name"),
            "outstanding": r["outstanding"],
            "opening_total": r["opening_total"],
        }
        for r in list_ar_customers(db)
    ]

def list_ledger_vendors(db: Session) -> list[dict]:
    """Reuse AP aggregate list — one SQL group-by, no N+1."""
    from app.services.ap_ledger import list_ap_vendors

    return [
        {
            "id": r["vendor_id"],
            "label": r["vendor_label"],
            "business_name": r.get("business_name") or "",
            "person_name": r.get("person_name"),
            "alias": r.get("alias"),
            "phone": r.get("phone"),
            "city_name": r.get("city_name"),
            "outstanding": r["outstanding"],
            "opening_total": r["opening_total"],
        }
        for r in list_ap_vendors(db)
    ]

def list_ledger_products(db: Session) -> list[dict]:
    rows = (
        db.query(CatalogProduct, StockBalance)
        .outerjoin(StockBalance, StockBalance.catalog_product_id == CatalogProduct.id)
        .filter(CatalogProduct.is_active.is_(True), CatalogProduct.deleted_at.is_(None))
        .order_by(CatalogProduct.our_product_id.asc())
        .limit(500)
        .all()
    )
    out = []
    for p, bal in rows:
        out.append(
            {
                "id": p.id,
                "label": p.our_product_id + (f" · {p.year_group}" if p.year_group else ""),
                "qty": int(bal.quantity_on_hand) if bal else 0,
                "buying_price": format(p.buying_price, "f"),
                "selling_price": format(p.selling_price, "f") if p.selling_price is not None else None,
            }
        )
    return out

def product_stock_ledger(db: Session, catalog_product_id: int) -> dict:
    prod = db.get(CatalogProduct, catalog_product_id)
    if not prod or not prod.is_active or prod.deleted_at:
        return {}
    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == catalog_product_id).first()
    entries = (
        db.query(StockLedger)
        .filter(StockLedger.catalog_product_id == catalog_product_id)
        .order_by(StockLedger.created_at.desc(), StockLedger.id.desc())
        .limit(200)
        .all()
    )
    from app.services.stock_receipt import annotate_stock_ledger

    rows = []
    for row in annotate_stock_ledger(db, entries):
        created = row["created_at"]
        row = dict(row)
        row["created_at"] = created.isoformat() if created else None
        rows.append(row)
    return {
        "id": prod.id,
        "label": prod.our_product_id,
        "quantity_on_hand": int(bal.quantity_on_hand) if bal else 0,
        "entries": rows,
    }
