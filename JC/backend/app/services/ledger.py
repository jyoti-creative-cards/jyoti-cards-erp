from __future__ import annotations

from collections import defaultdict
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
        .filter(VendorOrder.vendor_id == vendor_id, VendorOrder.bucket.in_(("placed", "cancelled")))
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
                quantity_billed=ln.quantity_billed,
                billed_amount=_fmt_amount(ln.billed_amount),
                buying_price=format(ln.buying_price, "f"),
            )
            for ln in lines
        ]
        if order.bucket == "placed":
            title = "Placed order"
            event_type = "order_placed"
        else:
            title = "Cancelled placement"
            event_type = "order_cancelled"
        summary = ", ".join(f"{ln.our_product_id} × {ln.quantity}" for ln in lines[:8])
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
                    details={
                        "bucket": order.bucket,
                        "placement_id": placement.id,
                        "vendor_order_id": placement.vendor_order_id,
                        "lines": [l.model_dump() for l in line_details],
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
    for receipt in receipts:
        rlines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).all()
        line_details = [
            LedgerLineDetail(
                our_product_id=ln.our_product_id, quantity_received=ln.quantity_received,
                quantity_billed=ln.quantity_billed, billed_amount=_fmt_amount(ln.billed_amount),
                buying_price=format(ln.buying_price, "f"),
            )
            for ln in rlines
        ]
        summary = ", ".join(f"{ln.our_product_id} +{ln.quantity_received}" for ln in rlines[:8]) or "—"
        entries.append((
            receipt.received_at,
            EntityLedgerEntry(
                id=f"receipt-{receipt.id}", event_type="stock_received", title="Stock receipt", summary=summary,
                occurred_at=receipt.received_at,
                **_actor_fields(receipt.received_by_name, receipt.received_by_type, show_actor),
                details={
                    "receipt_id": receipt.id, "order_receipt_number": receipt.order_receipt_number,
                    "expected_bill_amount": _fmt_amount(receipt.expected_bill_amount), "lines": [l.model_dump() for l in line_details],
                },
            ),
        ))
        if receipt.bill_status == "billed":
            bill_amt = receipt_bill_amount(db, receipt.id)
            dn_total = receipt_debit_note_total(db, receipt.id)
            entries.append((
                receipt.billed_at or receipt.received_at,
                EntityLedgerEntry(
                    id=f"bill-{receipt.id}", event_type="vendor_bill", title="Bill",
                    summary=f"{receipt.bill_number or receipt.id} — ₹{bill_amt}", occurred_at=receipt.billed_at or receipt.received_at,
                    **_actor_fields(receipt.received_by_name, receipt.received_by_type, show_actor),
                    details={
                        "receipt_id": receipt.id, "bill_number": receipt.bill_number,
                        "bill_amount": format(bill_amt, "f"), "debit_note_total": format(dn_total, "f"),
                        "net_payable": format(bill_amt + dn_total, "f"),
                        "additional_charges": _fmt_amount(receipt.additional_charges),
                        "bill_file_url": presigned_url(receipt.bill_file_key) if receipt.bill_file_key else None,
                        "lines": [l.model_dump() for l in line_details],
                    },
                ),
            ))

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
    reversed_ap_ids = set()
    if include_ap and ap_entries:
        rev_rows = (
            db.query(ApLedgerEntry.reverses_entry_id)
            .filter(
                ApLedgerEntry.vendor_id == vendor_id,
                ApLedgerEntry.entry_type == "payment_reversal",
                ApLedgerEntry.reverses_entry_id.isnot(None),
            )
            .all()
        )
        reversed_ap_ids = {r[0] for r in rev_rows if r[0]}
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
                        "ledger_entry_id": ap.id,
                        "payment_ref": ap.payment_ref,
                        "amount": format(abs(ap.amount), "f"),
                        "payment_receipt_url": presigned_url(ap.payment_receipt_key) if ap.payment_receipt_key else None,
                        "comment": ap.payment_comment,
                        "reversed": ap.id in reversed_ap_ids,
                    },
                ),
            )
        )

    entries.sort(key=lambda x: x[0], reverse=True)
    return [e[1] for e in entries]


def build_customer_ledger(db: Session, customer_id: int, *, show_actor: bool = True) -> List[EntityLedgerEntry]:
    """Orders placed, bills sold, payments collected, returns — full customer activity."""
    from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
    from app.models.customer_bill import CustomerBill, CustomerBillLine
    from app.models.customer_return import CustomerReturn, CustomerReturnLine
    from app.models.accounts_receivable import ArLedgerEntry

    entries: list[tuple[datetime, EntityLedgerEntry]] = []

    placements = (
        db.query(CustomerOrderPlacement, CustomerOrder)
        .join(CustomerOrder, CustomerOrderPlacement.customer_order_id == CustomerOrder.id)
        .filter(CustomerOrder.customer_id == customer_id)
        .order_by(CustomerOrderPlacement.placed_at.desc())
        .all()
    )
    placement_ids = [p.id for p, _ in placements]
    olines_by: dict[int, list] = defaultdict(list)
    if placement_ids:
        for ln in db.query(CustomerOrderLine).filter(CustomerOrderLine.placement_id.in_(placement_ids)).all():
            olines_by[ln.placement_id].append(ln)
    for placement, order in placements:
        lines = olines_by.get(placement.id) or []
        line_details = [
            LedgerLineDetail(
                our_product_id=ln.our_product_id,
                quantity=ln.quantity,
                quantity_billed=ln.quantity_billed,
                buying_price=format(ln.unit_price, "f"),
                unit_price=format(ln.unit_price, "f"),
                selling_price=format(ln.unit_price, "f"),
            )
            for ln in lines
        ]
        cancelled = placement.status == "cancelled" or order.bucket == "cancelled"
        event_type = "order_cancelled" if cancelled else "order_placed"
        title = "Cancelled order" if cancelled else "Order placed"
        summary = ", ".join(f"{ln.our_product_id} × {ln.quantity}" for ln in lines[:8]) or "—"
        entries.append(
            (
                placement.placed_at,
                EntityLedgerEntry(
                    id=f"co-placement-{placement.id}",
                    event_type=event_type,
                    title=title,
                    summary=summary,
                    occurred_at=placement.placed_at,
                    **_actor_fields("—", "system", show_actor),
                    details={
                        "bucket": order.bucket,
                        "placement_id": placement.id,
                        "customer_order_id": order.id,
                        "customer_id": customer_id,
                        "customer_notes": placement.customer_notes,
                        "lines": [l.model_dump() for l in line_details],
                    },
                ),
            )
        )

    bills = (
        db.query(CustomerBill)
        .filter(CustomerBill.customer_id == customer_id)
        .order_by(CustomerBill.created_at.desc())
        .all()
    )
    bill_ids = [b.id for b in bills]
    blines_by: dict[int, list] = defaultdict(list)
    if bill_ids:
        for ln in db.query(CustomerBillLine).filter(CustomerBillLine.bill_id.in_(bill_ids)).all():
            blines_by[ln.bill_id].append(ln)
    for bill in bills:
        blines = blines_by.get(bill.id) or []
        line_details = [
            LedgerLineDetail(
                our_product_id=ln.our_product_id,
                quantity=ln.quantity_shipped,
                quantity_billed=ln.quantity_shipped,
                billed_amount=_fmt_amount(ln.line_total),
                buying_price=format(ln.unit_price, "f"),
                unit_price=format(ln.unit_price, "f"),
                selling_price=format(ln.unit_price, "f"),
            )
            for ln in blines
        ]
        summary = ", ".join(f"{ln.our_product_id} × {ln.quantity_shipped}" for ln in blines[:8]) or "—"
        entries.append(
            (
                bill.created_at,
                EntityLedgerEntry(
                    id=f"co-bill-{bill.id}",
                    event_type="customer_bill",
                    title=f"Bill {bill.bill_number}",
                    summary=f"₹{bill.grand_total} · {summary}",
                    occurred_at=bill.created_at,
                    **_actor_fields(bill.created_by_name, bill.created_by_type, show_actor),
                    details={
                        "bill_id": bill.id,
                        "bill_number": bill.bill_number,
                        "grand_total": format(bill.grand_total, "f"),
                        "placement_id": bill.placement_id,
                        "customer_id": customer_id,
                        "document_url": presigned_url(bill.document_key) if bill.document_key else None,
                        "lines": [l.model_dump() for l in line_details],
                    },
                ),
            )
        )

    returns = (
        db.query(CustomerReturn)
        .filter(CustomerReturn.customer_id == customer_id)
        .order_by(CustomerReturn.created_at.desc())
        .all()
    )
    return_ids = [r.id for r in returns]
    rlines_by: dict[int, list] = defaultdict(list)
    if return_ids:
        for ln in db.query(CustomerReturnLine).filter(CustomerReturnLine.return_id.in_(return_ids)).all():
            rlines_by[ln.return_id].append(ln)
    for ret in returns:
        rlines = rlines_by.get(ret.id) or []
        summary = ", ".join(f"{ln.our_product_id} × {ln.quantity_returned}" for ln in rlines[:8]) or "—"
        entries.append(
            (
                ret.created_at,
                EntityLedgerEntry(
                    id=f"co-return-{ret.id}",
                    event_type="customer_return",
                    title=f"Return {ret.return_number}",
                    summary=f"Credit ₹{ret.credit_amount} · {summary}",
                    occurred_at=ret.created_at,
                    **_actor_fields(ret.created_by_name, ret.created_by_type, show_actor),
                    details={
                        "return_id": ret.id,
                        "return_number": ret.return_number,
                        "credit_amount": format(ret.credit_amount, "f"),
                        "calculated_amount": format(ret.calculated_amount, "f"),
                        "customer_id": customer_id,
                        "notes": ret.notes,
                        "lines": [
                            {
                                "our_product_id": ln.our_product_id,
                                "quantity": ln.quantity_returned,
                                "billed_amount": format(ln.line_calculated, "f"),
                            }
                            for ln in rlines
                        ],
                    },
                ),
            )
        )

    ar_entries = (
        db.query(ArLedgerEntry)
        .filter(
            ArLedgerEntry.customer_id == customer_id,
            ArLedgerEntry.entry_type.in_(("payment", "opening_balance")),
        )
        .order_by(ArLedgerEntry.created_at.desc())
        .all()
    )
    reversed_ar_ids = {
        r[0]
        for r in db.query(ArLedgerEntry.reverses_entry_id)
        .filter(
            ArLedgerEntry.customer_id == customer_id,
            ArLedgerEntry.entry_type == "payment_reversal",
            ArLedgerEntry.reverses_entry_id.isnot(None),
        )
        .all()
        if r[0]
    }
    for ar in ar_entries:
        if ar.entry_type == "opening_balance":
            entries.append(
                (
                    ar.created_at,
                    EntityLedgerEntry(
                        id=f"ar-opening-{ar.id}",
                        event_type="ar_opening",
                        title="Opening due",
                        summary=f"₹{abs(ar.amount)}" + (f" as on {ar.value_date}" if ar.value_date else ""),
                        occurred_at=ar.created_at,
                        **_actor_fields(ar.created_by_name, ar.created_by_type, show_actor),
                        details={
                            "ledger_entry_id": ar.id,
                            "amount": format(abs(ar.amount), "f"),
                            "as_on": ar.value_date.isoformat() if ar.value_date else None,
                        },
                    ),
                )
            )
        else:
            entries.append(
                (
                    ar.created_at,
                    EntityLedgerEntry(
                        id=f"ar-payment-{ar.id}",
                        event_type="ar_payment",
                        title="Payment collected",
                        summary=f"₹{abs(ar.amount)} — {ar.payment_ref or 'payment'}",
                        occurred_at=ar.created_at,
                        **_actor_fields(ar.created_by_name, ar.created_by_type, show_actor),
                        details={
                            "ledger_entry_id": ar.id,
                            "payment_ref": ar.payment_ref,
                            "amount": format(abs(ar.amount), "f"),
                            "comment": ar.payment_comment,
                            "reversed": ar.id in reversed_ar_ids,
                            "customer_id": customer_id,
                        },
                    ),
                )
            )

    entries.sort(key=lambda x: x[0], reverse=True)
    return [e[1] for e in entries]
