"""expense paid from a payment account

Revision ID: v3c4d5e6f7a8
Revises: u2b3c4d5e6f7
Create Date: 2026-11-28 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "v3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "u2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE jc_expenses ADD COLUMN IF NOT EXISTS payment_mode_id INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE jc_expenses DROP COLUMN IF EXISTS payment_mode_id")
