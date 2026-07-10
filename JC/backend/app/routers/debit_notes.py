from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context
from app.models.debit_note import DebitNote
from app.models.stock import StockReceipt
from app.models.vendor import Vendor
from app.models.city import City
from app.schemas.debit_note import DebitNoteIn, DebitNoteOut, DebitNoteUpdate
from app.services.debit_notes import (
    _resolve_item_amount,
    create_debit_note,
    infer_direction,
    normalize_signed_values,
)
from app.services.ap_ledger import debit_note_payable_effect

router = APIRouter(prefix="/debit-notes", tags=["debit-notes"])


def _vendor_label(vendor: Vendor, city_name: Optional[str]) -> str:
    return f"{vendor.business_name} — {city_name}" if city_name else vendor.business_name


def _debit_note_out(db: Session, note: DebitNote) -> DebitNoteOut:
    receipt = db.get(StockReceipt, note.receipt_id)
    vendor = db.get(Vendor, note.vendor_id)
    city_name = None
    if vendor and vendor.city_id:
        city = db.get(City, vendor.city_id)
        city_name = city.name if city else None
    direction = note.direction or infer_direction(note.note_type, note.quantity, note.amount)
    return DebitNoteOut(
        id=note.id,
        vendor_id=note.vendor_id,
        receipt_id=note.receipt_id,
        note_type=note.note_type,
        direction=direction,
        catalog_product_id=note.catalog_product_id,
        our_product_id=note.our_product_id,
        quantity=note.quantity,
        unit_price=format(note.unit_price, "f") if note.unit_price is not None else None,
        amount=format(note.amount, "f"),
        payable_effect=format(debit_note_payable_effect(note.amount, note.note_type), "f"),
        notes=note.notes,
        created_by_name=note.created_by_name,
        created_by_type=note.created_by_type,
        created_at=note.created_at,
        updated_at=note.updated_at,
        bill_number=receipt.bill_number if receipt else None,
        vendor_label=_vendor_label(vendor, city_name) if vendor else None,
    )


@router.get("", response_model=List[DebitNoteOut])
def list_debit_notes(
    vendor_id: Optional[int] = Query(None),
    receipt_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    q = db.query(DebitNote).order_by(DebitNote.created_at.desc())
    if vendor_id is not None:
        q = q.filter(DebitNote.vendor_id == vendor_id)
    if receipt_id is not None:
        q = q.filter(DebitNote.receipt_id == receipt_id)
    return [_debit_note_out(db, n) for n in q.all()]


@router.get("/{note_id}", response_model=DebitNoteOut)
def get_debit_note(
    note_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    note = db.get(DebitNote, note_id)
    if not note:
        raise HTTPException(404, "debit note not found")
    return _debit_note_out(db, note)


@router.post("", response_model=DebitNoteOut, status_code=status.HTTP_201_CREATED)
def create_debit_note_endpoint(
    body: DebitNoteIn,
    vendor_id: int = Query(...),
    receipt_id: int = Query(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    note = create_debit_note(db, auth, vendor_id=vendor_id, receipt_id=receipt_id, body=body)
    db.commit()
    db.refresh(note)
    return _debit_note_out(db, note)


@router.patch("/{note_id}", response_model=DebitNoteOut)
def update_debit_note(
    note_id: int,
    body: DebitNoteUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
):
    note = db.get(DebitNote, note_id)
    if not note:
        raise HTTPException(404, "debit note not found")

    note_type = body.note_type or note.note_type
    if note_type == "item":
        cat_id = body.catalog_product_id if body.catalog_product_id is not None else note.catalog_product_id
        qty = body.quantity if body.quantity is not None else note.quantity
        direction = body.direction if body.direction is not None else note.direction
        if not cat_id or qty is None or qty == 0:
            raise HTTPException(400, "item debit note requires product and non-zero quantity")
        direction, signed_qty, _ = normalize_signed_values(
            "item", direction=direction, quantity=qty, amount=None
        )
        amount, our_product_id, unit_price = _resolve_item_amount(db, note.receipt_id, cat_id, signed_qty)
        note.note_type = "item"
        note.direction = direction
        note.catalog_product_id = cat_id
        note.our_product_id = our_product_id
        note.quantity = signed_qty
        note.unit_price = unit_price
        note.amount = amount
    else:
        amt = body.amount if body.amount is not None else note.amount
        direction = body.direction if body.direction is not None else note.direction
        direction, _, signed_amt = normalize_signed_values(
            "value", direction=direction, quantity=None, amount=amt
        )
        note.note_type = "value"
        note.direction = direction
        note.catalog_product_id = None
        note.our_product_id = None
        note.quantity = None
        note.unit_price = None
        note.amount = signed_amt

    if body.notes is not None:
        note.notes = body.notes

    from app.models.accounts_payable import ApLedgerEntry
    from app.services.ap_ledger import post_debit_note_entry
    entry = db.query(ApLedgerEntry).filter(ApLedgerEntry.debit_note_id == note.id).first()
    if entry:
        entry.amount = debit_note_payable_effect(note.amount, note.note_type)
        entry.description = f"Debit note — ₹{note.amount} ({note.direction or ''})"
    else:
        post_debit_note_entry(
            db,
            vendor_id=note.vendor_id,
            receipt_id=note.receipt_id,
            debit_note_id=note.id,
            amount=note.amount,
            note_type=note.note_type,
            description=f"Debit note — ₹{note.amount} ({note.direction or ''})",
            actor_type=auth.actor_type,
            actor_id=auth.actor_id,
            actor_name=auth.actor_name,
        )

    db.commit()
    db.refresh(note)
    return _debit_note_out(db, note)
