import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st

from backend.services.whatsapp import business_number
from config import APP_PASSWORD
from db.database import SessionLocal, init_db

init_db()
st.set_page_config(page_title="Jyoti Cards ERP", page_icon="📦", layout="wide")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("Jyoti Cards ERP Login")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if password == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Wrong password")
    st.stop()

st.sidebar.title("📦 Jyoti Cards ERP")
st.sidebar.caption(f"Business WhatsApp: {business_number()}")
page = st.sidebar.radio("Navigate", [
    "Dashboard",
    "Products",
    "Vendors",
    "Customers",
    "Purchase Orders",
    "Sales Orders",
    "Discounts",
    "Inventory",
    "Payments",
    "Reports",
    "WhatsApp Inbox",
])

db = SessionLocal()
try:
    if page == "Dashboard":
        from ui.dashboard import render
    elif page == "Products":
        from ui.products_page import render
    elif page == "Vendors":
        from ui.vendors_page import render
    elif page == "Customers":
        from ui.customers_page import render
    elif page == "Purchase Orders":
        from ui.purchase_orders_page import render
    elif page == "Sales Orders":
        from ui.sales_orders_page import render
    elif page == "Discounts":
        from ui.discounts_page import render
    elif page == "Inventory":
        from ui.inventory_page import render
    elif page == "Payments":
        from ui.payments_page import render
    elif page == "Reports":
        from ui.reports_page import render
    elif page == "WhatsApp Inbox":
        from ui.whatsapp_page import render
    render(db)
finally:
    db.close()
