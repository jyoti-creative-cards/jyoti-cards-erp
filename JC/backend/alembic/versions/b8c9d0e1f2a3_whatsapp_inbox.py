"""whatsapp inbox messages

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-15 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS jc_whatsapp_messages (
            id SERIAL PRIMARY KEY,
            wamid VARCHAR(160) NOT NULL,
            direction VARCHAR(8) NOT NULL,
            phone VARCHAR(20) NOT NULL,
            contact_name VARCHAR(200),
            customer_id INTEGER,
            message_type VARCHAR(32) NOT NULL DEFAULT 'text',
            body TEXT NOT NULL DEFAULT '',
            wa_timestamp TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_jc_whatsapp_messages_wamid ON jc_whatsapp_messages (wamid)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jc_whatsapp_messages_phone ON jc_whatsapp_messages (phone)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jc_whatsapp_messages_direction ON jc_whatsapp_messages (direction)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jc_whatsapp_messages_customer_id ON jc_whatsapp_messages (customer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jc_whatsapp_messages_wa_timestamp ON jc_whatsapp_messages (wa_timestamp)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS jc_whatsapp_messages")
