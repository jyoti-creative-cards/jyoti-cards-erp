"""Professional customer tax invoice PDF — matches vendor order style."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.customer_bill_math import fmt_discount_pct
from app.services.company_info import company_lines
from app.services.pdf_documents import (
    _fetch_image,
    _header,
    _safe,
    _totals_block,
    add_page_number,
)

# Tight page chrome so ~25 item rows stay on one A4 sheet. Side margins match
# every table width below — a wider item table, a short bill-to line, a short
# totals block, and a small photo grid.
_BILL_MARGIN_X = 0.85 * cm
_BILL_MARGIN_TOP = 0.45 * cm
_BILL_MARGIN_BOTTOM = 1.15 * cm
_BILL_CONTENT_W = A4[0] - 2 * _BILL_MARGIN_X

COPY_LABELS = ["ORIGINAL", "DUPLICATE", "TRIPLICATE", "QUADRUPLICATE"]


def _prefetch_images_parallel(
    img_map: Dict[int, str | None],
    max_w: float,
    max_h: float,
) -> Dict[int, Optional[Image]]:
    result: Dict[int, Optional[Image]] = {}
    entries = [(k, v) for k, v in img_map.items() if v]
    if not entries:
        return result
    with ThreadPoolExecutor(max_workers=min(len(entries), 8)) as ex:
        futs = {ex.submit(_fetch_image, url, max_w, max_h): k for k, url in entries}
        for fut in as_completed(futs):
            k = futs[fut]
            try:
                result[k] = fut.result()
            except Exception:
                result[k] = None
    return result


def _money(v: object) -> str:
    """Indian grouping, 2 decimals. Fits rate cells without US-style overflow."""
    try:
        from decimal import Decimal, ROUND_HALF_UP

        d = Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return _safe(v)
    neg = d < 0
    d = abs(d)
    rupees, paise = format(d, "f").split(".")
    if len(rupees) <= 3:
        grouped = rupees
    else:
        last3 = rupees[-3:]
        rest = rupees[:-3]
        chunks: list[str] = []
        while rest:
            chunks.append(rest[-2:])
            rest = rest[:-2]
        grouped = ",".join(reversed(chunks)) + "," + last3
    out = f"{grouped}.{paise}"
    return f"-{out}" if neg else out


def _cell(text: str, *, right: bool = False, muted: bool = False, size: int = 8) -> Paragraph:
    styles = getSampleStyleSheet()
    key = f"bill_cell_{'r' if right else 'l'}_{'m' if muted else 't'}_{size}"
    return Paragraph(
        escape(text or ""),
        ParagraphStyle(
            key,
            parent=styles["Normal"],
            fontSize=size,
            leading=size + 1,
            alignment=TA_RIGHT if right else TA_LEFT,
            textColor=colors.HexColor("#64748b" if muted else "#0f172a"),
            wordWrap="CJK",
        ),
    )


def _line_qty(ln: Dict[str, Any]) -> int:
    for key in ("quantity", "quantity_shipped", "qty"):
        raw = ln.get(key)
        if raw is None or raw == "":
            continue
        try:
            n = int(raw)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    return 0


def _addon_label(addon: Dict[str, Any]) -> str:
    name = _safe(addon.get("name"), 40)
    sku = _safe(addon.get("our_product_id"), 24)
    if name and name != "-":
        return name
    if sku and sku != "-":
        return sku
    return "Addon"


def _addon_qty(addon: Dict[str, Any], line_qty: int) -> int:
    # NB: addon snapshots (catalog_addons.py::_addon_row) only ever set "quantity"
    # (the per-product-unit link qty) — there is no "per_unit" key anywhere upstream.
    try:
        per = int(addon.get("quantity") or 1)
    except (TypeError, ValueError):
        per = 1
    if per < 1:
        per = 1
    return per * max(line_qty, 1)


def bill_item_headers(gst_on: bool, gst_label: str = "") -> list[str]:
    if gst_on:
        return ["", "Code", "Description", "Qty", "Rate", "Disc.", "Net", "Taxable", f"GST ({gst_label})", "Total"]
    # Non-GST "Order Estimate": no Description (our_product_id already appears in
    # Code) and no separate Disc. column — Net already reflects any discount, showing
    # both was redundant/confusing. No Photo column either — photos now live in their
    # own "Photos" section after the table (see _photos_section) so this table can
    # give Code the width it needs to stay on one line.
    return ["Code", "Qty", "Rate", "Net", "Amount"]


def _col_widths(weights: list[float], total: float) -> list[float]:
    scale = total / (sum(weights) or 1)
    return [w * scale for w in weights]


def _bill_items_table(
    lines: List[Dict[str, Any]],
    image_urls: Dict[int, str | None],
    gst_on: bool,
    gst_label: str,
    overall_disc_pct: object = None,
) -> Table:
    if gst_on:
        head = bill_item_headers(True, gst_label)
        # Thumb stays smaller than the text row so 20–25 lines still fit one page.
        img_size = 0.52 * cm
        rest = _BILL_CONTENT_W - img_size
        col_widths = [img_size, *_col_widths(
            [1.7, 3.6, 0.9, 1.5, 1.15, 1.5, 1.55, 1.45, 1.55], rest,
        )]
        prefetched = _prefetch_images_parallel(image_urls or {}, img_size, img_size)
    else:
        # Non-GST estimate has no in-table Photo column — see _photos_section, which
        # renders images after the table instead. Code takes the spare width.
        head = bill_item_headers(False)
        col_widths = _col_widths([6.4, 1.35, 2.5, 2.5, 2.9], _BILL_CONTENT_W)
        prefetched = {}

    dash = _cell("—", right=True, muted=True)
    data: list[list[Any]] = [head]
    for ln in lines:
        if not isinstance(ln, dict):
            continue
        cid = int(ln.get("catalog_product_id") or 0)
        img = prefetched.get(cid) or ""
        qty = _line_qty(ln)
        code = _cell(_safe(ln.get("our_product_id"), 24))
        desc = _cell(_safe(ln.get("name") or ln.get("our_product_id"), 60))
        rate = _cell(
            _money(ln.get("rate_inclusive") or ln.get("unit_price") or ln.get("base_unit_price")),
            right=True,
        )
        total = _cell(_money(ln.get("line_total") or ln.get("line_inclusive_after_discount")), right=True)
        disc_pct = fmt_discount_pct(ln.get("item_discount_percent") or overall_disc_pct)
        disc = ln.get("line_discount")
        disc_lbl = "—"
        try:
            if disc and float(disc) > 0 and disc_pct:
                disc_lbl = f"{disc_pct}%"
            elif disc and float(disc) > 0:
                disc_lbl = f"-{_money(disc)}"
        except (TypeError, ValueError):
            disc_lbl = "—"
        net = _cell(
            _money(ln.get("net_rate") or ln.get("effective_price") or ln.get("rate_inclusive") or ln.get("unit_price")),
            right=True,
        )
        disc_cell = _cell(disc_lbl, right=True)

        if gst_on:
            data.append([
                img,
                code,
                desc,
                _cell(str(qty), right=True),
                rate,
                disc_cell,
                net,
                _cell(_money(ln.get("line_taxable_value")), right=True),
                _cell(_money(ln.get("line_gst_amount") or "0.00"), right=True),
                total,
            ])
        else:
            data.append([
                code,
                _cell(str(qty), right=True),
                rate,
                net,
                total,
            ])

        for addon in ln.get("addons") or []:
            if not isinstance(addon, dict):
                continue
            aq = _addon_qty(addon, qty)
            label = _addon_label(addon)
            unit = _safe(addon.get("unit") or "pc", 8)
            if not unit or unit == "-":
                unit = "pc"
            row = [""] * len(head)
            if gst_on:
                row[2] = _cell(f"+ {label}", muted=True)
                row[3] = _cell(f"{aq} {unit}", right=True, muted=True)
                start = 4
            else:
                row[0] = _cell(f"+ {label}", muted=True)
                row[1] = _cell(f"{aq} {unit}", right=True, muted=True)
                start = 2
            for i in range(start, len(head)):
                row[i] = dash
            data.append(row)

    if len(data) < 2:
        empty = [""] * len(head)
        if gst_on:
            empty[1] = _cell("-")
            empty[2] = _cell("No line items")
        else:
            empty[0] = _cell("No line items")
        data.append(empty)

    # Numeric columns start right after Code/Photo+Code+Description — right-align
    # from that column on, on the HEADER row too (row 0), not just the data rows.
    # Leaving row 0 out of the ALIGN (as before) left header labels default-left
    # while every data cell below was explicitly right-aligned, so headers and their
    # own columns visibly didn't line up.
    numeric_start = 3 if gst_on else 1
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("ALIGN", (numeric_start, 0), (-1, -1), "RIGHT"),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, colors.HexColor("#e2e8f0")),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f8fafc")))
    table.setStyle(TableStyle(style_cmds))
    return table


def _photos_section(lines: List[Dict[str, Any]], image_urls: Dict[int, str | None]) -> list:
    """Small numbered photo tiles under the totals. Ten across keeps 25 items to
    three short rows so the item table above can stay on the same page."""
    per_row = 10
    tile_w = _BILL_CONTENT_W / per_row
    img_px = 1.05 * cm
    prefetched = _prefetch_images_parallel(image_urls or {}, img_px, img_px)
    styles = getSampleStyleSheet()
    cap_style = ParagraphStyle(
        "photo_cap", parent=styles["Normal"], fontSize=5.5, alignment=TA_CENTER,
        textColor=colors.HexColor("#334155"), leading=6.5,
    )
    placeholder_style = ParagraphStyle(
        "photo_ph", parent=styles["Normal"], fontSize=5, alignment=TA_CENTER,
        textColor=colors.HexColor("#94a3b8"), leading=6,
    )
    tiles: list[Any] = []
    n = 0
    for ln in lines:
        if not isinstance(ln, dict):
            continue
        n += 1
        cid = int(ln.get("catalog_product_id") or 0)
        img = prefetched.get(cid)
        code = _safe(ln.get("our_product_id"), 14)
        if img:
            pic: Any = img
        else:
            pic = Table([[Paragraph("—", placeholder_style)]], colWidths=[img_px], rowHeights=[img_px])
            pic.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
        cap = Paragraph(f"{n}. {escape(code)}", cap_style)
        tile = Table([[pic], [cap]], colWidths=[tile_w])
        tile.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        tiles.append(tile)

    if not tiles:
        return []

    grid_rows = [tiles[i:i + per_row] for i in range(0, len(tiles), per_row)]
    if grid_rows and len(grid_rows[-1]) < per_row:
        grid_rows[-1] = grid_rows[-1] + [""] * (per_row - len(grid_rows[-1]))
    grid = Table(grid_rows, colWidths=[tile_w] * per_row)
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    heading = Paragraph("Photos", ParagraphStyle(
        "photos_head", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8,
        textColor=colors.HexColor("#0f172a"), spaceBefore=1, spaceAfter=1, leading=9,
    ))
    return [Spacer(1, 0.08 * cm), heading, grid]


def _party_chip(label: str, line_html: str, second: str | None, width: float) -> Table:
    """One or two lines: 'BILL TO  Name · phone · CITY' then company/address."""
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "bill_party", parent=styles["Normal"], fontSize=8, leading=10,
        textColor=colors.HexColor("#0f172a"),
    )
    flows: list[Any] = [Paragraph(
        f'<font color="#64748b"><b>{escape(label)}</b></font>&nbsp;&nbsp;{line_html}',
        body,
    )]
    if second:
        flows.append(Paragraph(escape(second), ParagraphStyle(
            "bill_party_2", parent=body, fontSize=7.5, leading=9,
            textColor=colors.HexColor("#334155"),
        )))
    inner = Table([[f] for f in flows], colWidths=[max(width - 8, 20)])
    inner.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    tbl = Table([[inner]], colWidths=[width])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eff6ff")),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return tbl


def _customer_party_html(
    *,
    customer_name: str,
    customer_phone: str | None,
    customer_city: str | None,
    customer_party_number: int | str | None,
    customer_company: str | None,
    customer_address: str | None,
    addr_limit: int,
) -> tuple[str, str | None]:
    parts = [f"<b>{escape(_safe(customer_name, 70))}</b>"]
    if customer_party_number:
        parts.append(escape(f"Party #{_safe(customer_party_number, 16)}"))
    phone = _safe(customer_phone, 20) if customer_phone else ""
    if phone and phone != "-":
        parts.append(escape(phone))
    city = _safe(customer_city, 36) if customer_city else ""
    if city and city != "-":
        parts.append(f"<b>{escape(city)}</b>")
    second_bits: list[str] = []
    company = _safe(customer_company, 36) if customer_company else ""
    if company and company != "-":
        second_bits.append(company)
    address = _safe(customer_address, addr_limit) if customer_address else ""
    if address and address != "-":
        second_bits.append(address)
    second = " · ".join(second_bits) or None
    return " &middot; ".join(parts), second


def _bill_to_flow(
    *,
    gst_on: bool,
    customer_name: str,
    customer_company: str | None,
    customer_phone: str | None,
    customer_address: str | None,
    customer_city: str | None,
    customer_party_number: int | str | None,
) -> Table:
    addr_limit = 42 if gst_on else 88
    line_html, second = _customer_party_html(
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_city=customer_city,
        customer_party_number=customer_party_number,
        customer_company=customer_company,
        customer_address=customer_address,
        addr_limit=addr_limit,
    )
    if not gst_on:
        return _party_chip("BILL TO", line_html, second, _BILL_CONTENT_W)
    seller_lines = [ln for ln in company_lines() if ln]
    seller_name = seller_lines[0] if seller_lines else "Seller"
    seller_rest = " · ".join(seller_lines[1:]) or None
    half = _BILL_CONTENT_W / 2
    left = _party_chip("FROM", f"<b>{escape(seller_name)}</b>", seller_rest, half)
    right = _party_chip("BILL TO", line_html, second, half)
    pair = Table([[left, right]], colWidths=[half, half])
    pair.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return pair


def _build_summary_rows(totals: Dict[str, Any], gst_on: bool, gst_label: str) -> list[list[str]]:
    rows: list[list[str]] = []
    sub = totals.get("subtotal_inclusive")
    if sub is not None:
        rows.append(["Subtotal", f"Rs. {_money(sub)}"])

    disc_amt = totals.get("discount_amount")
    dp = fmt_discount_pct(totals.get("discount_percent"))
    try:
        disc_n = float(disc_amt or 0)
    except (TypeError, ValueError):
        disc_n = 0.0
    if disc_n > 0:
        label = f"Discount ({dp}%)" if dp else "Discount"
        rows.append([label, f"- Rs. {_money(disc_amt)}"])

    after = totals.get("after_discount_inclusive")
    if after is not None and disc_n > 0:
        rows.append(["After discount", f"Rs. {_money(after)}"])

    if gst_on:
        rows.append(["Taxable value", f"Rs. {_money(totals.get('taxable_value'))}"])
        rows.append([f"GST ({gst_label})", f"Rs. {_money(totals.get('gst_amount'))}"])

    # Packaging is listed before freight/transport (and the freight agent name last of
    # all the charge rows) — the agent name is a routing note, not really a charge in
    # its own right, so it reads better trailing the actual charge lines.
    packaging = totals.get("packaging_charges")
    if packaging:
        try:
            if float(packaging) > 0:
                rows.append(["Packaging charges", f"Rs. {_money(packaging)}"])
        except (TypeError, ValueError):
            pass

    freight = totals.get("freight_charges")
    mode = (totals.get("transport_mode") or "").strip().lower()
    if not mode:
        mode = "bus" if freight else "self_pickup"
    if freight:
        try:
            if float(freight) > 0:
                if mode == "transport":
                    rows.append(["Transport charges", f"Rs. {_money(freight)}"])
                    receipt = (totals.get("transport_receipt_number") or "").strip()
                    if receipt:
                        rows.append(["Transport receipt", _safe(receipt, 40)])
                else:
                    rows.append(["Freight charges", f"Rs. {_money(freight)}"])
                    agent = (totals.get("freight_agent_name") or "").strip()
                    if agent:
                        rows.append(["Freight agent", _safe(agent, 40)])
        except (TypeError, ValueError):
            pass

    additional = totals.get("additional_charges")
    if isinstance(additional, list):
        for ac in additional:
            if isinstance(ac, dict) and ac.get("name") and ac.get("amount"):
                rows.append([_safe(ac["name"], 40), f"Rs. {_money(ac['amount'])}"])

    round_off = totals.get("round_off")
    if round_off and str(round_off) not in ("0.00", "0", "0.0"):
        try:
            ro = float(round_off)
            if ro != 0:
                sign = "+" if ro > 0 else ""
                rows.append(["Round off", f"{sign}Rs. {_money(round_off)}"])
        except (TypeError, ValueError):
            pass

    grand = totals.get("rounded_grand_total") or totals.get("grand_total")
    rows.append(["Grand Total", f"Rs. {_money(grand)}"])
    return rows


def _build_bill_story(
    *,
    bill_id: int,
    order_id: int,
    bill_number: str | None = None,
    customer_name: str,
    customer_company: str | None,
    customer_phone: str | None = None,
    customer_address: str | None = None,
    customer_city: str | None = None,
    customer_party_number: int | str | None = None,
    totals: Dict[str, Any],
    generated_at: datetime | None = None,
    printed_at: datetime | None = None,
    customer_notes: str | None = None,
    narration: str | None = None,
    item_image_urls: Dict[int, str | None] | None = None,
    order_created_at: datetime | None = None,
    invoice_date=None,
    copy_label: str | None = None,
    credit_limit: float | None = None,
    outstanding: float | None = None,
) -> list:
    styles = getSampleStyleSheet()
    story: list = []

    if copy_label:
        label_style = ParagraphStyle(
            "copy_label",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            alignment=TA_RIGHT,
            textColor=colors.white,
            leading=9,
        )
        label_table = Table(
            [[Paragraph(f"  {copy_label} COPY  ", label_style)]],
            colWidths=[_BILL_CONTENT_W],
        )
        label_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1d4ed8")),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ]))
        story.append(label_table)
        story.append(Spacer(1, 0.06 * cm))

    from app.services.biz_date import format_ist_day

    gst_on = bool(totals.get("gst_enabled"))
    bill_lbl = _safe(bill_number, 40) if bill_number else f"#{bill_id}"
    if gst_on:
        # One title line. Entered/Printed stay in the page footer.
        _header(
            story, "TAX INVOICE", "", f"Bill {bill_lbl}  ·  {format_ist_day(invoice_date or generated_at)}",
            compact=True, content_width=_BILL_CONTENT_W,
        )
    else:
        # Non-GST estimate: one heading only (the brand bar above says "Order
        # Estimate") — no second "ORDER ESTIMATE" title/subtitle underneath it, and no
        # "not a tax invoice" line. Bill number + date are one short line.
        # Entered/Printed stay in the page footer (see render_copies_pdf).
        _header(
            story, "", "", "", brand_override="Order Estimate",
            compact=True, content_width=_BILL_CONTENT_W,
        )
        story.append(Paragraph(
            escape(f"Bill {bill_lbl}  ·  {format_ist_day(invoice_date or generated_at)}"),
            ParagraphStyle(
                "bill_stamp_combined", parent=styles["Normal"], fontName="Helvetica-Bold",
                fontSize=9, leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#0f172a"),
                spaceBefore=1, spaceAfter=2,
            ),
        ))

    # Name, party, phone, and city on one line. Company and address share a second
    # line only when present. City stays bold so transport can still read it.
    story.append(_bill_to_flow(
        gst_on=gst_on,
        customer_name=customer_name,
        customer_company=customer_company,
        customer_phone=customer_phone,
        customer_address=customer_address,
        customer_city=customer_city,
        customer_party_number=customer_party_number,
    ))
    story.append(Spacer(1, 0.12 * cm))

    lines = totals.get("lines") if isinstance(totals.get("lines"), list) else []
    gst_label = str(totals.get("gst_rate_label") or totals.get("gst_rate_percent") or "")
    story.append(_bill_items_table(
        lines, item_image_urls or {}, gst_on, gst_label,
        overall_disc_pct=totals.get("discount_percent"),
    ))
    story.append(Spacer(1, 0.1 * cm))
    highlight_prefixes = ("Discount", "Freight", "Transport charges", "Packaging charges") if not gst_on else ()
    story.append(_totals_block(
        _build_summary_rows(totals, gst_on, gst_label),
        highlight_prefixes=highlight_prefixes,
        compact=True,
        content_width=_BILL_CONTENT_W,
    ))
    story.append(Spacer(1, 0.08 * cm))

    notes_style = ParagraphStyle(
        "cnotes", parent=styles["Normal"], fontSize=7.5,
        textColor=colors.HexColor("#0f172a"), spaceAfter=1, leading=9,
    )
    if narration:
        story.append(Paragraph(f"<b>Narration:</b> {escape(_safe(narration, 220))}", notes_style))
    if customer_notes:
        story.append(Paragraph(f"<b>Customer notes:</b> {escape(_safe(customer_notes, 180))}", notes_style))

    if outstanding is not None:
        # Customer-facing: only the amount outstanding (incl. this bill) — no internal
        # credit-limit figures on the printed bill.
        out_text = f"Outstanding (incl. this bill): Rs.{outstanding:,.2f}"
        story.append(Paragraph(escape(out_text), ParagraphStyle(
            "outstanding_line", parent=styles["Normal"], fontSize=7.5, leading=9,
            fontName="Helvetica-Bold",
            textColor=colors.HexColor("#1d4ed8"), spaceBefore=1, spaceAfter=1,
        )))

    if not gst_on:
        # Photos live after the table + narration/notes/outstanding — small tiles,
        # so the item table above keeps the page.
        story.extend(_photos_section(lines, item_image_urls or {}))

    foot = (
        "Amounts in Indian Rupees (Rs.). Rates are GST-inclusive."
        if gst_on
        else "Amounts in Indian Rupees (Rs.). Thank you for your business!"
    )
    story.append(Spacer(1, 0.08 * cm))
    story.append(Paragraph(escape(foot), ParagraphStyle(
        "foot", parent=styles["Normal"], fontSize=6.5, leading=8, alignment=TA_CENTER,
        textColor=colors.HexColor("#64748b"),
    )))
    return story


def render_customer_bill_pdf(
    *,
    bill_id: int,
    order_id: int,
    customer_name: str,
    customer_company: str | None,
    customer_phone: str | None = None,
    customer_address: str | None = None,
    customer_city: str | None = None,
    customer_party_number: int | str | None = None,
    totals: Dict[str, Any],
    generated_at: datetime | None = None,
    printed_at: datetime | None = None,
    customer_notes: str | None = None,
    narration: str | None = None,
    item_image_urls: Dict[int, str | None] | None = None,
    order_created_at: datetime | None = None,
    invoice_date=None,
    credit_limit: float | None = None,
    outstanding: float | None = None,
    bill_number: str | None = None,
) -> bytes:
    return render_copies_pdf(
        copies=1,
        bill_id=bill_id,
        order_id=order_id,
        bill_number=bill_number,
        customer_name=customer_name,
        customer_company=customer_company,
        customer_phone=customer_phone,
        customer_address=customer_address,
        customer_city=customer_city,
        customer_party_number=customer_party_number,
        totals=totals,
        generated_at=generated_at,
        printed_at=printed_at,
        customer_notes=customer_notes,
        narration=narration,
        item_image_urls=item_image_urls,
        order_created_at=order_created_at,
        invoice_date=invoice_date,
        with_labels=False,
        credit_limit=credit_limit,
        outstanding=outstanding,
    )


def render_copies_pdf(
    *,
    copies: int = 1,
    with_labels: bool = True,
    bill_id: int,
    order_id: int,
    bill_number: str | None = None,
    customer_name: str,
    customer_company: str | None,
    customer_phone: str | None = None,
    customer_address: str | None = None,
    customer_city: str | None = None,
    customer_party_number: int | str | None = None,
    totals: Dict[str, Any],
    generated_at: datetime | None = None,
    printed_at: datetime | None = None,
    customer_notes: str | None = None,
    narration: str | None = None,
    item_image_urls: Dict[int, str | None] | None = None,
    order_created_at: datetime | None = None,
    invoice_date=None,
    credit_limit: float | None = None,
    outstanding: float | None = None,
) -> bytes:
    copies = max(1, min(copies, 4))
    now = datetime.now(timezone.utc)
    kwargs = dict(
        bill_id=bill_id,
        order_id=order_id,
        bill_number=bill_number,
        customer_name=customer_name,
        customer_company=customer_company,
        customer_phone=customer_phone,
        customer_address=customer_address,
        customer_city=customer_city,
        customer_party_number=customer_party_number,
        totals=totals,
        generated_at=generated_at,
        printed_at=printed_at or now,
        customer_notes=customer_notes,
        narration=narration,
        item_image_urls=item_image_urls,
        order_created_at=order_created_at,
        invoice_date=invoice_date,
        credit_limit=credit_limit,
        outstanding=outstanding,
    )
    combined: list = []
    for i in range(copies):
        label = COPY_LABELS[i] if with_labels else None
        story = _build_bill_story(copy_label=label, **kwargs)
        combined.extend(story)
        if i < copies - 1:
            combined.append(PageBreak())

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=_BILL_MARGIN_X,
        leftMargin=_BILL_MARGIN_X,
        topMargin=_BILL_MARGIN_TOP,
        bottomMargin=_BILL_MARGIN_BOTTOM,
    )

    gst_on = bool(totals.get("gst_enabled"))
    if gst_on:
        on_page = add_page_number
    else:
        from app.services.biz_date import format_ist as _fmt_ist

        entered_str = _fmt_ist(kwargs["generated_at"] or now)
        printed_str = _fmt_ist(kwargs["printed_at"])

        def on_page(canvas, doc_):  # noqa: ANN001 - reportlab callback signature
            add_page_number(canvas, doc_)
            canvas.saveState()
            canvas.setFont("Helvetica", 6.5)
            canvas.setFillColor(colors.HexColor("#94a3b8"))
            # Left side — page number stays bottom-right, so the two don't stack.
            canvas.drawString(
                _BILL_MARGIN_X, 0.72 * cm,
                f"Entered {entered_str}  ·  Printed {printed_str}",
            )
            canvas.restoreState()

    doc.build(combined, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
