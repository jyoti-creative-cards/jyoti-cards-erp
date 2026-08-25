"""void/restore/purge — stock + AP correctness for receipts, bills, and debit notes."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.accounts_payable import ApLedgerEntry
from app.models.debit_note import DebitNote
from app.models.stock import StockBalance, StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.services.ap_ledger import post_bill_entry, post_debit_note_entry
from app.services.debit_notes import create_debit_note
from app.services.void_service import (
    purge_debit_note,
    purge_receipt,
    restore_debit_note,
    restore_receipt,
    void_debit_note,
    void_receipt,
)
from app.schemas.debit_note import DebitNoteIn


AUTH = AuthContext(actor_type="admin", actor_id=1, actor_name="Test Admin")


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
        engine.dispose()


def _vendor(db, billing_pct=Decimal("100")) -> Vendor:
    v = Vendor(
        business_name="Test Vendor", phone="9999999999", billing_pct=billing_pct,
        additional_charge=Decimal("0"), additional_charge_label="Additional charge",
        discount_pct=Decimal("0"), gst_included=True, gst_rate_pct=Decimal("18"),
    )
    db.add(v)
    db.flush()
    return v


def _receipt(db, vendor_id: int, qty: int = 10, price=Decimal("10")) -> tuple[StockReceipt, StockReceiptLine]:
    r = StockReceipt(
        vendor_id=vendor_id, receipt_type="vendor_order", bill_status="pending_bill",
        received_by_type="admin", received_by_name="Test",
    )
    db.add(r)
    db.flush()
    ln = StockReceiptLine(
        receipt_id=r.id, catalog_product_id=1, our_product_id="P1",
        quantity_received=qty, buying_price=price,
    )
    db.add(ln)
    db.flush()
    from app.services.stock_receipt import add_stock
    add_stock(db, catalog_product_id=1, our_product_id="P1", quantity=qty, entry_type="receive",
              reference_type="stock_receipt", reference_id=r.id)
    db.commit()
    return r, ln


def _bill(db, r: StockReceipt, ln: StockReceiptLine, amount: Decimal) -> None:
    r.bill_status = "billed"
    r.total_billed_amount = amount
    r.billed_at = datetime.now(timezone.utc)
    ln.quantity_billed = ln.quantity_received
    ln.billed_amount = amount
    post_bill_entry(
        db, vendor_id=r.vendor_id, receipt_id=r.id, amount=amount, description="Bill",
        actor_type="admin", actor_id=1, actor_name="Test",
    )
    db.commit()


def test_void_pending_receipt_reverses_stock(db):
    vendor = _vendor(db)
    r, ln = _receipt(db, vendor.id, qty=10)
    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == 1).one()
    assert bal.quantity_on_hand == 10

    void_receipt(db, AUTH, r.id, "test mistake")
    db.refresh(bal)
    assert bal.quantity_on_hand == 0
    r2 = db.get(StockReceipt, r.id)
    assert r2.deleted_at is not None
    assert r2.deleted_reason == "test mistake"


def test_void_billed_receipt_excludes_ap_and_reverses_stock(db):
    vendor = _vendor(db)
    r, ln = _receipt(db, vendor.id, qty=10, price=Decimal("10"))
    _bill(db, r, ln, Decimal("100"))

    active = db.query(ApLedgerEntry).filter(ApLedgerEntry.deleted_at.is_(None)).all()
    assert len(active) == 1
    assert active[0].amount == Decimal("100.00")

    void_receipt(db, AUTH, r.id, None)

    active_after = db.query(ApLedgerEntry).filter(ApLedgerEntry.deleted_at.is_(None)).all()
    assert active_after == []
    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == 1).one()
    assert bal.quantity_on_hand == 0


def test_restore_receipt_reapplies_stock_and_ap(db):
    vendor = _vendor(db)
    r, ln = _receipt(db, vendor.id, qty=10)
    _bill(db, r, ln, Decimal("100"))

    void_receipt(db, AUTH, r.id, "oops")
    restore_receipt(db, AUTH, r.id)

    r2 = db.get(StockReceipt, r.id)
    assert r2.deleted_at is None
    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == 1).one()
    assert bal.quantity_on_hand == 10
    active = db.query(ApLedgerEntry).filter(ApLedgerEntry.deleted_at.is_(None)).all()
    assert len(active) == 1
    assert active[0].amount == Decimal("100.00")


def test_purge_receipt_removes_rows_requires_void_first(db):
    vendor = _vendor(db)
    r, ln = _receipt(db, vendor.id, qty=10)
    _bill(db, r, ln, Decimal("100"))

    with pytest.raises(Exception):
        purge_receipt(db, AUTH, r.id)  # not voided yet

    void_receipt(db, AUTH, r.id, None)
    purge_receipt(db, AUTH, r.id)

    assert db.get(StockReceipt, r.id) is None
    assert db.query(ApLedgerEntry).filter(ApLedgerEntry.receipt_id == r.id).count() == 0


def test_void_item_debit_note_reverses_its_own_stock_and_ap(db):
    vendor = _vendor(db)
    r, ln = _receipt(db, vendor.id, qty=10, price=Decimal("10"))
    _bill(db, r, ln, Decimal("100"))

    note = create_debit_note(
        db, AUTH, vendor_id=vendor.id, receipt_id=r.id,
        body=DebitNoteIn(note_type="item", direction="short", catalog_product_id=1, quantity=2),
    )
    db.commit()

    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == 1).one()
    assert bal.quantity_on_hand == 8  # 10 received - 2 short (item DN reduces stock)

    void_debit_note(db, AUTH, note.id, "wrong note")
    db.refresh(bal)
    assert bal.quantity_on_hand == 10  # reversed back

    active_dn_entries = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.debit_note_id == note.id, ApLedgerEntry.deleted_at.is_(None))
        .all()
    )
    assert active_dn_entries == []

    restore_debit_note(db, AUTH, note.id)
    db.refresh(bal)
    assert bal.quantity_on_hand == 8
    active_dn_entries = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.debit_note_id == note.id, ApLedgerEntry.deleted_at.is_(None))
        .all()
    )
    assert len(active_dn_entries) == 1


def test_purge_debit_note_requires_void_first(db):
    vendor = _vendor(db)
    r, ln = _receipt(db, vendor.id, qty=10, price=Decimal("10"))
    _bill(db, r, ln, Decimal("100"))
    note = create_debit_note(
        db, AUTH, vendor_id=vendor.id, receipt_id=r.id,
        body=DebitNoteIn(note_type="value", direction="over", amount=Decimal("20")),
    )
    db.commit()

    with pytest.raises(Exception):
        purge_debit_note(db, AUTH, note.id)

    void_debit_note(db, AUTH, note.id, None)
    purge_debit_note(db, AUTH, note.id)
    assert db.get(DebitNote, note.id) is None


def test_void_receipt_does_not_touch_independently_voided_debit_note(db):
    """Voiding a receipt must not resurrect a note voided earlier in a separate action."""
    vendor = _vendor(db)
    r, ln = _receipt(db, vendor.id, qty=10, price=Decimal("10"))
    _bill(db, r, ln, Decimal("100"))
    note = create_debit_note(
        db, AUTH, vendor_id=vendor.id, receipt_id=r.id,
        body=DebitNoteIn(note_type="value", direction="over", amount=Decimal("20")),
    )
    db.commit()

    void_debit_note(db, AUTH, note.id, "independent void")
    first_voided_at = db.get(DebitNote, note.id).deleted_at

    void_receipt(db, AUTH, r.id, "receipt also voided")
    restore_receipt(db, AUTH, r.id)

    note2 = db.get(DebitNote, note.id)
    assert note2.deleted_at == first_voided_at  # still independently voided, not resurrected
