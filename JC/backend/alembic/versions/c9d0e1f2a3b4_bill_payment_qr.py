"""per-bill payment QR

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-16 19:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE jc_customer_bills ADD COLUMN IF NOT EXISTS payment_qr_key VARCHAR(500)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE jc_customer_bills DROP COLUMN IF EXISTS payment_qr_key")
