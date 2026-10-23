"""Commission agents: party orders, agent dues.

Revision ID: f7a8b9c0d1e2
Revises: e1f2a3b4c5d6
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS jc_commission_agents (
            id SERIAL PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            phone VARCHAR(32),
            notes TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS jc_commission_ledger_entries (
            id SERIAL PRIMARY KEY,
            commission_agent_id INTEGER NOT NULL REFERENCES jc_commission_agents(id) ON DELETE RESTRICT,
            entry_type VARCHAR(20) NOT NULL,
            amount NUMERIC(14, 2) NOT NULL,
            customer_bill_id INTEGER REFERENCES jc_customer_bills(id) ON DELETE SET NULL,
            customer_id INTEGER REFERENCES jc_customers(id) ON DELETE SET NULL,
            customer_return_id INTEGER,
            description TEXT,
            value_date DATE,
            created_by_type VARCHAR(20) NOT NULL,
            created_by_id INTEGER,
            created_by_name VARCHAR(200) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jc_commission_ledger_agent ON jc_commission_ledger_entries (commission_agent_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jc_commission_ledger_bill ON jc_commission_ledger_entries (customer_bill_id)"
    )
    op.execute(
        "ALTER TABLE jc_customers ADD COLUMN IF NOT EXISTS commission_agent_id INTEGER REFERENCES jc_commission_agents(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jc_customers_commission_agent ON jc_customers (commission_agent_id)"
    )
    op.execute(
        "ALTER TABLE jc_customer_bills ADD COLUMN IF NOT EXISTS commission_agent_id INTEGER REFERENCES jc_commission_agents(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jc_customer_bills_commission_agent ON jc_customer_bills (commission_agent_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE jc_customer_bills DROP COLUMN IF EXISTS commission_agent_id")
    op.execute("ALTER TABLE jc_customers DROP COLUMN IF EXISTS commission_agent_id")
    op.execute("DROP TABLE IF EXISTS jc_commission_ledger_entries")
    op.execute("DROP TABLE IF EXISTS jc_commission_agents")
