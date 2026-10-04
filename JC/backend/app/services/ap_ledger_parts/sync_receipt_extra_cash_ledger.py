from __future__ import annotations
"""Split from app/services/ap_ledger.py."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.accounts_payable import ApLedgerEntry, VendorApAccount
from app.models.debit_note import DebitNote
from app.models.stock import StockReceipt, StockReceiptLine
from app.models.catalog_product import CatalogProduct
from app.models.vendor import Vendor
from app.models.city import City
from app.deps import AuthContext
from app.services.cost_visibility import hide_cost
from app.services.money import as_signed_decrease, as_signed_increase, mag
from app.services.storage import presigned_url


def sync_receipt_extra_cash_ledger(
    db: Session,
    *,
    vendor_id: int,
    receipt_id: int,
    extra_cash: Decimal,
    bill_label: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
) -> None:
    """Same shape as sync_receipt_bill_ledger, for split-billing vendors' second (extra-cash) AP entry."""
    rows = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.receipt_id == receipt_id, ApLedgerEntry.entry_type.in_(("bill", "adjustment")))
        .order_by(ApLedgerEntry.id.asc())
        .all()
    )
    extra_bill = next((r for r in rows if r.entry_type == "bill" and "extra cash" in (r.description or "")), None)
    target = as_signed_increase(extra_cash) if extra_cash > 0 else Decimal("0.00")
    if extra_bill is None:
        if target > 0:
            post_bill_entry(
                db,
                vendor_id=vendor_id,
                receipt_id=receipt_id,
                amount=target,
                description=f"Bill {bill_label} — extra cash (half-price balance) ₹{target}",
                actor_type=actor_type,
                actor_id=actor_id,
                actor_name=actor_name,
            )
        return
    included = {extra_bill.id}
    changed = True
    while changed:
        changed = False
        for r in rows:
            if r.entry_type == "adjustment" and r.reverses_entry_id in included and r.id not in included:
                included.add(r.id)
                changed = True
    net = sum((Decimal(str(r.amount)) for r in rows if r.id in included), Decimal("0")).quantize(Decimal("0.01"))
    delta = (target - net).quantize(Decimal("0.01"))
    if abs(delta) < Decimal("0.01"):
        return
    post_ap_adjustment(
        db,
        vendor_id=vendor_id,
        amount=delta,
        receipt_id=receipt_id,
        reverses_entry_id=extra_bill.id,
        description=f"Bill adjust {bill_label} — extra cash Δ₹{delta}",
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
    )

def sync_receipt_bill_ledger(
    db: Session,
    *,
    vendor_id: int,
    receipt_id: int,
    bill_total: Decimal,
    bill_label: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
) -> None:
    """Bring AP bill net to `bill_total` via new bill/adjustment rows only."""
    target = as_signed_increase(bill_total) if bill_total > 0 else Decimal("0.00")
    net, bill = receipt_bill_ledger_net(db, receipt_id)
    if bill is None:
        if target > 0:
            post_bill_entry(
                db,
                vendor_id=vendor_id,
                receipt_id=receipt_id,
                amount=target,
                description=f"Bill {bill_label} — ₹{target}",
                actor_type=actor_type,
                actor_id=actor_id,
                actor_name=actor_name,
            )
        return
    delta = (target - net).quantize(Decimal("0.01"))
    if abs(delta) < Decimal("0.01"):
        return
    post_ap_adjustment(
        db,
        vendor_id=vendor_id,
        amount=delta,
        receipt_id=receipt_id,
        reverses_entry_id=bill.id,
        description=f"Bill adjust {bill_label} — Δ₹{delta}",
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
    )

def set_opening_balance(
    db: Session,
    *,
    vendor_id: int,
    amount: Decimal,
    as_on: date,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
) -> Optional[ApLedgerEntry]:
    get_or_create_ap_account(db, vendor_id)
    existing = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.vendor_id == vendor_id, ApLedgerEntry.entry_type == "opening_balance")
        .all()
    )
    for row in existing:
        db.delete(row)
    db.flush()
    amt = amount.quantize(Decimal("0.01"))
    if amt <= 0:
        return None
    entry = ApLedgerEntry(
        vendor_id=vendor_id,
        entry_type="opening_balance",
        amount=amt,
        description=f"Opening balance (as on {as_on.isoformat()}) — ₹{amt}",
        value_date=as_on,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
        created_at=datetime(as_on.year, as_on.month, as_on.day, tzinfo=timezone.utc),
    )
    db.add(entry)
    db.flush()
    account = db.query(VendorApAccount).filter(VendorApAccount.vendor_id == vendor_id).first()
    if account:
        account.updated_at = datetime.now(timezone.utc)
    return entry

def post_payment_entry(
    db: Session,
    *,
    vendor_id: int,
    amount: Decimal,
    payment_ref: str,
    payment_receipt_key: Optional[str],
    payment_comment: Optional[str],
    description: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
    value_date: Optional[date] = None,
    payment_mode: Optional[str] = None,
) -> ApLedgerEntry:
    get_or_create_ap_account(db, vendor_id)
    entry = ApLedgerEntry(
        vendor_id=vendor_id,
        entry_type="payment",
        amount=as_signed_decrease(amount),
        payment_ref=payment_ref,
        payment_receipt_key=payment_receipt_key,
        payment_comment=payment_comment,
        payment_mode=payment_mode,
        description=description,
        value_date=value_date,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(entry)
    db.flush()
    account = db.query(VendorApAccount).filter(VendorApAccount.vendor_id == vendor_id).first()
    if account:
        from datetime import datetime, timezone
        account.updated_at = datetime.now(timezone.utc)
    return entry

def post_debit_note_entry(
    db: Session,
    *,
    vendor_id: int,
    receipt_id: int,
    debit_note_id: int,
    amount: Decimal,
    note_type: str,
    description: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
    created_at: Optional[datetime] = None,
) -> ApLedgerEntry:
    get_or_create_ap_account(db, vendor_id)
    effect = debit_note_payable_effect(amount, note_type)
    entry = ApLedgerEntry(
        vendor_id=vendor_id,
        entry_type="debit_note",
        amount=effect,
        receipt_id=receipt_id,
        debit_note_id=debit_note_id,
        description=description,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    if created_at is not None:
        entry.created_at = created_at
    db.add(entry)
    db.flush()
    return entry

def post_bill_entry(
    db: Session,
    *,
    vendor_id: int,
    receipt_id: int,
    amount: Decimal,
    description: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
    value_date: Optional[date] = None,
    created_at: Optional[datetime] = None,
) -> ApLedgerEntry:
    get_or_create_ap_account(db, vendor_id)
    entry = ApLedgerEntry(
        vendor_id=vendor_id,
        entry_type="bill",
        amount=as_signed_increase(amount),
        receipt_id=receipt_id,
        description=description,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
        value_date=value_date,
    )
    if created_at is not None:
        entry.created_at = created_at
    db.add(entry)
    db.flush()
    return entry

def post_ap_adjustment(
    db: Session,
    *,
    vendor_id: int,
    amount: Decimal,
    description: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
    receipt_id: Optional[int] = None,
    reverses_entry_id: Optional[int] = None,
) -> ApLedgerEntry:
    """Compensating AP row — never mutate / delete prior money history."""
    get_or_create_ap_account(db, vendor_id)
    entry = ApLedgerEntry(
        vendor_id=vendor_id,
        entry_type="adjustment",
        amount=Decimal(str(amount)).quantize(Decimal("0.01")),
        receipt_id=receipt_id,
        description=description[:500],
        reverses_entry_id=reverses_entry_id,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(entry)
    db.flush()
    return entry

def receipt_bill_ledger_net(db: Session, receipt_id: int) -> tuple[Decimal, Optional[ApLedgerEntry]]:
    """Net bill effect for a receipt (bill + chained adjustments). Never mutates."""
    rows = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.receipt_id == receipt_id)
        .order_by(ApLedgerEntry.id.asc())
        .all()
    )
    bill = next((r for r in rows if r.entry_type == "bill"), None)
    if not bill:
        return Decimal("0.00"), None
    included = {bill.id}
    changed = True
    while changed:
        changed = False
        for r in rows:
            if (
                r.entry_type == "adjustment"
                and r.reverses_entry_id in included
                and r.id not in included
            ):
                included.add(r.id)
                changed = True
    net = sum((Decimal(str(r.amount)) for r in rows if r.id in included), Decimal("0"))
    return net.quantize(Decimal("0.01")), bill

def reverse_ap_ledger_row(
    db: Session,
    *,
    orig: ApLedgerEntry,
    reason: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
) -> ApLedgerEntry:
    """Post opposite signed amount; leave `orig` untouched."""
    opp = (-Decimal(str(orig.amount))).quantize(Decimal("0.01"))
    return post_ap_adjustment(
        db,
        vendor_id=orig.vendor_id,
        amount=opp,
        receipt_id=orig.receipt_id,
        reverses_entry_id=orig.id,
        description=f"Reverse {orig.entry_type} #{orig.id} — {reason}",
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
    )

def lock_ap_account(db: Session, vendor_id: int) -> VendorApAccount:
    """Row lock for settle / payment races."""
    row = (
        db.query(VendorApAccount)
        .filter(VendorApAccount.vendor_id == vendor_id)
        .with_for_update()
        .first()
    )
    if row:
        return row
    get_or_create_ap_account(db, vendor_id)
    row = (
        db.query(VendorApAccount)
        .filter(VendorApAccount.vendor_id == vendor_id)
        .with_for_update()
        .first()
    )
    if not row:
        raise RuntimeError(f"AP account missing for vendor {vendor_id}")
    return row

def get_or_create_ap_account(db: Session, vendor_id: int) -> VendorApAccount:
    row = db.query(VendorApAccount).filter(VendorApAccount.vendor_id == vendor_id).first()
    if row:
        return row
    from sqlalchemy.exc import IntegrityError

    try:
        with db.begin_nested():
            row = VendorApAccount(vendor_id=vendor_id, is_open=True)
            db.add(row)
            db.flush()
    except IntegrityError:
        # vendor_id is unique — two concurrent first-ever bills/payments for the same
        # vendor can both miss the SELECT above and both try to insert.
        row = db.query(VendorApAccount).filter(VendorApAccount.vendor_id == vendor_id).first()
        if not row:
            raise
    return row

def debit_note_payable_effect(amount: Decimal, note_type: str) -> Decimal:
    """Effect on net payable: negative = pay less, positive = pay more."""
    amt = amount.quantize(Decimal("0.01"))
    if note_type == "item":
        return -amt
    return amt

def receipt_debit_note_total(db: Session, receipt_id: int) -> Decimal:
    notes = db.query(DebitNote).filter(
        DebitNote.receipt_id == receipt_id, DebitNote.deleted_at.is_(None)
    ).all()
    total = sum((debit_note_payable_effect(n.amount, n.note_type) for n in notes), Decimal("0"))
    return total.quantize(Decimal("0.01"))

