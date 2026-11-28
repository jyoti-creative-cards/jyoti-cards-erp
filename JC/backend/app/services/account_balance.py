"""One balance per payment account, and one total per expense subcategory.

Customer receipts add. Vendor payments and cash expenses subtract. The
amount is the payment or the expense, not a raw signed ledger sum.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.accounts_payable import ApLedgerEntry
from app.models.accounts_receivable import ArLedgerEntry
from app.models.expense import Expense, ExpenseHead, ExpenseSource, ExpenseSubhead
from app.models.payment_mode import PaymentMode

LEGACY_NAMES = {
    "cash register": "cash",
    "nc saving account": "nc",
    "icici": "icici",
}


def norm_name(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def match_account(source_name: str | None, modes: list[PaymentMode]) -> PaymentMode | None:
    key = norm_name(source_name)
    if not key:
        return None
    by_name = {norm_name(mode.name): mode for mode in modes}
    if key in by_name:
        return by_name[key]
    legacy = LEGACY_NAMES.get(key)
    if legacy and legacy in by_name:
        return by_name[legacy]
    return None


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _payment_amounts(db: Session, model, modes: list[PaymentMode]) -> tuple[dict[int, Decimal], dict[str, Decimal]]:
    reversed_ids = {
        row[0]
        for row in db.query(model.reverses_entry_id)
        .filter(
            model.entry_type == "payment_reversal",
            model.deleted_at.is_(None),
            model.reverses_entry_id.isnot(None),
        )
        .all()
        if row[0]
    }
    rows = (
        db.query(model)
        .filter(
            model.entry_type == "payment",
            model.deleted_at.is_(None),
        )
        .all()
    )
    by_mode: dict[int, Decimal] = {mode.id: Decimal("0") for mode in modes}
    unmatched: dict[str, Decimal] = {}
    by_name = {norm_name(mode.name): mode for mode in modes}
    for row in rows:
        if row.id in reversed_ids:
            continue
        amount = abs(Decimal(str(row.amount or 0)))
        mode = by_name.get(norm_name(row.payment_mode))
        if mode is None:
            label = " ".join((row.payment_mode or "").split()) or "Unknown"
            unmatched[label] = unmatched.get(label, Decimal("0")) + amount
            continue
        by_mode[mode.id] = by_mode.get(mode.id, Decimal("0")) + amount
    return by_mode, unmatched


def account_balances(db: Session) -> dict:
    modes = db.query(PaymentMode).order_by(PaymentMode.sort_order.asc(), PaymentMode.name.asc()).all()
    sources = db.query(ExpenseSource).all()
    received, received_other = _payment_amounts(db, ArLedgerEntry, modes)
    paid, paid_other = _payment_amounts(db, ApLedgerEntry, modes)
    expenses = db.query(Expense).all()
    spent: dict[int, Decimal] = {mode.id: Decimal("0") for mode in modes}
    other: dict[str, Decimal] = {}
    categories: dict[str, Decimal] = {}
    for row in expenses:
        amount = Decimal(str(row.amount or 0))
        key = (row.category or "").strip().lower()
        if key:
            categories[key] = categories.get(key, Decimal("0")) + amount
        if row.is_cash is False:
            continue
        mode = None
        if row.payment_mode_id:
            mode = next((item for item in modes if item.id == row.payment_mode_id), None)
        if mode is None and row.source_id:
            source = next((item for item in sources if item.id == row.source_id), None)
            mode = match_account(source.name if source else None, modes)
        if mode is None:
            source = next((item for item in sources if item.id == row.source_id), None) if row.source_id else None
            label = source.name if source else "Unknown"
            other[label] = other.get(label, Decimal("0")) + amount
            continue
        spent[mode.id] = spent.get(mode.id, Decimal("0")) + amount

    accounts = []
    for mode in modes:
        balance = received.get(mode.id, Decimal("0")) - paid.get(mode.id, Decimal("0")) - spent.get(mode.id, Decimal("0"))
        accounts.append({"id": mode.id, "name": mode.name, "balance": _money(balance)})

    unmatched = []
    labels = set(received_other) | set(paid_other) | set(other)
    for label in sorted(labels):
        balance = received_other.get(label, Decimal("0")) - paid_other.get(label, Decimal("0")) - other.get(label, Decimal("0"))
        unmatched.append({"name": label, "balance": _money(balance)})

    subs = (
        db.query(ExpenseSubhead, ExpenseHead)
        .join(ExpenseHead, ExpenseHead.id == ExpenseSubhead.head_id)
        .all()
    )
    category_rows = []
    for sub, head in subs:
        key = f"{head.name} / {sub.name}".lower()
        category_rows.append({
            "subhead_id": sub.id,
            "category": key,
            "balance": _money(categories.get(key, Decimal("0"))),
        })
    category_rows.sort(key=lambda row: row["category"])
    return {"accounts": accounts, "unmatched": unmatched, "categories": category_rows}


def paid_from_label(source_name: str | None, mode_name: str | None, modes: list[PaymentMode]) -> str:
    if mode_name:
        return mode_name
    mode = match_account(source_name, modes)
    if mode is not None:
        return mode.name
    return " ".join((source_name or "").split())
