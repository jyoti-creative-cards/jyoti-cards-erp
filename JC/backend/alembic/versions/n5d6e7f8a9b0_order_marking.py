"""one order marking and the customer marking

Revision ID: n5d6e7f8a9b0
Revises: m4c5d6e7f8a9
Create Date: 2026-11-11 16:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "n5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "m4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jc_customer_orders", sa.Column("marking", sa.Text(), nullable=True))
    op.add_column("jc_customer_orders", sa.Column("customer_marking", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jc_customer_orders", "customer_marking")
    op.drop_column("jc_customer_orders", "marking")
