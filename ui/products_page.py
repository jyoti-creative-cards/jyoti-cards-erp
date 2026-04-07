import os

import pandas as pd
import streamlit as st

from services.products import list_products, create_product, update_product, delete_product
from services.vendors import list_vendors

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "products")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def save_uploaded_file(uploaded_file):
    if not uploaded_file:
        return None
    filename = uploaded_file.name.replace(" ", "_")
    target_path = os.path.join(UPLOAD_DIR, filename)
    with open(target_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return target_path


def render(db):
    st.header("Products")
    vendors = list_vendors(db)
    vendor_options = {"None": None}
    vendor_options.update({f"{v.name} (ID:{v.id})": v.id for v in vendors})
    tab_list, tab_add = st.tabs(["All Products", "Add Product"])

    with tab_list:
        products = list_products(db)
        if products:
            st.dataframe(pd.DataFrame([{
                "ID": p.id,
                "Name": p.name,
                "SKU": p.sku,
                "Vendor": p.vendor.name if p.vendor else "",
                "Purchase ₹": p.purchase_price,
                "Selling ₹": p.selling_price,
                "Min Stock": p.min_stock_level,
                "Reorder": p.reorder_level,
                "Active": p.active,
            } for p in products]), use_container_width=True, hide_index=True)
            prod_map = {f"{p.name} ({p.sku})": p for p in products}
            selected = st.selectbox("Select product", list(prod_map.keys()))
            p = prod_map[selected]
            if p.image_path and os.path.exists(p.image_path):
                st.image(p.image_path, width=150)
            with st.form("edit_product"):
                name = st.text_input("Name", p.name)
                sku = st.text_input("SKU", p.sku)
                category = st.text_input("Category", p.category or "")
                selected_vendor = st.selectbox("Vendor", list(vendor_options.keys()))
                purchase_price = st.number_input("Purchase Price", min_value=0.0, value=float(p.purchase_price or 0))
                selling_price = st.number_input("Selling Price", min_value=0.0, value=float(p.selling_price or 0))
                min_stock = st.number_input("Min Stock", min_value=0.0, value=float(p.min_stock_level or 0))
                reorder_level = st.number_input("Reorder Level", min_value=0.0, value=float(p.reorder_level or 0))
                active = st.checkbox("Active", value=bool(p.active))
                image = st.file_uploader("Replace Image", type=["png", "jpg", "jpeg", "webp"], key=f"img_{p.id}")
                c1, c2 = st.columns(2)
                if c1.form_submit_button("Save"):
                    update_product(db, p.id, name=name, sku=sku, category=category, vendor_id=vendor_options[selected_vendor], purchase_price=purchase_price, selling_price=selling_price, min_stock_level=min_stock, reorder_level=reorder_level, active=active, image_path=save_uploaded_file(image) if image else p.image_path)
                    st.rerun()
                if c2.form_submit_button("Delete"):
                    delete_product(db, p.id)
                    st.rerun()
        else:
            st.info("No products")

    with tab_add:
        with st.form("add_product"):
            name = st.text_input("Name")
            sku = st.text_input("SKU")
            category = st.text_input("Category")
            selected_vendor = st.selectbox("Vendor", list(vendor_options.keys()), key="vendor_new")
            purchase_price = st.number_input("Purchase Price", min_value=0.0)
            selling_price = st.number_input("Selling Price", min_value=0.0)
            min_stock = st.number_input("Min Stock", min_value=0.0)
            reorder_level = st.number_input("Reorder Level", min_value=0.0)
            active = st.checkbox("Active", value=True)
            image = st.file_uploader("Product Image", type=["png", "jpg", "jpeg", "webp"], key="img_new")
            if st.form_submit_button("Add Product") and name and sku:
                create_product(db, name=name, sku=sku, category=category, vendor_id=vendor_options[selected_vendor], purchase_price=purchase_price, selling_price=selling_price, min_stock_level=min_stock, reorder_level=reorder_level, active=active, image_path=save_uploaded_file(image))
                st.rerun()
