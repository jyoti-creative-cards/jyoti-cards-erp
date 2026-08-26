"""Finance overview — cash pulse + books snapshot.

Money correctness:
- Collect / Pay / Freight dues come only from money.dues_snapshot
- cash_pulse is cash movement — NOT books P&L
- books_snapshot is receivables/payables position + billed/collected to date
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.accounts_payable import ApLedgerEntry
from app.models.accounts_receivable import ArLedgerEntry
from app.models.expense import Expense
from app.models.manual_loss import ManualLoss
from app.services.ap_ledger import ap_dues_total
from app.services.ar_ledger import ar_dues_total
from app.services.freight_ledger import freight_dues_total
from app.services.money import mag


def _fmt(v: Decimal) -> str:
    return format(v.quantize(Decimal("0.01")), "f")


def _sum_type(db: Session, model, entry_type: str) -> Decimal:
    raw = (
        db.query(func.coalesce(func.sum(model.amount), 0))
        .filter(model.entry_type == entry_type, model.deleted_at.is_(None))
        .scalar()
    )
    return Decimal(str(raw or 0)).quantize(Decimal("0.01"))


def _sum_types(db: Session, model, entry_types: tuple[str, ...]) -> Decimal:
    """Sum multiple entry types together — used to net payments against their reversals."""
    raw = (
        db.query(func.coalesce(func.sum(model.amount), 0))
        .filter(model.entry_type.in_(entry_types), model.deleted_at.is_(None))
        .scalar()
    )
    return Decimal(str(raw or 0)).quantize(Decimal("0.01"))


def finance_overview(db: Session) -> dict:
    # One dues pass — same numbers as GET /finance/dues
    ar = ar_dues_total(db)
    ap = ap_dues_total(db)
    fr = freight_dues_total(db)
    dues = {
        "ar": {"total": _fmt(ar["total"]), "count": ar["count"]},
        "ap": {"total": _fmt(ap["total"]), "count": ap["count"]},
        "freight": {"total": _fmt(fr["total"]), "count": fr["count"]},
        "currency": "INR",
        "convention": "signed_ledger_sum",
    }

    # SQL aggregates — never load full ledgers into Python.
    # Net "payment" against "payment_reversal" so voided/reversed payments don't inflate cash moved.
    ar_payment_sum = _sum_types(db, ArLedgerEntry, ("payment", "payment_reversal"))  # signed negative
    revenue = mag(ar_payment_sum)
    ar_billed = mag(_sum_type(db, ArLedgerEntry, "bill"))
    ar_credit_total = mag(_sum_type(db, ArLedgerEntry, "credit_note"))
    ar_opening = mag(_sum_type(db, ArLedgerEntry, "opening_balance"))

    expense_total = Decimal(
        str(db.query(func.coalesce(func.sum(Expense.amount), 0)).scalar() or 0)
    ).quantize(Decimal("0.01"))
    ap_payment_sum = _sum_types(db, ApLedgerEntry, ("payment", "payment_reversal"))
    ap_paid = mag(ap_payment_sum)
    cash_out = (expense_total + ap_paid).quantize(Decimal("0.01"))
    ap_billed = _sum_type(db, ApLedgerEntry, "bill")

    loss_total = Decimal(
        str(db.query(func.coalesce(func.sum(ManualLoss.amount), 0)).scalar() or 0)
    ).quantize(Decimal("0.01"))
    net_cash = (revenue - cash_out - loss_total).quantize(Decimal("0.01"))

    # Monthly cash series (last 6) via date_trunc — net payments against reversals, exclude voided rows
    month_expr_ar = func.date_trunc("month", ArLedgerEntry.created_at)
    ar_by_month = (
        db.query(month_expr_ar, func.coalesce(func.sum(ArLedgerEntry.amount), 0))
        .filter(ArLedgerEntry.entry_type.in_(("payment", "payment_reversal")), ArLedgerEntry.deleted_at.is_(None))
        .group_by(month_expr_ar)
        .all()
    )
    month_expr_ap = func.date_trunc("month", ApLedgerEntry.created_at)
    ap_by_month = (
        db.query(month_expr_ap, func.coalesce(func.sum(ApLedgerEntry.amount), 0))
        .filter(ApLedgerEntry.entry_type.in_(("payment", "payment_reversal")), ApLedgerEntry.deleted_at.is_(None))
        .group_by(month_expr_ap)
        .all()
    )
    month_expr_ex = func.date_trunc("month", Expense.expense_date)
    ex_by_month = (
        db.query(month_expr_ex, func.coalesce(func.sum(Expense.amount), 0))
        .group_by(month_expr_ex)
        .all()
    )

    monthly: dict[str, dict] = {}

    def _mk(dt) -> str:
        if dt is None:
            return "unknown"
        if hasattr(dt, "date"):
            d = dt.date()
        else:
            d = dt
        return f"{d.year:04d}-{d.month:02d}"

    for dt, amt in ar_by_month:
        k = _mk(dt)
        monthly.setdefault(k, {"month": k, "revenue": Decimal("0"), "cost": Decimal("0"), "expenses": Decimal("0"), "ap_paid": Decimal("0")})
        monthly[k]["revenue"] += mag(amt)
    for dt, amt in ap_by_month:
        k = _mk(dt)
        monthly.setdefault(k, {"month": k, "revenue": Decimal("0"), "cost": Decimal("0"), "expenses": Decimal("0"), "ap_paid": Decimal("0")})
        paid = mag(amt)
        monthly[k]["ap_paid"] += paid
        monthly[k]["cost"] += paid
    for dt, amt in ex_by_month:
        k = _mk(dt)
        monthly.setdefault(k, {"month": k, "revenue": Decimal("0"), "cost": Decimal("0"), "expenses": Decimal("0"), "ap_paid": Decimal("0")})
        a = Decimal(str(amt or 0))
        monthly[k]["expenses"] += a
        monthly[k]["cost"] += a

    month_series = []
    for k in sorted(monthly.keys())[-6:]:
        m = monthly[k]
        month_series.append({
            "month": k,
            "revenue": _fmt(m["revenue"]),
            "cost": _fmt(m["cost"]),
            "expenses": _fmt(m["expenses"]),
            "ap_paid": _fmt(m["ap_paid"]),
            "net_cash": _fmt(m["revenue"] - m["cost"]),
            "profit": _fmt(m["revenue"] - m["cost"]),
        })

    cat_rows = (
        db.query(Expense.category, func.coalesce(func.sum(Expense.amount), 0))
        .group_by(Expense.category)
        .all()
    )
    expense_breakdown = [
        {"category": cat, "amount": _fmt(Decimal(str(amt or 0)))}
        for cat, amt in sorted(cat_rows, key=lambda x: Decimal(str(x[1] or 0)), reverse=True)
    ]

    cost_mix = [
        {"label": "Expenses", "amount": _fmt(expense_total)},
        {"label": "Vendor payments", "amount": _fmt(ap_paid)},
    ]

    # Top-10 for hub cards — reuse dues parties already loaded
    vendors = [
        {
            "vendor_id": v["vendor_id"],
            "vendor_label": v["vendor_label"],
            "outstanding": v["outstanding"],
            "opening_total": "0.00",
            "bill_total": "0.00",
            "debit_note_total": "0.00",
            "payment_total": "0.00",
            "transaction_count": 0,
        }
        for v in ap["parties"][:10]
    ]
    customers = [
        {
            "customer_id": c["customer_id"],
            "customer_label": c["customer_label"],
            "outstanding": c["outstanding"],
            "opening_total": "0.00",
            "bill_total": "0.00",
            "payment_total": "0.00",
            "credit_total": "0.00",
            "transaction_count": 0,
        }
        for c in ar["parties"][:10]
    ]

    losses = (
        db.query(ManualLoss)
        .order_by(ManualLoss.loss_date.desc(), ManualLoss.id.desc())
        .limit(50)
        .all()
    )

    cash_pulse = {
        "cash_in": _fmt(revenue),
        "cash_out": _fmt(cash_out),
        "net_cash": _fmt(net_cash),
        "manual_losses": _fmt(loss_total),
        "note": "Cash movement only — not books P&L. Does not include opening receivables or inventory.",
    }

    books_snapshot = {
        "ar_outstanding": dues["ar"]["total"],
        "ap_outstanding": dues["ap"]["total"],
        "freight_outstanding": dues["freight"]["total"],
        "ar_opening": _fmt(ar_opening),
        "ar_billed": _fmt(ar_billed),
        "ar_collected": _fmt(revenue),
        "ar_credits": _fmt(ar_credit_total),
        "ap_billed": _fmt(ap_billed),
        "ap_paid": _fmt(ap_paid),
        "note": "Position from signed ledgers. Not a full accounting P&L.",
    }

    return {
        "dues": dues,
        "ar_outstanding": dues["ar"]["total"],
        "ap_outstanding": dues["ap"]["total"],
        "freight_outstanding": dues["freight"]["total"],
        "ar_due_parties": dues["ar"]["count"],
        "ap_due_parties": dues["ap"]["count"],
        "cash_pulse": cash_pulse,
        "revenue": _fmt(revenue),
        "cost": _fmt(cash_out),
        "expense_total": _fmt(expense_total),
        "ap_paid": _fmt(ap_paid),
        "manual_loss_total": _fmt(loss_total),
        "net_cash": _fmt(net_cash),
        "profit": _fmt(net_cash),
        "profit_is_net_cash": True,
        "books_snapshot": books_snapshot,
        "revenue_billed": _fmt(ar_billed),
        "ar_credit_total": _fmt(ar_credit_total),
        "ap_billed": _fmt(ap_billed),
        "month_series": month_series,
        "expense_breakdown": expense_breakdown,
        "cost_mix": cost_mix,
        "ap_vendors": vendors,
        "ar_customers": customers,
        "losses": [
            {
                "id": l.id,
                "loss_date": l.loss_date.isoformat(),
                "amount": _fmt(l.amount),
                "description": l.description,
                "created_by_name": l.created_by_name,
                "created_at": l.created_at,
            }
            for l in losses
        ],
    }
