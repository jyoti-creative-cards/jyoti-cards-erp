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

def stock_wise(db: Session, from_date: Optional[date], to_date: Optional[date]) -> dict:
    """Item-wise stock: opening, inward, outward, closing for an IST date range."""
    start, end = _range_bounds(from_date, to_date)
    range_parts = []
    if start is not None:
        range_parts.append(StockLedger.created_at >= start)
    if end is not None:
        range_parts.append(StockLedger.created_at <= end)
    def _in_period(pred):
        return and_(*range_parts, pred) if range_parts else pred

    if start is not None:
        opening_expr = func.coalesce(
            func.sum(case((StockLedger.created_at < start, StockLedger.quantity_delta), else_=0)),
            0,
        )
    else:
        opening_expr = func.coalesce(func.sum(0), 0)
    inward_expr = func.coalesce(
        func.sum(case((_in_period(StockLedger.quantity_delta > 0), StockLedger.quantity_delta), else_=0)),
        0,
    )
    outward_expr = func.coalesce(
        func.sum(case((_in_period(StockLedger.quantity_delta < 0), -StockLedger.quantity_delta), else_=0)),
        0,
    )
    rows = (
        db.query(
            CatalogProduct.id,
            CatalogProduct.our_product_id,
            CatalogProduct.category,
            opening_expr,
            inward_expr,
            outward_expr,
        )
        .join(StockLedger, StockLedger.catalog_product_id == CatalogProduct.id)
        .filter(CatalogProduct.deleted_at.is_(None), CatalogProduct.is_active.is_(True))
        .group_by(CatalogProduct.id, CatalogProduct.our_product_id, CatalogProduct.category)
        .all()
    )
    items = []
    totals = {"opening": 0, "inward": 0, "outward": 0, "closing": 0}
    for pid, label, category, opening, inward, outward in rows:
        opening_n = int(opening or 0)
        inward_n = int(inward or 0)
        outward_n = int(outward or 0)
        closing_n = opening_n + inward_n - outward_n
        if opening_n == 0 and inward_n == 0 and outward_n == 0:
            continue
        items.append(
            {
                "id": pid,
                "label": label,
                "category": category or "",
                "opening": opening_n,
                "inward": inward_n,
                "outward": outward_n,
                "closing": closing_n,
            }
        )
        totals["opening"] += opening_n
        totals["inward"] += inward_n
        totals["outward"] += outward_n
        totals["closing"] += closing_n
    items.sort(key=lambda x: (x["label"] or "", x["id"]))
    totals["sku_count"] = len(items)
    return {"items": items, "totals": totals}

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

def pnl_detail(db: Session, from_date: Optional[date], to_date: Optional[date]) -> dict:
    start, end = _range_bounds(from_date, to_date)
    # Accrual-ish sales
    sales_q = db.query(CustomerBill).filter(CustomerBill.deleted_at.is_(None))
    if start:
        sales_q = sales_q.filter(CustomerBill.created_at >= start)
    if end:
        sales_q = sales_q.filter(CustomerBill.created_at <= end)
    sales_bills = sales_q.all()
    sales_total = sum((Decimal(str(b.grand_total or 0)) for b in sales_bills), Decimal("0"))
    gst_total = sum((Decimal(str(b.gst_amount or 0)) for b in sales_bills), Decimal("0"))
    # GST is a pass-through liability, not revenue — exclude from taxable sales
    sales_taxable = sales_total - gst_total

    # Customer returns (credit notes) reduce net sales — stored signed negative on AR ledger
    cn_q = db.query(ArLedgerEntry).filter(
        ArLedgerEntry.entry_type == "credit_note", ArLedgerEntry.deleted_at.is_(None)
    )
    if start:
        cn_q = cn_q.filter(ArLedgerEntry.created_at >= start)
    if end:
        cn_q = cn_q.filter(ArLedgerEntry.created_at <= end)
    customer_returns = sum((abs(Decimal(str(e.amount or 0))) for e in cn_q.all()), Decimal("0"))
    net_sales = sales_taxable - customer_returns

    # COGS approx = purchase billed in period, net of vendor debit notes (signed: + increases payable/cost, - decreases)
    ap_q = db.query(ApLedgerEntry).filter(
        ApLedgerEntry.entry_type.in_(("bill", "debit_note")), ApLedgerEntry.deleted_at.is_(None)
    )
    if start:
        ap_q = ap_q.filter(ApLedgerEntry.created_at >= start)
    if end:
        ap_q = ap_q.filter(ApLedgerEntry.created_at <= end)
    ap_rows = ap_q.all()
    cogs = sum((Decimal(str(e.amount or 0)) for e in ap_rows if e.entry_type == "bill"), Decimal("0"))
    vendor_debit_notes = sum((Decimal(str(e.amount or 0)) for e in ap_rows if e.entry_type == "debit_note"), Decimal("0"))
    cogs_net = cogs + vendor_debit_notes

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
    ar_pay = db.query(ArLedgerEntry).filter(ArLedgerEntry.entry_type == "payment", ArLedgerEntry.deleted_at.is_(None))
    if start:
        ar_pay = ar_pay.filter(ArLedgerEntry.created_at >= start)
    if end:
        ar_pay = ar_pay.filter(ArLedgerEntry.created_at <= end)
    cash_in = sum((abs(Decimal(str(p.amount))) for p in ar_pay.all()), Decimal("0"))

    gross = net_sales - cogs_net
    # expenses already includes freight settlements linked as transport expenses
    net = gross - expenses - losses
    return {
        "sales_billed": _fmt(sales_total),
        "gst_on_sales": _fmt(gst_total),
        "sales_taxable": _fmt(sales_taxable),
        "customer_returns": _fmt(customer_returns),
        "net_sales": _fmt(net_sales),
        "cogs_purchases": _fmt(cogs),
        "vendor_debit_notes": _fmt(vendor_debit_notes),
        "cogs_net": _fmt(cogs_net),
        "gross_profit": _fmt(gross),
        "expenses": _fmt(expenses),
        "freight_paid": _fmt(freight_paid),
        "manual_losses": _fmt(losses),
        "net_profit": _fmt(net),
        "note": "Excludes GST (pass-through) and nets customer returns + vendor debit notes. Freight settle counted once via expenses (not again via freight_paid).",
        "cash_collected": _fmt(cash_in),
        "bill_count": len(sales_bills),
    }

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

