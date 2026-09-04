from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.addon_product import AddonProduct
from app.models.addon_stock_ledger import AddonStockLedger
from app.models.catalog_addon_link import CatalogAddonLink


def add_addon_stock(
    db: Session,
    *,
    addon_product_id: int,
    quantity: int,
    entry_type: str,
    reference_type: str | None = None,
    reference_id: int | None = None,
    party: str | None = None,
    notes: str | None = None,
    created_by_name: str | None = None,
) -> AddonProduct:
    """Apply a signed quantity delta to an add-on's stock and log it. Never blocks —
    add-on stock is allowed to go negative, same philosophy as product stock."""
    addon = db.query(AddonProduct).filter(AddonProduct.id == addon_product_id).with_for_update().first()
    if not addon:
        raise ValueError(f"addon product {addon_product_id} not found")
    addon.quantity_on_hand = int(addon.quantity_on_hand or 0) + quantity
    db.add(
        AddonStockLedger(
            addon_product_id=addon_product_id,
            entry_type=entry_type,
            quantity_delta=quantity,
            balance_after=addon.quantity_on_hand,
            reference_type=reference_type,
            reference_id=reference_id,
            party=party,
            notes=notes,
            created_by_name=created_by_name,
        )
    )
    db.flush()
    return addon


def deduct_addons_for_product(
    db: Session,
    *,
    catalog_product_id: int,
    units: int,
    reference_type: str,
    reference_id: int,
    party: str | None = None,
    note: str | None = None,
) -> None:
    """Apply add-on stock movement for `units` of a catalog product being reserved
    (units > 0 shrinks add-on stock) or restored (units < 0 grows it back), based on
    each linked add-on's per-unit quantity. Called from the same choke points as
    catalog-product stock (reserve_stock / restore_stock) so it always mirrors it."""
    if not units:
        return
    links = db.query(CatalogAddonLink).filter(CatalogAddonLink.catalog_product_id == catalog_product_id).all()
    if not links:
        return
    entry_type = "customer_order" if units > 0 else "customer_order_restore"
    for link in links:
        delta = -(int(link.quantity or 1) * units)
        if delta == 0:
            continue
        try:
            add_addon_stock(
                db,
                addon_product_id=link.addon_product_id,
                quantity=delta,
                entry_type=entry_type,
                reference_type=reference_type,
                reference_id=reference_id,
                party=party,
                notes=note,
            )
        except ValueError:
            continue  # addon was deleted/missing — never block the customer order over it
