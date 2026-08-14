"""Stock balance ↔ ledger integrity helpers."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.stock import StockBalance, StockLedger
from app.services.reconcile import stock_balance_mismatches
from app.services.stock_receipt import add_stock


def test_stock_balance_matches_ledger():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[StockBalance.__table__, StockLedger.__table__])
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        add_stock(
            db,
            catalog_product_id=1,
            our_product_id="P1",
            quantity=10,
            entry_type="receive",
            reference_type="test",
            reference_id=1,
        )
        add_stock(
            db,
            catalog_product_id=1,
            our_product_id="P1",
            quantity=-3,
            entry_type="bill",
            reference_type="test",
            reference_id=2,
        )
        db.commit()
        assert stock_balance_mismatches(db) == []
        bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == 1).one()
        bal.quantity_on_hand = 99
        db.commit()
        bad = stock_balance_mismatches(db)
        assert len(bad) == 1
        assert bad[0]["ledger_sum"] == 7
        assert bad[0]["quantity_on_hand"] == 99
    finally:
        db.close()
        engine.dispose()


def test_mag_still_ok():
    from app.services.money import mag

    assert mag(Decimal("-1.2")) == Decimal("1.20")
