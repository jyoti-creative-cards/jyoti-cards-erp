import pandas as pd
import plotly.express as px
import streamlit as st

from services.inventory import get_low_stock
from services.reports import sales_dataframe, purchase_dataframe, inventory_dataframe, vendor_performance_dataframe


def render(db):
    st.header("Dashboard")

    sales_df = sales_dataframe(db)
    purchase_df = purchase_dataframe(db)
    stock_df = inventory_dataframe(db)
    vendor_df = vendor_performance_dataframe(db)
    low_stock = get_low_stock(db)

    total_sales = float(sales_df["amount"].sum()) if not sales_df.empty else 0
    total_purchase = float(purchase_df["amount"].sum()) if not purchase_df.empty else 0
    total_orders = len(sales_df.index)
    total_pos = len(purchase_df.index)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sales", f"₹{total_sales:,.0f}")
    c2.metric("Purchases", f"₹{total_purchase:,.0f}")
    c3.metric("Sales Orders", total_orders)
    c4.metric("Low Stock", len(low_stock))

    st.subheader("Business Trends")
    left, right = st.columns(2)
    with left:
        if not sales_df.empty:
            sales_chart = sales_df.groupby("date", as_index=False)["amount"].sum()
            st.plotly_chart(px.line(sales_chart, x="date", y="amount", title="Sales by Date"), use_container_width=True)
    with right:
        if not purchase_df.empty:
            po_chart = purchase_df.groupby("date", as_index=False)["amount"].sum()
            st.plotly_chart(px.bar(po_chart, x="date", y="amount", title="Purchases by Date"), use_container_width=True)

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
