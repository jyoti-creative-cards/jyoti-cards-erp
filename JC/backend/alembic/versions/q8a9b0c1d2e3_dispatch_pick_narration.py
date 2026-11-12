"""narration written when dispatching and when marking picked

Revision ID: q8a9b0c1d2e3
Revises: p7f8a9b0c1d2
Create Date: 2026-11-12 15:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "q8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "p7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jc_customer_bills", sa.Column("dispatch_narration", sa.Text(), nullable=True))
    op.add_column("jc_customer_bills", sa.Column("dispatch_narration_by", sa.String(length=200), nullable=True))
    op.add_column("jc_customer_bills", sa.Column("dispatch_narration_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jc_customer_bills", sa.Column("pick_narration", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jc_customer_bills", "pick_narration")
    op.drop_column("jc_customer_bills", "dispatch_narration_at")
    op.drop_column("jc_customer_bills", "dispatch_narration_by")
    op.drop_column("jc_customer_bills", "dispatch_narration")
