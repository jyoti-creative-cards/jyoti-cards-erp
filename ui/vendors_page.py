import streamlit as st
import pandas as pd
from services.vendors import list_vendors, create_vendor, update_vendor, delete_vendor


def render(db):
    st.header("Vendors")

    tab_list, tab_add = st.tabs(["All Vendors", "Add Vendor"])

    with tab_list:
        vendors = list_vendors(db)
        if vendors:
            rows = [{"ID": v.id, "Name": v.name, "Phone": v.phone or "", "Address": v.address or "", "Credit Terms": v.credit_terms or ""} for v in vendors]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.subheader("Edit Vendor")
            vmap = {v.name: v for v in vendors}
            selected = st.selectbox("Select vendor", list(vmap.keys()), key="edit_vendor")
            v = vmap[selected]

            with st.form("edit_vendor"):
                name = st.text_input("Name", v.name)
                phone = st.text_input("Phone", v.phone or "")
                address = st.text_area("Address", v.address or "")
                credit_terms = st.text_input("Credit Terms", v.credit_terms or "")
                c1, c2 = st.columns(2)
                save = c1.form_submit_button("Save")
                remove = c2.form_submit_button("Delete", type="secondary")
                if save:
                    update_vendor(db, v.id, name=name, phone=phone, address=address, credit_terms=credit_terms)
                    st.success("Updated")
                    st.rerun()
                if remove:
                    delete_vendor(db, v.id)
                    st.success("Deleted")
                    st.rerun()
        else:
            st.info("No vendors yet")

    with tab_add:
        with st.form("add_vendor"):
            name = st.text_input("Name")
            phone = st.text_input("Phone")
            address = st.text_area("Address")
            credit_terms = st.text_input("Credit Terms")
            if st.form_submit_button("Add Vendor"):
                if name:
                    create_vendor(db, name=name, phone=phone, address=address, credit_terms=credit_terms)
                    st.success(f"Added {name}")
                    st.rerun()
                else:
                    st.error("Name required")
