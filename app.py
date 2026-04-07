import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
from db.database import init_db, SessionLocal

init_db()

st.set_page_config(page_title="Jyoti Cards ERP", page_icon="📦", layout="wide")

st.sidebar.title("📦 Jyoti Cards ERP")
page = st.sidebar.radio(
    "Navigate",
    ["Dashboard", "Products", "Vendors", "Customers", "Purchase Orders", "Sales Orders", "Inventory", "Payments"],
)

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
    elif page == "Inventory":
        from ui.inventory_page import render
    elif page == "Payments":
        from ui.payments_page import render

    render(db)
finally:
    db.close()
