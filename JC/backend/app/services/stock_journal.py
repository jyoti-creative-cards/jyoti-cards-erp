"""Stock journal — move leftover stock to a new item number, or consume stock as samples.

Not a sale (no customer, no AR) and not a purchase (no vendor, no AP, no cash).
Consumption posts one non-cash expense so the cost is tracked without leaving the bank.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.deps import AuthContext
from app.models.catalog_product import CatalogProduct
from app.models.expense import Expense
from app.models.stock import StockBalance
from app.models.stock_journal import StockJournal, StockJournalLine
from app.schemas.stock_journal import JournalIn, JournalLineOut, JournalOut
from app.services.activity import log_from_auth
from app.services.biz_date import resolve_biz_dt
from app.services.stock_receipt import add_stock
from app.services import response_cache


def _q(amount: Decimal) -> Decimal:
    return Decimal(str(amount)).quantize(Decimal("0.01"))


def _product(db: Session, product_id: int) -> CatalogProduct:
    row = db.get(CatalogProduct, product_id)
    if not row or row.deleted_at is not None or not row.is_active:
        raise HTTPException(400, "Product not found")
    return row


def _on_hand(db: Session, product_id: int) -> int:
    bal = (
        db.query(StockBalance)
        .filter(StockBalance.catalog_product_id == product_id)
        .first()
    )
    return int(bal.quantity_on_hand) if bal else 0


def _album_products(db: Session, name: str) -> list[CatalogProduct]:
    needle = (name or "").strip().lower()
    if not needle:
        raise HTTPException(400, "Enter the album name")
    rows = (
        db.query(CatalogProduct)
        .filter(
            CatalogProduct.is_active.is_(True),
            CatalogProduct.deleted_at.is_(None),
            or_(
                func.lower(CatalogProduct.category) == needle,
                func.lower(CatalogProduct.second_category) == needle,
                func.lower(CatalogProduct.series) == needle,
            ),
        )
        .order_by(CatalogProduct.our_product_id.asc(), CatalogProduct.id.asc())
        .all()
    )
    if not rows:
        raise HTTPException(400, f"No active products match “{name.strip()}”")
    return rows


def _buying_rate(product: CatalogProduct, override: Decimal | None, *, required: bool) -> Decimal:
    raw = override if override is not None else product.buying_price
    if raw is None:
        if required:
            raise HTTPException(
                400,
                f"{product.our_product_id} has no buying price. Enter a rate before saving.",
            )
        return Decimal("0.00")
    rate = _q(Decimal(str(raw)))
    if required and rate <= 0:
        raise HTTPException(400, f"{product.our_product_id} needs a buying price above zero.")
    return rate


def resolve_lines(db: Session, body: JournalIn) -> tuple[list[dict], list[str], Decimal]:
    """Expand the form into concrete stock lines. Does not write."""
    warnings: list[str] = []
    drafted: list[dict] = []

    if body.kind == "transfer":
        if not body.from_product_id or not body.to_product_id or not body.quantity:
            raise HTTPException(400, "Transfer needs the old item, the new item, and a quantity.")
        if body.from_product_id == body.to_product_id:
            raise HTTPException(400, "Old item and new item are the same.")
        src = _product(db, body.from_product_id)
        dst = _product(db, body.to_product_id)
        qty = int(body.quantity)
        src_rate = _buying_rate(src, None, required=False)
        dst_rate = _buying_rate(dst, None, required=False)
        if src.buying_price is None or dst.buying_price is None:
            warnings.append(
                f"{src.our_product_id} or {dst.our_product_id} has no buying price. "
                "Quantity will move. Stock value for a missing price stays zero."
            )
        elif src_rate != dst_rate:
            warnings.append(
                f"{src.our_product_id} buying price is {src_rate}, {dst.our_product_id} is {dst_rate}. "
                "Quantity moves. Stock value changes because each item keeps its own buying price."
            )
        drafted.append({
            "product": src,
            "quantity_delta": -qty,
            "rate": src_rate,
            "amount": _q(src_rate * qty),
        })
        drafted.append({
            "product": dst,
            "quantity_delta": qty,
            "rate": dst_rate,
            "amount": _q(dst_rate * qty),
        })
        total = Decimal("0.00")
    else:
        if body.album and body.lines:
            raise HTTPException(400, "Use either an album or item lines, not both.")
        if body.album:
            if not body.copies:
                raise HTTPException(400, "Enter how many catalogue copies.")
            products = _album_products(db, body.album)
            copies = int(body.copies)
            drafted = []
            for product in products:
                rate = _buying_rate(product, None, required=True)
                drafted.append({
                    "product": product,
                    "quantity_delta": -copies,
                    "rate": rate,
                    "amount": _q(rate * copies),
                })
        elif body.lines:
            for ln in body.lines:
                product = _product(db, ln.catalog_product_id)
                rate = _buying_rate(product, ln.rate, required=True)
                drafted.append({
                    "product": product,
                    "quantity_delta": -int(ln.quantity),
                    "rate": rate,
                    "amount": _q(rate * int(ln.quantity)),
                })
        else:
            raise HTTPException(400, "Add item lines, or an album name and copies.")
        if not drafted:
            raise HTTPException(400, "Nothing to consume.")
        total = _q(sum((row["amount"] for row in drafted), Decimal("0")))

    # Merge same product so one check sees the full outward qty.
    merged: dict[int, dict] = {}
    for row in drafted:
        pid = int(row["product"].id)
        cur = merged.get(pid)
        if cur is None:
            merged[pid] = dict(row)
            continue
        cur["quantity_delta"] = int(cur["quantity_delta"]) + int(row["quantity_delta"])
        cur["amount"] = _q(cur["amount"] + row["amount"])
    lines = [row for row in merged.values() if int(row["quantity_delta"]) != 0]
    if not lines:
        raise HTTPException(400, "Nothing to post.")

    for row in lines:
        need = -int(row["quantity_delta"])
        if need <= 0:
            row["on_hand"] = _on_hand(db, int(row["product"].id))
            continue
        have = _on_hand(db, int(row["product"].id))
        row["on_hand"] = have
        if have < need:
            raise HTTPException(
                400,
                f"Not enough stock of {row['product'].our_product_id}: have {have}, journal needs {need}.",
            )
    return lines, warnings, total


def _line_out(row: dict) -> JournalLineOut:
    product: CatalogProduct = row["product"]
    return JournalLineOut(
        catalog_product_id=int(product.id),
        our_product_id=product.our_product_id,
        quantity_delta=int(row["quantity_delta"]),
        rate=format(row["rate"], "f"),
        amount=format(row["amount"], "f"),
        on_hand=int(row.get("on_hand") or 0),
    )


def preview_journal(db: Session, body: JournalIn) -> JournalOut:
    lines, warnings, total = resolve_lines(db, body)
    return JournalOut(
        id=0,
        journal_date=body.journal_date,
        kind=body.kind,
        narration=(body.narration or "").strip() or None,
        expense_category=(body.expense_category or "").strip().lower() or None,
        total_cost=format(total, "f"),
        lines=[_line_out(row) for row in lines],
        warnings=warnings,
    )


def post_journal(db: Session, body: JournalIn, auth: AuthContext) -> JournalOut:
    lines, warnings, total = resolve_lines(db, body)
    when = resolve_biz_dt(body.journal_date)
    # Lock outward balances before writing so two journals cannot oversell the same qty.
    for row in lines:
        if int(row["quantity_delta"]) >= 0:
            continue
        bal = (
            db.query(StockBalance)
            .filter(StockBalance.catalog_product_id == int(row["product"].id))
            .with_for_update()
            .first()
        )
        have = int(bal.quantity_on_hand) if bal else 0
        need = -int(row["quantity_delta"])
        if have < need:
            raise HTTPException(
                400,
                f"Not enough stock of {row['product'].our_product_id}: have {have}, journal needs {need}.",
            )

    journal = StockJournal(
        journal_date=body.journal_date,
        kind=body.kind,
        narration=(body.narration or "").strip() or None,
        expense_category=(
            (body.expense_category or "").strip().lower() or None
            if body.kind == "transfer"
            else (body.expense_category or "sample catalogues").strip().lower() or "sample catalogues"
        ),
        total_cost=total,
        created_by_name=auth.actor_name or "Admin",
        created_at=when,
    )
    db.add(journal)
    db.flush()

    ordered = sorted(lines, key=lambda row: (int(row["quantity_delta"]) > 0, int(row["product"].id)))
    saved: list[JournalLineOut] = []
    for row in ordered:
        product: CatalogProduct = row["product"]
        delta = int(row["quantity_delta"])
        db.add(
            StockJournalLine(
                journal_id=journal.id,
                catalog_product_id=product.id,
                our_product_id=product.our_product_id,
                quantity_delta=delta,
                rate=row["rate"],
                amount=row["amount"],
            )
        )
        balance = add_stock(
            db,
            catalog_product_id=product.id,
            our_product_id=product.our_product_id,
            quantity=delta,
            entry_type="journal",
            reference_type="stock_journal",
            reference_id=journal.id,
            party=None,
            notes=journal.narration or body.kind,
            created_at=when,
        )
        saved.append(
            JournalLineOut(
                catalog_product_id=product.id,
                our_product_id=product.our_product_id,
                quantity_delta=delta,
                rate=format(row["rate"], "f"),
                amount=format(row["amount"], "f"),
                on_hand=int(balance.quantity_on_hand),
            )
        )

    if body.kind == "consumption":
        category = (body.expense_category or "sample catalogues").strip().lower() or "sample catalogues"
        expense = Expense(
            expense_date=body.journal_date,
            category=category,
            description=(body.narration or "").strip() or f"Stock journal #{journal.id}",
            amount=total,
            reference=f"journal:{journal.id}",
            is_cash=False,
            created_by_name=auth.actor_name or "Admin",
        )
        db.add(expense)
        db.flush()
        journal.expense_id = expense.id
        journal.expense_category = category

    log_from_auth(
        db,
        auth,
        action="create",
        entity_type="stock_journal",
        entity_id=journal.id,
        entity_label=body.kind,
        detail=f"₹{total}" if body.kind == "consumption" else f"{len(saved)} lines",
    )
    db.commit()
    db.refresh(journal)
    response_cache.invalidate("stock")
    response_cache.invalidate("ledger")
    return JournalOut(
        id=journal.id,
        journal_date=journal.journal_date,
        kind=journal.kind,
        narration=journal.narration,
        expense_category=journal.expense_category,
        expense_id=journal.expense_id,
        total_cost=format(journal.total_cost, "f"),
        created_by_name=journal.created_by_name,
        voided_at=journal.voided_at,
        void_reason=journal.void_reason,
        lines=saved,
        warnings=warnings,
    )


def _journal_out(db: Session, journal: StockJournal, warnings: list[str] | None = None) -> JournalOut:
    rows = (
        db.query(StockJournalLine)
        .filter(StockJournalLine.journal_id == journal.id)
        .order_by(StockJournalLine.id.asc())
        .all()
    )
    lines = [
        JournalLineOut(
            catalog_product_id=ln.catalog_product_id,
            our_product_id=ln.our_product_id,
            quantity_delta=ln.quantity_delta,
            rate=format(ln.rate, "f"),
            amount=format(ln.amount, "f"),
            on_hand=_on_hand(db, ln.catalog_product_id),
        )
        for ln in rows
    ]
    return JournalOut(
        id=journal.id,
        journal_date=journal.journal_date,
        kind=journal.kind,
        narration=journal.narration,
        expense_category=journal.expense_category,
        expense_id=journal.expense_id,
        total_cost=format(journal.total_cost, "f"),
        created_by_name=journal.created_by_name,
        voided_at=journal.voided_at,
        void_reason=journal.void_reason,
        lines=lines,
        warnings=warnings or [],
    )


def list_journals(db: Session, from_date=None, to_date=None) -> list[JournalOut]:
    q = db.query(StockJournal)
    if from_date is not None:
        q = q.filter(StockJournal.journal_date >= from_date)
    if to_date is not None:
        q = q.filter(StockJournal.journal_date <= to_date)
    rows = q.order_by(StockJournal.journal_date.desc(), StockJournal.id.desc()).all()
    return [_journal_out(db, row) for row in rows]


def get_journal(db: Session, journal_id: int) -> JournalOut:
    row = db.get(StockJournal, journal_id)
    if not row:
        raise HTTPException(404, "Journal not found")
    return _journal_out(db, row)


def void_journal(db: Session, journal_id: int, reason: str, auth: AuthContext) -> JournalOut:
    journal = db.get(StockJournal, journal_id)
    if not journal:
        raise HTTPException(404, "Journal not found")
    if journal.voided_at is not None:
        raise HTTPException(400, "Journal is already voided")
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(400, "Enter a reason")
    lines = (
        db.query(StockJournalLine)
        .filter(StockJournalLine.journal_id == journal.id)
        .order_by(StockJournalLine.id.asc())
        .all()
    )
    when = datetime.now(timezone.utc)
    # Put stock back in reverse order of the original post (inward first was last).
    for ln in reversed(lines):
        add_stock(
            db,
            catalog_product_id=ln.catalog_product_id,
            our_product_id=ln.our_product_id,
            quantity=-int(ln.quantity_delta),
            entry_type="journal_void",
            reference_type="stock_journal",
            reference_id=journal.id,
            notes=reason,
            created_at=when,
        )
    if journal.expense_id:
        expense = db.get(Expense, journal.expense_id)
        if expense is not None:
            db.delete(expense)
        journal.expense_id = None
    journal.voided_at = when
    journal.voided_by_name = auth.actor_name or "Admin"
    journal.void_reason = reason
    log_from_auth(
        db,
        auth,
        action="void",
        entity_type="stock_journal",
        entity_id=journal.id,
        entity_label=journal.kind,
        detail=reason,
    )
    db.commit()
    db.refresh(journal)
    response_cache.invalidate("stock")
    response_cache.invalidate("ledger")
    return _journal_out(db, journal)
