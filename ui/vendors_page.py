import pandas as pd
import streamlit as st

from services.vendors import list_vendors, create_vendor, update_vendor, delete_vendor


def render(db):
    st.header("Vendors")
    tab_list, tab_add = st.tabs(["All Vendors", "Add Vendor"])

    with tab_list:
        vendors = list_vendors(db)
        if vendors:
            rows = [{
                "ID": v.id,
                "Name": v.name,
                "Phone": v.phone or "",
                "GST %": v.gst_percent,
                "GST No": v.gst_number or "",
                "Shipment": v.default_shipment_mode or "",
                "Transport": v.transporter_name or "",
            } for v in vendors]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            vmap = {f"{v.name} ({v.id})": v for v in vendors}
            selected = st.selectbox("Edit vendor", list(vmap.keys()))
            v = vmap[selected]
            with st.form("edit_vendor"):
                name = st.text_input("Name", v.name)
                phone = st.text_input("Phone", v.phone or "")
                address = st.text_area("Address", v.address or "")
                credit_terms = st.text_input("Credit Terms", v.credit_terms or "")
                gst_number = st.text_input("GST Number", v.gst_number or "")
                gst_percent = st.number_input("GST Percent", min_value=0.0, value=float(v.gst_percent or 0))
                gst_inclusive = st.checkbox("GST Inclusive", value=bool(v.gst_inclusive))
                shipment_mode = st.text_input("Default Shipment Mode", v.default_shipment_mode or "")
                transporter_name = st.text_input("Transporter Name", v.transporter_name or "")
                transporter_contact = st.text_input("Transporter Contact", v.transporter_contact or "")
                c1, c2 = st.columns(2)
                if c1.form_submit_button("Save"):
                    update_vendor(db, v.id, name=name, phone=phone, address=address, credit_terms=credit_terms, gst_number=gst_number, gst_percent=gst_percent, gst_inclusive=gst_inclusive, default_shipment_mode=shipment_mode, transporter_name=transporter_name, transporter_contact=transporter_contact)
                    st.rerun()
                if c2.form_submit_button("Delete"):
                    delete_vendor(db, v.id)
                    st.rerun()
        else:
            st.info("No vendors yet")

    with tab_add:
        with st.form("add_vendor"):
            name = st.text_input("Name")
            phone = st.text_input("Phone")
            address = st.text_area("Address")
            credit_terms = st.text_input("Credit Terms")
            gst_number = st.text_input("GST Number")
            gst_percent = st.number_input("GST Percent", min_value=0.0)
            gst_inclusive = st.checkbox("GST Inclusive")
            shipment_mode = st.text_input("Default Shipment Mode")
            transporter_name = st.text_input("Transporter Name")
            transporter_contact = st.text_input("Transporter Contact")
            if st.form_submit_button("Add Vendor") and name:
                create_vendor(db, name=name, phone=phone, address=address, credit_terms=credit_terms, gst_number=gst_number, gst_percent=gst_percent, gst_inclusive=gst_inclusive, default_shipment_mode=shipment_mode, transporter_name=transporter_name, transporter_contact=transporter_contact)
                st.rerun()
