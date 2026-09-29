from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.ledger import _sortable_ts, vendor_bill_channels


def test_ledger_sort_accepts_aware_and_naive_timestamps():
    aware = datetime(2026, 9, 29, 6, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 9, 28, 12, 0)
    ordered = sorted([aware, naive], key=_sortable_ts)
    assert ordered == [naive, aware]


def test_vendor_bill_split_tags_paper_as_bank_and_remainder_as_cash():
    receipt = SimpleNamespace(
        total_billed_amount=Decimal("51991"),
        actual_ap_amount=Decimal("96051"),
        expected_extra_cash=Decimal("44060"),
    )
    bank, cash = vendor_bill_channels(receipt)
    assert bank == Decimal("51991.00")
    assert cash == Decimal("44060.00")
