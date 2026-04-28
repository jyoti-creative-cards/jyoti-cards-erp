import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))
_DASH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Dashboard"))
if _DASH not in sys.path:
    sys.path.insert(0, _DASH)

# Local: same ``DATABASE_URL`` as ERP from ``Dashboard/.env`` (Cloud uses secrets).
_ENV = os.path.join(_DASH, ".env")
try:
    from dotenv import load_dotenv

    load_dotenv(_ENV, override=False)
except ImportError:
    if os.path.isfile(_ENV):
        with open(_ENV, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, rest = line.partition("=")
                k, v = k.strip(), rest.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v

from streamlit_db_env import apply_streamlit_db_env

apply_streamlit_db_env()

from bill_pdf import build_billing_pdfs_for_co_record

from dash_db import get_dashboard_db
from login import try_login
from stock_lookup import image_abs_path

st.set_page_config(page_title="Customer portal", layout="wide")


def _portal_public_url() -> str:
    try:
        return str(
            st.secrets.get(
                "CUSTOMER_PORTAL_PUBLIC_URL", "https://jyoti-cards.streamlit.app"
            )
        ).strip()
    except Exception:
        return os.environ.get(
            "CUSTOMER_PORTAL_PUBLIC_URL", "https://jyoti-cards.streamlit.app"
        ).strip()


if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "customer_name" not in st.session_state:
    st.session_state.customer_name = ""
if "customer_id" not in st.session_state:
    st.session_state.customer_id = None


def _logout() -> None:
    st.session_state.logged_in = False
    st.session_state.customer_name = ""
    st.session_state.customer_id = None
    for k in ("inv_pick", "inv_q", "ord_tab"):
        st.session_state.pop(k, None)


def _status_badge_html(stock_status: str) -> str:
    if stock_status == "in_stock":
        return '<span style="color:#0d7d4d;font-weight:600;">In stock</span>'
    if stock_status == "low_stock":
        return '<span style="color:#b8860b;font-weight:600;">Low stock</span>'
    return '<span style="color:#b22222;font-weight:600;">Out of stock</span>'


if not st.session_state.logged_in:
    _, c, _ = st.columns([1, 1.15, 1])
    with c:
        st.markdown("## Customer ordering")
        pu = _portal_public_url()
        st.markdown(f"[Open customer portal]({pu}) — order status lives here after login.")
        st.caption("Sign in with the mobile number and password your shop set in the Dashboard.")
        with st.form("login_form"):
            phone = st.text_input("Mobile number", placeholder="10-digit mobile")
            password = st.text_input("Password", type="password")
            ok = st.form_submit_button("Log in", type="primary", use_container_width=True)
            if ok:
                good, msg, cid = try_login(phone, password)
                if good:
                    st.session_state.logged_in = True
                    st.session_state.customer_name = msg
                    st.session_state.customer_id = cid
                    st.rerun()
                else:
                    st.error(msg)
else:
    db = get_dashboard_db()
    top_l, top_r = st.columns([3, 1])
    with top_l:
        st.markdown(f"## Hello, **{st.session_state.customer_name}**")
    with top_r:
        st.write("")
        st.write("")
        if st.button("Log out", use_container_width=True):
            _logout()
            st.rerun()

    tab_shop, tab_orders = st.tabs(["Browse & order", "Order status"])
    cid = st.session_state.customer_id

    with tab_shop:
        st.caption("In-stock only. Type in the box — suggestions show in the same panel.")
        with st.container(border=True):
            q = st.text_input(
                "Search",
                placeholder="e.g. 5025",
                key="inv_q",
                label_visibility="collapsed",
            )
            prefix = (q or "").strip()
            matches = db.search_all_products_prefix(prefix, limit=40) if prefix else []
            labels = [f"{m['our_product_id']} — {m['name']}  ({m['stock_status']})" for m in matches]
            sel = None
            if prefix and matches:
                st.caption("Suggestions — click one (includes out-of-stock):")
                pick_i = st.radio(
                    "suggestions",
                    range(len(matches)),
                    format_func=lambda i: labels[i],
                    key=f"inv_pick_{prefix}",
                    label_visibility="collapsed",
                    horizontal=False,
                )
                sel = matches[int(pick_i)]
            elif prefix:
                st.caption("No products match that search.")
        if sel is not None:
            st.markdown("---")
            st.markdown(f"**{sel['name']}**  ·  ID `{sel['our_product_id']}`")
            cat = (sel.get("category") or "").strip() or "—"
            st.markdown(f"**Category:** {cat}")
            st.markdown(_status_badge_html(sel["stock_status"]), unsafe_allow_html=True)
            stock_state = str(sel.get("stock_status") or "")
            oos = stock_state == "out_of_stock" or float(sel.get("on_hand") or 0) <= 0.0001
            show_alts = stock_state in ("out_of_stock", "low_stock")
            if show_alts:
                alts = db.instock_alternative_for_portal(int(sel["id"]), 12)
                if alts:
                    st.markdown("**In-stock alternatives:**")
                    for a in alts:
                        st.caption(
                            f"`{a['our_product_id']}` — {a['name']}  ·  "
                            f"~{a['on_hand']:.1f} on hand  ·  {a.get('stock_status', 'in_stock')}"
                        )
                else:
                    st.caption("No in-stock alternatives are configured right now.")
            rel = sel.get("image_rel")
            ap = image_abs_path(rel) if rel else None
            if ap and (str(ap).startswith("http") or os.path.isfile(ap)):
                st.image(ap, use_container_width=True)
            else:
                st.info("No image on file.")
            with st.form("place_order"):
                qty = st.number_input(
                    "Quantity",
                    min_value=0.001,
                    value=1.0,
                    step=1.0,
                    format="%.3f",
                )
                sub = st.form_submit_button("Place order", type="primary", use_container_width=True)
                if oos:
                    st.caption("This SKU is out of stock — you cannot place an order until it is available.")
                elif stock_state == "low_stock":
                    st.caption("This SKU is low stock. Alternatives shown above are only those currently in stock.")
                if sub and cid and not oos:
                    try:
                        db.insert_customer_order(cid, int(sel["id"]), float(qty))
                        st.success("Order placed. Check **Order status**.")
                    except Exception as e:
                        st.error(str(e)[:400])
                elif sub and oos:
                    pass
                elif sub and not cid:
                    st.error("Session missing customer id. Log out and log in again.")

    with tab_orders:
        if not cid:
            st.error("Session missing customer id. Log out and log in again.")
        else:
            orders = db.list_customer_orders_for_customer(cid)
            if not orders:
                st.info("You have no orders yet.")
            else:
                pmap = {p.id: p for p in db.list_vendor_products()}
                for o in orders:
                    pr = pmap.get(o.product_id)
                    sku = pr.our_product_id if pr else "—"
                    pnm = pr.name if pr else "—"
                    bill = db.get_customer_order_billing_by_order_id(o.id)
                    with st.expander(
                        f"Order **#{o.id}** · **{o.status}** · {sku}",
                        expanded=False,
                    ):
                        st.write("**Product:**", sku, "—", pnm)
                        st.write(
                            "**Quantity:**",
                            o.quantity,
                            "· **Unit price (₹):**",
                            f"{o.unit_price:,.2f}",
                        )
                        st.write("**Notes (from the shop):**", (o.notes or "—").strip() or "—")
                        srows = db.list_customer_order_shipments(int(o.id))
                        if srows:
                            st.write("**Shipments:**")
                            for s in srows:
                                st.caption(
                                    f"  · {s.created_at} — **qty** {s.quantity:g} @ ₹{s.unit_price:,.2f}  "
                                    f"· receipt {s.delivery_receipt_number or '—'}"
                                )
                                rp2 = (s.receipt_image_path or "").strip()
                                if rp2:
                                    pabs3 = image_abs_path(rp2)
                                    if pabs3 and (
                                        str(pabs3).startswith("http") or os.path.isfile(pabs3)
                                    ):
                                        st.image(pabs3, width=280)
                        if bill:
                            st.success("Bill is available — download below.")
                            try:
                                raw_pdf, gst_pdf = build_billing_pdfs_for_co_record(bill)
                                d1, d2 = st.columns(2)
                                with d1:
                                    st.download_button(
                                        "Download raw bill (PDF)",
                                        raw_pdf,
                                        file_name=f"Order{o.id}_raw.pdf",
                                        mime="application/pdf",
                                        key=f"dlr_{o.id}",
                                    )
                                with d2:
                                    st.download_button(
                                        "Download GST bill (PDF)",
                                        gst_pdf,
                                        file_name=f"Order{o.id}_gst.pdf",
                                        mime="application/pdf",
                                        key=f"dlg_{o.id}",
                                    )
                            except Exception as e:
                                st.warning(f"Could not build PDF: {e}")
                        else:
                            st.caption(
                                "Bill downloads appear after the shop generates your invoice."
                            )
