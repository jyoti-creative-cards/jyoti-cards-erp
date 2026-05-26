"""Block GL postings when fiscal year is closed or accounting period is locked."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.fiscal_year import AccountingPeriod, FiscalYear


def assert_period_open_for_posting_date(db: Session, posting_date: date) -> None:
    """
    No-op if no closed FY / locked period covers this date.
    Raises ValueError with a clear message if posting is not allowed.
    """
    fy_closed = (
        db.query(FiscalYear)
        .filter(
            FiscalYear.start_date <= posting_date,
            FiscalYear.end_date >= posting_date,
            FiscalYear.is_closed.is_(True),
        )
        .first()
    )
    if fy_closed is not None:
        raise ValueError(
            f"Cannot post: fiscal year “{fy_closed.name}” is closed for {posting_date.isoformat()}."
        )

    locked = (
        db.query(AccountingPeriod)
        .filter(
            AccountingPeriod.start_date <= posting_date,
            AccountingPeriod.end_date >= posting_date,
            AccountingPeriod.is_locked.is_(True),
        )
        .first()
    )
    if locked is not None:
        raise ValueError(
            f"Cannot post: period “{locked.name}” is locked for {posting_date.isoformat()}."
        )
