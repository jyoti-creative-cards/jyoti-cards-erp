"""product marking can be shown on the customer bill

Revision ID: u2b3c4d5e6f7
Revises: t1e2f3a4b5c6
Create Date: 2026-11-17 19:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "u2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "t1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jc_product_markings",
        sa.Column("show_to_party", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("jc_product_markings", "show_to_party")
