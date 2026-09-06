from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, get_auth_context, require_admin, require_permission
from app.models.debit_note import DebitNote
from app.models.stock import StockReceipt
from app.models.vendor import Vendor
from app.models.city import City
from app.schemas.debit_note import DebitNoteIn, DebitNoteOut, DebitNoteUpdate
from app.schemas.stock import VoidIn
from app.services.debit_notes import (
    create_debit_note,
    infer_direction,
    reverse_debit_note_effects,
)
from app.services.activity import log_from_auth
from app.services.ap_ledger import debit_note_payable_effect
from app.services.cost_visibility import hide_cost
from app.services.void_service import void_debit_note

router = APIRouter(prefix="/debit-notes", tags=["debit-notes"])


def _vendor_label(vendor: Vendor, city_name: Optional[str]) -> str:
    return f"{vendor.business_name} — {city_name}" if city_name else vendor.business_name


def _debit_note_out(db: Session, note: DebitNote, *, auth: AuthContext) -> DebitNoteOut:
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
        # unit_price is the catalog buying_price at receive time — a cost hint, not just a DN amount.
        unit_price=hide_cost(format(note.unit_price, "f") if note.unit_price is not None else None, auth),
        amount=format(note.amount, "f"),
        payable_effect=format(debit_note_payable_effect(note.amount, note.note_type), "f"),
        notes=note.notes,
        created_by_name=note.created_by_name,
        created_by_type=note.created_by_type,
        created_at=note.created_at,
        updated_at=note.updated_at,
        bill_number=receipt.bill_number if receipt else None,
        vendor_label=_vendor_label(vendor, city_name) if vendor else None,
        source=note.source,
        deleted_at=note.deleted_at,
        deleted_reason=note.deleted_reason,
    )


@router.get("", response_model=List[DebitNoteOut])
def list_debit_notes(
    vendor_id: Optional[int] = Query(None),
    receipt_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    q = db.query(DebitNote).filter(DebitNote.deleted_at.is_(None)).order_by(DebitNote.created_at.desc())
    if vendor_id is not None:
        q = q.filter(DebitNote.vendor_id == vendor_id)
    if receipt_id is not None:
        q = q.filter(DebitNote.receipt_id == receipt_id)
    return [_debit_note_out(db, n, auth=auth) for n in q.all()]


@router.get("/{note_id}", response_model=DebitNoteOut)
def get_debit_note(
    note_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.read")),
):
    note = db.get(DebitNote, note_id)
    if not note:
        raise HTTPException(404, "debit note not found")
    return _debit_note_out(db, note, auth=auth)


@router.post(
    "", response_model=DebitNoteOut, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("vendor_orders.write"))],
)
def create_debit_note_endpoint(
    body: DebitNoteIn,
    vendor_id: int = Query(...),
    receipt_id: int = Query(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    note = create_debit_note(db, auth, vendor_id=vendor_id, receipt_id=receipt_id, body=body)
    db.commit()
    db.refresh(note)
    return _debit_note_out(db, note, auth=auth)


@router.post("/{note_id}/void")
def void_debit_note_endpoint(
    note_id: int,
    body: VoidIn,
    db: Session = Depends(get_db),
    # Void is destructive to AP history (reverses the ledger effect) — admin only,
    # same trust boundary as every other void/purge in the app. Editing (below)
    # stays at vendor_orders.write since it's a routine correction, not a reversal.
    auth: AuthContext = Depends(require_admin),
):
    from app.services import response_cache

    result = void_debit_note(db, auth, note_id, body.reason)
    response_cache.invalidate("stock:")
    return result


@router.patch("/{note_id}", response_model=DebitNoteOut, dependencies=[Depends(require_permission("vendor_orders.write"))])
def update_debit_note(
    note_id: int,
    body: DebitNoteUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("vendor_orders.write")),
):
    """Edit = reverse the old note's AP/stock effect with a compensating entry, then
    create a brand-new note with the merged values. Never mutate note.amount/quantity
    or an existing ApLedgerEntry in place — that would rewrite history a reconciliation
    or PDF might already have been generated against. Same pattern receipt_edit.py
    already uses for auto-generated debit notes when a receipt is edited.
    """
    note = db.get(DebitNote, note_id)
    if not note:
        raise HTTPException(404, "debit note not found")
    if note.deleted_at:
        raise HTTPException(400, "debit note is voided — restore it from the recycle bin first")

    note_type = body.note_type or note.note_type
    if note_type == "item":
        cat_id = body.catalog_product_id if body.catalog_product_id is not None else note.catalog_product_id
        qty = body.quantity if body.quantity is not None else note.quantity
        direction = body.direction if body.direction is not None else note.direction
        if not cat_id or qty is None or qty == 0:
            raise HTTPException(400, "item debit note requires product and non-zero quantity")
        new_body = DebitNoteIn(
            note_type="item",
            direction=direction,
            catalog_product_id=cat_id,
            quantity=qty,
            notes=body.notes if body.notes is not None else note.notes,
        )
    else:
        amt = body.amount if body.amount is not None else note.amount
        direction = body.direction if body.direction is not None else note.direction
        new_body = DebitNoteIn(
            note_type="value",
            direction=direction,
            catalog_product_id=body.catalog_product_id if body.catalog_product_id is not None else note.catalog_product_id,
            amount=amt,
            notes=body.notes if body.notes is not None else note.notes,
        )

    vendor_id, receipt_id = note.vendor_id, note.receipt_id
    old_summary = f"{note.note_type} ₹{note.amount} ({note.direction or ''})"
    reverse_debit_note_effects(db, auth, note, reason=f"edited — was {old_summary}")
    db.delete(note)
    db.flush()

    new_note = create_debit_note(db, auth, vendor_id=vendor_id, receipt_id=receipt_id, body=new_body, source="manual")

    vendor = db.get(Vendor, vendor_id)
    city_name = None
    if vendor and vendor.city_id:
        city = db.get(City, vendor.city_id)
        city_name = city.name if city else None
    log_from_auth(
        db,
        auth,
        action="update",
        entity_type="debit_note",
        entity_id=new_note.id,
        entity_label=_vendor_label(vendor, city_name) if vendor else None,
        detail=f"edited (was {old_summary}) → {new_note.note_type} ₹{new_note.amount}",
    )
    db.commit()
    db.refresh(new_note)
    return _debit_note_out(db, new_note, auth=auth)
