"""per-item stock alert percent

Revision ID: s0c1d2e3f4a5
Revises: r9b0c1d2e3f4
Create Date: 2026-11-13 19:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "s0c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "r9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jc_catalog_products",
        sa.Column("stock_alert_percent", sa.Numeric(6, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jc_catalog_products", "stock_alert_percent")
