"""A long edit note must still save. The history column is only 500 characters."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.entity_history import EntityHistory
from app.services.history import record_entity_history


def test_long_change_summary_is_stored():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        record_entity_history(
            session,
            "stock_receipt",
            183,
            {"lines": []},
            "line " + ("x" * 900),
        )
        session.commit()
        row = session.query(EntityHistory).one()
        assert len(row.change_summary) == 500
        assert row.change_summary.endswith("...")
    finally:
        session.close()
        engine.dispose()
