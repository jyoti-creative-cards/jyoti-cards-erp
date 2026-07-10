from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.accounts_payable import ApLedgerEntry, VendorApAccount
from app.models.debit_note import DebitNote
from app.models.stock import StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.models.city import City
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


def receipt_bill_amount(db: Session, receipt_id: int) -> Decimal:
    """Bill amount for AP. Prefer total_billed_amount (full bill). Do not add additional_charges on top."""
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt:
        return Decimal("0")
    if receipt.total_billed_amount is not None:
        return receipt.total_billed_amount.quantize(Decimal("0.01"))
    lines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt_id).all()
    line_total = sum((ln.billed_amount or Decimal("0")) for ln in lines)
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
) -> ApLedgerEntry:
    get_or_create_ap_account(db, vendor_id)
    entry = ApLedgerEntry(
        vendor_id=vendor_id,
        entry_type="bill",
        amount=amount.quantize(Decimal("0.01")),
        receipt_id=receipt_id,
        description=description,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
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
        amount=(-amount).quantize(Decimal("0.01")),
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
    bill_total = sum((r.amount for r in rows if r.entry_type == "bill"), Decimal("0")).quantize(Decimal("0.01"))
    payment_total = sum((abs(r.amount) for r in rows if r.entry_type == "payment"), Decimal("0")).quantize(Decimal("0.01"))
    debit_note_net = sum((r.amount for r in rows if r.entry_type == "debit_note"), Decimal("0")).quantize(Decimal("0.01"))
    return {
        "bill_total": bill_total,
        "debit_note_total": debit_note_net,
        "payment_total": payment_total,
        "outstanding": outstanding,
        "transaction_count": len(rows),
    }


def build_ap_ledger(db: Session, vendor_id: int) -> list[dict]:
    entries = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.vendor_id == vendor_id)
        .order_by(ApLedgerEntry.created_at.asc(), ApLedgerEntry.id.asc())
        .all()
    )
    balance = Decimal("0")
    out = []
    for e in entries:
        balance = (balance + e.amount).quantize(Decimal("0.01"))
        receipt = db.get(StockReceipt, e.receipt_id) if e.receipt_id else None
        bill_amount = receipt_debit_total = net_payable = None
        if e.entry_type == "bill" and e.receipt_id:
            bill_amount = receipt_bill_amount(db, e.receipt_id)
            debit_note_total = receipt_debit_note_total(db, e.receipt_id)
            net_payable = (bill_amount + debit_note_total).quantize(Decimal("0.01"))
            receipt_debit_total = debit_note_total
        details: dict = {}
        if e.receipt_id and receipt:
            rlines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == e.receipt_id).all()
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
            dns = db.query(DebitNote).filter(DebitNote.receipt_id == e.receipt_id).all()
            if dns:
                from app.services.debit_notes import infer_direction
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
            dn = db.get(DebitNote, e.debit_note_id)
            if dn:
                from app.services.debit_notes import infer_direction
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
                "details": details,
            }
        )
    out.reverse()
    return out


def list_ap_vendors(db: Session) -> list[dict]:
    vendor_ids = {vid for (vid,) in db.query(ApLedgerEntry.vendor_id).distinct().all()}
    if not vendor_ids:
        return []
    result = []
    for vid in vendor_ids:
        totals = vendor_ap_totals(db, vid)
        if totals["transaction_count"] == 0:
            continue
        account = db.query(VendorApAccount).filter(VendorApAccount.vendor_id == vid).first()
        result.append(
            {
                "vendor_id": vid,
                "vendor_label": _vendor_label(db, vid),
                "outstanding": format(totals["outstanding"], "f"),
                "bill_total": format(totals["bill_total"], "f"),
                "debit_note_total": format(totals["debit_note_total"], "f"),
                "payment_total": format(totals["payment_total"], "f"),
                "transaction_count": totals["transaction_count"],
                "updated_at": account.updated_at if account else None,
            }
        )
    result.sort(key=lambda x: Decimal(x["outstanding"]), reverse=True)
    return result


def build_ap_statement(db: Session, vendor_id: int) -> dict:
    """Bill-wise statement: bills with nested debit notes + separate payments."""
    entries = build_ap_ledger(db, vendor_id)  # newest first
    chronological = list(reversed(entries))
    bills_by_receipt: dict[int, dict] = {}
    payments: list[dict] = []
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
            })

    # Refresh DN totals / net from nested notes
    for bill in bills_by_receipt.values():
        dn_sum = sum(Decimal(d.get("payable_effect") or "0") for d in bill["debit_notes"])
        bill["debit_note_total"] = format(dn_sum.quantize(Decimal("0.01")), "f")
        bill_amt = Decimal(bill.get("bill_amount") or "0")
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
