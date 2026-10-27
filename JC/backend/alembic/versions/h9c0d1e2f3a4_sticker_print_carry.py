"""bus or transport on a sticker print

Revision ID: h9c0d1e2f3a4
Revises: g8b9c0d1e2f3
Create Date: 2026-10-27 16:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "h9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "g8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jc_sticker_prints", sa.Column("carry", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("jc_sticker_prints", "carry")
