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

from app.services.ap_ledger_parts.sync_receipt_extra_cash_ledger import debit_note_payable_effect

def build_ap_ledger(db: Session, vendor_id: int, *, auth: Optional[AuthContext] = None) -> list[dict]:
    from app.services.debit_notes import infer_direction

    entries = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.vendor_id == vendor_id, ApLedgerEntry.deleted_at.is_(None))
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
        for dn in db.query(DebitNote).filter(
            DebitNote.receipt_id.in_(receipt_ids), DebitNote.deleted_at.is_(None)
        ).all():
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

    product_ids = {
        ln.catalog_product_id
        for lines in rlines_by_receipt.values()
        for ln in lines
        if ln.catalog_product_id
    }
    product_ids.update(dn.catalog_product_id for dn in notes_by_id.values() if dn.catalog_product_id)
    product_ids.update(
        dn.catalog_product_id
        for notes in notes_by_receipt.values()
        for dn in notes
        if dn.catalog_product_id
    )
    product_names = {
        pid: name
        for pid, name in db.query(CatalogProduct.id, CatalogProduct.our_product_id)
        .filter(CatalogProduct.id.in_(product_ids))
        .all()
    } if product_ids else {}
    vendor = db.get(Vendor, vendor_id)
    vendor_party = vendor.business_name if vendor else f"Vendor #{vendor_id}"

    def _doc_status(row) -> str:
        if row is None:
            return "open"
        if getattr(row, "deleted_at", None):
            return "voided"
        if getattr(row, "cancelled_at", None) or getattr(row, "status", None) == "cancelled":
            return "cancelled"
        return "open"

    def _note_display_date(dn: DebitNote):
        receipt = receipts_by_id.get(dn.receipt_id) if dn.receipt_id else None
        if receipt is not None and receipt.billed_at:
            return receipt.billed_at
        return dn.created_at

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
                    "our_product_id": product_names.get(ln.catalog_product_id) or ln.our_product_id,
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
                details["debit_notes"] = []
                for dn in dns:
                    details["debit_notes"].append(
                        {
                            "id": dn.id,
                            "note_type": dn.note_type,
                            "direction": dn.direction or infer_direction(dn.note_type, dn.quantity, dn.amount),
                            "our_product_id": product_names.get(dn.catalog_product_id) or dn.our_product_id,
                            "quantity": dn.quantity,
                            "amount": format(dn.amount, "f"),
                            "payable_effect": format(debit_note_payable_effect(dn.amount, dn.note_type), "f"),
                            "notes": dn.notes,
                            "display_date": _note_display_date(dn),
                        }
                    )
        if e.debit_note_id:
            dn = notes_by_id.get(e.debit_note_id)
            if dn:
                details["debit_note"] = {
                    "id": dn.id,
                    "note_type": dn.note_type,
                    "direction": dn.direction or infer_direction(dn.note_type, dn.quantity, dn.amount),
                    "our_product_id": product_names.get(dn.catalog_product_id) or dn.our_product_id,
                    "quantity": dn.quantity,
                    # unit_price is the catalog buying_price at receive time — a cost hint,
                    # not the bill amount owed. Redact for AP-visibility-only staff.
                    "unit_price": hide_cost(format(dn.unit_price, "f") if dn.unit_price is not None else None, auth),
                    "amount": format(dn.amount, "f"),
                    "payable_effect": format(debit_note_payable_effect(dn.amount, dn.note_type), "f"),
                    "notes": dn.notes,
                    "display_date": _note_display_date(dn),
                }
        payment_party = None
        display_date = e.value_date or e.created_at
        display_name = e.payment_ref or e.description
        status = "open"
        if e.entry_type == "payment":
            payment_party = vendor_party
            display_name = e.payment_ref or vendor_party or e.description
        elif e.entry_type == "bill" and receipt and receipt.bill_status == "billed":
            display_date = receipt.billed_at or receipt.received_at or display_date
            display_name = receipt.bill_number or f"Bill #{receipt.id}"
            status = _doc_status(receipt)
        elif e.entry_type == "debit_note" and e.debit_note_id:
            dn = notes_by_id.get(e.debit_note_id)
            if dn:
                display_date = _note_display_date(dn)
                display_name = f"Debit note #{dn.id}"
                status = _doc_status(dn)
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
                "payment_mode": e.payment_mode,
                "party_name": payment_party,
                "display_date": display_date,
                "display_name": display_name,
                "status": status,
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

def build_ap_statement(db: Session, vendor_id: int, *, auth: Optional[AuthContext] = None) -> dict:
    """Bill-wise statement: bills with nested debit notes + separate payments."""
    entries = build_ap_ledger(db, vendor_id, auth=auth)  # newest first
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
                "display_date": e.get("display_date"),
                "display_name": e.get("display_name") or e.get("bill_number"),
                "status": e.get("status"),
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
                            "display_date": dn.get("display_date") or e.get("display_date"),
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
                    "display_date": dn.get("display_date") or e.get("display_date"),
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
                "payment_mode": e.get("payment_mode"),
                "description": e["description"],
                "created_at": e["created_at"],
                "value_date": e.get("value_date"),
                "display_date": e.get("display_date"),
                "display_name": e.get("display_name"),
                "status": e.get("status"),
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

def vendor_ap_totals(db: Session, vendor_id: int) -> dict:
    rows = db.query(ApLedgerEntry).filter(
        ApLedgerEntry.vendor_id == vendor_id, ApLedgerEntry.deleted_at.is_(None)
    ).all()
    outstanding = sum((r.amount for r in rows), Decimal("0")).quantize(Decimal("0.01"))
    opening_total = sum((r.amount for r in rows if r.entry_type == "opening_balance"), Decimal("0")).quantize(Decimal("0.01"))
    bill_ids = {r.id for r in rows if r.entry_type == "bill"}
    bill_total = sum((r.amount for r in rows if r.entry_type == "bill"), Decimal("0"))
    # A bill edit after receipt (e.g. correcting GST/total once the vendor's real invoice
    # arrives) posts a compensating `adjustment` row reversing the original `bill` entry
    # rather than mutating it, to preserve money history. Fold those in here too, or this
    # "Total bills" subtotal quietly stops matching `outstanding` after any such edit.
    bill_total += sum(
        (r.amount for r in rows if r.entry_type == "adjustment" and r.reverses_entry_id in bill_ids),
        Decimal("0"),
    )
    bill_total = bill_total.quantize(Decimal("0.01"))
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

