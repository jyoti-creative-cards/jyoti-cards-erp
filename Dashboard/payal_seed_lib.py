"""Shared Payal demo seed (customer → vendor → PO → order → bills → AR/AP → doc 3-way).
Used by ``e2e_payal_complete_flow.py`` (isolated SQLite) and ``seed_payal_live.py`` (your ``.env``)."""
from __future__ import annotations

import os
import re
import sys
from datetime import date

import db
from bill_pdf import build_billing_pdfs_for_co_record, build_billing_pdfs_for_record
from gl import AC_CASH, AC_EQUITY, list_gl_accounts, pnl_to_date, post_journal, trial_balance

_MIN_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def norm10(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    return d[-10:] if len(d) >= 10 else d


def seed_cash_opening() -> None:
    post_journal(
        date.today().isoformat(),
        "Opening: cash and equity (Payal seed)",
        "opening",
        None,
        [(AC_CASH, 2_000_000.0, 0.0), (AC_EQUITY, 0.0, 2_000_000.0)],
    )


def assert_gl_balanced() -> None:
    with db._connect() as conn:
        r = conn.execute(
            "SELECT COALESCE(SUM(debit),0) AS s FROM gl_journal_lines"
        ).fetchone()
        r2 = conn.execute(
            "SELECT COALESCE(SUM(credit),0) AS s FROM gl_journal_lines"
        ).fetchone()
    def _val(x: object, key: str = "s") -> float:
        if x is None:
            return 0.0
        if isinstance(x, dict):
            return float(x.get(key, 0) or 0)
        return float(x[key])

    tdr = _val(r)
    tcr = _val(r2)
    assert abs(tdr - tcr) < 0.1, f"Unbalanced: Dr={tdr} Cr={tcr}"


def write_product_png(product_id: int) -> str:
    d = os.path.join(db.UPLOADS_ROOT, db.VP_UPLOAD_SUB, str(product_id))
    os.makedirs(d, exist_ok=True)
    fn = "payal_e2e.png"
    ap = os.path.join(d, fn)
    with open(ap, "wb") as f:
        f.write(_MIN_PNG)
    rel = f"{db.VP_UPLOAD_SUB}/{product_id}/{fn}"
    try:
        import storage_s3 as storage_s3_mod

        if storage_s3_mod.s3_enabled():
            storage_s3_mod.put_bytes(f"products/{product_id}.png", _MIN_PNG, "image/png")
            rel = f"s3:products/{product_id}.png"
    except Exception as ex:
        print("S3 product image (optional):", ex, file=sys.stderr)
    return rel


def upload_dummy_pdfs_s3(poid: int, coid: int, cob_id: int, pob_id: int) -> None:
    try:
        import storage_s3 as storage_s3_mod

        if not storage_s3_mod.s3_enabled():
            print(
                "S3: skipped (set S3_ENDPOINT_URL, S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY in .env)",
                file=sys.stderr,
            )
            return
        pob = db.get_po_billing(pob_id)
        cob = db.get_customer_order_billing(cob_id)
        if pob:
            raw_pdf, _ = build_billing_pdfs_for_record(pob)
            storage_s3_mod.put_vendor_bill_pdf(int(poid), raw_pdf)
        if cob:
            raw_pdf2, _ = build_billing_pdfs_for_co_record(cob)
            storage_s3_mod.put_customer_bill_pdf(int(coid), raw_pdf2)
        storage_s3_mod.put_bytes(
            "e2e_dummy/customer_payment_utr.txt",
            b"UPI TXNID PAYAL-E2E-99887766\nAmt credited\n",
            "text/plain",
        )
        storage_s3_mod.put_bytes(
            "e2e_dummy/vendor_payment_utr.txt",
            b"NEFT REF VENDOR-E2E-44332211\nPaid to supplier\n",
            "text/plain",
        )
        storage_s3_mod.put_bytes(
            "e2e_dummy/freight_receipt.pdf",
            b"%PDF-1.4\n%E2E dummy freight\n%%EOF\n",
            "application/pdf",
        )
        print(
            "S3: uploaded vendor_bills/, customer_bills/, products/, e2e_dummy/ — check bucket `files`."
        )
    except Exception as ex:
        print("S3 uploads failed:", ex, file=sys.stderr)


def find_customer_id_by_phone(phone: str) -> int | None:
    db.init_db()
    want = norm10(phone)
    for c in db.list_customers():
        if norm10(c.phone or "") == want:
            return int(c.id)
    return None


def run_payal_flow(
    *,
    pwd: str = "PayalE2E#99",
    phone: str = "8952839355",
    skip_if_phone_exists: bool = True,
) -> int:
    """Insert full demo graph. WhatsApp runs per ``insert_customer`` / order hooks unless WHATSAPP_DISABLE is set."""
    if skip_if_phone_exists and find_customer_id_by_phone(phone) is not None:
        print(
            f"Skip: customer with phone ending {norm10(phone)} already exists. "
            "Delete that row or pass skip_if_phone_exists=False.",
            file=sys.stderr,
        )
        return 2

    db.init_db()
    seed_cash_opening()
    assert len(list_gl_accounts()) >= 7

    cid = db.insert_customer("Payal", "Payal Home", phone, None, "India", pwd)
    cust = db.get_customer(cid)
    assert cust and db.verify_password(cust.password_hash, pwd)
    assert norm10(phone) == norm10(cust.phone or "")
    wa_note = (os.environ.get("WHATSAPP_DISABLE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    print(
        "OK customer created.",
        "(WhatsApp skipped — WHATSAPP_DISABLE)"
        if wa_note
        else "(WhatsApp welcome sent if Meta env OK)",
    )

    vid = db.insert_vendor(
        "E2E Vendor Person",
        "E2E Vendor Co",
        "9810012345",
        None,
        30,
        100,
        "E2E vendor notes",
        "Our Legal",
        "1 ERP Lane",
        "Mumbai 400001",
        "GSTIN-E2E-1",
        "9100000000",
        "erp@e2e.test",
    )
    pid = db.insert_vendor_product(
        vid,
        "V-E2E-1",
        "PAYAL-SKU-1",
        "Payal Demo Product",
        "Cards",
        80.0,
        None,
        None,
    )
    img_rel = write_product_png(pid)
    db.set_vendor_product_image_paths(pid, [img_rel])
    src = db.product_image_src(img_rel)
    assert src, "product image must resolve"
    print("OK product + image:", img_rel[:72])

    poid = db.insert_purchase_order(
        vid,
        pid,
        20.0,
        80.0,
        30,
        100,
        None,
        None,
        "E2E PO",
        "TransportCo",
        "TR-E2E-1",
    )
    db.insert_stock_receipt(
        int(pid),
        int(poid),
        20.0,
        "SHIP-E2E",
        "GRN-E2E-1",
        118.0,
        "stock for portal",
    )
    assert abs(db.product_on_hand(pid) - 20.0) < 0.001
    hits = db.search_instock_products_prefix("PAYAL", 20)
    assert any(h.get("our_product_id") == "PAYAL-SKU-1" for h in hits)

    coid = db.insert_customer_order(cid, pid, 2.0, unit_price=118.0, notes="E2E order")
    db.list_portal_order_lines_detail()
    db.update_customer_order(coid, status="confirmed")
    db.update_customer_order(
        coid,
        status="shipped",
        delivery_receipt_number="DR-E2E-1",
        delivery_contact="Driver 9900",
    )
    db.update_customer_order(coid, status="delivered")

    cob_id = db.insert_customer_order_billing(coid)
    cob = db.get_customer_order_billing(cob_id)
    assert cob and getattr(cob, "gl_journal_id", None)
    e_co = float(cob.raw_line_total)
    db.insert_ar_payment(cob_id, e_co, "UPI", "UPI-PAYAL-E2E-99887766")

    pob_id = db.insert_po_billing_for_po(poid)
    pob = db.get_po_billing(pob_id)
    assert pob and getattr(pob, "gl_journal_id", None)
    e_po = float(pob.raw_line_total)
    db.insert_ap_payment(pob_id, e_po, "NEFT", "NEFT-VENDOR-E2E-44332211")

    assert_gl_balanced()
    print("P&L (2099-12-31):", pnl_to_date("2099-12-31"))
    upload_dummy_pdfs_s3(poid, coid, cob_id, pob_id)

    pid2 = db.insert_vendor_product(
        vid,
        "V-DOC-2",
        "PAYAL-DOC-2",
        "Doc Match Product",
        "Demo",
        100.0,
        18.0,
        0,
    )
    po_doc_id = db.create_purchase_order_document(
        vid,
        [{"product_id": pid2, "quantity": 5.0, "unit_cost": 100.0}],
        notes="E2E doc PO",
    )
    po_lines = db.list_purchase_order_document_lines(po_doc_id)
    grn_id = db.create_goods_receipt_document(
        po_doc_id,
        [{"po_line_id": po_lines[0]["id"], "quantity": 5.0}],
        vendor_receipt_ref="VR-E2E",
        grn_number="GRN-DOC-E2E",
    )
    vb_id = db.create_vendor_bill_document(
        po_doc_id,
        [{"po_line_id": po_lines[0]["id"], "quantity": 5.0, "unit_cost": 100.0}],
        goods_receipt_id=grn_id,
        vendor_invoice_ref="INV-V-E2E-1",
    )
    vb = db.get_vendor_bill_document(vb_id)
    assert vb and vb.get("match_status") == "matched"
    db.compare_vendor_bill_three_way(vb_id)

    assert_gl_balanced()

    print()
    print("Payal seed OK.")
    print("  Database: PostgreSQL (DATABASE_URL)")
    print(f"  Portal login: {phone} / {pwd}")
    print("  Search SKU: PAYAL")
    return 0
