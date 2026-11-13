"""A product bill is not a catalogue, and a confirmed tile names one creator."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOrder, CustomerOrderPlacement
from app.models.our_catalog import OurCatalog, OurCatalogIssue
from app.models.vendor import Vendor
from app.models.catalog_product import CatalogProduct
from app.routers.customer_orders.listing import _confirmed_tile
from app.services.our_catalogs.core import for_customer

WHEN = datetime(2026, 8, 2, 6, 0, tzinfo=timezone.utc)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_card_bills_do_not_count_as_catalogue_copies():
    db = _db()
    vendor = Vendor(business_name="V", phone="1")
    db.add(vendor)
    db.flush()
    card = CatalogProduct(
        our_product_id="5455 PATRIKA", vendor_id=vendor.id, vendor_product_id="A",
        category="ALBUM NO. 03", selling_price=Decimal("1"),
    )
    album = CatalogProduct(
        our_product_id="2027 ALBUM NO. 03", vendor_id=vendor.id, vendor_product_id="B",
        category="CATELOGUE", selling_price=Decimal("0"),
    )
    customer = Customer(business_name="Press", phone="2", password_hash="x")
    db.add_all([card, album, customer])
    db.flush()
    catalog = OurCatalog(name="2027 ALBUM NO. 03", copies_made=10)
    db.add(catalog)
    db.flush()
    bill = CustomerBill(
        customer_id=customer.id, bill_number="A1",
        subtotal_inclusive=Decimal("3"), discount_amount=0, taxable_value=Decimal("3"),
        gst_amount=0, grand_total=Decimal("3"),
        created_by_type="staff", created_by_name="Raj", bill_date=WHEN.date(),
    )
    db.add(bill)
    db.flush()
    db.add(CustomerBillLine(
        bill_id=bill.id, catalog_product_id=card.id, our_product_id=card.our_product_id,
        quantity_shipped=3, unit_price=Decimal("1"), line_total=Decimal("3"), status="billed",
    ))
    db.add(CustomerBillLine(
        bill_id=bill.id, catalog_product_id=album.id, our_product_id=album.our_product_id,
        quantity_shipped=1, unit_price=Decimal("0"), line_total=Decimal("0"), status="billed",
    ))
    db.add(OurCatalogIssue(
        catalog_id=catalog.id, customer_id=customer.id, copies=3, price=0,
        bill_id=bill.id, issued_on=WHEN.date(), note="From bill A1",
    ))
    db.commit()
    rows = for_customer(db, customer.id)
    assert len(rows) == 1
    assert rows[0]["received"] == 1
    assert rows[0]["copies_left"] == 9
    db.close()


def test_confirmed_tile_uses_the_latest_open_placement_only():
    db = _db()
    customer = Customer(business_name="C", phone="3", password_hash="x")
    db.add(customer)
    db.flush()
    order = CustomerOrder(customer_id=customer.id, bucket="open", status="open", marking="old carried note")
    db.add(order)
    db.flush()
    db.add(CustomerOrderPlacement(
        customer_order_id=order.id, status="billed", placed_by_name="Fiza",
        customer_notes="old note", placed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    ))
    db.add(CustomerOrderPlacement(
        customer_order_id=order.id, status="open", placed_by_name="Raj",
        customer_notes="Order placed by admin (phone)",
        placed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    ))
    db.commit()
    creators, marks = _confirmed_tile(db, [customer.id])
    assert creators[customer.id] == ["Raj"]
    assert marks == {}
    db.close()
