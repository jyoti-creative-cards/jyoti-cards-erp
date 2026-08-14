"""Ops reconcile jobs — stock balances, freight cache, money dues."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.freight_agent import FreightAgent, FreightLedgerEntry
from app.models.stock import StockBalance, StockLedger
from app.services.freight_ledger import reconcile_all_freight_balances
from app.services.money import assert_dues_consistent


def stock_balance_mismatches(db: Session, *, limit: int = 200) -> list[dict]:
    """Balance.on_hand must equal Σ ledger quantity_delta."""
    ledger_sum = (
        db.query(
            StockLedger.catalog_product_id,
            func.coalesce(func.sum(StockLedger.quantity_delta), 0).label("qty"),
        )
        .group_by(StockLedger.catalog_product_id)
        .subquery()
    )
    rows = (
        db.query(
            StockBalance.catalog_product_id,
            StockBalance.quantity_on_hand,
            func.coalesce(ledger_sum.c.qty, 0),
        )
        .outerjoin(ledger_sum, ledger_sum.c.catalog_product_id == StockBalance.catalog_product_id)
        .all()
    )
    bad = []
    for pid, on_hand, led in rows:
        oh = int(on_hand or 0)
        ls = int(led or 0)
        if oh != ls:
            bad.append(
                {
                    "catalog_product_id": int(pid),
                    "quantity_on_hand": oh,
                    "ledger_sum": ls,
                    "delta": oh - ls,
                }
            )
            if len(bad) >= limit:
                break
    return bad


def freight_balance_mismatches(db: Session, *, limit: int = 200) -> list[dict]:
    bad = []
    for agent in db.query(FreightAgent).all():
        led = (
            db.query(func.coalesce(func.sum(FreightLedgerEntry.amount), 0))
            .filter(FreightLedgerEntry.freight_agent_id == agent.id)
            .scalar()
        )
        led = Decimal(str(led or 0)).quantize(Decimal("0.01"))
        cached = Decimal(str(agent.balance_due or 0)).quantize(Decimal("0.01"))
        if cached != led:
            bad.append(
                {
                    "freight_agent_id": agent.id,
                    "name": agent.name,
                    "balance_due": format(cached, "f"),
                    "ledger_sum": format(led, "f"),
                }
            )
            if len(bad) >= limit:
                break
    return bad


def run_reconcile(db: Session, *, repair_freight: bool = False) -> dict:
    money = assert_dues_consistent(db)
    stock_bad = stock_balance_mismatches(db)
    freight_bad = freight_balance_mismatches(db)
    repaired = 0
    if repair_freight and freight_bad:
        repaired = reconcile_all_freight_balances(db)
        freight_bad = freight_balance_mismatches(db)
    ok = bool(money.get("ok")) and not stock_bad and not freight_bad
    return {
        "ok": ok,
        "money": money,
        "stock_mismatches": stock_bad,
        "stock_mismatch_count": len(stock_bad),
        "freight_mismatches": freight_bad,
        "freight_mismatch_count": len(freight_bad),
        "freight_repaired": repaired,
    }
