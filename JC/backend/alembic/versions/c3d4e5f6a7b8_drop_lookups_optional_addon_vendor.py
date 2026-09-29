"""drop catalog lookups and make add-on vendor optional

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-29 08:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("jc_addon_products", "vendor_id", existing_type=sa.Integer(), nullable=True)
    op.drop_table("jc_catalog_lookups")


def downgrade() -> None:
    op.create_table(
        "jc_catalog_lookups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lookup_type", sa.String(length=30), nullable=False),
        sa.Column("value", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_jc_catalog_lookups_lookup_type", "jc_catalog_lookups", ["lookup_type"])
    op.alter_column("jc_addon_products", "vendor_id", existing_type=sa.Integer(), nullable=False)
