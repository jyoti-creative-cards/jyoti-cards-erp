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


def _vendor_label(db: Session, vendor_id: int) -> str:
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        return f"Vendor #{vendor_id}"
    city_name = None
    if vendor.city_id:
        city = db.get(City, vendor.city_id)
        city_name = city.name if city else None
    return f"{vendor.business_name} — {city_name}" if city_name else vendor.business_name

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

def get_opening_balance(db: Session, vendor_id: int) -> Optional[ApLedgerEntry]:
    return (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.vendor_id == vendor_id, ApLedgerEntry.entry_type == "opening_balance")
        .order_by(ApLedgerEntry.id.desc())
        .first()
    )

def list_ap_vendors(db: Session) -> list[dict]:
    """One aggregate query + vendor/city joins — no per-vendor N+1."""
    from sqlalchemy import and_, case, func, or_
    from sqlalchemy.orm import aliased

    # Bill edits post a compensating `adjustment` row that reverses the original `bill`
    # entry rather than mutating it (see vendor_ap_totals for the same fold-in). Without
    # this join, `bill_sum` here silently stops matching `outstanding` after any such edit.
    bill_ref = aliased(ApLedgerEntry)

    opening_sum = func.coalesce(
        func.sum(case((ApLedgerEntry.entry_type == "opening_balance", ApLedgerEntry.amount), else_=0)),
        0,
    )
    bill_sum = func.coalesce(
        func.sum(
            case(
                (
                    or_(
                        ApLedgerEntry.entry_type == "bill",
                        and_(ApLedgerEntry.entry_type == "adjustment", bill_ref.id.isnot(None)),
                    ),
                    ApLedgerEntry.amount,
                ),
                else_=0,
            )
        ),
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
        .outerjoin(
            bill_ref,
            and_(bill_ref.id == ApLedgerEntry.reverses_entry_id, bill_ref.entry_type == "bill"),
        )
        .filter(ApLedgerEntry.deleted_at.is_(None))
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
            WHERE e.deleted_at IS NULL
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

