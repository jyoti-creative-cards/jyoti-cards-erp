"""When a letter series such as B1-1000 is finished, the next letter opens."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.bill_series import BillSeries
from app.services.bill_series_alloc import ensure_next_letter_series


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    return session


def test_finished_b_series_opens_c():
    db = _db()
    db.add(BillSeries(name="B1-1000", prefix="B", start_num=1, end_num=1000, current_num=1000, is_active=True))
    db.commit()
    row = ensure_next_letter_series(db)
    assert row is not None
    assert row.prefix == "C"
    assert row.name == "C1-1000"
    assert row.start_num == 1
    assert row.end_num == 1000
    assert row.current_num == 0
    again = ensure_next_letter_series(db)
    assert again.id == row.id


def test_open_b_series_stays_the_default():
    db = _db()
    db.add(BillSeries(name="B1-1000", prefix="B", start_num=1, end_num=1000, current_num=40, is_active=True))
    db.commit()
    row = ensure_next_letter_series(db)
    assert row.prefix == "B"
    assert db.query(BillSeries).count() == 1


def test_finished_c_opens_d():
    db = _db()
    db.add(BillSeries(name="B1-1000", prefix="B", start_num=1, end_num=1000, current_num=1000, is_active=True))
    db.add(BillSeries(name="C1-1000", prefix="C", start_num=1, end_num=1000, current_num=1000, is_active=True))
    db.commit()
    row = ensure_next_letter_series(db)
    assert row.prefix == "D"
