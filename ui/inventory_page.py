import streamlit as st
import pandas as pd
from services.inventory import get_stock, get_low_stock, get_transactions
from services.products import list_products


def render(db):
    st.header("Inventory")

    tab_stock, tab_low, tab_txns = st.tabs(["Current Stock", "Low Stock", "Transactions"])

    with tab_stock:
        stock_data = get_stock(db)
        if stock_data:
            rows = [{
                "Product": prod.name,
                "SKU": prod.sku,
                "Available": inv.quantity_available,
                "Reserved": inv.quantity_reserved,
                "Total": inv.quantity_available + inv.quantity_reserved,
                "Unit": prod.unit,
                "Location": inv.godown_location or "-",
            } for inv, prod in stock_data]
            df = pd.DataFrame(rows)

            # highlight low stock
            products = list_products(db)
            min_levels = {p.name: p.min_stock_level for p in products}

            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No inventory data")

    with tab_low:
        low = get_low_stock(db)
        if low:
            rows = [{
                "Product": prod.name,
                "Available": inv.quantity_available,
                "Min Level": prod.min_stock_level,
                "Deficit": prod.min_stock_level - inv.quantity_available,
            } for inv, prod in low]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.success("All stock levels are healthy")

    with tab_txns:
        products = list_products(db)
        prod_map = {"All": None}
        prod_map.update({f"{p.name} ({p.sku})": p.id for p in products})
        selected = st.selectbox("Filter by product", list(prod_map.keys()))

        txns = get_transactions(db, product_id=prod_map[selected])
        if txns:
            rows = [{
                "Date": t.created_at.strftime("%Y-%m-%d %H:%M"),
                "Product": t.product.name,
                "Type": t.txn_type.value,
                "Qty": t.quantity,
                "Ref": f"{t.reference_type}#{t.reference_id}" if t.reference_type else "-",
                "Notes": t.notes or "",
            } for t in txns]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No transactions yet")
