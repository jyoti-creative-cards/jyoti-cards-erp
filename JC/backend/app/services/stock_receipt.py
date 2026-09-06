from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.deps import AuthContext
from app.models.catalog_product import CatalogProduct
from app.models.stock import StockBalance, StockLedger, StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement


def get_open_order(db: Session, vendor_id: int, bucket: str) -> VendorOrder | None:
    return (
        db.query(VendorOrder)
        .filter(
            VendorOrder.vendor_id == vendor_id,
            VendorOrder.bucket == bucket,
            VendorOrder.is_open.is_(True),
        )
        .first()
    )


def get_or_create_open_order(db: Session, vendor_id: int, bucket: str, status: str) -> VendorOrder:
    from sqlalchemy.exc import IntegrityError

    order = get_open_order(db, vendor_id, bucket)
    if order:
        return order
    try:
        with db.begin_nested():
            order = VendorOrder(vendor_id=vendor_id, bucket=bucket, status=status, is_open=True)
            db.add(order)
            db.flush()
    except IntegrityError:
        order = get_open_order(db, vendor_id, bucket)
        if not order:
            raise
    return order


def add_stock(
    db: Session,
    *,
    catalog_product_id: int,
    our_product_id: str,
    quantity: int,
    entry_type: str,
    reference_type: str,
    reference_id: int,
    party: str | None = None,
    notes: str | None = None,
) -> StockBalance:
    balance = (
        db.query(StockBalance)
        .filter(StockBalance.catalog_product_id == catalog_product_id)
        .with_for_update()
        .first()
    )
    if not balance:
        # catalog_product_id is unique on StockBalance — two concurrent first-ever
        # touches of a brand-new product's stock can both miss the row above and
        # both try to insert. Same begin_nested/IntegrityError-retry shape as
        # get_or_create_open_order.
        from sqlalchemy.exc import IntegrityError

        try:
            with db.begin_nested():
                balance = StockBalance(catalog_product_id=catalog_product_id, quantity_on_hand=0)
                db.add(balance)
                db.flush()
        except IntegrityError:
            balance = (
                db.query(StockBalance)
                .filter(StockBalance.catalog_product_id == catalog_product_id)
                .with_for_update()
                .first()
            )
            if not balance:
                raise
    balance.quantity_on_hand += quantity
    db.add(
        StockLedger(
            catalog_product_id=catalog_product_id,
            entry_type=entry_type,
            quantity_delta=quantity,
            balance_after=balance.quantity_on_hand,
            reference_type=reference_type,
            reference_id=reference_id,
            party=party,
            notes=notes,
        )
    )
    return balance


def build_vendor_received_detail(db: Session, vendor_id: int, auth: AuthContext) -> dict:
    """Detail view for the 'Received' tab's full-page per-vendor drill-down — sources
    directly from StockReceipt (bill_status == 'pending_bill'), same rationale as
    build_vendor_billed_detail (no real VendorOrder id exists for this bucket either).
    Before this existed, the frontend hardcoded aggregated_lines: [] for this bucket,
    so the 'Received qty'/'Unbilled' stat pills always showed 0 and every receipt card
    showed '0 products' with no expand table. Shape matches build_vendor_billed_detail:
    one 'placement' per receipt, aggregated_lines grouped by product with a
    per-placement breakdown (including quantity_remaining = received - billed, used
    for the 'Unbilled' column/pill)."""
    from app.services.cost_visibility import hide_cost
    from app.services.storage import presigned_urls
    from app.models.city import City

    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        return {"vendor_id": vendor_id, "vendor_label": f"Vendor #{vendor_id}", "placements": [], "aggregated_lines": []}
    city = db.get(City, vendor.city_id) if vendor.city_id else None
    label = f"{vendor.business_name} — {city.name}" if city else vendor.business_name

    receipts = (
        db.query(StockReceipt)
        .filter(
            StockReceipt.vendor_id == vendor_id,
            StockReceipt.bill_status == "pending_bill",
            StockReceipt.deleted_at.is_(None),
        )
        .order_by(StockReceipt.received_at.desc())
        .all()
    )
    receipt_ids = [r.id for r in receipts]
    lines_by_receipt: dict[int, list[StockReceiptLine]] = {}
    if receipt_ids:
        for ln in db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id.in_(receipt_ids)).all():
            lines_by_receipt.setdefault(ln.receipt_id, []).append(ln)
    product_ids = {ln.catalog_product_id for lns in lines_by_receipt.values() for ln in lns}
    products = (
        {p.id: p for p in db.query(CatalogProduct).filter(CatalogProduct.id.in_(product_ids)).all()}
        if product_ids else {}
    )

    placements: list[dict] = []
    agg_by_pid: dict[int, dict] = {}
    for r in receipts:
        lines = lines_by_receipt.get(r.id, [])
        placements.append({
            "id": r.id,
            "receipt_id": r.id,
            "order_receipt_number": r.order_receipt_number,
            "placed_at": r.received_at.isoformat() if r.received_at else None,
            "line_count": len(lines),
            "total_quantity": sum(int(ln.quantity_received or 0) for ln in lines),
            "notes": None,
        })
        for ln in lines:
            prod = products.get(ln.catalog_product_id)
            entry = agg_by_pid.setdefault(ln.catalog_product_id, {
                "catalog_product_id": ln.catalog_product_id,
                "our_product_id": ln.our_product_id,
                "vendor_product_id": prod.vendor_product_id if prod else None,
                "image_urls": presigned_urls(prod.image_keys or []) if prod else [],
                "buying_price": hide_cost(format(ln.buying_price, "f"), auth),
                "total_quantity": 0,
                "total_pending": 0,
                "breakdown": [],
            })
            recv_qty = int(ln.quantity_received or 0)
            billed_qty = int(ln.quantity_billed or 0)
            remaining = max(0, recv_qty - billed_qty)
            entry["total_quantity"] += recv_qty
            entry["total_pending"] += remaining
            entry["breakdown"].append({
                "placement_id": r.id,
                "quantity": recv_qty,
                "quantity_billed": billed_qty,
                "quantity_remaining": remaining,
                "billed_amount": format(ln.billed_amount, "f") if ln.billed_amount is not None else None,
            })

    return {
        "vendor_id": vendor_id,
        "vendor_label": label,
        "vendor_alias": vendor.alias,
        "placements": placements,
        "aggregated_lines": list(agg_by_pid.values()),
    }


def build_vendor_billed_detail(db: Session, vendor_id: int, auth: AuthContext) -> dict:
    """Detail view for the 'Billed' tab's per-vendor drill-down (hub inline expand and
    the full-page detail view) — sources directly from StockReceipt (bill_status ==
    'billed'), not VendorOrder, since VendorOrder.bucket never actually becomes 'billed'
    in this one-receipt-per-bill model (see _billed_summaries in routers/vendor_orders.py).
    Before this existed, the frontend tried to look up a real VendorOrder id that would
    never exist for this bucket and silently fell back to an empty placements/lines list
    — the 'Billed' tab card showed real totals but expanding/opening it always showed
    nothing. Shape matches what renderBilledExpand / renderDetail's isBilled branch
    already expect: one 'placement' per bill (receipt, id == receipt_id), aggregated_lines
    grouped by product with a per-placement breakdown."""
    from app.models.debit_note import DebitNote  # noqa: F401  (kept for readers tracing debit-note totals)
    from app.services.ap_ledger import receipt_bill_amount, receipt_debit_note_total
    from app.services.cost_visibility import hide_cost
    from app.services.storage import presigned_url, presigned_urls

    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        return {"vendor_id": vendor_id, "vendor_label": f"Vendor #{vendor_id}", "placements": [], "aggregated_lines": []}
    from app.models.city import City

    city = db.get(City, vendor.city_id) if vendor.city_id else None
    label = f"{vendor.business_name} — {city.name}" if city else vendor.business_name

    receipts = (
        db.query(StockReceipt)
        .filter(
            StockReceipt.vendor_id == vendor_id,
            StockReceipt.bill_status == "billed",
            StockReceipt.deleted_at.is_(None),
        )
        .order_by(StockReceipt.billed_at.desc())
        .all()
    )
    receipt_ids = [r.id for r in receipts]
    lines_by_receipt: dict[int, list[StockReceiptLine]] = {}
    if receipt_ids:
        for ln in db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id.in_(receipt_ids)).all():
            lines_by_receipt.setdefault(ln.receipt_id, []).append(ln)
    product_ids = {ln.catalog_product_id for lns in lines_by_receipt.values() for ln in lns}
    products = (
        {p.id: p for p in db.query(CatalogProduct).filter(CatalogProduct.id.in_(product_ids)).all()}
        if product_ids else {}
    )

    placements: list[dict] = []
    agg_by_pid: dict[int, dict] = {}
    for r in receipts:
        lines = lines_by_receipt.get(r.id, [])
        bill_amt = receipt_bill_amount(db, r.id)
        dn_total = receipt_debit_note_total(db, r.id)
        placements.append({
            "id": r.id,
            "receipt_id": r.id,
            "bill_number": r.bill_number,
            "placed_at": (r.billed_at or r.received_at).isoformat(),
            "line_count": len(lines),
            "total_quantity": sum(int(ln.quantity_received or 0) for ln in lines),
            "bill_amount": format(bill_amt, "f"),
            "debit_note_total": format(dn_total, "f"),
            "net_payable": format(bill_amt + dn_total, "f"),
            "closed_at": r.closed_at.isoformat() if r.closed_at else None,
            "close_reason": r.close_reason,
            "bill_file_url": presigned_url(r.bill_file_key) if r.bill_file_key else None,
        })
        for ln in lines:
            prod = products.get(ln.catalog_product_id)
            entry = agg_by_pid.setdefault(ln.catalog_product_id, {
                "catalog_product_id": ln.catalog_product_id,
                "our_product_id": ln.our_product_id,
                "vendor_product_id": prod.vendor_product_id if prod else None,
                "image_urls": presigned_urls(prod.image_keys or []) if prod else [],
                "buying_price": hide_cost(format(ln.buying_price, "f"), auth),
                "breakdown": [],
            })
            entry["breakdown"].append({
                "placement_id": r.id,
                "quantity": ln.quantity_received,
                "quantity_billed": ln.quantity_billed,
                "billed_amount": format(ln.billed_amount, "f") if ln.billed_amount is not None else None,
            })

    return {
        "vendor_id": vendor_id,
        "vendor_label": label,
        "vendor_alias": vendor.alias,
        "placements": placements,
        "aggregated_lines": list(agg_by_pid.values()),
    }
