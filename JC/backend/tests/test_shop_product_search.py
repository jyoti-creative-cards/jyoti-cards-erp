"""Customer search matches our item number only."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.catalog_product import CatalogProduct
from app.models.vendor import Vendor
from app.routers.shop.list_order_history import _query_products, _portal_stock_status, _rank_products, stock_status_for_wanted


def test_our_item_number_ranks_above_the_same_vendor_code():
    box = CatalogProduct(our_product_id="6734 BOX PATRIKA", vendor_id=1, vendor_product_id="G-42")
    card = CatalogProduct(our_product_id="9073 CARD", vendor_id=1, vendor_product_id="6734")
    ranked = _rank_products([card, box], "6734")
    assert ranked[0].our_product_id == "6734 BOX PATRIKA"


def test_search_returns_the_item_number_not_only_the_vendor_code():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    vendor = Vendor(business_name="Mill", phone="9000000673")
    db.add(vendor)
    db.flush()
    db.add(CatalogProduct(
        our_product_id="9073 CARD", vendor_id=vendor.id, vendor_product_id="6734",
        year_group="2026-27", image_keys=[],
    ))
    db.add(CatalogProduct(
        our_product_id="6734 BOX PATRIKA", vendor_id=vendor.id, vendor_product_id="G-42",
        year_group="2026-27", image_keys=[],
    ))
    db.add(CatalogProduct(
        our_product_id="6734 OLD PATRIKA", vendor_id=vendor.id, vendor_product_id="OLD",
        year_group="2015-25", image_keys=[],
    ))
    db.commit()
    found = _query_products(db, "6734", 20)
    assert [row.our_product_id for row in found] == ["6734 BOX PATRIKA"]
    assert _query_products(db, "G-42", 20) == []
    assert _query_products(db, "6734 OLD", 20) == []


def test_stock_follows_the_quantity_the_customer_asked_for():
    assert stock_status_for_wanted(120, 50) == "in_stock"
    assert stock_status_for_wanted(40, 50) == "low_stock"
    assert stock_status_for_wanted(0, 50) == "out_of_stock"
    assert stock_status_for_wanted(-3, 50) == "out_of_stock"
    assert _portal_stock_status(299, 300) == "low_stock"
    assert _portal_stock_status(300, 300) == "in_stock"
    assert _portal_stock_status(0, 300) == "out_of_stock"
