"""expense addon product link

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-30 10:25:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE jc_expenses ADD COLUMN IF NOT EXISTS addon_product_id INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE jc_expenses DROP COLUMN IF EXISTS addon_product_id")
