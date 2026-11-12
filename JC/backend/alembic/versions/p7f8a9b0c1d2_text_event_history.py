"""history of markings and tile notes

Revision ID: p7f8a9b0c1d2
Revises: o6e7f8a9b0c1
Create Date: 2026-11-12 13:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "p7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "o6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jc_text_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jc_text_events_kind", "jc_text_events", ["kind"])
    op.create_index("ix_jc_text_events_subject", "jc_text_events", ["subject"])


def downgrade() -> None:
    op.drop_index("ix_jc_text_events_subject", table_name="jc_text_events")
    op.drop_index("ix_jc_text_events_kind", table_name="jc_text_events")
    op.drop_table("jc_text_events")
