from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.accounts_payable import ApLedgerEntry, VendorApAccount
from app.models.debit_note import DebitNote
from app.models.stock import StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.models.city import City
from app.services.money import as_signed_decrease, as_signed_increase, mag
from app.services.storage import presigned_url


def _vendor_label(db: Session, vendor_id: int) -> str:
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        return f"Vendor #{vendor_id}"
    city_name = None
    if vendor.city_id:
        city = db.get(City, vendor.city_id)
        city_name = city.name if city else None
    return f"{vendor.business_name} — {city_name}" if city_name else vendor.business_name


def get_or_create_ap_account(db: Session, vendor_id: int) -> VendorApAccount:
    row = db.query(VendorApAccount).filter(VendorApAccount.vendor_id == vendor_id).first()
    if row:
        return row
    row = VendorApAccount(vendor_id=vendor_id, is_open=True)
    db.add(row)
    db.flush()
    return row


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


def receipt_bill_amount(db: Session, receipt_id: int) -> Decimal:
    """Bill amount for AP. actual_ap_amount takes precedence (split-price vendors). Falls back to total_billed_amount."""
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt:
        return Decimal("0")
    if receipt.actual_ap_amount is not None:
        return receipt.actual_ap_amount.quantize(Decimal("0.01"))
    if receipt.total_billed_amount is not None:
        return receipt.total_billed_amount.quantize(Decimal("0.01"))
    lines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt_id).all()
    line_total = sum((ln.billed_amount or Decimal("0") for ln in lines), Decimal("0"))
    # Legacy: only fold additional_charges when no total override was stored
    extra = receipt.additional_charges if receipt.additional_charges else Decimal("0")
    return (line_total + extra).quantize(Decimal("0.01"))


def debit_note_payable_effect(amount: Decimal, note_type: str) -> Decimal:
    """Effect on net payable: negative = pay less, positive = pay more."""
    amt = amount.quantize(Decimal("0.01"))
    if note_type == "item":
        return -amt
    return amt


def receipt_debit_note_total(db: Session, receipt_id: int) -> Decimal:
    notes = db.query(DebitNote).filter(DebitNote.receipt_id == receipt_id).all()
    total = sum((debit_note_payable_effect(n.amount, n.note_type) for n in notes), Decimal("0"))
    return total.quantize(Decimal("0.01"))


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
) -> ApLedgerEntry:
    get_or_create_ap_account(db, vendor_id)
    entry = ApLedgerEntry(
        vendor_id=vendor_id,
        entry_type="payment",
        amount=as_signed_decrease(amount),
        payment_ref=payment_ref,
        payment_receipt_key=payment_receipt_key,
        payment_comment=payment_comment,
        description=description,
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


def vendor_ap_totals(db: Session, vendor_id: int) -> dict:
    rows = db.query(ApLedgerEntry).filter(ApLedgerEntry.vendor_id == vendor_id).all()
    outstanding = sum((r.amount for r in rows), Decimal("0")).quantize(Decimal("0.01"))
    opening_total = sum((r.amount for r in rows if r.entry_type == "opening_balance"), Decimal("0")).quantize(Decimal("0.01"))
    bill_total = sum((r.amount for r in rows if r.entry_type == "bill"), Decimal("0")).quantize(Decimal("0.01"))
    payment_total = Decimal("0")
    for r in rows:
        if r.entry_type == "payment":
            payment_total += mag(r.amount)
        elif r.entry_type == "payment_reversal":
            payment_total -= mag(r.amount)
    payment_total = payment_total.quantize(Decimal("0.01"))
    dn_ids = {r.id for r in rows if r.entry_type == "debit_note"}
    debit_note_net = sum((r.amount for r in rows if r.entry_type == "debit_note"), Decimal("0"))
    debit_note_net += sum(
        (
            r.amount
            for r in rows
            if r.entry_type == "adjustment" and r.reverses_entry_id in dn_ids
        ),
        Decimal("0"),
    )
    debit_note_net = debit_note_net.quantize(Decimal("0.01"))
    return {
        "opening_total": opening_total,
        "bill_total": bill_total,
        "debit_note_total": debit_note_net,
        "payment_total": payment_total,
        "outstanding": outstanding,
        "transaction_count": len(rows),
    }


def get_opening_balance(db: Session, vendor_id: int) -> Optional[ApLedgerEntry]:
    return (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.vendor_id == vendor_id, ApLedgerEntry.entry_type == "opening_balance")
        .order_by(ApLedgerEntry.id.desc())
        .first()
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


def build_ap_ledger(db: Session, vendor_id: int) -> list[dict]:
    from app.services.debit_notes import infer_direction

    entries = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.vendor_id == vendor_id)
        .order_by(ApLedgerEntry.created_at.asc(), ApLedgerEntry.id.asc())
        .all()
    )

    receipt_ids = {e.receipt_id for e in entries if e.receipt_id}
    receipts_by_id: dict[int, StockReceipt] = {}
    rlines_by_receipt: dict[int, list] = {}
    notes_by_receipt: dict[int, list] = {}
    if receipt_ids:
        receipts_by_id = {r.id: r for r in db.query(StockReceipt).filter(StockReceipt.id.in_(receipt_ids)).all()}
        for ln in db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id.in_(receipt_ids)).all():
            rlines_by_receipt.setdefault(ln.receipt_id, []).append(ln)
        for dn in db.query(DebitNote).filter(DebitNote.receipt_id.in_(receipt_ids)).all():
            notes_by_receipt.setdefault(dn.receipt_id, []).append(dn)

    debit_note_ids = {e.debit_note_id for e in entries if e.debit_note_id}
    notes_by_id: dict[int, DebitNote] = {}
    if debit_note_ids:
        # Reuse already-fetched rows where possible to avoid a second round-trip
        have = {n.id for notes in notes_by_receipt.values() for n in notes}
        missing = debit_note_ids - have
        notes_by_id = {n.id: n for notes in notes_by_receipt.values() for n in notes}
        if missing:
            for dn in db.query(DebitNote).filter(DebitNote.id.in_(missing)).all():
                notes_by_id[dn.id] = dn

    def _bill_amount(receipt: StockReceipt, rlines: list) -> Decimal:
        if receipt.actual_ap_amount is not None:
            return receipt.actual_ap_amount.quantize(Decimal("0.01"))
        if receipt.total_billed_amount is not None:
            return receipt.total_billed_amount.quantize(Decimal("0.01"))
        line_total = sum((ln.billed_amount or Decimal("0") for ln in rlines), Decimal("0"))
        extra = receipt.additional_charges if receipt.additional_charges else Decimal("0")
        return (line_total + extra).quantize(Decimal("0.01"))

    def _debit_note_total(rid: int) -> Decimal:
        total = sum(
            (debit_note_payable_effect(n.amount, n.note_type) for n in notes_by_receipt.get(rid, [])),
            Decimal("0"),
        )
        return total.quantize(Decimal("0.01"))

    balance = Decimal("0")
    out = []
    for e in entries:
        balance = (balance + e.amount).quantize(Decimal("0.01"))
        receipt = receipts_by_id.get(e.receipt_id) if e.receipt_id else None
        rlines = rlines_by_receipt.get(e.receipt_id, []) if e.receipt_id else []
        bill_amount = receipt_debit_total = net_payable = None
        if e.entry_type == "bill" and e.receipt_id:
            bill_amount = _bill_amount(receipt, rlines)
            debit_note_total = _debit_note_total(e.receipt_id)
            net_payable = (bill_amount + debit_note_total).quantize(Decimal("0.01"))
            receipt_debit_total = debit_note_total
        details: dict = {}
        if e.receipt_id and receipt:
            details["lines"] = [
                {
                    "our_product_id": ln.our_product_id,
                    "quantity_received": ln.quantity_received,
                    "quantity_billed": ln.quantity_billed,
                    "billed_amount": format(ln.billed_amount, "f"),
                }
                for ln in rlines
            ]
            if receipt.additional_charges:
                details["additional_charges"] = format(receipt.additional_charges, "f")
            dns = notes_by_receipt.get(e.receipt_id, [])
            if dns:
                details["debit_notes"] = [
                    {
                        "id": dn.id,
                        "note_type": dn.note_type,
                        "direction": dn.direction or infer_direction(dn.note_type, dn.quantity, dn.amount),
                        "our_product_id": dn.our_product_id,
                        "quantity": dn.quantity,
                        "amount": format(dn.amount, "f"),
                        "payable_effect": format(debit_note_payable_effect(dn.amount, dn.note_type), "f"),
                        "notes": dn.notes,
                    }
                    for dn in dns
                ]
        if e.debit_note_id:
            dn = notes_by_id.get(e.debit_note_id)
            if dn:
                details["debit_note"] = {
                    "id": dn.id,
                    "note_type": dn.note_type,
                    "direction": dn.direction or infer_direction(dn.note_type, dn.quantity, dn.amount),
                    "our_product_id": dn.our_product_id,
                    "quantity": dn.quantity,
                    "unit_price": format(dn.unit_price, "f") if dn.unit_price is not None else None,
                    "amount": format(dn.amount, "f"),
                    "payable_effect": format(debit_note_payable_effect(dn.amount, dn.note_type), "f"),
                    "notes": dn.notes,
                }
        out.append(
            {
                "id": e.id,
                "entry_type": e.entry_type,
                "amount": format(abs(e.amount), "f"),
                "signed_amount": format(e.amount, "f"),
                "running_balance": format(balance, "f"),
                "description": e.description,
                "receipt_id": e.receipt_id,
                "debit_note_id": e.debit_note_id,
                "payment_ref": e.payment_ref,
                "payment_receipt_url": presigned_url(e.payment_receipt_key) if e.payment_receipt_key else None,
                "payment_comment": e.payment_comment,
                "bill_number": receipt.bill_number if receipt else None,
                "bill_amount": format(bill_amount, "f") if bill_amount is not None else None,
                "debit_note_total": format(receipt_debit_total, "f") if receipt_debit_total is not None else None,
                "net_payable": format(net_payable, "f") if net_payable is not None else None,
                "created_by_name": e.created_by_name,
                "created_at": e.created_at,
                "value_date": e.value_date.isoformat() if e.value_date else None,
                "reverses_entry_id": e.reverses_entry_id,
                "details": details,
            }
        )
    out.reverse()
    return out


def list_ap_vendors(db: Session) -> list[dict]:
    """One aggregate query + vendor/city joins — no per-vendor N+1."""
    from sqlalchemy import case, func

    opening_sum = func.coalesce(
        func.sum(case((ApLedgerEntry.entry_type == "opening_balance", ApLedgerEntry.amount), else_=0)),
        0,
    )
    bill_sum = func.coalesce(
        func.sum(case((ApLedgerEntry.entry_type == "bill", ApLedgerEntry.amount), else_=0)),
        0,
    )
    dn_sum = func.coalesce(
        func.sum(case((ApLedgerEntry.entry_type == "debit_note", ApLedgerEntry.amount), else_=0)),
        0,
    )
    payment_sum = func.coalesce(
        func.sum(
            case(
                (ApLedgerEntry.entry_type.in_(("payment", "payment_reversal")), ApLedgerEntry.amount),
                else_=0,
            )
        ),
        0,
    )
    outstanding_sum = func.coalesce(func.sum(ApLedgerEntry.amount), 0)
    agg_rows = (
        db.query(
            ApLedgerEntry.vendor_id,
            func.count(ApLedgerEntry.id),
            opening_sum,
            bill_sum,
            dn_sum,
            payment_sum,
            outstanding_sum,
        )
        .group_by(ApLedgerEntry.vendor_id)
        .all()
    )
    if not agg_rows:
        return []

    by_id = {
        int(vid): {
            "txn_count": int(txn or 0),
            "opening_total": Decimal(str(op or 0)).quantize(Decimal("0.01")),
            "bill_total": Decimal(str(bill or 0)).quantize(Decimal("0.01")),
            "debit_note_total": Decimal(str(dn or 0)).quantize(Decimal("0.01")),
            "payment_total": mag(pay),
            "outstanding": Decimal(str(out or 0)).quantize(Decimal("0.01")),
        }
        for vid, txn, op, bill, dn, pay, out in agg_rows
    }
    vendors = (
        db.query(Vendor)
        .filter(Vendor.id.in_(list(by_id.keys())), Vendor.deleted_at.is_(None))
        .all()
    )
    city_ids = {v.city_id for v in vendors if v.city_id}
    cities = {
        c.id: c.name
        for c in (db.query(City).filter(City.id.in_(city_ids)).all() if city_ids else [])
    }
    accounts = {
        a.vendor_id: a
        for a in db.query(VendorApAccount).filter(VendorApAccount.vendor_id.in_(list(by_id.keys()))).all()
    }
    latest_opening: dict[int, ApLedgerEntry] = {}
    for e in (
        db.query(ApLedgerEntry)
        .filter(
            ApLedgerEntry.vendor_id.in_(list(by_id.keys())),
            ApLedgerEntry.entry_type == "opening_balance",
        )
        .all()
    ):
        prev = latest_opening.get(e.vendor_id)
        if prev is None or e.id > prev.id:
            latest_opening[e.vendor_id] = e

    result = []
    for vendor in vendors:
        t = by_id.get(vendor.id)
        if not t or t["txn_count"] == 0:
            continue
        city_name = cities.get(vendor.city_id) if vendor.city_id else None
        label = f"{vendor.business_name} — {city_name}" if city_name else vendor.business_name
        opening = latest_opening.get(vendor.id)
        account = accounts.get(vendor.id)
        result.append(
            {
                "vendor_id": vendor.id,
                "vendor_label": label,
                "business_name": vendor.business_name,
                "person_name": vendor.person_name,
                "alias": vendor.alias,
                "phone": vendor.phone,
                "city_name": city_name,
                "outstanding": format(t["outstanding"], "f"),
                "opening_total": format(t["opening_total"], "f"),
                "opening_as_on": opening.value_date.isoformat() if opening and opening.value_date else None,
                "bill_total": format(t["bill_total"], "f"),
                "debit_note_total": format(t["debit_note_total"], "f"),
                "payment_total": format(t["payment_total"], "f"),
                "transaction_count": t["txn_count"],
                "updated_at": account.updated_at if account else None,
            }
        )
    result.sort(key=lambda x: Decimal(x["outstanding"]), reverse=True)
    return result


def ap_dues_total(db: Session) -> dict:
    """Canonical Pay-vendors total — same number Home, Finance pulse, and Pay tab must show.

    One SQL join+group — outstanding > 0 only.
    """
    from sqlalchemy import text

    rows = db.execute(
        text(
            """
            SELECT v.id, v.business_name, ci.name AS city_name, SUM(e.amount) AS outstanding
            FROM jc_ap_ledger_entries e
            JOIN jc_vendors v ON v.id = e.vendor_id AND v.deleted_at IS NULL
            LEFT JOIN jc_cities ci ON ci.id = v.city_id
            GROUP BY v.id, v.business_name, ci.name
            HAVING SUM(e.amount) > 0
            ORDER BY SUM(e.amount) DESC
            """
        )
    ).all()
    due = [
        {
            "vendor_id": int(r.id),
            "vendor_label": f"{r.business_name} — {r.city_name}" if r.city_name else r.business_name,
            "outstanding": format(Decimal(str(r.outstanding or 0)).quantize(Decimal("0.01")), "f"),
        }
        for r in rows
    ]
    total = sum((Decimal(v["outstanding"]) for v in due), Decimal("0")).quantize(Decimal("0.01"))
    return {"total": total, "count": len(due), "parties": due}


def build_ap_statement(db: Session, vendor_id: int) -> dict:
    """Bill-wise statement: bills with nested debit notes + separate payments."""
    entries = build_ap_ledger(db, vendor_id)  # newest first
    chronological = list(reversed(entries))
    bills_by_receipt: dict[int, dict] = {}
    payments: list[dict] = []
    reversed_ids = {
        e["reverses_entry_id"]
        for e in chronological
        if e.get("entry_type") == "payment_reversal" and e.get("reverses_entry_id")
    }
    for e in chronological:
        if e["entry_type"] == "bill" and e.get("receipt_id"):
            rid = e["receipt_id"]
            bills_by_receipt[rid] = {
                "receipt_id": rid,
                "ledger_entry_id": e["id"],
                "bill_number": e.get("bill_number"),
                "bill_amount": e.get("bill_amount") or e.get("signed_amount"),
                "debit_note_total": e.get("debit_note_total") or "0.00",
                "net_payable": e.get("net_payable") or e.get("signed_amount"),
                "description": e["description"],
                "created_at": e["created_at"],
                "created_by_name": e["created_by_name"],
                "lines": (e.get("details") or {}).get("lines") or [],
                "debit_notes": [],
                "running_balance_after": e["running_balance"],
            }
            # Prefer nested DNs from bill details (may be incomplete if DNs added later)
            for dn in (e.get("details") or {}).get("debit_notes") or []:
                bills_by_receipt[rid]["debit_notes"].append({
                    **dn,
                    "entry_id": None,
                    "created_at": None,
                    "description": None,
                })
        elif e["entry_type"] == "debit_note" and e.get("receipt_id"):
            rid = e["receipt_id"]
            if rid not in bills_by_receipt:
                bills_by_receipt[rid] = {
                    "receipt_id": rid,
                    "ledger_entry_id": None,
                    "bill_number": e.get("bill_number"),
                    "bill_amount": "0.00",
                    "debit_note_total": "0.00",
                    "net_payable": "0.00",
                    "description": f"Bill {e.get('bill_number') or rid}",
                    "created_at": e["created_at"],
                    "created_by_name": e["created_by_name"],
                    "lines": [],
                    "debit_notes": [],
                    "running_balance_after": e["running_balance"],
                }
            dn = (e.get("details") or {}).get("debit_note") or {}
            # Replace placeholder from bill details if same id
            existing = bills_by_receipt[rid]["debit_notes"]
            replaced = False
            if dn.get("id"):
                for i, old in enumerate(existing):
                    if old.get("id") == dn["id"]:
                        existing[i] = {
                            **dn,
                            "entry_id": e["id"],
                            "created_at": e["created_at"],
                            "description": e["description"],
                            "payable_effect": e["signed_amount"],
                        }
                        replaced = True
                        break
            if not replaced:
                existing.append({
                    **dn,
                    "entry_id": e["id"],
                    "created_at": e["created_at"],
                    "description": e["description"],
                    "payable_effect": e["signed_amount"],
                })
            bills_by_receipt[rid]["running_balance_after"] = e["running_balance"]
        elif e["entry_type"] == "payment":
            payments.append({
                "id": e["id"],
                "amount": e["amount"],
                "signed_amount": e["signed_amount"],
                "payment_ref": e.get("payment_ref"),
                "payment_comment": e.get("payment_comment"),
                "payment_receipt_url": e.get("payment_receipt_url"),
                "description": e["description"],
                "created_at": e["created_at"],
                "created_by_name": e["created_by_name"],
                "running_balance_after": e["running_balance"],
                "reversed": e["id"] in reversed_ids,
            })

    # Refresh DN totals / net from nested notes
    for bill in bills_by_receipt.values():
        # sum() of empty iterable returns 0 (int) — keep Decimal for .quantize
        dn_sum = sum(
            (Decimal(str(d.get("payable_effect") or "0")) for d in bill["debit_notes"]),
            Decimal("0"),
        )
        bill["debit_note_total"] = format(dn_sum.quantize(Decimal("0.01")), "f")
        bill_amt = Decimal(str(bill.get("bill_amount") or "0"))
        bill["net_payable"] = format((bill_amt + dn_sum).quantize(Decimal("0.01")), "f")

    bills = sorted(bills_by_receipt.values(), key=lambda b: b["created_at"] or "", reverse=True)
    payments.reverse()  # newest first
    totals = vendor_ap_totals(db, vendor_id)
    return {
        "bills": bills,
        "payments": payments,
        "entries": entries,
        **{k: format(v, "f") if isinstance(v, Decimal) else v for k, v in totals.items()},
    }
