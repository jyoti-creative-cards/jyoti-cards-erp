"""Home dashboard aggregates — needs action, today pulse, recent activity."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.freight_agent import FreightAgent
from app.services.money import mag


def _fmt(v: Decimal | int | float | None) -> str:
    if v is None:
        return "0.00"
    return format(Decimal(str(v)).quantize(Decimal("0.01")), "f")


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=timezone.utc)
    end = datetime.combine(d, time.max, tzinfo=timezone.utc)
    return start, end


def build_dashboard(db: Session) -> dict:
    """Few round-trips — prod API is US-West; each query costs ~RTT from India."""
    today = date.today()
    start, end = _day_bounds(today)
    week_start, _ = _day_bounds(date.fromordinal(today.toordinal() - 6))

    # —— 1) Counts + today pulse in one SQL ——
    row = db.execute(
        text(
            """
            SELECT
              (SELECT COUNT(DISTINCT customer_id) FROM jc_customer_open_lines
                 WHERE status = 'open' AND quantity_open > 0) AS co_open,
              (SELECT COUNT(*) FROM jc_vendor_orders
                 WHERE is_open IS TRUE AND bucket IN ('placed','received')) AS vo_open,
              (SELECT COUNT(*) FROM jc_customer_returns
                 WHERE created_at >= :week_start) AS returns_recent,
              (SELECT COUNT(*) FROM jc_customer_returns
                 WHERE created_at >= :day_start AND created_at <= :day_end) AS returns_today,
              (SELECT COUNT(*) FROM jc_catalog_products p
                 LEFT JOIN jc_stock_balances b ON b.catalog_product_id = p.id
                 WHERE p.is_active IS TRUE AND p.deleted_at IS NULL
                   AND COALESCE(b.quantity_on_hand, 0) <= 10) AS low_stock,
              (SELECT COALESCE(SUM(grand_total), 0) FROM jc_customer_bills
                 WHERE created_at >= :day_start AND created_at <= :day_end) AS sales_total,
              (SELECT COUNT(*) FROM jc_customer_bills
                 WHERE created_at >= :day_start AND created_at <= :day_end) AS sales_count,
              (SELECT COUNT(*) FROM jc_ap_ledger_entries
                 WHERE entry_type = 'bill' AND deleted_at IS NULL
                   AND created_at >= :day_start AND created_at <= :day_end) AS purchase_count,
              (SELECT COALESCE(SUM(amount), 0) FROM jc_ar_ledger_entries
                 WHERE entry_type = 'payment'
                   AND created_at >= :day_start AND created_at <= :day_end) AS cash_in_raw,
              (SELECT COALESCE(SUM(amount), 0) FROM jc_ap_ledger_entries
                 WHERE entry_type = 'payment' AND deleted_at IS NULL
                   AND created_at >= :day_start AND created_at <= :day_end) AS cash_out_raw
            """
        ),
        {"day_start": start, "day_end": end, "week_start": week_start},
    ).one()

    customer_orders = int(row.co_open or 0)
    vendor_orders = int(row.vo_open or 0)
    returns_recent = int(row.returns_recent or 0)
    returns_today = int(row.returns_today or 0)
    low_count = int(row.low_stock or 0)
    sales_total = Decimal(str(row.sales_total or 0))
    sales_count = int(row.sales_count or 0)
    purchase_count = int(row.purchase_count or 0)
    cash_in = mag(row.cash_in_raw)
    cash_out = mag(row.cash_out_raw)

    # —— 2) AR dues (one join query) ——
    ar_rows = db.execute(
        text(
            """
            SELECT c.id, c.business_name, ci.name AS city_name, SUM(e.amount) AS outstanding
            FROM jc_ar_ledger_entries e
            JOIN jc_customers c ON c.id = e.customer_id AND c.deleted_at IS NULL
            LEFT JOIN jc_cities ci ON ci.id = c.city_id
            GROUP BY c.id, c.business_name, ci.name
            HAVING SUM(e.amount) > 0
            ORDER BY SUM(e.amount) DESC
            """
        )
    ).all()
    ar_due_parties = [
        {
            "customer_id": int(r.id),
            "customer_label": f"{r.business_name} — {r.city_name}" if r.city_name else r.business_name,
            "outstanding": _fmt(r.outstanding),
        }
        for r in ar_rows
    ]
    ar_outstanding = sum((Decimal(str(r.outstanding or 0)) for r in ar_rows), Decimal("0")).quantize(Decimal("0.01"))

    # —— 3) AP dues (one join query) ——
    ap_rows = db.execute(
        text(
            """
            SELECT v.id, v.business_name, ci.name AS city_name, SUM(e.amount) AS outstanding
            FROM jc_ap_ledger_entries e
            JOIN jc_vendors v ON v.id = e.vendor_id AND v.deleted_at IS NULL
            LEFT JOIN jc_cities ci ON ci.id = v.city_id
            WHERE e.deleted_at IS NULL
            GROUP BY v.id, v.business_name, ci.name
            HAVING SUM(e.amount) > 0
            ORDER BY SUM(e.amount) DESC
            """
        )
    ).all()
    ap_due_parties = [
        {
            "vendor_id": int(r.id),
            "vendor_label": f"{r.business_name} — {r.city_name}" if r.city_name else r.business_name,
            "outstanding": _fmt(r.outstanding),
        }
        for r in ap_rows
    ]
    ap_outstanding = sum((Decimal(str(r.outstanding or 0)) for r in ap_rows), Decimal("0")).quantize(Decimal("0.01"))

    # —— 4) Freight from cached balance_due ——
    freight_agents = (
        db.query(FreightAgent)
        .filter(FreightAgent.balance_due > 0)
        .order_by(FreightAgent.balance_due.desc())
        .all()
    )
    freight_due = [
        {
            "id": a.id,
            "name": a.name,
            "outstanding": _fmt(a.balance_due or 0),
            "balance_due": _fmt(a.balance_due or 0),
        }
        for a in freight_agents
    ]
    freight_outstanding = sum(
        (Decimal(str(a.balance_due or 0)) for a in freight_agents), Decimal("0")
    ).quantize(Decimal("0.01"))

    # —— 5) Recent activity ——
    activity_rows = (
        db.query(ActivityLog)
        .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
        .limit(12)
        .all()
    )
    activity = [
        {
            "id": e.id,
            "actor_name": e.actor_name,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "entity_label": e.entity_label,
            "detail": e.detail,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in activity_rows
    ]

    actions = [
        {
            "id": "customer_orders",
            "label": "Process customer orders",
            "count": customer_orders,
            "amount": None,
            "tone": "ok",
            "cta": "Open orders",
            "goto": "orders_customer",
        },
        {
            "id": "vendor_orders",
            "label": "Receive / bill vendors",
            "count": vendor_orders,
            "amount": None,
            "tone": "warn",
            "cta": "Open orders",
            "goto": "orders_vendor",
        },
        {
            "id": "collect",
            "label": "Collect from customers",
            "count": len(ar_due_parties),
            "amount": _fmt(ar_outstanding),
            "tone": "ok",
            "cta": "Collect",
            "goto": "finance_ar",
        },
        {
            "id": "pay_vendors",
            "label": "Pay vendors",
            "count": len(ap_due_parties),
            "amount": _fmt(ap_outstanding),
            "tone": "warn",
            "cta": "Pay",
            "goto": "finance_ap",
        },
        {
            "id": "freight",
            "label": "Freight due",
            "count": len(freight_due),
            "amount": _fmt(freight_outstanding),
            "tone": "danger",
            "cta": "Settle",
            "goto": "finance_freight",
        },
        {
            "id": "low_stock",
            "label": "Low stock",
            "count": low_count,
            "amount": None,
            "tone": "warn",
            "cta": "View",
            "goto": "reports_low_stock",
        },
        {
            "id": "returns",
            "label": "Returns (7 days)",
            "count": returns_recent,
            "amount": None,
            "tone": "muted",
            "cta": "Open returns",
            "goto": "returns",
        },
    ]

    pulse = {
        "date": today.isoformat(),
        "sales_billed": _fmt(sales_total),
        "sales_count": sales_count,
        "purchase_count": purchase_count,
        "cash_in": _fmt(cash_in),
        "cash_out": _fmt(cash_out),
        "customer_orders_open": customer_orders,
        "vendor_orders_open": vendor_orders,
        "returns_today": returns_today,
        "note": "Today cash movement — not books P&L",
    }

    return {
        "actions": actions,
        "action_total": sum(1 for a in actions if a["count"] > 0),
        "pulse": pulse,
        "activity": activity,
        "top_collect": [
            {"id": c["customer_id"], "label": c["customer_label"], "outstanding": c["outstanding"]}
            for c in ar_due_parties[:5]
        ],
        "top_pay": [
            {"id": v["vendor_id"], "label": v["vendor_label"], "outstanding": v["outstanding"]}
            for v in ap_due_parties[:5]
        ],
    }
