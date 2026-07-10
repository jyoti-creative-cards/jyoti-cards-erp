"""Finance overview — Revenue, Cost, PnL aggregates."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.accounts_payable import ApLedgerEntry
from app.models.accounts_receivable import ArLedgerEntry
from app.models.expense import Expense
from app.models.freight_agent import FreightAgent
from app.models.manual_loss import ManualLoss
from app.services.ap_ledger import list_ap_vendors
from app.services.ar_ledger import list_ar_customers


def _fmt(v: Decimal) -> str:
    return format(v.quantize(Decimal("0.01")), "f")


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def finance_overview(db: Session) -> dict:
    # Revenue = AR cash received (payments)
    ar_payments = (
        db.query(ArLedgerEntry)
        .filter(ArLedgerEntry.entry_type == "payment")
        .all()
    )
    revenue = sum((p.amount for p in ar_payments), Decimal("0"))

    # AR outstanding / billed
    ar_bills = db.query(ArLedgerEntry).filter(ArLedgerEntry.entry_type == "bill").all()
    ar_billed = sum((b.amount for b in ar_bills), Decimal("0"))
    ar_outstanding = (ar_billed - revenue).quantize(Decimal("0.01"))

    # Cost = expenses + AP payments made (cash out), not pending bills
    expenses = db.query(Expense).all()
    expense_total = sum((e.amount for e in expenses), Decimal("0"))
    ap_payments = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.entry_type == "payment")
        .all()
    )
    ap_paid = sum((abs(p.amount) for p in ap_payments), Decimal("0"))
    cost = (expense_total + ap_paid).quantize(Decimal("0.01"))

    # AP outstanding
    ap_rows = db.query(ApLedgerEntry).all()
    ap_outstanding = sum((r.amount for r in ap_rows), Decimal("0")).quantize(Decimal("0.01"))
    ap_billed = sum((r.amount for r in ap_rows if r.entry_type == "bill"), Decimal("0"))

    losses = db.query(ManualLoss).order_by(ManualLoss.loss_date.desc(), ManualLoss.id.desc()).all()
    loss_total = sum((l.amount for l in losses), Decimal("0"))
    profit = (revenue - cost - loss_total).quantize(Decimal("0.01"))

    # Monthly series (last 6 months of activity)
    monthly: dict[str, dict] = {}
    for p in ar_payments:
        k = _month_key(p.created_at.date())
        monthly.setdefault(k, {"month": k, "revenue": Decimal("0"), "cost": Decimal("0"), "expenses": Decimal("0"), "ap_paid": Decimal("0")})
        monthly[k]["revenue"] += p.amount
    for p in ap_payments:
        k = _month_key(p.created_at.date())
        monthly.setdefault(k, {"month": k, "revenue": Decimal("0"), "cost": Decimal("0"), "expenses": Decimal("0"), "ap_paid": Decimal("0")})
        monthly[k]["ap_paid"] += abs(p.amount)
        monthly[k]["cost"] += abs(p.amount)
    for e in expenses:
        k = _month_key(e.expense_date)
        monthly.setdefault(k, {"month": k, "revenue": Decimal("0"), "cost": Decimal("0"), "expenses": Decimal("0"), "ap_paid": Decimal("0")})
        monthly[k]["expenses"] += e.amount
        monthly[k]["cost"] += e.amount

    month_series = []
    for k in sorted(monthly.keys())[-6:]:
        m = monthly[k]
        month_series.append({
            "month": k,
            "revenue": _fmt(m["revenue"]),
            "cost": _fmt(m["cost"]),
            "expenses": _fmt(m["expenses"]),
            "ap_paid": _fmt(m["ap_paid"]),
            "profit": _fmt(m["revenue"] - m["cost"]),
        })

    # Expense by category
    by_cat: dict[str, Decimal] = {}
    for e in expenses:
        by_cat[e.category] = by_cat.get(e.category, Decimal("0")) + e.amount
    expense_breakdown = [
        {"category": cat, "amount": _fmt(amt)}
        for cat, amt in sorted(by_cat.items(), key=lambda x: x[1], reverse=True)
    ]

    # Cost mix
    cost_mix = [
        {"label": "Expenses", "amount": _fmt(expense_total)},
        {"label": "Vendor payments", "amount": _fmt(ap_paid)},
    ]

    vendors = list_ap_vendors(db)
    customers = list_ar_customers(db)

    freight_outstanding = (
        db.query(func.coalesce(func.sum(FreightAgent.balance_due), 0)).scalar() or Decimal("0")
    )
    freight_outstanding = Decimal(str(freight_outstanding)).quantize(Decimal("0.01"))

    return {
        "revenue": _fmt(revenue),
        "revenue_billed": _fmt(ar_billed),
        "ar_outstanding": _fmt(ar_outstanding),
        "cost": _fmt(cost),
        "expense_total": _fmt(expense_total),
        "ap_paid": _fmt(ap_paid),
        "ap_outstanding": _fmt(ap_outstanding),
        "ap_billed": _fmt(ap_billed),
        "freight_outstanding": _fmt(freight_outstanding),
        "manual_loss_total": _fmt(loss_total),
        "profit": _fmt(profit),
        "month_series": month_series,
        "expense_breakdown": expense_breakdown,
        "cost_mix": cost_mix,
        "ap_vendors": vendors[:10],
        "ar_customers": customers[:10],
        "losses": [
            {
                "id": l.id,
                "loss_date": l.loss_date.isoformat(),
                "amount": _fmt(l.amount),
                "description": l.description,
                "created_by_name": l.created_by_name,
                "created_at": l.created_at,
            }
            for l in losses[:50]
        ],
    }
