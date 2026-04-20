from datetime import date
from calendar import monthrange

import pandas as pd
import plotly.express as px
import streamlit as st

from db.models import SalesOrder, PurchaseOrder, PurchaseOrderStatus, SalesStatus
from services.inventory import get_low_stock
from services.reports import sales_dataframe, purchase_dataframe, inventory_dataframe, vendor_performance_dataframe


def render(db):
    st.header("Dashboard")

    today = date.today()
    month_start = today.replace(day=1)
    month_end = today.replace(day=monthrange(today.year, today.month)[1])

    todays_orders = (
        db.query(SalesOrder)
        .filter(SalesOrder.order_date == today)
        .count()
    )

    pending_po_statuses = [
        PurchaseOrderStatus.CREATED,
        PurchaseOrderStatus.PENDING,
        PurchaseOrderStatus.APPROVED,
        PurchaseOrderStatus.LOADED,
        PurchaseOrderStatus.IN_TRANSIT,
        PurchaseOrderStatus.PARTIALLY_RECEIVED,
    ]
    pending_pos = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.status.in_([s.value for s in pending_po_statuses]))
        .count()
    )

    low_stock = get_low_stock(db)

    month_sales = (
        db.query(SalesOrder)
        .filter(SalesOrder.order_date >= month_start, SalesOrder.order_date <= month_end)
        .filter(SalesOrder.status != SalesStatus.CANCELLED.value)
        .all()
    )
    month_revenue = sum((so.total_amount or 0) for so in month_sales)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Today's Orders", todays_orders)
    c2.metric("Pending POs", pending_pos)
    c3.metric("Low Stock Alerts", len(low_stock))
    c4.metric("Revenue (This Month)", f"₹{month_revenue:,.0f}")

    st.divider()

    sales_df = sales_dataframe(db)
    purchase_df = purchase_dataframe(db)
    stock_df = inventory_dataframe(db)
    vendor_df = vendor_performance_dataframe(db)

    st.subheader("Business Trends")
    left, right = st.columns(2)
    with left:
        if not sales_df.empty:
            sales_chart = sales_df.groupby("date", as_index=False)["amount"].sum()
            st.plotly_chart(px.line(sales_chart, x="date", y="amount", title="Sales by Date"), use_container_width=True)
        else:
            st.info("No sales data yet")
    with right:
        if not purchase_df.empty:
            po_chart = purchase_df.groupby("date", as_index=False)["amount"].sum()
            st.plotly_chart(px.bar(po_chart, x="date", y="amount", title="Purchases by Date"), use_container_width=True)
        else:
            st.info("No purchase data yet")

    left, right = st.columns(2)
    with left:
        st.subheader("Inventory Left %")
        if not stock_df.empty:
            st.plotly_chart(px.bar(stock_df, x="product", y="left_percent", title="Product Left %"), use_container_width=True)
        else:
            st.info("No inventory data")
    with right:
        st.subheader("Order Channel Mix")
        if not sales_df.empty:
            channel_df = sales_df.groupby("channel", as_index=False).size()
            st.plotly_chart(px.pie(channel_df, names="channel", values="size", title="Manual vs WhatsApp"), use_container_width=True)
        else:
            st.info("No sales data")

    st.subheader("Vendor Performance")
    if not vendor_df.empty:
        st.dataframe(vendor_df, use_container_width=True, hide_index=True)
    else:
        st.info("No vendor performance data")

    st.subheader("Low Stock")
    if low_stock:
        rows = [{"Product": prod.name, "SKU": prod.sku, "Available": inv.quantity_available, "Min": prod.min_stock_level} for inv, prod in low_stock]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.success("No low stock items")
