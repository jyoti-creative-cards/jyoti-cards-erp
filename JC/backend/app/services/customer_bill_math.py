"""Inclusive selling prices → optional invoice discount → optional GST split per line."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List


def _d(x: object) -> Decimal:
    try:
        return Decimal(str(x).strip())
    except Exception:
        return Decimal("0")


def _fmt2(d: Decimal) -> str:
    return format(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _line_has_disc_or_net(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    pct = row.get("discount_percent")
    if pct is not None and str(pct).strip() != "":
        try:
            if Decimal(str(pct)) != 0:
                return True
        except Exception:
            return True
    net = row.get("net_rate")
    if net is not None and str(net).strip() != "":
        return True
    return False


def assert_discount_xor(overall_percent: object, lines: list | None) -> None:
    """Overall % and per-line disc/net cannot both be set."""
    from fastapi import HTTPException

    overall = Decimal("0")
    if overall_percent is not None and str(overall_percent).strip() != "":
        try:
            overall = Decimal(str(overall_percent))
        except Exception:
            overall = Decimal("0")
    if overall <= 0:
        return
    for row in lines or []:
        if _line_has_disc_or_net(row):
            raise HTTPException(400, "use overall discount or per-item, not both")


def snap_discount_pct(raw: object) -> Decimal:
    """Print-friendly %. 9.91 from rounded net → 10. Real 7.50 stays 7.50."""
    d = _d(raw)
    if d <= 0:
        return Decimal("0")
    d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole = d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if whole > 0 and abs(d - whole) <= Decimal("0.15"):
        return whole
    return d


def fmt_discount_pct(raw: object) -> str | None:
    d = snap_discount_pct(raw)
    if d <= 0:
        return None
    if d == d.to_integral():
        return str(int(d))
    return _fmt2(d)


def prepare_totals_for_pdf(
    totals: Dict[str, Any] | None,
    *,
    overall_percent: object = None,
    line_percent_by_cid: dict[int, object] | None = None,
) -> Dict[str, Any]:
    """Stamp entered % on a stored totals blob so the PDF cannot print 9.91."""
    if not isinstance(totals, dict):
        return {}
    out = dict(totals)
    overall = overall_percent if overall_percent is not None else out.get("discount_percent")
    shown_overall = fmt_discount_pct(overall) if overall is not None else None
    if shown_overall:
        out["discount_percent"] = shown_overall
    lines = []
    for ln in out.get("lines") or []:
        if not isinstance(ln, dict):
            continue
        row = dict(ln)
        cid = int(row.get("catalog_product_id") or 0)
        entered = None
        if line_percent_by_cid and cid and cid in line_percent_by_cid:
            entered = line_percent_by_cid[cid]
        elif overall is not None and _d(overall) > 0:
            entered = overall
        elif row.get("item_discount_percent") is not None:
            entered = row.get("item_discount_percent")
        row["item_discount_percent"] = fmt_discount_pct(entered) if entered is not None else None
        lines.append(row)
    out["lines"] = lines
    return out


def compute_bill_totals(
    order_items: List[dict[str, Any]],
    gst_enabled: bool,
    gst_rate_percent: Decimal,
    discount_percent: Decimal | None,
    freight_charges: Decimal | None = None,
    packaging_charges: Decimal | None = None,
    item_overrides: list[dict] | None = None,
    additional_charges: list[dict] | None = None,
) -> Dict[str, Any]:
    """
    Order line unit_price is GST-inclusive (list / catalogue rate).

    item_overrides: [{catalog_product_id, override_price?, discount_percent?}]
      - discount_percent set: money AND print use that % of list. Net is ignored.
      - override_price only: line total = net × qty. Print % is derived (snapped).
    """
    overrides_map: dict[int, dict] = {}
    if item_overrides:
        for ov in item_overrides:
            if isinstance(ov, dict) and ov.get("catalog_product_id"):
                overrides_map[int(ov["catalog_product_id"])] = ov

    raw_lines: List[Dict[str, Any]] = []
    subtotal_inclusive = Decimal("0")

    for row in order_items:
        if not isinstance(row, dict):
            continue
        try:
            qty = int(row.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty < 1:
            continue
        sku = str(row.get("our_product_id") or "")
        name = str(row.get("name") or "")
        list_unit = _d(row.get("unit_price"))
        if list_unit < 0:
            list_unit = Decimal("0")

        cid = row.get("catalog_product_id")
        item_discount_pct = Decimal("0")
        fixed_line_discount: Decimal | None = None
        net_unit: Decimal | None = None

        if cid is not None and int(cid) in overrides_map:
            ov = overrides_map[int(cid)]
            entered_pct = ov.get("discount_percent")
            if entered_pct is not None and str(entered_pct).strip() != "":
                item_discount_pct = _d(entered_pct)
                if item_discount_pct < 0:
                    item_discount_pct = Decimal("0")
                if item_discount_pct > Decimal("100"):
                    item_discount_pct = Decimal("100")
            elif ov.get("override_price") is not None:
                net_unit = _d(ov["override_price"])
                if net_unit < 0:
                    net_unit = Decimal("0")
                line_before = (list_unit * Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                line_after = (net_unit * Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if line_after > line_before:
                    line_before = line_after
                    fixed_line_discount = Decimal("0")
                else:
                    fixed_line_discount = (line_before - line_after).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                if list_unit > 0 and net_unit < list_unit:
                    item_discount_pct = snap_discount_pct(
                        (list_unit - net_unit) * Decimal("100") / list_unit
                    )

        line_inc = (list_unit * Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if fixed_line_discount is not None:
            # Prefer list×qty as before-discount; already computed above when net set
            line_inc = (list_unit * Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if net_unit is not None and net_unit > list_unit:
                line_inc = (net_unit * Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        subtotal_inclusive += line_inc
        raw_lines.append(
            {
                "catalog_product_id": int(cid) if cid is not None else None,
                "our_product_id": sku,
                "name": name,
                "quantity": qty,
                "inclusive_unit_price": list_unit if net_unit is None or net_unit <= list_unit else net_unit,
                "line_inclusive_total": line_inc,
                "item_discount_pct": item_discount_pct,
                "fixed_line_discount": fixed_line_discount,
                "net_unit": net_unit,
            }
        )

    subtotal_inclusive = subtotal_inclusive.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    dp = discount_percent if discount_percent is not None else Decimal("0")
    if dp < 0:
        dp = Decimal("0")
    if dp > Decimal("100"):
        dp = Decimal("100")

    # Overall invoice discount (when no per-line discounts drive the math)
    overall_discount_amount = (subtotal_inclusive * dp / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    r = gst_rate_percent if gst_rate_percent > 0 else Decimal("0")
    factor = Decimal("1") + r / Decimal("100") if gst_enabled and r > 0 else Decimal("1")

    n = len(raw_lines)
    has_fixed = any(lr.get("fixed_line_discount") is not None for lr in raw_lines)
    has_item_discounts = has_fixed or any(lr["item_discount_pct"] > 0 for lr in raw_lines)
    line_discounts: List[Decimal] = []
    for lr in raw_lines:
        li = lr["line_inclusive_total"]
        if lr.get("fixed_line_discount") is not None:
            ld = lr["fixed_line_discount"]
        elif lr["item_discount_pct"] > 0:
            ld = (li * lr["item_discount_pct"] / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        elif not has_item_discounts and subtotal_inclusive > 0 and n > 0 and overall_discount_amount > 0:
            ld = (li / subtotal_inclusive * overall_discount_amount).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            ld = Decimal("0")
        line_discounts.append(ld)

    if n > 0 and not has_item_discounts and overall_discount_amount > 0:
        allocated = sum(line_discounts, Decimal("0"))
        drift = (overall_discount_amount - allocated).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        line_discounts[-1] = (line_discounts[-1] + drift).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    discount_amount = sum(line_discounts, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    after_discount_inclusive = (subtotal_inclusive - discount_amount).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    lines_out: List[Dict[str, Any]] = []
    taxable_total = Decimal("0")
    gst_total = Decimal("0")
    for lr, ld in zip(raw_lines, line_discounts):
        qty = lr["quantity"]
        inc_unit = lr["inclusive_unit_price"]
        li = lr["line_inclusive_total"]
        line_after = (li - ld).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        rate_incl_fmt = _fmt2(inc_unit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

        if gst_enabled and r > 0:
            line_taxable = (line_after / factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            line_gst_amt = (line_after - line_taxable).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            base_unit_excl = (inc_unit / factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            taxable_unit = (
                (line_taxable / Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if qty > 0
                else Decimal("0")
            )
        else:
            line_taxable = line_after
            line_gst_amt = Decimal("0")
            base_unit_excl = inc_unit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            taxable_unit = base_unit_excl

        taxable_total += line_taxable
        gst_total += line_gst_amt

        eff = (
            (line_after / Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if qty > 0
            else Decimal("0")
        )
        display_pct = snap_discount_pct(lr["item_discount_pct"]) if lr["item_discount_pct"] > 0 else Decimal("0")
        if display_pct <= 0 and dp > 0 and not has_item_discounts:
            display_pct = snap_discount_pct(dp)
        out_row: Dict[str, Any] = {
            "our_product_id": lr["our_product_id"],
            "name": lr["name"] or lr["our_product_id"],
            "quantity": qty,
            "rate_inclusive": rate_incl_fmt,
            "unit_price": rate_incl_fmt,
            "base_unit_price": _fmt2(base_unit_excl),
            "taxable_unit_price": _fmt2(taxable_unit),
            "line_inclusive_before_discount": _fmt2(li),
            "line_discount": _fmt2(ld),
            "line_inclusive_after_discount": _fmt2(line_after),
            "line_taxable_value": _fmt2(line_taxable),
            "line_gst_amount": _fmt2(line_gst_amt),
            "line_total": _fmt2(line_after),
            "item_discount_percent": fmt_discount_pct(display_pct),
            "effective_price": _fmt2(eff),
            "net_rate": _fmt2(eff),
        }
        if lr.get("catalog_product_id") is not None:
            out_row["catalog_product_id"] = lr["catalog_product_id"]
        lines_out.append(out_row)

    taxable_total = taxable_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    gst_total = gst_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    gst_rate_display = _fmt2(r).rstrip("0").rstrip(".") if r == r.to_integral() else _fmt2(r)

    freight = (freight_charges or Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if freight < 0:
        freight = Decimal("0")
    packaging = (packaging_charges or Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if packaging < 0:
        packaging = Decimal("0")

    extra_charges_out: list[dict] = []
    extra_total = Decimal("0")
    if additional_charges:
        for ac in additional_charges:
            if not isinstance(ac, dict):
                continue
            ac_name = str(ac.get("name") or "").strip()
            if not ac_name:
                continue
            try:
                ac_amt = Decimal(str(ac.get("amount") or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            except Exception:
                ac_amt = Decimal("0")
            if ac_amt < 0:
                ac_amt = Decimal("0")
            if ac_amt > 0:
                extra_charges_out.append({"name": ac_name, "amount": _fmt2(ac_amt)})
                extra_total += ac_amt

    grand = (after_discount_inclusive + freight + packaging + extra_total).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    rounded_grand = grand.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    round_off = (rounded_grand - grand).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "lines": lines_out,
        "subtotal_inclusive": _fmt2(subtotal_inclusive),
        "discount_percent": fmt_discount_pct(dp),
        "discount_amount": _fmt2(discount_amount),
        "after_discount_inclusive": _fmt2(after_discount_inclusive),
        "freight_charges": _fmt2(freight) if freight > 0 else None,
        "packaging_charges": _fmt2(packaging) if packaging > 0 else None,
        "additional_charges": extra_charges_out if extra_charges_out else None,
        "gst_enabled": gst_enabled,
        "gst_rate_percent": _fmt2(r),
        "gst_rate_label": f"{gst_rate_display}%",
        "taxable_value": _fmt2(taxable_total),
        "gst_amount": _fmt2(gst_total),
        "grand_total": _fmt2(grand),
        "round_off": _fmt2(round_off) if round_off != 0 else None,
        "rounded_grand_total": _fmt2(rounded_grand),
    }
