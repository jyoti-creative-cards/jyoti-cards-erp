from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.catalog_product import CatalogProduct
from app.models.credit_debit_note import CreditNote
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.customer_order import CustomerOrder
from app.models.stock_adjustment import StockAdjustment
from app.models.stock_balance import StockBalance

router = APIRouter(prefix="/credit-notes", tags=["credit-notes"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ReturnItem(BaseModel):
    catalog_product_id: int
    quantity: int = Field(..., ge=1)
    unit_price: Optional[float] = None  # override if different from order


class CreditNoteCreate(BaseModel):
    customer_id: int
    customer_order_id: int
    customer_bill_id: Optional[int] = None
    reason: Optional[str] = None
    note_date: Optional[date] = None
    return_items: list[ReturnItem]
    refund_method: str = Field(default="credit", pattern="^(credit|payout)$")


class CreditNotePublic(BaseModel):
    id: int
    customer_id: int
    customer_order_id: int
    customer_bill_id: Optional[int]
    amount: str
    reason: Optional[str]
    status: str
    refund_method: str
    is_full_return: bool
    return_items: Optional[list]
    note_date: Optional[date]
    paid_out_at: Optional[datetime]
    applied_to_bill_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApplyToBillBody(BaseModel):
    bill_id: int


class PayoutBody(BaseModel):
    note: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _to_public(row: CreditNote) -> CreditNotePublic:
    return CreditNotePublic(
        id=row.id,
        customer_id=row.customer_id,
        customer_order_id=row.customer_order_id,
        customer_bill_id=row.customer_bill_id,
        amount=str(row.amount),
        reason=row.reason,
        status=row.status,
        refund_method=row.refund_method,
        is_full_return=bool(row.is_full_return),
        return_items=row.return_items or [],
        note_date=row.note_date,
        paid_out_at=row.paid_out_at,
        applied_to_bill_id=row.applied_to_bill_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _apply_stock_delta(db: Session, catalog_product_id: int, delta: int) -> None:
    row = db.get(StockBalance, catalog_product_id)
    if row is None:
        nb = StockBalance(catalog_product_id=catalog_product_id, quantity=max(delta, 0), low_stock_threshold=0)
        db.add(nb)
    else:
        row.quantity = max(0, int(row.quantity) + delta)
        db.add(row)


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=list[CreditNotePublic], dependencies=[Depends(require_admin)])
def list_credit_notes(
    customer_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
) -> list[CreditNotePublic]:
    q = db.query(CreditNote)
    if customer_id:
        q = q.filter(CreditNote.customer_id == customer_id)
    if status_filter:
        q = q.filter(CreditNote.status == status_filter)
    return [_to_public(r) for r in q.order_by(CreditNote.id.desc()).all()]


@router.get("/{note_id}", response_model=CreditNotePublic, dependencies=[Depends(require_admin)])
def get_credit_note(note_id: int, db: Session = Depends(get_db)) -> CreditNotePublic:
    row = db.get(CreditNote, note_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="credit note not found")
    return _to_public(row)


@router.post("", response_model=CreditNotePublic, dependencies=[Depends(require_admin)])
def create_credit_note(body: CreditNoteCreate, db: Session = Depends(get_db)) -> CreditNotePublic:
    # Validate order belongs to customer
    order = db.get(CustomerOrder, body.customer_order_id)
    if order is None or order.customer_id != body.customer_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found for this customer")

    if not body.return_items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="return_items cannot be empty")

    # Build return line items and compute total credit amount
    order_items: dict[int, dict] = {
        int(it.get("catalog_product_id", 0)): it
        for it in (order.items or [])
        if it.get("catalog_product_id")
    }

    lines = []
    total_amount = Decimal("0")

    for ri in body.return_items:
        order_item = order_items.get(ri.catalog_product_id)
        prod = db.get(CatalogProduct, ri.catalog_product_id)
        if prod is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"product {ri.catalog_product_id} not found")

        if order_item:
            ordered_qty = int(order_item.get("quantity", 0))
            if ri.quantity > ordered_qty:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail=f"return quantity {ri.quantity} > ordered quantity {ordered_qty} for product {prod.our_product_id}",
                )
            unit_price = ri.unit_price if ri.unit_price is not None else float(order_item.get("unit_price", 0))
        else:
            unit_price = ri.unit_price or 0.0

        line_amount = Decimal(str(unit_price)) * ri.quantity
        total_amount += line_amount

        lines.append({
            "catalog_product_id": ri.catalog_product_id,
            "product_name": prod.our_product_id,
            "quantity": ri.quantity,
            "unit_price": unit_price,
            "line_amount": float(line_amount),
        })

    # Determine if full return
    total_ordered = sum(int(it.get("quantity", 0)) for it in (order.items or []))
    total_returned = sum(ri.quantity for ri in body.return_items)
    is_full = total_returned >= total_ordered

    # Create credit note
    note = CreditNote(
        customer_id=body.customer_id,
        customer_order_id=body.customer_order_id,
        customer_bill_id=body.customer_bill_id,
        amount=float(total_amount),
        reason=body.reason,
        status="open",
        refund_method=body.refund_method,
        is_full_return=is_full,
        return_items=lines,
        note_date=body.note_date or date.today(),
    )
    db.add(note)
    db.flush()

    # Adjust stock — returned goods go back to inventory
    for ri in body.return_items:
        _apply_stock_delta(db, ri.catalog_product_id, ri.quantity)
        adj = StockAdjustment(
            catalog_product_id=ri.catalog_product_id,
            quantity_delta=ri.quantity,
            note=f"Return — Credit Note #{note.id}",
        )
        db.add(adj)

    db.commit()
    db.refresh(note)
    return _to_public(note)


@router.post("/{note_id}/apply", response_model=CreditNotePublic, dependencies=[Depends(require_admin)])
def apply_credit_note(note_id: int, body: ApplyToBillBody, db: Session = Depends(get_db)) -> CreditNotePublic:
    note = db.get(CreditNote, note_id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="credit note not found")
    if note.status != "open":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"credit note is already {note.status}")

    bill = db.get(CustomerBill, body.bill_id)
    if bill is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="bill not found")

    note.status = "applied"
    note.applied_to_bill_id = body.bill_id
    db.add(note)
    db.commit()
    db.refresh(note)
    return _to_public(note)


@router.post("/{note_id}/payout", response_model=CreditNotePublic, dependencies=[Depends(require_admin)])
def payout_credit_note(note_id: int, body: PayoutBody, db: Session = Depends(get_db)) -> CreditNotePublic:
    note = db.get(CreditNote, note_id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="credit note not found")
    if note.status != "open":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"credit note is already {note.status}")

    note.status = "paid_out"
    note.paid_out_at = datetime.now(timezone.utc)
    note.refund_method = "payout"
    if body.note:
        note.reason = (note.reason or "") + f" | Payout: {body.note}"
    db.add(note)
    db.commit()
    db.refresh(note)
    return _to_public(note)


@router.delete("/{note_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_credit_note(note_id: int, db: Session = Depends(get_db)) -> None:
    note = db.get(CreditNote, note_id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="credit note not found")
    if note.status != "open":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="can only delete open credit notes")
    # Reverse stock adjustments
    for item in (note.return_items or []):
        qty = int(item.get("quantity", 0))
        cid = item.get("catalog_product_id")
        if cid and qty:
            _apply_stock_delta(db, int(cid), -qty)
    db.delete(note)
    db.commit()
