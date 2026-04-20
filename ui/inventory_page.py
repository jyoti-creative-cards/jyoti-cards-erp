import streamlit as st

from services.inventory import get_stock, get_low_stock, get_transactions
from services.products import list_products


def render(db):
    st.markdown("## 📊 Inventory")
    st.caption("Live stock levels across all your items")

    tabs = st.tabs(["📦 Current Stock", "⚠️ Low Stock", "📜 History"])

    # ── current stock ─────────────────────────────────────────────────────────
    with tabs[0]:
        stock_data = get_stock(db)
        if not stock_data:
            st.info("No stock data yet. Receive goods against a purchase order to see stock here.")
            return

        rows = []
        total_items = 0
        total_qty = 0
        for inv, prod in stock_data:
            vendor_name = ""
            if prod.vendor:
                vendor_name = prod.vendor.firm_name or prod.vendor.name
            rows.append({
                "Our ID": prod.sku,
                "Item": prod.name,
                "Available": f"{inv.quantity_available:g}",
                "Reserved": f"{inv.quantity_reserved:g}",
                "Vendor": vendor_name or "—",
            })
            total_items += 1
            total_qty += inv.quantity_available

        mc1, mc2 = st.columns(2)
        mc1.metric("Total Items in Stock", total_items)
        mc2.metric("Total Quantity", f"{total_qty:,.0f}")
        st.dataframe(rows, use_container_width=True, hide_index=True)

    # ── low stock ─────────────────────────────────────────────────────────────
    with tabs[1]:
        low = get_low_stock(db)
        if not low:
            st.success("All items are well stocked. No alerts.")
            return

        st.warning(f"{len(low)} item(s) below minimum stock level")
        for inv, prod in low:
            pct = (inv.quantity_available / prod.min_stock_level * 100) if prod.min_stock_level else 100
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{prod.sku}** — {prod.name}")
                st.progress(min(pct / 100, 1.0))
            with col2:
                st.metric("Available", f"{inv.quantity_available:g}", delta=f"{inv.quantity_available - prod.min_stock_level:g} from min")

    # ── transaction history ───────────────────────────────────────────────────
    with tabs[2]:
        products = list_products(db)
        opts = {"All Items": None}
        opts.update({f"{p.sku} — {p.name}": p.id for p in products})
        selected = st.selectbox("Filter by item", list(opts.keys()), key="inv_filter")

        txns = get_transactions(db, product_id=opts[selected])
        if not txns:
            st.info("No transactions yet.")
            return

        rows = []
        for t in txns:
            rows.append({
                "Date": t.created_at.strftime("%d %b %Y, %I:%M %p") if t.created_at else "—",
                "Our ID": t.product.sku,
                "Item": t.product.name,
                "Type": t.txn_type.value.replace("_", " ").title(),
                "Qty": f"{t.quantity:+g}",
                "Ref": f"{t.reference_type} #{t.reference_id}" if t.reference_type else "—",
                "Notes": t.notes or "—",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
