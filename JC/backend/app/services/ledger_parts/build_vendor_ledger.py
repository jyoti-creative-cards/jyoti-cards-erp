from __future__ import annotations
"""Split from app/services/ledger.py."""

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.stock import StockReceipt, StockReceiptLine
from app.models.debit_note import DebitNote
from app.models.accounts_payable import ApLedgerEntry
from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement
from app.deps import AuthContext
from app.models.vendor import Vendor
from app.models.customer import Customer
from app.services.ap_ledger import debit_note_payable_effect
from app.services.cost_visibility import hide_cost
from app.schemas.ledger import EntityLedgerEntry, LedgerLineDetail
from app.services.storage import presigned_url

_IST = ZoneInfo("Asia/Kolkata")

from app.services.ledger_parts.common import _actor_fields, _doc_status, _fmt_amount, _line_name, _occurred_at_from_display, _product_maps, _sortable_ts

def build_vendor_ledger(
    db: Session, vendor_id: int, *, auth: AuthContext, show_actor: bool = True, include_ap: bool = True
) -> List[EntityLedgerEntry]:
    entries: list[tuple[datetime, EntityLedgerEntry]] = []

    placements = (
        db.query(VendorOrderPlacement, VendorOrder)
        .join(VendorOrder, VendorOrderPlacement.vendor_order_id == VendorOrder.id)
        .filter(VendorOrder.vendor_id == vendor_id, VendorOrder.bucket.in_(("placed", "cancelled")))
        .order_by(VendorOrderPlacement.placed_at.desc())
        .all()
    )
    placement_ids = [p.id for p, _ in placements]
    plines_by: dict[int, list] = defaultdict(list)
    if placement_ids:
        for ln in db.query(VendorOrderLine).filter(VendorOrderLine.placement_id.in_(placement_ids)).all():
            plines_by[ln.placement_id].append(ln)
    receipts = (
        db.query(StockReceipt)
        .filter(StockReceipt.vendor_id == vendor_id, StockReceipt.deleted_at.is_(None))
        .order_by(StockReceipt.received_at.desc())
        .all()
    )
    receipt_ids = [r.id for r in receipts]
    rlines_by: dict[int, list] = defaultdict(list)
    if receipt_ids:
        for ln in db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id.in_(receipt_ids)).all():
            rlines_by[ln.receipt_id].append(ln)

    all_notes = (
        db.query(DebitNote)
        .filter(DebitNote.vendor_id == vendor_id, DebitNote.deleted_at.is_(None))
        .order_by(DebitNote.created_at.desc())
        .all()
    )
    notes_by_receipt: dict[int, list] = defaultdict(list)
    for n in all_notes:
        notes_by_receipt[n.receipt_id].append(n)
    receipts_by_id = {r.id: r for r in receipts}
    product_ids: set[int] = set()
    for lines in list(plines_by.values()) + list(rlines_by.values()):
        product_ids.update(ln.catalog_product_id for ln in lines if ln.catalog_product_id)
    product_ids.update(n.catalog_product_id for n in all_notes if n.catalog_product_id)
    vendor_names, vendor_products = _product_maps(db, product_ids)
    vendor = db.get(Vendor, vendor_id)
    vendor_party = vendor.business_name if vendor else f"Vendor #{vendor_id}"

    for placement, order in placements:
        lines = plines_by.get(placement.id) or []
        line_details = [
            LedgerLineDetail(
                our_product_id=_line_name(vendor_names.get(ln.catalog_product_id), ln.our_product_id),
                vendor_product_id=vendor_products.get(ln.catalog_product_id),
                quantity=ln.quantity,
                quantity_remaining=ln.quantity if order.bucket == "placed" else None,
                quantity_billed=ln.quantity_billed,
                billed_amount=_fmt_amount(ln.billed_amount),
                buying_price=hide_cost(format(ln.buying_price, "f") if ln.buying_price is not None else None, auth),
            )
            for ln in lines
        ]
        if order.bucket == "placed":
            title = "Placed order"
            event_type = "order_placed"
        else:
            title = "Cancelled placement"
            event_type = "order_cancelled"
        summary = ", ".join(
            f"{_line_name(vendor_names.get(ln.catalog_product_id), ln.our_product_id)} × {ln.quantity}" for ln in lines[:8]
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
                    details={
                        "bucket": order.bucket,
                        "placement_id": placement.id,
                        "vendor_order_id": placement.vendor_order_id,
                        "lines": [l.model_dump() for l in line_details],
                    },
                ),
            )
        )

    def _receipt_bill_amount(receipt: StockReceipt, rlines: list) -> Decimal:
        if receipt.actual_ap_amount is not None:
            return receipt.actual_ap_amount.quantize(Decimal("0.01"))
        if receipt.total_billed_amount is not None:
            return receipt.total_billed_amount.quantize(Decimal("0.01"))
        line_total = sum((ln.billed_amount or Decimal("0") for ln in rlines), Decimal("0"))
        extra = receipt.additional_charges if receipt.additional_charges else Decimal("0")
        return (line_total + extra).quantize(Decimal("0.01"))

    def _receipt_debit_note_total(receipt_id: int) -> Decimal:
        total = sum(
            (debit_note_payable_effect(n.amount, n.note_type) for n in notes_by_receipt.get(receipt_id, [])),
            Decimal("0"),
        )
        return total.quantize(Decimal("0.01"))

    for receipt in receipts:
        rlines = rlines_by.get(receipt.id) or []
        line_details = [
            LedgerLineDetail(
                our_product_id=_line_name(vendor_names.get(ln.catalog_product_id), ln.our_product_id), vendor_product_id=vendor_products.get(ln.catalog_product_id),
                quantity_received=ln.quantity_received,
                quantity_billed=ln.quantity_billed, billed_amount=_fmt_amount(ln.billed_amount),
                buying_price=hide_cost(format(ln.buying_price, "f") if ln.buying_price is not None else None, auth),
            )
            for ln in rlines
        ]
        summary = ", ".join(
            f"{_line_name(vendor_names.get(ln.catalog_product_id), ln.our_product_id)} +{ln.quantity_received}" for ln in rlines[:8]
        ) or "—"
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
            if _doc_status(receipt) == "voided":
                continue
            bill_amt = _receipt_bill_amount(receipt, rlines)
            dn_total = _receipt_debit_note_total(receipt.id)
            bank_amt, cash_amt = vendor_bill_channels(receipt)
            line_details = [
                LedgerLineDetail(
                    our_product_id=_line_name(vendor_names.get(ln.catalog_product_id), ln.our_product_id),
                    vendor_product_id=vendor_products.get(ln.catalog_product_id),
                    quantity_received=ln.quantity_received,
                    quantity_billed=ln.quantity_billed,
                    billed_amount=_fmt_amount(ln.billed_amount),
                    buying_price=hide_cost(format(ln.buying_price, "f") if ln.buying_price is not None else None, auth),
                )
                for ln in rlines
            ]
            bill_number = receipt.bill_number
            occurred = _occurred_at_from_display(
                receipt.billed_at or receipt.received_at, receipt.billed_at or receipt.received_at
            )
            entries.append((
                occurred,
                EntityLedgerEntry(
                    id=f"bill-{receipt.id}", event_type="vendor_bill", title="Bill",
                    summary=f"{bill_number or receipt.id} — ₹{bill_amt}", occurred_at=occurred,
                    **_actor_fields(receipt.received_by_name, receipt.received_by_type, show_actor),
                    details={
                        "receipt_id": receipt.id, "bill_number": bill_number,
                        "bill_amount": format(bill_amt, "f"),
                        "bank_amount": format(bank_amt, "f"),
                        "cash_amount": format(cash_amt, "f") if cash_amt > 0 else None,
                        "debit_note_total": format(dn_total, "f"),
                        "net_payable": format(bill_amt + dn_total, "f"),
                        "additional_charges": _fmt_amount(receipt.additional_charges),
                        "bill_file_url": presigned_url(receipt.bill_file_key) if receipt.bill_file_key else None,
                        "lines": [l.model_dump() for l in line_details],
                    },
                ),
            ))

    for note in all_notes:
        receipt = receipts_by_id.get(note.receipt_id)
        if _doc_status(note) == "voided":
            continue
        our_product_id = _line_name(
            vendor_names.get(note.catalog_product_id) if note.catalog_product_id else None,
            note.our_product_id,
        )
        vendor_product_id = vendor_products.get(note.catalog_product_id) if note.catalog_product_id else None
        summary = (
            f"{our_product_id} × {note.quantity} = ₹{note.amount}"
            if note.note_type == "item"
            else f"Value debit ₹{note.amount}"
        )
        display_date = receipt.billed_at if receipt is not None and receipt.billed_at else note.created_at
        occurred = _occurred_at_from_display(display_date, note.created_at)
        entries.append(
            (
                occurred,
                EntityLedgerEntry(
                    id=f"debit-note-{note.id}",
                    event_type="debit_note",
                    title="Debit note",
                    summary=summary,
                    occurred_at=occurred,
                    **_actor_fields(note.created_by_name, note.created_by_type, show_actor),
                    details={
                        "debit_note_id": note.id,
                        "receipt_id": note.receipt_id,
                        "bill_number": receipt.bill_number if receipt else None,
                        "note_type": note.note_type,
                        "our_product_id": our_product_id,
                        "vendor_product_id": vendor_product_id,
                        "quantity": note.quantity,
                        "amount": format(note.amount, "f"),
                        "notes": note.notes,
                        "party_name": vendor_party,
                    },
                ),
            )
        )

    ap_entries = (
        db.query(ApLedgerEntry)
        .filter(
            ApLedgerEntry.vendor_id == vendor_id,
            ApLedgerEntry.entry_type == "payment",
            ApLedgerEntry.deleted_at.is_(None),
        )
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
        if _doc_status(ap) == "voided":
            continue
        occurred = _occurred_at_from_display(ap.value_date or ap.created_at, ap.created_at)
        entries.append(
            (
                occurred,
                EntityLedgerEntry(
                    id=f"ap-payment-{ap.id}",
                    event_type="ap_payment",
                    title="AP payment",
                    summary=f"₹{abs(ap.amount)} — {ap.payment_ref or 'payment'}",
                    occurred_at=occurred,
                    **_actor_fields(ap.created_by_name, ap.created_by_type, show_actor),
                    details={
                        "ledger_entry_id": ap.id,
                        "payment_ref": ap.payment_ref,
                        "amount": format(abs(ap.amount), "f"),
                        "payment_receipt_url": presigned_url(ap.payment_receipt_key) if ap.payment_receipt_key else None,
                        "comment": ap.payment_comment,
                        "payment_mode": ap.payment_mode,
                        "reversed": ap.id in reversed_ap_ids,
                        "party_name": vendor_party,
                    },
                ),
            )
        )

    entries.sort(key=lambda x: _sortable_ts(x[0]), reverse=True)
    return [e[1] for e in entries]

def vendor_bill_channels(receipt: StockReceipt) -> tuple[Decimal, Decimal]:
    """Paper invoice is bank. The untaxed 50% remainder is cash."""
    paper = receipt.total_billed_amount
    cash = Decimal("0.00")
    if paper is not None and receipt.actual_ap_amount is not None:
        diff = (receipt.actual_ap_amount - paper).quantize(Decimal("0.01"))
        if diff > 0:
            cash = diff
    elif receipt.expected_extra_cash is not None and receipt.expected_extra_cash > 0:
        cash = receipt.expected_extra_cash.quantize(Decimal("0.01"))
    if paper is not None:
        bank = paper.quantize(Decimal("0.01"))
    elif receipt.actual_ap_amount is not None:
        bank = receipt.actual_ap_amount.quantize(Decimal("0.01"))
    else:
        bank = Decimal("0.00")
    return bank, cash
