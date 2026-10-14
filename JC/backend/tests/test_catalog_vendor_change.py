"""A product's vendor can be changed from the product edit form."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.activity_log import ActivityLog  # noqa: F401
from app.models.catalog_product import CatalogProduct
from app.models.entity_history import EntityHistory  # noqa: F401
from app.models.price_history import PriceHistory  # noqa: F401
from app.models.vendor import Vendor
from app.routers.catalog.bulk_create import update_product
from app.schemas.catalog import CatalogUpdate

AUTH = AuthContext(actor_type="admin", actor_id=1, actor_name="Test Admin")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)(), engine


def test_update_product_moves_it_to_another_vendor():
    db, engine = _db()
    try:
        first = Vendor(business_name="Old Press", phone="9000000001")
        second = Vendor(business_name="New Press", phone="9000000002")
        db.add_all([first, second])
        db.flush()
        product = CatalogProduct(
            our_product_id="1041 PATRIKA",
            vendor_id=first.id,
            vendor_product_id="V1",
            unit="pcs",
            buying_price=Decimal("10"),
        )
        db.add(product)
        db.commit()

        updated = update_product(
            product.id,
            CatalogUpdate(vendor_id=second.id),
            db,
            AUTH,
        )
        assert updated.vendor_id == second.id
        assert updated.vendor_name == "New Press"
        stored = db.get(CatalogProduct, product.id)
        assert stored.vendor_id == second.id
    finally:
        db.close()
        engine.dispose()
