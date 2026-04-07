import streamlit as st
import pandas as pd
import os
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
            rows = [{
                "ID": p.id,
                "Name": p.name,
                "SKU": p.sku,
                "Vendor": p.vendor.name if p.vendor else "",
                "Category": p.category or "",
                "Purchase ₹": p.purchase_price,
                "Selling ₹": p.selling_price,
                "Unit": p.unit,
                "Min Stock": p.min_stock_level,
                "Image": "Yes" if p.image_path else "No",
            } for p in products]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.subheader("Edit Product")
            prod_map = {f"{p.name} ({p.sku})": p for p in products}
            selected = st.selectbox("Select product", list(prod_map.keys()), key="edit_prod")
            p = prod_map[selected]
            if p.image_path and os.path.exists(p.image_path):
                st.image(p.image_path, width=160)

            with st.form("edit_product"):
                name = st.text_input("Name", p.name)
                sku = st.text_input("SKU", p.sku)
                category = st.text_input("Category", p.category or "")
                current_vendor_label = "None"
                for label, vendor_id_value in vendor_options.items():
                    if vendor_id_value == p.vendor_id:
                        current_vendor_label = label
                        break
                selected_vendor = st.selectbox("Vendor", list(vendor_options.keys()), index=list(vendor_options.keys()).index(current_vendor_label))
                purchase_price = st.number_input("Purchase Price", value=p.purchase_price, min_value=0.0)
                selling_price = st.number_input("Selling Price", value=p.selling_price, min_value=0.0)
                unit = st.selectbox("Unit", ["pcs", "kg", "box", "litre", "dozen"], index=["pcs", "kg", "box", "litre", "dozen"].index(p.unit) if p.unit in ["pcs", "kg", "box", "litre", "dozen"] else 0)
                min_stock = st.number_input("Min Stock Level", value=p.min_stock_level, min_value=0.0)
                image = st.file_uploader("Replace Image", type=["png", "jpg", "jpeg", "webp"], key=f"edit_img_{p.id}")

                c1, c2 = st.columns(2)
                save = c1.form_submit_button("Save Changes")
                remove = c2.form_submit_button("Delete Product", type="secondary")

                if save:
                    image_path = save_uploaded_file(image) if image else p.image_path
                    update_product(db, p.id, name=name, sku=sku, category=category,
                                   vendor_id=vendor_options[selected_vendor],
                                   purchase_price=purchase_price, selling_price=selling_price,
                                   unit=unit, min_stock_level=min_stock, image_path=image_path)
                    st.success("Updated")
                    st.rerun()
                if remove:
                    delete_product(db, p.id)
                    st.success("Deleted")
                    st.rerun()
        else:
            st.info("No products yet")

    with tab_add:
        with st.form("add_product"):
            name = st.text_input("Name")
            sku = st.text_input("SKU")
            category = st.text_input("Category")
            selected_vendor = st.selectbox("Vendor", list(vendor_options.keys()))
            purchase_price = st.number_input("Purchase Price", min_value=0.0)
            selling_price = st.number_input("Selling Price", min_value=0.0)
            unit = st.selectbox("Unit", ["pcs", "kg", "box", "litre", "dozen"])
            min_stock = st.number_input("Min Stock Level", min_value=0.0)
            image = st.file_uploader("Product Image", type=["png", "jpg", "jpeg", "webp"])

            if st.form_submit_button("Add Product"):
                if name and sku:
                    image_path = save_uploaded_file(image)
                    create_product(db, name=name, sku=sku, category=category,
                                   vendor_id=vendor_options[selected_vendor],
                                   purchase_price=purchase_price, selling_price=selling_price,
                                   unit=unit, min_stock_level=min_stock, image_path=image_path)
                    st.success(f"Added {name}")
                    st.rerun()
                else:
                    st.error("Name and SKU required")
