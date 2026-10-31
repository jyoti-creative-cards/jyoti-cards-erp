"""price history effective from date

Revision ID: j1e2f3a4b5c6
Revises: i0d1e2f3a4b5
Create Date: 2026-10-31 13:20:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "j1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "i0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jc_price_history", sa.Column("effective_from", sa.Date(), nullable=True))
    op.execute(
        "UPDATE jc_price_history SET effective_from = (recorded_at AT TIME ZONE 'Asia/Kolkata')::date "
        "WHERE effective_from IS NULL"
    )


def downgrade() -> None:
    op.drop_column("jc_price_history", "effective_from")
