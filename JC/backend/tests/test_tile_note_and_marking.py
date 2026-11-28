"""A saved marking shows on the tile, and a tile note leaves with the order."""

from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.board import TileNote
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.stock import StockBalance
from app.models.vendor import Vendor
from app.routers.customer_orders import list_customer_orders
from app.routers.customer_orders.listing import _confirmed_tile
from app.services.customer_order_flow import confirm_received_order, create_received_placement
from app.services.customer_selling.marking import set_live_marking

AUTH = AuthContext(actor_type="admin", actor_id=1, actor_name="Test Admin")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _party(db):
    customer = Customer(business_name="Mehta", phone="9000001111", password_hash="x")
    vendor = Vendor(business_name="V", phone="9100001111")
    db.add_all([customer, vendor])
    db.flush()
    product = CatalogProduct(
        our_product_id="CARD-1", vendor_id=vendor.id, vendor_product_id="V1",
        buying_price=Decimal("10"), selling_price=Decimal("20"),
    )
    db.add(product)
    db.flush()
    db.add(StockBalance(catalog_product_id=product.id, quantity_on_hand=20))
    db.flush()
    return customer, product


def test_saved_marking_replaces_the_old_one_on_the_confirmed_tile():
    db = _db()
    customer, product = _party(db)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": product.id, "quantity": 2}],
    )
    confirm_received_order(db, customer.id)
    db.flush()
    creators, marks = _confirmed_tile(db, [customer.id])
    assert marks == {}
    set_live_marking(db, customer.id, kind="marking", text="Rush today")
    db.commit()
    _creators, marks = _confirmed_tile(db, [customer.id])
    assert marks[customer.id] == "Rush today"
    rows = list_customer_orders(bucket="open", day="all", db=db, auth=AUTH)
    assert rows[0].marking == "Rush today"
    set_live_marking(db, customer.id, kind="marking", text="")
    db.commit()
    _creators, marks = _confirmed_tile(db, [customer.id])
    assert marks == {}
    db.close()


def test_confirming_clears_the_new_note_and_leaves_other_notes():
    db = _db()
    customer, product = _party(db)
    other = Customer(business_name="Other", phone="9000002222", password_hash="x")
    db.add(other)
    db.flush()
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": product.id, "quantity": 1}],
    )
    db.add_all([
        TileNote(tile_key=f"co:received:{customer.id}", body="Call before packing", updated_by_name="Anita"),
        TileNote(tile_key=f"co:open:{customer.id}", body="Keep this", updated_by_name="Anita"),
        TileNote(tile_key=f"co:received:{other.id}", body="Someone else", updated_by_name="Anita"),
    ])
    db.commit()
    assert confirm_received_order(db, customer.id) is True
    db.commit()
    keys = {row.tile_key: row.body for row in db.query(TileNote).all()}
    assert f"co:received:{customer.id}" not in keys
    assert keys[f"co:open:{customer.id}"] == "Keep this"
    assert keys[f"co:received:{other.id}"] == "Someone else"
    db.close()
