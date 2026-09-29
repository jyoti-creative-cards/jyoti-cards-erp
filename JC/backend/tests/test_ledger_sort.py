from datetime import datetime, timezone

from app.services.ledger import _sortable_ts


def test_ledger_sort_accepts_aware_and_naive_timestamps():
    aware = datetime(2026, 9, 29, 6, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 9, 28, 12, 0)
    ordered = sorted([aware, naive], key=_sortable_ts)
    assert ordered == [naive, aware]
