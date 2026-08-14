"""Invoice day and enter-clock stay separate. No hardcoded customer dates."""
from datetime import date, datetime, timezone

from app.services.biz_date import (
    as_biz_date,
    bill_invoice_date,
    format_ist,
    resolve_invoice_date,
    today_ist,
)


def test_today_ist_is_date():
    assert isinstance(today_ist(), date)


def test_resolve_invoice_date_none_is_today():
    assert resolve_invoice_date(None) == today_ist()


def test_resolve_invoice_date_keeps_backdate():
    assert resolve_invoice_date(date(2026, 7, 18)) == date(2026, 7, 18)


def test_bill_invoice_date_prefers_stored_day():
    class B:
        bill_date = date(2026, 7, 1)
        created_at = datetime(2026, 8, 14, 10, 34, tzinfo=timezone.utc)
    assert bill_invoice_date(B()) == date(2026, 7, 1)


def test_bill_invoice_date_falls_back_to_created():
    class B:
        bill_date = None
        created_at = datetime(2026, 8, 14, 6, 30, tzinfo=timezone.utc)
    assert bill_invoice_date(B()) == date(2026, 8, 14)


def test_as_biz_date_utc_noon_is_ist_same_day():
    # 06:30 UTC = 12:00 IST
    assert as_biz_date(datetime(2026, 7, 1, 6, 30, tzinfo=timezone.utc)) == date(2026, 7, 1)


def test_format_ist_uses_clock_not_date_only():
    s = format_ist(datetime(2026, 8, 14, 5, 4, tzinfo=timezone.utc))
    assert "14 Aug 2026" in s
    assert "10:34" in s
