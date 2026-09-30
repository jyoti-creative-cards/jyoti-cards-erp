"""customer order source and who placed it

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-29 18:50:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jc_customer_order_placements", sa.Column("order_source", sa.String(length=20), nullable=True))
    op.add_column("jc_customer_order_placements", sa.Column("placed_by_name", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("jc_customer_order_placements", "placed_by_name")
    op.drop_column("jc_customer_order_placements", "order_source")
