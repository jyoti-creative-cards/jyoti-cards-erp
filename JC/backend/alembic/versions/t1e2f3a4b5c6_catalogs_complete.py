"""remember when a party already has every catalogue

Revision ID: t1e2f3a4b5c6
Revises: s0c1d2e3f4a5
Create Date: 2026-11-13 20:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "t1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "s0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jc_customers",
        sa.Column("catalogs_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("jc_customers", "catalogs_complete")
