import streamlit as st
import pandas as pd
from services.customers import list_customers, create_customer, update_customer, delete_customer


def render(db):
    st.header("Customers")

    tab_list, tab_add = st.tabs(["All Customers", "Add Customer"])

    with tab_list:
        customers = list_customers(db)
        if customers:
            rows = [{
                "ID": c.id,
                "Name": c.name,
                "Type": c.customer_type,
                "Payment": c.payment_mode,
                "Phone": c.phone or "",
                "Address": c.address or "",
                "Credit Limit": f"₹{c.credit_limit:,.0f}",
                "Outstanding": f"₹{c.outstanding_balance:,.0f}",
            } for c in customers]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.subheader("Edit Customer")
            cmap = {c.name: c for c in customers}
            selected = st.selectbox("Select customer", list(cmap.keys()), key="edit_cust")
            c = cmap[selected]

            with st.form("edit_customer"):
                name = st.text_input("Name", c.name)
                phone = st.text_input("Phone", c.phone or "")
                address = st.text_area("Address", c.address or "")
                customer_type = st.selectbox("Customer Type", ["retailer", "wholesaler"], index=["retailer", "wholesaler"].index(c.customer_type) if c.customer_type in ["retailer", "wholesaler"] else 0)
                payment_mode = st.selectbox("Payment Mode", ["credit", "cash"], index=["credit", "cash"].index(c.payment_mode) if c.payment_mode in ["credit", "cash"] else 0)
                credit_limit = st.number_input("Credit Limit", value=c.credit_limit, min_value=0.0)
                c1, c2 = st.columns(2)
                save = c1.form_submit_button("Save")
                remove = c2.form_submit_button("Delete", type="secondary")
                if save:
                    update_customer(db, c.id, name=name, phone=phone, address=address, customer_type=customer_type, payment_mode=payment_mode, credit_limit=credit_limit)
                    st.success("Updated")
                    st.rerun()
                if remove:
                    delete_customer(db, c.id)
                    st.success("Deleted")
                    st.rerun()
        else:
            st.info("No customers yet")

    with tab_add:
        with st.form("add_customer"):
            name = st.text_input("Name")
            phone = st.text_input("Phone")
            address = st.text_area("Address")
            customer_type = st.selectbox("Customer Type", ["retailer", "wholesaler"])
            payment_mode = st.selectbox("Payment Mode", ["credit", "cash"])
            credit_limit = st.number_input("Credit Limit", min_value=0.0)
            if st.form_submit_button("Add Customer"):
                if name:
                    create_customer(db, name=name, phone=phone, address=address, customer_type=customer_type, payment_mode=payment_mode, credit_limit=credit_limit)
                    st.success(f"Added {name}")
                    st.rerun()
                else:
                    st.error("Name required")
