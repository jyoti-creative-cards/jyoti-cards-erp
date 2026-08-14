from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional

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
from app.services.ap_ledger import _vendor_label, vendor_ap_totals
from app.services.ar_ledger import _customer_label, customer_ar_totals


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=timezone.utc)
    end = datetime.combine(d, time.max, tzinfo=timezone.utc)
    return start, end


def _range_bounds(from_date: Optional[date], to_date: Optional[date]) -> tuple[Optional[datetime], Optional[datetime]]:
    start = datetime.combine(from_date, time.min, tzinfo=timezone.utc) if from_date else None
    end = datetime.combine(to_date, time.max, tzinfo=timezone.utc) if to_date else None
    return start, end


def list_sales(db: Session, from_date: Optional[date] = None, to_date: Optional[date] = None) -> list[dict]:
    q = db.query(CustomerBill).order_by(CustomerBill.created_at.desc(), CustomerBill.id.desc())
    start, end = _range_bounds(from_date, to_date)
    if start:
        q = q.filter(CustomerBill.created_at >= start)
    if end:
        q = q.filter(CustomerBill.created_at <= end)
    out = []
    for b in q.limit(500).all():
        c = db.get(Customer, b.customer_id)
        out.append(
            {
                "id": b.id,
                "doc_type": "sales_bill",
                "doc_number": b.bill_number,
                "party_id": b.customer_id,
                "party_label": c.business_name if c else f"Customer #{b.customer_id}",
                "amount": format(b.grand_total or Decimal("0"), "f"),
                "date": b.created_at.date().isoformat() if b.created_at else None,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
        )
    return out


def list_purchases(db: Session, from_date: Optional[date] = None, to_date: Optional[date] = None) -> list[dict]:
    q = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.entry_type == "bill", ApLedgerEntry.receipt_id.isnot(None))
        .order_by(ApLedgerEntry.created_at.desc(), ApLedgerEntry.id.desc())
    )
    start, end = _range_bounds(from_date, to_date)
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
                "ledger_id": e.id,
                "doc_type": "purchase_bill",
                "doc_number": (receipt.bill_number if receipt else None) or f"R-{e.receipt_id}",
                "party_id": e.vendor_id,
                "party_label": _vendor_label(db, e.vendor_id),
                "amount": format(e.amount, "f"),
                "date": e.created_at.date().isoformat() if e.created_at else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
        )
    return out


def list_payments(db: Session, from_date: Optional[date] = None, to_date: Optional[date] = None) -> list[dict]:
    start, end = _range_bounds(from_date, to_date)
    out: list[dict] = []

    ar_q = db.query(ArLedgerEntry).filter(ArLedgerEntry.entry_type == "payment")
    if start:
        ar_q = ar_q.filter(ArLedgerEntry.created_at >= start)
    if end:
        ar_q = ar_q.filter(ArLedgerEntry.created_at <= end)
    for e in ar_q.order_by(ArLedgerEntry.created_at.desc()).limit(300).all():
        out.append(
            {
                "id": e.id,
                "doc_type": "ar_payment",
                "direction": "in",
                "doc_number": e.payment_ref or f"AR-{e.id}",
                "party_id": e.customer_id,
                "party_label": _customer_label(db, e.customer_id),
                "amount": format(abs(e.amount), "f"),
                "date": e.created_at.date().isoformat() if e.created_at else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "description": e.description,
            }
        )

    ap_q = db.query(ApLedgerEntry).filter(ApLedgerEntry.entry_type == "payment")
    if start:
        ap_q = ap_q.filter(ApLedgerEntry.created_at >= start)
    if end:
        ap_q = ap_q.filter(ApLedgerEntry.created_at <= end)
    for e in ap_q.order_by(ApLedgerEntry.created_at.desc()).limit(300).all():
        out.append(
            {
                "id": e.id,
                "doc_type": "ap_payment",
                "direction": "out",
                "doc_number": e.payment_ref or f"AP-{e.id}",
                "party_id": e.vendor_id,
                "party_label": _vendor_label(db, e.vendor_id),
                "amount": format(abs(e.amount), "f"),
                "date": e.created_at.date().isoformat() if e.created_at else None,
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


def daybook(db: Session, day: date) -> dict:
    start, end = _day_bounds(day)
    rows: list[dict] = []

    for b in db.query(CustomerBill).filter(CustomerBill.created_at >= start, CustomerBill.created_at <= end).all():
        c = db.get(Customer, b.customer_id)
        rows.append(
            {
                "kind": "sales",
                "label": f"Sales bill {b.bill_number}",
                "party": c.business_name if c else f"#{b.customer_id}",
                "amount": format(b.grand_total or Decimal("0"), "f"),
                "signed": format(b.grand_total or Decimal("0"), "f"),
                "ref_id": b.id,
                "at": b.created_at.isoformat() if b.created_at else None,
            }
        )

    for e in db.query(ApLedgerEntry).filter(
        ApLedgerEntry.entry_type == "bill",
        ApLedgerEntry.created_at >= start,
        ApLedgerEntry.created_at <= end,
    ).all():
        rows.append(
            {
                "kind": "purchase",
                "label": e.description,
                "party": _vendor_label(db, e.vendor_id),
                "amount": format(e.amount, "f"),
                "signed": format(e.amount, "f"),
                "ref_id": e.receipt_id or e.id,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
        )

    for e in db.query(ArLedgerEntry).filter(
        ArLedgerEntry.entry_type == "payment",
        ArLedgerEntry.created_at >= start,
        ArLedgerEntry.created_at <= end,
    ).all():
        rows.append(
            {
                "kind": "payment_in",
                "label": e.description,
                "party": _customer_label(db, e.customer_id),
                "amount": format(abs(e.amount), "f"),
                "signed": format(e.amount, "f"),
                "ref_id": e.id,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
        )

    for e in db.query(ApLedgerEntry).filter(
        ApLedgerEntry.entry_type == "payment",
        ApLedgerEntry.created_at >= start,
        ApLedgerEntry.created_at <= end,
    ).all():
        rows.append(
            {
                "kind": "payment_out",
                "label": e.description,
                "party": _vendor_label(db, e.vendor_id),
                "amount": format(abs(e.amount), "f"),
                "signed": format(e.amount, "f"),
                "ref_id": e.id,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
        )

    for e in db.query(ArLedgerEntry).filter(
        ArLedgerEntry.entry_type.in_(("opening_balance", "credit_note")),
        ArLedgerEntry.created_at >= start,
        ArLedgerEntry.created_at <= end,
    ).all():
        rows.append(
            {
                "kind": e.entry_type,
                "label": e.description,
                "party": _customer_label(db, e.customer_id),
                "amount": format(abs(e.amount), "f"),
                "signed": format(e.amount, "f"),
                "ref_id": e.id,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
        )

    for e in db.query(ApLedgerEntry).filter(
        ApLedgerEntry.entry_type.in_(("opening_balance", "debit_note")),
        ApLedgerEntry.created_at >= start,
        ApLedgerEntry.created_at <= end,
    ).all():
        rows.append(
            {
                "kind": e.entry_type,
                "label": e.description,
                "party": _vendor_label(db, e.vendor_id),
                "amount": format(abs(e.amount), "f"),
                "signed": format(e.amount, "f"),
                "ref_id": e.id,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
        )

    for ex in db.query(Expense).filter(Expense.expense_date == day).all():
        rows.append(
            {
                "kind": "expense",
                "label": ex.description or ex.category,
                "party": ex.category,
                "amount": format(ex.amount, "f"),
                "signed": format(-ex.amount, "f"),
                "ref_id": ex.id,
                "at": day.isoformat(),
            }
        )

    for e in db.query(FreightLedgerEntry).filter(
        FreightLedgerEntry.entry_type == "settlement",
        FreightLedgerEntry.created_at >= start,
        FreightLedgerEntry.created_at <= end,
    ).all():
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
    return {
        "date": day.isoformat(),
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
    return {
        "id": prod.id,
        "label": prod.our_product_id,
        "quantity_on_hand": int(bal.quantity_on_hand) if bal else 0,
        "entries": [
            {
                "id": e.id,
                "entry_type": e.entry_type,
                "quantity_delta": e.quantity_delta,
                "balance_after": e.balance_after,
                "party": e.party,
                "notes": e.notes,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
    }
