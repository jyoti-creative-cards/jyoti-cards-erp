from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin
from app.services import reports as svc
from app.services import reports_extended as ext
from app.services.ar_ledger import build_ar_ledger, customer_ar_totals, _customer_label
from app.services.ap_ledger import build_ap_ledger, vendor_ap_totals, _vendor_label

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/sales")
def sales_report(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return {"items": svc.list_sales(db, from_date, to_date)}


@router.get("/purchases")
def purchases_report(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return {"items": svc.list_purchases(db, from_date, to_date)}


@router.get("/payments")
def payments_report(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return {"items": svc.list_payments(db, from_date, to_date)}


@router.get("/daybook")
def daybook_report(
    day: date = Query(..., description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return svc.daybook(db, day)


@router.get("/item-sales")
def item_sales(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return {"items": ext.item_wise_sales(db, from_date, to_date)}


@router.get("/item-purchases")
def item_purchases(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return {"items": ext.item_wise_purchases(db, from_date, to_date)}


@router.get("/customer-sales")
def customer_sales(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return {"items": ext.customer_wise_sales(db, from_date, to_date)}


@router.get("/vendor-purchases")
def vendor_purchases(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return {"items": ext.vendor_wise_purchases(db, from_date, to_date)}


@router.get("/ageing/ar")
def ageing_ar(
    as_of: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    from app.services import response_cache
    key = f"ageing_ar:{as_of or 'today'}"
    hit = response_cache.get(key)
    if hit is not None:
        return hit
    data = ext.ageing_ar(db, as_of)
    response_cache.set(key, data, ttl_seconds=30.0)
    return data


@router.get("/ageing/ap")
def ageing_ap(
    as_of: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    from app.services import response_cache
    key = f"ageing_ap:{as_of or 'today'}"
    hit = response_cache.get(key)
    if hit is not None:
        return hit
    data = ext.ageing_ap(db, as_of)
    response_cache.set(key, data, ttl_seconds=30.0)
    return data


@router.get("/stock/valuation")
def stock_valuation(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    return ext.stock_valuation(db)


@router.get("/stock/movers")
def stock_movers(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return ext.stock_movers(db, from_date, to_date)


@router.get("/stock/low")
def stock_low(
    threshold: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return {"items": ext.low_stock(db, threshold)}


@router.get("/returns-register")
def returns_register(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return {"items": ext.returns_register(db, from_date, to_date)}


@router.get("/debit-notes-register")
def debit_notes_register(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return {"items": ext.debit_note_register(db, from_date, to_date)}


@router.get("/gst/sales")
def gst_sales(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return {"items": ext.gst_sales_register(db, from_date, to_date)}


@router.get("/gst/purchases")
def gst_purchases(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return {"items": ext.gst_purchase_register(db, from_date, to_date)}


@router.get("/cashbook")
def cashbook_report(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return ext.cashbook(db, from_date, to_date)


@router.get("/expense-by-category")
def expense_by_category(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return {"items": ext.expense_by_category(db, from_date, to_date)}


@router.get("/pnl")
def pnl_report(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return ext.pnl_detail(db, from_date, to_date)


@router.get("/ledgers/customers")
def ledger_customers(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    from app.services import response_cache
    hit = response_cache.get("ledger_customers")
    if hit is not None:
        return hit
    data = {"items": svc.list_ledger_customers(db)}
    response_cache.set("ledger_customers", data, ttl_seconds=20.0)
    return data


@router.get("/ledgers/vendors")
def ledger_vendors(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    from app.services import response_cache
    hit = response_cache.get("ledger_vendors")
    if hit is not None:
        return hit
    data = {"items": svc.list_ledger_vendors(db)}
    response_cache.set("ledger_vendors", data, ttl_seconds=20.0)
    return data


@router.get("/ledgers/products")
def ledger_products(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    return {"items": svc.list_ledger_products(db)}


@router.get("/ledgers/staff")
def ledger_staff(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    return {"items": ext.list_ledger_staff(db)}


@router.get("/ledgers/freight")
def ledger_freight(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    return {"items": ext.list_ledger_freight(db)}


@router.get("/ledgers/expenses")
def ledger_expenses(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    return {"items": ext.list_ledger_expenses(db)}


@router.get("/ledgers/routes")
def ledger_routes(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    return {"items": ext.list_ledger_routes(db)}


@router.get("/ledgers/cash")
def ledger_cash_list(db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    return {"items": [{"id": 0, "label": "Cash", "outstanding": "—"}]}


@router.get("/ledgers/customers/{customer_id}")
def ledger_customer_detail(customer_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    from app.models.customer import Customer

    c = db.get(Customer, customer_id)
    if not c or c.deleted_at:
        raise HTTPException(404, "customer not found")
    totals = customer_ar_totals(db, customer_id)
    return {
        "party_type": "customer",
        "party_id": customer_id,
        "party_label": _customer_label(db, customer_id),
        "outstanding": format(totals["outstanding"], "f"),
        "opening_total": format(totals["opening_total"], "f"),
        "bill_total": format(totals["bill_total"], "f"),
        "payment_total": format(totals["payment_total"], "f"),
        "credit_total": format(totals["credit_total"], "f"),
        "entries": build_ar_ledger(db, customer_id),
    }


@router.get("/ledgers/vendors/{vendor_id}")
def ledger_vendor_detail(vendor_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    from app.models.vendor import Vendor

    v = db.get(Vendor, vendor_id)
    if not v or v.deleted_at:
        raise HTTPException(404, "vendor not found")
    totals = vendor_ap_totals(db, vendor_id)
    return {
        "party_type": "vendor",
        "party_id": vendor_id,
        "party_label": _vendor_label(db, vendor_id),
        "outstanding": format(totals["outstanding"], "f"),
        "opening_total": format(totals["opening_total"], "f"),
        "bill_total": format(totals["bill_total"], "f"),
        "payment_total": format(totals["payment_total"], "f"),
        "debit_note_total": format(totals["debit_note_total"], "f"),
        "entries": build_ap_ledger(db, vendor_id),
    }


@router.get("/ledgers/products/{catalog_product_id}")
def ledger_product_detail(
    catalog_product_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    data = svc.product_stock_ledger(db, catalog_product_id)
    if not data:
        raise HTTPException(404, "product not found")
    return {"party_type": "product", **data}


@router.get("/ledgers/staff/{staff_id}")
def ledger_staff_detail(
    staff_id: int,
    actor_name: Optional[str] = Query(None),
    actor_type: str = Query("staff"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    if actor_type == "admin":
        data = ext.staff_activity_ledger(db, staff_id=None, actor_name=actor_name or "admin", actor_type="admin")
    else:
        data = ext.staff_activity_ledger(db, staff_id=staff_id)
    if not data:
        raise HTTPException(404, "staff not found")
    return data


@router.get("/ledgers/freight/{agent_id}")
def ledger_freight_detail(agent_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    data = ext.freight_ledger_detail(db, agent_id)
    if not data:
        raise HTTPException(404, "freight agent not found")
    return data


@router.get("/ledgers/expenses/{category}")
def ledger_expense_detail(
    category: str,
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return ext.expense_ledger_detail(db, category, from_date, to_date)


@router.get("/ledgers/routes/{route_id}")
def ledger_route_detail(route_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(require_admin)):
    data = ext.route_ledger_detail(db, route_id)
    if not data:
        raise HTTPException(404, "route not found")
    return data


@router.get("/ledgers/cash/book")
def ledger_cash_detail(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return ext.cash_ledger_detail(db, from_date, to_date)
