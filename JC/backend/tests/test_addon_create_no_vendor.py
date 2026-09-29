"""Add-on create needs only a name and an opening quantity. Year groups come from products."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.activity_log import ActivityLog  # noqa: F401
from app.models.addon_product import AddonProduct
from app.models.addon_stock_ledger import AddonStockLedger  # noqa: F401
from app.models.catalog_product import CatalogProduct
from app.models.entity_history import EntityHistory  # noqa: F401
from app.models.price_history import PriceHistory  # noqa: F401
from app.models.vendor import Vendor
from app.routers.addons import create_addon, update_addon
from app.routers.catalog import list_product_year_groups
from app.schemas.addon import AddonCreate, AddonUpdate

AUTH = AuthContext(actor_type="admin", actor_id=1, actor_name="Test Admin")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)(), engine


def test_create_addon_without_vendor_sets_opening_quantity():
    db, engine = _db()
    try:
        assert "jc_catalog_lookups" not in inspect(engine).get_table_names()
        row = create_addon(AddonCreate(our_product_id="FLOWER", quantity=12), db, AUTH)
        assert row.vendor_id is None
        assert row.vendor_product_id == ""
        assert row.unit == "pcs"
        assert row.buying_price in ("0.00", "0")
        assert row.quantity_on_hand == 12
        stored = db.get(AddonProduct, row.id)
        assert stored.quantity_on_hand == 12
        assert stored.vendor_id is None
    finally:
        db.close()
        engine.dispose()


def test_rename_addon():
    db, engine = _db()
    try:
        created = create_addon(AddonCreate(our_product_id="DORI", quantity=0), db, AUTH)
        updated = update_addon(created.id, AddonUpdate(our_product_id="RIBBON", description="red"), db, AUTH)
        assert updated.our_product_id == "RIBBON"
        assert updated.description == "red"
    finally:
        db.close()
        engine.dispose()


def test_year_groups_come_from_products():
    db, engine = _db()
    try:
        vendor = Vendor(business_name="Self", phone="9000000001")
        db.add(vendor)
        db.flush()
        db.add(CatalogProduct(
            our_product_id="1041 PATRIKA",
            vendor_id=vendor.id,
            vendor_product_id="V1",
            category="ALBUM NO. 01",
            unit="pcs",
            year_group="2025-26",
            buying_price=1,
        ))
        db.commit()
        years = list_product_year_groups(db)
        assert years[0] == "2025-26"
        assert "2026-27" in years
    finally:
        db.close()
        engine.dispose()
