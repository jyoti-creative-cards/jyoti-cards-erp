import streamlit as st
import pandas as pd
from services.payments import (
    list_payments, record_customer_payment, record_vendor_payment,
    get_customer_ledger, get_vendor_ledger,
)
from services.customers import list_customers
from services.vendors import list_vendors


def render(db):
    st.header("Payments")

    tab_all, tab_cust, tab_vendor, tab_ledger = st.tabs(["All Payments", "Customer Payment", "Vendor Payment", "Ledger"])

    with tab_all:
        payments = list_payments(db)
        if payments:
            rows = [{
                "ID": p.id,
                "Type": p.payment_type.value,
                "Party": (p.customer.name if p.customer else p.vendor.name if p.vendor else "-"),
                "Amount": f"₹{p.amount:,.0f}",
                "Date": str(p.payment_date),
                "Reference": p.reference or "",
            } for p in payments]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No payments recorded")

    with tab_cust:
        customers = list_customers(db)
        if not customers:
            st.warning("No customers")
            return

        cmap = {f"{c.name} (Outstanding: ₹{c.outstanding_balance:,.0f})": c for c in customers}
        selected = st.selectbox("Customer", list(cmap.keys()), key="pay_cust")
        c = cmap[selected]

        with st.form("cust_payment"):
            amount = st.number_input("Amount", min_value=0.01)
            reference = st.text_input("Reference (UPI/Cash/Cheque)")
            notes = st.text_area("Notes")
            if st.form_submit_button("Record Payment"):
                record_customer_payment(db, c.id, amount, reference, notes)
                st.success(f"₹{amount:,.0f} received from {c.name}")
                st.rerun()

    with tab_vendor:
        vendors = list_vendors(db)
        if not vendors:
            st.warning("No vendors")
            return

        vmap = {v.name: v for v in vendors}
        selected = st.selectbox("Vendor", list(vmap.keys()), key="pay_vendor")
        v = vmap[selected]

        with st.form("vendor_payment"):
            amount = st.number_input("Amount", min_value=0.01, key="vp_amt")
            reference = st.text_input("Reference", key="vp_ref")
            notes = st.text_area("Notes", key="vp_notes")
            if st.form_submit_button("Record Payment"):
                record_vendor_payment(db, v.id, amount, reference, notes)
                st.success(f"₹{amount:,.0f} paid to {v.name}")
                st.rerun()

    with tab_ledger:
        entity_type = st.radio("Entity", ["Customer", "Vendor"], horizontal=True)
        if entity_type == "Customer":
            customers = list_customers(db)
            if customers:
                cmap = {c.name: c for c in customers}
                sel = st.selectbox("Select Customer", list(cmap.keys()), key="ledger_cust")
                entries = get_customer_ledger(db, cmap[sel].id)
                if entries:
                    rows = [{
                        "Date": e.created_at.strftime("%Y-%m-%d %H:%M"),
                        "Description": e.description,
                        "Debit": f"₹{e.debit:,.0f}" if e.debit else "",
                        "Credit": f"₹{e.credit:,.0f}" if e.credit else "",
                    } for e in entries]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                else:
                    st.info("No ledger entries")
        else:
            vendors = list_vendors(db)
            if vendors:
                vmap = {v.name: v for v in vendors}
                sel = st.selectbox("Select Vendor", list(vmap.keys()), key="ledger_vendor")
                entries = get_vendor_ledger(db, vmap[sel].id)
                if entries:
                    rows = [{
                        "Date": e.created_at.strftime("%Y-%m-%d %H:%M"),
                        "Description": e.description,
                        "Debit": f"₹{e.debit:,.0f}" if e.debit else "",
                        "Credit": f"₹{e.credit:,.0f}" if e.credit else "",
                    } for e in entries]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                else:
                    st.info("No ledger entries")
