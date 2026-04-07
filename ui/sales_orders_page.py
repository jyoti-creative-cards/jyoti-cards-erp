import streamlit as st
import pandas as pd
from datetime import date
from services.customers import list_customers
from services.products import list_products
from services.sales import list_sales_orders, create_sales_order, update_sales_status, mark_delivered, get_sales_order
from services.inventory import get_product_stock
from db.models import SalesStatus


def render(db):
    st.header("Sales Orders")

    tab_list, tab_create = st.tabs(["All Orders", "Create Order"])

    with tab_list:
        sos = list_sales_orders(db)
        if sos:
            rows = [{
                "SO#": so.id,
                "Customer": so.customer.name,
                "Date": str(so.order_date),
                "Amount": f"₹{so.total_amount:,.0f}",
                "Status": so.status.value,
            } for so in sos]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.subheader("Order Actions")
            so_id = st.selectbox("Select SO", [so.id for so in sos], format_func=lambda x: f"SO#{x}")
            so = get_sales_order(db, so_id)

            if so and so.items:
                items = [{
                    "Product": i.product.name,
                    "Qty": i.quantity,
                    "Price": f"₹{i.unit_price:,.0f}",
                    "Total": f"₹{i.total_price:,.0f}",
                } for i in so.items]
                st.dataframe(pd.DataFrame(items), use_container_width=True, hide_index=True)

            if so:
                cols = st.columns(4)
                if so.status == SalesStatus.PENDING:
                    if cols[0].button("Mark Packed"):
                        update_sales_status(db, so.id, SalesStatus.PACKED)
                        st.rerun()
                if so.status == SalesStatus.PACKED:
                    if cols[1].button("Dispatch"):
                        update_sales_status(db, so.id, SalesStatus.DISPATCHED)
                        st.rerun()
                if so.status == SalesStatus.DISPATCHED:
                    if cols[2].button("Mark Delivered"):
                        mark_delivered(db, so.id)
                        st.rerun()
                if so.status in (SalesStatus.PENDING, SalesStatus.PACKED):
                    if cols[3].button("Cancel Order"):
                        update_sales_status(db, so.id, SalesStatus.CANCELLED)
                        st.rerun()
        else:
            st.info("No sales orders yet")

    with tab_create:
        customers = list_customers(db)
        products = list_products(db)

        if not customers:
            st.warning("Add customers first")
            return
        if not products:
            st.warning("Add products first")
            return

        cust_map = {c.name: c for c in customers}
        prod_map = {f"{p.name} ({p.sku})": p for p in products}

        selected_cust = st.selectbox("Customer", list(cust_map.keys()), key="so_cust")
        order_date = st.date_input("Order Date", date.today(), key="so_date")
        notes = st.text_area("Notes", key="so_notes")

        st.subheader("Items")
        num_items = st.number_input("Number of items", min_value=1, max_value=20, value=1, key="so_num_items")

        item_data = []
        for idx in range(int(num_items)):
            cols = st.columns([3, 1, 1, 1])
            prod_key = cols[0].selectbox("Product", list(prod_map.keys()), key=f"so_prod_{idx}")
            p = prod_map[prod_key]
            stock = get_product_stock(db, p.id)
            avail = stock.quantity_available if stock else 0
            cols[3].write(f"Stock: {avail}")
            qty = cols[1].number_input("Qty", min_value=0.01, value=1.0, key=f"so_qty_{idx}")
            price = cols[2].number_input("Price", min_value=0.0, value=p.selling_price, key=f"so_price_{idx}")
            item_data.append({"product_id": p.id, "quantity": qty, "unit_price": price})

        total = sum(i["quantity"] * i["unit_price"] for i in item_data)
        st.write(f"**Total: ₹{total:,.0f}**")

        if st.button("Create Sales Order"):
            c = cust_map[selected_cust]
            try:
                so = create_sales_order(db, c.id, item_data, order_date=order_date, notes=notes)
                st.success(f"SO#{so.id} created")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
