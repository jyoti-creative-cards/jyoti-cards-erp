from datetime import date, timedelta
from collections import defaultdict

import pandas as pd
import streamlit as st
from sqlalchemy import func

from db.models import (
    Inventory,
    InventoryTransaction,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    Product,
    SalesOrder,
    Vendor,
    VendorOffering,
    WhatsAppLog,
)
from services.inventory import get_low_stock, get_stock
from services.purchases import list_purchase_orders


def render(db):
    st.markdown("## 🏠 Home")

    # ══════════════════════════════════════════════════════════════════════════
    #  QUICK METRICS
    # ══════════════════════════════════════════════════════════════════════════
    vendor_count = db.query(Vendor).count()
    item_count = db.query(Product).filter(Product.active.is_(True)).count()
    mapping_count = db.query(VendorOffering).filter(VendorOffering.active.is_(True)).count()

    all_latest = list_purchase_orders(db, latest_only=True)
    sales_orders = db.query(SalesOrder).order_by(SalesOrder.created_at.desc()).all()
    open_pos = [po for po in all_latest if po.status.value in ("created", "partially_received", "completed")]
    closed_pos = [po for po in all_latest if po.status.value == "closed"]
    open_value = sum(float(po.final_amount or 0) for po in open_pos)
    total_value = sum(float(po.final_amount or 0) for po in all_latest)
    sales_pending = [so for so in sales_orders if (so.status.value if hasattr(so.status, "value") else str(so.status)) in ("pending", "confirmed")]
    sales_total = sum(float(so.total_amount or 0) for so in sales_orders)

    stock_rows = get_stock(db)
    low_stock = get_low_stock(db)
    inventory_value = sum(
        float(inv.quantity_available or 0) * float(prod.purchase_price or 0)
        for inv, prod in stock_rows
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Vendors", vendor_count)
    c2.metric("Items", item_count)
    c3.metric("Open Orders", len(open_pos))
    c4.metric("Low Stock", len(low_stock))

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Open Order Value", f"₹ {open_value:,.0f}")
    c6.metric("Total PO Value", f"₹ {total_value:,.0f}")
    c7.metric("Inventory Value", f"₹ {inventory_value:,.0f}")
    c8.metric("Customer Order Value", f"₹ {sales_total:,.0f}")

    c9, c10, c11, c12 = st.columns(4)
    c9.metric("Pending Customer Actions", len(sales_pending))
    c10.metric("Customer Orders", len(sales_orders))
    c11.metric("Open Vendor Actions", len(open_pos))
    c12.metric("Closed Vendor Orders", len(closed_pos))

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════════
    #  STATUS CHARTS (CUSTOMER + VENDOR)
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("### 📊 Order Status Overview")
    status_left, status_right = st.columns(2)

    with status_left:
        st.markdown("#### Customer Orders by Status")
        customer_status = defaultdict(int)
        for so in sales_orders:
            s = so.status.value if hasattr(so.status, "value") else str(so.status)
            customer_status[s.replace("_", " ").title()] += 1
        if customer_status:
            cdf = pd.DataFrame(
                [{"Status": k, "Count": v} for k, v in sorted(customer_status.items())]
            )
            st.bar_chart(cdf.set_index("Status")["Count"], use_container_width=True)
        else:
            st.info("No customer orders yet.")

    with status_right:
        st.markdown("#### Vendor Orders by Status")
        vendor_status = defaultdict(int)
        for po in all_latest:
            vendor_status[po.status.value.replace("_", " ").title()] += 1
        if vendor_status:
            vdf = pd.DataFrame(
                [{"Status": k, "Count": v} for k, v in sorted(vendor_status.items())]
            )
            st.bar_chart(vdf.set_index("Status")["Count"], use_container_width=True)
        else:
            st.info("No vendor orders yet.")

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════════
    #  ANALYTICS — with filters
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("### 📊 Analytics")

    # ── filters ───────────────────────────────────────────────────────────────
    fc1, fc2, fc3 = st.columns([1, 1, 1])
    today = date.today()
    default_start = today - timedelta(days=90)

    date_from = fc1.date_input("From", value=default_start, key="dash_from")
    date_to = fc2.date_input("To", value=today, key="dash_to")

    vendor_names = sorted({po.vendor.firm_name or po.vendor.name for po in all_latest})
    vendor_filter = fc3.selectbox("Vendor", ["All Vendors"] + vendor_names, key="dash_vf")

    # filter POs by date range and vendor
    filtered_pos = [
        po for po in all_latest
        if po.order_date and date_from <= po.order_date <= date_to
        and (vendor_filter == "All Vendors" or (po.vendor.firm_name or po.vendor.name) == vendor_filter)
    ]

    if not filtered_pos:
        st.info("No orders in this date range.")
    else:
        analytics_left, analytics_right = st.columns(2)

        # ── spend by vendor ───────────────────────────────────────────────────
        with analytics_left:
            st.markdown("#### 🏢 Spend by Vendor")
            vendor_spend = defaultdict(float)
            vendor_order_count = defaultdict(int)
            for po in filtered_pos:
                vname = po.vendor.firm_name or po.vendor.name
                vendor_spend[vname] += float(po.final_amount or 0)
                vendor_order_count[vname] += 1
            spend_df = pd.DataFrame([
                {"Vendor": k, "Amount ₹": v, "Orders": vendor_order_count[k]}
                for k, v in sorted(vendor_spend.items(), key=lambda x: -x[1])
            ])
            st.bar_chart(spend_df.set_index("Vendor")["Amount ₹"])
            st.dataframe(spend_df, use_container_width=True, hide_index=True)

        # ── monthly trend ─────────────────────────────────────────────────────
        with analytics_right:
            st.markdown("#### 📈 Monthly Purchase Trend")
            monthly = defaultdict(float)
            monthly_count = defaultdict(int)
            for po in filtered_pos:
                month_key = po.order_date.strftime("%Y-%m")
                monthly[month_key] += float(po.final_amount or 0)
                monthly_count[month_key] += 1
            if monthly:
                month_df = pd.DataFrame([
                    {"Month": k, "Value ₹": monthly[k], "Orders": monthly_count[k]}
                    for k in sorted(monthly.keys())
                ])
                st.line_chart(month_df.set_index("Month")["Value ₹"])
                st.dataframe(month_df, use_container_width=True, hide_index=True)

        st.markdown("---")

        # ── top items by PO value ─────────────────────────────────────────────
        st.markdown("#### 🏆 Top Items by Purchase Value")
        item_spend = defaultdict(lambda: {"name": "", "qty": 0.0, "value": 0.0})
        for po in filtered_pos:
            for item in po.items:
                sku = item.our_product_code or (item.product.sku if item.product else "?")
                item_spend[sku]["name"] = item.product.name if item.product else "?"
                item_spend[sku]["qty"] += float(item.quantity_ordered)
                item_spend[sku]["value"] += float(item.total_price or 0)

        top_items = sorted(item_spend.items(), key=lambda x: -x[1]["value"])[:15]
        if top_items:
            top_df = pd.DataFrame([
                {"Our ID": sku, "Item": d["name"], "Qty Ordered": f"{d['qty']:g}", "Value ₹": f"{d['value']:,.0f}"}
                for sku, d in top_items
            ])
            st.dataframe(top_df, use_container_width=True, hide_index=True)

        # ── PO status breakdown ───────────────────────────────────────────────
        st.markdown("---")
        stat_left, stat_right = st.columns(2)

        with stat_left:
            st.markdown("#### 📋 Order Status Breakdown")
            status_counts = defaultdict(int)
            status_values = defaultdict(float)
            for po in filtered_pos:
                s = po.status.value.replace("_", " ").title()
                status_counts[s] += 1
                status_values[s] += float(po.final_amount or 0)
            status_df = pd.DataFrame([
                {"Status": k, "Count": status_counts[k], "Value ₹": f"{status_values[k]:,.0f}"}
                for k in sorted(status_counts.keys())
            ])
            st.dataframe(status_df, use_container_width=True, hide_index=True)

        with stat_right:
            st.markdown("#### 📦 Inventory Snapshot")
            if stock_rows:
                top_stock = sorted(stock_rows, key=lambda x: -float(x[0].quantity_available))[:10]
                inv_df = pd.DataFrame([{
                    "Our ID": prod.sku,
                    "Item": prod.name,
                    "Stock": f"{inv.quantity_available:g}",
                    "Value ₹": f"{inv.quantity_available * (prod.purchase_price or 0):,.0f}",
                } for inv, prod in top_stock])
                st.dataframe(inv_df, use_container_width=True, hide_index=True)
            else:
                st.info("No inventory data yet.")

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════════
    #  OPEN ORDERS + LOW STOCK
    # ══════════════════════════════════════════════════════════════════════════
    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown("#### 📝 Open Purchase Orders")
        active_pos = [po for po in all_latest if po.status.value not in ("closed", "cancelled")]
        if active_pos:
            rows = [{
                "PO #": po.id,
                "Vendor": po.vendor.firm_name or po.vendor.name,
                "Items": len(po.items),
                "Value ₹": f"{po.final_amount:,.0f}",
                "Status": po.status.value.replace("_", " ").title(),
                "Date": str(po.order_date),
            } for po in active_pos[:15]]
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("No open orders.")

    with col_right:
        st.markdown("#### ⚠️ Low Stock Alerts")
        if low_stock:
            for inv, prod in low_stock[:8]:
                pct = (inv.quantity_available / prod.min_stock_level * 100) if prod.min_stock_level else 100
                st.markdown(f"**{prod.sku}** — {prod.name}")
                st.progress(min(pct / 100, 1.0))
                st.caption(f"{inv.quantity_available:g} available / {prod.min_stock_level:g} minimum")
        else:
            st.success("All items well stocked.")

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════════
    #  ACTION QUEUES
    # ══════════════════════════════════════════════════════════════════════════
    aq_left, aq_right = st.columns(2)

    with aq_left:
        st.markdown("#### 🧾 Customer Orders Needing Action")
        action_rows = []
        for so in sales_pending[:20]:
            status_val = so.status.value if hasattr(so.status, "value") else str(so.status)
            action_rows.append(
                {
                    "SO #": so.id,
                    "Customer": so.customer.name if so.customer else "—",
                    "Status": status_val.replace("_", " ").title(),
                    "Total ₹": f"{float(so.total_amount or 0):,.0f}",
                    "Channel": so.channel or "—",
                    "Date": str(so.order_date),
                }
            )
        if action_rows:
            st.dataframe(action_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No pending customer actions.")

    with aq_right:
        st.markdown("#### 🚚 Vendor Orders Needing Action")
        vendor_rows = []
        for po in open_pos[:20]:
            vendor_rows.append(
                {
                    "PO #": po.id,
                    "Vendor": po.vendor.firm_name or po.vendor.name,
                    "Status": po.status.value.replace("_", " ").title(),
                    "Value ₹": f"{float(po.final_amount or 0):,.0f}",
                    "Expected": str(po.expected_date or "—"),
                }
            )
        if vendor_rows:
            st.dataframe(vendor_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No vendor action queue.")

    st.markdown("---")

    # ── recent whatsapp ───────────────────────────────────────────────────────
    st.markdown("#### 💬 Recent WhatsApp")
    logs = db.query(WhatsAppLog).order_by(WhatsAppLog.created_at.desc()).limit(5).all()
    if logs:
        for log in logs:
            direction = "➡️ Sent" if log.direction == "outbound" else "⬅️ Received"
            time_str = log.created_at.strftime("%d %b, %I:%M %p") if log.created_at else ""
            msg_preview = (log.message or "")[:120]
            st.markdown(f"**{direction}** to `{log.phone}` — {time_str}")
            st.caption(msg_preview)
    else:
        st.info("No messages yet.")
