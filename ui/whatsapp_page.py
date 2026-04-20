"""
WhatsApp Orders & Chat Logs page for the ERP.
Shows all WhatsApp orders, lets owner update status + auto-notifies customer.
"""
import os
import httpx
import streamlit as st
from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import SalesOrder, SalesOrderItem, SalesStatus, Customer, WhatsAppLog, WhatsAppConversation
from services.sales import update_sales_status

BOT_BASE_URL = os.getenv("BOT_BASE_URL", "http://localhost:8080")

STATUS_EMOJI = {
    "created": "🆕", "pending": "⏳", "confirmed": "✅",
    "packed": "📦", "dispatched": "🚚", "delivered": "📬", "cancelled": "❌",
}
ALL_STATUSES = ["created", "pending", "confirmed", "packed", "dispatched", "delivered", "cancelled"]


def _notify_bot(order_id: int, new_status: str):
    try:
        r = httpx.post(f"{BOT_BASE_URL}/notify/order-update",
                       json={"order_id": order_id, "new_status": new_status}, timeout=8)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def render():
    st.title("📱 WhatsApp Orders")

    db: Session = SessionLocal()

    try:
        # ── Summary KPIs ──────────────────────────────────────────────────────
        wa_orders = db.query(SalesOrder).filter(SalesOrder.channel == "whatsapp").all()
        total     = len(wa_orders)
        pending   = sum(1 for o in wa_orders if o.status.value in ("created", "pending"))
        today_str = str(__import__("datetime").date.today())
        today_n   = sum(1 for o in wa_orders if str(o.order_date) == today_str)
        revenue   = sum(o.total_amount or 0 for o in wa_orders)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total WA Orders", total)
        c2.metric("Action Needed", pending)
        c3.metric("Today", today_n)
        c4.metric("Revenue", f"₹{revenue:,.0f}")

        st.divider()

        # ── Tabs ──────────────────────────────────────────────────────────────
        tab1, tab2 = st.tabs(["📦 Orders", "💬 Chat Logs"])

        # ══ Orders tab ════════════════════════════════════════════════════════
        with tab1:
            status_filter = st.selectbox("Filter by status",
                                          ["All"] + ALL_STATUSES, key="wa_status_filter")

            q = db.query(SalesOrder).filter(SalesOrder.channel == "whatsapp").order_by(SalesOrder.created_at.desc())
            if status_filter != "All":
                q = q.filter(SalesOrder.status == status_filter)
            orders = q.limit(100).all()

            if not orders:
                st.info("No WhatsApp orders yet.")
            else:
                for so in orders:
                    cname = so.customer.name if so.customer else "Unknown"
                    cphone = (so.customer.whatsapp_phone or so.customer.phone or "") if so.customer else ""
                    em    = STATUS_EMOJI.get(so.status.value, "📋")
                    items_text = ", ".join(
                        f"{i.product.name} ×{i.quantity:.0f}" for i in so.items if i.product
                    )
                    with st.expander(
                        f"{em} #{so.id} — {cname} | ₹{so.total_amount:,.0f} | "
                        f"{so.status.value.upper()} | {so.order_date}"
                    ):
                        col_a, col_b = st.columns([3, 1])

                        with col_a:
                            st.write(f"**Customer:** {cname}")
                            st.write(f"**Phone:** {cphone}")
                            st.write(f"**Items:** {items_text}")
                            st.write(f"**Amount:** ₹{so.total_amount:,.0f}")
                            if so.notes:
                                st.write(f"**Notes:** {so.notes}")
                            st.write(f"**Ordered:** {so.created_at}")

                        with col_b:
                            cur_idx = ALL_STATUSES.index(so.status.value) if so.status.value in ALL_STATUSES else 0
                            new_s   = st.selectbox("Update status", ALL_STATUSES,
                                                    index=cur_idx, key=f"s_{so.id}")

                            if st.button("💾 Save & Notify", key=f"save_{so.id}"):
                                try:
                                    update_sales_status(db, so.id, SalesStatus(new_s))
                                    result = _notify_bot(so.id, new_s)
                                    if result.get("sent"):
                                        st.success(f"✅ Updated + WhatsApp sent to {cphone}")
                                    elif result.get("error"):
                                        st.warning(f"Status updated, WA failed: {result['error']}")
                                    else:
                                        st.success("Status updated.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")

        # ══ Chat Logs tab ══════════════════════════════════════════════════════
        with tab2:
            phone_filter = st.text_input("Filter by phone", key="wa_phone_filter")
            logs_q = db.query(WhatsAppLog).order_by(WhatsAppLog.created_at.desc())
            if phone_filter:
                logs_q = logs_q.filter(WhatsAppLog.phone.contains(phone_filter))
            logs = logs_q.limit(200).all()

            if not logs:
                st.info("No messages logged yet.")
            else:
                for log in logs:
                    with st.chat_message("user" if log.direction == "inbound" else "assistant"):
                        st.caption(f"{'📨 From' if log.direction == 'inbound' else '📤 Sent to'} "
                                   f"{log.phone} — {log.created_at}")
                        st.write(log.message or "—")

    finally:
        db.close()
