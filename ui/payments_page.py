import pandas as pd
import streamlit as st

from services.customers import list_customers
from services.payments import list_payments, record_customer_payment, record_vendor_payment, get_customer_ledger, get_vendor_ledger
from services.vendors import list_vendors


def render(db):
    st.header("Payments")
    tabs = st.tabs(["All Payments", "Customer Payment", "Vendor Payment", "Ledger"])
    with tabs[0]:
        payments = list_payments(db)
        if payments:
            st.dataframe(pd.DataFrame([{"ID": p.id, "Type": p.payment_type.value, "Party": p.customer.name if p.customer else p.vendor.name if p.vendor else "", "Amount": p.amount, "Date": p.payment_date, "Ref": p.reference or ""} for p in payments]), use_container_width=True, hide_index=True)
    with tabs[1]:
        customers = list_customers(db)
        if customers:
            cmap = {f"{c.name} ({c.id})": c for c in customers}
            c = cmap[st.selectbox("Customer", list(cmap.keys()))]
            with st.form("cust_pay"):
                amount = st.number_input("Amount", min_value=0.01)
                reference = st.text_input("Reference")
                notes = st.text_area("Notes")
                if st.form_submit_button("Record"):
                    record_customer_payment(db, c.id, amount, reference, notes)
                    st.rerun()
    with tabs[2]:
        vendors = list_vendors(db)
        if vendors:
            vmap = {f"{v.name} ({v.id})": v for v in vendors}
            v = vmap[st.selectbox("Vendor", list(vmap.keys()))]
            with st.form("vendor_pay"):
                amount = st.number_input("Amount", min_value=0.01, key="vend_amt")
                reference = st.text_input("Reference", key="vend_ref")
                notes = st.text_area("Notes", key="vend_notes")
                if st.form_submit_button("Record"):
                    record_vendor_payment(db, v.id, amount, reference, notes)
                    st.rerun()
    with tabs[3]:
        entity = st.radio("Ledger For", ["Customer", "Vendor"], horizontal=True)
        if entity == "Customer":
            customers = list_customers(db)
            if customers:
                cmap = {f"{c.name} ({c.id})": c.id for c in customers}
                entries = get_customer_ledger(db, cmap[st.selectbox("Customer Ledger", list(cmap.keys()))])
                st.dataframe(pd.DataFrame([{"Date": e.created_at, "Description": e.description, "Debit": e.debit, "Credit": e.credit} for e in entries]), use_container_width=True, hide_index=True)
        else:
            vendors = list_vendors(db)
            if vendors:
                vmap = {f"{v.name} ({v.id})": v.id for v in vendors}
                entries = get_vendor_ledger(db, vmap[st.selectbox("Vendor Ledger", list(vmap.keys()))])
                st.dataframe(pd.DataFrame([{"Date": e.created_at, "Description": e.description, "Debit": e.debit, "Credit": e.credit} for e in entries]), use_container_width=True, hide_index=True)
