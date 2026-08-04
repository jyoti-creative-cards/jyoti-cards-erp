from __future__ import annotations

from datetime import datetime, timezone
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


def _get_or_create_open_line(db: Session, customer_id: int, catalog_product_id: int, unit_price: Decimal) -> CustomerOpenLine:
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
    db.add(row)
    db.flush()
    return row


def add_to_customer_open(db: Session, customer_id: int, lines: list[tuple[int, int, Decimal]]) -> None:
    for catalog_product_id, qty, price in lines:
        if qty <= 0:
            continue
        row = _get_or_create_open_line(db, customer_id, catalog_product_id, price)
        row.quantity_received += qty
        row.quantity_open += qty
        row.status = "open"


def reserve_stock(db: Session, *, catalog_product_id: int, our_product_id: str, quantity: int, reference_id: int, party: str) -> None:
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
    if balance.quantity_on_hand < quantity:
        raise ValueError("insufficient stock")
    add_stock(
        db,
        catalog_product_id=catalog_product_id,
        our_product_id=our_product_id,
        quantity=-quantity,
        entry_type="reserved",
        reference_type="customer_placement",
        reference_id=reference_id,
        party=party,
        notes=f"Customer order reserved {quantity}",
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


def edit_customer_placement_line_qty(db: Session, line_id: int, new_qty: int, customer_name: str) -> CustomerOrderLine:
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
    if delta > 0:
        reserve_stock(
            db,
            catalog_product_id=line.catalog_product_id,
            our_product_id=line.our_product_id,
            quantity=delta,
            reference_id=placement.id,
            party=customer_name,
        )
        add_to_customer_open(db, order.customer_id, [(line.catalog_product_id, delta, line.unit_price)])
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
        open_row = (
            db.query(CustomerOpenLine)
            .filter(
                CustomerOpenLine.customer_id == order.customer_id,
                CustomerOpenLine.catalog_product_id == line.catalog_product_id,
            )
            .first()
        )
        if open_row:
            reduce = min(-delta, int(open_row.quantity_open))
            open_row.quantity_open = max(0, int(open_row.quantity_open) - reduce)
            open_row.quantity_received = max(open_row.quantity_billed, int(open_row.quantity_received) - reduce)
            if open_row.quantity_open <= 0 and open_row.quantity_billed <= 0:
                open_row.status = "cancelled"
    line.quantity = new_qty
    return line


def replace_received_placement(
    db: Session,
    *,
    placement_id: int,
    lines: list[dict],
    customer_notes: str | None,
    customer_name: str,
) -> CustomerOrderPlacement:
    """Full replace of an unbilled received placement (add / change qty / remove)."""
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
    for ln in existing:
        if int(ln.quantity_billed or 0) > 0:
            raise ValueError(f"{ln.our_product_id} already billed — cannot full-edit")

    desired: dict[int, int] = {}
    for raw in lines:
        qty = int(raw.get("quantity") or 0)
        if qty <= 0:
            continue
        cid = int(raw["catalog_product_id"])
        desired[cid] = desired.get(cid, 0) + qty

    if not desired:
        raise ValueError("enter quantity on at least one line")

    # Remove lines not in desired
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

        unit_price = effective_selling_price(prod.buying_price, prod.selling_price) or Decimal("0")
        if unit_price <= 0:
            raise ValueError(f"sell price not set for {prod.our_product_id}")
        if cid in by_cat:
            edit_customer_placement_line_qty(db, by_cat[cid].id, qty, customer_name)
        else:
            db.add(
                CustomerOrderLine(
                    placement_id=placement.id,
                    catalog_product_id=prod.id,
                    our_product_id=prod.our_product_id,
                    quantity=qty,
                    quantity_billed=0,
                    unit_price=unit_price,
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
            )
            add_to_customer_open(db, order.customer_id, [(prod.id, qty, unit_price)])

    placement.customer_notes = customer_notes
    order.updated_at = datetime.now(timezone.utc)
    return placement


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
        add_to_customer_open(db, customer_id, [(prod.id, int(quantity), unit_price)])

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
) -> CustomerOrderPlacement:
    """Create a received placement (portal or admin offline) — same path to bill later."""
    from app.services.catalog_addons import addon_snapshots_for_product

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
            unit_price = effective_selling_price(prod.buying_price, prod.selling_price) or Decimal("0")
        unit_price = Decimal(str(unit_price))
        if unit_price <= 0:
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

    received = get_or_create_customer_order(db, customer_id, "received", "received")
    placement = CustomerOrderPlacement(
        customer_order_id=received.id,
        status="received",
        customer_notes=customer_notes,
        placed_at=datetime.now(timezone.utc),
    )
    db.add(placement)
    db.flush()

    open_lines: list[tuple[int, int, Decimal]] = []
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
        )
        open_lines.append((prod.id, qty, item["unit_price"]))

    add_to_customer_open(db, customer_id, open_lines)
    received.updated_at = datetime.now(timezone.utc)
    return placement
