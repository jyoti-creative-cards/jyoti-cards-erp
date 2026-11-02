"""freight payment date and dated product markings

Revision ID: l3a4b5c6d7e8
Revises: k2f3a4b5c6d7
Create Date: 2026-11-02 15:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "l3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "k2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jc_freight_ledger_entries", sa.Column("value_date", sa.Date(), nullable=True))
    op.add_column("jc_freight_ledger_entries", sa.Column("head", sa.String(length=120), nullable=True))
    op.execute(
        "UPDATE jc_freight_ledger_entries SET value_date = (created_at AT TIME ZONE 'Asia/Kolkata')::date WHERE value_date IS NULL"
    )
    op.create_table(
        "jc_product_markings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("catalog_product_id", sa.Integer(), sa.ForeignKey("jc_catalog_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.String(length=200), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_markings_product", "jc_product_markings", ["catalog_product_id"])
    op.execute(
        """
        INSERT INTO jc_product_markings (catalog_product_id, text, starts_on, ends_on)
        SELECT id, marking, DATE '2020-01-01', DATE '2099-12-31'
        FROM jc_catalog_products
        WHERE deleted_at IS NULL AND marking IS NOT NULL AND btrim(marking) <> ''
        """
    )


def downgrade() -> None:
    op.drop_index("ix_product_markings_product", table_name="jc_product_markings")
    op.drop_table("jc_product_markings")
    op.drop_column("jc_freight_ledger_entries", "head")
    op.drop_column("jc_freight_ledger_entries", "value_date")
