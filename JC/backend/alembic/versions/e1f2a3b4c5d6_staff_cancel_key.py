"""staff cancel key

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-10-22 09:00:00.000000

"""
from typing import Sequence, Union

import bcrypt
import sqlalchemy as sa
from alembic import op


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Named keys from the desk. Anyone else sets theirs in Staff.
_NAMED = (
    ("nikhil", "aa"),
    ("raj", "bb"),
)


def upgrade() -> None:
    op.execute("ALTER TABLE jc_staff ADD COLUMN IF NOT EXISTS cancel_key_hash VARCHAR(255)")
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, name, cancel_key_hash FROM jc_staff WHERE deleted_at IS NULL")).fetchall()
    for staff_id, name, existing in rows:
        if existing:
            continue
        folded = (name or "").strip().lower()
        for needle, plain in _NAMED:
            if needle in folded:
                hashed = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
                conn.execute(
                    sa.text("UPDATE jc_staff SET cancel_key_hash = :h WHERE id = :id AND cancel_key_hash IS NULL"),
                    {"h": hashed, "id": staff_id},
                )
                break


def downgrade() -> None:
    op.execute("ALTER TABLE jc_staff DROP COLUMN IF EXISTS cancel_key_hash")
