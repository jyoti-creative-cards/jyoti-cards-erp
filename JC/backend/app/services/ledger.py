from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.stock import StockReceipt, StockReceiptLine
from app.models.debit_note import DebitNote
from app.models.accounts_payable import ApLedgerEntry
from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement
from app.services.ap_ledger import receipt_bill_amount, receipt_debit_note_total
from app.schemas.ledger import EntityLedgerEntry, LedgerLineDetail
from app.services.storage import presigned_url


def _fmt_amount(val: Optional[Decimal]) -> Optional[str]:
    if val is None:
        return None
    return format(val, "f")


def _actor_fields(actor_name: str, actor_type: str, show_actor: bool) -> dict:
    if not show_actor:
        return {"actor_name": None, "actor_type": None}
    return {"actor_name": actor_name, "actor_type": actor_type}


def build_vendor_ledger(db: Session, vendor_id: int, *, show_actor: bool = True, include_ap: bool = True) -> List[EntityLedgerEntry]:
    entries: list[tuple[datetime, EntityLedgerEntry]] = []

    placements = (
        db.query(VendorOrderPlacement, VendorOrder)
        .join(VendorOrder, VendorOrderPlacement.vendor_order_id == VendorOrder.id)
        .filter(VendorOrder.vendor_id == vendor_id)
        .order_by(VendorOrderPlacement.placed_at.desc())
        .all()
    )
    for placement, order in placements:
        lines = db.query(VendorOrderLine).filter(VendorOrderLine.placement_id == placement.id).all()
        line_details = [
            LedgerLineDetail(
                our_product_id=ln.our_product_id,
                quantity=ln.quantity,
                quantity_remaining=ln.quantity if order.bucket == "placed" else None,
                quantity_received=ln.quantity if order.bucket == "billed" else None,
                quantity_billed=ln.quantity_billed,
                billed_amount=_fmt_amount(ln.billed_amount),
                buying_price=format(ln.buying_price, "f"),
            )
            for ln in lines
        ]
        if order.bucket == "placed":
            title = "Placed order"
            event_type = "order_placed"
            summary = ", ".join(f"{ln.our_product_id} × {ln.quantity}" for ln in lines[:8])
        elif order.bucket == "cancelled":
            title = "Cancelled placement"
            event_type = "order_cancelled"
            summary = ", ".join(f"{ln.our_product_id} × {ln.quantity}" for ln in lines[:8])
        else:
            title = "Received bill / shipment"
            event_type = "stock_received"
            summary = ", ".join(
                f"{ln.our_product_id} recv {ln.quantity}"
                + (f" bill {ln.quantity_billed}" if ln.quantity_billed else "")
                for ln in lines[:8]
            )
        receipt = (
            db.query(StockReceipt)
            .filter(StockReceipt.billed_placement_id == placement.id)
            .first()
        )
        details = {
            "bucket": order.bucket,
            "placement_id": placement.id,
            "vendor_order_id": placement.vendor_order_id,
            "lines": [l.model_dump() for l in line_details],
        }
        if receipt:
            bill_amt = receipt_bill_amount(db, receipt.id)
            dn_total = receipt_debit_note_total(db, receipt.id)
            details.update(
                {
                    "receipt_id": receipt.id,
                    "bill_number": receipt.bill_number,
                    "bill_amount": format(bill_amt, "f"),
                    "debit_note_total": format(dn_total, "f"),
                    "net_payable": format(bill_amt + dn_total, "f"),
                    "additional_charges": _fmt_amount(receipt.additional_charges),
                    "bill_file_url": presigned_url(receipt.bill_file_key) if receipt.bill_file_key else None,
                    "received_at": receipt.received_at.isoformat(),
                }
            )
        entries.append(
            (
                placement.placed_at,
                EntityLedgerEntry(
                    id=f"placement-{placement.id}",
                    event_type=event_type,
                    title=title,
                    summary=summary or "—",
                    occurred_at=placement.placed_at,
                    **_actor_fields(placement.placed_by_name, placement.placed_by_type, show_actor),
                    details=details,
                ),
            )
        )

    for note in db.query(DebitNote).filter(DebitNote.vendor_id == vendor_id).order_by(DebitNote.created_at.desc()).all():
        receipt = db.get(StockReceipt, note.receipt_id)
        summary = (
            f"{note.our_product_id} × {note.quantity} = ₹{note.amount}"
            if note.note_type == "item"
            else f"Value debit ₹{note.amount}"
        )
        entries.append(
            (
                note.created_at,
                EntityLedgerEntry(
                    id=f"debit-note-{note.id}",
                    event_type="debit_note",
                    title="Debit note",
                    summary=summary,
                    occurred_at=note.created_at,
                    **_actor_fields(note.created_by_name, note.created_by_type, show_actor),
                    details={
                        "debit_note_id": note.id,
                        "receipt_id": note.receipt_id,
                        "bill_number": receipt.bill_number if receipt else None,
                        "note_type": note.note_type,
                        "our_product_id": note.our_product_id,
                        "quantity": note.quantity,
                        "amount": format(note.amount, "f"),
                        "notes": note.notes,
                    },
                ),
            )
        )

    ap_entries = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.vendor_id == vendor_id, ApLedgerEntry.entry_type == "payment")
        .order_by(ApLedgerEntry.created_at.desc())
        .all()
    ) if include_ap else []
    for ap in ap_entries:
        entries.append(
            (
                ap.created_at,
                EntityLedgerEntry(
                    id=f"ap-payment-{ap.id}",
                    event_type="ap_payment",
                    title="AP payment",
                    summary=f"₹{abs(ap.amount)} — {ap.payment_ref or 'payment'}",
                    occurred_at=ap.created_at,
                    **_actor_fields(ap.created_by_name, ap.created_by_type, show_actor),
                    details={
                        "payment_ref": ap.payment_ref,
                        "amount": format(abs(ap.amount), "f"),
                        "payment_receipt_url": presigned_url(ap.payment_receipt_key) if ap.payment_receipt_key else None,
                        "comment": ap.payment_comment,
                    },
                ),
            )
        )

    receipts = (
        db.query(StockReceipt)
        .filter(StockReceipt.vendor_id == vendor_id)
        .order_by(StockReceipt.received_at.desc())
        .all()
    )
    seen_placement_ids = {e[1].details.get("placement_id") for e in entries if e[1].details.get("placement_id")}
    for receipt in receipts:
        if receipt.billed_placement_id and receipt.billed_placement_id in seen_placement_ids:
            continue
        rlines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).all()
        line_details = [
            LedgerLineDetail(
                our_product_id=ln.our_product_id,
                quantity_received=ln.quantity_received,
                quantity_billed=ln.quantity_billed,
                billed_amount=_fmt_amount(ln.billed_amount),
                buying_price=format(ln.buying_price, "f"),
            )
            for ln in rlines
        ]
        summary = ", ".join(f"{ln.our_product_id} +{ln.quantity_received}" for ln in rlines[:8])
        entries.append(
            (
                receipt.received_at,
                EntityLedgerEntry(
                    id=f"receipt-{receipt.id}",
                    event_type="stock_received",
                    title="Stock receipt",
                    summary=summary or "—",
                    occurred_at=receipt.received_at,
                    **_actor_fields(receipt.received_by_name, receipt.received_by_type, show_actor),
                    details={
                        "receipt_id": receipt.id,
                        "bill_number": receipt.bill_number,
                        "additional_charges": _fmt_amount(receipt.additional_charges),
                        "bill_file_url": presigned_url(receipt.bill_file_key) if receipt.bill_file_key else None,
                        "lines": [l.model_dump() for l in line_details],
                    },
                ),
            )
        )

    entries.sort(key=lambda x: x[0], reverse=True)
    return [e[1] for e in entries]


def build_customer_ledger(db: Session, customer_id: int, *, show_actor: bool = True) -> List[EntityLedgerEntry]:
    """Ready for customer orders — returns empty until order module exists."""
    return []
