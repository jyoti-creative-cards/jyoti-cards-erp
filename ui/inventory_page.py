import pandas as pd
import streamlit as st

from db.models import TxnType
from services.inventory import get_stock, get_low_stock, get_transactions, add_stock, deduct_stock
from services.products import list_products


def render(db):
    st.header("Inventory")
    tabs = st.tabs(["Current Stock", "Low Stock", "Manual Adjustment", "Transactions"])

    with tabs[0]:
        stock_data = get_stock(db)
        if stock_data:
            rows = []
            for inv, prod in stock_data:
                avail = inv.quantity_available or 0
                if avail <= 0:
                    status = "Out of Stock"
                elif avail <= (prod.min_stock_level or 0):
                    status = "Low Stock"
                else:
                    status = "In Stock"
                rows.append({
                    "Product": prod.name,
                    "SKU": prod.sku,
                    "Available": avail,
                    "Reserved": inv.quantity_reserved,
                    "Min Stock": prod.min_stock_level,
                    "Reorder Level": prod.reorder_level,
                    "Status": status,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No stock")

    with tabs[1]:
        low = get_low_stock(db)
        if low:
            st.dataframe(
                pd.DataFrame([
                    {"Product": prod.name, "SKU": prod.sku,
                     "Available": inv.quantity_available, "Min": prod.min_stock_level}
                    for inv, prod in low
                ]),
                use_container_width=True, hide_index=True,
            )
        else:
            st.success("Healthy stock")

    with tabs[2]:
        products = list_products(db)
        if not products:
            st.info("Add products first")
        else:
            pmap = {f"{p.name} ({p.sku})": p.id for p in products}
            with st.form("manual_adjust"):
                sel = st.selectbox("Product", list(pmap.keys()))
                direction = st.radio("Direction", ["Add", "Remove"], horizontal=True)
                qty = st.number_input("Quantity", min_value=0.01, value=1.0)
                notes = st.text_input("Reason / Notes")
                if st.form_submit_button("Apply Adjustment"):
                    try:
                        if direction == "Add":
                            add_stock(db, pmap[sel], qty, "manual_adjustment", 0,
                                      notes=notes or "Manual adjustment",
                                      txn_type=TxnType.ADJUSTMENT)
                        else:
                            deduct_stock(db, pmap[sel], qty, "manual_adjustment", 0,
                                         notes=notes or "Manual adjustment")
                        st.success(f"Inventory {direction.lower()}ed by {qty}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not adjust: {e}")

    with tabs[3]:
        products = list_products(db)
        pmap = {"All": None}
        pmap.update({f"{p.name} ({p.sku})": p.id for p in products})
        selected = st.selectbox("Product", list(pmap.keys()), key="txn_filter")
        txns = get_transactions(db, product_id=pmap[selected])
        if txns:
            st.dataframe(
                pd.DataFrame([{
                    "Date": t.created_at,
                    "Product": t.product.name if t.product else "",
                    "Type": t.txn_type.value if hasattr(t.txn_type, "value") else t.txn_type,
                    "Qty": t.quantity,
                    "Ref": f"{t.reference_type}#{t.reference_id}",
                    "Notes": t.notes or "",
                } for t in txns]),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("No transactions")
