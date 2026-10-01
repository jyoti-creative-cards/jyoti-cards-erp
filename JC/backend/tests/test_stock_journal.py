"""Stock journal: transfer leftover qty, consume sample catalogues, keep cash out clean."""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.accounts_payable import ApLedgerEntry
from app.models.accounts_receivable import ArLedgerEntry
from app.models.catalog_product import CatalogProduct
from app.models.expense import Expense
from app.models.stock import StockBalance
from app.models.vendor import Vendor
from app.schemas.stock_journal import JournalIn, JournalLineIn
from app.services.biz_date import today_ist
from app.services.reports import daybook
from app.services.stock_journal import post_journal, preview_journal, void_journal
from app.services.stock_receipt import add_stock

import app.models  # noqa: F401 — register journal tables on Base.metadata


AUTH = AuthContext(actor_type="admin", actor_id=None, actor_name="Admin", permissions=set())


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _vendor(db) -> Vendor:
    row = Vendor(business_name="Journal Vendor", phone="9000001111")
    db.add(row)
    db.flush()
    return row


def _product(db, vendor, number, *, category="Album 1", buying=Decimal("5.00"), stock=10) -> CatalogProduct:
    row = CatalogProduct(
        our_product_id=number,
        vendor_id=vendor.id,
        vendor_product_id=number,
        category=category,
        buying_price=buying,
        selling_price=Decimal("9.00"),
        image_keys=[],
        is_active=True,
    )
    db.add(row)
    db.flush()
    if stock:
        add_stock(
            db,
            catalog_product_id=row.id,
            our_product_id=row.our_product_id,
            quantity=stock,
            entry_type="opening",
            reference_type="test",
            reference_id=row.id,
        )
    db.flush()
    return row


def _hand(db, product_id: int) -> int:
    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == product_id).one()
    return int(bal.quantity_on_hand)


def test_transfer_moves_qty_without_cash_or_bills(db):
    vendor = _vendor(db)
    old = _product(db, vendor, "5002", buying=Decimal("10.00"), stock=40, category="Old")
    new = _product(db, vendor, "5003", buying=Decimal("25.00"), stock=0, category="New")
    body = JournalIn(
        journal_date=today_ist(),
        kind="transfer",
        narration="Leftover 5002 becomes 5003",
        from_product_id=old.id,
        to_product_id=new.id,
        quantity=10,
    )
    preview = preview_journal(db, body)
    assert any("25.00" in w and "10.00" in w for w in preview.warnings)
    saved = post_journal(db, body, AUTH)
    assert saved.id
    assert _hand(db, old.id) == 30
    assert _hand(db, new.id) == 10
    assert db.query(Expense).count() == 0
    assert db.query(ApLedgerEntry).count() == 0
    assert db.query(ArLedgerEntry).count() == 0
    book = daybook(db, day=today_ist())
    assert Decimal(book["totals"]["cash_out"]) == 0


def test_album_consumption_is_expense_not_cash(db):
    vendor = _vendor(db)
    a = _product(db, vendor, "A1", buying=Decimal("5.00"), stock=10)
    b = _product(db, vendor, "A2", buying=Decimal("3.00"), stock=10)
    cash = Expense(
        expense_date=today_ist(),
        category="rent",
        amount=Decimal("10.00"),
        is_cash=True,
        created_by_name="Admin",
    )
    db.add(cash)
    db.commit()
    saved = post_journal(
        db,
        JournalIn(
            journal_date=today_ist(),
            kind="consumption",
            narration="200 catalogues",
            expense_category="Sample catalogues",
            album="album 1",
            copies=4,
        ),
        AUTH,
    )
    assert {ln.our_product_id for ln in saved.lines} == {"A1", "A2"}
    assert all(ln.quantity_delta == -4 for ln in saved.lines)
    assert Decimal(saved.total_cost) == Decimal("32.00")
    assert _hand(db, a.id) == 6
    assert _hand(db, b.id) == 6
    expense = db.get(Expense, saved.expense_id)
    assert expense is not None
    assert expense.is_cash is False
    assert expense.amount == Decimal("32.00")
    book = daybook(db, day=today_ist())
    assert Decimal(book["totals"]["cash_out"]) == Decimal("10.00")
    kinds = {row["kind"] for row in book["entries"]}
    assert "stock_journal" in kinds
    assert "expense" in kinds


def test_missing_rate_and_oversell_blocked(db):
    vendor = _vendor(db)
    bare = _product(db, vendor, "NORATE", buying=None, stock=5)
    with pytest.raises(HTTPException) as missing:
        post_journal(
            db,
            JournalIn(
                journal_date=today_ist(),
                kind="consumption",
                lines=[JournalLineIn(catalog_product_id=bare.id, quantity=1)],
            ),
            AUTH,
        )
    assert missing.value.status_code == 400
    priced = _product(db, vendor, "LOW", buying=Decimal("2.00"), stock=3)
    with pytest.raises(HTTPException) as over:
        post_journal(
            db,
            JournalIn(
                journal_date=today_ist(),
                kind="consumption",
                lines=[JournalLineIn(catalog_product_id=priced.id, quantity=9)],
            ),
            AUTH,
        )
    assert over.value.status_code == 400
    assert _hand(db, priced.id) == 3


def test_void_restores_stock_and_drops_expense(db):
    vendor = _vendor(db)
    item = _product(db, vendor, "S1", buying=Decimal("4.00"), stock=8)
    saved = post_journal(
        db,
        JournalIn(
            journal_date=today_ist(),
            kind="consumption",
            lines=[JournalLineIn(catalog_product_id=item.id, quantity=2)],
        ),
        AUTH,
    )
    assert _hand(db, item.id) == 6
    void_journal(db, saved.id, "Wrong catalogue", AUTH)
    assert _hand(db, item.id) == 8
    assert db.query(Expense).filter(Expense.reference == f"journal:{saved.id}").count() == 0
    book = daybook(db, day=today_ist())
    assert Decimal(book["totals"]["cash_out"]) == 0
