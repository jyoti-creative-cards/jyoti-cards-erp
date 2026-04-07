import pandas as pd
import streamlit as st

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
                "Phone": c.phone or "",
                "WhatsApp": c.whatsapp_phone or "",
                "Type": c.customer_type,
                "Payment": c.payment_mode,
                "Default Discount %": c.default_discount_percent,
                "Outstanding": c.outstanding_balance,
            } for c in customers]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            cmap = {f"{c.name} ({c.id})": c for c in customers}
            selected = st.selectbox("Edit customer", list(cmap.keys()))
            c = cmap[selected]
            with st.form("edit_customer"):
                name = st.text_input("Name", c.name)
                phone = st.text_input("Phone", c.phone or "")
                whatsapp_phone = st.text_input("WhatsApp Phone", c.whatsapp_phone or "")
                address = st.text_area("Address", c.address or "")
                customer_type = st.selectbox("Customer Type", ["retailer", "wholesaler"], index=0 if c.customer_type == "retailer" else 1)
                payment_mode = st.selectbox("Payment Mode", ["credit", "cash"], index=0 if c.payment_mode == "credit" else 1)
                credit_limit = st.number_input("Credit Limit", min_value=0.0, value=float(c.credit_limit or 0))
                default_discount_percent = st.number_input("Default Discount %", min_value=0.0, value=float(c.default_discount_percent or 0))
                notifications_enabled = st.checkbox("Notifications Enabled", value=bool(c.notifications_enabled))
                c1, c2 = st.columns(2)
                if c1.form_submit_button("Save"):
                    update_customer(db, c.id, name=name, phone=phone, whatsapp_phone=whatsapp_phone, address=address, customer_type=customer_type, payment_mode=payment_mode, credit_limit=credit_limit, default_discount_percent=default_discount_percent, notifications_enabled=notifications_enabled)
                    st.rerun()
                if c2.form_submit_button("Delete"):
                    delete_customer(db, c.id)
                    st.rerun()
        else:
            st.info("No customers yet")

    with tab_add:
        with st.form("add_customer"):
            name = st.text_input("Name")
            phone = st.text_input("Phone")
            whatsapp_phone = st.text_input("WhatsApp Phone")
            address = st.text_area("Address")
            customer_type = st.selectbox("Customer Type", ["retailer", "wholesaler"])
            payment_mode = st.selectbox("Payment Mode", ["credit", "cash"])
            credit_limit = st.number_input("Credit Limit", min_value=0.0)
            default_discount_percent = st.number_input("Default Discount %", min_value=0.0)
            notifications_enabled = st.checkbox("Notifications Enabled", value=True)
            if st.form_submit_button("Add Customer") and name:
                create_customer(db, name=name, phone=phone, whatsapp_phone=whatsapp_phone, address=address, customer_type=customer_type, payment_mode=payment_mode, credit_limit=credit_limit, default_discount_percent=default_discount_percent, notifications_enabled=notifications_enabled)
                st.rerun()
