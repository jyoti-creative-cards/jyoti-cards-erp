"""Round-2 finance audit H1 fix: editing a received bill posts a compensating
`adjustment` ledger row that reverses the original `bill` entry (money history is
never mutated in place — see ap_ledger.py's own comment). `vendor_ap_totals()` and
`list_ap_vendors()` used to sum only `entry_type == "bill"` rows into `bill_total`,
so after any such edit the vendor statement's
`Opening + Total bills + Bill corrections - Paid` breakdown silently stopped adding
up to the displayed `Outstanding`, even though `outstanding` itself (a sum over all
row types) was always correct. Fix folds bill-reversing `adjustment` rows into
`bill_total` in both functions so the breakdown reconciles again.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.accounts_payable import ApLedgerEntry
from app.models.vendor import Vendor
from app.services.ap_ledger import list_ap_vendors, vendor_ap_totals


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


def _setup(db):
    vendor = Vendor(business_name="Test Vendor", phone="9999999999")
    db.add(vendor)
    db.flush()

    bill = ApLedgerEntry(
        vendor_id=vendor.id, entry_type="bill", amount=Decimal("1000.00"),
        description="Bill #1", created_by_type="admin", created_by_name="Test",
    )
    db.add(bill)
    db.flush()

    # Simulate a post-receipt bill edit: correcting the total from 1000 -> 1200 posts a
    # compensating +200 adjustment reversing the original bill, per sync_receipt_bill_ledger.
    adjustment = ApLedgerEntry(
        vendor_id=vendor.id, entry_type="adjustment", amount=Decimal("200.00"),
        reverses_entry_id=bill.id, description="Bill #1 correction",
        created_by_type="admin", created_by_name="Test",
    )
    db.add(adjustment)

    payment = ApLedgerEntry(
        vendor_id=vendor.id, entry_type="payment", amount=Decimal("-500.00"),
        description="Payment", created_by_type="admin", created_by_name="Test",
    )
    db.add(payment)
    db.commit()
    return vendor


def test_vendor_ap_totals_bill_total_includes_bill_edit_adjustment(db):
    vendor = _setup(db)
    totals = vendor_ap_totals(db, vendor.id)

    # outstanding = 1000 + 200 - 500 = 700
    assert totals["outstanding"] == Decimal("700.00")
    # bill_total must fold in the +200 correction, not just the original 1000 bill row,
    # or opening + bill_total + debit_note_total - payment_total != outstanding.
    assert totals["bill_total"] == Decimal("1200.00")
    assert totals["debit_note_total"] == Decimal("0.00")
    assert totals["payment_total"] == Decimal("500.00")

    reconciled = (
        totals["opening_total"] + totals["bill_total"] + totals["debit_note_total"] - totals["payment_total"]
    )
    assert reconciled == totals["outstanding"]


def test_list_ap_vendors_bill_total_includes_bill_edit_adjustment(db):
    vendor = _setup(db)
    rows = list_ap_vendors(db)
    row = next(r for r in rows if r["vendor_id"] == vendor.id)

    assert row["outstanding"] == "700.00"
    assert row["bill_total"] == "1200.00"
