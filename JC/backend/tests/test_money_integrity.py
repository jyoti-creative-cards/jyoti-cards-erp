"""Live DB integrity — dues snapshot must match lists and overview."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def db():
    env = Path(__file__).resolve().parents[1] / ".env"
    if not os.getenv("DATABASE_URL") and not env.exists():
        pytest.skip("No DATABASE_URL / .env")
    # Ensure cwd so pydantic Settings finds .env
    os.chdir(Path(__file__).resolve().parents[1])
    from app.db.session import SessionLocal, init_db

    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_dues_snapshot_consistent(db):
    from app.services.money import assert_dues_consistent

    result = assert_dues_consistent(db)
    assert result["ok"], result["errors"]


def test_ar_signed_payments_non_positive(db):
    from app.models.accounts_receivable import ArLedgerEntry

    bad = (
        db.query(ArLedgerEntry)
        .filter(
            ArLedgerEntry.entry_type.in_(("payment", "credit_note")),
            ArLedgerEntry.amount > 0,
        )
        .count()
    )
    assert bad == 0, f"{bad} AR payment/credit rows still positive (unsigned legacy)"


def test_freight_settlements_non_positive(db):
    from app.models.freight_agent import FreightLedgerEntry

    bad = (
        db.query(FreightLedgerEntry)
        .filter(
            FreightLedgerEntry.entry_type == "settlement",
            FreightLedgerEntry.amount > 0,
        )
        .count()
    )
    assert bad == 0, f"{bad} freight settlements still positive"


def test_ap_payments_non_positive(db):
    from app.models.accounts_payable import ApLedgerEntry

    bad = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.entry_type == "payment", ApLedgerEntry.amount > 0)
        .count()
    )
    assert bad == 0, f"{bad} AP payment rows still positive"


def test_freight_balance_matches_ledger(db):
    from decimal import Decimal

    from app.models.freight_agent import FreightAgent
    from app.services.freight_ledger import agent_freight_totals

    for a in db.query(FreightAgent).all():
        t = agent_freight_totals(db, a.id)
        cached = (a.balance_due or Decimal("0")).quantize(Decimal("0.01"))
        assert cached == t["outstanding"], (
            f"agent {a.id} balance_due {a.balance_due} != ledger {t['outstanding']}"
        )
