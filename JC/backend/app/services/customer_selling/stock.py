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


def reserve_stock(
    db: Session,
    *,
    catalog_product_id: int,
    our_product_id: str,
    quantity: int,
    reference_id: int,
    party: str,
    allow_negative: bool = False,
    when: datetime | None = None,
    only_addon_ids: list[int] | None = None,
) -> None:
    reserve_stock_many(
        db,
        lines=[{
            "catalog_product_id": catalog_product_id,
            "our_product_id": our_product_id,
            "quantity": quantity,
        }],
        reference_id=reference_id,
        party=party,
        allow_negative=allow_negative,
        when=when,
        only_addons={catalog_product_id: only_addon_ids} if only_addon_ids is not None else None,
    )


def reserve_stock_many(
    db: Session,
    *,
    lines: list[dict],
    reference_id: int,
    party: str,
    allow_negative: bool = False,
    when: datetime | None = None,
    only_addons: dict[int, list[int]] | None = None,
) -> None:
    """Reserve several products in one lock, one ledger write, one add-on pass."""
    from app.models.addon_product import AddonProduct
    from app.models.catalog_addon_link import CatalogAddonLink
    from app.models.stock import StockLedger

    wanted = []
    for raw in lines:
        qty = int(raw.get("quantity") or 0)
        if qty <= 0:
            continue
        wanted.append((int(raw["catalog_product_id"]), str(raw.get("our_product_id") or ""), qty))
    if not wanted:
        return
    product_ids = list({cid for cid, _, _ in wanted})
    balances = {
        int(b.catalog_product_id): b
        for b in db.query(StockBalance)
        .filter(StockBalance.catalog_product_id.in_(product_ids))
        .with_for_update()
        .all()
    }
    for cid, our_product_id, qty in wanted:
        balance = balances.get(cid)
        if balance is None:
            balance = StockBalance(catalog_product_id=cid, quantity_on_hand=0)
            db.add(balance)
            db.flush()
            balances[cid] = balance
        on_hand = int(balance.quantity_on_hand or 0)
        if on_hand < qty and not allow_negative:
            raise ValueError(
                f"insufficient stock for {our_product_id} (need {qty}, have {on_hand})"
            )
        note = f"Customer order reserved {qty}"
        if allow_negative and on_hand < qty:
            note = f"Customer order reserved {qty} (oversell; had {on_hand})"
        balance.quantity_on_hand = on_hand - qty
        ledger_row = StockLedger(
            catalog_product_id=cid,
            entry_type="reserved",
            quantity_delta=-qty,
            balance_after=balance.quantity_on_hand,
            reference_type="customer_placement",
            reference_id=reference_id,
            party=party,
            notes=note,
        )
        if when is not None:
            ledger_row.created_at = when
        db.add(ledger_row)

    links = (
        db.query(CatalogAddonLink)
        .filter(CatalogAddonLink.catalog_product_id.in_(product_ids))
        .order_by(CatalogAddonLink.id.asc())
        .all()
    )
    if not links:
        return
    addon_ids = list({int(link.addon_product_id) for link in links})
    addons = {
        int(a.id): a
        for a in db.query(AddonProduct)
        .filter(AddonProduct.id.in_(addon_ids))
        .with_for_update()
        .all()
    }
    qty_by_product: dict[int, int] = {}
    name_by_product: dict[int, str] = {}
    for cid, name, qty in wanted:
        qty_by_product[cid] = qty_by_product.get(cid, 0) + qty
        name_by_product[cid] = name
    from app.models.addon_stock_ledger import AddonStockLedger

    for link in links:
        if only_addons is not None and int(link.catalog_product_id) in only_addons:
            if int(link.addon_product_id) not in set(only_addons[int(link.catalog_product_id)] or []):
                continue
        addon = addons.get(int(link.addon_product_id))
        if not addon or not addon.is_active or addon.deleted_at:
            continue
        units = qty_by_product.get(int(link.catalog_product_id), 0)
        delta = -(int(link.quantity or 1) * units)
        if delta == 0:
            continue
        addon.quantity_on_hand = int(addon.quantity_on_hand or 0) + delta
        ledger_row = AddonStockLedger(
            addon_product_id=addon.id,
            entry_type="customer_order",
            quantity_delta=delta,
            balance_after=addon.quantity_on_hand,
            reference_type="customer_placement",
            reference_id=reference_id,
            party=party,
            notes=f"Order for {name_by_product.get(int(link.catalog_product_id), '')} x{units}",
        )
        if when is not None:
            ledger_row.created_at = when
        db.add(ledger_row)

def restore_stock(db: Session, *, catalog_product_id: int, our_product_id: str, quantity: int, reference_id: int, party: str, notes: str, when: datetime | None = None, only_addon_ids: list[int] | None = None, reference_type: str = "customer_placement") -> None:
    if quantity <= 0:
        return
    add_stock(
        db,
        catalog_product_id=catalog_product_id,
        our_product_id=our_product_id,
        quantity=quantity,
        entry_type="unreserved",
        reference_type=reference_type,
        reference_id=reference_id,
        party=party,
        notes=notes,
        created_at=when,
    )
    deduct_addons_for_product(
        db,
        catalog_product_id=catalog_product_id,
        units=-quantity,
        reference_type=reference_type,
        reference_id=reference_id,
        party=party,
        note=notes,
        when=when,
        only_addon_ids=only_addon_ids,
    )

