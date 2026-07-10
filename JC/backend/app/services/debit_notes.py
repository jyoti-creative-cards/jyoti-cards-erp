from __future__ import annotations

from decimal import Decimal
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.deps import AuthContext
from app.models.debit_note import DebitNote
from app.models.stock import StockReceiptLine
from app.models.vendor import Vendor
from app.models.city import City
from app.schemas.debit_note import DebitNoteIn
from app.services.activity import log_from_auth
from app.services.ap_ledger import post_debit_note_entry


def _vendor_label(vendor: Vendor, city_name: Optional[str]) -> str:
    return f"{vendor.business_name} — {city_name}" if city_name else vendor.business_name


def infer_direction(note_type: str, quantity: Optional[int], amount: Decimal) -> str:
    """Infer direction from signed qty/amount when column is empty (legacy rows)."""
    if note_type == "item":
        return "extra" if (quantity or 0) < 0 else "short"
    return "over" if amount < 0 else "under"


def normalize_signed_values(
    note_type: str,
    *,
    direction: Optional[str],
    quantity: Optional[int],
    amount: Optional[Decimal],
) -> Tuple[Optional[str], Optional[int], Optional[Decimal]]:
    """Return (direction, signed_quantity, signed_amount_for_value)."""
    if note_type == "item":
        qty = int(quantity or 0)
        if qty == 0:
            raise HTTPException(400, "quantity cannot be 0")
        dir_ = direction or ("extra" if qty < 0 else "short")
        if dir_ not in ("short", "extra"):
            raise HTTPException(400, "item debit note direction must be short or extra")
        qty_abs = abs(qty)
        signed_qty = -qty_abs if dir_ == "extra" else qty_abs
        return dir_, signed_qty, None

    if amount is None:
        raise HTTPException(400, "amount required")
    amt = Decimal(str(amount))
    if amt == 0:
        raise HTTPException(400, "amount cannot be 0")
    dir_ = direction or ("over" if amt < 0 else "under")
    if dir_ not in ("over", "under"):
        raise HTTPException(400, "value debit note direction must be over or under")
    amt_abs = abs(amt).quantize(Decimal("0.01"))
    signed_amt = -amt_abs if dir_ == "over" else amt_abs
    return dir_, None, signed_amt


def _resolve_item_amount(db: Session, receipt_id: int, catalog_product_id: int, quantity: int) -> tuple[Decimal, str, Decimal]:
    line = (
        db.query(StockReceiptLine)
        .filter(StockReceiptLine.receipt_id == receipt_id, StockReceiptLine.catalog_product_id == catalog_product_id)
        .first()
    )
    if not line:
        raise HTTPException(400, "product not in this receipt")
    unit = line.buying_price
    amount = (unit * quantity).quantize(Decimal("0.01"))
    return amount, line.our_product_id, unit


def create_debit_note(
    db: Session,
    auth: AuthContext,
    *,
    vendor_id: int,
    receipt_id: int,
    body: DebitNoteIn,
) -> DebitNote:
    from app.models.stock import StockReceipt

    receipt = db.get(StockReceipt, receipt_id)
    if not receipt or receipt.vendor_id != vendor_id:
        raise HTTPException(404, "receipt not found for vendor")

    if body.note_type == "item":
        direction, signed_qty, _ = normalize_signed_values(
            "item", direction=body.direction, quantity=body.quantity, amount=None
        )
        amount, our_product_id, unit_price = _resolve_item_amount(
            db, receipt_id, body.catalog_product_id, signed_qty
        )
        note = DebitNote(
            vendor_id=vendor_id,
            receipt_id=receipt_id,
            note_type="item",
            direction=direction,
            catalog_product_id=body.catalog_product_id,
            our_product_id=our_product_id,
            quantity=signed_qty,
            unit_price=unit_price,
            amount=amount,
            notes=body.notes,
            created_by_type=auth.actor_type,
            created_by_id=auth.actor_id,
            created_by_name=auth.actor_name,
        )
        detail = f"{our_product_id} × {signed_qty} ({direction}) = ₹{amount}"
    else:
        direction, _, signed_amt = normalize_signed_values(
            "value", direction=body.direction, quantity=None, amount=body.amount
        )
        note = DebitNote(
            vendor_id=vendor_id,
            receipt_id=receipt_id,
            note_type="value",
            direction=direction,
            amount=signed_amt,
            notes=body.notes,
            created_by_type=auth.actor_type,
            created_by_id=auth.actor_id,
            created_by_name=auth.actor_name,
        )
        detail = f"value debit ₹{signed_amt} ({direction})"

    db.add(note)
    db.flush()
    post_debit_note_entry(
        db,
        vendor_id=vendor_id,
        receipt_id=receipt_id,
        debit_note_id=note.id,
        amount=note.amount,
        note_type=body.note_type,
        description=f"Debit note — {detail}",
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        actor_name=auth.actor_name,
    )
    vendor = db.get(Vendor, vendor_id)
    city_name = None
    if vendor and vendor.city_id:
        city = db.get(City, vendor.city_id)
        city_name = city.name if city else None
    label = _vendor_label(vendor, city_name) if vendor else f"Vendor #{vendor_id}"
    log_from_auth(
        db,
        auth,
        action="debit_note",
        entity_type="debit_note",
        entity_id=note.id,
        entity_label=label,
        detail=detail,
    )
    return note
