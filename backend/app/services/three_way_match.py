"""3-way match: PO ordered vs goods received (receipts) vs vendor bill lines."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.stock_receipt import StockReceipt
from app.models.vendor_purchase_order import VendorPurchaseOrder


def _dec(s: object) -> Decimal:
    try:
        return Decimal(str(s).strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def aggregate_received_quantities(db: Session, purchase_order_id: int) -> Dict[int, int]:
    rows = db.query(StockReceipt).filter(StockReceipt.purchase_order_id == purchase_order_id).all()
    agg: dict[int, int] = defaultdict(int)
    for r in rows:
        raw = r.line_items if isinstance(r.line_items, list) else []
        for li in raw:
            if not isinstance(li, dict):
                continue
            try:
                cid = int(li["catalog_product_id"])
                q = int(li["quantity"])
            except (KeyError, TypeError, ValueError):
                continue
            agg[cid] += max(0, q)
    return dict(agg)


def _parse_po_lines(po: VendorPurchaseOrder) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    raw = po.items if isinstance(po.items, list) else []
    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            cid = int(row["catalog_product_id"])
            qty = int(row["quantity"])
        except (KeyError, TypeError, ValueError):
            continue
        out[cid] = {
            "quantity_ordered": max(0, qty),
            "buying_price": _dec(row.get("buying_price")),
            "our_product_id": str(row.get("our_product_id") or ""),
            "name": str(row.get("name") or ""),
        }
    return out


def _parse_bill_lines(bill_lines: List[dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for bl in bill_lines:
        if not isinstance(bl, dict):
            continue
        try:
            cid = int(bl["catalog_product_id"])
            bqty = int(bl["quantity"])
            up = _dec(bl.get("unit_price"))
        except (KeyError, TypeError, ValueError):
            continue
        ref = str(bl.get("bill_item_ref") or "").strip()
        amt = (up * _dec(bqty)).quantize(Decimal("0.0001"))
        out[cid] = {
            "bill_item_ref": ref,
            "quantity": max(0, bqty),
            "unit_price": up,
            "line_amount": amt,
        }
    return out


def run_three_way_match(
    db: Session,
    po: VendorPurchaseOrder,
    bill_lines: List[dict[str, Any]],
) -> Dict[str, Any]:
    po_map = _parse_po_lines(po)
    bill_map = _parse_bill_lines(bill_lines)
    received = aggregate_received_quantities(db, po.id)

    all_cids = set(po_map.keys()) | set(received.keys()) | set(bill_map.keys())

    line_rows: List[Dict[str, Any]] = []
    reasons: List[str] = []
    matched_all = True

    for cid in sorted(all_cids):
        po_row = po_map.get(cid)
        bill_row = bill_map.get(cid)
        recv_q = int(received.get(cid, 0))

        sku = po_row["our_product_id"] if po_row else str(cid)
        nm = (po_row or {}).get("name") or ""

        issues: List[str] = []

        if po_row is None:
            if bill_row:
                issues.append("bill_line_not_on_po")
                matched_all = False
                reasons.append(f"Bill line #{cid} ({bill_row.get('bill_item_ref')}) not on PO")
            line_rows.append(
                {
                    "catalog_product_id": cid,
                    "our_product_id": sku,
                    "name": nm,
                    "bill_item_ref": (bill_row or {}).get("bill_item_ref", ""),
                    "po_ordered": 0,
                    "received": recv_q,
                    "bill_quantity": int((bill_row or {}).get("quantity", 0)),
                    "po_buying_unit": "0",
                    "bill_unit_price": str((bill_row or {}).get("unit_price", "0")),
                    "bill_line_amount": str((bill_row or {}).get("line_amount", "0")),
                    "expected_amount_po_buying_times_bill_qty": "0",
                    "issues": issues,
                    "line_matched": False,
                }
            )
            continue

        ord_q = int(po_row["quantity_ordered"])
        bp = po_row["buying_price"]

        if bill_row is None:
            if recv_q > 0:
                issues.append("vendor_bill_line_missing")
                matched_all = False
                reasons.append(f"{sku}: received {recv_q} units but no vendor bill line")
            line_rows.append(
                {
                    "catalog_product_id": cid,
                    "our_product_id": sku,
                    "name": nm,
                    "bill_item_ref": "",
                    "po_ordered": ord_q,
                    "received": recv_q,
                    "bill_quantity": 0,
                    "po_buying_unit": str(bp),
                    "bill_unit_price": "0",
                    "bill_line_amount": "0",
                    "expected_amount_po_buying_times_bill_qty": "0",
                    "issues": issues,
                    "line_matched": len(issues) == 0,
                }
            )
            continue

        bqty = int(bill_row["quantity"])
        b_amt = bill_row["line_amount"]
        b_unit = bill_row["unit_price"]
        bill_ref = bill_row.get("bill_item_ref") or ""
        expected = (bp * _dec(bqty)).quantize(Decimal("0.0001"))

        if recv_q != bqty:
            issues.append("received_vs_bill_qty")
            matched_all = False
            reasons.append(f"{sku}: received {recv_q} vs bill qty {bqty}")

        if abs(b_amt - expected) > Decimal("0.02"):
            issues.append("bill_amount_vs_po_buying_times_bill_qty")
            matched_all = False
            reasons.append(f"{sku}: bill line amount {b_amt} vs PO buying×bill qty {expected}")

        if recv_q > ord_q:
            issues.append("received_exceeds_po_ordered")
            matched_all = False
            reasons.append(f"{sku}: received {recv_q} exceeds PO ordered {ord_q}")

        line_ok = len(issues) == 0
        line_rows.append(
            {
                "catalog_product_id": cid,
                "our_product_id": sku,
                "name": nm,
                "bill_item_ref": bill_ref,
                "po_ordered": ord_q,
                "received": recv_q,
                "bill_quantity": bqty,
                "po_buying_unit": str(bp),
                "bill_unit_price": str(b_unit),
                "bill_line_amount": str(b_amt),
                "expected_amount_po_buying_times_bill_qty": str(expected),
                "issues": issues,
                "line_matched": line_ok,
            }
        )

    po_total = sum(
        (pr["buying_price"] * _dec(pr["quantity_ordered"])).quantize(Decimal("0.0001"))
        for pr in po_map.values()
    )

    recv_total = Decimal("0")
    for cid, pr in po_map.items():
        rq = min(int(received.get(cid, 0)), int(pr["quantity_ordered"]))
        recv_total += (pr["buying_price"] * _dec(rq)).quantize(Decimal("0.0001"))

    bill_total = Decimal("0")
    for c in bill_map:
        bill_total += bill_map[c]["line_amount"]

    summary = (
        "Matched — receipts and vendor bill align with PO buying prices."
        if matched_all
        else "Not matched — see reasons per line."
    )

    return {
        "matched": matched_all,
        "summary": summary,
        "reasons": reasons,
        "lines": line_rows,
        "totals": {
            "po_ordered_value_at_buying": str(po_total),
            "received_value_at_po_buying_capped": str(recv_total),
            "bill_total_entered": str(bill_total.quantize(Decimal("0.0001"))),
        },
    }
