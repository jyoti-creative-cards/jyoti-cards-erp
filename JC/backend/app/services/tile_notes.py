"""Tile notes are tied to the stage a party is sitting in. Once that stage is
empty, the note goes with it so the next order starts blank."""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.board import TileNote
from app.models.customer_bill import CustomerBill
from app.models.customer_order import CustomerOpenLine, CustomerOrderLine, CustomerOrderPlacement


def clear_stage_note(db: Session, customer_id: int, stage: str) -> None:
    key = f"co:{stage}:{int(customer_id)}"
    row = db.query(TileNote).filter(TileNote.tile_key == key).one_or_none()
    if row is not None:
        db.delete(row)


def clear_received_note_if_gone(db: Session, customer_id: int) -> None:
    from app.services.customer_selling.buckets import get_open_customer_order

    received = get_open_customer_order(db, customer_id, "received")
    if received is not None and received.is_open:
        leftover = (
            db.query(CustomerOrderLine.id)
            .join(CustomerOrderPlacement, CustomerOrderPlacement.id == CustomerOrderLine.placement_id)
            .filter(
                CustomerOrderPlacement.customer_order_id == received.id,
                CustomerOrderPlacement.deleted_at.is_(None),
                CustomerOrderLine.status == "active",
                CustomerOrderLine.quantity > CustomerOrderLine.quantity_billed,
            )
            .first()
        )
        if leftover:
            return
    clear_stage_note(db, customer_id, "received")


def clear_open_note_if_gone(db: Session, customer_id: int) -> None:
    left = (
        db.query(CustomerOpenLine.id)
        .filter(
            CustomerOpenLine.customer_id == customer_id,
            CustomerOpenLine.status == "open",
            CustomerOpenLine.quantity_open > 0,
        )
        .first()
    )
    if left:
        return
    clear_stage_note(db, customer_id, "open")


def clear_billed_note_if_gone(db: Session, customer_id: int) -> None:
    still = (
        db.query(CustomerBill.id)
        .filter(
            CustomerBill.customer_id == customer_id,
            CustomerBill.cancelled_at.is_(None),
            CustomerBill.deleted_at.is_(None),
            CustomerBill.freight_picked_at.is_(None),
            or_(
                CustomerBill.transport_mode.isnot(None),
                CustomerBill.freight_agent_id.isnot(None),
            ),
        )
        .first()
    )
    if still:
        return
    clear_stage_note(db, customer_id, "billed")
