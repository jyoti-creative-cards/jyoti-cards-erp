from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.addon_product import AddonProduct
from app.models.bill_series import BillSeries
from app.models.catalog_addon_link import CatalogAddonLink
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.customer_order import CustomerOrder, CustomerOrderPlacement
from app.models.stock import StockBalance, StockReceipt
from app.models.vendor import Vendor
from app.schemas.stock import VendorBillIn, VendorReceiptLineIn, VendorReceiveCreate
from app.services.customer_bill_process import close_bill_line, process_customer_bill
from app.services.customer_order_flow import confirm_received_order, create_received_placement
from app.services.document_present import is_locked, present
from app.services.vendor_receive_bill import bill_receipt, receive_vendor_goods

AUTH = AuthContext(actor_type="admin", actor_id=1, actor_name="Test Admin")


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _vendor(db) -> Vendor:
    vendor = Vendor(business_name="V1", phone="9998887771")
    db.add(vendor)
    db.flush()
    return vendor


def _setup(db, on_hand: int = 100) -> tuple[Customer, CatalogProduct, Vendor]:
    vendor = _vendor(db)
    prod = CatalogProduct(
        our_product_id="P1",
        vendor_id=vendor.id,
        vendor_product_id="VP1",
        buying_price=Decimal("10"),
        selling_price=Decimal("20"),
    )
    db.add(prod)
    db.flush()
    db.add(StockBalance(catalog_product_id=prod.id, quantity_on_hand=on_hand))
    customer = Customer(business_name="C1", phone="9998887772", password_hash="x")
    db.add(customer)
    db.flush()
    return customer, prod, vendor


def _vendor_and_product(db) -> tuple[Vendor, CatalogProduct]:
    vendor = _vendor(db)
    prod = CatalogProduct(
        our_product_id="VP-1",
        vendor_id=vendor.id,
        vendor_product_id="VV-1",
        buying_price=Decimal("10"),
    )
    db.add(prod)
    db.flush()
    db.add(StockBalance(catalog_product_id=prod.id, quantity_on_hand=0))
    db.flush()
    return vendor, prod


def _bill_series(db, name="T", prefix="T") -> BillSeries:
    series = BillSeries(name=name, prefix=prefix, start_num=1, end_num=999, current_num=0, is_active=True)
    db.add(series)
    db.flush()
    return series


def test_saved_customer_bill_keeps_card_after_rename(db):
    customer, prod, _ = _setup(db)
    create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    confirm_received_order(db, customer.id)
    bill = process_customer_bill(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines_in=[{"catalog_product_id": prod.id, "quantity_to_ship": 2}],
        overall_discount_percent=None,
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        freight_agent_id=None,
        freight_charges=None,
        packaging_charges=None,
        additional_charges=None,
        bill_series_id=_bill_series(db).id,
        narration=None,
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        transport_mode="self_pickup",
    )
    db.flush()
    before = present(db, "customer_bill", bill)
    prod.our_product_id = "RENAMED"
    prod.category = "NEW-CAT"
    db.flush()
    after = present(db, "customer_bill", bill)
    assert after["locked"] is True
    assert after["lines"][0]["our_product_id"] == before["lines"][0]["our_product_id"]
    assert after["lines"][0]["our_product_id"] != "RENAMED"
    assert after["lines"][0].get("category") != "NEW-CAT"


def test_open_order_follows_rename(db):
    customer, prod, _ = _setup(db)
    placement = create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    db.flush()
    prod.our_product_id = "RENAMED"
    db.flush()
    view = present(db, "customer_order", placement)
    assert view["locked"] is False
    assert view["lines"][0]["our_product_id"] == "RENAMED"


def test_open_order_uses_live_addons_and_price(db):
    customer, prod, vendor = _setup(db)
    old_addon = AddonProduct(
        our_product_id="A1",
        vendor_id=vendor.id,
        vendor_product_id="VA1",
        name="Old Addon",
        unit="pc",
        buying_price=Decimal("1"),
    )
    new_addon = AddonProduct(
        our_product_id="A2",
        vendor_id=vendor.id,
        vendor_product_id="VA2",
        name="New Addon",
        unit="box",
        buying_price=Decimal("2"),
    )
    db.add_all([old_addon, new_addon])
    db.flush()
    db.add(CatalogAddonLink(catalog_product_id=prod.id, addon_product_id=old_addon.id, quantity=2))
    db.flush()

    placement = create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    db.flush()

    db.query(CatalogAddonLink).filter(CatalogAddonLink.catalog_product_id == prod.id).delete()
    db.add(CatalogAddonLink(catalog_product_id=prod.id, addon_product_id=new_addon.id, quantity=5))
    prod.selling_price = Decimal("25")
    db.flush()

    view = present(db, "customer_order", placement)
    assert view["locked"] is False
    assert view["lines"][0]["addons"] == [
        {
            "addon_product_id": new_addon.id,
            "our_product_id": "A2",
            "name": "New Addon",
            "quantity": 5,
            "unit": "box",
            "image_url": None,
        }
    ]
    assert view["lines"][0]["unit_price"] == "25"
    assert view["lines"][0]["selling_price"] == "25"


def test_backdated_received_order_uses_business_date_in_hub(db):
    from app.routers.customer_orders import list_customer_orders

    customer, prod, _ = _setup(db)
    placement = create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 1}],
        placed_on=date.today() - timedelta(days=1),
    )
    db.commit()

    today_rows = list_customer_orders(bucket="received", day="today", db=db, auth=AUTH)
    assert not any(row.customer_id == customer.id for row in today_rows)

    all_rows = list_customer_orders(bucket="received", day="all", db=db, auth=AUTH)
    row = next(row for row in all_rows if row.customer_id == customer.id)
    assert row.display_date == placement.placed_at
    assert row.updated_at == placement.placed_at


def test_soft_deleted_customer_bill_stays_out_of_billed_hub(db):
    from app.routers.customer_orders import list_customer_orders

    customer, _prod, _ = _setup(db)
    bill = CustomerBill(
        customer_id=customer.id,
        bill_number="B-DELETED-1",
        subtotal_inclusive=Decimal("100"),
        grand_total=Decimal("100"),
        created_by_type="admin",
        created_by_name="Test Admin",
        bill_date=date.today(),
        deleted_at=datetime.now(timezone.utc),
        deleted_reason="voided",
        deleted_by_name="Test Admin",
    )
    db.add(bill)
    db.commit()

    rows = list_customer_orders(bucket="billed", day="all", db=db, auth=AUTH)
    assert not any(row.customer_id == customer.id for row in rows)


def test_null_bill_date_stays_in_all_but_not_today(db):
    from app.routers.customer_orders import list_customer_orders

    customer, _prod, _ = _setup(db)
    created_at = datetime.now(timezone.utc) - timedelta(days=2)
    bill = CustomerBill(
        customer_id=customer.id,
        bill_number="B-NO-DATE-1",
        subtotal_inclusive=Decimal("100"),
        grand_total=Decimal("100"),
        created_by_type="admin",
        created_by_name="Test Admin",
        bill_date=None,
        created_at=created_at,
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)

    all_rows = list_customer_orders(bucket="billed", day="all", db=db, auth=AUTH)
    row = next(row for row in all_rows if row.customer_id == customer.id)
    assert row.display_date == bill.created_at
    assert row.updated_at == bill.created_at

    today_rows = list_customer_orders(bucket="billed", day="today", db=db, auth=AUTH)
    assert not any(today_row.customer_id == customer.id for today_row in today_rows)


def test_backdated_vendor_order_uses_business_date_in_hub(db):
    from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement
    from app.routers.vendor_orders import list_vendor_orders

    vendor, prod = _vendor_and_product(db)
    placed_at = datetime.now(timezone.utc) - timedelta(days=2)
    order = VendorOrder(vendor_id=vendor.id, bucket="placed", status="placed", is_open=True)
    db.add(order)
    db.flush()
    placement = VendorOrderPlacement(
        vendor_order_id=order.id,
        status="placed",
        placed_by_type="admin",
        placed_by_name="Test",
        placed_at=placed_at,
    )
    db.add(placement)
    db.flush()
    db.add(
        VendorOrderLine(
            placement_id=placement.id,
            catalog_product_id=prod.id,
            our_product_id=prod.our_product_id,
            quantity=10,
            quantity_remaining=10,
            buying_price=Decimal("10"),
        )
    )
    db.commit()

    today_rows = list_vendor_orders(bucket="placed", view="default", day="today", db=db, auth=AUTH)
    assert not any(row.vendor_id == vendor.id for row in today_rows)

    all_rows = list_vendor_orders(bucket="placed", view="default", day="all", db=db, auth=AUTH)
    row = next(row for row in all_rows if row.vendor_id == vendor.id)
    assert row.display_date == placement.placed_at
    assert row.updated_at == placement.placed_at


def test_backdated_vendor_open_order_stays_out_of_today_bucket(db):
    from app.models.vendor_open_line import VendorOpenLine
    from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement
    from app.routers.vendor_orders import list_vendor_orders

    vendor, prod = _vendor_and_product(db)
    placed_at = datetime.now(timezone.utc) - timedelta(days=1)
    order = VendorOrder(vendor_id=vendor.id, bucket="placed", status="placed", is_open=True)
    db.add(order)
    db.flush()
    placement = VendorOrderPlacement(
        vendor_order_id=order.id,
        status="placed",
        placed_by_type="admin",
        placed_by_name="Test",
        placed_at=placed_at,
    )
    db.add(placement)
    db.flush()
    db.add(
        VendorOrderLine(
            placement_id=placement.id,
            catalog_product_id=prod.id,
            our_product_id=prod.our_product_id,
            quantity=10,
            quantity_remaining=10,
            buying_price=Decimal("10"),
        )
    )
    db.add(
        VendorOpenLine(
            vendor_id=vendor.id,
            catalog_product_id=prod.id,
            our_product_id=prod.our_product_id,
            quantity=10,
            buying_price=Decimal("10"),
            status="open",
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    today_rows = list_vendor_orders(bucket="open", view="default", day="today", db=db, auth=AUTH)
    assert not any(row.vendor_id == vendor.id for row in today_rows)

    all_rows = list_vendor_orders(bucket="open", view="default", day="all", db=db, auth=AUTH)
    row = next(row for row in all_rows if row.vendor_id == vendor.id and row.open_kind == "to_receive")
    assert row.display_date == placement.placed_at
    assert row.updated_at == placement.placed_at


def test_closed_customer_order_locks_by_parent_bucket(db):
    customer, prod, _ = _setup(db)
    placement = create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    order = db.get(CustomerOrder, placement.customer_order_id)
    order.bucket = "closed"
    db.flush()
    view = present(db, "customer_order", placement)
    assert is_locked("customer_order", placement) is True
    assert view["locked"] is True
    assert view["status"] == "closed"


def test_closed_bill_line_freezes_customer_order_card(db):
    customer, prod, _ = _setup(db)
    create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    confirm_received_order(db, customer.id)
    bill = process_customer_bill(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines_in=[{"catalog_product_id": prod.id, "quantity_to_ship": 2}],
        overall_discount_percent=None,
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        freight_agent_id=None,
        freight_charges=None,
        packaging_charges=None,
        additional_charges=None,
        bill_series_id=_bill_series(db).id,
        narration=None,
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
        transport_mode="self_pickup",
    )
    db.flush()
    bill_line = db.query(CustomerBillLine).filter(CustomerBillLine.bill_id == bill.id).one()
    old_billed_price = str(bill_line.unit_price)
    prod.selling_price = Decimal("99")
    db.flush()
    close_bill_line(db, bill_line.id, "dispatched")
    db.flush()

    closed_order = (
        db.query(CustomerOrder)
        .filter(CustomerOrder.customer_id == customer.id, CustomerOrder.bucket == "closed")
        .one()
    )
    placement = (
        db.query(CustomerOrderPlacement)
        .filter_by(customer_order_id=closed_order.id, status="closed")
        .one()
    )
    before = present(db, "customer_order", placement)
    prod.our_product_id = "RENAMED"
    prod.category = "NEW-CAT"
    db.flush()
    after = present(db, "customer_order", placement)
    assert before["status"] == "closed"
    assert after["status"] == "closed"
    assert after["locked"] is True
    assert before["lines"][0]["unit_price"] == old_billed_price
    assert before["lines"][0]["unit_price"] != "99"
    assert after["lines"][0]["unit_price"] == old_billed_price
    assert after["lines"][0]["unit_price"] != "99"
    assert after["lines"][0]["our_product_id"] == before["lines"][0]["our_product_id"]
    assert after["lines"][0]["our_product_id"] != "RENAMED"
    assert after["lines"][0]["category"] == before["lines"][0]["category"]
    assert after["lines"][0]["category"] != "NEW-CAT"


def test_is_locked_covers_document_kinds():
    assert is_locked("customer_bill", SimpleNamespace(id=1)) is True
    assert is_locked("vendor_bill", SimpleNamespace(bill_status="billed")) is True
    assert is_locked("vendor_order", SimpleNamespace(status="open", order=SimpleNamespace(bucket="closed"))) is True
    assert is_locked("customer_receipt", SimpleNamespace()) is False
    assert is_locked("debit_note", SimpleNamespace()) is False
    assert is_locked("expense", SimpleNamespace()) is False
    assert is_locked("payment", SimpleNamespace()) is False
    assert is_locked("freight", SimpleNamespace()) is False
    assert is_locked("customer_return", SimpleNamespace()) is False


def test_vendor_bill_locks_and_receipt_stays_live(db):
    vendor, prod = _vendor_and_product(db)
    body = VendorReceiveCreate(
        vendor_id=vendor.id,
        lines=[VendorReceiptLineIn(catalog_product_id=prod.id, quantity_received=5)],
        order_receipt_number="R1",
    )
    receive_vendor_goods(db, AUTH, body, offline=True)
    receipt = db.query(StockReceipt).one()

    prod.our_product_id = "RENAMED"
    db.flush()
    live = present(db, "vendor_receipt", receipt)
    assert live["locked"] is False
    assert live["lines"][0]["our_product_id"] == "RENAMED"

    prod.our_product_id = "AT-BILL"
    db.flush()
    bill_receipt(
        db,
        AUTH,
        receipt.id,
        VendorBillIn(
            total_billed_amount=Decimal("50"),
            lines=[{"catalog_product_id": prod.id, "quantity_billed": 5}],
        ),
    )
    db.flush()

    prod.our_product_id = "AFTER"
    db.flush()
    locked = present(db, "vendor_bill", receipt)
    assert locked["locked"] is True
    assert locked["lines"][0]["our_product_id"] == "AT-BILL"

    again = present(db, "vendor_receipt", receipt)
    assert again["lines"][0]["our_product_id"] == "AFTER"
