import pandas as pd
import plotly.express as px
import streamlit as st

from services.notifications import send_daily_summary
from services.reports import sales_dataframe, purchase_dataframe, inventory_dataframe, vendor_performance_dataframe


def render(db):
    st.header("Reports")
    if st.button("Send Daily Summary To Internal WhatsApp"):
        send_daily_summary(db)
        st.success("Summary sent")

    sales_df = sales_dataframe(db)
    purchase_df = purchase_dataframe(db)
    stock_df = inventory_dataframe(db)
    vendor_df = vendor_performance_dataframe(db)

    period = st.selectbox("Period", ["daily", "weekly", "monthly", "quarterly"])
    st.caption(f"Report mode: {period}")

    if not sales_df.empty:
        st.subheader("Sales")
        sales_df["date"] = pd.to_datetime(sales_df["date"])
        st.plotly_chart(px.line(sales_df.groupby("date", as_index=False)["amount"].sum(), x="date", y="amount", title="Sales Trend"), use_container_width=True)
        st.dataframe(sales_df, use_container_width=True, hide_index=True)

    if not purchase_df.empty:
        st.subheader("Purchases")
        st.plotly_chart(px.bar(purchase_df.groupby("date", as_index=False)["amount"].sum(), x="date", y="amount", title="Purchase Trend"), use_container_width=True)
        st.dataframe(purchase_df, use_container_width=True, hide_index=True)

    if not stock_df.empty:
        st.subheader("Inventory Health")
        st.plotly_chart(px.bar(stock_df, x="product", y=["left_percent", "sold_percent"], barmode="group", title="Stock Left vs Sold %"), use_container_width=True)
        st.dataframe(stock_df, use_container_width=True, hide_index=True)

    if not vendor_df.empty:
        st.subheader("Vendor Performance")
        st.dataframe(vendor_df, use_container_width=True, hide_index=True)
