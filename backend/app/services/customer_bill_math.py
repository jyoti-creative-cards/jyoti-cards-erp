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
    Order line unit_price is GST-inclusive.
    Discount % applies to the invoice inclusive subtotal; allocated to lines by proportion.
    GST split uses the same rate on each line's discounted inclusive amount.
    item_overrides: [{catalog_product_id, override_price?, discount_percent?}]
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
        inc_unit = _d(row.get("unit_price"))

        # Apply per-item override if present
        cid = row.get("catalog_product_id")
        item_discount_pct = Decimal("0")
        if cid is not None and int(cid) in overrides_map:
            ov = overrides_map[int(cid)]
            if ov.get("override_price") is not None:
                inc_unit = _d(ov["override_price"])
            if ov.get("discount_percent") is not None:
                item_discount_pct = _d(ov["discount_percent"])
                if item_discount_pct < 0:
                    item_discount_pct = Decimal("0")
                if item_discount_pct > Decimal("100"):
                    item_discount_pct = Decimal("100")

        line_inc = (inc_unit * Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        subtotal_inclusive += line_inc
        raw_lines.append(
            {
                "our_product_id": sku,
                "name": name,
                "quantity": qty,
                "inclusive_unit_price": inc_unit,
                "line_inclusive_total": line_inc,
                "item_discount_pct": item_discount_pct,
            }
        )

    subtotal_inclusive = subtotal_inclusive.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    dp = discount_percent if discount_percent is not None else Decimal("0")
    if dp < 0:
        dp = Decimal("0")
    if dp > Decimal("100"):
        dp = Decimal("100")

    discount_amount = (subtotal_inclusive * dp / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    after_discount_inclusive = (subtotal_inclusive - discount_amount).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    r = gst_rate_percent if gst_rate_percent > 0 else Decimal("0")
    factor = Decimal("1") + r / Decimal("100") if gst_enabled and r > 0 else Decimal("1")

    n = len(raw_lines)
    line_discounts: List[Decimal] = []
    for lr in raw_lines:
        li = lr["line_inclusive_total"]
        item_dp = lr["item_discount_pct"]
        if item_dp > 0:
            # Per-item discount overrides the proportional global discount for this line
            ld = (li * item_dp / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif subtotal_inclusive > 0 and n > 0:
            ld = (li / subtotal_inclusive * discount_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            ld = Decimal("0")
        line_discounts.append(ld)
    if n > 0:
        # Only correct drift on lines without per-item discount
        global_discount_lines = [i for i, lr in enumerate(raw_lines) if lr["item_discount_pct"] == 0]
        if global_discount_lines:
            allocated = sum(line_discounts[i] for i in global_discount_lines)
            global_discount_total = sum(
                (lr["line_inclusive_total"] / subtotal_inclusive * discount_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if subtotal_inclusive > 0 else Decimal("0")
                for lr in raw_lines if lr["item_discount_pct"] == 0
            )
            drift = global_discount_total - allocated
            last_global = global_discount_lines[-1]
            line_discounts[last_global] = (line_discounts[last_global] + drift).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    lines_out: List[Dict[str, Any]] = []
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
        else:
            line_taxable = line_after
            line_gst_amt = Decimal("0")
            base_unit_excl = inc_unit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        lines_out.append(
            {
                "our_product_id": lr["our_product_id"],
                "name": lr["name"],
                "quantity": qty,
                "rate_inclusive": rate_incl_fmt,
                "base_unit_price": _fmt2(base_unit_excl),
                "line_inclusive_before_discount": _fmt2(li),
                "line_discount": _fmt2(ld),
                "line_inclusive_after_discount": _fmt2(line_after),
                "line_taxable_value": _fmt2(line_taxable),
                "line_gst_amount": _fmt2(line_gst_amt),
                "line_total": _fmt2(line_after),
                "item_discount_percent": _fmt2(lr["item_discount_pct"]) if lr["item_discount_pct"] > 0 else None,
                "effective_price": _fmt2((line_after / Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if qty > 0 else _fmt2(Decimal("0")),
            }
        )

    taxable_total = (after_discount_inclusive / factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if (
        gst_enabled and r > 0
    ) else after_discount_inclusive
    gst_total = (after_discount_inclusive - taxable_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if (
        gst_enabled and r > 0
    ) else Decimal("0")

    gst_rate_display = _fmt2(r).rstrip("0").rstrip(".") if r == r.to_integral() else _fmt2(r)

    freight = (freight_charges or Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if freight < 0:
        freight = Decimal("0")
    packaging = (packaging_charges or Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if packaging < 0:
        packaging = Decimal("0")

    # Additional charges (e.g. VAT, handling, etc.)
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

    grand = (after_discount_inclusive + freight + packaging + extra_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "lines": lines_out,
        "subtotal_inclusive": _fmt2(subtotal_inclusive),
        "discount_percent": _fmt2(dp) if dp > 0 else None,
        "discount_amount": _fmt2(discount_amount) if dp > 0 else _fmt2(Decimal("0")),
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
    }
