"""add category_3 on catalog products

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-15 10:20:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE jc_catalog_products ADD COLUMN IF NOT EXISTS category_3 VARCHAR(120)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jc_catalog_products_category_3 ON jc_catalog_products (category_3)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jc_catalog_products_category_3")
    op.execute("ALTER TABLE jc_catalog_products DROP COLUMN IF EXISTS category_3")
