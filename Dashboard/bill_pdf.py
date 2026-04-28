"""Professional PDF bills: raw (full line) and GST (billed portion + tax)."""
from __future__ import annotations

from io import BytesIO
from typing import Any, Mapping, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

def _money(x: float) -> str:
    return f"Rs. {float(x):,.2f}"


def _build_doc(title: str, story: list) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        title=title,
    )
    doc.build(story)
    return buf.getvalue()


def _normalize_seller(seller: Optional[Mapping[str, Any]]) -> dict:
    keys = ("legal_name", "address", "city_pin", "gstin", "phone", "email")
    out = {k: "" for k in keys}
    if seller:
        for k in keys:
            if k in seller and seller[k] is not None:
                out[k] = str(seller[k])
    return out


def _seller_from_billing_row(b) -> dict:
    """Our business block on PDF — from `po_billings` snapshot only."""
    return _normalize_seller(
        {
            "legal_name": getattr(b, "snap_issuer_legal_name", None),
            "address": getattr(b, "snap_issuer_address", None),
            "city_pin": getattr(b, "snap_issuer_city_pin", None),
            "gstin": getattr(b, "snap_issuer_gstin", None),
            "phone": getattr(b, "snap_issuer_phone", None),
            "email": getattr(b, "snap_issuer_email", None),
        }
    )


def _append_our_company_header(story: list, sel: dict, h1, h2, small) -> None:
    ln = (sel.get("legal_name") or "—").replace("&", "&amp;")
    story.append(Paragraph(ln, h1))
    addr = (sel.get("address") or "—").replace("&", "&amp;")
    cp = (sel.get("city_pin") or "").strip()
    if cp:
        addr += f"<br/>{cp.replace('&', '&amp;')}"
    story.append(Paragraph(addr, h2))
    meta = []
    ph = (sel.get("phone") or "").strip()
    em = (sel.get("email") or "").strip()
    gst = (sel.get("gstin") or "").strip()
    if ph:
        meta.append(f"Phone: {ph}")
    if em:
        meta.append(f"Email: {em}")
    if gst:
        meta.append(f"GSTIN: {gst}")
    if meta:
        story.append(Paragraph(" &nbsp;|&nbsp; ".join(meta), small))


def build_multi_line_document_pdf(
    *,
    title: str,
    doc_no: str,
    doc_date: str,
    party_heading: str,
    party_name: str,
    party_company: Optional[str],
    party_phone: Optional[str],
    party_address: Optional[str] = None,
    meta_rows: list[list[str]],
    line_rows: list[dict[str, Any]],
    total_rows: list[list[str]],
    notes: Optional[str] = None,
    seller: Optional[Mapping[str, Any]] = None,
    subtitle: Optional[str] = None,
) -> bytes:
    sel = _normalize_seller(seller)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "H1M",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=8,
        textColor=colors.HexColor("#1a1a2e"),
    )
    h2 = ParagraphStyle(
        "H2M",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#444"),
        spaceAfter=4,
    )
    small = ParagraphStyle(
        "SM",
        parent=styles["Normal"],
        fontSize=8.5,
        textColor=colors.HexColor("#666"),
    )
    story: list = []
    _append_our_company_header(story, sel, h1, h2, small)
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(f"<b>{title.replace('&', '&amp;')}</b>", ParagraphStyle("TM", parent=h1, fontSize=13)))
    if subtitle:
        story.append(Paragraph(subtitle.replace("&", "&amp;"), small))
    story.append(Spacer(1, 0.3 * cm))

    vblock = f"<b>{party_heading.replace('&', '&amp;')}</b><br/>{party_name.replace('&', '&amp;')}"
    if (party_company or "").strip():
        vblock += f"<br/>{(party_company or '').strip().replace('&', '&amp;')}"
    if (party_phone or "").strip():
        vblock += f"<br/>Phone: {(party_phone or '').strip()}"
    if (party_address or "").strip():
        vblock += f"<br/>{(party_address or '').strip().replace('&', '&amp;')}"
    story.append(Paragraph(vblock, h2))
    story.append(Spacer(1, 0.25 * cm))

    info_rows = [["Document no.", doc_no], ["Date", doc_date]] + meta_rows
    t0 = Table(info_rows, colWidths=[4.2 * cm, 11 * cm])
    t0.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, -1), (-1, -1), 0.25, colors.HexColor("#ddd")),
            ]
        )
    )
    story.append(t0)
    story.append(Spacer(1, 0.35 * cm))

    table_data = [["#", "SKU", "Description", "Qty", "Rate", "Base", "GST", "Amount"]]
    for idx, row in enumerate(line_rows, start=1):
        table_data.append(
            [
                str(idx),
                str(row.get("sku") or "—"),
                str(row.get("item_name") or "—").replace("&", "&amp;"),
                f"{float(row.get('quantity') or 0):g}",
                _money(float(row.get("unit_rate") or 0)),
                _money(float(row.get("base_total") or 0)),
                _money(float(row.get("gst_total") or 0)),
                _money(float(row.get("grand_total") or 0)),
            ]
        )
    t1 = Table(
        table_data,
        colWidths=[0.8 * cm, 2.1 * cm, 5.0 * cm, 1.4 * cm, 2.1 * cm, 2.0 * cm, 1.9 * cm, 2.2 * cm],
        repeatRows=1,
    )
    t1.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cdd3df")),
                ("ALIGN", (0, 1), (0, -1), "CENTER"),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(t1)
    story.append(Spacer(1, 0.25 * cm))

    t2 = Table(total_rows, colWidths=[10.7 * cm, 5.3 * cm])
    t2.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, 0), (-1, 0), 0.4, colors.HexColor("#d6dce8")),
            ]
        )
    )
    story.append(t2)
    if (notes or "").strip():
        story.append(Spacer(1, 0.25 * cm))
        story.append(Paragraph(f"<b>Notes:</b> {(notes or '').strip().replace('&', '&amp;')}", small))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("— Authorised signatory —", ParagraphStyle("sigm", parent=small, alignment=1)))
    return _build_doc(doc_no, story)


def build_raw_bill_pdf(
    *,
    doc_no: str,
    doc_date: str,
    po_number: int,
    vendor_name: str,
    vendor_company: Optional[str],
    vendor_phone: Optional[str],
    vendor_address: Optional[str] = None,
    item_sku: str,
    item_title: str,
    quantity: float,
    unit_rate: float,
    line_total: float,
    vendor_invoice_ref: Optional[str],
    notes: Optional[str],
    seller: Optional[Mapping[str, Any]] = None,
    buyer_heading: str = "Vendor (Bill to)",
    order_row_label: str = "Purchase order",
    order_row_value: Optional[str] = None,
    raw_heading: str = "PURCHASE ACKNOWLEDGMENT (FULL VALUE)",
    raw_subcaption: str = "Document without GST break-up — full agreed rate.",
    invoice_row_label: str = "Our reference (vendor inv.)",
) -> bytes:
    sel = _normalize_seller(seller)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "H1",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=8,
        textColor=colors.HexColor("#1a1a2e"),
    )
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#444"),
        spaceAfter=4,
    )
    small = ParagraphStyle(
        "S",
        parent=styles["Normal"],
        fontSize=8.5,
        textColor=colors.HexColor("#666"),
    )
    story: list = []
    _append_our_company_header(story, sel, h1, h2, small)
    story.append(Spacer(1, 0.4 * cm))
    story.append(
        Paragraph(
            f"<b>{raw_heading.replace('&', '&amp;')}</b>",
            ParagraphStyle("T", parent=h1, fontSize=13),
        )
    )
    story.append(Paragraph(raw_subcaption.replace("&", "&amp;"), small))
    story.append(Spacer(1, 0.35 * cm))

    vc = (vendor_company or "").strip()
    bh = (buyer_heading or "Party").replace("&", "&amp;")
    vblock = f"<b>{bh}</b><br/>{vendor_name.replace('&', '&amp;')}"
    if vc:
        vblock += f"<br/>{vc.replace('&', '&amp;')}"
    if vendor_phone:
        vblock += f"<br/>Phone: {vendor_phone}"
    va = (vendor_address or "").strip()
    if va:
        vblock += f"<br/>{va.replace('&', '&amp;')}"
    story.append(Paragraph(vblock, h2))
    story.append(Spacer(1, 0.25 * cm))

    ord_val = (order_row_value or f"PO #{po_number}").strip()
    info_data = [
        ["Document no.", doc_no],
        ["Date", doc_date],
        [order_row_label, ord_val],
        [invoice_row_label, (vendor_invoice_ref or "—").strip() or "—"],
    ]
    t0 = Table(info_data, colWidths=[4.2 * cm, 11 * cm])
    t0.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, -1), (-1, -1), 0.25, colors.HexColor("#ddd")),
            ]
        )
    )
    story.append(t0)
    story.append(Spacer(1, 0.4 * cm))

    line_data = [
        ["Description", "SKU", "Qty", "Unit rate", "Amount"],
        [
            item_title.replace("&", "&amp;"),
            item_sku,
            f"{quantity:g}",
            _money(unit_rate),
            _money(line_total),
        ],
    ]
    t1 = Table(line_data, colWidths=[5.5 * cm, 2.2 * cm, 1.5 * cm, 2.5 * cm, 2.8 * cm])
    t1.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#ccc")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(t1)
    story.append(Spacer(1, 0.25 * cm))
    story.append(
        Paragraph(
            f"<b>Total (full value):</b> {_money(line_total)}",
            ParagraphStyle("Tot", parent=h2, fontSize=11, alignment=2),
        )
    )
    story.append(Spacer(1, 0.35 * cm))
    story.append(
        Paragraph(
            "This document reflects the <b>full unit rate</b> × quantity as agreed. "
            "Tax, if any, is addressed on the companion GST document where applicable.",
            small,
        )
    )
    if (notes or "").strip():
        story.append(Spacer(1, 0.2 * cm))
        story.append(
            Paragraph(f"<b>Notes:</b> {(notes or '').strip().replace('&', '&amp;')}", small)
        )
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("— Authorised signatory —", ParagraphStyle("sig", parent=small, alignment=1)))

    return _build_doc(f"Raw bill {doc_no}", story)


def build_gst_bill_pdf(
    *,
    doc_no: str,
    doc_date: str,
    po_number: int,
    vendor_name: str,
    vendor_company: Optional[str],
    vendor_phone: Optional[str],
    vendor_address: Optional[str] = None,
    item_sku: str,
    item_title: str,
    quantity: float,
    unit_rate: float,
    billing_pct: Optional[int],
    taxable_total: float,
    gst_rate_pct: Optional[float],
    gst_amount: float,
    grand_total: float,
    vendor_invoice_ref: Optional[str],
    notes: Optional[str],
    seller: Optional[Mapping[str, Any]] = None,
    buyer_heading: str = "Vendor (Bill to)",
    order_row_label: str = "Purchase order",
    order_row_value: Optional[str] = None,
    gst_heading: str = "TAX INVOICE (BILLED PORTION + GST)",
    invoice_row_label: str = "Our reference (vendor inv.)",
) -> bytes:
    sel = _normalize_seller(seller)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "H1",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=8,
        textColor=colors.HexColor("#1a1a2e"),
    )
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#444"),
        spaceAfter=4,
    )
    small = ParagraphStyle(
        "S",
        parent=styles["Normal"],
        fontSize=8.5,
        textColor=colors.HexColor("#666"),
    )
    story: list = []
    _append_our_company_header(story, sel, h1, h2, small)
    story.append(Spacer(1, 0.4 * cm))
    story.append(
        Paragraph(
            f"<b>{gst_heading.replace('&', '&amp;')}</b>",
            ParagraphStyle("T", parent=h1, fontSize=13),
        )
    )
    bp = billing_pct if billing_pct is not None else 100
    story.append(
        Paragraph(
            f"Taxable value = full line × <b>{bp}%</b> billing share; GST applied on taxable value only.",
            small,
        )
    )
    story.append(Spacer(1, 0.35 * cm))

    vc = (vendor_company or "").strip()
    bh = (buyer_heading or "Party").replace("&", "&amp;")
    vblock = f"<b>{bh}</b><br/>{vendor_name.replace('&', '&amp;')}"
    if vc:
        vblock += f"<br/>{vc.replace('&', '&amp;')}"
    if vendor_phone:
        vblock += f"<br/>Phone: {vendor_phone}"
    va = (vendor_address or "").strip()
    if va:
        vblock += f"<br/>{va.replace('&', '&amp;')}"
    story.append(Paragraph(vblock, h2))
    story.append(Spacer(1, 0.25 * cm))

    ord_val = (order_row_value or f"PO #{po_number}").strip()
    info_data = [
        ["Document no.", doc_no],
        ["Date", doc_date],
        [order_row_label, ord_val],
        [invoice_row_label, (vendor_invoice_ref or "—").strip() or "—"],
    ]
    t0 = Table(info_data, colWidths=[4.2 * cm, 11 * cm])
    t0.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, -1), (-1, -1), 0.25, colors.HexColor("#ddd")),
            ]
        )
    )
    story.append(t0)
    story.append(Spacer(1, 0.35 * cm))

    gr = gst_rate_pct if gst_rate_pct is not None else 0.0
    line_data = [
        ["Description", "SKU", "Qty", "Full unit rate", f"Billing {bp}%"],
        [
            item_title.replace("&", "&amp;"),
            item_sku,
            f"{quantity:g}",
            _money(unit_rate),
            _money(taxable_total),
        ],
    ]
    t1 = Table(line_data, colWidths=[5.2 * cm, 2 * cm, 1.3 * cm, 2.5 * cm, 3.5 * cm])
    t1.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16213e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#ccc")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6fb")]),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ]
        )
    )
    story.append(t1)
    story.append(Spacer(1, 0.3 * cm))

    summ = [
        ["Taxable value (after billing %)", _money(taxable_total)],
        [f"GST @ {gr:g}% on taxable value", _money(gst_amount)],
        ["Grand total", _money(grand_total)],
    ]
    t2 = Table(summ, colWidths=[11 * cm, 4.5 * cm])
    t2.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#1a1a2e")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef1f8")),
            ]
        )
    )
    story.append(t2)
    story.append(Spacer(1, 0.35 * cm))
    story.append(
        Paragraph(
            "Amount in words: numeric total shown above. Please retain for your records.",
            small,
        )
    )
    if (notes or "").strip():
        story.append(Spacer(1, 0.2 * cm))
        story.append(
            Paragraph(f"<b>Notes:</b> {(notes or '').strip().replace('&', '&amp;')}", small)
        )
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("— Authorised signatory —", ParagraphStyle("sig", parent=small, alignment=1)))

    return _build_doc(f"GST bill {doc_no}", story)


def build_billing_pdfs_for_record(b) -> tuple[bytes, bytes]:
    """Build both PDFs from one `po_billings` row (snapshots + amounts)."""
    doc_date = (getattr(b, "created_at", None) or "")[:10] or "—"
    seller = _seller_from_billing_row(b)
    v_name = (getattr(b, "snap_vendor_person", None) or "").strip() or "—"
    v_co = getattr(b, "snap_vendor_company", None)
    v_ph = getattr(b, "snap_vendor_phone", None)
    sku = (getattr(b, "snap_item_sku", None) or "").strip() or "—"
    title = (getattr(b, "snap_item_name", None) or "").strip() or "—"
    poid = int(b.po_id)
    raw = build_raw_bill_pdf(
        doc_no=f"RAW-B{b.id}-PO{poid}",
        doc_date=doc_date,
        po_number=poid,
        vendor_name=v_name,
        vendor_company=v_co,
        vendor_phone=v_ph,
        item_sku=sku,
        item_title=title,
        quantity=float(b.quantity),
        unit_rate=float(b.unit_cost),
        line_total=float(b.raw_line_total),
        vendor_invoice_ref=b.vendor_invoice_raw,
        notes=b.notes,
        seller=seller,
    )
    return raw, raw


def build_billing_pdfs_for_co_record(b) -> tuple[bytes, bytes]:
    """Build both PDFs from one `customer_order_billings` row (customer sale)."""
    doc_date = (getattr(b, "created_at", None) or "")[:10] or "—"
    seller = _seller_from_billing_row(b)
    c_name = (getattr(b, "snap_customer_name", None) or "").strip() or "—"
    c_co = getattr(b, "snap_customer_company", None)
    c_ph = getattr(b, "snap_customer_phone", None)
    c_ad = getattr(b, "snap_customer_address", None)
    sku = (getattr(b, "snap_item_sku", None) or "").strip() or "—"
    title = (getattr(b, "snap_item_name", None) or "").strip() or "—"
    coid = int(b.customer_order_id)
    raw = build_raw_bill_pdf(
        doc_no=f"RAW-COB{b.id}-CO{coid}",
        doc_date=doc_date,
        po_number=coid,
        vendor_name=c_name,
        vendor_company=c_co,
        vendor_phone=c_ph,
        vendor_address=c_ad,
        item_sku=sku,
        item_title=title,
        quantity=float(b.quantity),
        unit_rate=float(b.unit_cost),
        line_total=float(b.raw_line_total),
        vendor_invoice_ref=b.vendor_invoice_raw,
        notes=b.notes,
        seller=seller,
        buyer_heading="Customer (Bill to)",
        order_row_label="Customer order",
        order_row_value=f"Order #{coid}",
        raw_heading="SALES — FULL VALUE",
        raw_subcaption="Document without GST break-up — full agreed selling rate.",
        invoice_row_label="Our invoice ref.",
    )
    return raw, raw
