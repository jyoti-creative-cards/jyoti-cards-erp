"""Business calendar dates (Asia/Kolkata) for backdated orders / bills / receives."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException

_BIZ_TZ = ZoneInfo("Asia/Kolkata")


def resolve_biz_dt(d: date | datetime | None) -> datetime:
    """Resolve optional client date to UTC datetime.

    - None → now (UTC)
    - date → noon that day in Asia/Kolkata (stable for IST day filters)
    - datetime → converted to UTC (naive treated as Kolkata wall time)
    """
    if d is None:
        return datetime.now(timezone.utc)
    if isinstance(d, datetime):
        if d.tzinfo is None:
            local = d.replace(tzinfo=_BIZ_TZ)
        else:
            local = d.astimezone(_BIZ_TZ)
    else:
        local = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=_BIZ_TZ)

    today = datetime.now(_BIZ_TZ).date()
    if local.date() > today + timedelta(days=1):
        raise HTTPException(400, "date cannot be in the future")
    if local.date() < today - timedelta(days=3650):
        raise HTTPException(400, "date too far in the past")
    return local.astimezone(timezone.utc)


def as_biz_date(d: date | datetime | None) -> date | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        ts = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        return ts.astimezone(_BIZ_TZ).date()
    return d


def today_ist() -> date:
    return datetime.now(_BIZ_TZ).date()


def to_ist(dt: datetime | None) -> datetime:
    ts = dt or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_BIZ_TZ)


def format_ist(dt: datetime | None) -> str:
    return to_ist(dt).strftime("%d %b %Y, %I:%M %p IST")


def format_ist_day(d: date | datetime | None) -> str:
    if d is None:
        d = today_ist()
    if isinstance(d, datetime):
        d = as_biz_date(d) or today_ist()
    return d.strftime("%d %b %Y")


def resolve_invoice_date(bill_date: date | datetime | None) -> date:
    """Invoice day (backdate OK). Validates via resolve_biz_dt. Default = today IST."""
    if bill_date is None:
        return today_ist()
    resolve_biz_dt(bill_date)
    return as_biz_date(bill_date) or today_ist()


def bill_invoice_date(bill) -> date:
    """Invoice date on a stored bill — never invent a customer name / hardcoded day."""
    stored = getattr(bill, "bill_date", None)
    if isinstance(stored, datetime):
        return as_biz_date(stored) or today_ist()
    if stored:
        return stored
    return as_biz_date(getattr(bill, "created_at", None)) or today_ist()
