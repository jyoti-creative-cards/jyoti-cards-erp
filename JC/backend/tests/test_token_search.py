"""token_match exact_int_columns — numeric # search must be exact, not substring."""
from __future__ import annotations

from sqlalchemy import Integer, String, create_engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from app.db.session import Base
from app.services.token_search import token_match


class _Party(Base):
    __tablename__ = "test_parties_token_search"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    party_number: Mapped[int] = mapped_column(Integer, nullable=True)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[_Party.__table__])
    return sessionmaker(bind=engine)()


def _seed(db):
    db.add_all([
        _Party(name="Alpha Traders", party_number=1),
        _Party(name="Beta Traders", party_number=11),
        _Party(name="Gamma Traders", party_number=111),
    ])
    db.commit()


def test_numeric_token_exact_matches_party_number_only():
    db = _db()
    _seed(db)
    clause = token_match("1", [_Party.name], exact_int_columns=[_Party.party_number])
    rows = db.query(_Party).filter(clause).all()
    assert [r.party_number for r in rows] == [1]


def test_name_token_still_uses_substring():
    db = _db()
    _seed(db)
    clause = token_match("traders", [_Party.name], exact_int_columns=[_Party.party_number])
    rows = db.query(_Party).filter(clause).all()
    assert len(rows) == 3
