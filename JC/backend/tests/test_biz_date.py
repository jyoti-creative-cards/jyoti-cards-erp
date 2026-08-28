"""Invoice day and enter-clock stay separate. No hardcoded customer dates."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.services.biz_date import (
    as_biz_date,
    bill_invoice_date,
    format_ist,
    ist_day_bounds_utc,
    resolve_invoice_date,
    today_ist,
)
from app.services import biz_date as biz_date_mod


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


def test_resolve_biz_dt_date_uses_ist_clock_not_noon(monkeypatch):
    """Date-only pickers must stamp the real IST clock, not 12:00 PM."""
    ist = ZoneInfo("Asia/Kolkata")
    frozen = datetime(2026, 8, 28, 16, 44, 12, tzinfo=ist)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz is None else frozen.astimezone(tz)

    monkeypatch.setattr(biz_date_mod, "datetime", _FrozenDateTime)

    got = biz_date_mod.resolve_biz_dt(date(2026, 8, 28)).astimezone(ist)
    assert got.date() == date(2026, 8, 28)
    assert (got.hour, got.minute, got.second) == (16, 44, 12)

    back = biz_date_mod.resolve_biz_dt(date(2026, 7, 1)).astimezone(ist)
    assert back.date() == date(2026, 7, 1)
    assert (back.hour, back.minute, back.second) == (16, 44, 12)

    none_got = biz_date_mod.resolve_biz_dt(None).astimezone(ist)
    assert (none_got.hour, none_got.minute) == (16, 44)


def test_ist_day_bounds_still_full_calendar_day():
    start, end = ist_day_bounds_utc(date(2026, 8, 28))
    assert as_biz_date(start) == date(2026, 8, 28)
    assert as_biz_date(end) == date(2026, 8, 28)
    assert start.astimezone(ZoneInfo("Asia/Kolkata")).hour == 0
    assert end.astimezone(ZoneInfo("Asia/Kolkata")).hour == 23
