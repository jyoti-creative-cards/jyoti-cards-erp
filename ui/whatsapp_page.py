import pandas as pd
import streamlit as st

from backend.services.parser import parse_customer_message
from backend.services.whatsapp import business_number, send_whatsapp_message
from db.models import WhatsAppLog
from services.customers import get_or_create_customer_by_whatsapp
from services.sales import create_sales_order_from_names


def render(db):
    st.header("WhatsApp Inbox")
    st.info(f"Customer order number: {business_number()}")

    logs = db.query(WhatsAppLog).order_by(WhatsAppLog.created_at.desc()).limit(100).all()
    if logs:
        st.dataframe(pd.DataFrame([{
            "Time": l.created_at.strftime("%Y-%m-%d %H:%M"),
            "Phone": l.phone,
            "Direction": l.direction,
            "Message": l.message,
            "Status": l.status,
            "Type": l.related_type or "",
        } for l in logs]), use_container_width=True, hide_index=True)

    st.subheader("Manual inbound simulation")
    with st.form("manual_whatsapp"):
        phone = st.text_input("Customer Phone")
        message = st.text_area("Message")
        if st.form_submit_button("Process Message") and phone and message:
            customer = get_or_create_customer_by_whatsapp(db, phone)
            parsed = parse_customer_message(message)
            if parsed["intent"] == "place_order":
                so = create_sales_order_from_names(db, phone, parsed["items"], notes="Inbox manual simulation")
                st.success(f"Created SO#{so.id}")
            elif parsed["intent"] == "catalog_query":
                send_whatsapp_message(db, phone, "Catalog query logged. Use webhook/API for full auto reply.", "catalog_query", customer.id)
                st.success("Catalog query logged")
            else:
                st.warning("Could not parse message")
