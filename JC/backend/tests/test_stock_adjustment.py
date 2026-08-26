"""Manual stock adjustment — correction without any order/receipt."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.stock import StockBalance, StockLedger
from app.services.reconcile import stock_balance_mismatches
from app.services.stock_receipt import add_stock


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[StockBalance.__table__, StockLedger.__table__])
    Session = sessionmaker(bind=engine)
    return Session(), engine


def test_manual_adjustment_increases_stock_and_logs_ledger():
    db, engine = _session()
    try:
        add_stock(
            db, catalog_product_id=1, our_product_id="P1", quantity=10,
            entry_type="receive", reference_type="test", reference_id=1,
        )
        balance = add_stock(
            db, catalog_product_id=1, our_product_id="P1", quantity=5,
            entry_type="manual_adjustment", reference_type="manual_adjustment", reference_id=1,
            party="Admin", notes="Physical recount — found extra units",
        )
        db.commit()
        assert balance.quantity_on_hand == 15
        entry = (
            db.query(StockLedger)
            .filter(StockLedger.catalog_product_id == 1, StockLedger.entry_type == "manual_adjustment")
            .one()
        )
        assert entry.quantity_delta == 5
        assert entry.balance_after == 15
        assert entry.notes == "Physical recount — found extra units"
        assert entry.party == "Admin"
        assert stock_balance_mismatches(db) == []
    finally:
        db.close()
        engine.dispose()


def test_manual_adjustment_can_decrease_and_go_negative():
    db, engine = _session()
    try:
        add_stock(
            db, catalog_product_id=2, our_product_id="P2", quantity=3,
            entry_type="receive", reference_type="test", reference_id=1,
        )
        balance = add_stock(
            db, catalog_product_id=2, our_product_id="P2", quantity=-8,
            entry_type="manual_adjustment", reference_type="manual_adjustment", reference_id=2,
            party="Admin", notes="Damaged stock written off",
        )
        db.commit()
        # Negative on-hand is allowed for manual corrections — matches vendor void/restore behavior.
        assert balance.quantity_on_hand == -5
        assert stock_balance_mismatches(db) == []
    finally:
        db.close()
        engine.dispose()


def test_manual_adjustment_creates_balance_row_if_missing():
    db, engine = _session()
    try:
        balance = add_stock(
            db, catalog_product_id=3, our_product_id="P3", quantity=7,
            entry_type="manual_adjustment", reference_type="manual_adjustment", reference_id=3,
            party="Admin", notes="Initial correction for untracked item",
        )
        db.commit()
        assert balance.quantity_on_hand == 7
        assert db.query(StockBalance).filter(StockBalance.catalog_product_id == 3).count() == 1
    finally:
        db.close()
        engine.dispose()
