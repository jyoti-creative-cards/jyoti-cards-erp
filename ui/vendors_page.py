import streamlit as st

from services.vendors import list_vendors, create_vendor, update_vendor, delete_vendor


def render(db):
    st.markdown("## 🏢 Vendors")
    st.caption("Manage suppliers you buy goods from")

    vendors = list_vendors(db)

    tab_list, tab_add = st.tabs(["All Vendors", "➕ Add New Vendor"])

    # ── vendor list ───────────────────────────────────────────────────────────
    with tab_list:
        if not vendors:
            st.info("No vendors yet. Add your first vendor from the tab above.")
            return

        rows = []
        for v in vendors:
            rows.append({
                "Firm": v.firm_name or v.name,
                "Owner": v.owner_name or "—",
                "Mobile": v.phone or "—",
                "Billing": v.billing_condition or "100%",
                "Credit Terms": v.credit_terms or "—",
                "Shipment": v.default_shipment_mode or "—",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("#### ✏️ Edit Vendor")
        vmap = {f"{v.firm_name or v.name}": v for v in vendors}
        selected = st.selectbox("Choose vendor", list(vmap.keys()), label_visibility="collapsed")
        v = vmap[selected]

        with st.form("edit_vendor"):
            st.markdown('<div class="section-label">BASIC INFO</div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            firm_name = c1.text_input("Firm Name", v.firm_name or v.name)
            owner_name = c2.text_input("Owner Name", v.owner_name or "")
            c3, c4 = st.columns(2)
            phone = c3.text_input("Mobile Number", v.phone or "")
            billing_condition = c4.text_input("Billing Condition", v.billing_condition or "100%")

            st.markdown('<div class="section-label">ADDRESS & TAX</div>', unsafe_allow_html=True)
            address = st.text_area("Address", v.address or "", height=80)
            c5, c6, c7 = st.columns(3)
            credit_terms = c5.text_input("Credit Terms", v.credit_terms or "")
            gst_number = c6.text_input("GST Number", v.gst_number or "")
            gst_percent = c7.number_input("GST %", min_value=0.0, value=float(v.gst_percent or 0))
            gst_inclusive = st.checkbox("GST Inclusive", value=bool(v.gst_inclusive))

            st.markdown('<div class="section-label">SHIPPING</div>', unsafe_allow_html=True)
            c8, c9, c10 = st.columns(3)
            shipment_mode = c8.text_input("Shipment Mode", v.default_shipment_mode or "")
            transporter_name = c9.text_input("Transporter", v.transporter_name or "")
            transporter_contact = c10.text_input("Transporter Mobile", v.transporter_contact or "")

            st.markdown("")
            bc1, bc2, _ = st.columns([1, 1, 3])
            if bc1.form_submit_button("💾 Save Changes", use_container_width=True):
                update_vendor(db, v.id, firm_name=firm_name, owner_name=owner_name, phone=phone,
                              billing_condition=billing_condition, address=address, credit_terms=credit_terms,
                              gst_number=gst_number, gst_percent=gst_percent, gst_inclusive=gst_inclusive,
                              default_shipment_mode=shipment_mode, transporter_name=transporter_name,
                              transporter_contact=transporter_contact)
                st.rerun()
            if bc2.form_submit_button("🗑️ Delete", use_container_width=True):
                delete_vendor(db, v.id)
                st.rerun()

    # ── add vendor ────────────────────────────────────────────────────────────
    with tab_add:
        with st.form("add_vendor"):
            st.markdown('<div class="section-label">BASIC INFO</div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            firm_name = c1.text_input("Firm Name", key="new_firm")
            owner_name = c2.text_input("Owner Name", key="new_owner")
            c3, c4 = st.columns(2)
            phone = c3.text_input("Mobile Number", key="new_phone")
            billing_condition = c4.text_input("Billing Condition", value="100%", key="new_billing")

            st.markdown('<div class="section-label">ADDRESS & TAX</div>', unsafe_allow_html=True)
            address = st.text_area("Address", key="new_address", height=80)
            c5, c6, c7 = st.columns(3)
            credit_terms = c5.text_input("Credit Terms", key="new_credit")
            gst_number = c6.text_input("GST Number", key="new_gst")
            gst_percent = c7.number_input("GST %", min_value=0.0, key="new_gst_pct")
            gst_inclusive = st.checkbox("GST Inclusive", key="new_gst_inc")

            st.markdown('<div class="section-label">SHIPPING</div>', unsafe_allow_html=True)
            c8, c9, c10 = st.columns(3)
            shipment_mode = c8.text_input("Shipment Mode", key="new_ship")
            transporter_name = c9.text_input("Transporter", key="new_trans")
            transporter_contact = c10.text_input("Transporter Mobile", key="new_trans_ph")

            st.markdown("")
            if st.form_submit_button("➕ Add Vendor", use_container_width=True):
                if not firm_name:
                    st.error("Firm name is required")
                else:
                    create_vendor(db, firm_name=firm_name, owner_name=owner_name, phone=phone,
                                  billing_condition=billing_condition, address=address, credit_terms=credit_terms,
                                  gst_number=gst_number, gst_percent=gst_percent, gst_inclusive=gst_inclusive,
                                  default_shipment_mode=shipment_mode, transporter_name=transporter_name,
                                  transporter_contact=transporter_contact)
                    st.rerun()
