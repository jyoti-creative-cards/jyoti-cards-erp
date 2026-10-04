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

def build_customer_ledger(db: Session, customer_id: int, *, show_actor: bool = True) -> List[EntityLedgerEntry]:
    """Orders placed, bills sold, payments collected, returns — full customer activity."""
    from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
    from app.models.customer_bill import CustomerBill, CustomerBillLine
    from app.models.customer_return import CustomerReturn, CustomerReturnLine
    from app.models.accounts_receivable import ArLedgerEntry

    entries: list[tuple[datetime, EntityLedgerEntry]] = []

    # Billing (process_customer_bill) and per-line close (close_bill_line) each spawn a
    # fresh internal "billed"/"closed"-bucket placement to carry their own line history —
    # they are not a second real order. Without this exclusion, one logical order shows
    # up twice under Activity → Orders: once from its real received/open placement, once
    # again from this internal mirror (e.g. the "488 and 489 look identical" bug). The
    # mirror's content already surfaces via its own "Bill {number}" entry below, so
    # hiding it here loses nothing.
    mirror_placement_ids = {
        r[0]
        for r in db.query(CustomerBill.placement_id)
        .filter(CustomerBill.customer_id == customer_id, CustomerBill.placement_id.isnot(None))
        .all()
    }

    placements = (
        db.query(CustomerOrderPlacement, CustomerOrder)
        .join(CustomerOrder, CustomerOrderPlacement.customer_order_id == CustomerOrder.id)
        .filter(
            CustomerOrder.customer_id == customer_id,
            CustomerOrderPlacement.deleted_at.is_(None),
            CustomerOrder.bucket != "closed",
        )
        .order_by(CustomerOrderPlacement.placed_at.desc())
        .all()
    )
    placements = [(p, o) for p, o in placements if p.id not in mirror_placement_ids]
    placement_ids = [p.id for p, _ in placements]
    olines_by: dict[int, list] = defaultdict(list)
    if placement_ids:
        for ln in db.query(CustomerOrderLine).filter(CustomerOrderLine.placement_id.in_(placement_ids)).all():
            olines_by[ln.placement_id].append(ln)
    order_ids = {
        ln.catalog_product_id
        for lines in olines_by.values()
        for ln in lines
        if ln.catalog_product_id
    }
    order_names, _order_vendor_codes = _product_maps(db, order_ids)
    customer = db.get(Customer, customer_id)
    customer_party = customer.business_name if customer else f"Customer #{customer_id}"
    for placement, order in placements:
        lines = olines_by.get(placement.id) or []

        def _order_line_name(ln) -> str:
            cid = ln.catalog_product_id
            live = order_names.get(int(cid)) if cid else None
            return _line_name(live, ln.our_product_id)

        line_details = [
            LedgerLineDetail(
                our_product_id=_order_line_name(ln),
                quantity=ln.quantity,
                quantity_billed=ln.quantity_billed,
                # NB: no buying_price here — this is the customer-side ledger, so
                # ln.unit_price is our *selling* price, not a cost figure. Reusing
                # the buying_price field name (as build_vendor_ledger legitimately
                # does for real cost data) would be a redaction trap for any future
                # code that pattern-matches on that field name to apply hide_cost().
                unit_price=format(ln.unit_price, "f"),
                selling_price=format(ln.unit_price, "f"),
            )
            for ln in lines
        ]
        cancelled = placement.status == "cancelled" or order.bucket == "cancelled"
        event_type = "order_cancelled" if cancelled else "order_placed"
        title = "Cancelled order" if cancelled else "Order placed"
        summary = ", ".join(
            f"{_order_line_name(ln)} × {ln.quantity}"
            for ln in lines[:8]
        ) or "—"
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
        .filter(CustomerBill.customer_id == customer_id, CustomerBill.deleted_at.is_(None))
        .order_by(CustomerBill.created_at.desc())
        .all()
    )
    bill_ids = [b.id for b in bills]
    blines_by: dict[int, list] = defaultdict(list)
    if bill_ids:
        for ln in db.query(CustomerBillLine).filter(CustomerBillLine.bill_id.in_(bill_ids)).all():
            blines_by[ln.bill_id].append(ln)
    bill_names, _bill_vendor_codes = _product_maps(
        db,
        {ln.catalog_product_id for lines in blines_by.values() for ln in lines if ln.catalog_product_id},
    )
    for bill in bills:
        if _doc_status(bill) == "voided":
            continue
        blines = blines_by.get(bill.id) or []

        def _bill_line_name(ln) -> str:
            live = bill_names.get(ln.catalog_product_id) if ln.catalog_product_id else None
            return _line_name(live, ln.our_product_id)

        line_details = [
            LedgerLineDetail(
                our_product_id=_bill_line_name(ln),
                quantity=ln.quantity_shipped,
                quantity_billed=ln.quantity_shipped,
                billed_amount=_fmt_amount(ln.line_total),
                # NB: no buying_price here — see comment in build_customer_ledger above.
                unit_price=format(ln.unit_price, "f"),
                selling_price=format(ln.unit_price, "f"),
            )
            for ln in blines
        ]
        summary = (
            ", ".join(f"{_bill_line_name(ln)} × {ln.quantity_shipped}" for ln in blines[:8])
            or "—"
        )
        bill_number = bill.bill_number
        title = (
            f"Cancelled bill {bill_number}"
            if _doc_status(bill) == "cancelled"
            else f"Bill {bill_number}"
        )
        occurred = _occurred_at_from_display(bill.bill_date, bill.created_at)
        entries.append(
            (
                occurred,
                EntityLedgerEntry(
                    id=f"co-bill-{bill.id}",
                    event_type="customer_bill",
                    title=title,
                    summary=f"₹{bill.grand_total} · {summary}",
                    occurred_at=occurred,
                    **_actor_fields(bill.created_by_name, bill.created_by_type, show_actor),
                    details={
                        "bill_id": bill.id,
                        "bill_number": bill_number,
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
        .filter(CustomerReturn.customer_id == customer_id, CustomerReturn.deleted_at.is_(None))
        .order_by(CustomerReturn.created_at.desc())
        .all()
    )
    return_ids = [r.id for r in returns]
    rlines_by: dict[int, list] = defaultdict(list)
    if return_ids:
        for ln in db.query(CustomerReturnLine).filter(CustomerReturnLine.return_id.in_(return_ids)).all():
            rlines_by[ln.return_id].append(ln)
    return_names, _return_vendor_codes = _product_maps(
        db,
        {ln.catalog_product_id for lines in rlines_by.values() for ln in lines if ln.catalog_product_id},
    )
    for ret in returns:
        if _doc_status(ret) == "voided":
            continue
        rlines = rlines_by.get(ret.id) or []

        def _return_line_name(ln) -> str:
            live = return_names.get(ln.catalog_product_id) if ln.catalog_product_id else None
            return _line_name(live, ln.our_product_id)

        summary = (
            ", ".join(f"{_return_line_name(ln)} × {ln.quantity_returned}" for ln in rlines[:8])
            or "—"
        )
        return_number = ret.return_number
        occurred = _occurred_at_from_display(ret.created_at, ret.created_at)
        entries.append(
            (
                occurred,
                EntityLedgerEntry(
                    id=f"co-return-{ret.id}",
                    event_type="customer_return",
                    title=f"Return {return_number}",
                    summary=f"Credit ₹{ret.credit_amount} · {summary}",
                    occurred_at=occurred,
                    **_actor_fields(ret.created_by_name, ret.created_by_type, show_actor),
                    details={
                        "return_id": ret.id,
                        "return_number": return_number,
                        "credit_amount": format(ret.credit_amount, "f"),
                        "calculated_amount": format(ret.calculated_amount, "f"),
                        "customer_id": customer_id,
                        "notes": ret.notes,
                        "lines": [
                            {
                                "our_product_id": _return_line_name(ln),
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
            ArLedgerEntry.deleted_at.is_(None),
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
            if _doc_status(ar) == "voided":
                continue
            occurred = _occurred_at_from_display(ar.value_date or ar.created_at, ar.created_at)
            entries.append(
                (
                    occurred,
                    EntityLedgerEntry(
                        id=f"ar-payment-{ar.id}",
                        event_type="ar_payment",
                        title="Payment collected",
                        summary=f"₹{abs(ar.amount)} — {ar.payment_ref or 'payment'}",
                        occurred_at=occurred,
                        **_actor_fields(ar.created_by_name, ar.created_by_type, show_actor),
                        details={
                            "ledger_entry_id": ar.id,
                            "payment_ref": ar.payment_ref,
                            "amount": format(abs(ar.amount), "f"),
                            "comment": ar.payment_comment,
                            "reversed": ar.id in reversed_ar_ids,
                            "customer_id": customer_id,
                            "party_name": customer_party,
                        },
                    ),
                )
            )

    entries.sort(key=lambda x: _sortable_ts(x[0]), reverse=True)
    return [e[1] for e in entries]
