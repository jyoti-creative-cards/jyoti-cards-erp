"""hand-edited Hindi sticker names stay put

Revision ID: r9b0c1d2e3f4
Revises: q8a9b0c1d2e3
Create Date: 2026-11-13 16:50:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "r9b0c1d2e3f4"
down_revision: Union[str, Sequence[str], None] = "q8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jc_sticker_labels",
        sa.Column("name_edited", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("jc_sticker_labels", "name_edited")
