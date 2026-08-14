"""Split vendor flow: receive goods (stock) then bill (AP) against unbilled received."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.deps import AuthContext
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.stock import StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement
from app.schemas.stock import VendorReceiptCreate
from app.services.activity import log_from_auth
from app.services.ap_ledger import post_bill_entry, receipt_bill_amount
from app.services.debit_notes import create_debit_note
from app.services.open_lines import reduce_from_open
from app.services.stock_receipt import add_stock, get_open_order, get_or_create_open_order


def _vendor_label(db: Session, vendor: Vendor) -> str:
    city_name = None
    if vendor.city_id:
        city = db.get(City, vendor.city_id)
        city_name = city.name if city else None
    return f"{vendor.business_name} — {city_name}" if city_name else vendor.business_name


def unbilled_received_qty_by_product(db: Session, vendor_id: int) -> dict[int, int]:
    """Yet-to-bill qty from received bucket lines (quantity_remaining)."""
    received = get_open_order(db, vendor_id, "received")
    if not received:
        return {}
    rows = (
        db.query(
            VendorOrderLine.catalog_product_id,
            func.coalesce(func.sum(VendorOrderLine.quantity_remaining), 0),
        )
        .join(VendorOrderPlacement, VendorOrderLine.placement_id == VendorOrderPlacement.id)
        .filter(
            VendorOrderPlacement.vendor_order_id == received.id,
            VendorOrderPlacement.status == "received",
            VendorOrderLine.quantity_remaining > 0,
        )
        .group_by(VendorOrderLine.catalog_product_id)
        .all()
    )
    return {int(cat_id): int(qty or 0) for cat_id, qty in rows if int(qty or 0) > 0}


def reduce_unbilled_received(db: Session, vendor_id: int, lines: list[tuple[int, int]]) -> None:
    """FIFO reduce quantity_remaining on received placements."""
    received = get_open_order(db, vendor_id, "received")
    if not received:
        return
    for catalog_product_id, qty in lines:
        left = int(qty or 0)
        if left <= 0:
            continue
        order_lines = (
            db.query(VendorOrderLine)
            .join(VendorOrderPlacement, VendorOrderLine.placement_id == VendorOrderPlacement.id)
            .filter(
                VendorOrderPlacement.vendor_order_id == received.id,
                VendorOrderPlacement.status == "received",
                VendorOrderLine.catalog_product_id == catalog_product_id,
                VendorOrderLine.quantity_remaining > 0,
            )
            .order_by(VendorOrderPlacement.placed_at.asc(), VendorOrderLine.id.asc())
            .with_for_update()
            .all()
        )
        for ol in order_lines:
            if left <= 0:
                break
            take = min(int(ol.quantity_remaining or 0), left)
            ol.quantity_remaining = int(ol.quantity_remaining or 0) - take
            prev_billed = int(ol.quantity_billed or 0)
            ol.quantity_billed = prev_billed + take
            left -= take
        if left > 0:
            prod = db.get(CatalogProduct, catalog_product_id)
            label = prod.our_product_id if prod else catalog_product_id
            raise HTTPException(400, f"cannot bill more than unbilled received for {label}")


def receive_vendor_goods(
    db: Session,
    auth: AuthContext,
    body: VendorReceiptCreate,
    *,
    offline: bool = False,
) -> dict:
    """Stock in + received aggregate. No AP, no debit notes. Order receipt # required.

    offline=True: no placed order / open-line reduce — pick any vendor products.
    """
    stock_lines = [ln for ln in body.lines if int(ln.quantity_received or 0) > 0]
    if not stock_lines:
        raise HTTPException(400, "enter quantity received on at least one row")
    order_receipt_number = (getattr(body, "order_receipt_number", None) or "").strip()
    if not order_receipt_number:
        raise HTTPException(400, "order receipt number is required")

    vendor = db.get(Vendor, body.vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    label = _vendor_label(db, vendor)

    placed = None
    if not offline:
        placed = get_open_order(db, body.vendor_id, "placed")
        if not placed:
            raise HTTPException(400, "no open placed order for this vendor")

        from app.services.order_summary import pending_qty_by_product

        pending = pending_qty_by_product(db, body.vendor_id)
        for ln in stock_lines:
            pid = ln.catalog_product_id
            want = int(ln.quantity_received or 0)
            have = int(pending.get(pid, 0))
            if want > have:
                prod = db.get(CatalogProduct, pid)
                raise HTTPException(
                    400,
                    f"received qty for {prod.our_product_id if prod else pid} ({want}) exceeds pending ({have})",
                )

    from app.services.biz_date import resolve_biz_dt

    received_order = get_or_create_open_order(db, body.vendor_id, "received", "received")
    now = resolve_biz_dt(getattr(body, "received_on", None))

    note = (getattr(body, "notes", None) or "").strip() or None
    placement = VendorOrderPlacement(
        vendor_order_id=received_order.id,
        status="received",
        placed_by_type=auth.actor_type,
        placed_by_id=auth.actor_id,
        placed_by_name=auth.actor_name,
        placed_at=now,
    )
    db.add(placement)
    db.flush()

    receipt = StockReceipt(
        # Same receive type so Received → Bill / edit paths stay unified
        receipt_type="vendor_receive",
        vendor_id=body.vendor_id,
        placed_order_id=placed.id if placed else None,
        billed_placement_id=None,
        received_placement_id=placement.id,
        additional_charges=None,
        total_billed_amount=None,
        bill_number=None,
        order_receipt_number=order_receipt_number[:120],
        bill_file_key=body.bill_file_key,
        notes=note,
        received_by_type=auth.actor_type,
        received_by_id=auth.actor_id,
        received_by_name=auth.actor_name,
        received_at=now,
    )
    db.add(receipt)
    db.flush()

    line_summary = []
    for ln in stock_lines:
        prod = db.get(CatalogProduct, ln.catalog_product_id)
        if not prod or prod.vendor_id != body.vendor_id:
            raise HTTPException(400, f"invalid product {ln.catalog_product_id} for vendor")
        recv_qty = int(ln.quantity_received or 0)
        db.add(
            VendorOrderLine(
                placement_id=placement.id,
                catalog_product_id=prod.id,
                our_product_id=prod.our_product_id,
                quantity=recv_qty,
                quantity_remaining=recv_qty,  # unbilled
                quantity_billed=0,
                billed_amount=Decimal("0"),
                buying_price=prod.buying_price,
            )
        )
        db.add(
            StockReceiptLine(
                receipt_id=receipt.id,
                catalog_product_id=prod.id,
                our_product_id=prod.our_product_id,
                quantity_received=recv_qty,
                quantity_billed=0,
                billed_amount=Decimal("0"),
                buying_price=prod.buying_price,
            )
        )
        add_stock(
            db,
            catalog_product_id=prod.id,
            our_product_id=prod.our_product_id,
            quantity=recv_qty,
            entry_type="received",
            reference_type="stock_receipt",
            reference_id=receipt.id,
            party=label,
            notes=note or ("Offline goods received" if offline else "Goods received"),
        )
        line_summary.append(f"{prod.our_product_id}+{recv_qty}")

    if not offline:
        reduce_from_open(
            db,
            body.vendor_id,
            [(ln.catalog_product_id, int(ln.quantity_received or 0)) for ln in stock_lines],
        )
        placed.updated_at = now

    received_order.updated_at = now
    log_from_auth(
        db,
        auth,
        action="offline_receive" if offline else "receive_goods",
        entity_type="stock_receipt",
        entity_id=receipt.id,
        entity_label=label,
        detail=", ".join(line_summary[:10]),
    )
    db.commit()
    return {
        "ok": True,
        "receipt_id": receipt.id,
        "received_placement_id": placement.id,
        "vendor_id": body.vendor_id,
        "message": f"{'Offline receive' if offline else 'Received goods'} for {len(stock_lines)} product(s)",
        "document_url": None,
    }


def bill_from_received(db: Session, auth: AuthContext, body: VendorReceiptCreate) -> dict:
    """Bill against unbilled received. No stock change. Posts AP + debit notes."""
    bill_lines = [
        ln
        for ln in body.lines
        if int(ln.quantity_billed or 0) > 0 or int(ln.quantity_received or 0) > 0
    ]
    # Prefer quantity_billed; fall back to quantity_received as billed qty for convenience
    normalized: list[tuple] = []
    for ln in bill_lines:
        bq = int(ln.quantity_billed or 0)
        if bq <= 0:
            bq = int(ln.quantity_received or 0)
        if bq > 0:
            normalized.append((ln, bq))
    if not normalized:
        raise HTTPException(400, "enter billed quantity on at least one row")

    line_bill_total = sum((ln.billed_amount or Decimal("0")) for ln, _ in normalized)
    if body.total_billed_amount is None and line_bill_total <= 0:
        raise HTTPException(400, "enter total bill amount for this shipment")

    vendor = db.get(Vendor, body.vendor_id)
    if not vendor or vendor.deleted_at:
        raise HTTPException(404, "vendor not found")
    label = _vendor_label(db, vendor)

    unbilled = unbilled_received_qty_by_product(db, body.vendor_id)
    if not unbilled:
        raise HTTPException(400, "no unbilled received goods for this vendor")

    for ln, bq in normalized:
        have = int(unbilled.get(ln.catalog_product_id, 0))
        if bq > have:
            prod = db.get(CatalogProduct, ln.catalog_product_id)
            raise HTTPException(
                400,
                f"billed qty for {prod.our_product_id if prod else ln.catalog_product_id} ({bq}) exceeds unbilled received ({have})",
            )

    from app.services.biz_date import as_biz_date, resolve_biz_dt

    billed = get_or_create_open_order(db, body.vendor_id, "billed", "billed")
    now = resolve_biz_dt(getattr(body, "bill_date", None))

    placement = VendorOrderPlacement(
        vendor_order_id=billed.id,
        status="billed",
        placed_by_type=auth.actor_type,
        placed_by_id=auth.actor_id,
        placed_by_name=auth.actor_name,
        placed_at=now,
    )
    db.add(placement)
    db.flush()

    receipt = StockReceipt(
        receipt_type="vendor_bill",
        vendor_id=body.vendor_id,
        placed_order_id=None,
        billed_placement_id=placement.id,
        additional_charges=body.additional_charges.quantize(Decimal("0.01")) if body.additional_charges is not None else None,
        total_billed_amount=body.total_billed_amount.quantize(Decimal("0.01")) if body.total_billed_amount is not None else None,
        bill_number=(body.bill_number or "").strip() or None,
        bill_file_key=body.bill_file_key,
        notes=(getattr(body, "notes", None) or "").strip() or None,
        received_by_type=auth.actor_type,
        received_by_id=auth.actor_id,
        received_by_name=auth.actor_name,
        received_at=now,
    )
    db.add(receipt)
    db.flush()

    line_summary = []
    reduce_pairs: list[tuple[int, int]] = []
    for ln, bq in normalized:
        prod = db.get(CatalogProduct, ln.catalog_product_id)
        if not prod or prod.vendor_id != body.vendor_id:
            raise HTTPException(400, f"invalid product {ln.catalog_product_id} for vendor")
        unbilled_recv = int(unbilled.get(prod.id, 0))
        # quantity_received on bill receipt = how much of received pool this bill covers (same as billed here)
        db.add(
            VendorOrderLine(
                placement_id=placement.id,
                catalog_product_id=prod.id,
                our_product_id=prod.our_product_id,
                quantity=bq,
                quantity_remaining=bq,
                quantity_billed=bq,
                billed_amount=(ln.billed_amount or Decimal("0")).quantize(Decimal("0.01")),
                buying_price=prod.buying_price,
            )
        )
        db.add(
            StockReceiptLine(
                receipt_id=receipt.id,
                catalog_product_id=prod.id,
                our_product_id=prod.our_product_id,
                # Bill receipts do not receive stock — keep 0 so summary qty is not double-counted
                quantity_received=0,
                quantity_billed=bq,
                billed_amount=(ln.billed_amount or Decimal("0")).quantize(Decimal("0.01")),
                buying_price=prod.buying_price,
            )
        )
        reduce_pairs.append((prod.id, bq))
        line_summary.append(f"{prod.our_product_id} billed {bq}")

    reduce_unbilled_received(db, body.vendor_id, reduce_pairs)

    bill_total = receipt_bill_amount(db, receipt.id)
    if bill_total != 0:
        from app.models.accounts_payable import ApLedgerEntry

        existing_bill = (
            db.query(ApLedgerEntry)
            .filter(ApLedgerEntry.receipt_id == receipt.id, ApLedgerEntry.entry_type == "bill")
            .first()
        )
        if not existing_bill:
            post_bill_entry(
                db,
                vendor_id=body.vendor_id,
                receipt_id=receipt.id,
                amount=bill_total,
                description=f"Bill {body.bill_number or receipt.id} — ₹{bill_total}",
                actor_type=auth.actor_type,
                actor_id=auth.actor_id,
                actor_name=auth.actor_name,
                value_date=as_biz_date(now),
                created_at=now,
            )

    bill_product_ids = {ln.catalog_product_id for ln, _ in normalized}
    for dn_in in body.debit_notes or []:
        if dn_in.note_type == "item" and dn_in.catalog_product_id not in bill_product_ids:
            raise HTTPException(400, "debit note item must be from billed lines")
        create_debit_note(db, auth, vendor_id=body.vendor_id, receipt_id=receipt.id, body=dn_in)

    billed.updated_at = now
    received = get_open_order(db, body.vendor_id, "received")
    if received:
        received.updated_at = now

    log_from_auth(
        db,
        auth,
        action="bill_received",
        entity_type="stock_receipt",
        entity_id=receipt.id,
        entity_label=label,
        detail=", ".join(line_summary[:10]),
    )
    db.commit()
    return {
        "ok": True,
        "receipt_id": receipt.id,
        "billed_placement_id": placement.id,
        "vendor_id": body.vendor_id,
        "message": f"Billed {len(normalized)} product(s)",
        "document_url": None,
    }
