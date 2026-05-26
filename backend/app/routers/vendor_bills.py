from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.stock_receipt import StockReceipt
from app.models.vendor_bill import VendorBill
from app.models.vendor_purchase_order import VendorPurchaseOrder
from app.schemas.vendor_bill import VendorBillCreate, VendorBillPatch, VendorBillPublic
from app.services.catalog_storage import presigned_url, storage_configured, upload_bytes
from app.services.accounting import ensure_ap_for_vendor_bill
from app.services.three_way_match import run_three_way_match

router = APIRouter(prefix="/vendor-bills", tags=["vendor-bills"])

ALLOWED_PO_FOR_BILL = frozenset({"closed", "disputed"})
_DOC_PREFIX = "vendor_bills"


def _save_doc_upload(file: Optional[UploadFile]) -> Optional[str]:
    if file is None or not getattr(file, "filename", None):
        return None
    raw = file.file.read()
    if not raw:
        return None
    suf = Path(file.filename or "upload").suffix.lower()
    if suf not in (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"):
        suf = ".bin"
    mime = file.content_type or "application/octet-stream"
    key = f"{_DOC_PREFIX}/{uuid.uuid4().hex}{suf}"
    upload_bytes(key, raw, mime)
    return key


def _parse_bill_lines_json(raw: str) -> List[dict]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"invalid bill_lines JSON: {e}") from e
    if not isinstance(data, list) or len(data) < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bill_lines must be a non-empty array")
    validated = VendorBillCreate.model_validate(
        {
            "purchase_order_id": 1,
            "bill_lines": [
                {
                    "bill_item_ref": str(x.get("bill_item_ref") or ""),
                    "catalog_product_id": int(x["catalog_product_id"]),
                    "quantity": int(x["quantity"]),
                    "unit_price": str(x["unit_price"]),
                }
                for x in data
                if isinstance(x, dict)
            ],
            "notes": None,
        }
    )
    return [bl.model_dump() for bl in validated.bill_lines]


def _to_public(row: VendorBill) -> VendorBillPublic:
    raw_lines = row.bill_lines if isinstance(row.bill_lines, list) else []
    doc_url = presigned_url(row.document_key) if row.document_key else None
    return VendorBillPublic(
        id=row.id,
        purchase_order_id=row.purchase_order_id,
        document_key=row.document_key,
        document_url=doc_url or None,
        bill_lines=list(raw_lines),
        match_status=row.match_status,
        match_result=row.match_result if isinstance(row.match_result, dict) else None,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_po_for_bill(po: VendorPurchaseOrder) -> None:
    st = (po.status or "").strip().lower()
    if st not in ALLOWED_PO_FOR_BILL:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"vendor bill allowed only when PO status is closed or disputed (got {po.status})",
        )


class _GRNBillLine(BaseModel):
    catalog_product_id: int
    quantity: int
    unit_price: str
    bill_item_ref: str = ""


class _GRNBillPreview(BaseModel):
    purchase_order_id: int
    bill_lines: List[_GRNBillLine]


@router.get(
    "/grn-preview/{purchase_order_id}",
    response_model=_GRNBillPreview,
    dependencies=[Depends(require_admin)],
)
def grn_bill_preview(purchase_order_id: int, db: Session = Depends(get_db)) -> _GRNBillPreview:
    """Return bill lines pre-filled from GRN received quantities for a PO."""
    po = db.get(VendorPurchaseOrder, purchase_order_id)
    if po is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="purchase order not found")

    receipts = (
        db.query(StockReceipt)
        .filter(StockReceipt.purchase_order_id == purchase_order_id)
        .all()
    )

    received: dict[int, int] = {}
    for rec in receipts:
        for item in (rec.line_items if isinstance(rec.line_items, list) else []):
            if not isinstance(item, dict):
                continue
            try:
                cid = int(item["catalog_product_id"])
                qty = int(item.get("quantity_received") or item.get("quantity") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            received[cid] = received.get(cid, 0) + qty

    if not received:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="No GRN receipts found for this PO. Create a stock receipt first.",
        )

    po_items: dict[int, dict] = {}
    for item in (po.items if isinstance(po.items, list) else []):
        if not isinstance(item, dict):
            continue
        try:
            cid = int(item["catalog_product_id"])
        except (KeyError, TypeError, ValueError):
            continue
        po_items[cid] = item

    lines: List[_GRNBillLine] = []
    for cid, qty in sorted(received.items()):
        if qty <= 0:
            continue
        po_item = po_items.get(cid, {})
        up = str(po_item.get("unit_price") or po_item.get("price") or "0")
        ref = str(po_item.get("our_product_id") or po_item.get("vendor_product_id") or str(cid))
        lines.append(_GRNBillLine(catalog_product_id=cid, quantity=qty, unit_price=up, bill_item_ref=ref))

    return _GRNBillPreview(purchase_order_id=purchase_order_id, bill_lines=lines)


@router.get("", response_model=List[VendorBillPublic], dependencies=[Depends(require_admin)])
def list_vendor_bills(
    db: Session = Depends(get_db),
    purchase_order_id: Optional[int] = Query(None, ge=1),
) -> List[VendorBillPublic]:
    q = db.query(VendorBill).order_by(VendorBill.id.desc())
    if purchase_order_id is not None:
        q = q.filter(VendorBill.purchase_order_id == purchase_order_id)
    rows = q.limit(500).all()
    return [_to_public(r) for r in rows]


@router.get("/{bill_id}", response_model=VendorBillPublic, dependencies=[Depends(require_admin)])
def get_vendor_bill(bill_id: int, db: Session = Depends(get_db)) -> VendorBillPublic:
    row = db.get(VendorBill, bill_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor bill not found")
    return _to_public(row)


@router.post("", response_model=VendorBillPublic, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_vendor_bill(
    db: Session = Depends(get_db),
    purchase_order_id: int = Form(...),
    bill_lines: str = Form(...),
    notes: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
) -> VendorBillPublic:
    po = db.get(VendorPurchaseOrder, purchase_order_id)
    if po is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="purchase order not found")
    _validate_po_for_bill(po)

    lines_dicts = _parse_bill_lines_json(bill_lines)

    doc_key: Optional[str] = None
    if file is not None and getattr(file, "filename", None):
        if not storage_configured():
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="S3 storage not configured — cannot upload document",
            )
        try:
            doc_key = _save_doc_upload(file)
        except RuntimeError as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e

    row = VendorBill(
        purchase_order_id=purchase_order_id,
        document_key=doc_key,
        bill_lines=lines_dicts,
        match_status="pending",
        match_result=None,
        notes=(notes or "").strip() or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    try:
        ensure_ap_for_vendor_bill(db, vb=row, po=po)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return _to_public(row)


@router.patch("/{bill_id}", response_model=VendorBillPublic, dependencies=[Depends(require_admin)])
def patch_vendor_bill(
    bill_id: int,
    body: VendorBillPatch,
    db: Session = Depends(get_db),
) -> VendorBillPublic:
    row = db.get(VendorBill, bill_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor bill not found")

    if body.bill_lines is not None:
        payload = [
            {
                "bill_item_ref": bl.bill_item_ref,
                "catalog_product_id": bl.catalog_product_id,
                "quantity": bl.quantity,
                "unit_price": bl.unit_price,
            }
            for bl in body.bill_lines
        ]
        row.bill_lines = payload
        row.match_status = "pending"
        row.match_result = None

    if body.notes is not None:
        row.notes = body.notes.strip() or None

    db.add(row)
    db.commit()
    db.refresh(row)
    po2 = db.get(VendorPurchaseOrder, row.purchase_order_id)
    if po2 is not None:
        try:
            ensure_ap_for_vendor_bill(db, vb=row, po=po2)
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(row)
    return _to_public(row)


@router.post("/{bill_id}/run-match", response_model=VendorBillPublic, dependencies=[Depends(require_admin)])
def run_match(bill_id: int, db: Session = Depends(get_db)) -> VendorBillPublic:
    row = db.get(VendorBill, bill_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor bill not found")

    po = db.get(VendorPurchaseOrder, row.purchase_order_id)
    if po is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="purchase order missing")

    raw_lines = row.bill_lines if isinstance(row.bill_lines, list) else []
    lines_for_match = [x for x in raw_lines if isinstance(x, dict)]

    try:
        result = run_three_way_match(db, po, lines_for_match)
    except Exception as ex:
        row.match_status = "error"
        row.match_result = {"matched": False, "summary": str(ex), "reasons": [str(ex)], "lines": [], "totals": {}}
        db.add(row)
        db.commit()
        db.refresh(row)
        return _to_public(row)

    row.match_result = result
    row.match_status = "matched" if result.get("matched") else "unmatched"
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_public(row)
