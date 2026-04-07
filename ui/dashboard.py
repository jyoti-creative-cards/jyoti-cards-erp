import streamlit as st
import pandas as pd
from datetime import date
from db.models import SalesOrder, PurchaseOrder, SalesStatus, OrderStatus, Delivery, DeliveryStatus
from services.inventory import get_low_stock


def render(db):
    st.header("Dashboard")

    today = date.today()

    col1, col2, col3, col4 = st.columns(4)

    today_sales = db.query(SalesOrder).filter(SalesOrder.order_date == today).count()
    today_purchases = db.query(PurchaseOrder).filter(PurchaseOrder.order_date == today).count()
    pending_deliveries = db.query(Delivery).filter(Delivery.status != DeliveryStatus.DELIVERED).count()
    low_stock_items = get_low_stock(db)

    col1.metric("Today Sales Orders", today_sales)
    col2.metric("Today Purchase Orders", today_purchases)
    col3.metric("Pending Deliveries", pending_deliveries)
    col4.metric("Low Stock Items", len(low_stock_items))

    st.divider()

    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Pending Sales Orders")
        pending_so = (
            db.query(SalesOrder)
            .filter(SalesOrder.status.in_([SalesStatus.PENDING, SalesStatus.PACKED]))
            .order_by(SalesOrder.created_at.desc())
            .limit(10)
            .all()
        )
        if pending_so:
            rows = [{"ID": s.id, "Customer": s.customer.name, "Amount": f"₹{s.total_amount:,.0f}", "Status": s.status.value} for s in pending_so]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No pending sales orders")

    with c2:
        st.subheader("Pending Purchase Orders")
        pending_po = (
            db.query(PurchaseOrder)
            .filter(PurchaseOrder.status.in_([OrderStatus.PENDING, OrderStatus.PARTIALLY_RECEIVED]))
            .order_by(PurchaseOrder.created_at.desc())
            .limit(10)
            .all()
        )
        if pending_po:
            rows = [{"ID": p.id, "Vendor": p.vendor.name, "Amount": f"₹{p.total_amount:,.0f}", "Status": p.status.value} for p in pending_po]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No pending purchase orders")

    st.divider()
    st.subheader("Low Stock Alerts")
    if low_stock_items:
        rows = []
        for inv, prod in low_stock_items:
            rows.append({
                "Product": prod.name,
                "SKU": prod.sku,
                "Available": inv.quantity_available,
                "Min Level": prod.min_stock_level,
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.success("All stock levels OK")
