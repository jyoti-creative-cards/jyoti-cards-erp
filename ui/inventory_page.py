import pandas as pd
import streamlit as st

from services.inventory import get_stock, get_low_stock, get_transactions
from services.products import list_products


def render(db):
    st.header("Inventory")
    tabs = st.tabs(["Current Stock", "Low Stock", "Transactions"])
    with tabs[0]:
        stock_data = get_stock(db)
        if stock_data:
            st.dataframe(pd.DataFrame([{
                "Product": prod.name,
                "SKU": prod.sku,
                "Available": inv.quantity_available,
                "Reserved": inv.quantity_reserved,
                "Left %": round((inv.quantity_available / (inv.quantity_available + inv.quantity_reserved) * 100), 2) if (inv.quantity_available + inv.quantity_reserved) else 0,
            } for inv, prod in stock_data]), use_container_width=True, hide_index=True)
        else:
            st.info("No stock")
    with tabs[1]:
        low = get_low_stock(db)
        if low:
            st.dataframe(pd.DataFrame([{"Product": prod.name, "Available": inv.quantity_available, "Min": prod.min_stock_level} for inv, prod in low]), use_container_width=True, hide_index=True)
        else:
            st.success("Healthy stock")
    with tabs[2]:
        products = list_products(db)
        pmap = {"All": None}
        pmap.update({f"{p.name} ({p.sku})": p.id for p in products})
        selected = st.selectbox("Product", list(pmap.keys()))
        txns = get_transactions(db, product_id=pmap[selected])
        if txns:
            st.dataframe(pd.DataFrame([{"Date": t.created_at, "Product": t.product.name, "Type": t.txn_type.value, "Qty": t.quantity, "Ref": f"{t.reference_type}#{t.reference_id}", "Notes": t.notes or ""} for t in txns]), use_container_width=True, hide_index=True)
