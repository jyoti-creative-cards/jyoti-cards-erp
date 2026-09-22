"""backfill_locked_document_cards

Revision ID: a1c2d3e4f5b6
Revises: 0bd4b909f1d2
Create Date: 2026-09-22 21:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.orm import sessionmaker


# revision identifiers, used by Alembic.
revision: str = "a1c2d3e4f5b6"
down_revision: Union[str, Sequence[str], None] = "0bd4b909f1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Session = sessionmaker(bind=bind)
    session = Session()
    try:
        from app.services.document_card_backfill import backfill_locked_cards

        backfill_locked_cards(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def downgrade() -> None:
    # Cards stay; clearing them would wipe intentional freeze_card data.
    pass
