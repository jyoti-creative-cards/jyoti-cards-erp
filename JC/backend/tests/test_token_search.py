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


def test_underscore_in_token_is_literal():
    db = _db()
    db.add_all([
        _Party(name="A_B Traders", party_number=2),
        _Party(name="AXB Traders", party_number=3),
    ])
    db.commit()
    clause = token_match("a_b", [_Party.name])
    rows = db.query(_Party).filter(clause).all()
    assert [r.name for r in rows] == ["A_B Traders"]


def test_empty_query_matches_nobody():
    assert token_match("   ", [_Party.name]) is None
    assert token_match("", [_Party.name]) is None
    assert token_match(None, [_Party.name]) is None


def test_quick_search_ignores_address_landmarks():
    """A shared address word must not pull in unrelated parties."""
    import app.models  # noqa: F401 — register every table before create_all
    from app.deps import AuthContext
    from app.models.customer import Customer
    from app.routers.customers import quick_search_customers

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    db.add_all([
        Customer(
            business_name="SHOP", phone="9000000001", password_hash="x", is_active=True,
            address="Sharma lane, Kumawat market, Sai Nath road",
        ),
        Customer(
            business_name="KUMAWAT", phone="9000000002", password_hash="x", is_active=True,
            address="shop no 4",
        ),
        Customer(
            business_name="SAI NATH", phone="9000000003", password_hash="x", is_active=True,
            address="near the main shop",
        ),
        Customer(
            business_name="Sharma Cards", phone="9000000004", password_hash="x", is_active=True,
            person_name="Ramesh",
        ),
    ])
    db.commit()
    auth = AuthContext(actor_type="admin", actor_id=1, actor_name="Test")
    try:
        assert [r["business_name"] for r in quick_search_customers("sharma", db, auth)] == ["Sharma Cards"]
        assert [r["business_name"] for r in quick_search_customers("nath", db, auth)] == ["SAI NATH"]
        assert [r["business_name"] for r in quick_search_customers("shop", db, auth)] == ["SHOP"]
        assert quick_search_customers("zzzz-not-a-party", db, auth) == []
    finally:
        db.close()
        engine.dispose()
