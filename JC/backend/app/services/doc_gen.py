from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.customer import Customer
from app.models.debit_note import DebitNote
from app.models.customer_bill import CustomerBill
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.stock import StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.models.vendor_order import VendorOrderLine, VendorOrderPlacement
from app.services.biz_date import bill_invoice_date
from app.services.catalog_addons import addon_snapshots_for_product, attach_addons_to_totals
from app.services.customer_bill_pdf import render_customer_bill_pdf
from app.services.pdf_documents import render_customer_order_pdf, render_vendor_placement_pdf, render_vendor_receipt_pdf
from app.services.storage import (
    customer_bill_key,
    customer_folder_slug,
    customer_order_key,
    presigned_urls,
    upload_bytes,
    vendor_folder_slug,
    vendor_order_key,
    vendor_receipt_key,
)


def _customer_ctx(db: Session, customer_id: int) -> tuple[Customer, str | None]:
    c = db.get(Customer, customer_id)
    if not c:
        raise ValueError("customer not found")
    city_name = None
    if c.city_id:
        city = db.get(City, c.city_id)
        city_name = city.name if city else None
    return c, city_name


def generate_customer_order_document(db: Session, placement_id: int) -> str | None:
    placement = db.get(CustomerOrderPlacement, placement_id)
    if not placement:
        return None
    lines = db.query(CustomerOrderLine).filter(CustomerOrderLine.placement_id == placement.id).all()
    if not lines:
        return None
    order = db.get(CustomerOrder, placement.customer_order_id)
    if not order:
        return None
    customer_id = order.customer_id
    customer, city_name = _customer_ctx(db, customer_id)
    slug = customer_folder_slug(customer.business_name)
    pdf_lines = []
    image_urls: dict[int, str | None] = {}
    for ln in lines:
        prod = db.get(CatalogProduct, ln.catalog_product_id)
        addons = ln.addons_json or addon_snapshots_for_product(db, ln.catalog_product_id)
        urls = presigned_urls(prod.image_keys or []) if prod else []
        image_urls[ln.catalog_product_id] = urls[0] if urls else None
        unit = float(ln.unit_price)
        pdf_lines.append({
            "catalog_product_id": ln.catalog_product_id,
            "our_product_id": ln.our_product_id,
            # Customer-facing doc — never show the vendor's internal product code.
            "name": ln.our_product_id,
            "quantity": ln.quantity,
            "unit_price": format(ln.unit_price, "f"),
            "line_total": format(Decimal(str(unit)) * ln.quantity, "f"),
            "addons": addons,
        })
    from app.services.ar_ledger import customer_ar_totals

    ar = customer_ar_totals(db, customer_id)
    outstanding = float(ar["outstanding"])
    pdf = render_customer_order_pdf(
        placement_id=placement.id,
        customer_name=customer.business_name,
        customer_phone=customer.phone,
        customer_address=customer.address,
        customer_city=city_name,
        lines=pdf_lines,
        image_urls=image_urls,
        customer_notes=placement.customer_notes,
        placed_at=placement.placed_at,
        outstanding=outstanding,
    )
    key = customer_order_key(slug, placement.id)
    upload_bytes(key, pdf, "application/pdf")
    placement.document_key = key
    db.add(placement)
    db.flush()
    return key


def generate_customer_bill_document(db: Session, bill_id: int) -> str | None:
    bill = db.get(CustomerBill, bill_id)
    if not bill:
        return None
    customer, city_name = _customer_ctx(db, bill.customer_id)
    slug = customer_folder_slug(customer.business_name)
    from app.models.customer_bill import CustomerBillLine
    from app.services.customer_bill_math import prepare_totals_for_pdf
    from sqlalchemy.orm.attributes import flag_modified

    totals = attach_addons_to_totals(db, dict(bill.totals_json or {}))
    blines = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id).all()
    line_pcts = {
        int(ln.catalog_product_id): ln.discount_percent
        for ln in blines
        if ln.discount_percent is not None
    }
    totals = prepare_totals_for_pdf(
        totals,
        overall_percent=bill.discount_percent,
        line_percent_by_cid=line_pcts or None,
    )
    from app.models.freight_agent import FreightAgent
    from app.services.transport_mode import stamp_transport_on_totals

    mode = bill.transport_mode or ("bus" if bill.freight_agent_id else "self_pickup")
    agent_name = None
    if bill.freight_agent_id:
        agent = db.get(FreightAgent, bill.freight_agent_id)
        agent_name = agent.name if agent else None
    totals = stamp_transport_on_totals(
        totals,
        {
            "transport_mode": mode,
            "transport_receipt_number": bill.transport_receipt_number,
            "freight_agent_id": bill.freight_agent_id,
            "freight_charges": bill.freight_charges,
        },
        agent_name=agent_name,
    )
    bill.totals_json = totals
    flag_modified(bill, "totals_json")
    lines = totals.get("lines") or []
    if not lines:
        return None
    cids = [int(ln.get("catalog_product_id") or 0) for ln in lines if isinstance(ln, dict)]
    image_urls: dict[int, str | None] = {}
    for cid in cids:
        if not cid:
            continue
        prod = db.get(CatalogProduct, cid)
        urls = presigned_urls(prod.image_keys or []) if prod else []
        image_urls[cid] = urls[0] if urls else None
    totals = {**totals, "lines": [dict(ln) for ln in lines if isinstance(ln, dict)]}
    placement = db.get(CustomerOrderPlacement, bill.placement_id) if bill.placement_id else None
    from app.services.ar_ledger import customer_ar_totals

    ar = customer_ar_totals(db, bill.customer_id)
    # Outstanding already includes this bill — shown on the PDF. Credit limit is
    # internal-only and is intentionally not sent to render_customer_bill_pdf.
    outstanding = float(ar["outstanding"])
    pdf = render_customer_bill_pdf(
        bill_id=bill.id,
        order_id=bill.placement_id or bill.id,
        bill_number=bill.bill_number,
        customer_name=customer.business_name,
        customer_company=customer.person_name,
        customer_phone=customer.phone,
        customer_address=customer.address,
        customer_city=city_name,
        totals=totals,
        generated_at=bill.created_at or datetime.now(timezone.utc),
        invoice_date=bill_invoice_date(bill),
        customer_notes=placement.customer_notes if placement else None,
        narration=bill.narration,
        item_image_urls=image_urls,
        order_created_at=placement.placed_at if placement else bill.created_at,
        outstanding=outstanding,
    )
    key = customer_bill_key(slug, bill.bill_number)
    upload_bytes(key, pdf, "application/pdf")
    bill.document_key = key
    db.add(bill)
    db.flush()
    return key


def _vendor_ctx(db: Session, vendor_id: int) -> tuple[Vendor, str | None]:
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        raise ValueError("vendor not found")
    city_name = None
    if vendor.city_id:
        city = db.get(City, vendor.city_id)
        city_name = city.name if city else None
    return vendor, city_name


def generate_vendor_placement_document(db: Session, placement_id: int) -> str | None:
    placement = db.get(VendorOrderPlacement, placement_id)
    if not placement:
        return None
    from app.models.vendor_order import VendorOrder
    order = db.get(VendorOrder, placement.vendor_order_id)
    if not order:
        return None
    vendor, city_name = _vendor_ctx(db, order.vendor_id)
    slug = vendor_folder_slug(vendor.business_name)
    db.flush()  # ensure lines from same request are visible
    vlines = db.query(VendorOrderLine).filter(VendorOrderLine.placement_id == placement.id).all()
    if not vlines:
        return None
    pdf_lines = []
    image_urls: dict[int, str | None] = {}
    for ln in vlines:
        prod = db.get(CatalogProduct, ln.catalog_product_id)
        urls = presigned_urls(prod.image_keys or []) if prod else []
        image_urls[ln.catalog_product_id] = urls[0] if urls else None
        pdf_lines.append({
            "catalog_product_id": ln.catalog_product_id,
            "our_product_id": ln.our_product_id,
            "vendor_product_id": prod.vendor_product_id if prod else "",
            "name": prod.vendor_product_id if prod else ln.our_product_id,
            "quantity": ln.quantity,
            "unit_price": format(ln.buying_price, "f"),
            "line_total": format(Decimal(str(ln.buying_price)) * ln.quantity, "f"),
        })
    pdf = render_vendor_placement_pdf(
        placement_id=placement.id,
        vendor_name=vendor.business_name,
        vendor_phone=vendor.phone,
        vendor_address=vendor.address,
        vendor_city=city_name,
        vendor_gst=vendor.gst_number,
        vendor_person=vendor.person_name,
        lines=pdf_lines,
        image_urls=image_urls,
        placed_by=placement.placed_by_name,
        placed_at=placement.placed_at,
    )
    key = vendor_order_key(slug, placement.id)
    upload_bytes(key, pdf, "application/pdf")
    placement.document_key = key
    db.add(placement)
    db.flush()
    return key


def generate_vendor_receipt_document(db: Session, receipt_id: int) -> str | None:
    receipt = db.get(StockReceipt, receipt_id)
    if not receipt:
        return None
    vendor, city_name = _vendor_ctx(db, receipt.vendor_id)
    slug = vendor_folder_slug(vendor.business_name)
    rlines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).all()
    # Total-only bills store line billed_amount as 0 — don't invent per-line amounts
    total_only = receipt.total_billed_amount is not None and all(
        (ln.billed_amount or Decimal("0")) == 0 for ln in rlines
    )
    pdf_lines = []
    image_urls: dict[int, str | None] = {}
    for ln in rlines:
        prod = db.get(CatalogProduct, ln.catalog_product_id)
        urls = presigned_urls(prod.image_keys or []) if prod else []
        image_urls[ln.catalog_product_id] = urls[0] if urls else None
        if total_only:
            line_amt_str = "—"
        elif ln.billed_amount:
            line_amt_str = format(ln.billed_amount, "f")
        else:
            line_amt_str = format(Decimal(str(ln.buying_price)) * int(ln.quantity_billed or 0), "f")
        pdf_lines.append({
            "catalog_product_id": ln.catalog_product_id,
            "our_product_id": ln.our_product_id,
            "vendor_product_id": prod.vendor_product_id if prod else "",
            "name": prod.vendor_product_id if prod else ln.our_product_id,
            "quantity_received": ln.quantity_received,
            "quantity_billed": ln.quantity_billed,
            "unit_price": format(ln.buying_price, "f"),
            "line_total": line_amt_str,
        })
    from app.services.ap_ledger import receipt_bill_amount, receipt_debit_note_total, debit_note_payable_effect
    bill_amt = receipt_bill_amount(db, receipt.id)
    dn_total = receipt_debit_note_total(db, receipt.id)
    net = (bill_amt + dn_total).quantize(Decimal("0.01"))
    from app.services.debit_notes import infer_direction
    dn_rows = db.query(DebitNote).filter(
        DebitNote.receipt_id == receipt.id, DebitNote.deleted_at.is_(None)
    ).order_by(DebitNote.id.asc()).all()
    debit_notes_out = []
    dir_labels = {
        "short": "Short delivery",
        "extra": "Extra goods",
        "over": "Bill overcharged",
        "under": "Bill undercharged",
    }
    for dn in dn_rows:
        direction = dn.direction or infer_direction(dn.note_type, dn.quantity, dn.amount)
        dir_lbl = dir_labels.get(direction or "", "Adjustment")
        if dn.note_type == "item" and dn.our_product_id:
            label = f"{dir_lbl}: {dn.our_product_id} × {abs(dn.quantity or 0)}"
        else:
            label = f"{dir_lbl}: ₹{abs(dn.amount)}"
        effect = debit_note_payable_effect(dn.amount, dn.note_type)
        debit_notes_out.append({
            "label": label,
            "notes": dn.notes or "",
            "amount": format(effect, "f"),
            "direction": direction,
        })
    total = receipt.total_billed_amount or bill_amt
    extra_cash = None
    if vendor.billing_pct < 100:
        if receipt.actual_ap_amount is not None and total is not None:
            extra_cash = (receipt.actual_ap_amount - total).quantize(Decimal("0.01"))
        elif receipt.expected_extra_cash is not None:
            extra_cash = receipt.expected_extra_cash
    pdf = render_vendor_receipt_pdf(
        receipt_id=receipt.id,
        vendor_name=vendor.business_name,
        vendor_phone=vendor.phone,
        vendor_address=vendor.address,
        vendor_city=city_name,
        vendor_gst=vendor.gst_number,
        vendor_person=vendor.person_name,
        bill_number=receipt.bill_number,
        lines=pdf_lines,
        image_urls=image_urls,
        total_billed=format(total, "f") if total is not None else None,
        debit_notes=debit_notes_out,
        net_payable=format(net, "f"),
        received_by=receipt.received_by_name,
        received_at=receipt.received_at,
        gst_included=vendor.gst_included,
        gst_rate_pct=vendor.gst_rate_pct,
        extra_cash=format(extra_cash, "f") if extra_cash is not None else None,
    )
    key = vendor_receipt_key(slug, receipt.bill_number or f"receipt_{receipt.id}", receipt.id)
    upload_bytes(key, pdf, "application/pdf")
    receipt.receipt_document_key = key
    db.add(receipt)
    db.flush()
    return key
