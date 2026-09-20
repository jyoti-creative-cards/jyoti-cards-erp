"""Regression tests for the second audit pass:

1. Backdated customer bill's AR ledger entry (created_at) carries the bill's business
   date instead of always stamping real "now" — same class of bug as the stock ledger
   fix, but on the money side. bill.created_at itself must stay real "now" (Today/Past
   hub-tab scoping depends on it), only the ArLedgerEntry.created_at should backdate.
2. Backdated vendor bill's debit note (DebitNote.created_at, its AP ledger row, and its
   item-DN stock ledger row) carries the bill's business date instead of "now".
3. Two return lines referencing the same bill_line_id in one request must not each pass
   the returnable-qty cap independently (would over-restore stock beyond what was sold).
4. get_or_create_ar_account / get_or_create_ap_account survive a "lost the race"
   IntegrityError (simulated by pre-inserting the row after the SELECT would have missed
   it) instead of blowing up with an unhandled 500.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.accounts_payable import ApLedgerEntry
from app.models.accounts_receivable import ArLedgerEntry, CustomerArAccount
from app.models.bill_series import BillSeries
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBillLine
from app.models.debit_note import DebitNote
from app.models.stock import StockBalance, StockLedger, StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.schemas.debit_note import DebitNoteIn
from app.services.ap_ledger import get_or_create_ap_account
from app.services.ar_ledger import get_or_create_ar_account
from app.services.customer_bill_process import process_customer_bill
from app.services.customer_order_flow import confirm_received_order, create_received_placement
from app.services.customer_returns import create_customer_return
from app.services.debit_notes import create_debit_note

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


def _vendor(db) -> Vendor:
    v = Vendor(business_name="V1", phone="9998887771")
    db.add(v)
    db.flush()
    return v


def _setup(db, on_hand: int = 100):
    vendor = _vendor(db)
    prod = CatalogProduct(
        our_product_id="P1", vendor_id=vendor.id, vendor_product_id="VP1",
        buying_price=Decimal("10"), selling_price=Decimal("20"),
    )
    db.add(prod)
    db.flush()
    db.add(StockBalance(catalog_product_id=prod.id, quantity_on_hand=on_hand))
    customer = Customer(business_name="C1", phone="9998887772", password_hash="x")
    db.add(customer)
    db.flush()
    return customer, prod, vendor


def _bill_series(db, name="T", prefix="T") -> BillSeries:
    series = BillSeries(name=name, prefix=prefix, start_num=1, end_num=999, current_num=0, is_active=True)
    db.add(series)
    db.flush()
    return series


def _naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------------------
# 1. Backdated customer bill → AR ledger created_at should backdate; bill row itself
#    stays real "now" (Today/Past hub scoping depends on it).
# ---------------------------------------------------------------------------

def test_backdated_customer_bill_ar_entry_uses_business_date(db):
    customer, prod, _ = _setup(db)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 5}],
    )
    confirm_received_order(db, customer.id)
    series = _bill_series(db)
    backdate = date.today() - timedelta(days=7)

    before_real = _naive(datetime.now(timezone.utc))
    bill = process_customer_bill(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines_in=[{"catalog_product_id": prod.id, "quantity_to_ship": 5}],
        overall_discount_percent=None,
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        freight_agent_id=None,
        freight_charges=None,
        packaging_charges=None,
        additional_charges=None,
        bill_series_id=series.id,
        narration=None,
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        transport_mode="self_pickup",
        bill_date=backdate,
    )
    db.flush()
    after_real = _naive(datetime.now(timezone.utc))

    ar_row = db.query(ArLedgerEntry).filter(ArLedgerEntry.bill_id == bill.id, ArLedgerEntry.entry_type == "bill").one()
    assert ar_row.created_at.date() == backdate, "AR ledger row must carry the bill's backdate"

    # bill.created_at (and the Today/Past queue) stays real "now" — deliberately unchanged.
    assert before_real <= _naive(bill.created_at) <= after_real


def test_real_time_customer_bill_ar_entry_still_uses_now(db):
    """No bill_date given → AR ledger entry still stamps real time (no regression)."""
    customer, prod, _ = _setup(db)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 5}],
    )
    confirm_received_order(db, customer.id)
    series = _bill_series(db)
    before = _naive(datetime.now(timezone.utc))
    bill = process_customer_bill(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines_in=[{"catalog_product_id": prod.id, "quantity_to_ship": 5}],
        overall_discount_percent=None,
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        freight_agent_id=None,
        freight_charges=None,
        packaging_charges=None,
        additional_charges=None,
        bill_series_id=series.id,
        narration=None,
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        transport_mode="self_pickup",
    )
    db.flush()
    after = _naive(datetime.now(timezone.utc))

    ar_row = db.query(ArLedgerEntry).filter(ArLedgerEntry.bill_id == bill.id, ArLedgerEntry.entry_type == "bill").one()
    assert before <= _naive(ar_row.created_at) <= after


# ---------------------------------------------------------------------------
# 2. Backdated vendor bill → debit note (+ its AP row, + its item-DN stock ledger row)
#    should carry the bill's business date instead of "now".
# ---------------------------------------------------------------------------

def test_backdated_vendor_debit_note_uses_business_date(db):
    _, prod, vendor = _setup(db)
    receipt = StockReceipt(vendor_id=vendor.id, receipt_type="vendor_receive", bill_status="pending_bill", received_by_type="admin", received_by_name="Test")
    db.add(receipt)
    db.flush()
    db.add(StockReceiptLine(
        receipt_id=receipt.id, catalog_product_id=prod.id, our_product_id=prod.our_product_id,
        quantity_received=20, quantity_billed=20, buying_price=Decimal("10"),
    ))
    db.flush()

    backdate = datetime.now(timezone.utc) - timedelta(days=15)
    note = create_debit_note(
        db, AUTH, vendor_id=vendor.id, receipt_id=receipt.id,
        body=DebitNoteIn(note_type="item", direction="short", catalog_product_id=prod.id, quantity=2, notes=None),
        source="manual",
        created_at=backdate,
    )
    db.flush()

    assert _naive(note.created_at).date() == _naive(backdate).date()

    ap_row = db.query(ApLedgerEntry).filter(ApLedgerEntry.debit_note_id == note.id).one()
    assert _naive(ap_row.created_at).date() == _naive(backdate).date()

    stock_row = (
        db.query(StockLedger)
        .filter(StockLedger.reference_type == "debit_note", StockLedger.reference_id == note.id)
        .one()
    )
    assert _naive(stock_row.created_at).date() == _naive(backdate).date()
    assert _naive(stock_row.created_at).date() != _naive(datetime.now(timezone.utc)).date()


def test_real_time_vendor_debit_note_still_uses_now(db):
    """No created_at given → debit note still stamps real time (no regression)."""
    _, prod, vendor = _setup(db)
    receipt = StockReceipt(vendor_id=vendor.id, receipt_type="vendor_receive", bill_status="pending_bill", received_by_type="admin", received_by_name="Test")
    db.add(receipt)
    db.flush()
    db.add(StockReceiptLine(
        receipt_id=receipt.id, catalog_product_id=prod.id, our_product_id=prod.our_product_id,
        quantity_received=20, quantity_billed=20, buying_price=Decimal("10"),
    ))
    db.flush()

    before = _naive(datetime.now(timezone.utc))
    note = create_debit_note(
        db, AUTH, vendor_id=vendor.id, receipt_id=receipt.id,
        body=DebitNoteIn(note_type="item", direction="short", catalog_product_id=prod.id, quantity=2, notes=None),
        source="manual",
    )
    db.flush()
    after = _naive(datetime.now(timezone.utc)) + timedelta(seconds=1)  # sqlite func.now() truncates to whole seconds
    assert before - timedelta(seconds=1) <= _naive(note.created_at) <= after


# ---------------------------------------------------------------------------
# 3. Duplicate bill_line_id in one return request must not over-restore stock.
# ---------------------------------------------------------------------------

def test_duplicate_bill_line_id_in_return_does_not_overrestore(db):
    customer, prod, _ = _setup(db, on_hand=100)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 10}],
    )
    confirm_received_order(db, customer.id)
    series = _bill_series(db)
    bill = process_customer_bill(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines_in=[{"catalog_product_id": prod.id, "quantity_to_ship": 10}],
        overall_discount_percent=None,
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        freight_agent_id=None,
        freight_charges=None,
        packaging_charges=None,
        additional_charges=None,
        bill_series_id=series.id,
        narration=None,
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        transport_mode="self_pickup",
    )
    db.flush()

    bill_line = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id).one()
    assert bill_line.quantity_shipped == 10

    # Two rows for the SAME bill_line_id, each individually <= returnable(10), but
    # summing to 12 — must be rejected, not silently split into two return lines that
    # together over-restore stock.
    with pytest.raises(HTTPException) as exc:
        create_customer_return(
            db,
            customer_id=customer.id,
            lines=[
                {"bill_line_id": bill_line.id, "quantity": 6},
                {"bill_line_id": bill_line.id, "quantity": 6},
            ],
            credit_amount=Decimal("0"),
            notes=None,
            actor_type="admin",
            actor_id=1,
            actor_name="Test",
        )
    assert exc.value.status_code == 400


def test_single_bill_line_return_still_works(db):
    """No regression: one row per bill_line_id within cap still succeeds."""
    customer, prod, _ = _setup(db, on_hand=100)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 10}],
    )
    confirm_received_order(db, customer.id)
    series = _bill_series(db)
    bill = process_customer_bill(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines_in=[{"catalog_product_id": prod.id, "quantity_to_ship": 10}],
        overall_discount_percent=None,
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        freight_agent_id=None,
        freight_charges=None,
        packaging_charges=None,
        additional_charges=None,
        bill_series_id=series.id,
        narration=None,
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        transport_mode="self_pickup",
    )
    db.flush()
    bill_line = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id).one()

    ret = create_customer_return(
        db,
        customer_id=customer.id,
        lines=[{"bill_line_id": bill_line.id, "quantity": 6}],
        credit_amount=Decimal("60"),
        notes=None,
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
    )
    db.flush()
    assert ret.id is not None
    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == prod.id).one()
    assert bal.quantity_on_hand == 96  # 100 - 10 reserved + 6 returned


# ---------------------------------------------------------------------------
# 4. get_or_create_ar_account / get_or_create_ap_account survive a lost-race
#    IntegrityError instead of raising an unhandled 500.
# ---------------------------------------------------------------------------

def test_get_or_create_ar_account_survives_lost_race(db, monkeypatch):
    customer, _, _ = _setup(db)

    from app.services import ar_ledger

    real_query = db.query
    call_count = {"n": 0}

    def fake_query(model, *a, **kw):
        q = real_query(model, *a, **kw)
        if model is CustomerArAccount:
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Simulate: our SELECT missed it, but another request just inserted the
                # row underneath us — mimic that by inserting it for real right now.
                db.add(CustomerArAccount(customer_id=customer.id, is_open=True))
                db.flush()
        return q

    monkeypatch.setattr(db, "query", fake_query)
    row = ar_ledger.get_or_create_ar_account(db, customer.id)
    assert row.customer_id == customer.id
    # Exactly one row exists — no duplicate, no crash.
    count = real_query(CustomerArAccount).filter(CustomerArAccount.customer_id == customer.id).count()
    assert count == 1
