import streamlit as st

from config import META_PHONE_NUMBER_ID, WHATSAPP_PROVIDER
from backend.services.whatsapp import business_number, send_whatsapp_message
from db.models import WhatsAppLog
from services.vendors import list_vendors


def render(db):
    st.markdown("## 💬 WhatsApp")
    st.caption("Message logs and manual messaging with vendors")

    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Business Number", business_number())
    mc2.metric("Provider", WHATSAPP_PROVIDER.upper())
    mc3.metric("Phone ID", META_PHONE_NUMBER_ID or "Not set")

    tabs = st.tabs(["📜 Message Log", "✉️ Send Message"])

    # ── message log ───────────────────────────────────────────────────────────
    with tabs[0]:
        logs = db.query(WhatsAppLog).order_by(WhatsAppLog.created_at.desc()).limit(100).all()
        if not logs:
            st.info("No messages yet.")
            return

        for log in logs:
            direction = "➡️ Sent" if log.direction == "outbound" else "⬅️ Received"
            status_icon = "✅" if log.status in ("sent", "mock_sent") else ("❌" if log.status == "failed" else "⏳")
            time_str = log.created_at.strftime("%d %b %Y, %I:%M %p") if log.created_at else ""

            with st.container():
                hc1, hc2 = st.columns([4, 1])
                hc1.markdown(f"{direction} **{log.phone}** — {time_str}")
                hc2.markdown(f"{status_icon} `{log.status}`")
                st.caption(log.message or "—")
                if log.related_type:
                    st.caption(f"Related: {log.related_type} #{log.related_id}")
                st.markdown("---")

    # ── send message ──────────────────────────────────────────────────────────
    with tabs[1]:
        vendors = list_vendors(db)
        if not vendors:
            st.warning("Add vendors first to send messages.")
            return

        vendor_map = {(v.firm_name or v.name): v for v in vendors}
        sel = st.selectbox("Select Vendor", list(vendor_map.keys()), key="wa_vendor")
        vendor = vendor_map[sel]

        greeting = f"Hello {vendor.owner_name or vendor.firm_name or vendor.name}, this is Jyoti Cards."

        with st.form("send_wa"):
            phone = st.text_input("Mobile Number", value=vendor.phone or "")
            message = st.text_area("Message", value=greeting, height=100)
            if st.form_submit_button("📤 Send WhatsApp Message", use_container_width=True):
                if not phone or not message:
                    st.error("Phone and message are required")
                else:
                    result = send_whatsapp_message(db, phone, message, "vendor_manual", vendor.id)
                    if result.status == "failed":
                        st.error(f"Failed: {result.error or 'Unknown error'}")
                    else:
                        st.success(f"Message sent — Status: {result.status}")
                        st.rerun()
