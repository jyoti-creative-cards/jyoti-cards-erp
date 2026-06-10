"""Chart seed, AR/AP postings, GL/PnL helpers."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.ap_bill import APBill
from app.models.ar_invoice import ARInvoice
from app.models.chart_account import ChartAccount
from app.models.customer_bill import CustomerBill
from app.models.customer_order import CustomerOrder
from app.models.invoice_payment import InvoicePayment
from app.models.journal_entry import JournalEntry, JournalLine
from app.models.vendor import Vendor
from app.models.vendor_bill import VendorBill
from app.models.vendor_purchase_order import VendorPurchaseOrder
from app.services.period_control import assert_period_open_for_posting_date

ACC_CASH = "1000"
ACC_AR = "1100"
ACC_AP = "2000"
ACC_REV = "4000"
ACC_PUR = "5000"

_DEFAULT_CHART: tuple[tuple[str, str, str], ...] = (
    (ACC_CASH, "Cash / Bank", "asset"),
    (ACC_AR, "Accounts Receivable", "asset"),
    (ACC_AP, "Accounts Payable", "liability"),
    (ACC_REV, "Sales Revenue", "revenue"),
    (ACC_PUR, "Purchases / COGS", "expense"),
)


def seed_chart_accounts(db: Session) -> None:
    for code, name, kind in _DEFAULT_CHART:
        row = db.query(ChartAccount).filter(ChartAccount.code == code).first()
        if row is None:
            db.add(ChartAccount(code=code, name=name, kind=kind))


def _d(val: object) -> Decimal:
    try:
        return Decimal(str(val).strip()).quantize(Decimal("0.0001"))
    except Exception:
        return Decimal("0.0000")


def sum_vendor_bill_lines(lines: list) -> Decimal:
    s = Decimal("0")
    for x in lines:
        if not isinstance(x, dict):
            continue
        try:
            q = int(x.get("quantity") or 0)
        except (TypeError, ValueError):
            q = 0
        up = _d(x.get("unit_price"))
        if q:
            s += Decimal(q) * up
    return s.quantize(Decimal("0.01"))


def ap_book_amount_from_vendor_bill(db: Session, *, gross_line_total: Decimal, vendor_id: int) -> tuple[Decimal, int, Decimal]:
    """
    Books-only vendor liability: gross PO line totals × vendor billing_percentage / 100.
    Remainder is off-books cash per your arrangement (not modeled here).
    Returns (booked_amount, pct_used, gross).
    """
    v = db.get(Vendor, vendor_id)
    pct = int(v.billing_percentage) if v and v.billing_percentage is not None else 100
    if pct < 0:
        pct = 0
    if pct > 100:
        pct = 100
    booked = (gross_line_total * Decimal(pct) / Decimal(100)).quantize(Decimal("0.01"))
    return booked, pct, gross_line_total


def create_journal(
    db: Session,
    *,
    memo: str,
    ref_type: str,
    ref_id: Optional[int],
    lines: list[tuple[str, Decimal, Decimal]],
    posted_at: Optional[datetime] = None,
) -> JournalEntry:
    td = sum((ln[1] for ln in lines), Decimal("0"))
    tc = sum((ln[2] for ln in lines), Decimal("0"))
    if td != tc:
        raise ValueError(f"journal unbalanced: debit {td} credit {tc}")
    when = posted_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    assert_period_open_for_posting_date(db, when.date())
    je = JournalEntry(posted_at=when, memo=memo, ref_type=ref_type, ref_id=ref_id)
    db.add(je)
    db.flush()
    for code, debit, credit in lines:
        db.add(
            JournalLine(
                journal_entry_id=je.id,
                account_code=code,
                debit=debit,
                credit=credit,
            )
        )
    return je


def amount_paid_on_ar(db: Session, ar: ARInvoice) -> Decimal:
    total = db.query(sa_func.coalesce(sa_func.sum(InvoicePayment.amount), 0)).filter(
        InvoicePayment.kind == "ar", InvoicePayment.ref_id == ar.id
    ).scalar()
    paid = _d(total or 0)
    if paid == 0 and (ar.status or "").strip().lower() == "paid":
        return _d(ar.amount)
    return paid.quantize(Decimal("0.01"))


def amount_paid_on_ap(db: Session, ap: APBill) -> Decimal:
    total = db.query(sa_func.coalesce(sa_func.sum(InvoicePayment.amount), 0)).filter(
        InvoicePayment.kind == "ap", InvoicePayment.ref_id == ap.id
    ).scalar()
    paid = _d(total or 0)
    if paid == 0 and (ap.status or "").strip().lower() == "paid":
        return _d(ap.amount)
    return paid.quantize(Decimal("0.01"))


def _delete_journal_safe(db: Session, jid: Optional[int]) -> None:
    if not jid:
        return
    row = db.get(JournalEntry, jid)
    if row is not None:
        db.delete(row)


def _posting_at_from_bill_and_order(bill: CustomerBill, order: CustomerOrder) -> datetime:
    t = bill.created_at or order.created_at
    if t is None:
        return datetime.now(timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


def _posting_at_from_vendor_bill(vb: VendorBill, po: VendorPurchaseOrder) -> datetime:
    t = vb.created_at or po.created_at
    if t is None:
        return datetime.now(timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


def _posting_at_from_payment_date(pay_day: date) -> datetime:
    return datetime.combine(pay_day, time(12, 0, 0), tzinfo=timezone.utc)


def ensure_ar_for_customer_bill(
    db: Session,
    *,
    bill: CustomerBill,
    order: CustomerOrder,
    totals: dict,
) -> Optional[ARInvoice]:
    seed_chart_accounts(db)
    amt = _d((totals or {}).get("grand_total") or "0").quantize(Decimal("0.01"))
    if amt <= 0:
        return None
    posted_at = _posting_at_from_bill_and_order(bill, order)

    row = db.query(ARInvoice).filter(ARInvoice.customer_bill_id == bill.id).first()
    if row is not None:
        if row.status == "paid":
            return row
        paid = amount_paid_on_ar(db, row)
        row.customer_id = order.customer_id
        if paid > 0:
            if _d(row.amount).quantize(Decimal("0.01")) != amt:
                raise ValueError("cannot change invoice total after payments recorded")
            db.add(row)
            return row
        row.amount = float(amt)
        _delete_journal_safe(db, row.journal_entry_id)
        row.journal_entry_id = None
        db.flush()
        je = create_journal(
            db,
            memo=f"Customer bill #{bill.id} — AR",
            ref_type="ar_invoice",
            ref_id=row.id,
            lines=[
                (ACC_AR, amt, Decimal("0")),
                (ACC_REV, Decimal("0"), amt),
            ],
            posted_at=posted_at,
        )
        row.journal_entry_id = je.id
        db.add(row)
        return row

    ar = ARInvoice(
        customer_bill_id=bill.id,
        customer_id=order.customer_id,
        amount=float(amt),
        status="open",
    )
    db.add(ar)
    db.flush()
    je = create_journal(
        db,
        memo=f"Customer bill #{bill.id} — AR",
        ref_type="ar_invoice",
        ref_id=ar.id,
        lines=[
            (ACC_AR, amt, Decimal("0")),
            (ACC_REV, Decimal("0"), amt),
        ],
        posted_at=posted_at,
    )
    ar.journal_entry_id = je.id
    db.add(ar)
    return ar


def ensure_ap_for_vendor_bill(db: Session, *, vb: VendorBill, po: VendorPurchaseOrder) -> Optional[APBill]:
    seed_chart_accounts(db)
    raw = vb.bill_lines if isinstance(vb.bill_lines, list) else []
    gross = sum_vendor_bill_lines([x for x in raw if isinstance(x, dict)])
    if gross <= 0:
        return None
    booked, pct, _g = ap_book_amount_from_vendor_bill(db, gross_line_total=gross, vendor_id=po.vendor_id)
    posted_at = _posting_at_from_vendor_bill(vb, po)
    memo = f"Vendor bill #{vb.id} — AP (gross {gross}, books {pct}%)"

    row = db.query(APBill).filter(APBill.vendor_bill_id == vb.id).first()
    if row is not None:
        if row.status == "paid":
            return row
        paid = amount_paid_on_ap(db, row)
        if paid > 0:
            if _d(row.amount).quantize(Decimal("0.01")) != booked:
                raise ValueError("cannot change AP booked amount after payments recorded")
            row.vendor_id = po.vendor_id
            row.purchase_order_id = po.id
            db.add(row)
            return row
        row.amount = float(booked)
        row.vendor_id = po.vendor_id
        row.purchase_order_id = po.id
        _delete_journal_safe(db, row.journal_entry_id)
        row.journal_entry_id = None
        db.flush()
        je = create_journal(
            db,
            memo=memo,
            ref_type="ap_bill",
            ref_id=row.id,
            lines=[
                (ACC_PUR, booked, Decimal("0")),
                (ACC_AP, Decimal("0"), booked),
            ],
            posted_at=posted_at,
        )
        row.journal_entry_id = je.id
        db.add(row)
        return row

    ap = APBill(
        vendor_bill_id=vb.id,
        vendor_id=po.vendor_id,
        purchase_order_id=po.id,
        amount=float(booked),
        status="open",
    )
    db.add(ap)
    db.flush()
    je = create_journal(
        db,
        memo=memo,
        ref_type="ap_bill",
        ref_id=ap.id,
        lines=[
            (ACC_PUR, booked, Decimal("0")),
            (ACC_AP, Decimal("0"), booked),
        ],
        posted_at=posted_at,
    )
    ap.journal_entry_id = je.id
    db.add(ap)
    return ap


def record_ar_payment(
    db: Session,
    ar: ARInvoice,
    *,
    receipt_key: Optional[str],
    transaction_id: Optional[str],
    payment_date: Optional[date],
    amount: Optional[Decimal] = None,
) -> None:
    seed_chart_accounts(db)
    total = _d(ar.amount).quantize(Decimal("0.01"))
    paid_before = amount_paid_on_ar(db, ar)
    if paid_before >= total - Decimal("0.005"):
        raise ValueError("already paid")
    balance = (total - paid_before).quantize(Decimal("0.01"))
    pay = balance if amount is None else _d(amount).quantize(Decimal("0.01"))
    if pay <= 0:
        raise ValueError("payment amount must be positive")
    if pay > balance + Decimal("0.005"):
        raise ValueError("payment exceeds balance")
    pay_day = payment_date or date.today()
    posted_at = _posting_at_from_payment_date(pay_day)
    je = create_journal(
        db,
        memo=f"AR payment AR#{ar.id}",
        ref_type="ar_payment",
        ref_id=ar.id,
        lines=[
            (ACC_CASH, pay, Decimal("0")),
            (ACC_AR, Decimal("0"), pay),
        ],
        posted_at=posted_at,
    )
    db.add(
        InvoicePayment(
            kind="ar",
            ref_id=ar.id,
            amount=float(pay),
            payment_date=pay_day,
            transaction_id=(transaction_id or "").strip() or None,
            receipt_key=receipt_key,
            journal_entry_id=je.id,
        )
    )
    db.flush()
    paid_after = amount_paid_on_ar(db, ar)
    ar.payment_journal_entry_id = je.id
    if receipt_key:
        ar.payment_receipt_key = receipt_key
    ar.payment_transaction_id = (transaction_id or "").strip() or None
    ar.payment_date = pay_day
    if paid_after >= total - Decimal("0.005"):
        ar.status = "paid"
        ar.paid_at = datetime.now(timezone.utc)
    else:
        ar.status = "open"
    db.add(ar)


def record_ap_payment(
    db: Session,
    ap: APBill,
    *,
    receipt_key: Optional[str],
    transaction_id: Optional[str],
    payment_date: Optional[date],
    amount: Optional[Decimal] = None,
) -> None:
    seed_chart_accounts(db)
    total = _d(ap.amount).quantize(Decimal("0.01"))
    paid_before = amount_paid_on_ap(db, ap)
    if paid_before >= total - Decimal("0.005"):
        raise ValueError("already paid")
    balance = (total - paid_before).quantize(Decimal("0.01"))
    pay = balance if amount is None else _d(amount).quantize(Decimal("0.01"))
    if pay <= 0:
        raise ValueError("payment amount must be positive")
    if pay > balance + Decimal("0.005"):
        raise ValueError("payment exceeds balance")
    pay_day = payment_date or date.today()
    posted_at = _posting_at_from_payment_date(pay_day)
    je = create_journal(
        db,
        memo=f"AP payment AP#{ap.id}",
        ref_type="ap_payment",
        ref_id=ap.id,
        lines=[
            (ACC_AP, pay, Decimal("0")),
            (ACC_CASH, Decimal("0"), pay),
        ],
        posted_at=posted_at,
    )
    db.add(
        InvoicePayment(
            kind="ap",
            ref_id=ap.id,
            amount=float(pay),
            payment_date=pay_day,
            transaction_id=(transaction_id or "").strip() or None,
            receipt_key=receipt_key,
            journal_entry_id=je.id,
        )
    )
    db.flush()
    paid_after = amount_paid_on_ap(db, ap)
    ap.payment_journal_entry_id = je.id
    if receipt_key:
        ap.payment_receipt_key = receipt_key
    ap.payment_transaction_id = (transaction_id or "").strip() or None
    ap.payment_date = pay_day
    if paid_after >= total - Decimal("0.005"):
        ap.status = "paid"
        ap.paid_at = datetime.now(timezone.utc)
    else:
        ap.status = "open"
    db.add(ap)


def _account_kinds(db: Session) -> dict[str, str]:
    rows = db.query(ChartAccount).all()
    return {r.code: r.kind for r in rows}


def pnl_for_range(
    db: Session, start: datetime, end: datetime
) -> tuple[Decimal, Decimal, Decimal]:
    """Return (revenue, expense, net) from journal lines in [start, end)."""
    kinds = _account_kinds(db)
    q = (
        db.query(JournalLine, JournalEntry.posted_at)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .filter(JournalEntry.posted_at >= start, JournalEntry.posted_at < end)
    )
    revenue = Decimal("0")
    expense = Decimal("0")
    for line, _pa in q.all():
        code = line.account_code or ""
        k = kinds.get(code, "")
        deb = _d(line.debit)
        cred = _d(line.credit)
        if k == "revenue":
            revenue += cred - deb
        elif k == "expense":
            expense += deb - cred
    net = revenue - expense
    return revenue, expense, net


def monthly_pnl_series(db: Session, start: datetime, end: datetime) -> list[dict[str, Any]]:
    kinds = _account_kinds(db)
    q = (
        db.query(JournalLine, JournalEntry.posted_at)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .filter(JournalEntry.posted_at >= start, JournalEntry.posted_at < end)
    )
    buckets: dict[str, tuple[Decimal, Decimal]] = {}
    for line, posted_at in q.all():
        key = posted_at.strftime("%Y-%m") if posted_at else ""
        if key not in buckets:
            buckets[key] = (Decimal("0"), Decimal("0"))
        rev, exp = buckets[key]
        k = kinds.get(line.account_code or "", "")
        deb = _d(line.debit)
        cred = _d(line.credit)
        if k == "revenue":
            rev += cred - deb
        elif k == "expense":
            exp += deb - cred
        buckets[key] = (rev, exp)
    out = []
    for m in sorted(buckets.keys()):
        rev, exp = buckets[m]
        out.append({"month": m, "revenue": str(rev.quantize(Decimal("0.01"))), "expense": str(exp.quantize(Decimal("0.01"))), "net_pnl": str((rev - exp).quantize(Decimal("0.01")))})
    return out


def gl_activity(
    db: Session, start: datetime, end: datetime
) -> list[tuple[str, str, str, Decimal, Decimal]]:
    """Per-account debit/credit totals in range."""
    names = {r.code: r.name for r in db.query(ChartAccount).all()}
    kinds = _account_kinds(db)
    sums: dict[str, tuple[Decimal, Decimal]] = {}
    q = (
        db.query(JournalLine)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .filter(JournalEntry.posted_at >= start, JournalEntry.posted_at < end)
    )
    for line in q.all():
        code = line.account_code or ""
        deb = _d(line.debit)
        cred = _d(line.credit)
        if code not in sums:
            sums[code] = (Decimal("0"), Decimal("0"))
        d0, c0 = sums[code]
        sums[code] = (d0 + deb, c0 + cred)
    rows = []
    for code in sorted(sums.keys()):
        d0, c0 = sums[code]
        rows.append((code, names.get(code, code), kinds.get(code, ""), d0, c0))
    return rows


def get_customer_outstanding(db: Session, customer_id: int) -> Decimal:
    """Return total outstanding (unpaid) AR balance for a customer."""
    open_invoices = db.query(ARInvoice).filter(
        ARInvoice.customer_id == customer_id,
        ARInvoice.status != "paid",
    ).all()
    total = Decimal("0")
    for inv in open_invoices:
        paid = amount_paid_on_ar(db, inv)
        bal = Decimal(str(inv.amount)) - paid
        if bal > 0:
            total += bal
    return total


def count_open_ar(db: Session) -> int:
    return int(db.query(sa_func.count(ARInvoice.id)).filter(ARInvoice.status == "open").scalar() or 0)


def count_open_ap(db: Session) -> int:
    return int(db.query(sa_func.count(APBill.id)).filter(APBill.status == "open").scalar() or 0)


def order_line_summary(items: list) -> tuple[str, int]:
    skus: list[str] = []
    qty = 0
    for x in items:
        if isinstance(x, dict):
            skus.append(str(x.get("our_product_id") or "").strip())
            try:
                qty += int(x.get("quantity") or 0)
            except (TypeError, ValueError):
                pass
    s = "; ".join([x for x in skus if x])[:200]
    return (s or "—", max(0, qty))


def format_order_date(order: CustomerOrder) -> str:
    try:
        return order.created_at.strftime("%d-%m-%Y") if order.created_at else "—"
    except Exception:
        return "—"
