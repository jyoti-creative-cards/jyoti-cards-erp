from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import get_db
from app.deps import require_admin
from app.models.ap_bill import APBill
from app.models.catalog_product import CatalogProduct
from app.models.stock_balance import StockBalance
from app.models.vendor import Vendor
from app.models.vendor_bill import VendorBill
from app.models.vendor_order import VendorOrder
from app.services.catalog_storage import storage_configured, upload_bytes

router = APIRouter(prefix="/vendor-orders", tags=["vendor-orders"])

_DOC_PREFIX = "vendor_bills"


# ─── helpers ─────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _int(v) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def _pending(item: dict) -> int:
    return max(0, _int(item.get("qty_ordered")) - _int(item.get("qty_received")))


def _apply_stock_delta(db: Session, catalog_product_id: int, delta: int) -> None:
    row = db.get(StockBalance, catalog_product_id)
    if row is None:
        row = StockBalance(catalog_product_id=catalog_product_id, quantity=0, low_stock_threshold=0)
        db.add(row)
    row.quantity = int(row.quantity or 0) + delta
    db.add(row)


def _order_to_public(vo: VendorOrder, vendor: Vendor | None = None) -> dict:
    items = vo.items if isinstance(vo.items, list) else []
    total_ordered = sum(_int(it.get("qty_ordered")) for it in items)
    total_received = sum(_int(it.get("qty_received")) for it in items)
    total_pending = total_ordered - total_received
    total_ordered_value = sum(_int(it.get("qty_ordered")) * _float(it.get("unit_price")) for it in items)
    total_received_value = sum(_int(it.get("qty_received")) * _float(it.get("unit_price")) for it in items)

    # Bill discrepancy check
    bill_amount = _float(vo.bill_amount)
    bill_discrepancy = None
    if vo.bill_amount is not None and total_received_value > 0:
        diff = abs(bill_amount - total_received_value)
        bill_discrepancy = round(diff, 2) if diff > 0.01 else None

    return {
        "id": vo.id,
        "vendor_id": vo.vendor_id,
        "vendor_name": (vendor.company_name or vendor.person_name) if vendor else None,
        "status": vo.status,
        "items": items,
        "notes": vo.notes,
        "bill_number": vo.bill_number,
        "bill_amount": float(vo.bill_amount) if vo.bill_amount is not None else None,
        "bill_key": vo.bill_key,
        "bill_uploaded_at": vo.bill_uploaded_at.isoformat() if vo.bill_uploaded_at else None,
        "summary": {
            "total_items": len(items),
            "total_ordered": total_ordered,
            "total_received": total_received,
            "total_pending": total_pending,
            "total_ordered_value": round(total_ordered_value, 2),
            "total_received_value": round(total_received_value, 2),
            "bill_discrepancy": bill_discrepancy,
        },
        "created_at": vo.created_at.isoformat() if vo.created_at else None,
        "updated_at": vo.updated_at.isoformat() if vo.updated_at else None,
    }


def _get_or_create_open_order(db: Session, vendor_id: int) -> VendorOrder:
    vo = (
        db.query(VendorOrder)
        .filter(VendorOrder.vendor_id == vendor_id, VendorOrder.status == "open")
        .first()
    )
    if vo is None:
        vo = VendorOrder(vendor_id=vendor_id, status="open", items=[])
        db.add(vo)
        db.flush()
    return vo


# ─── schemas ──────────────────────────────────────────────────────────────────

class AddItemsBody(BaseModel):
    items: list[dict]  # [{catalog_product_id, qty_ordered, unit_price, notes?}]
    force_duplicate: bool = False


class ReceiveItemsBody(BaseModel):
    lines: list[dict]  # [{line_id?, catalog_product_id, qty_received, date_received?}]
    bill_number: str = ""          # vendor's invoice number (mandatory by law, required in UI)
    bill_amount: Optional[float] = None  # vendor's billed amount


# ─── routes ───────────────────────────────────────────────────────────────────

@router.get("", dependencies=[Depends(require_admin)])
def list_vendor_orders(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(VendorOrder).order_by(VendorOrder.updated_at.desc()).limit(500).all()
    out = []
    for vo in rows:
        vendor = db.get(Vendor, vo.vendor_id)
        out.append(_order_to_public(vo, vendor))
    return out


@router.get("/summary", dependencies=[Depends(require_admin)])
def vendor_orders_summary(db: Session = Depends(get_db)) -> list[dict]:
    """Per-vendor summary: pending items, received, AP."""
    vendors = db.query(Vendor).filter(Vendor.deleted_at.is_(None)).all()
    out = []
    for vendor in vendors:
        vname = vendor.company_name or vendor.person_name or f"Vendor #{vendor.id}"
        open_orders = (
            db.query(VendorOrder)
            .filter(VendorOrder.vendor_id == vendor.id, VendorOrder.status == "open")
            .all()
        )
        all_items = []
        for vo in open_orders:
            items = vo.items if isinstance(vo.items, list) else []
            all_items.extend(items)

        pending_items = [it for it in all_items if _pending(it) > 0]
        total_pending_value = sum(_pending(it) * _float(it.get("unit_price")) for it in pending_items)
        total_received_value = sum(_int(it.get("qty_received")) * _float(it.get("unit_price")) for it in all_items)

        out.append({
            "vendor_id": vendor.id,
            "vendor_name": vname,
            "open_orders": len(open_orders),
            "total_pending_items": sum(_pending(it) for it in all_items),
            "total_pending_value": round(total_pending_value, 2),
            "total_received_value": round(total_received_value, 2),
            "pending_lines": [
                {
                    "product_name": it.get("product_name"),
                    "catalog_product_id": it.get("catalog_product_id"),
                    "qty_ordered": _int(it.get("qty_ordered")),
                    "qty_received": _int(it.get("qty_received")),
                    "qty_pending": _pending(it),
                    "unit_price": _float(it.get("unit_price")),
                    "date_ordered": it.get("date_ordered"),
                }
                for it in pending_items
            ],
        })
    return out


@router.get("/{vendor_id}/open", dependencies=[Depends(require_admin)])
def get_open_order(vendor_id: int, db: Session = Depends(get_db)) -> dict:
    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    vo = _get_or_create_open_order(db, vendor_id)
    db.commit()
    db.refresh(vo)
    return _order_to_public(vo, vendor)


@router.get("/{order_id}", dependencies=[Depends(require_admin)])
def get_vendor_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    vendor = db.get(Vendor, vo.vendor_id)
    return _order_to_public(vo, vendor)


@router.post("/{vendor_id}/add-items", dependencies=[Depends(require_admin)])
def add_items_to_order(vendor_id: int, body: AddItemsBody, db: Session = Depends(get_db)) -> dict:
    """Add items to the vendor's open order. Creates order if none exists."""
    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    if not body.items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="items required")

    vo = _get_or_create_open_order(db, vendor_id)
    items: list = list(vo.items) if isinstance(vo.items, list) else []
    now = _now_iso()

    # Duplicate check: same vendor + same items + same qty added today
    if not body.force_duplicate:
        from datetime import timedelta as _td, timezone as _tz
        _ist_offset = _td(hours=5, minutes=30)
        _now_ist = datetime.now(_tz.utc) + _ist_offset
        _today_str = _now_ist.strftime("%Y-%m-%d")
        _req_pairs = sorted([(int(it.get("catalog_product_id", 0)), _int(it.get("qty_ordered", 0))) for it in body.items])
        # Check items already in today's open order
        _existing_today = sorted([
            (int(li.get("catalog_product_id", 0)), _int(li.get("qty_ordered", 0)))
            for li in items
            if (li.get("date_ordered") or "")[:10] == _today_str
        ])
        if _req_pairs and _existing_today and _req_pairs == _existing_today:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"duplicate": True, "message": f"Duplicate vendor order — same items with same quantities already added today.", "existing_id": vo.id},
            )

    for item in body.items:
        cid = int(item.get("catalog_product_id", 0))
        qty = _int(item.get("qty_ordered", 0))
        price = _float(item.get("unit_price", 0))
        if cid <= 0 or qty <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="each item needs catalog_product_id and qty_ordered >= 1")
        cat = db.get(CatalogProduct, cid)
        items.append({
            "line_id": uuid.uuid4().hex,
            "catalog_product_id": cid,
            "product_name": cat.our_product_id if cat else str(cid),
            "qty_ordered": qty,
            "qty_received": 0,
            "unit_price": price or (float(cat.buying_price or 0) if cat else 0),
            "date_ordered": now,
            "date_received": None,
            "notes": (item.get("notes") or "").strip(),
        })

    vo.items = items
    flag_modified(vo, "items")
    db.add(vo)
    db.commit()
    db.refresh(vo)
    return _order_to_public(vo, vendor)


@router.post("/{order_id}/receive", dependencies=[Depends(require_admin)])
def receive_items(order_id: int, body: ReceiveItemsBody, db: Session = Depends(get_db)) -> dict:
    """Mark items as received: update received qty, add to stock, create VendorBill + APBill."""
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    if vo.status != "open":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="can only receive against an open order")
    if not body.lines:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="lines required")
    if not body.bill_number.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bill_number is required — vendor bill must accompany goods")
    if body.bill_amount is None or body.bill_amount <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bill_amount is required — enter vendor's billed amount")

    vendor = db.get(Vendor, vo.vendor_id)
    items: list = list(vo.items) if isinstance(vo.items, list) else []
    now = _now_iso()

    # Build lookup by line_id and by catalog_product_id
    by_line_id = {it["line_id"]: it for it in items if "line_id" in it}
    by_cid: dict[int, list[dict]] = {}
    for it in items:
        cid = int(it.get("catalog_product_id", 0))
        by_cid.setdefault(cid, []).append(it)

    bill_lines = []  # track what was actually received in this batch for VendorBill
    total_received_value = 0.0

    for line in body.lines:
        qty = _int(line.get("qty_received", 0))
        if qty <= 0:
            continue
        date_recv = line.get("date_received") or now
        lid = line.get("line_id", "")
        cid = int(line.get("catalog_product_id", 0))

        matched = None
        if lid and lid in by_line_id:
            matched = by_line_id[lid]
        elif cid > 0 and cid in by_cid:
            # Match to first line with pending qty, or first line for over-delivery
            for it in by_cid[cid]:
                if _pending(it) > 0:
                    matched = it
                    break
            if matched is None:
                matched = by_cid[cid][0]  # allow over-delivery on an item

        if matched is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"no matching order line for product {cid or lid}")

        # Allow receiving more than ordered (batch size rounding in B2B)
        matched["qty_received"] = _int(matched.get("qty_received")) + qty
        matched["date_received"] = date_recv
        flag_modified(vo, "items")

        # Add to stock
        _apply_stock_delta(db, int(matched["catalog_product_id"]), qty)

        unit_price = _float(matched.get("unit_price", 0))
        total_received_value += qty * unit_price
        bill_lines.append({
            "catalog_product_id": int(matched["catalog_product_id"]),
            "product_name": matched.get("product_name", ""),
            "qty_received": qty,
            "unit_price": unit_price,
            "line_total": round(qty * unit_price, 4),
        })

    if not bill_lines:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no valid lines to receive")

    # Auto-close if all items fully received
    all_received = all(_pending(it) == 0 for it in items)
    if all_received:
        vo.status = "closed"

    vo.items = items
    vo.bill_number = body.bill_number.strip()
    vo.bill_amount = body.bill_amount
    vo.bill_uploaded_at = datetime.now(timezone.utc)
    flag_modified(vo, "items")
    db.add(vo)
    db.flush()  # flush so vo.id is available

    # Create VendorBill (vendor's invoice for this batch)
    vb = VendorBill(
        vendor_order_id=vo.id,
        vendor_id=vo.vendor_id,
        bill_number=body.bill_number.strip(),
        bill_amount=body.bill_amount,
        bill_lines=bill_lines,
        match_status="matched",
        notes=f"Received {len(bill_lines)} item(s). Calculated value: {round(total_received_value, 2)}. "
              f"{'Discrepancy: ' + str(round(abs(body.bill_amount - total_received_value), 2)) if abs(body.bill_amount - total_received_value) > 0.01 else 'No discrepancy.'}",
    )
    db.add(vb)
    db.flush()  # flush to get vb.id

    # Create APBill (accounts payable for vendor's bill amount)
    ap = APBill(
        vendor_bill_id=vb.id,
        vendor_id=vo.vendor_id,
        amount=body.bill_amount,
        status="open",
    )
    db.add(ap)

    db.commit()
    db.refresh(vo)
    return _order_to_public(vo, vendor)


@router.post("/{order_id}/upload-bill", dependencies=[Depends(require_admin)])
async def upload_vendor_bill(
    order_id: int,
    bill_number: str = Form(""),
    bill_amount: str = Form("0"),
    bill_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
) -> dict:
    """Upload vendor bill and record amount. Validates against received qty×price."""
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    vendor = db.get(Vendor, vo.vendor_id)

    # Upload file if provided
    bill_key = vo.bill_key
    if bill_file is not None and getattr(bill_file, "filename", None):
        try:
            raw = await bill_file.read()
            if raw and storage_configured():
                ext = Path(bill_file.filename or "bill").suffix or ".pdf"
                key = f"{_DOC_PREFIX}/vendor_{vo.vendor_id}/{uuid.uuid4().hex}{ext}"
                bill_key = upload_bytes(key, raw, bill_file.content_type or "application/pdf")
        except Exception as ex:
            print(f"Bill upload failed: {ex}")

    vo.bill_number = bill_number.strip() or vo.bill_number
    try:
        vo.bill_amount = float(bill_amount) if bill_amount else None
    except ValueError:
        vo.bill_amount = None
    vo.bill_key = bill_key
    vo.bill_uploaded_at = datetime.now(timezone.utc)
    db.add(vo)
    db.commit()
    db.refresh(vo)
    return _order_to_public(vo, vendor)


@router.get("/{order_id}/three-way-match", dependencies=[Depends(require_admin)])
def three_way_match(order_id: int, db: Session = Depends(get_db)) -> dict:
    """Three-way match view: ordered vs received vs vendor bills vs debit notes."""
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")

    items: list = list(vo.items) if isinstance(vo.items, list) else []
    ordered_value = sum(_float(it.get("unit_price", 0)) * _int(it.get("qty_ordered", 0)) for it in items)
    received_value = sum(_float(it.get("unit_price", 0)) * _int(it.get("qty_received", 0)) for it in items)

    # Vendor bills for this order
    vendor_bills = (
        db.query(VendorBill)
        .filter(VendorBill.vendor_order_id == order_id)
        .order_by(VendorBill.id.asc())
        .all()
    )
    bill_total = sum(float(vb.bill_amount or 0) for vb in vendor_bills)

    # Debit notes for this order
    from app.models.credit_debit_note import DebitNote
    debit_notes = (
        db.query(DebitNote)
        .filter(DebitNote.vendor_order_id == order_id)
        .order_by(DebitNote.id.asc())
        .all()
    )
    debit_total = sum(float(dn.amount or 0) for dn in debit_notes)

    # AP bills
    from app.models.ap_bill import APBill
    ap_rows = (
        db.query(APBill)
        .join(VendorBill, APBill.vendor_bill_id == VendorBill.id)
        .filter(VendorBill.vendor_order_id == order_id)
        .all()
    )
    ap_total = sum(float(ap.amount or 0) for ap in ap_rows)
    ap_open = sum(float(ap.amount or 0) for ap in ap_rows if ap.status == "open")

    # Per-item view
    line_match = []
    for it in items:
        qty_ord = _int(it.get("qty_ordered", 0))
        qty_recv = _int(it.get("qty_received", 0))
        pending = max(0, qty_ord - qty_recv)
        over = max(0, qty_recv - qty_ord)
        line_match.append({
            "product_name": it.get("product_name", ""),
            "catalog_product_id": it.get("catalog_product_id"),
            "unit_price": _float(it.get("unit_price", 0)),
            "qty_ordered": qty_ord,
            "qty_received": qty_recv,
            "qty_pending": pending,
            "qty_over_delivered": over,
            "ordered_value": round(qty_ord * _float(it.get("unit_price", 0)), 2),
            "received_value": round(qty_recv * _float(it.get("unit_price", 0)), 2),
        })

    return {
        "order_id": order_id,
        "status": vo.status,
        "ordered_value": round(ordered_value, 2),
        "received_value": round(received_value, 2),
        "bill_total": round(bill_total, 2),
        "debit_total": round(debit_total, 2),
        "net_payable": round(bill_total - debit_total, 2),
        "ap_open": round(ap_open, 2),
        "value_discrepancy": round(bill_total - received_value, 2),
        "line_items": line_match,
        "vendor_bills": [
            {
                "id": vb.id,
                "bill_number": vb.bill_number,
                "bill_amount": float(vb.bill_amount or 0),
                "created_at": vb.created_at.isoformat() if vb.created_at else None,
                "lines": vb.bill_lines or [],
            }
            for vb in vendor_bills
        ],
        "debit_notes": [
            {
                "id": dn.id,
                "amount": float(dn.amount or 0),
                "note_type": getattr(dn, "note_type", "value"),
                "reason": dn.reason,
                "note_date": dn.note_date.isoformat() if dn.note_date else None,
                "items": getattr(dn, "items", None),
            }
            for dn in debit_notes
        ],
        "ap_bills": [
            {
                "id": ap.id,
                "amount": float(ap.amount or 0),
                "status": ap.status,
                "paid_at": ap.paid_at.isoformat() if ap.paid_at else None,
            }
            for ap in ap_rows
        ],
    }


@router.patch("/{order_id}/close", dependencies=[Depends(require_admin)])
def close_vendor_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    vo.status = "closed"
    db.add(vo)
    db.commit()
    db.refresh(vo)
    vendor = db.get(Vendor, vo.vendor_id)
    return _order_to_public(vo, vendor)


@router.patch("/{order_id}/reopen", dependencies=[Depends(require_admin)])
def reopen_vendor_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    vo.status = "open"
    db.add(vo)
    db.commit()
    db.refresh(vo)
    vendor = db.get(Vendor, vo.vendor_id)
    return _order_to_public(vo, vendor)
