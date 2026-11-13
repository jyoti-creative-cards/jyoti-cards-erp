"""Confirmed orders are only still-open confirmed placements. Items without an album stay out of albums."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement
from app.models.stock import StockBalance
from app.models.vendor import Vendor
from app.services.reports.confirmed_orders import confirmed_order_report
from app.services.reports.items_without_album import items_without_album

WHEN = datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_confirmed_report_skips_new_and_billed():
    db = _db()
    vendor = Vendor(business_name="V", phone="9998887771")
    db.add(vendor)
    db.flush()
    product = CatalogProduct(
        our_product_id="P", vendor_id=vendor.id, vendor_product_id="VP",
        buying_price=Decimal("1"), selling_price=Decimal("2"),
    )
    customer = Customer(business_name="C", phone="9998887772", password_hash="x")
    db.add_all([product, customer])
    db.flush()
    order = CustomerOrder(customer_id=customer.id, bucket="open", status="open")
    db.add(order)
    db.flush()

    def place(status, qty, billed):
        row = CustomerOrderPlacement(
            customer_order_id=order.id, status=status, placed_at=WHEN,
        )
        db.add(row)
        db.flush()
        db.add(CustomerOrderLine(
            placement_id=row.id, catalog_product_id=product.id, our_product_id="P",
            quantity=qty, quantity_billed=billed, unit_price=Decimal("2"), status="active",
        ))
        return row

    place("received", 10, 0)
    open_row = place("open", 8, 3)
    place("billed", 5, 5)
    db.commit()

    data = confirmed_order_report(db, on=None, from_date=None, to_date=None)
    assert [row["order_id"] for row in data["rows"]] == [open_row.id]
    assert data["rows"][0]["qty"] == 5
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
