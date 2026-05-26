from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, cast
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.catalog_product import CatalogProduct
from app.models.stock_receipt import StockReceipt
from app.models.vendor import Vendor
from app.models.vendor_purchase_order import VendorPurchaseOrder
from app.schemas.purchase_order import (
    PurchaseOrderCreate,
    PurchaseOrderLinePublic,
    PurchaseOrderPublic,
    PurchaseOrderReceiptLinePublic,
    PurchaseOrderReceiptPublic,
    PurchaseOrderUpdate,
)
from app.services.catalog_storage import presigned_urls

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])

ALLOWED_STATUSES = frozenset({"booked", "in_progress", "closed", "disputed", "cancelled"})

RECEIPT_ALLOWED_PO_STATUSES = frozenset({"booked", "in_progress"})


def _float_snap(row: dict, key: str) -> float:
    v = row.get(key)
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _int_snap(row: dict, key: str) -> int:
    v = row.get(key)
    if v is None:
        return 0
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0


def _receipts_public(db: Session, po_id: int) -> List[PurchaseOrderReceiptPublic]:
    rows = (
        db.query(StockReceipt)
        .filter(StockReceipt.purchase_order_id == po_id)
        .order_by(StockReceipt.id.asc())
        .all()
    )
    out: List[PurchaseOrderReceiptPublic] = []
    for r in rows:
        img_url: str | None = None
        if r.receipt_image_key:
            u = presigned_urls([r.receipt_image_key])
            img_url = u[0] if u else None
        raw_lines = r.line_items if isinstance(r.line_items, list) else []
        plines: List[PurchaseOrderReceiptLinePublic] = []
        for li in raw_lines:
            if not isinstance(li, dict):
                continue
            try:
                cid = int(li["catalog_product_id"])
                q = int(li["quantity"])
            except (KeyError, TypeError, ValueError):
                continue
            p = db.get(CatalogProduct, cid)
            plines.append(
                PurchaseOrderReceiptLinePublic(
                    catalog_product_id=cid,
                    quantity=q,
                    name=(p.name if p else "") or "",
                )
            )
        out.append(
            PurchaseOrderReceiptPublic(
                id=r.id,
                receipt_number=r.receipt_number,
                contact_number=r.contact_number,
                is_partial=bool(r.is_partial),
                receipt_image_url=img_url or None,
                lines=plines,
                created_at=r.created_at,
                notes=r.note,
            )
        )
    return out


def _lines_to_public(raw: list[Any]) -> tuple[List[PurchaseOrderLinePublic], float]:
    out: List[PurchaseOrderLinePublic] = []
    total_buying = 0.0
    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            cid = int(row["catalog_product_id"])
            qty = int(row["quantity"])
        except (KeyError, TypeError, ValueError):
            continue
        qty = max(1, qty)
        recv = min(qty, _int_snap(row, "received_quantity"))
        pending = max(0, qty - recv)
        bp = _float_snap(row, "buying_price")
        sp = _float_snap(row, "selling_price")
        line_total = round(bp * qty, 2)
        total_buying += line_total
        out.append(
            PurchaseOrderLinePublic(
                catalog_product_id=cid,
                quantity=qty,
                received_quantity=recv,
                quantity_pending=pending,
                name=str(row.get("name") or ""),
                our_product_id=str(row.get("our_product_id") or ""),
                vendor_product_id=str(row.get("vendor_product_id") or ""),
                buying_price=bp,
                selling_price=sp,
                line_total_buying=line_total,
            )
        )
    return out, round(total_buying, 2)


def _to_public(db: Session, row: VendorPurchaseOrder) -> PurchaseOrderPublic:
    raw = row.items if isinstance(row.items, list) else []
    lines, total_buying = _lines_to_public(raw)
    return PurchaseOrderPublic(
        id=row.id,
        vendor_id=row.vendor_id,
        status=row.status,
        items=lines,
        receipts=_receipts_public(db, row.id),
        notes=row.notes,
        total_buying_value=total_buying,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _merge_received_into_new_items(
    old_items: list[Any], new_built: list[dict[str, Any]]
) -> None:
    old_map: dict[int, int] = {}
    for x in old_items:
        if not isinstance(x, dict):
            continue
        try:
            cid = int(x["catalog_product_id"])
            rq = _int_snap(x, "received_quantity")
        except (KeyError, TypeError, ValueError):
            continue
        old_map[cid] = max(0, rq)
    for row in new_built:
        cid = int(row["catalog_product_id"])
        cap = int(row["quantity"])
        prev = min(old_map.get(cid, 0), cap)
        row["received_quantity"] = prev


def _build_items(
    db: Session,
    vendor_id: int,
    lines: list,
) -> list[dict[str, Any]]:
    built: list[dict[str, Any]] = []
    for line in lines:
        cid = line.catalog_product_id
        qty = line.quantity
        p = db.get(CatalogProduct, cid)
        if p is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"catalog product {cid} not found",
            )
        if p.vendor_id != vendor_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"product {cid} does not belong to vendor {vendor_id}",
            )
        bp = float(p.buying_price) if p.buying_price is not None else 0.0
        sp = float(p.selling_price) if p.selling_price is not None else 0.0
        built.append(
            {
                "catalog_product_id": p.id,
                "quantity": qty,
                "received_quantity": 0,
                "name": p.name,
                "our_product_id": p.our_product_id,
                "vendor_product_id": p.vendor_product_id,
                "buying_price": bp,
                "selling_price": sp,
            }
        )
    return built


def _parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
    if not value or not str(value).strip():
        return None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


@router.get("", response_model=List[PurchaseOrderPublic], dependencies=[Depends(require_admin)])
def list_orders(
    db: Session = Depends(get_db),
    vendor_id: Optional[int] = Query(None, ge=1),
    po_status: Optional[str] = Query(None, alias="status", description="Filter by PO status"),
    q: Optional[str] = Query(None, description="Search PO id or item text"),
    created_from: Optional[str] = Query(None),
    created_to: Optional[str] = Query(None),
) -> List[PurchaseOrderPublic]:
    query = db.query(VendorPurchaseOrder)
    if vendor_id is not None:
        query = query.filter(VendorPurchaseOrder.vendor_id == vendor_id)
    if po_status is not None and po_status.strip():
        st = po_status.strip().lower()
        if st in ALLOWED_STATUSES:
            query = query.filter(VendorPurchaseOrder.status == st)
    d0 = _parse_iso_dt(created_from)
    d1 = _parse_iso_dt(created_to)
    if d0 is not None:
        query = query.filter(VendorPurchaseOrder.created_at >= d0)
    if d1 is not None:
        query = query.filter(VendorPurchaseOrder.created_at <= d1)

    if q is not None and q.strip():
        term = q.strip()
        if term.isdigit():
            query = query.filter(VendorPurchaseOrder.id == int(term))
        else:
            like = f"%{term}%"
            query = query.filter(cast(VendorPurchaseOrder.items, String).ilike(like))

    rows = query.order_by(VendorPurchaseOrder.id.desc()).all()
    return [_to_public(db, r) for r in rows]


@router.post(
    "",
    response_model=PurchaseOrderPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_order(
    body: PurchaseOrderCreate,
    db: Session = Depends(get_db),
) -> PurchaseOrderPublic:
    if db.get(Vendor, body.vendor_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="vendor not found")
    items = _build_items(db, body.vendor_id, body.items)
    row = VendorPurchaseOrder(
        vendor_id=body.vendor_id,
        status="booked",
        items=items,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_public(db, row)


@router.get("/{order_id}", response_model=PurchaseOrderPublic, dependencies=[Depends(require_admin)])
def get_order(order_id: int, db: Session = Depends(get_db)) -> PurchaseOrderPublic:
    row = db.get(VendorPurchaseOrder, order_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
    return _to_public(db, row)


@router.patch("/{order_id}", response_model=PurchaseOrderPublic, dependencies=[Depends(require_admin)])
def update_order(
    order_id: int,
    body: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
) -> PurchaseOrderPublic:
    row = db.get(VendorPurchaseOrder, order_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")

    if body.status is None and body.items is None and body.notes is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no fields to update")

    vid = row.vendor_id
    old_items = row.items if isinstance(row.items, list) else []

    if body.notes is not None:
        row.notes = body.notes

    if body.status is not None:
        st = body.status.strip().lower()
        if st not in ALLOWED_STATUSES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"status must be one of: {sorted(ALLOWED_STATUSES)}",
            )
        row.status = st

    if body.items is not None:
        if not body.items:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="items cannot be empty")
        built = _build_items(db, vid, body.items)
        _merge_received_into_new_items(old_items, built)
        row.items = built

    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_public(db, row)


@router.delete("/{order_id}", dependencies=[Depends(require_admin)])
def delete_order(order_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(VendorPurchaseOrder, order_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
    db.delete(row)
    db.commit()
    return {"ok": True, "id": order_id}


def receipt_allowed_status(po_status: str) -> bool:
    return po_status in RECEIPT_ALLOWED_PO_STATUSES
