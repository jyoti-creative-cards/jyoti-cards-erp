import os

import streamlit as st

from services.products import list_products, create_product, update_product, delete_product
from services.vendor_offerings import delete_vendor_offering, update_vendor_offering, upsert_vendor_offering
from services.vendors import list_vendors

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "products")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _save_upload(uploaded_file):
    if not uploaded_file:
        return None
    filename = uploaded_file.name.replace(" ", "_")
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return path


def render(db):
    st.markdown("## 📋 Items")
    st.caption("Your product catalog — each item has your ID and the vendor's ID")

    vendors = list_vendors(db)
    vendor_opts = {"— No Vendor —": None}
    vendor_opts.update({(v.firm_name or v.name): v.id for v in vendors})

    tab_list, tab_add = st.tabs(["All Items", "➕ Add New Item"])

    # ── item list ─────────────────────────────────────────────────────────────
    with tab_list:
        products = list_products(db)
        if not products:
            st.info("No items yet. Add your first item from the tab above.")
            return

        rows = []
        for p in products:
            vendor_name = ""
            if p.vendor:
                vendor_name = p.vendor.firm_name or p.vendor.name
            vendor_code = next(
                (o.vendor_product_code for o in getattr(p, "vendor_offerings", []) if o.vendor_id == p.vendor_id),
                "—",
            )
            rows.append({
                "Our ID": p.sku,
                "Name": p.name,
                "Vendor": vendor_name or "—",
                "Vendor ID": vendor_code,
                "Buy ₹": f"{p.purchase_price:,.0f}" if p.purchase_price else "—",
                "Sell ₹": f"{p.selling_price:,.0f}" if p.selling_price else "—",
                "Active": "Yes" if p.active else "No",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("#### ✏️ Edit Item")
        prod_map = {f"{p.sku} — {p.name}": p for p in products}
        selected = st.selectbox("Choose item", list(prod_map.keys()), label_visibility="collapsed")
        p = prod_map[selected]

        if p.image_path and os.path.exists(p.image_path):
            st.image(p.image_path, width=120)

        with st.form("edit_product"):
            st.markdown('<div class="section-label">ITEM DETAILS</div>', unsafe_allow_html=True)
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Item Name", p.name)
            sku = c2.text_input("Our Item ID", p.sku)
            category = c3.text_input("Category", p.category or "")

            st.markdown('<div class="section-label">VENDOR LINK</div>', unsafe_allow_html=True)
            vendor_labels = list(vendor_opts.keys())
            current_label = next((lbl for lbl, vid in vendor_opts.items() if vid == p.vendor_id), "— No Vendor —")
            c4, c5 = st.columns(2)
            sel_vendor = c4.selectbox("Primary Vendor", vendor_labels, index=vendor_labels.index(current_label))
            current_vid = next(
                (o.vendor_product_code for o in getattr(p, "vendor_offerings", []) if o.vendor_id == p.vendor_id), ""
            )
            vendor_item_id = c5.text_input("Vendor Item ID", current_vid)

            st.markdown('<div class="section-label">PRICING</div>', unsafe_allow_html=True)
            c6, c7 = st.columns(2)
            purchase_price = c6.number_input("Buy Price ₹", min_value=0.0, value=float(p.purchase_price or 0))
            selling_price = c7.number_input("Sell Price ₹", min_value=0.0, value=float(p.selling_price or 0))

            st.markdown('<div class="section-label">STOCK SETTINGS</div>', unsafe_allow_html=True)
            c8, c9 = st.columns(2)
            min_stock = c8.number_input("Minimum Stock", min_value=0.0, value=float(p.min_stock_level or 0))
            reorder_level = c9.number_input("Reorder Level", min_value=0.0, value=float(p.reorder_level or 0))
            active = st.checkbox("Active Item", value=bool(p.active))
            image = st.file_uploader("Replace Image", type=["png", "jpg", "jpeg", "webp"], key=f"img_{p.id}")

            st.markdown("")
            bc1, bc2, _ = st.columns([1, 1, 3])
            if bc1.form_submit_button("💾 Save", use_container_width=True):
                updated = update_product(
                    db, p.id, name=name, sku=sku, category=category,
                    vendor_id=vendor_opts[sel_vendor],
                    purchase_price=purchase_price, selling_price=selling_price,
                    min_stock_level=min_stock, reorder_level=reorder_level, active=active,
                    image_path=_save_upload(image) if image else p.image_path,
                )
                if vendor_opts[sel_vendor] and vendor_item_id:
                    upsert_vendor_offering(
                        db, vendor_id=vendor_opts[sel_vendor], product_id=updated.id,
                        vendor_product_code=vendor_item_id, vendor_price=purchase_price,
                        billing_percent=100, active=True,
                    )
                st.rerun()
            if bc2.form_submit_button("🗑️ Delete", use_container_width=True):
                delete_product(db, p.id)
                st.rerun()

        # ── vendor mapping detail ─────────────────────────────────────────────
        primary_vid = vendor_opts[sel_vendor] if 'sel_vendor' in dir() else p.vendor_id
        mappings = [o for o in getattr(p, "vendor_offerings", []) if primary_vid is None or o.vendor_id == primary_vid]
        if mappings:
            st.markdown("---")
            st.markdown("#### 🔗 Vendor Mapping")
            m = mappings[0]
            with st.form(f"map_{m.id}"):
                c1, c2 = st.columns(2)
                c1.text_input("Our Item ID", value=p.sku, disabled=True, key=f"ms_{m.id}")
                c2.text_input("Item Name", value=p.name, disabled=True, key=f"mn_{m.id}")
                c3, c4, c5 = st.columns(3)
                vid_code = c3.text_input("Vendor Item ID", value=m.vendor_product_code or "", key=f"mvc_{m.id}")
                vprice = c4.number_input("Vendor Price ₹", min_value=0.0, value=float(m.vendor_price or p.purchase_price or 0), key=f"mvp_{m.id}")
                bpct = c5.number_input("Billing %", min_value=0.0, value=float(m.billing_percent or 100), key=f"mb_{m.id}")
                notes = st.text_area("Notes", value=m.notes or "", height=60, key=f"mnt_{m.id}")

                mc1, mc2, _ = st.columns([1, 1, 3])
                if mc1.form_submit_button("💾 Save Mapping", use_container_width=True):
                    update_vendor_offering(db, m.id, vendor_product_code=vid_code, vendor_price=vprice, billing_percent=bpct, active=True, notes=notes)
                    update_product(db, p.id, purchase_price=vprice)
                    st.rerun()
                if mc2.form_submit_button("🗑️ Remove", use_container_width=True):
                    delete_vendor_offering(db, m.id)
                    st.rerun()

    # ── add item ──────────────────────────────────────────────────────────────
    with tab_add:
        with st.form("add_product"):
            st.markdown('<div class="section-label">ITEM DETAILS</div>', unsafe_allow_html=True)
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Item Name", key="n_name")
            sku = c2.text_input("Our Item ID", key="n_sku")
            category = c3.text_input("Category", key="n_cat")

            st.markdown('<div class="section-label">VENDOR LINK</div>', unsafe_allow_html=True)
            c4, c5 = st.columns(2)
            sel_vendor = c4.selectbox("Primary Vendor", list(vendor_opts.keys()), key="n_vendor")
            vendor_item_id = c5.text_input("Vendor Item ID", key="n_vid")

            st.markdown('<div class="section-label">PRICING</div>', unsafe_allow_html=True)
            c6, c7 = st.columns(2)
            purchase_price = c6.number_input("Buy Price ₹", min_value=0.0, key="n_buy")
            selling_price = c7.number_input("Sell Price ₹", min_value=0.0, key="n_sell")

            st.markdown('<div class="section-label">STOCK SETTINGS</div>', unsafe_allow_html=True)
            c8, c9 = st.columns(2)
            min_stock = c8.number_input("Minimum Stock", min_value=0.0, key="n_min")
            reorder_level = c9.number_input("Reorder Level", min_value=0.0, key="n_reorder")
            active = st.checkbox("Active Item", value=True, key="n_active")
            image = st.file_uploader("Item Image", type=["png", "jpg", "jpeg", "webp"], key="n_img")

            st.markdown("")
            if st.form_submit_button("➕ Add Item", use_container_width=True):
                if not name or not sku:
                    st.error("Item name and Our Item ID are required")
                elif not vendor_opts[sel_vendor] or not vendor_item_id:
                    st.error("Select a vendor and enter vendor item ID")
                else:
                    product = create_product(
                        db, name=name, sku=sku, category=category,
                        vendor_id=vendor_opts[sel_vendor],
                        purchase_price=purchase_price, selling_price=selling_price,
                        min_stock_level=min_stock, reorder_level=reorder_level, active=active,
                        image_path=_save_upload(image),
                    )
                    upsert_vendor_offering(
                        db, vendor_id=vendor_opts[sel_vendor], product_id=product.id,
                        vendor_product_code=vendor_item_id, vendor_price=purchase_price,
                        billing_percent=100, active=True,
                    )
                    st.success(f"Item '{name}' added!")
                    st.rerun()
