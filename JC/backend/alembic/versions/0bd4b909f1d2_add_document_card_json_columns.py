"""add_document_card_json_columns

Revision ID: 0bd4b909f1d2
Revises: 21709dfd2f88
Create Date: 2026-09-22 19:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0bd4b909f1d2"
down_revision: Union[str, Sequence[str], None] = "21709dfd2f88"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jc_customer_bills", sa.Column("card_json", sa.JSON(), nullable=True))
    op.add_column("jc_customer_order_placements", sa.Column("card_json", sa.JSON(), nullable=True))
    op.add_column("jc_vendor_order_placements", sa.Column("card_json", sa.JSON(), nullable=True))
    op.add_column("jc_stock_receipts", sa.Column("card_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("jc_stock_receipts", "card_json")
    op.drop_column("jc_vendor_order_placements", "card_json")
    op.drop_column("jc_customer_order_placements", "card_json")
    op.drop_column("jc_customer_bills", "card_json")
