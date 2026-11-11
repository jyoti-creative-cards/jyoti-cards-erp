"""fold every existing order and bill line into one marking

Revision ID: o6e7f8a9b0c1
Revises: n5d6e7f8a9b0
Create Date: 2026-11-11 17:05:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "o6e7f8a9b0c1"
down_revision: Union[str, Sequence[str], None] = "n5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SKIP = {"order placed by admin (phone)", "offline order", "order placed by admin"}


def _pieces(value) -> list[str]:
    out = []
    for piece in str(value or "").split("·"):
        text = " ".join(piece.split())
        if not text or text.lower() in _SKIP:
            continue
        out.append(text[:400])
    return out


def _join(chunks: list[str]):
    seen = set()
    parts = []
    for chunk in chunks:
        key = chunk.casefold()
        if key in seen:
            continue
        seen.add(key)
        parts.append(chunk)
    return " · ".join(parts) or None


def upgrade() -> None:
    conn = op.get_bind()
    orders = conn.execute(sa.text(
        "SELECT id, customer_id, marking, customer_marking FROM jc_customer_orders "
        "WHERE is_open IS TRUE AND bucket IN ('received', 'open')"
    )).fetchall()
    notes = conn.execute(sa.text(
        "SELECT p.customer_order_id, p.customer_notes "
        "FROM jc_customer_order_placements p "
        "JOIN jc_customer_orders o ON o.id = p.customer_order_id "
        "WHERE p.deleted_at IS NULL AND o.is_open IS TRUE AND o.bucket IN ('received', 'open')"
    )).fetchall()
    bills = conn.execute(sa.text(
        "SELECT id, customer_id, narration FROM jc_customer_bills "
        "WHERE cancelled_at IS NULL AND closed_at IS NULL AND deleted_at IS NULL"
    )).fetchall()

    chunks: dict[int, list[str]] = {}
    order_ids_by_customer: dict[int, list[int]] = {}
    bill_ids_by_customer: dict[int, list[int]] = {}
    for row in orders:
        cid = int(row.customer_id)
        order_ids_by_customer.setdefault(cid, []).append(int(row.id))
        chunks.setdefault(cid, []).extend(_pieces(row.marking))
        chunks.setdefault(cid, []).extend(_pieces(row.customer_marking))
    order_customer = {int(row.id): int(row.customer_id) for row in orders}
    for row in notes:
        cid = order_customer.get(int(row.customer_order_id))
        if cid is None:
            continue
        chunks.setdefault(cid, []).extend(_pieces(row.customer_notes))
    for row in bills:
        cid = int(row.customer_id)
        bill_ids_by_customer.setdefault(cid, []).append(int(row.id))
        chunks.setdefault(cid, []).extend(_pieces(row.narration))

    for cid, parts in chunks.items():
        combined = _join(parts)
        if not combined:
            continue
        for order_id in order_ids_by_customer.get(cid, []):
            conn.execute(
                sa.text(
                    "UPDATE jc_customer_orders SET marking = :text, customer_marking = NULL WHERE id = :id"
                ),
                {"text": combined, "id": order_id},
            )
        for bill_id in bill_ids_by_customer.get(cid, []):
            conn.execute(
                sa.text("UPDATE jc_customer_bills SET narration = :text WHERE id = :id"),
                {"text": combined, "id": bill_id},
            )


def downgrade() -> None:
    pass
