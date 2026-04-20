from datetime import date

import streamlit as st

from services.purchases import (
    build_po_version_seed,
    create_purchase_order,
    create_purchase_order_version,
    get_purchase_order,
    get_vendor_offerings_for_po,
    list_purchase_order_versions,
    list_purchase_orders,
)
from services.vendors import list_vendors


def _label(offering):
    return f"{offering.product.sku} — {offering.product.name}"


def _status_display(val: str) -> str:
    return val.replace("_", " ").title()


def render(db):
    st.markdown("## 📝 Purchase Orders")
    st.caption("Create and manage orders with your vendors")

    if "po_flash" in st.session_state:
        flash = st.session_state.pop("po_flash")
        level = flash.get("level", "success")
        text = flash.get("text", "")
        if level == "warning":
            st.warning(text)
        elif level == "error":
            st.error(text)
        else:
            st.success(text)

    tabs = st.tabs(["📋 All Orders", "➕ Create Order", "🔄 New Version"])

    # ══════════════════════════════════════════════════════════════════════════
    #  TAB 1 — order list + detail
    # ══════════════════════════════════════════════════════════════════════════
    with tabs[0]:
        pos = list_purchase_orders(db, latest_only=True)
        if not pos:
            st.info("No purchase orders yet. Create one from the next tab.")
            return

        # ── filters ───────────────────────────────────────────────────────────
        vendor_names = sorted({po.vendor.firm_name or po.vendor.name for po in pos})
        status_vals = sorted({po.status.value for po in pos})

        fc1, fc2, fc3 = st.columns([2, 2, 1])
        v_filter = fc1.selectbox("Vendor", ["All Vendors"] + vendor_names, key="po_vf")
        s_filter = fc2.selectbox("Status", ["All Statuses"] + [_status_display(s) for s in status_vals], key="po_sf")

        filtered = pos
        if v_filter != "All Vendors":
            filtered = [po for po in filtered if (po.vendor.firm_name or po.vendor.name) == v_filter]
        if s_filter != "All Statuses":
            filtered = [po for po in filtered if _status_display(po.status.value) == s_filter]

        if not filtered:
            st.warning("No orders match these filters.")
            return

        # ── order table ───────────────────────────────────────────────────────
        rows = []
        for po in filtered:
            rows.append({
                "PO #": po.id,
                "Vendor": po.vendor.firm_name or po.vendor.name,
                "Items": len(po.items),
                "Value ₹": f"{po.final_amount:,.0f}",
                "Status": _status_display(po.status.value),
                "Version": f"v{po.version_number}",
                "Date": str(po.order_date),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

        # ── detail view ───────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 🔍 Order Details")
        po_id = st.selectbox(
            "Select order",
            [po.id for po in filtered],
            format_func=lambda x: f"PO #{x} — {next((po.vendor.firm_name or po.vendor.name) for po in filtered if po.id == x)}",
            key="po_detail",
            label_visibility="collapsed",
        )
        po = get_purchase_order(db, po_id)
        if not po:
            return

        # ── summary metrics ───────────────────────────────────────────────────
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Vendor", po.vendor.firm_name or po.vendor.name)
        m2.metric("Status", _status_display(po.status.value))
        m3.metric("Order Value", f"₹ {po.final_amount:,.0f}")
        m4.metric("Version", f"v{po.version_number}")

        # ── items + summary side by side ──────────────────────────────────────
        col_items, col_info = st.columns([3, 2])

        with col_items:
            st.markdown("**Order Items**")
            item_rows = []
            for item in po.items:
                item_rows.append({
                    "Our ID": item.our_product_code or item.product.sku,
                    "Item": item.product.name,
                    "Qty": f"{item.quantity_ordered:g}",
                    "Received": f"{item.quantity_received:g}",
                    "Base ₹": f"{item.base_unit_price:,.0f}",
                    "Bill %": f"{item.billing_percent:g}%",
                    "PO Rate ₹": f"{item.unit_price:,.0f}",
                    "Total ₹": f"{item.total_price:,.0f}",
                })
            st.dataframe(item_rows, use_container_width=True, hide_index=True)

        with col_info:
            st.markdown("**Order Info**")
            info = {
                "Order Date": str(po.order_date or "—"),
                "Expected": str(po.expected_date or "—"),
                "Vendor Committed": str(po.vendor_committed_date or "—"),
                "Shipment": po.shipment_mode or "—",
                "Transport": po.transport_name or "—",
                "Transport Ph": po.transport_contact or "—",
                "Billing": po.vendor.billing_condition or "100%",
                "Vendor WhatsApp": (po.vendor_notification_status.value if hasattr(po.vendor_notification_status, "value") else str(po.vendor_notification_status or "—")).upper(),
                "Internal WhatsApp": (po.internal_notification_status.value if hasattr(po.internal_notification_status, "value") else str(po.internal_notification_status or "—")).upper(),
            }
            for label, val in info.items():
                st.markdown(f"**{label}:** {val}")
            if po.notes:
                st.markdown("**Notes:**")
                st.code(po.notes, language=None)
            if po.close_note:
                st.markdown("**Close Note:**")
                st.code(po.close_note, language=None)

        # ── version history ───────────────────────────────────────────────────
        versions = list_purchase_order_versions(db, po.id)
        if len(versions) > 1:
            st.markdown("---")
            st.markdown("#### 📜 Version History")
            ver_rows = []
            for v in versions:
                ver_rows.append({
                    "PO #": v.id,
                    "Version": f"v{v.version_number}",
                    "Status": _status_display(v.status.value),
                    "Value ₹": f"{v.final_amount:,.0f}",
                    "Created": v.created_at.strftime("%d %b %Y, %I:%M %p"),
                    "Current": "✓" if v.is_latest else "",
                })
            st.dataframe(ver_rows, use_container_width=True, hide_index=True)

            old_versions = [v for v in versions if not v.is_latest]
            if old_versions:
                snap_id = st.selectbox(
                    "View older version",
                    [v.id for v in old_versions],
                    format_func=lambda x: f"PO #{x} — v{next(v.version_number for v in old_versions if v.id == x)}",
                    key="po_snap",
                )
                snap = get_purchase_order(db, snap_id)
                if snap:
                    with st.expander(f"Version v{snap.version_number} — ₹ {snap.final_amount:,.0f}", expanded=False):
                        snap_rows = [{
                            "Our ID": i.our_product_code or i.product.sku,
                            "Item": i.product.name,
                            "Qty": f"{i.quantity_ordered:g}",
                            "Rate ₹": f"{i.unit_price:,.0f}",
                            "Total ₹": f"{i.total_price:,.0f}",
                        } for i in snap.items]
                        st.dataframe(snap_rows, use_container_width=True, hide_index=True)

    # ══════════════════════════════════════════════════════════════════════════
    #  TAB 2 — create PO
    # ══════════════════════════════════════════════════════════════════════════
    with tabs[1]:
        vendors = list_vendors(db)
        if not vendors:
            st.warning("Add vendors first before creating orders.")
            return

        vmap = {(v.firm_name or v.name): v for v in vendors}
        vendor_label = st.selectbox("Select Vendor", list(vmap.keys()), key="po_c_vendor")
        vendor = vmap[vendor_label]

        offerings = get_vendor_offerings_for_po(db, vendor.id)
        if not offerings:
            st.warning(f"No items mapped to **{vendor_label}**. Go to Items page and link items to this vendor first.")
            return

        offering_map = {o.id: o for o in offerings}
        o_ids = list(offering_map.keys())

        st.markdown('<div class="section-label">ORDER DETAILS</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        order_date = c1.date_input("Order Date", date.today(), key="po_c_od")
        expected_date = c2.date_input("Expected Date", date.today(), key="po_c_ed")
        committed_date = c3.date_input("Vendor Committed", date.today(), key="po_c_cd")

        c4, c5, c6 = st.columns(3)
        shipment_mode = c4.text_input("Shipment", vendor.default_shipment_mode or "", key="po_c_ship")
        transport_name = c5.text_input("Transport", vendor.transporter_name or "", key="po_c_trans")
        transport_contact = c6.text_input("Transport Ph", vendor.transporter_contact or "", key="po_c_tph")
        notes = st.text_area("Notes", key="po_c_notes", height=60)

        st.markdown('<div class="section-label">ADD ITEMS</div>', unsafe_allow_html=True)
        count = st.number_input("Number of items", min_value=1, max_value=30, value=1, key="po_c_count")
        custom_pricing = st.checkbox("Override mapped price/billing for this PO", value=False, key="po_c_override")

        items = []
        for idx in range(int(count)):
            cols = st.columns([4, 1, 1, 1])
            oid = cols[0].selectbox("Item", o_ids, format_func=lambda x: _label(offering_map[x]), key=f"po_c_o_{idx}")
            o = offering_map[oid]
            qty = cols[1].number_input("Qty", min_value=1.0, value=1.0, key=f"po_c_q_{idx}")
            price = cols[2].number_input(
                "Price ₹",
                min_value=0.0,
                value=float(o.vendor_price or 0),
                key=f"po_c_p_{idx}",
                disabled=not custom_pricing,
            )
            bill = cols[3].number_input(
                "Bill %",
                min_value=0.0,
                value=float(o.billing_percent or 100),
                key=f"po_c_b_{idx}",
                disabled=not custom_pricing,
            )
            items.append({
                "product_id": o.product_id,
                "vendor_offering_id": o.id,
                "vendor_product_code": o.vendor_product_code,
                "quantity": qty,
                "base_unit_price": price,
                "billing_percent": bill,
            })

        st.markdown("")
        if st.button("📝 Create Order", use_container_width=True, key="po_c_btn"):
            po = create_purchase_order(
                db, vendor.id, items,
                order_date=order_date, expected_date=expected_date,
                vendor_committed_date=committed_date, shipment_mode=shipment_mode,
                transport_name=transport_name, transport_contact=transport_contact, notes=notes,
            )
            vendor_status = (po.vendor_notification_status.value if hasattr(po.vendor_notification_status, "value") else str(po.vendor_notification_status or "")).lower()
            if vendor_status == "sent":
                st.session_state["po_flash"] = {
                    "level": "success",
                    "text": f"PO #{po.id} created — ₹ {po.final_amount:,.0f}. Vendor WhatsApp sent.",
                }
            else:
                st.session_state["po_flash"] = {
                    "level": "warning",
                    "text": f"PO #{po.id} created — ₹ {po.final_amount:,.0f}. Vendor WhatsApp status: {vendor_status or 'unknown'}.",
                }
            st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    #  TAB 3 — new version
    # ══════════════════════════════════════════════════════════════════════════
    with tabs[2]:
        all_pos = list_purchase_orders(db, latest_only=True)
        if not all_pos:
            st.info("No orders to create versions of.")
            return

        base_po = get_purchase_order(
            db,
            st.selectbox(
                "Base Order",
                [p.id for p in all_pos],
                format_func=lambda x: f"PO #{x} — {next((po.vendor.firm_name or po.vendor.name) for po in all_pos if po.id == x)}",
                key="po_v_base",
            ),
        )
        seed_items = build_po_version_seed(base_po)
        offerings = get_vendor_offerings_for_po(db, base_po.vendor_id)
        if not offerings:
            st.warning("No vendor items mapped for this vendor.")
            return

        offering_map = {o.id: o for o in offerings}
        o_ids = list(offering_map.keys())

        st.caption(f"Creating new version of PO #{base_po.id} (currently v{base_po.version_number})")

        st.markdown('<div class="section-label">ORDER DETAILS</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        order_date = c1.date_input("Order Date", date.today(), key="po_v_od")
        expected_date = c2.date_input("Expected Date", date.today(), key="po_v_ed")
        committed_date = c3.date_input("Vendor Committed", date.today(), key="po_v_cd")

        c4, c5, c6 = st.columns(3)
        shipment_mode = c4.text_input("Shipment", base_po.shipment_mode or "", key="po_v_ship")
        transport_name = c5.text_input("Transport", base_po.transport_name or "", key="po_v_trans")
        transport_contact = c6.text_input("Transport Ph", base_po.transport_contact or "", key="po_v_tph")
        notes = st.text_area("Version Notes", value=base_po.notes or "", key="po_v_notes", height=60)

        st.markdown('<div class="section-label">ITEMS (edit as needed)</div>', unsafe_allow_html=True)
        count = st.number_input("Items", min_value=max(1, len(seed_items)), max_value=30, value=max(1, len(seed_items)), key="po_v_count")
        custom_pricing = st.checkbox("Override mapped price/billing for this version", value=True, key="po_v_override")

        items = []
        for idx in range(int(count)):
            cols = st.columns([4, 1, 1, 1])
            seed = seed_items[idx] if idx < len(seed_items) else None
            default_oid = o_ids[0]
            if seed and seed.get("vendor_offering_id") in offering_map:
                default_oid = seed["vendor_offering_id"]
            oid = cols[0].selectbox(
                "Item", o_ids,
                index=o_ids.index(default_oid),
                format_func=lambda x: _label(offering_map[x]),
                key=f"po_v_o_{idx}",
            )
            o = offering_map[oid]
            qty = cols[1].number_input("Qty", min_value=1.0, value=float(seed["quantity"]) if seed else 1.0, key=f"po_v_q_{idx}")
            price = cols[2].number_input(
                "Price ₹",
                min_value=0.0,
                value=float(seed["base_unit_price"]) if seed else float(o.vendor_price or 0),
                key=f"po_v_p_{idx}",
                disabled=not custom_pricing,
            )
            bill = cols[3].number_input(
                "Bill %",
                min_value=0.0,
                value=float(seed["billing_percent"]) if seed else float(o.billing_percent or 100),
                key=f"po_v_b_{idx}",
                disabled=not custom_pricing,
            )
            items.append({
                "product_id": o.product_id,
                "vendor_offering_id": o.id,
                "vendor_product_code": o.vendor_product_code,
                "quantity": qty,
                "base_unit_price": price,
                "billing_percent": bill,
            })

        st.markdown("")
        if st.button("🔄 Create New Version", use_container_width=True, key="po_v_btn"):
            new_po = create_purchase_order_version(
                db, base_po.id, items,
                order_date=order_date, expected_date=expected_date,
                vendor_committed_date=committed_date, shipment_mode=shipment_mode,
                transport_name=transport_name, transport_contact=transport_contact, notes=notes,
            )
            st.session_state["po_flash"] = {
                "level": "success",
                "text": f"PO #{new_po.id} v{new_po.version_number} created — ₹ {new_po.final_amount:,.0f}.",
            }
            st.rerun()
