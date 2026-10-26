"""expense paid-from sources

Revision ID: g8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-10-26 13:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "g8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jc_expense_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", name="uq_jc_expense_sources_name"),
    )
    op.add_column("jc_expenses", sa.Column("source_id", sa.Integer(), nullable=True))
    op.create_index("ix_jc_expenses_source_id", "jc_expenses", ["source_id"])
    op.execute(
        sa.text(
            "INSERT INTO jc_expense_sources (name) VALUES "
            "('ICICI'), ('NC Saving Account'), ('Cash Register')"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_jc_expenses_source_id", table_name="jc_expenses")
    op.drop_column("jc_expenses", "source_id")
    op.drop_table("jc_expense_sources")
