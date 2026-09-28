"""add second_category on catalog products

Revision ID: b2c3d4e5f6a7
Revises: a1c2d3e4f5b6
Create Date: 2026-09-28 16:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1c2d3e4f5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jc_catalog_products",
        sa.Column("second_category", sa.String(length=120), nullable=True),
    )
    op.create_index(
        "ix_jc_catalog_products_second_category",
        "jc_catalog_products",
        ["second_category"],
    )


def downgrade() -> None:
    op.drop_index("ix_jc_catalog_products_second_category", table_name="jc_catalog_products")
    op.drop_column("jc_catalog_products", "second_category")
