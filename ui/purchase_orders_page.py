import streamlit as st
import pandas as pd
from datetime import date
from services.vendors import list_vendors
from services.products import list_products
from services.purchases import list_purchase_orders, create_purchase_order, receive_goods, get_purchase_order


def render(db):
    st.header("Purchase Orders")

    tab_list, tab_create, tab_receive = st.tabs(["All POs", "Create PO", "Stock Policy"])

    with tab_list:
        pos = list_purchase_orders(db)
        if pos:
            rows = [{
                "PO#": po.id,
                "Vendor": po.vendor.name,
                "Date": str(po.order_date),
                "Amount": f"₹{po.total_amount:,.0f}",
                "Status": po.status.value,
            } for po in pos]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.subheader("PO Details")
            po_id = st.selectbox("Select PO", [po.id for po in pos], format_func=lambda x: f"PO#{x}")
            po = get_purchase_order(db, po_id)
            if po and po.items:
                items = [{
                    "Product": i.product.name,
                    "Ordered": i.quantity_ordered,
                    "Received": i.quantity_received,
                    "Unit Price": f"₹{i.unit_price:,.0f}",
                    "Total": f"₹{i.total_price:,.0f}",
                } for i in po.items]
                st.dataframe(pd.DataFrame(items), use_container_width=True, hide_index=True)
        else:
            st.info("No purchase orders yet")

    with tab_create:
        vendors = list_vendors(db)
        products = list_products(db)

        if not vendors:
            st.warning("Add vendors first")
            return
        if not products:
            st.warning("Add products first")
            return

        vendor_map = {v.name: v for v in vendors}
        product_map = {f"{p.name} ({p.sku})": p for p in products}

        selected_vendor = st.selectbox("Vendor", list(vendor_map.keys()), key="po_vendor")
        order_date = st.date_input("Order Date", date.today(), key="po_date")
        expected_date = st.date_input("Expected Date", key="po_exp_date")
        notes = st.text_area("Notes", key="po_notes")

        st.subheader("Items")
        num_items = st.number_input("Number of items", min_value=1, max_value=20, value=1, key="po_num_items")

        item_data = []
        for idx in range(int(num_items)):
            cols = st.columns([3, 1, 1])
            prod = cols[0].selectbox("Product", list(product_map.keys()), key=f"po_prod_{idx}")
            qty = cols[1].number_input("Qty", min_value=0.01, value=1.0, key=f"po_qty_{idx}")
            price = cols[2].number_input("Price", min_value=0.0, value=product_map[prod].purchase_price, key=f"po_price_{idx}")
            item_data.append({"product_id": product_map[prod].id, "quantity": qty, "unit_price": price})

        total = sum(i["quantity"] * i["unit_price"] for i in item_data)
        st.write(f"**Total: ₹{total:,.0f}**")

        if st.button("Create Purchase Order"):
            v = vendor_map[selected_vendor]
            po = create_purchase_order(db, v.id, item_data, order_date=order_date, expected_date=expected_date, notes=notes)
            st.success(f"PO#{po.id} created and stock added")
            st.rerun()

    with tab_receive:
        st.info("Current phase rule: stock is added immediately when PO is created.")
        st.caption("Receive-goods workflow kept for later phases if you want stricter inward handling.")
