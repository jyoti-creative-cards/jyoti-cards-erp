from __future__ import annotations
"""Split from app/services/customer_order_flow.py."""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.stock import StockBalance
from app.services.stock_receipt import add_stock
from app.services.addon_stock import deduct_addons_for_product

from app.services.customer_selling.stock import reserve_stock, restore_stock

def edit_customer_open_qty(db: Session, line_id: int, new_qty: int, customer_name: str) -> CustomerOpenLine:
    row = db.get(CustomerOpenLine, line_id)
    if not row or row.status != "open":
        raise ValueError("open line not found")
    if new_qty < 0:
        raise ValueError("quantity cannot be negative")
    if new_qty < row.quantity_billed:
        raise ValueError(f"quantity cannot be below billed ({row.quantity_billed})")
    old = int(row.quantity_open)
    delta = new_qty - old
    if delta == 0:
        return row
    if delta > 0:
        reserve_stock(
            db,
            catalog_product_id=row.catalog_product_id,
            our_product_id=row.our_product_id,
            quantity=delta,
            reference_id=row.id,
            party=customer_name,
        )
        row.quantity_received = int(row.quantity_received) + delta
    else:
        restore_stock(
            db,
            catalog_product_id=row.catalog_product_id,
            our_product_id=row.our_product_id,
            quantity=-delta,
            reference_id=row.id,
            party=customer_name,
            notes=f"Open qty edit {old}→{new_qty}",
        )
        row.quantity_received = max(row.quantity_billed, int(row.quantity_received) + delta)
    row.quantity_open = new_qty
    if new_qty <= 0 and row.quantity_billed <= 0:
        row.status = "cancelled"
    return row

def edit_customer_placement_line_qty(
    db: Session,
    line_id: int,
    new_qty: int,
    customer_name: str,
    *,
    allow_negative_stock: bool = False,
) -> CustomerOrderLine:
    line = db.get(CustomerOrderLine, line_id)
    if not line or line.status != "active":
        raise ValueError("line not found")
    if new_qty < int(line.quantity_billed or 0):
        raise ValueError(f"quantity cannot be below billed ({line.quantity_billed})")
    old = int(line.quantity)
    delta = new_qty - old
    if delta == 0:
        return line
    placement = db.get(CustomerOrderPlacement, line.placement_id)
    if not placement:
        raise ValueError("placement not found")
    order = db.get(CustomerOrder, placement.customer_order_id)
    if not order:
        raise ValueError("order not found")
    # NB: this only ever edits a still-"received" (not yet confirmed) placement line —
    # CustomerOpenLine rows are created at confirm time (see confirm_received_order), so
    # there is nothing to touch on that table here. Stock reservation still moves live.
    if delta > 0:
        reserve_stock(
            db,
            catalog_product_id=line.catalog_product_id,
            our_product_id=line.our_product_id,
            quantity=delta,
            reference_id=placement.id,
            party=customer_name,
            allow_negative=allow_negative_stock,
        )
    else:
        restore_stock(
            db,
            catalog_product_id=line.catalog_product_id,
            our_product_id=line.our_product_id,
            quantity=-delta,
            reference_id=placement.id,
            party=customer_name,
            notes=f"Received qty edit {old}→{new_qty}",
        )
    line.quantity = new_qty
    return line

def replace_received_placement(
    db: Session,
    *,
    placement_id: int,
    lines: list[dict],
    customer_notes: str | None,
    customer_name: str,
    allow_negative_stock: bool = False,
) -> CustomerOrderPlacement:
    """Replace received placement lines (add / change qty / remove).

    Already-billed qty is locked: cannot go below quantity_billed; removing a
    partly-billed product keeps the billed remainder.
    """
    placement = db.get(CustomerOrderPlacement, placement_id)
    if not placement or placement.status != "received":
        raise ValueError("placement not found or not editable")
    order = db.get(CustomerOrder, placement.customer_order_id)
    if not order:
        raise ValueError("order not found")

    existing = (
        db.query(CustomerOrderLine)
        .filter(CustomerOrderLine.placement_id == placement_id)
        .all()
    )
    by_cat = {int(ln.catalog_product_id): ln for ln in existing if ln.status == "active"}

    desired: dict[int, int] = {}
    for raw in lines:
        qty = int(raw.get("quantity") or 0)
        if qty <= 0:
            continue
        cid = int(raw["catalog_product_id"])
        desired[cid] = desired.get(cid, 0) + qty

    # Keep billed floor for products omitted from desired
    for cid, ln in by_cat.items():
        billed = int(ln.quantity_billed or 0)
        if cid not in desired and billed > 0:
            desired[cid] = billed

    if not desired and not by_cat:
        raise ValueError("enter quantity on at least one line")
    if not desired:
        raise ValueError("nothing left to keep — cancel the order instead")

    # Remove / shrink lines not wanted (unbilled only)
    for cid, ln in list(by_cat.items()):
        if cid not in desired:
            edit_customer_placement_line_qty(db, ln.id, 0, customer_name)
            ln.status = "cancelled"
            del by_cat[cid]

    # Update / add
    for cid, qty in desired.items():
        prod = db.get(CatalogProduct, cid)
        if not prod or not prod.is_active:
            raise ValueError(f"product {cid} not found")
        from app.services.pricing import effective_selling_price

        unit_price = effective_selling_price(prod.buying_price, prod.selling_price)
        if unit_price is None:
            raise ValueError(f"sell price not set for {prod.our_product_id}")
        if cid in by_cat:
            billed = int(by_cat[cid].quantity_billed or 0)
            if qty < billed:
                raise ValueError(f"{prod.our_product_id}: cannot go below billed qty ({billed})")
            edit_customer_placement_line_qty(
                db, by_cat[cid].id, qty, customer_name, allow_negative_stock=allow_negative_stock
            )
            # Backfill linked addons if older lines were saved without them
            existing_ln = by_cat[cid]
            if not existing_ln.addons_json:
                from app.services.catalog_addons import addon_snapshots_for_product

                existing_ln.addons_json = addon_snapshots_for_product(db, prod.id) or None
        else:
            from app.services.catalog_addons import addon_snapshots_for_product

            db.add(
                CustomerOrderLine(
                    placement_id=placement.id,
                    catalog_product_id=prod.id,
                    our_product_id=prod.our_product_id,
                    quantity=qty,
                    quantity_billed=0,
                    unit_price=unit_price,
                    status="active",
                    addons_json=addon_snapshots_for_product(db, prod.id) or None,
                )
            )
            reserve_stock(
                db,
                catalog_product_id=prod.id,
                our_product_id=prod.our_product_id,
                quantity=qty,
                reference_id=placement.id,
                party=customer_name,
                allow_negative=allow_negative_stock,
            )
            # CustomerOpenLine is populated at confirm time, not here — see confirm_received_order.

    placement.customer_notes = customer_notes
    order.updated_at = datetime.now(timezone.utc)
    return placement

