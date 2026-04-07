from datetime import date

import pandas as pd
import streamlit as st

from db.models import SalesStatus
from services.customers import list_customers
from services.inventory import get_product_stock
from services.products import list_products
from services.sales import list_sales_orders, create_sales_order, update_sales_status, mark_delivered, get_sales_order


def render(db):
    st.header("Sales Orders")
    tabs = st.tabs(["All Orders", "Create Order"])

    with tabs[0]:
        orders = list_sales_orders(db)
        if orders:
            rows = [{"SO#": so.id, "Customer": so.customer.name, "Channel": so.channel, "Discount %": so.discount_percent, "Amount": so.total_amount, "Status": so.status.value, "Customer Msg": so.customer_notification_status.value if so.customer_notification_status else ""} for so in orders]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            so = get_sales_order(db, st.selectbox("Order", [o.id for o in orders], format_func=lambda x: f"SO#{x}"))
            if so:
                st.dataframe(pd.DataFrame([{"Product": i.product.name, "Qty": i.quantity, "Discount %": i.discount_percent, "Total": i.total_price} for i in so.items]), use_container_width=True, hide_index=True)
                c1, c2, c3, c4 = st.columns(4)
                if c1.button("Packed"):
                    update_sales_status(db, so.id, SalesStatus.PACKED)
                    st.rerun()
                if c2.button("Dispatch"):
                    update_sales_status(db, so.id, SalesStatus.DISPATCHED)
                    st.rerun()
                if c3.button("Delivered"):
                    mark_delivered(db, so.id)
                    st.rerun()
                if c4.button("Cancel"):
                    update_sales_status(db, so.id, SalesStatus.CANCELLED)
                    st.rerun()
        else:
            st.info("No sales orders")

    with tabs[1]:
        customers = list_customers(db)
        products = list_products(db, active_only=True)
        if not customers or not products:
            st.warning("Need customers and products first")
        else:
            cmap = {f"{c.name} ({c.id})": c for c in customers}
            pmap = {f"{p.name} ({p.sku})": p for p in products}
            customer_label = st.selectbox("Customer", list(cmap.keys()))
            customer = cmap[customer_label]
            order_date = st.date_input("Order Date", date.today())
            notes = st.text_area("Notes")
            discount_percent = st.number_input("Order Discount %", min_value=0.0, value=float(customer.default_discount_percent or 0))
            count = st.number_input("Items", min_value=1, max_value=20, value=1, key="so_count")
            items = []
            for idx in range(int(count)):
                cols = st.columns([3, 1, 1, 1])
                p_label = cols[0].selectbox("Product", list(pmap.keys()), key=f"so_p_{idx}")
                product = pmap[p_label]
                stock = get_product_stock(db, product.id)
                cols[3].write(f"Stock: {stock.quantity_available if stock else 0}")
                qty = cols[1].number_input("Qty", min_value=1.0, value=1.0, key=f"so_q_{idx}")
                price = cols[2].number_input("Price", min_value=0.0, value=float(product.selling_price), key=f"so_pr_{idx}")
                items.append({"product_id": product.id, "quantity": qty, "unit_price": price})
            if st.button("Create Sales Order"):
                so = create_sales_order(db, customer.id, items, order_date=order_date, notes=notes, channel="manual", discount_percent=discount_percent)
                st.success(f"SO#{so.id} created and customer notified")
                st.rerun()
