"""Analytics / reports endpoint.

POST /reports/query
Body:
  {
    "report_type": "customer_sales" | "vendor_purchases" | "item_sales" | "item_purchases"
                 | "ar_summary" | "ap_summary" | "overall_sales",
    "customer_id": int | null,
    "vendor_id":   int | null,
    "catalog_product_id": int | null,
    "date_from":  "YYYY-MM-DD" | null,
    "date_to":    "YYYY-MM-DD" | null,
  }
Returns: { summary: {...}, rows: [...] }
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models.ar_invoice import ARInvoice
from app.models.ap_bill import APBill
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.customer_order import CustomerOrder
from app.models.vendor import Vendor
from app.models.stock_receipt import StockReceipt
from app.services.accounting import amount_paid_on_ar, amount_paid_on_ap

router = APIRouter(prefix="/reports", tags=["reports"])

IST = timedelta(hours=5, minutes=30)


def _to_dt(d: Optional[str], end: bool = False) -> Optional[datetime]:
    if not d:
        return None
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
        if end:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt.replace(tzinfo=timezone.utc) - IST  # convert IST → UTC for DB query
    except ValueError:
        return None


def _d(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


class ReportQuery(BaseModel):
    report_type: str
    customer_id: Optional[int] = None
    vendor_id: Optional[int] = None
    catalog_product_id: Optional[int] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


@router.post("/query", dependencies=[Depends(require_admin)])
def run_report(body: ReportQuery, db: Session = Depends(get_db)) -> dict:
    dt_from = _to_dt(body.date_from)
    dt_to = _to_dt(body.date_to, end=True)
    rtype = body.report_type.strip().lower()

    # ── Customer Sales ────────────────────────────────────────────────
    if rtype == "customer_sales":
        q = (
            db.query(CustomerBill)
            .join(CustomerOrder, CustomerOrder.id == CustomerBill.customer_order_id)
            .filter(CustomerBill.bill_status == "active")
        )
        if body.customer_id:
            q = q.filter(CustomerOrder.customer_id == body.customer_id)
        if dt_from:
            q = q.filter(CustomerBill.created_at >= dt_from)
        if dt_to:
            q = q.filter(CustomerBill.created_at <= dt_to)
        bills = q.order_by(CustomerBill.created_at.desc()).all()

        rows = []
        total = 0.0
        for b in bills:
            tot_dict = b.totals if isinstance(b.totals, dict) else {}
            grand = _d(tot_dict.get("grand_total") or tot_dict.get("subtotal"))
            total += grand
            cust = db.get(Customer, db.get(CustomerOrder, b.customer_order_id).customer_id if b.customer_order_id else 0)
            rows.append({
                "bill_id": b.id,
                "bill_no": b.bill_no or f"#{b.id}",
                "customer": cust.name if cust else "—",
                "company": cust.company_name if cust else None,
                "date": b.created_at.strftime("%d %b %Y") if b.created_at else "—",
                "amount": round(grand, 2),
                "order_id": b.customer_order_id,
            })
        return {"summary": {"total_bills": len(rows), "total_amount": round(total, 2)}, "rows": rows}

    # ── Item Sales ────────────────────────────────────────────────────
    if rtype == "item_sales":
        if not body.catalog_product_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="catalog_product_id required for item_sales")
        q = (
            db.query(CustomerBill)
            .join(CustomerOrder, CustomerOrder.id == CustomerBill.customer_order_id)
            .filter(CustomerBill.bill_status == "active")
        )
        if dt_from:
            q = q.filter(CustomerBill.created_at >= dt_from)
        if dt_to:
            q = q.filter(CustomerBill.created_at <= dt_to)
        if body.customer_id:
            q = q.filter(CustomerOrder.customer_id == body.customer_id)
        bills = q.order_by(CustomerBill.created_at.desc()).all()

        rows = []
        total_qty = 0
        total_amount = 0.0
        pid = body.catalog_product_id
        for b in bills:
            order = db.get(CustomerOrder, b.customer_order_id)
            items = order.items if order and isinstance(order.items, list) else []
            for it in items:
                if int(it.get("catalog_product_id", 0)) == pid:
                    qty = int(it.get("qty_billed") or it.get("quantity") or 0)
                    amt = float(it.get("unit_price", 0)) * qty
                    if qty == 0:
                        continue
                    total_qty += qty
                    total_amount += amt
                    cust = db.get(Customer, order.customer_id) if order else None
                    rows.append({
                        "bill_id": b.id,
                        "bill_no": b.bill_no or f"#{b.id}",
                        "customer": cust.name if cust else "—",
                        "date": b.created_at.strftime("%d %b %Y") if b.created_at else "—",
                        "quantity": qty,
                        "unit_price": float(it.get("unit_price", 0)),
                        "amount": round(amt, 2),
                    })
        return {"summary": {"total_bills": len(rows), "total_qty": total_qty, "total_amount": round(total_amount, 2)}, "rows": rows}

    # ── Item Purchases ────────────────────────────────────────────────
    if rtype == "item_purchases":
        if not body.catalog_product_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="catalog_product_id required")
        q = db.query(StockReceipt)
        if body.vendor_id:
            q = q.filter(StockReceipt.vendor_id == body.vendor_id)
        if dt_from:
            q = q.filter(StockReceipt.created_at >= dt_from)
        if dt_to:
            q = q.filter(StockReceipt.created_at <= dt_to)
        receipts = q.order_by(StockReceipt.created_at.desc()).all()

        pid = body.catalog_product_id
        rows = []
        total_qty = 0
        total_amount = 0.0
        for r in receipts:
            line_items = r.line_items if isinstance(r.line_items, list) else []
            for li in line_items:
                if int(li.get("catalog_product_id", 0)) == pid:
                    qty = int(li.get("quantity", 0))
                    price = _d(li.get("unit_price") or li.get("price") or 0)
                    amt = qty * price
                    total_qty += qty
                    total_amount += amt
                    vendor = db.get(Vendor, r.vendor_id) if r.vendor_id else None
                    rows.append({
                        "receipt_id": r.id,
                        "vendor": vendor.name if vendor else "—",
                        "date": r.created_at.strftime("%d %b %Y") if r.created_at else "—",
                        "quantity": qty,
                        "unit_price": price,
                        "amount": round(amt, 2),
                    })
        return {"summary": {"total_receipts": len(rows), "total_qty": total_qty, "total_amount": round(total_amount, 2)}, "rows": rows}

    # ── AR Summary ────────────────────────────────────────────────────
    if rtype == "ar_summary":
        q = db.query(ARInvoice)
        if body.customer_id:
            q = q.filter(ARInvoice.customer_id == body.customer_id)
        if dt_from:
            q = q.filter(ARInvoice.created_at >= dt_from)
        if dt_to:
            q = q.filter(ARInvoice.created_at <= dt_to)
        invoices = q.order_by(ARInvoice.created_at.desc()).all()

        rows = []
        total_billed = 0.0
        total_paid = 0.0
        total_outstanding = 0.0
        for inv in invoices:
            cust = db.get(Customer, inv.customer_id)
            paid = float(amount_paid_on_ar(db, inv))
            bal = _d(inv.amount) - paid
            total_billed += _d(inv.amount)
            total_paid += paid
            total_outstanding += max(0.0, bal)
            rows.append({
                "invoice_id": inv.id,
                "customer": cust.name if cust else "—",
                "company": cust.company_name if cust else None,
                "date": inv.created_at.strftime("%d %b %Y") if inv.created_at else "—",
                "amount": round(_d(inv.amount), 2),
                "paid": round(paid, 2),
                "outstanding": round(max(0.0, bal), 2),
                "status": inv.status,
            })
        return {
            "summary": {
                "total_invoices": len(rows),
                "total_billed": round(total_billed, 2),
                "total_paid": round(total_paid, 2),
                "total_outstanding": round(total_outstanding, 2),
            },
            "rows": rows,
        }

    # ── AP Summary ────────────────────────────────────────────────────
    if rtype == "ap_summary":
        q = db.query(APBill)
        if body.vendor_id:
            q = q.filter(APBill.vendor_id == body.vendor_id)
        if dt_from:
            q = q.filter(APBill.created_at >= dt_from)
        if dt_to:
            q = q.filter(APBill.created_at <= dt_to)
        bills = q.order_by(APBill.created_at.desc()).all()

        rows = []
        total_billed = 0.0
        total_paid = 0.0
        total_outstanding = 0.0
        for b in bills:
            vendor = db.get(Vendor, b.vendor_id) if hasattr(b, "vendor_id") else None
            paid = float(amount_paid_on_ap(db, b))
            bal = _d(b.amount) - paid
            total_billed += _d(b.amount)
            total_paid += paid
            total_outstanding += max(0.0, bal)
            rows.append({
                "bill_id": b.id,
                "vendor": vendor.name if vendor else "—",
                "date": b.created_at.strftime("%d %b %Y") if b.created_at else "—",
                "amount": round(_d(b.amount), 2),
                "paid": round(paid, 2),
                "outstanding": round(max(0.0, bal), 2),
                "status": b.status,
            })
        return {
            "summary": {
                "total_bills": len(rows),
                "total_billed": round(total_billed, 2),
                "total_paid": round(total_paid, 2),
                "total_outstanding": round(total_outstanding, 2),
            },
            "rows": rows,
        }

    # ── Overall Sales ─────────────────────────────────────────────────
    if rtype == "overall_sales":
        q = db.query(CustomerBill).filter(CustomerBill.bill_status == "active")
        if dt_from:
            q = q.filter(CustomerBill.created_at >= dt_from)
        if dt_to:
            q = q.filter(CustomerBill.created_at <= dt_to)
        bills = q.order_by(CustomerBill.created_at.desc()).all()

        total = 0.0
        rows = []
        by_customer: dict[str, float] = {}
        for b in bills:
            tot_dict = b.totals if isinstance(b.totals, dict) else {}
            grand = _d(tot_dict.get("grand_total") or tot_dict.get("subtotal"))
            total += grand
            order = db.get(CustomerOrder, b.customer_order_id) if b.customer_order_id else None
            cust = db.get(Customer, order.customer_id) if order else None
            cname = (cust.company_name or cust.name) if cust else "—"
            by_customer[cname] = by_customer.get(cname, 0) + grand
            rows.append({
                "bill_id": b.id,
                "bill_no": b.bill_no or f"#{b.id}",
                "customer": cname,
                "date": b.created_at.strftime("%d %b %Y") if b.created_at else "—",
                "amount": round(grand, 2),
            })
        top_customers = sorted(by_customer.items(), key=lambda x: x[1], reverse=True)[:10]
        return {
            "summary": {
                "total_bills": len(rows),
                "total_amount": round(total, 2),
                "top_customers": [{"name": k, "amount": round(v, 2)} for k, v in top_customers],
            },
            "rows": rows,
        }

    raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Unknown report_type: {rtype}")
