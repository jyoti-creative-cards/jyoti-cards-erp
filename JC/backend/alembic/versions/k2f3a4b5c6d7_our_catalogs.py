"""our physical catalogues

Revision ID: k2f3a4b5c6d7
Revises: j1e2f3a4b5c6
Create Date: 2026-11-02 12:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "k2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "j1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jc_our_catalogs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("copies_made", sa.Integer(), nullable=False),
        sa.Column("expense_id", sa.Integer(), nullable=True),
        sa.Column("stock_journal_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("stock_journal_id", name="uq_our_catalog_journal"),
    )
    op.create_table(
        "jc_our_catalog_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("catalog_id", sa.Integer(), sa.ForeignKey("jc_our_catalogs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("catalog_product_id", sa.Integer(), sa.ForeignKey("jc_catalog_products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.UniqueConstraint("catalog_id", "catalog_product_id", name="uq_our_catalog_line"),
    )
    op.create_index("ix_our_catalog_lines_catalog", "jc_our_catalog_lines", ["catalog_id"])
    op.create_table(
        "jc_our_catalog_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("catalog_id", sa.Integer(), sa.ForeignKey("jc_our_catalogs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("jc_customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("catalog_id", "customer_id", name="uq_our_catalog_assignment"),
    )
    op.create_index("ix_our_catalog_assign_catalog", "jc_our_catalog_assignments", ["catalog_id"])
    op.create_index("ix_our_catalog_assign_customer", "jc_our_catalog_assignments", ["customer_id"])
    op.create_table(
        "jc_our_catalog_issues",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("catalog_id", sa.Integer(), sa.ForeignKey("jc_our_catalogs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("jc_customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("copies", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("bill_id", sa.Integer(), sa.ForeignKey("jc_customer_bills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_our_catalog_issues_catalog", "jc_our_catalog_issues", ["catalog_id"])
    op.create_index("ix_our_catalog_issues_customer", "jc_our_catalog_issues", ["customer_id"])
    op.create_index("ix_our_catalog_issues_bill", "jc_our_catalog_issues", ["bill_id"])


def downgrade() -> None:
    op.drop_table("jc_our_catalog_issues")
    op.drop_table("jc_our_catalog_assignments")
    op.drop_table("jc_our_catalog_lines")
    op.drop_table("jc_our_catalogs")
