"""Rate history keeps the previous price, and agent bill rows can be listed."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.price_history import PriceHistory
from app.schemas.accounts_receivable import ArLedgerEntryOut
from app.services.history import record_price_change


def test_agent_bill_row_is_a_valid_ledger_entry():
    row = ArLedgerEntryOut(
        id="agent-bill-12",
        entry_type="bill",
        amount="100.00",
        signed_amount="0.00",
        display_amount="100.00",
        running_balance="0.00",
        description="Billed on the agent",
        created_by_name="Admin",
        created_at=datetime(2026, 10, 21, tzinfo=timezone.utc),
    )
    assert row.id == "agent-bill-12"
    assert row.display_amount == "100.00"


def test_first_rate_change_keeps_the_old_rate():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    record_price_change(
        db,
        "catalog_product",
        7,
        Decimal("8.00"),
        Decimal("12.00"),
        effective_from=date(2026, 10, 31),
        previous=(Decimal("6.50"), Decimal("10.00"), date(2026, 9, 1)),
    )
    db.commit()
    rows = db.query(PriceHistory).order_by(PriceHistory.effective_from.asc()).all()
    assert [(r.selling_price, r.effective_from) for r in rows] == [
        (Decimal("10.00"), date(2026, 9, 1)),
        (Decimal("12.00"), date(2026, 10, 31)),
    ]
    db.close()
