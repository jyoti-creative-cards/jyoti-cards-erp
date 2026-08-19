from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.ap_bill import APBill
from app.models.catalog_product import CatalogProduct
from app.models.credit_debit_note import DebitNote
from app.models.stock_balance import StockBalance
from app.models.vendor import Vendor
from app.models.vendor_bill import VendorBill
from app.models.vendor_order import VendorOrder
from app.models.vendor_order_line import VendorOrderLine
from app.models.vendor_order_note import VendorOrderNote
from app.models.vendor_receipt_line import VendorReceiptLine
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


def _line_pending(line: VendorOrderLine) -> int:
    return max(0, line.qty_ordered - line.qty_received)


def _apply_stock_delta(db: Session, catalog_product_id: int, delta: int) -> None:
    row = db.get(StockBalance, catalog_product_id)
    if row is None:
        row = StockBalance(catalog_product_id=catalog_product_id, quantity=0, low_stock_threshold=0)
        db.add(row)
    row.quantity = int(row.quantity or 0) + delta
    db.add(row)


def _line_to_dict(line: VendorOrderLine) -> dict:
    return {
        "line_id": line.line_id,
        "id": line.id,
        "sub_order_no": getattr(line, "sub_order_no", 1) or 1,
        "catalog_product_id": line.catalog_product_id,
        "product_name": line.product_name,
        "our_product_id": line.our_product_id,
        "qty_ordered": line.qty_ordered,
        "qty_received": line.qty_received,
        "qty_billed": line.qty_billed,
        "unit_price": float(line.unit_price or 0),
        "billed_price": float(line.billed_price) if line.billed_price is not None else None,
        "date_ordered": line.date_ordered.isoformat() if line.date_ordered else None,
        "date_received": line.date_received.isoformat() if line.date_received else None,
        "notes": line.notes,
    }


def _note_to_dict(n: VendorOrderNote) -> dict:
    return {
        "id": n.id,
        "stage": n.stage,
        "body": n.body,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def _order_to_public(vo: VendorOrder, vendor: Vendor | None = None, db: Session | None = None) -> dict:
    # Query lines and notes directly (bypass selectin relationship which is unreliable)
    if db is not None:
        lines = (
            db.query(VendorOrderLine)
            .filter(VendorOrderLine.vendor_order_id == vo.id)
            .order_by(VendorOrderLine.id)
            .all()
        )
        notes = (
            db.query(VendorOrderNote)
            .filter(VendorOrderNote.vendor_order_id == vo.id)
            .order_by(VendorOrderNote.created_at)
            .all()
        )
    else:
        # Fallback: try relationship, protect against scalar return
        raw_lines = vo.lines
        lines = list(raw_lines) if hasattr(raw_lines, "__iter__") else ([] if raw_lines is None else [raw_lines])
        raw_notes = vo.order_notes
        notes = list(raw_notes) if hasattr(raw_notes, "__iter__") else ([] if raw_notes is None else [raw_notes])

    total_ordered = sum(l.qty_ordered for l in lines)
    total_received = sum(l.qty_received for l in lines)
    total_pending = total_ordered - total_received
    total_ordered_value = sum(l.qty_ordered * _float(l.unit_price) for l in lines)
    total_received_value = sum(l.qty_received * _float(l.unit_price) for l in lines)

    return {
        "id": vo.id,
        "vendor_id": vo.vendor_id,
        "vendor_name": (vendor.company_name or vendor.person_name) if vendor else None,
        "status": vo.status,
        "items": [_line_to_dict(l) for l in lines],
        "notes_thread": [_note_to_dict(n) for n in notes],
        "notes": next((n.body for n in reversed(notes) if n.stage == "placed"), None),
        "summary": {
            "total_items": len(lines),
            "total_ordered": total_ordered,
            "total_received": total_received,
            "total_pending": total_pending,
            "total_ordered_value": round(total_ordered_value, 2),
            "total_received_value": round(total_received_value, 2),
        },
        "created_at": vo.created_at.isoformat() if vo.created_at else None,
        "updated_at": vo.updated_at.isoformat() if vo.updated_at else None,
    }


def _get_or_create_placed_order(db: Session, vendor_id: int) -> VendorOrder:
    """Always returns the single placed order for this vendor, creating if needed."""
    vo = (
        db.query(VendorOrder)
        .filter(VendorOrder.vendor_id == vendor_id, VendorOrder.status == "placed")
        .first()
    )
    if vo is None:
        vo = VendorOrder(vendor_id=vendor_id, status="placed")
        db.add(vo)
        db.flush()
        db.refresh(vo)
    return vo


# ─── Rule Engine ─────────────────────────────────────────────────────────────

class ReceiveSessionLine(BaseModel):
    line_id: str
    catalog_product_id: Optional[int] = None
    qty_received: int = 0
    qty_billed: Optional[int] = None   # defaults to qty_received
    billed_price: Optional[float] = None  # defaults to po unit_price
    date_received: Optional[str] = None


def compute_analysis(
    session_lines: list[ReceiveSessionLine],
    order_lines: list[VendorOrderLine],
    bill_amount: float,
) -> dict:
    """
    Apply the rule engine to determine discrepancies and available buttons.

    Returns:
        has_quantity_discrepancy, has_price_discrepancy, has_dn, keep_open_allowed,
        quantity_dn, price_dn, total_dn, buttons, per_line_detail
    """
    by_line_id = {l.line_id: l for l in order_lines}
    by_cid: dict[int, VendorOrderLine] = {}
    for l in order_lines:
        if l.catalog_product_id and l.catalog_product_id not in by_cid:
            by_cid[l.catalog_product_id] = l

    has_quantity_discrepancy = False
    has_price_discrepancy = False
    keep_open_allowed = False
    quantity_dn = 0.0
    expected_bill = 0.0
    per_line_detail = []

    for sl in session_lines:
        R = _int(sl.qty_received)
        if R <= 0:
            continue

        # Find order line
        matched: VendorOrderLine | None = by_line_id.get(sl.line_id)
        if matched is None and sl.catalog_product_id:
            matched = by_cid.get(sl.catalog_product_id)
        if matched is None:
            continue

        P = _float(matched.unit_price)
        B = sl.qty_billed if sl.qty_billed is not None else R

        # After this session: cumulative received
        cumulative_received = matched.qty_received + R
        O = matched.qty_ordered

        # Quantity discrepancy
        line_qty_dn = (B - R) * P
        quantity_dn += line_qty_dn
        expected_bill += B * P

        if B != R:
            has_quantity_discrepancy = True

        # Keep open allowed if order not fully received, or billed > received
        if cumulative_received < O or B > R:
            keep_open_allowed = True

        per_line_detail.append({
            "line_id": sl.line_id,
            "product_name": matched.product_name,
            "our_product_id": matched.our_product_id,
            "qty_ordered": O,
            "qty_already_received": matched.qty_received,
            "qty_received_this_session": R,
            "qty_cumulative_received": cumulative_received,
            "qty_billed": B,
            "po_unit_price": P,
            "billed_price": sl.billed_price if sl.billed_price is not None else P,
            "quantity_dn_this_line": round(line_qty_dn, 4),
        })

    # Price discrepancy: actual bill vs expected (billed_qty * po_price per line)
    price_dn = round(bill_amount - expected_bill, 4)
    if abs(price_dn) > 0.01:
        has_price_discrepancy = True

    has_dn = has_quantity_discrepancy or has_price_discrepancy
    total_dn = round(quantity_dn + price_dn, 4)

    # Determine buttons
    if not has_dn:
        buttons = ["accept", "keep_open"] if keep_open_allowed else ["accept"]
    else:
        buttons = ["keep_open", "debit_note"] if keep_open_allowed else ["debit_note"]

    return {
        "has_quantity_discrepancy": has_quantity_discrepancy,
        "has_price_discrepancy": has_price_discrepancy,
        "has_dn": has_dn,
        "keep_open_allowed": keep_open_allowed,
        "quantity_dn": round(quantity_dn, 4),
        "price_dn": price_dn,
        "total_dn": total_dn,
        "buttons": buttons,
        "per_line": per_line_detail,
        "expected_bill": round(expected_bill, 2),
        "bill_amount": round(bill_amount, 2),
    }


# ─── schemas ─────────────────────────────────────────────────────────────────

class AddItemsBody(BaseModel):
    items: list[dict]
    note: str = ""
    force_duplicate: bool = False


class ReceiveItemsBody(BaseModel):
    lines: list[dict]
    bill_number: str = ""
    bill_amount: Optional[float] = None
    additional_charges: Optional[float] = None
    action: str = "accept"            # "accept" | "keep_open" | "debit_note"
    debit_note_reason: str = ""
    note: str = ""


class AddNoteBody(BaseModel):
    stage: str
    body: str


# ─── routes ──────────────────────────────────────────────────────────────────

@router.get("", dependencies=[Depends(require_admin)])
def list_vendor_orders(
    vendor_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = db.query(VendorOrder).order_by(VendorOrder.updated_at.desc())
    if vendor_id is not None:
        q = q.filter(VendorOrder.vendor_id == vendor_id)
    rows = q.limit(500).all()
    out = []
    for vo in rows:
        vendor = db.get(Vendor, vo.vendor_id)
        out.append(_order_to_public(vo, vendor, db))
    return out


@router.get("/summary", dependencies=[Depends(require_admin)])
def vendor_orders_summary(db: Session = Depends(get_db)) -> list[dict]:
    vendors = db.query(Vendor).filter(Vendor.deleted_at.is_(None)).all()
    out = []
    for vendor in vendors:
        vname = vendor.company_name or vendor.person_name or f"Vendor #{vendor.id}"
        placed_orders = (
            db.query(VendorOrder)
            .filter(VendorOrder.vendor_id == vendor.id, VendorOrder.status == "placed")
            .all()
        )
        all_lines: list[VendorOrderLine] = []
        for vo in placed_orders:
            all_lines.extend(vo.lines or [])

        pending_lines = [l for l in all_lines if _line_pending(l) > 0]
        total_pending_value = sum(_line_pending(l) * _float(l.unit_price) for l in pending_lines)
        total_received_value = sum(l.qty_received * _float(l.unit_price) for l in all_lines)

        out.append({
            "vendor_id": vendor.id,
            "vendor_name": vname,
            "open_orders": len(placed_orders),
            "total_pending_items": sum(_line_pending(l) for l in all_lines),
            "total_pending_value": round(total_pending_value, 2),
            "total_received_value": round(total_received_value, 2),
            "pending_lines": [
                {
                    "product_name": l.product_name,
                    "catalog_product_id": l.catalog_product_id,
                    "qty_ordered": l.qty_ordered,
                    "qty_received": l.qty_received,
                    "qty_pending": _line_pending(l),
                    "unit_price": float(l.unit_price or 0),
                    "date_ordered": l.date_ordered.isoformat() if l.date_ordered else None,
                }
                for l in pending_lines
            ],
        })
    return out


@router.get("/{vendor_id}/open", dependencies=[Depends(require_admin)])
def get_open_order(vendor_id: int, db: Session = Depends(get_db)) -> dict:
    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    vo = _get_or_create_placed_order(db, vendor_id)
    db.commit()
    db.refresh(vo)
    return _order_to_public(vo, vendor, db)


@router.get("/{order_id}", dependencies=[Depends(require_admin)])
def get_vendor_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    vendor = db.get(Vendor, vo.vendor_id)
    return _order_to_public(vo, vendor, db)


@router.post("/{vendor_id}/add-items", dependencies=[Depends(require_admin)])
def add_items_to_order(vendor_id: int, body: AddItemsBody, db: Session = Depends(get_db)) -> dict:
    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    if not body.items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="items required")

    vo = _get_or_create_placed_order(db, vendor_id)

    # Determine next sub_order_no for this order
    from sqlalchemy import func as _func
    max_sub = db.query(_func.max(VendorOrderLine.sub_order_no)).filter(
        VendorOrderLine.vendor_order_id == vo.id
    ).scalar() or 0
    next_sub_no = max_sub + 1

    # Duplicate check
    if not body.force_duplicate:
        from datetime import timedelta as _td
        _ist_offset = _td(hours=5, minutes=30)
        _today_str = (datetime.now(timezone.utc) + _ist_offset).strftime("%Y-%m-%d")
        existing_lines = (
            db.query(VendorOrderLine)
            .filter(VendorOrderLine.vendor_order_id == vo.id)
            .all()
        )
        _req_pairs = sorted([(int(it.get("catalog_product_id", 0)), _int(it.get("qty_ordered", 0))) for it in body.items])
        _existing_today = sorted([
            (l.catalog_product_id, l.qty_ordered) for l in existing_lines
            if l.date_ordered and l.date_ordered.strftime("%Y-%m-%d") == _today_str
        ])
        if _req_pairs and _existing_today and _req_pairs == _existing_today:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"duplicate": True, "message": "Duplicate vendor order — same items with same quantities already added today.", "existing_id": vo.id},
            )

    for item in body.items:
        cid = int(item.get("catalog_product_id", 0))
        qty = _int(item.get("qty_ordered", 1))
        price = _float(item.get("unit_price", 0))
        cp = db.get(CatalogProduct, cid) if cid else None
        pname = cp.our_product_id if cp else item.get("product_name", "")
        our_id = cp.our_product_id if cp else ""
        db.add(VendorOrderLine(
            line_id=uuid.uuid4().hex,
            vendor_order_id=vo.id,
            catalog_product_id=cid or None,
            product_name=pname,
            our_product_id=our_id,
            qty_ordered=qty,
            qty_received=0,
            qty_billed=0,
            unit_price=price,
            date_ordered=datetime.now(timezone.utc),
            notes=item.get("notes"),
            sub_order_no=next_sub_no,
        ))

    if body.note and body.note.strip():
        db.add(VendorOrderNote(vendor_order_id=vo.id, stage="placed", body=body.note.strip()))

    db.add(vo)
    db.commit()
    db.refresh(vo)
    return _order_to_public(vo, vendor, db)


# ─── notes ────────────────────────────────────────────────────────────────────

@router.get("/{order_id}/notes", dependencies=[Depends(require_admin)])
def list_notes(order_id: int, db: Session = Depends(get_db)) -> list[dict]:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    notes = (
        db.query(VendorOrderNote)
        .filter(VendorOrderNote.vendor_order_id == order_id)
        .order_by(VendorOrderNote.created_at.asc())
        .all()
    )
    return [_note_to_dict(n) for n in notes]


@router.post("/{order_id}/notes", dependencies=[Depends(require_admin)])
def add_note(order_id: int, body: AddNoteBody, db: Session = Depends(get_db)) -> dict:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    if not body.body.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="note body required")
    valid_stages = {"placed", "received", "billed", "settled"}
    if body.stage not in valid_stages:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"stage must be one of {valid_stages}")
    n = VendorOrderNote(vendor_order_id=order_id, stage=body.stage, body=body.body.strip())
    db.add(n)
    db.commit()
    db.refresh(n)
    return _note_to_dict(n)


# ─── receive: analyze (no commit) ────────────────────────────────────────────

@router.post("/{order_id}/receive/analyze", dependencies=[Depends(require_admin)])
def analyze_receive(
    order_id: int,
    body: ReceiveItemsBody,
    db: Session = Depends(get_db),
) -> dict:
    """Run the rule engine on the entered quantities. Returns analysis + buttons. Does NOT commit anything."""
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    order_lines = list(vo.lines or [])
    session_lines = [ReceiveSessionLine(**l) for l in body.lines if _int(l.get("qty_received", 0)) > 0]
    bill_amt = float(body.bill_amount or 0) + float(body.additional_charges or 0)
    return compute_analysis(session_lines, order_lines, bill_amt)


# ─── receive: commit ─────────────────────────────────────────────────────────

@router.post("/{order_id}/receive", dependencies=[Depends(require_admin)])
def receive_items(order_id: int, body: ReceiveItemsBody, db: Session = Depends(get_db)) -> dict:
    try:
        return _receive_items_impl(order_id, body, db)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Receive failed: {type(e).__name__}: {e}") from e


def _receive_items_impl(order_id: int, body: ReceiveItemsBody, db: Session) -> dict:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    if vo.status != "placed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="can only receive against a placed order")
    if not body.lines:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="lines required")

    action = body.action.strip().lower()
    if action not in ("accept", "keep_open", "debit_note"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="action must be accept | keep_open | debit_note")

    # For accept / debit_note — need billing details
    if action in ("accept", "debit_note"):
        if not body.bill_number.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bill_number required for accept/debit_note")
        if not body.bill_amount or body.bill_amount <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bill_amount required for accept/debit_note")

    vendor = db.get(Vendor, vo.vendor_id)
    order_lines: list[VendorOrderLine] = list(vo.lines or [])
    by_line_id = {l.line_id: l for l in order_lines}
    by_cid: dict[int, list[VendorOrderLine]] = {}
    for l in order_lines:
        if l.catalog_product_id:
            by_cid.setdefault(l.catalog_product_id, []).append(l)

    now = _now_iso()
    session_lines_valid: list[tuple[dict, VendorOrderLine]] = []

    for line in body.lines:
        qty = _int(line.get("qty_received", 0))
        if qty <= 0:
            continue
        lid = line.get("line_id", "")
        cid = int(line.get("catalog_product_id", 0))

        matched: VendorOrderLine | None = by_line_id.get(lid)
        if matched is None and cid > 0:
            for ol in by_cid.get(cid, []):
                if _line_pending(ol) > 0:
                    matched = ol
                    break
            if matched is None and cid in by_cid:
                matched = by_cid[cid][0]

        if matched is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"no matching order line for {cid or lid}")
        session_lines_valid.append((line, matched))

    if not session_lines_valid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no valid lines to receive")

    # ── Step 1: Always update stock + qty_received ─────────────────────────
    for line, matched in session_lines_valid:
        qty = _int(line.get("qty_received", 0))
        date_recv_str = line.get("date_received") or now
        try:
            recv_dt = datetime.fromisoformat(date_recv_str)
        except (ValueError, TypeError):
            recv_dt = datetime.now(timezone.utc)

        matched.qty_received += qty
        matched.date_received = recv_dt
        db.add(matched)
        _apply_stock_delta(db, matched.catalog_product_id, qty)

    # ── Step 2: Attach note if provided ───────────────────────────────────
    note_stage = "received" if action == "keep_open" else "billed"
    if body.note and body.note.strip():
        db.add(VendorOrderNote(vendor_order_id=vo.id, stage=note_stage, body=body.note.strip()))

    if action == "keep_open":
        db.commit()
        db.refresh(vo)
        vendor = db.get(Vendor, vo.vendor_id)
        return {**_order_to_public(vo, vendor, db), "action_taken": "keep_open"}

    # ── Step 3: accept / debit_note — create billing records ──────────────
    total_bill = float(body.bill_amount or 0) + float(body.additional_charges or 0)

    bill_lines = []
    for line, matched in session_lines_valid:
        qty = _int(line.get("qty_received", 0))
        qty_billed = _int(line.get("qty_billed", qty))
        unit_price = _float(matched.unit_price)
        billed_price = _float(line.get("billed_price", unit_price))

        matched.qty_billed += qty_billed
        matched.billed_price = billed_price
        db.add(matched)

        bill_lines.append({
            "catalog_product_id": matched.catalog_product_id,
            "product_name": matched.product_name or "",
            "line_id": matched.line_id,
            "qty_received": qty,
            "qty_billed": qty_billed,
            "unit_price": unit_price,
            "billed_price": billed_price,
            "line_total": round(qty * unit_price, 4),
        })

    db.flush()

    vb = VendorBill(
        vendor_order_id=vo.id,
        vendor_id=vo.vendor_id,
        bill_number=body.bill_number.strip(),
        bill_amount=total_bill,
        bill_lines=bill_lines,
        match_status="matched",
    )
    db.add(vb)
    db.flush()

    # Insert receipt line rows
    for bl in bill_lines:
        date_recv_str = next(
            (l.get("date_received") for l, _ in session_lines_valid if _.line_id == bl["line_id"]),
            now,
        )
        try:
            recv_dt = datetime.fromisoformat(date_recv_str or now)
        except (ValueError, TypeError):
            recv_dt = datetime.now(timezone.utc)
        db.add(VendorReceiptLine(
            vendor_bill_id=vb.id,
            vendor_order_id=vo.id,
            vendor_id=vo.vendor_id,
            catalog_product_id=bl["catalog_product_id"],
            product_name=bl.get("product_name", ""),
            order_line_id=bl.get("line_id"),
            qty_received=bl["qty_received"],
            qty_billed=bl["qty_billed"],
            order_price=bl["unit_price"],
            billed_price=bl["billed_price"],
            qty_discrepancy=bl["qty_billed"] - bl["qty_received"],
            price_discrepancy=round(bl["billed_price"] - bl["unit_price"], 4),
            receipt_date=recv_dt,
        ))

    # ── Step 4: Debit Note if requested ───────────────────────────────────
    dn_result: dict | None = None
    if action == "debit_note":
        session_sl = [ReceiveSessionLine(**l) for l in body.lines if _int(l.get("qty_received", 0)) > 0]
        analysis = compute_analysis(session_sl, order_lines, total_bill)
        total_dn = analysis["total_dn"]
        quantity_dn = analysis["quantity_dn"]
        price_dn = analysis["price_dn"]

        dn = DebitNote(
            vendor_order_id=vo.id,
            vendor_bill_id=vb.id,
            vendor_id=vo.vendor_id,
            amount=abs(total_dn),
            reason=body.debit_note_reason.strip() or f"Auto: qty_dn={quantity_dn}, price_dn={price_dn}",
            note_type="item" if analysis["has_quantity_discrepancy"] else "value",
            note_date=datetime.now(timezone.utc).date(),
            items=[
                {
                    "quantity_component": quantity_dn,
                    "price_component": price_dn,
                    "total": total_dn,
                    "lines": analysis["per_line"],
                }
            ],
        )
        db.add(dn)
        db.flush()

        # Adjust the AP amount: positive DN = reduce AP, negative DN = increase AP
        ap_amount = round(total_bill - total_dn, 4)
        dn_result = {
            "debit_note_id": dn.id,
            "quantity_dn": quantity_dn,
            "price_dn": price_dn,
            "total_dn": total_dn,
            "ap_amount_after_dn": ap_amount,
        }
    else:
        ap_amount = total_bill

    # ── Step 5: Create AP bill ────────────────────────────────────────────
    ap_error: str | None = None
    try:
        ap = APBill(
            vendor_bill_id=vb.id,
            vendor_id=vo.vendor_id,
            purchase_order_id=vo.id,
            amount=max(0.0, ap_amount),
            status="open",
        )
        db.add(ap)
        from app.services.accounting import seed_chart_accounts, record_ap_bill
        seed_chart_accounts(db)
        record_ap_bill(db, ap)
    except Exception as ap_exc:
        ap_error = f"{type(ap_exc).__name__}: {ap_exc}"

    db.commit()
    db.refresh(vo)
    vendor = db.get(Vendor, vo.vendor_id)
    result = {**_order_to_public(vo, vendor, db), "action_taken": action}
    if dn_result:
        result["debit_note"] = dn_result
    if ap_error:
        result["ap_warning"] = f"Stock updated. AP creation failed: {ap_error}"
    return result


# ─── bill upload ─────────────────────────────────────────────────────────────

@router.post("/{order_id}/upload-bill", dependencies=[Depends(require_admin)])
async def upload_bill(
    order_id: int,
    bill_number: str = Form(...),
    bill_amount: Optional[str] = Form(None),
    bill_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
) -> dict:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    vendor = db.get(Vendor, vo.vendor_id)
    bill_key: str | None = None
    if bill_file and storage_configured():
        content = await bill_file.read()
        suffix = "".join(c for c in (bill_file.filename or "bill.pdf") if c.isalnum() or c in "._-")
        path = f"{_DOC_PREFIX}/{vo.vendor_id}/{order_id}_{suffix}"
        bill_key = upload_bytes(content, path, bill_file.content_type or "application/octet-stream")
    vb = (
        db.query(VendorBill)
        .filter(VendorBill.vendor_order_id == order_id)
        .order_by(VendorBill.id.desc())
        .first()
    )
    if vb:
        vb.bill_number = bill_number.strip()
        if bill_amount:
            try:
                vb.bill_amount = float(bill_amount)
            except ValueError:
                pass
        if bill_key:
            vb.document_key = bill_key
        db.add(vb)
    db.commit()
    db.refresh(vo)
    return _order_to_public(vo, vendor, db)


# ─── order status ─────────────────────────────────────────────────────────────

@router.patch("/{order_id}/close", dependencies=[Depends(require_admin)])
def close_vendor_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    vo.status = "closed"
    db.add(vo)
    db.commit()
    db.refresh(vo)
    return _order_to_public(vo, db.get(Vendor, vo.vendor_id), db)


@router.patch("/{order_id}/reopen", dependencies=[Depends(require_admin)])
def reopen_vendor_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    vo.status = "placed"
    db.add(vo)
    db.commit()
    db.refresh(vo)
    return _order_to_public(vo, db.get(Vendor, vo.vendor_id), db)


# ─── line edit / delete ───────────────────────────────────────────────────────

class UpdateLineBody(BaseModel):
    qty_ordered: Optional[int] = None
    unit_price: Optional[float] = None
    notes: Optional[str] = None


@router.patch("/{order_id}/lines/{line_id}", dependencies=[Depends(require_admin)])
def update_order_line(order_id: int, line_id: str, body: UpdateLineBody, db: Session = Depends(get_db)) -> dict:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    line = db.query(VendorOrderLine).filter(
        VendorOrderLine.vendor_order_id == order_id,
        VendorOrderLine.line_id == line_id,
    ).first()
    if line is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="line not found")
    if body.qty_ordered is not None:
        if body.qty_ordered < 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="qty_ordered must be >= 1")
        line.qty_ordered = body.qty_ordered
    if body.unit_price is not None:
        if body.unit_price < 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="unit_price cannot be negative")
        line.unit_price = body.unit_price
    if body.notes is not None:
        line.notes = body.notes.strip()
    db.add(line)
    db.commit()
    db.refresh(vo)
    return _order_to_public(vo, db.get(Vendor, vo.vendor_id), db)


@router.delete("/{order_id}/lines/{line_id}", dependencies=[Depends(require_admin)])
def delete_order_line(order_id: int, line_id: str, db: Session = Depends(get_db)) -> dict:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    line = db.query(VendorOrderLine).filter(
        VendorOrderLine.vendor_order_id == order_id,
        VendorOrderLine.line_id == line_id,
    ).first()
    if line is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="line not found")
    db.delete(line)
    db.commit()
    db.refresh(vo)
    return _order_to_public(vo, db.get(Vendor, vo.vendor_id), db)


@router.delete("/{order_id}", dependencies=[Depends(require_admin)])
def cancel_vendor_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    vendor = db.get(Vendor, vo.vendor_id)
    vo.status = "cancelled"
    db.add(VendorOrderNote(vendor_order_id=vo.id, stage="placed", body="Order cancelled."))
    db.commit()
    db.refresh(vo)
    return _order_to_public(vo, vendor, db)


# ─── receipt lines ────────────────────────────────────────────────────────────

@router.get("/{order_id}/receipt-lines", dependencies=[Depends(require_admin)])
def get_receipt_lines(order_id: int, db: Session = Depends(get_db)) -> list[dict]:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    rows = (
        db.query(VendorReceiptLine)
        .filter(VendorReceiptLine.vendor_order_id == order_id)
        .order_by(VendorReceiptLine.receipt_date.desc(), VendorReceiptLine.id.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "vendor_bill_id": r.vendor_bill_id,
            "catalog_product_id": r.catalog_product_id,
            "product_name": r.product_name,
            "qty_received": r.qty_received,
            "qty_billed": r.qty_billed,
            "order_price": float(r.order_price) if r.order_price is not None else None,
            "billed_price": float(r.billed_price) if r.billed_price is not None else None,
            "qty_discrepancy": r.qty_discrepancy,
            "price_discrepancy": float(r.price_discrepancy) if r.price_discrepancy is not None else None,
            "receipt_date": r.receipt_date.isoformat() if r.receipt_date else None,
            "is_resolved": getattr(r, "is_resolved", None),
            "resolve_comment": getattr(r, "resolve_comment", None),
        }
        for r in rows
    ]


# ─── billing history ──────────────────────────────────────────────────────────

@router.get("/{order_id}/billing-history", dependencies=[Depends(require_admin)])
def get_billing_history(order_id: int, db: Session = Depends(get_db)) -> list[dict]:
    """Return all VendorBills for this order with their APBill + DebitNote info."""
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")

    vendor_bills = (
        db.query(VendorBill)
        .filter(VendorBill.vendor_order_id == order_id)
        .order_by(VendorBill.id.desc())
        .all()
    )

    out = []
    for vb in vendor_bills:
        ap = db.query(APBill).filter(APBill.vendor_bill_id == vb.id).first()
        dns = db.query(DebitNote).filter(DebitNote.vendor_bill_id == vb.id).all()
        out.append({
            "vendor_bill_id": vb.id,
            "bill_number": vb.bill_number,
            "bill_amount": float(vb.bill_amount or 0),
            "bill_lines": vb.bill_lines or [],
            "match_status": vb.match_status,
            "created_at": vb.created_at.isoformat() if vb.created_at else None,
            "ap_bill": {
                "id": ap.id,
                "amount": float(ap.amount or 0),
                "status": ap.status,
                "paid_at": ap.paid_at.isoformat() if ap.paid_at else None,
            } if ap else None,
            "debit_notes": [
                {
                    "id": dn.id,
                    "amount": float(dn.amount or 0),
                    "reason": dn.reason,
                    "note_type": dn.note_type,
                    "items": dn.items,
                    "note_date": dn.note_date.isoformat() if dn.note_date else None,
                }
                for dn in dns
            ],
        })
    return out


# ─── three-way match ──────────────────────────────────────────────────────────

@router.get("/{order_id}/three-way-match", dependencies=[Depends(require_admin)])
def three_way_match(order_id: int, db: Session = Depends(get_db)) -> dict:
    vo = db.get(VendorOrder, order_id)
    if vo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor order not found")
    order_lines: list[VendorOrderLine] = list(vo.lines or [])
    ordered_value = sum(_float(l.unit_price) * l.qty_ordered for l in order_lines)
    received_value = sum(_float(l.unit_price) * l.qty_received for l in order_lines)
    vendor_bills = (
        db.query(VendorBill)
        .filter(VendorBill.vendor_order_id == order_id)
        .order_by(VendorBill.id.asc())
        .all()
    )
    bill_total = sum(float(vb.bill_amount or 0) for vb in vendor_bills)
    debit_notes = (
        db.query(DebitNote)
        .filter(DebitNote.vendor_order_id == order_id)
        .order_by(DebitNote.id.asc())
        .all()
    )
    debit_total = sum(float(dn.amount or 0) for dn in debit_notes)
    ap_rows = (
        db.query(APBill)
        .join(VendorBill, APBill.vendor_bill_id == VendorBill.id)
        .filter(VendorBill.vendor_order_id == order_id)
        .all()
    )
    ap_open = sum(float(ap.amount or 0) for ap in ap_rows if ap.status == "open")
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
        "line_items": [
            {
                "product_name": l.product_name,
                "catalog_product_id": l.catalog_product_id,
                "unit_price": float(l.unit_price or 0),
                "qty_ordered": l.qty_ordered,
                "qty_received": l.qty_received,
                "qty_pending": _line_pending(l),
                "ordered_value": round(l.qty_ordered * _float(l.unit_price), 2),
                "received_value": round(l.qty_received * _float(l.unit_price), 2),
            }
            for l in order_lines
        ],
        "vendor_bills": [{"id": vb.id, "bill_number": vb.bill_number, "bill_amount": float(vb.bill_amount or 0)} for vb in vendor_bills],
        "debit_notes": [{"id": dn.id, "amount": float(dn.amount or 0), "reason": dn.reason} for dn in debit_notes],
        "ap_bills": [{"id": ap.id, "amount": float(ap.amount or 0), "status": ap.status} for ap in ap_rows],
    }
