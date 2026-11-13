"""Confirmed orders are only still-open confirmed placements. Items without an album stay out of albums."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_order import CustomerOpenLine, CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.stock import StockBalance
from app.models.vendor import Vendor
from app.services.reports.confirmed_orders import confirmed_order_report
from app.services.reports.items_without_album import items_without_album

WHEN = datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_confirmed_report_skips_orders_already_billed():
    db = _db()
    vendor = Vendor(business_name="V", phone="9998887771")
    db.add(vendor)
    db.flush()
    product = CatalogProduct(
        our_product_id="P", vendor_id=vendor.id, vendor_product_id="VP",
        buying_price=Decimal("1"), selling_price=Decimal("2"),
    )
    still = Customer(business_name="Still", phone="9998887772", password_hash="x")
    billed = Customer(business_name="Billed", phone="9998887773", password_hash="x")
    db.add_all([product, still, billed])
    db.flush()
    order = CustomerOrder(customer_id=still.id, bucket="open", status="open", marking="Rush")
    done = CustomerOrder(customer_id=billed.id, bucket="open", status="open")
    db.add_all([order, done])
    db.flush()
    open_row = CustomerOrderPlacement(
        customer_order_id=order.id, status="open", placed_at=WHEN, customer_notes="Order placed by admin (phone)",
    )
    stale = CustomerOrderPlacement(customer_order_id=done.id, status="open", placed_at=WHEN)
    db.add_all([open_row, stale])
    db.flush()
    db.add(CustomerOrderLine(
        placement_id=open_row.id, catalog_product_id=product.id, our_product_id="P",
        quantity=8, quantity_billed=0, unit_price=Decimal("2"), status="active",
    ))
    db.add(CustomerOrderLine(
        placement_id=stale.id, catalog_product_id=product.id, our_product_id="P",
        quantity=5, quantity_billed=0, unit_price=Decimal("2"), status="active",
    ))
    db.add(CustomerOpenLine(
        customer_id=still.id, catalog_product_id=product.id, our_product_id="P",
        quantity_open=5, quantity_billed=3, unit_price=Decimal("2"), status="open",
    ))
    db.commit()

    data = confirmed_order_report(db, on=None, from_date=None, to_date=None)
    assert [row["party"] for row in data["rows"]] == ["Still"]
    assert data["rows"][0]["qty"] == 5
    assert data["rows"][0]["marking"] == "Rush"
    assert data["orders"][0]["confirmed_on"] == "2026-08-01"

    album_party = Customer(business_name="Album Party", phone="9998887774", password_hash="x")
    album = CatalogProduct(
        our_product_id="2027 ALBUM NO. 03", vendor_id=vendor.id, vendor_product_id="ALB",
        buying_price=Decimal("0"), selling_price=Decimal("0"),
    )
    db.add_all([album_party, album])
    db.flush()
    album_order = CustomerOrder(customer_id=album_party.id, bucket="open", status="open", is_open=True)
    db.add(album_order)
    db.flush()
    album_place = CustomerOrderPlacement(customer_order_id=album_order.id, status="open", placed_at=WHEN)
    db.add(album_place)
    db.flush()
    db.add(CustomerOpenLine(
        customer_id=album_party.id, catalog_product_id=album.id, our_product_id="2027 ALBUM NO. 03",
        quantity_open=1, unit_price=Decimal("0"), status="open",
    ))
    db.commit()
    hidden = confirmed_order_report(db, hide_catalogs=True)
    assert [row["party"] for row in hidden["orders"]] == ["Still"]
    shown = confirmed_order_report(db, hide_catalogs=False)
    assert "Album Party" in [row["party"] for row in shown["orders"]]
    db.close()


def test_items_without_album_skips_an_album():
    db = _db()
    vendor = Vendor(business_name="V", phone="9998887771")
    db.add(vendor)
    db.flush()
    loose = CatalogProduct(
        our_product_id="LOOSE", vendor_id=vendor.id, vendor_product_id="L",
        buying_price=Decimal("1"), selling_price=Decimal("4"),
    )
    filed = CatalogProduct(
        our_product_id="FILED", vendor_id=vendor.id, vendor_product_id="F",
        category="Album 1", buying_price=Decimal("1"), selling_price=Decimal("4"),
    )
    db.add_all([loose, filed])
    db.flush()
    db.add(StockBalance(catalog_product_id=loose.id, quantity_on_hand=3))
    db.commit()
    data = items_without_album(db)
    assert [row["item"] for row in data["items"]] == ["LOOSE"]
    assert data["items"][0]["stock"] == 3
    assert data["items"][0]["total_amount"] == "12.00"
    db.close()
