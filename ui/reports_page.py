from datetime import date, timedelta

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

    st.subheader("Sales Summary")
    if not sales_df.empty:
        sales_df["date"] = pd.to_datetime(sales_df["date"]).dt.date
        min_d, max_d = sales_df["date"].min(), sales_df["date"].max()
        col_a, col_b = st.columns(2)
        start = col_a.date_input("From", min_d, key="rep_sales_from")
        end = col_b.date_input("To", max_d, key="rep_sales_to")
        filtered = sales_df[(sales_df["date"] >= start) & (sales_df["date"] <= end)]
        total_sales = float(filtered["amount"].sum()) if not filtered.empty else 0
        st.metric(f"Sales between {start} and {end}", f"₹{total_sales:,.0f}")

        if not filtered.empty:
            trend = filtered.groupby("date", as_index=False)["amount"].sum()
            st.plotly_chart(px.line(trend, x="date", y="amount", title="Sales Trend"), use_container_width=True)
            st.dataframe(filtered, use_container_width=True, hide_index=True)
            st.download_button(
                "Download Sales CSV",
                filtered.to_csv(index=False).encode("utf-8"),
                f"sales_{start}_{end}.csv",
                "text/csv",
                key="dl_sales",
            )
    else:
        st.info("No sales data")

    st.subheader("Purchases")
    if not purchase_df.empty:
        st.plotly_chart(px.bar(purchase_df.groupby("date", as_index=False)["amount"].sum(), x="date", y="amount", title="Purchase Trend"), use_container_width=True)
        st.dataframe(purchase_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Purchases CSV",
            purchase_df.to_csv(index=False).encode("utf-8"),
            "purchases.csv",
            "text/csv",
            key="dl_purchases",
        )

    st.subheader("Inventory Valuation")
    if not stock_df.empty:
        st.plotly_chart(px.bar(stock_df, x="product", y=["left_percent", "sold_percent"], barmode="group", title="Stock Left vs Sold %"), use_container_width=True)
        st.dataframe(stock_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Inventory CSV",
            stock_df.to_csv(index=False).encode("utf-8"),
            "inventory.csv",
            "text/csv",
            key="dl_inventory",
        )

    st.subheader("Vendor Performance / Payables")
    if not vendor_df.empty:
        st.dataframe(vendor_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Vendor CSV",
            vendor_df.to_csv(index=False).encode("utf-8"),
            "vendors.csv",
            "text/csv",
            key="dl_vendors",
        )
