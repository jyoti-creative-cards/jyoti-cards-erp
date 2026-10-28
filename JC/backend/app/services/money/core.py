"""Canonical money conventions for JC.

SIGNED LEDGER RULE (AR, AP, Freight — one convention):
  `amount` is signed.
  Positive → increases outstanding (customer owes us / we owe vendor or freight agent)
  Negative → decreases outstanding (payment, credit, settlement, item debit note)

  outstanding(party) = Σ amount

Cash metrics always take abs() of payment/settlement rows for cash-in / cash-out.
Never treat cash_pulse.net as books P&L.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session


def _fmt(v: Decimal) -> str:
    return format(v.quantize(Decimal("0.01")), "f")


def mag(amount: Decimal | int | float | str | None) -> Decimal:
    """Absolute magnitude for display / cash totals."""
    return abs(Decimal(str(amount or 0))).quantize(Decimal("0.01"))


def as_signed_increase(amount: Decimal) -> Decimal:
    """Store a positive liability/asset increase."""
    return mag(amount)


def as_signed_decrease(amount: Decimal) -> Decimal:
    """Store a payment/credit/settlement as negative signed amount."""
    return (-mag(amount)).quantize(Decimal("0.01"))


def dues_snapshot(db: Session) -> dict:
    """Single source of truth for Collect / Pay / Freight dues.

    All admin surfaces (Home, Finance pulse, tabs) must use this — never
    re-sum raw ledger types in the UI or ad-hoc overview formulas.
    """
    from app.services.ap_ledger import ap_dues_total
    from app.services.ar_ledger import ar_dues_total
    from app.services.freight_ledger import freight_dues_total

    ar = ar_dues_total(db)
    ap = ap_dues_total(db)
    fr = freight_dues_total(db)
    return {
        "ar": {"total": _fmt(ar["total"]), "count": ar["count"]},
        "ap": {"total": _fmt(ap["total"]), "count": ap["count"]},
        "freight": {"total": _fmt(fr["total"]), "count": fr["count"]},
        "currency": "INR",
        "convention": "signed_ledger_sum",
    }


def assert_dues_consistent(db: Session) -> dict:
    """CI / integrity: overview dues == dues_snapshot == list sums."""
    from app.services.ap_ledger import list_ap_vendors
    from app.services.ar_ledger import list_ar_customers
    from app.services.finance_overview import finance_overview
    from app.services.freight_ledger import list_freight_agents_dues

    snap = dues_snapshot(db)
    ov = finance_overview(db)

    ar_list = sum(
        (Decimal(c["outstanding"]) for c in list_ar_customers(db) if Decimal(c["outstanding"]) > 0),
        Decimal("0"),
    )
    ap_list = sum(
        (Decimal(v["outstanding"]) for v in list_ap_vendors(db) if Decimal(v["outstanding"]) > 0),
        Decimal("0"),
    )
    fr_list = sum(
        (Decimal(a["outstanding"]) for a in list_freight_agents_dues(db) if Decimal(a["outstanding"]) > 0),
        Decimal("0"),
    )

    errors = []
    checks = [
        ("ar_snap_vs_overview", Decimal(snap["ar"]["total"]), Decimal(ov["ar_outstanding"])),
        ("ap_snap_vs_overview", Decimal(snap["ap"]["total"]), Decimal(ov["ap_outstanding"])),
        ("fr_snap_vs_overview", Decimal(snap["freight"]["total"]), Decimal(ov["freight_outstanding"])),
        ("ar_snap_vs_list", Decimal(snap["ar"]["total"]), ar_list),
        ("ap_snap_vs_list", Decimal(snap["ap"]["total"]), ap_list),
        ("fr_snap_vs_list", Decimal(snap["freight"]["total"]), fr_list),
    ]
    for name, a, b in checks:
        if a.quantize(Decimal("0.01")) != b.quantize(Decimal("0.01")):
            errors.append(f"{name}: {a} != {b}")

    return {"ok": not errors, "errors": errors, "snapshot": snap}
