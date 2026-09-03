from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct
from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.stock import StockBalance
from app.services.stock_receipt import add_stock


def get_open_customer_order(db: Session, customer_id: int, bucket: str) -> CustomerOrder | None:
    return (
        db.query(CustomerOrder)
        .filter(CustomerOrder.customer_id == customer_id, CustomerOrder.bucket == bucket, CustomerOrder.is_open.is_(True))
        .first()
    )


def get_or_create_customer_order(db: Session, customer_id: int, bucket: str, status: str) -> CustomerOrder:
    from sqlalchemy.exc import IntegrityError

    order = get_open_customer_order(db, customer_id, bucket)
    if order:
        return order
    try:
        with db.begin_nested():
            order = CustomerOrder(customer_id=customer_id, bucket=bucket, status=status, is_open=True)
            db.add(order)
            db.flush()
    except IntegrityError:
        order = get_open_customer_order(db, customer_id, bucket)
        if not order:
            raise
    return order


def _get_or_create_open_line(
    db: Session,
    customer_id: int,
    catalog_product_id: int,
    unit_price: Decimal,
    *,
    as_of: datetime | None = None,
) -> CustomerOpenLine:
    prod = db.get(CatalogProduct, catalog_product_id)
    if not prod:
        raise ValueError("product not found")
    row = (
        db.query(CustomerOpenLine)
        .filter(CustomerOpenLine.customer_id == customer_id, CustomerOpenLine.catalog_product_id == catalog_product_id)
        .first()
    )
    if row:
        if row.status != "open":
            row.status = "open"
        row.unit_price = unit_price
        row.our_product_id = prod.our_product_id
        return row
    row = CustomerOpenLine(
        customer_id=customer_id,
        catalog_product_id=catalog_product_id,
        our_product_id=prod.our_product_id,
        quantity_received=0,
        quantity_open=0,
        quantity_billed=0,
        unit_price=unit_price,
        status="open",
    )
    if as_of is not None:
        row.created_at = as_of
    db.add(row)
    db.flush()
    return row


def add_to_customer_open(
    db: Session,
    customer_id: int,
    lines: list[tuple[int, int, Decimal]],
    *,
    as_of: datetime | None = None,
) -> None:
    for catalog_product_id, qty, price in lines:
        if qty <= 0:
            continue
        row = _get_or_create_open_line(db, customer_id, catalog_product_id, price, as_of=as_of)
        row.quantity_received += qty
        row.quantity_open += qty
        row.status = "open"


def reserve_stock(
    db: Session,
    *,
    catalog_product_id: int,
    our_product_id: str,
    quantity: int,
    reference_id: int,
    party: str,
    allow_negative: bool = False,
) -> None:
    balance = (
        db.query(StockBalance)
        .filter(StockBalance.catalog_product_id == catalog_product_id)
        .with_for_update()
        .first()
    )
    if not balance:
        balance = StockBalance(catalog_product_id=catalog_product_id, quantity_on_hand=0)
        db.add(balance)
        db.flush()
    on_hand = int(balance.quantity_on_hand or 0)
    if on_hand < quantity and not allow_negative:
        raise ValueError(
            f"insufficient stock for {our_product_id} (need {quantity}, have {on_hand})"
        )
    note = f"Customer order reserved {quantity}"
    if allow_negative and on_hand < quantity:
        note = f"Customer order reserved {quantity} (oversell; had {on_hand})"
    add_stock(
        db,
        catalog_product_id=catalog_product_id,
        our_product_id=our_product_id,
        quantity=-quantity,
        entry_type="reserved",
        reference_type="customer_placement",
        reference_id=reference_id,
        party=party,
        notes=note,
    )


def restore_stock(db: Session, *, catalog_product_id: int, our_product_id: str, quantity: int, reference_id: int, party: str, notes: str) -> None:
    if quantity <= 0:
        return
    add_stock(
        db,
        catalog_product_id=catalog_product_id,
        our_product_id=our_product_id,
        quantity=quantity,
        entry_type="unreserved",
        reference_type="customer_placement",
        reference_id=reference_id,
        party=party,
        notes=notes,
    )


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


def cancel_customer_placement(
    db: Session,
    *,
    placement_id: int,
    reason: str,
    customer_name: str,
) -> CustomerOrderPlacement:
    """Cancel unbilled qty on a received placement. Billed qty is never cancelled."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("cancel reason required")

    placement = db.get(CustomerOrderPlacement, placement_id)
    if not placement:
        raise ValueError("placement not found")
    if placement.status != "received":
        raise ValueError("only received placements can be cancelled")

    order = db.get(CustomerOrder, placement.customer_order_id)
    if not order or order.bucket != "received":
        raise ValueError("cannot cancel — not a received order")

    lines = (
        db.query(CustomerOrderLine)
        .filter(
            CustomerOrderLine.placement_id == placement.id,
            CustomerOrderLine.status == "active",
        )
        .all()
    )
    cancellable = []
    for ln in lines:
        billed = int(ln.quantity_billed or 0)
        unbilled = int(ln.quantity) - billed
        if unbilled > 0:
            cancellable.append((ln, unbilled, billed))
    if not cancellable:
        raise ValueError("nothing left to cancel — already billed")

    cancelled_order = get_or_create_customer_order(db, order.customer_id, "cancelled", "cancelled")
    hist = CustomerOrderPlacement(
        customer_order_id=cancelled_order.id,
        status="cancelled",
        cancel_reason=reason,
        customer_notes=placement.customer_notes,
        placed_at=placement.placed_at,
    )
    db.add(hist)
    db.flush()

    now = datetime.now(timezone.utc)
    for ln, unbilled, billed in cancellable:
        # NB: only "received" (not yet confirmed) placements reach here — CustomerOpenLine
        # rows are created at confirm time, so there's nothing on that table to unwind.
        restore_stock(
            db,
            catalog_product_id=ln.catalog_product_id,
            our_product_id=ln.our_product_id,
            quantity=unbilled,
            reference_id=placement.id,
            party=customer_name,
            notes=f"Cancelled placement open: {reason}",
        )

        if billed > 0:
            ln.quantity = billed
        else:
            ln.status = "cancelled"
            ln.cancel_reason = reason

        db.add(
            CustomerOrderLine(
                placement_id=hist.id,
                catalog_product_id=ln.catalog_product_id,
                our_product_id=ln.our_product_id,
                quantity=unbilled,
                quantity_billed=0,
                unit_price=ln.unit_price,
                addons_json=ln.addons_json,
                status="cancelled",
                cancel_reason=reason,
            )
        )

    still_active = (
        db.query(CustomerOrderLine)
        .filter(
            CustomerOrderLine.placement_id == placement.id,
            CustomerOrderLine.status == "active",
        )
        .count()
    )
    if still_active == 0:
        placement.status = "cancelled"
        placement.cancel_reason = reason
        placement.closed_at = now
    order.updated_at = now
    cancelled_order.updated_at = now
    return placement


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


def confirm_received_order(db: Session, customer_id: int) -> bool:
    """Move a customer's received (New) order to the open (Confirmed) bucket.

    Returns True if something was confirmed, False if there was nothing to confirm.
    CustomerOpenLine (the running unbilled tally used for the Confirmed list + billing)
    is only populated here, at confirm time — never at placement time — so a fresh order
    only ever shows under "New" until someone explicitly confirms it.
    """
    received = get_open_customer_order(db, customer_id, "received")
    if not received:
        return False

    # Check there are any active lines worth confirming
    placements = (
        db.query(CustomerOrderPlacement)
        .filter(
            CustomerOrderPlacement.customer_order_id == received.id,
            CustomerOrderPlacement.status == "received",
        )
        .all()
    )
    active_lines = (
        db.query(CustomerOrderLine)
        .filter(
            CustomerOrderLine.placement_id.in_([p.id for p in placements]),
            CustomerOrderLine.status == "active",
        )
        .all()
    ) if placements else []

    if not active_lines:
        return False

    # Only now does this order's qty become part of the billable "open" tally.
    add_to_customer_open(
        db,
        customer_id,
        [
            (int(ln.catalog_product_id), int(ln.quantity) - int(ln.quantity_billed or 0), ln.unit_price)
            for ln in active_lines
            if int(ln.quantity) - int(ln.quantity_billed or 0) > 0
        ],
    )

    # Move the order bucket from received → open
    # Get or create the open order for this customer
    open_order = get_open_customer_order(db, customer_id, "open")
    if open_order is None:
        # Repurpose the received order as the open order
        received.bucket = "open"
        received.status = "open"
        received.updated_at = datetime.now(timezone.utc)
        for p in placements:
            p.status = "open"
    else:
        # Re-parent placements to the existing open order
        for p in placements:
            p.customer_order_id = open_order.id
            p.status = "open"
        open_order.updated_at = datetime.now(timezone.utc)
        # Close the (now empty) received order
        received.is_open = False

    return True


def get_open_unbilled_placement(db: Session, customer_id: int) -> CustomerOrderPlacement | None:
    """Latest open received placement with no billed lines — dealer’s one active order."""
    received = get_open_customer_order(db, customer_id, "received")
    if not received:
        return None
    placements = (
        db.query(CustomerOrderPlacement)
        .filter(
            CustomerOrderPlacement.customer_order_id == received.id,
            CustomerOrderPlacement.status == "received",
        )
        .order_by(CustomerOrderPlacement.placed_at.desc())
        .all()
    )
    for p in placements:
        lines = (
            db.query(CustomerOrderLine)
            .filter(CustomerOrderLine.placement_id == p.id, CustomerOrderLine.status.in_(["active", "billed"]))
            .all()
        )
        if not lines:
            return p
        if any(int(ln.quantity_billed or 0) > 0 for ln in lines):
            continue
        return p
    return None


def append_or_create_portal_placement(
    db: Session,
    *,
    customer_id: int,
    customer_name: str,
    catalog_product_id: int,
    quantity: int,
    unit_price: Decimal,
    customer_notes: str | None,
    addons_json: list | None = None,
) -> tuple[CustomerOrderPlacement, bool]:
    """Add line to the dealer’s open order, or create one. Returns (placement, merged)."""
    from app.services.catalog_addons import addon_snapshots_for_product

    placement = get_open_unbilled_placement(db, customer_id)
    if not placement:
        p = create_received_placement(
            db,
            customer_id=customer_id,
            customer_name=customer_name,
            lines=[{
                "catalog_product_id": catalog_product_id,
                "quantity": quantity,
                "unit_price": unit_price,
                "addons_json": addons_json,
            }],
            customer_notes=customer_notes,
        )
        return p, False

    prod = db.get(CatalogProduct, catalog_product_id)
    if not prod or not prod.is_active:
        raise ValueError(f"product {catalog_product_id} not found")

    existing = (
        db.query(CustomerOrderLine)
        .filter(
            CustomerOrderLine.placement_id == placement.id,
            CustomerOrderLine.catalog_product_id == catalog_product_id,
            CustomerOrderLine.status == "active",
        )
        .first()
    )
    if existing:
        edit_customer_placement_line_qty(
            db, existing.id, int(existing.quantity) + int(quantity), customer_name
        )
    else:
        addons = addons_json if addons_json is not None else addon_snapshots_for_product(db, prod.id)
        db.add(
            CustomerOrderLine(
                placement_id=placement.id,
                catalog_product_id=prod.id,
                our_product_id=prod.our_product_id,
                quantity=int(quantity),
                quantity_billed=0,
                unit_price=unit_price,
                addons_json=addons or None,
                status="active",
            )
        )
        reserve_stock(
            db,
            catalog_product_id=prod.id,
            our_product_id=prod.our_product_id,
            quantity=int(quantity),
            reference_id=placement.id,
            party=customer_name,
        )
        # CustomerOpenLine is populated at confirm time — see confirm_received_order.

    note = (customer_notes or "").strip()
    if note:
        prev = (placement.customer_notes or "").strip()
        placement.customer_notes = f"{prev}; {note}" if prev and note not in prev else (prev or note)

    order = db.get(CustomerOrder, placement.customer_order_id)
    if order:
        order.updated_at = datetime.now(timezone.utc)
    return placement, True


def create_portal_placement(
    db: Session,
    *,
    customer_id: int,
    customer_name: str,
    catalog_product_id: int,
    quantity: int,
    unit_price: Decimal,
    customer_notes: str | None,
    addons_json: list | None = None,
) -> CustomerOrderPlacement:
    placement, _merged = append_or_create_portal_placement(
        db,
        customer_id=customer_id,
        customer_name=customer_name,
        catalog_product_id=catalog_product_id,
        quantity=quantity,
        unit_price=unit_price,
        customer_notes=customer_notes,
        addons_json=addons_json,
    )
    return placement


def create_received_placement(
    db: Session,
    *,
    customer_id: int,
    customer_name: str,
    lines: list[dict],
    customer_notes: str | None = None,
    placed_on: date | None = None,
    allow_negative_stock: bool = False,
) -> CustomerOrderPlacement:
    """Create a received placement (portal or admin offline) — same path to bill later.

    allow_negative_stock: admin offline only — oversell goes through; on-hand may go negative.
    Portal must keep allow_negative_stock=False.
    """
    from app.services.biz_date import resolve_biz_dt
    from app.services.catalog_addons import addon_snapshots_for_product

    when = resolve_biz_dt(placed_on)
    cleaned: list[dict] = []
    for raw in lines:
        qty = int(raw.get("quantity") or 0)
        if qty <= 0:
            continue
        cid = int(raw["catalog_product_id"])
        prod = db.get(CatalogProduct, cid)
        if not prod or not prod.is_active:
            raise ValueError(f"product {cid} not found")
        from app.services.pricing import effective_selling_price

        unit_price = raw.get("unit_price")
        if unit_price is None:
            unit_price = effective_selling_price(prod.buying_price, prod.selling_price)
        else:
            unit_price = Decimal(str(unit_price))
        if unit_price is None:
            raise ValueError(f"sell price not set for {prod.our_product_id}")
        addons = raw.get("addons_json")
        if addons is None:
            addons = addon_snapshots_for_product(db, prod.id)
        cleaned.append(
            {
                "prod": prod,
                "quantity": qty,
                "unit_price": unit_price,
                "addons_json": addons or None,
            }
        )
    if not cleaned:
        raise ValueError("enter quantity on at least one line")

    # Pre-check stock — portal blocks; offline may proceed (on-hand can go negative)
    short: list[str] = []
    for item in cleaned:
        prod = item["prod"]
        qty = item["quantity"]
        bal = (
            db.query(StockBalance)
            .filter(StockBalance.catalog_product_id == prod.id)
            .first()
        )
        on_hand = int(bal.quantity_on_hand or 0) if bal else 0
        if on_hand < qty:
            short.append(f"{prod.our_product_id} (need {qty}, have {on_hand})")
    if short and not allow_negative_stock:
        raise ValueError("insufficient stock for " + "; ".join(short))

    received = get_or_create_customer_order(db, customer_id, "received", "received")
    placement = CustomerOrderPlacement(
        customer_order_id=received.id,
        status="received",
        customer_notes=customer_notes,
        placed_at=when,
    )
    db.add(placement)
    db.flush()

    for item in cleaned:
        prod = item["prod"]
        qty = item["quantity"]
        db.add(
            CustomerOrderLine(
                placement_id=placement.id,
                catalog_product_id=prod.id,
                our_product_id=prod.our_product_id,
                quantity=qty,
                quantity_billed=0,
                unit_price=item["unit_price"],
                addons_json=item["addons_json"],
                status="active",
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

    # CustomerOpenLine (the "Confirmed" bucket tally used for billing) is only populated
    # once staff explicitly confirms this order — see confirm_received_order. Until then it
    # only lives in "New" (received bucket), so it can't double-show under Confirmed.
    received.updated_at = when
    return placement
