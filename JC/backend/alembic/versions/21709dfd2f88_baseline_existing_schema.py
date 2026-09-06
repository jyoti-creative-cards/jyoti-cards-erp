"""baseline_existing_schema

Intentionally empty. Alembic is being adopted on a DB whose schema was built
up over time by ad-hoc `ALTER TABLE ... IF NOT EXISTS` statements in
app/db/session.py's init_db(). This revision is the marker that says "the DB
as of 2026-09-05 is our starting point" — it makes no changes. The DB is
`alembic stamp`-ed at this revision, not upgraded through it.

Known drift between models and the live schema at baseline time (index/
constraint naming from the old raw-SQL migrations vs. SQLAlchemy's naming
convention, a couple of JSONB-vs-JSON cosmetic reflection differences, a
few not-yet-enforced NOT NULL/FK constraints) is NOT captured here — write
real migrations for anything you intentionally want to change from here on.

Revision ID: 21709dfd2f88
Revises: 
Create Date: 2026-09-05 22:44:58.256624

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '21709dfd2f88'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
