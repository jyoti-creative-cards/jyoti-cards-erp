import os

import streamlit as st

from backend.services.whatsapp import (
    customer_welcome_template,
    send_whatsapp_document,
    send_whatsapp_message,
    send_whatsapp_template,
)
from db.models import NotificationStatus, Product, SalesOrder, SalesOrderItem, SalesStatus
from services.customers import create_customer, delete_customer, list_customers, update_customer
from services.sales_pdf import generate_sales_order_pdf


def _customer_phone(order: SalesOrder) -> str:
    customer = order.customer
    if not customer:
        return ""
    return customer.whatsapp_phone or customer.phone or ""


def _status_value(status) -> str:
    return status.value if hasattr(status, "value") else str(status or "")


def _append_note(existing: str, incoming: str) -> str:
    existing = (existing or "").strip()
    incoming = (incoming or "").strip()
    if not incoming:
        return existing
    if not existing:
        return incoming
    return f"{existing}\n{incoming}"


def _recalculate_order_totals(order: SalesOrder):
    subtotal = 0.0
    for item in order.items:
        item.total_price = float(item.quantity or 0) * float(item.unit_price or 0)
        subtotal += float(item.total_price or 0)
    order.subtotal_amount = subtotal
    order.total_amount = subtotal - float(order.discount_amount or 0)


def _send_customer_status_update(db, order: SalesOrder, new_status: str, shipping_note: str = ""):
    phone = _customer_phone(order)
    if not phone:
        order.customer_notification_status = NotificationStatus.FAILED
        db.commit()
        return "failed", "Customer phone missing."

    labels = {
        "confirmed": "CONFIRMED",
        "dispatched": "DISPATCHED",
        "delivered": "DELIVERED",
        "cancelled": "CANCELLED",
        "pending": "PENDING",
    }
    msg = (
        f"Order #{order.id} update\n"
        f"Status: {labels.get(new_status, new_status.upper())}\n"
        f"Total: ₹{float(order.total_amount or 0):,.0f}"
    )
    if shipping_note:
        msg += f"\nDetails: {shipping_note}"
    msg += "\nThanks for ordering with Jyoti Cards."

    result = send_whatsapp_message(db, phone, msg, "sales_order", order.id)
    order.customer_notification_status = (
        NotificationStatus.SENT if result.status == "sent" else NotificationStatus.FAILED
    )

    if new_status == "confirmed" and result.status == "sent":
        pdf_path = generate_sales_order_pdf(order)
        caption = f"Order #{order.id} receipt"
        doc_result = send_whatsapp_document(
            db, phone, pdf_path, caption, f"SO_{order.id}.pdf", "sales_order", order.id
        )
        if doc_result.status != "sent":
            order.customer_notification_status = NotificationStatus.FAILED

    db.commit()
    return result.status, result.error or ""


def render(db):
    st.markdown("## 👥 Customers")
    st.caption("Manage customers and view WhatsApp/portal orders")

    customers = list_customers(db)
    tabs = st.tabs(["All Customers", "Add Customer", "Customer Orders"])

    with tabs[0]:
        if not customers:
            st.info("No customers yet.")
        else:
            rows = []
            for c in customers:
                rows.append(
                    {
                        "Name": c.name,
                        "Phone": c.phone or "—",
                        "WhatsApp": c.whatsapp_phone or "—",
                        "Type": c.customer_type or "—",
                        "Payment": c.payment_mode or "—",
                        "Outstanding ₹": f"{float(c.outstanding_balance or 0):,.0f}",
                    }
                )
            st.dataframe(rows, use_container_width=True, hide_index=True)

            cmap = {f"{c.name} ({c.whatsapp_phone or c.phone or 'no-phone'})": c for c in customers}
            selected = st.selectbox("Edit customer", list(cmap.keys()), label_visibility="collapsed")
            customer = cmap[selected]

            with st.form("edit_customer"):
                c1, c2 = st.columns(2)
                name = c1.text_input("Name", customer.name or "")
                phone = c2.text_input("Phone", customer.phone or "")
                c3, c4 = st.columns(2)
                whatsapp_phone = c3.text_input("WhatsApp Phone", customer.whatsapp_phone or "")
                customer_type = c4.text_input("Customer Type", customer.customer_type or "retailer")
                c5, c6 = st.columns(2)
                payment_mode = c5.text_input("Payment Mode", customer.payment_mode or "credit")
                credit_limit = c6.number_input("Credit Limit", min_value=0.0, value=float(customer.credit_limit or 0))
                notes = st.text_area("Address / Notes", customer.address or "", height=70)

                b1, b2, _ = st.columns([1, 1, 3])
                if b1.form_submit_button("Save", use_container_width=True):
                    update_customer(
                        db,
                        customer.id,
                        name=name,
                        phone=phone,
                        whatsapp_phone=whatsapp_phone,
                        customer_type=customer_type,
                        payment_mode=payment_mode,
                        credit_limit=credit_limit,
                        address=notes,
                    )
                    st.rerun()
                if b2.form_submit_button("Delete", use_container_width=True):
                    delete_customer(db, customer.id)
                    st.rerun()

    with tabs[1]:
        with st.form("add_customer"):
            c1, c2 = st.columns(2)
            name = c1.text_input("Name")
            phone = c2.text_input("Phone")
            c3, c4 = st.columns(2)
            whatsapp_phone = c3.text_input("WhatsApp Phone")
            customer_type = c4.text_input("Customer Type", value="retailer")
            c5, c6 = st.columns(2)
            payment_mode = c5.text_input("Payment Mode", value="credit")
            credit_limit = c6.number_input("Credit Limit", min_value=0.0, value=0.0)
            address = st.text_area("Address / Notes", height=70)
            if st.form_submit_button("Add Customer", use_container_width=True):
                if not name:
                    st.error("Name is required")
                elif not (phone or whatsapp_phone):
                    st.error("Phone or WhatsApp number is required")
                else:
                    new_customer = create_customer(
                        db,
                        name=name,
                        phone=phone,
                        whatsapp_phone=whatsapp_phone,
                        customer_type=customer_type,
                        payment_mode=payment_mode,
                        credit_limit=credit_limit,
                        address=address,
                        notifications_enabled=True,
                    )
                    template_name = customer_welcome_template()
                    if template_name:
                        result = send_whatsapp_template(
                            db,
                            new_customer.whatsapp_phone or new_customer.phone,
                            template_name,
                            related_type="customer_onboarding",
                            related_id=new_customer.id,
                        )
                        if result.status == "sent":
                            st.success("Customer added and welcome template sent.")
                        else:
                            st.warning(f"Customer added, but template send failed: {result.error or result.status}")
                    else:
                        st.success("Customer added.")
                    st.rerun()

    with tabs[2]:
        all_orders = db.query(SalesOrder).order_by(SalesOrder.created_at.desc()).limit(300).all()
        if not all_orders:
            st.info("No customer orders yet.")
            return

        st.markdown("#### Filters")
        f1, f2, f3 = st.columns(3)
        status_options = ["All"] + sorted(
            list(
                {
                    (_status_value(so.status) or "pending").replace("_", " ").title()
                    for so in all_orders
                }
            )
        )
        customer_options = ["All"] + sorted(
            list({so.customer.name for so in all_orders if so.customer})
        )
        status_filter = f1.selectbox("Status", status_options, key="so_status_filter")
        customer_filter = f2.selectbox("Customer", customer_options, key="so_customer_filter")
        id_filter = f3.text_input("Order ID", value="", key="so_id_filter", placeholder="e.g. 7")

        filtered_orders = all_orders
        if status_filter != "All":
            filtered_orders = [
                so
                for so in filtered_orders
                if (_status_value(so.status).replace("_", " ").title() == status_filter)
            ]
        if customer_filter != "All":
            filtered_orders = [
                so
                for so in filtered_orders
                if so.customer and so.customer.name == customer_filter
            ]
        if id_filter.strip():
            filtered_orders = [
                so
                for so in filtered_orders
                if id_filter.strip() in str(so.id)
            ]

        if not filtered_orders:
            st.warning("No orders found for selected filters.")
            return

        table_rows = []
        for so in filtered_orders:
            cname = so.customer.name if so.customer else "—"
            items_count = len(so.items or [])
            table_rows.append(
                {
                    "Order #": so.id,
                    "Customer": cname,
                    "Status": (so.status.value if hasattr(so.status, "value") else str(so.status)).upper(),
                    "Channel": so.channel or "—",
                    "Items": items_count,
                    "Total ₹": f"{float(so.total_amount or 0):,.0f}",
                    "Date": str(so.order_date),
                }
            )
        st.dataframe(table_rows, use_container_width=True, hide_index=True)

        pick = st.selectbox("Select order", [o.id for o in filtered_orders], key="cust_order_pick")
        order = next(o for o in filtered_orders if o.id == pick)
        st.markdown(f"### Order #{order.id}")
        st.caption(
            f"Customer: {order.customer.name if order.customer else '—'}  |  "
            f"Status: {_status_value(order.status).replace('_', ' ').title()}  |  "
            f"Total: ₹{float(order.total_amount or 0):,.0f}"
        )

        st.markdown("#### 1) Review Incoming Order")
        item_rows = []
        for item in order.items:
            image_exists = bool(item.product and item.product.image_path and os.path.isfile(item.product.image_path))
            item_rows.append(
                {
                    "Line ID": item.id,
                    "SKU": item.product.sku if item.product else "—",
                    "Item": item.product.name if item.product else "—",
                    "Qty": f"{float(item.quantity):g}",
                    "Rate ₹": f"{float(item.unit_price):,.0f}",
                    "Amount ₹": f"{float(item.total_price):,.0f}",
                    "Image": "Yes" if image_exists else "No",
                }
            )
        st.dataframe(item_rows, use_container_width=True, hide_index=True)
        st.markdown("---")
        st.markdown("#### 2) Edit Draft Order")
        with st.form(f"edit_so_{order.id}"):
            st.caption("Update quantities/rates and optionally add one more item line.")
            edit_payload = []
            for item in order.items:
                c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
                c1.text_input(
                    "Item",
                    value=f"{item.product.sku if item.product else '—'} — {item.product.name if item.product else '—'}",
                    disabled=True,
                    key=f"so_item_lbl_{order.id}_{item.id}",
                )
                qty = c2.number_input(
                    "Qty",
                    min_value=0.0,
                    value=float(item.quantity or 0),
                    key=f"so_item_qty_{order.id}_{item.id}",
                )
                rate = c3.number_input(
                    "Rate ₹",
                    min_value=0.0,
                    value=float(item.unit_price or 0),
                    key=f"so_item_rate_{order.id}_{item.id}",
                )
                remove = c4.checkbox("Remove", key=f"so_item_rm_{order.id}_{item.id}")
                edit_payload.append((item.id, qty, rate, remove))

            st.markdown("##### Add New Line (optional)")
            products = db.query(Product).filter(Product.active.is_(True)).order_by(Product.name).all()
            pmap = {f"{p.sku} — {p.name}": p for p in products}
            sel = st.selectbox("Product", ["— No New Line —"] + list(pmap.keys()), key=f"so_add_sel_{order.id}")
            ac1, ac2 = st.columns(2)
            add_qty = ac1.number_input("New Qty", min_value=0.0, value=0.0, key=f"so_add_qty_{order.id}")
            add_rate = ac2.number_input("New Rate ₹", min_value=0.0, value=0.0, key=f"so_add_rate_{order.id}")

            if st.form_submit_button("Save Item Changes", use_container_width=True):
                for item in list(order.items):
                    payload = next((p for p in edit_payload if p[0] == item.id), None)
                    if not payload:
                        continue
                    _, qty, rate, remove = payload
                    if remove or qty <= 0:
                        db.delete(item)
                        continue
                    item.quantity = qty
                    item.unit_price = rate

                if sel != "— No New Line —" and add_qty > 0:
                    product = pmap[sel]
                    unit_rate = add_rate if add_rate > 0 else float(product.selling_price or 0)
                    db.add(
                        SalesOrderItem(
                            order_id=order.id,
                            product_id=product.id,
                            quantity=add_qty,
                            unit_price=unit_rate,
                            discount_percent=0,
                            total_price=float(add_qty) * float(unit_rate),
                        )
                    )
                db.flush()
                _recalculate_order_totals(order)
                db.commit()
                st.success("Order items updated.")
                st.rerun()

        st.markdown("---")
        st.markdown("#### 3) Confirm Order")
        current_order_status = _status_value(order.status).lower()
        can_confirm = current_order_status in {"pending", "confirmed"}
        c1, c2 = st.columns([1, 1])
        if c1.button("Generate Order PDF", key=f"so_pdf_{order.id}", use_container_width=True):
            pdf_path = generate_sales_order_pdf(order)
            st.success(f"PDF generated: {pdf_path}")
        if not can_confirm:
            st.info("Order already moved beyond confirmation. Use update section below.")
        if c2.button(
            "Confirm Order + Send Customer Update",
            key=f"so_confirm_{order.id}",
            use_container_width=True,
            disabled=not can_confirm,
        ):
            order.status = SalesStatus.CONFIRMED
            db.commit()
            db.refresh(order)
            send_status, send_error = _send_customer_status_update(db, order, "confirmed", "Order confirmed by Jyoti Cards")
            if send_status == "sent":
                st.success(f"Order #{order.id} confirmed and receipt sent to customer.")
            else:
                st.warning(f"Order confirmed, but WhatsApp send status: {send_status}. {send_error}")
            st.rerun()

        st.markdown("---")
        st.markdown("#### 4) Dispatch / Delivery Updates")
        status_map = {
            "pending": SalesStatus.PENDING,
            "confirmed": SalesStatus.CONFIRMED,
            "dispatched": SalesStatus.DISPATCHED,
            "delivered": SalesStatus.DELIVERED,
            "cancelled": SalesStatus.CANCELLED,
        }
        current_status = _status_value(order.status).lower()
        options = list(status_map.keys())
        default_idx = options.index(current_status) if current_status in options else 0
        new_status = st.selectbox("New Status", options, index=default_idx, key=f"so_status_{order.id}")
        shipping_note = st.text_area(
            "Dispatch / Tracking / Notes",
            value="",
            height=80,
            key=f"so_note_{order.id}",
            placeholder="e.g. DTDC, AWB12345, expected delivery tomorrow",
        )
        if st.button("Save Status + Send WhatsApp Update", key=f"so_update_{order.id}", use_container_width=True):
            order.status = status_map[new_status]
            order.notes = _append_note(order.notes, shipping_note)
            db.commit()
            db.refresh(order)
            send_status, send_error = _send_customer_status_update(db, order, new_status, shipping_note)
            if send_status == "sent":
                st.success(f"Order #{order.id} updated and customer notified on WhatsApp.")
            else:
                st.warning(f"Order #{order.id} updated, but WhatsApp send status: {send_status}. {send_error}")
            st.rerun()
