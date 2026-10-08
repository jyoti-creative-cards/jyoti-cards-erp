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

from app.services.customer_selling.buckets import get_or_create_customer_order
from app.services.customer_selling.confirm import get_open_unbilled_placement
from app.services.customer_selling.lines import edit_customer_placement_line_qty
from app.services.customer_selling.stock import reserve_stock

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
            order_source="app",
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
                addons_json=addons if addons is not None else None,
                status="active",
            )
        )
        from app.services.catalog_addons import kept_addon_ids

        reserve_stock(
            db,
            catalog_product_id=prod.id,
            our_product_id=prod.our_product_id,
            quantity=int(quantity),
            reference_id=placement.id,
            party=customer_name,
            only_addon_ids=kept_addon_ids(addons) if addons is not None else None,
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
    order_source: str | None = None,
    placed_by_name: str | None = None,
) -> CustomerOrderPlacement:
    """Create a received placement (portal or admin offline) — same path to bill later.

    allow_negative_stock: admin offline only — oversell goes through; on-hand may go negative.
    Portal must keep allow_negative_stock=False.
    """
    from app.services.biz_date import resolve_biz_dt
    from app.services.catalog_addons import addon_snapshots_map, kept_addon_ids

    when = resolve_biz_dt(placed_on)
    wanted: list[tuple[int, int, object]] = []
    for raw in lines:
        qty = int(raw.get("quantity") or 0)
        if qty <= 0:
            continue
        wanted.append((int(raw["catalog_product_id"]), qty, raw))
    if not wanted:
        raise ValueError("enter quantity on at least one line")
    product_ids = list({cid for cid, _, _ in wanted})
    products = {
        p.id: p
        for p in db.query(CatalogProduct).filter(CatalogProduct.id.in_(product_ids)).all()
    }
    addon_map = addon_snapshots_map(db, product_ids)
    from app.services.pricing import effective_selling_price

    cleaned: list[dict] = []
    for cid, qty, raw in wanted:
        prod = products.get(cid)
        if not prod or not prod.is_active:
            raise ValueError(f"product {cid} not found")
        unit_price = raw.get("unit_price")
        if unit_price is None:
            unit_price = effective_selling_price(prod.buying_price, prod.selling_price)
        else:
            unit_price = Decimal(str(unit_price))
        if unit_price is None:
            raise ValueError(f"sell price not set for {prod.our_product_id}")
        addons = raw.get("addons_json")
        if addons is None:
            addons = list(addon_map.get(prod.id) or [])
        skip = {int(x) for x in (raw.get("skip_addon_ids") or [])}
        if skip:
            addons = [a for a in addons if int(a.get("addon_product_id") or 0) not in skip]
        cleaned.append(
            {
                "prod": prod,
                "quantity": qty,
                "unit_price": unit_price,
                "addons_json": addons,
            }
        )

    # Pre-check stock — portal blocks; offline may proceed (on-hand can go negative)
    balances = {
        int(b.catalog_product_id): int(b.quantity_on_hand or 0)
        for b in db.query(StockBalance).filter(StockBalance.catalog_product_id.in_(product_ids)).all()
    }
    short: list[str] = []
    for item in cleaned:
        prod = item["prod"]
        qty = item["quantity"]
        on_hand = balances.get(prod.id, 0)
        if on_hand < qty:
            short.append(f"{prod.our_product_id} (need {qty}, have {on_hand})")
    if short and not allow_negative_stock:
        raise ValueError("insufficient stock for " + "; ".join(short))

    received = get_or_create_customer_order(db, customer_id, "received", "received")
    placement = CustomerOrderPlacement(
        customer_order_id=received.id,
        status="received",
        customer_notes=customer_notes,
        order_source=order_source,
        placed_by_name=(placed_by_name or "").strip() or None,
        placed_at=when,
    )
    db.add(placement)
    db.flush()

    for item in cleaned:
        prod = item["prod"]
        db.add(
            CustomerOrderLine(
                placement_id=placement.id,
                catalog_product_id=prod.id,
                our_product_id=prod.our_product_id,
                quantity=item["quantity"],
                quantity_billed=0,
                unit_price=item["unit_price"],
                addons_json=item["addons_json"],
                status="active",
            )
        )
    from app.services.customer_selling.stock import reserve_stock_many

    reserve_stock_many(
        db,
        lines=[
            {
                "catalog_product_id": item["prod"].id,
                "our_product_id": item["prod"].our_product_id,
                "quantity": item["quantity"],
            }
            for item in cleaned
        ],
        reference_id=placement.id,
        party=customer_name,
        allow_negative=allow_negative_stock,
        when=when,
        only_addons={
            int(item["prod"].id): kept_addon_ids(item["addons_json"]) or []
            for item in cleaned
        },
    )

    # CustomerOpenLine (the "Confirmed" bucket tally used for billing) is only populated
    # once staff explicitly confirms this order — see confirm_received_order. Until then it
    # only lives in "New" (received bucket), so it can't double-show under Confirmed.
    # NB: updated_at tracks when this hit the queue (real time) for Today/Past scoping —
    # not the (possibly backdated) business date `when`/`placed_on`, which only affects
    # placement.placed_at for reporting. A backdated admin entry should land in "Past",
    # not silently masquerade as "Today".
    received.updated_at = datetime.now(timezone.utc)
    return placement

