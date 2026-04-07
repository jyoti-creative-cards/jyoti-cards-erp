import os
from datetime import date

import pandas as pd
import streamlit as st

from db.models import PurchaseOrderStatus
from services.products import list_products
from services.purchases import list_purchase_orders, create_purchase_order, get_purchase_order, update_purchase_order_status, receive_purchase_order, add_vendor_bill, run_three_way_match
from services.vendors import list_vendors

BILL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "vendor_bills")
RECEIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "goods_receipts")
os.makedirs(BILL_DIR, exist_ok=True)
os.makedirs(RECEIPT_DIR, exist_ok=True)


def _save(uploaded, folder):
    if not uploaded:
        return ""
    path = os.path.join(folder, uploaded.name.replace(" ", "_"))
    with open(path, "wb") as f:
        f.write(uploaded.getbuffer())
    return path


def render(db):
    st.header("Purchase Orders")
    tabs = st.tabs(["All POs", "Create PO", "Lifecycle", "Bills And Receipts"])

    with tabs[0]:
        pos = list_purchase_orders(db)
        if pos:
            rows = [{
                "PO#": po.id,
                "Vendor": po.vendor.name,
                "Status": po.status.value,
                "Order Date": po.order_date,
                "Committed": po.vendor_committed_date,
                "Shipment": po.shipment_mode or "",
                "Final ₹": po.final_amount,
                "Vendor Msg": po.vendor_notification_status.value if po.vendor_notification_status else "",
            } for po in pos]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            selected = st.selectbox("PO details", [po.id for po in pos], format_func=lambda x: f"PO#{x}")
            po = get_purchase_order(db, selected)
            if po:
                item_rows = [{"Product": i.product.name, "Qty": i.quantity_ordered, "Received": i.quantity_received, "GST %": i.gst_percent, "Price": i.unit_price} for i in po.items]
                st.dataframe(pd.DataFrame(item_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No purchase orders")

    with tabs[1]:
        vendors = list_vendors(db)
        products = list_products(db, active_only=True)
        if not vendors or not products:
            st.warning("Need vendors and products first")
        else:
            vmap = {f"{v.name} ({v.id})": v for v in vendors}
            pmap = {f"{p.name} ({p.sku})": p for p in products}
            vendor_label = st.selectbox("Vendor", list(vmap.keys()))
            vendor = vmap[vendor_label]
            order_date = st.date_input("Order Date", date.today())
            expected_date = st.date_input("Expected Date", date.today())
            vendor_committed_date = st.date_input("Vendor Committed Date", date.today())
            shipment_mode = st.text_input("Shipment Mode", vendor.default_shipment_mode or "")
            transport_name = st.text_input("Transport Name", vendor.transporter_name or "")
            transport_contact = st.text_input("Transport Contact", vendor.transporter_contact or "")
            notes = st.text_area("Notes")
            count = st.number_input("Items", min_value=1, max_value=20, value=1)
            items = []
            for idx in range(int(count)):
                cols = st.columns([3, 1, 1, 1])
                p_label = cols[0].selectbox("Product", list(pmap.keys()), key=f"po_p_{idx}")
                p = pmap[p_label]
                qty = cols[1].number_input("Qty", min_value=1.0, value=1.0, key=f"po_q_{idx}")
                price = cols[2].number_input("Base Price", min_value=0.0, value=float(p.purchase_price), key=f"po_pr_{idx}")
                gst = cols[3].number_input("GST %", min_value=0.0, value=float(vendor.gst_percent or 0), key=f"po_g_{idx}")
                items.append({"product_id": p.id, "quantity": qty, "unit_price": price, "gst_percent": gst})
            if st.button("Create PO"):
                po = create_purchase_order(db, vendor.id, items, order_date=order_date, expected_date=expected_date, vendor_committed_date=vendor_committed_date, shipment_mode=shipment_mode, transport_name=transport_name, transport_contact=transport_contact, notes=notes)
                st.success(f"PO#{po.id} created and vendor notified")
                st.rerun()

    with tabs[2]:
        pos = list_purchase_orders(db)
        if pos:
            po = get_purchase_order(db, st.selectbox("Select PO", [p.id for p in pos], format_func=lambda x: f"PO#{x}", key="lifecycle_po"))
            status = st.selectbox("New Status", [s.value for s in PurchaseOrderStatus], index=[s.value for s in PurchaseOrderStatus].index(po.status.value))
            loading_date = st.date_input("Loading Date", value=po.loading_date or date.today())
            receiving_date = st.date_input("Receiving Date", value=po.receiving_date or date.today())
            notes = st.text_area("Lifecycle Notes", value=po.notes or "")
            c1, c2, c3 = st.columns(3)
            if c1.button("Update Status"):
                update_purchase_order_status(db, po.id, PurchaseOrderStatus(status), loading_date=loading_date, receiving_date=receiving_date, notes=notes)
                st.rerun()
            if c2.button("Receive Goods"):
                receive_purchase_order(db, po.id, receipt_number=f"GRN-{po.id}")
                st.rerun()
            if c3.button("Run 3-Way Match"):
                run_three_way_match(db, po.id)
                st.rerun()

    with tabs[3]:
        pos = list_purchase_orders(db)
        if pos:
            po = get_purchase_order(db, st.selectbox("PO for uploads", [p.id for p in pos], format_func=lambda x: f"PO#{x}", key="upload_po"))
            bill_file = st.file_uploader("Vendor Bill")
            bill_number = st.text_input("Bill Number")
            bill_date = st.date_input("Bill Date", key="bill_date")
            bill_amount = st.number_input("Bill Amount", min_value=0.0)
            bill_gst = st.number_input("Bill GST", min_value=0.0)
            if st.button("Upload Bill"):
                path = _save(bill_file, BILL_DIR)
                add_vendor_bill(db, po.id, bill_number, bill_date, bill_amount, bill_gst, path)
                st.rerun()
            receipt_file = st.file_uploader("Goods Receipt")
            if st.button("Upload Receipt"):
                path = _save(receipt_file, RECEIPT_DIR)
                receive_purchase_order(db, po.id, receipt_number=f"GRN-{po.id}", receipt_file_path=path)
                st.rerun()
