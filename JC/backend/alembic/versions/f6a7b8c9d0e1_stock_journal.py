"""stock journal and non-cash expenses

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-01 15:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jc_expenses",
        sa.Column("is_cash", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "jc_stock_journals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("journal_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("narration", sa.Text(), nullable=True),
        sa.Column("expense_category", sa.String(length=120), nullable=True),
        sa.Column("expense_id", sa.Integer(), nullable=True),
        sa.Column("total_cost", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("created_by_name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by_name", sa.String(length=200), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_jc_stock_journals_journal_date", "jc_stock_journals", ["journal_date"])
    op.create_index("ix_jc_stock_journals_expense_id", "jc_stock_journals", ["expense_id"])
    op.create_table(
        "jc_stock_journal_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("jc_stock_journals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("catalog_product_id", sa.Integer(), sa.ForeignKey("jc_catalog_products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("our_product_id", sa.String(length=120), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("rate", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.create_index("ix_jc_stock_journal_lines_journal_id", "jc_stock_journal_lines", ["journal_id"])
    op.create_index("ix_jc_stock_journal_lines_catalog_product_id", "jc_stock_journal_lines", ["catalog_product_id"])


def downgrade() -> None:
    op.drop_table("jc_stock_journal_lines")
    op.drop_table("jc_stock_journals")
    op.drop_column("jc_expenses", "is_cash")
