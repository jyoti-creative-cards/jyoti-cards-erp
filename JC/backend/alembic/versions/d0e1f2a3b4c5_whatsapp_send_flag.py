"""whatsapp send switch, off until turned on

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-10-20 18:40:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS jc_runtime_flags (
            key VARCHAR(64) PRIMARY KEY,
            value VARCHAR(32) NOT NULL
        )
        """
    )
    op.execute(
        """
        INSERT INTO jc_runtime_flags (key, value)
        VALUES ('whatsapp_sends', '0')
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS jc_runtime_flags")
