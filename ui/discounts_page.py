import pandas as pd
import streamlit as st

from services.customers import list_customers
from services.discounts import list_discount_rules, create_discount_rule
from services.products import list_products


def render(db):
    st.header("Discounts")
    rules = list_discount_rules(db)
    if rules:
        st.dataframe(pd.DataFrame([{"Name": r.name, "Customer": r.customer.name if r.customer else "All", "Product": r.product.name if r.product else "All", "Discount %": r.discount_percent, "Active": r.active} for r in rules]), use_container_width=True, hide_index=True)
    customers = list_customers(db)
    products = list_products(db, active_only=True)
    cmap = {"All": None}
    cmap.update({f"{c.name} ({c.id})": c.id for c in customers})
    pmap = {"All": None}
    pmap.update({f"{p.name} ({p.sku})": p.id for p in products})
    with st.form("discount_rule"):
        name = st.text_input("Rule Name")
        customer = st.selectbox("Customer", list(cmap.keys()))
        product = st.selectbox("Product", list(pmap.keys()))
        discount_percent = st.number_input("Discount %", min_value=0.0)
        active = st.checkbox("Active", value=True)
        if st.form_submit_button("Create Rule") and name:
            create_discount_rule(db, name=name, customer_id=cmap[customer], product_id=pmap[product], discount_percent=discount_percent, active=active)
            st.rerun()
