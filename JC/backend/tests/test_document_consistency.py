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
from app.services.customer_bill_process import cancel_customer_bill, close_bill_line, process_customer_bill
from app.services.customer_order_flow import confirm_received_order, create_received_placement
from app.services.document_present import is_locked, present
from app.services.ledger import build_customer_ledger
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


def test_open_vendor_without_placed_placement_lists_in_all_not_today(db):
    """Open qty from add_to_open (e.g. receipt restore) with no status=placed placement."""
    from app.models.vendor_open_line import VendorOpenLine
    from app.routers.vendor_orders import list_vendor_orders

    vendor, prod = _vendor_and_product(db)
    db.add(
        VendorOpenLine(
            vendor_id=vendor.id,
            catalog_product_id=prod.id,
            our_product_id=prod.our_product_id,
            quantity=5,
            buying_price=Decimal("10"),
            status="open",
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    today_rows = list_vendor_orders(bucket="open", view="default", day="today", db=db, auth=AUTH)
    assert not any(
        row.vendor_id == vendor.id and row.open_kind == "to_receive" for row in today_rows
    )

    all_rows = list_vendor_orders(bucket="open", view="default", day="all", db=db, auth=AUTH)
    row = next(row for row in all_rows if row.vendor_id == vendor.id and row.open_kind == "to_receive")
    assert row.display_date is None
    assert row.total_quantity == 5


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


def test_locked_customer_bill_pdf_keeps_card_party_and_product(db, monkeypatch):
    from app.services import doc_gen

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
    old_party = customer.business_name
    old_code = prod.our_product_id
    customer.business_name = "RENAMED-CUSTOMER"
    prod.our_product_id = "RENAMED"
    db.flush()

    captured: dict = {}

    def _capture_pdf(**kw):
        captured.update(kw)
        return b"%PDF-fake%"

    monkeypatch.setattr(doc_gen, "render_customer_bill_pdf", _capture_pdf)
    monkeypatch.setattr(doc_gen, "upload_bytes", lambda *a, **kw: None)
    monkeypatch.setattr(doc_gen, "presigned_urls", lambda keys: [])

    doc_gen.generate_customer_bill_document(db, bill.id)

    assert captured["customer_name"] == old_party
    assert captured["customer_name"] != "RENAMED-CUSTOMER"
    line_codes = [
        ln.get("our_product_id") or ln.get("name")
        for ln in (captured["totals"].get("lines") or [])
        if isinstance(ln, dict)
    ]
    assert old_code in line_codes
    assert "RENAMED" not in line_codes


def test_debit_note_stays_live_while_vendor_bill_locks(db):
    from app.schemas.debit_note import DebitNoteIn
    from app.services.debit_notes import create_debit_note

    vendor, prod = _vendor_and_product(db)
    body = VendorReceiveCreate(
        vendor_id=vendor.id,
        lines=[VendorReceiptLineIn(catalog_product_id=prod.id, quantity_received=5)],
        order_receipt_number="DN-R1",
    )
    receive_vendor_goods(db, AUTH, body, offline=True)
    receipt = db.query(StockReceipt).one()

    note = create_debit_note(
        db,
        AUTH,
        vendor_id=vendor.id,
        receipt_id=receipt.id,
        body=DebitNoteIn(
            note_type="item",
            direction="short",
            catalog_product_id=prod.id,
            quantity=1,
        ),
    )
    db.flush()

    prod.our_product_id = "RENAMED-1"
    db.flush()
    live = present(db, "debit_note", note)
    assert live["locked"] is False
    assert live["lines"][0]["our_product_id"] == "RENAMED-1"

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
    db.refresh(receipt)

    frozen_at_bill = present(db, "vendor_bill", receipt)["lines"][0]["our_product_id"]
    assert frozen_at_bill == "RENAMED-1"

    prod.our_product_id = "RENAMED-2"
    db.flush()
    locked_bill = present(db, "vendor_bill", receipt)
    assert locked_bill["locked"] is True
    assert locked_bill["lines"][0]["our_product_id"] == "RENAMED-1"
    assert locked_bill["lines"][0]["our_product_id"] != "RENAMED-2"

    still_live = present(db, "debit_note", note)
    assert still_live["locked"] is False
    assert still_live["lines"][0]["our_product_id"] == "RENAMED-2"


def test_item_report_groups_by_id_and_uses_present_labels(db):
    from app.services.reports_extended import item_wise_purchases, item_wise_sales

    customer, prod, vendor = _setup(db)
    old_code = prod.our_product_id
    create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    confirm_received_order(db, customer.id)
    process_customer_bill(
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

    prod.our_product_id = "RENAMED"
    db.flush()

    receive_vendor_goods(
        db,
        AUTH,
        VendorReceiveCreate(
            vendor_id=vendor.id,
            lines=[VendorReceiptLineIn(catalog_product_id=prod.id, quantity_received=3)],
            order_receipt_number="R-ITEM-1",
        ),
        offline=True,
    )
    receipt = db.query(StockReceipt).one()
    bill_receipt(
        db,
        AUTH,
        receipt.id,
        VendorBillIn(
            total_billed_amount=Decimal("30"),
            lines=[{"catalog_product_id": prod.id, "quantity_billed": 3}],
        ),
    )
    db.flush()

    sales = item_wise_sales(db, None, None)
    assert len(sales) == 1
    assert sales[0]["catalog_product_id"] == prod.id
    assert sales[0]["label"] == "RENAMED"
    bill_labels = [ln["label"] for ln in sales[0]["lines"]]
    assert old_code in bill_labels
    assert "RENAMED" not in bill_labels

    purchases = item_wise_purchases(db, None, None)
    assert len(purchases) == 1
    assert purchases[0]["catalog_product_id"] == prod.id
    receipt_labels = [ln["label"] for ln in purchases[0]["lines"]]
    assert "RENAMED" in receipt_labels


def test_customer_order_search_matches_card_and_live_product_names(db):
    from app.routers.customer_orders import list_customer_orders

    customer, prod, _ = _setup(db)
    old_code = prod.our_product_id
    create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    confirm_received_order(db, customer.id)
    process_customer_bill(
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

    prod.our_product_id = "RENAMED"
    db.flush()

    # Open placement after rename — live name.
    create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 1}],
    )
    db.flush()

    by_old = list_customer_orders(bucket="billed", day="all", search=old_code, db=db, auth=AUTH)
    assert any(r.customer_id == customer.id for r in by_old)

    by_new = list_customer_orders(bucket="billed", day="all", search="RENAMED", db=db, auth=AUTH)
    assert any(r.customer_id == customer.id for r in by_new)

    open_by_new = list_customer_orders(bucket="received", day="all", search="RENAMED", db=db, auth=AUTH)
    assert any(r.customer_id == customer.id for r in open_by_new)

    # Open-line-only match must not leak into billed.
    other = Customer(business_name="C-OPEN", phone="1112223334", password_hash="x")
    db.add(other)
    db.flush()
    open_only = CatalogProduct(
        our_product_id="OPEN-ONLY",
        vendor_id=prod.vendor_id,
        vendor_product_id="VP-OPEN",
        buying_price=Decimal("10"),
        selling_price=Decimal("20"),
    )
    db.add(open_only)
    db.flush()
    db.add(StockBalance(catalog_product_id=open_only.id, quantity_on_hand=10))
    db.flush()
    create_received_placement(
        db,
        customer_id=other.id,
        customer_name=other.business_name,
        lines=[{"catalog_product_id": open_only.id, "quantity": 1}],
    )
    db.flush()
    billed_leak = list_customer_orders(bucket="billed", day="all", search="OPEN-ONLY", db=db, auth=AUTH)
    assert not any(r.customer_id == other.id for r in billed_leak)

    # Cancelled bill for product X must not put the customer in billed search for X
    # when their only active billed doc does not contain X.
    prod_x = CatalogProduct(
        our_product_id="CANCEL-X",
        vendor_id=prod.vendor_id,
        vendor_product_id="VP-CX",
        buying_price=Decimal("10"),
        selling_price=Decimal("20"),
    )
    prod_y = CatalogProduct(
        our_product_id="ACTIVE-Y",
        vendor_id=prod.vendor_id,
        vendor_product_id="VP-AY",
        buying_price=Decimal("10"),
        selling_price=Decimal("20"),
    )
    db.add_all([prod_x, prod_y])
    db.flush()
    db.add_all(
        [
            StockBalance(catalog_product_id=prod_x.id, quantity_on_hand=10),
            StockBalance(catalog_product_id=prod_y.id, quantity_on_hand=10),
        ]
    )
    db.flush()

    cancelled_bill = CustomerBill(
        customer_id=customer.id,
        bill_number="B-CANCEL-X",
        subtotal_inclusive=Decimal("40"),
        grand_total=Decimal("40"),
        created_by_type="admin",
        created_by_name="Test",
        bill_date=date.today(),
        cancelled_at=datetime.now(timezone.utc),
        cancel_reason="test cancel",
        card_json={
            "kind": "customer_bill",
            "bill_number": "B-CANCEL-X",
            "party_name": customer.business_name,
            "lines": [
                {
                    "catalog_product_id": prod_x.id,
                    "our_product_id": "CANCEL-X",
                }
            ],
        },
    )
    db.add(cancelled_bill)
    db.flush()
    db.add(
        CustomerBillLine(
            bill_id=cancelled_bill.id,
            catalog_product_id=prod_x.id,
            our_product_id="CANCEL-X",
            quantity_shipped=2,
            unit_price=Decimal("20"),
            line_total=Decimal("40"),
            status="billed",
        )
    )

    active_bill = CustomerBill(
        customer_id=customer.id,
        bill_number="B-ACTIVE-Y",
        subtotal_inclusive=Decimal("20"),
        grand_total=Decimal("20"),
        created_by_type="admin",
        created_by_name="Test",
        bill_date=date.today(),
        card_json={
            "kind": "customer_bill",
            "bill_number": "B-ACTIVE-Y",
            "party_name": customer.business_name,
            "lines": [
                {
                    "catalog_product_id": prod_y.id,
                    "our_product_id": "ACTIVE-Y",
                }
            ],
        },
    )
    db.add(active_bill)
    db.flush()
    db.add(
        CustomerBillLine(
            bill_id=active_bill.id,
            catalog_product_id=prod_y.id,
            our_product_id="ACTIVE-Y",
            quantity_shipped=1,
            unit_price=Decimal("20"),
            line_total=Decimal("20"),
            status="billed",
        )
    )
    db.flush()

    cancel_search = list_customer_orders(bucket="billed", day="all", search="CANCEL-X", db=db, auth=AUTH)
    assert not any(r.customer_id == customer.id for r in cancel_search)

    active_search = list_customer_orders(bucket="billed", day="all", search="ACTIVE-Y", db=db, auth=AUTH)
    assert any(r.customer_id == customer.id for r in active_search)


def test_vendor_order_search_matches_card_and_live_product_names(db):
    from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement
    from app.routers.vendor_orders import list_vendor_orders

    vendor, prod = _vendor_and_product(db)
    old_code = prod.our_product_id
    order = VendorOrder(vendor_id=vendor.id, bucket="placed", status="placed", is_open=True)
    db.add(order)
    db.flush()
    placement = VendorOrderPlacement(
        vendor_order_id=order.id,
        status="closed",
        placed_by_type="admin",
        placed_by_name="Test",
        card_json={
            "kind": "vendor_order",
            "party_name": vendor.business_name,
            "lines": [
                {
                    "catalog_product_id": prod.id,
                    "our_product_id": old_code,
                }
            ],
        },
    )
    db.add(placement)
    db.flush()
    db.add(
        VendorOrderLine(
            placement_id=placement.id,
            catalog_product_id=prod.id,
            our_product_id=old_code,
            quantity=5,
            quantity_remaining=5,
            buying_price=Decimal("10"),
        )
    )
    db.flush()

    prod.our_product_id = "RENAMED-V"
    db.flush()

    by_old = list_vendor_orders(bucket="placed", view="default", day="all", search=old_code, db=db, auth=AUTH)
    assert any(r.vendor_id == vendor.id for r in by_old)

    by_new = list_vendor_orders(bucket="placed", view="default", day="all", search="RENAMED-V", db=db, auth=AUTH)
    assert any(r.vendor_id == vendor.id for r in by_new)


def test_closed_billed_receipt_stays_out_of_billed_search(db):
    from app.routers.vendor_orders import list_vendor_orders

    vendor, prod_y = _vendor_and_product(db)
    prod_y.our_product_id = "ACTIVE-Y"
    db.flush()

    prod_x = CatalogProduct(
        our_product_id="CLOSED-X",
        vendor_id=vendor.id,
        vendor_product_id="VP-CX",
        buying_price=Decimal("10"),
    )
    db.add(prod_x)
    db.flush()
    db.add(StockBalance(catalog_product_id=prod_x.id, quantity_on_hand=0))
    db.flush()

    receive_vendor_goods(
        db,
        AUTH,
        VendorReceiveCreate(
            vendor_id=vendor.id,
            lines=[VendorReceiptLineIn(catalog_product_id=prod_y.id, quantity_received=5)],
            order_receipt_number="R-ACTIVE-Y",
        ),
        offline=True,
    )
    receipt_y = db.query(StockReceipt).filter(StockReceipt.order_receipt_number == "R-ACTIVE-Y").one()
    bill_receipt(
        db,
        AUTH,
        receipt_y.id,
        VendorBillIn(
            total_billed_amount=Decimal("50"),
            lines=[{"catalog_product_id": prod_y.id, "quantity_billed": 5}],
        ),
    )

    receive_vendor_goods(
        db,
        AUTH,
        VendorReceiveCreate(
            vendor_id=vendor.id,
            lines=[VendorReceiptLineIn(catalog_product_id=prod_x.id, quantity_received=3)],
            order_receipt_number="R-CLOSED-X",
        ),
        offline=True,
    )
    receipt_x = db.query(StockReceipt).filter(StockReceipt.order_receipt_number == "R-CLOSED-X").one()
    bill_receipt(
        db,
        AUTH,
        receipt_x.id,
        VendorBillIn(
            total_billed_amount=Decimal("30"),
            lines=[{"catalog_product_id": prod_x.id, "quantity_billed": 3}],
        ),
    )
    receipt_x.closed_at = datetime.now(timezone.utc)
    db.flush()

    closed_search = list_vendor_orders(bucket="billed", day="all", search="CLOSED-X", db=db, auth=AUTH)
    assert not any(r.vendor_id == vendor.id for r in closed_search)

    active_search = list_vendor_orders(bucket="billed", day="all", search="ACTIVE-Y", db=db, auth=AUTH)
    assert any(r.vendor_id == vendor.id for r in active_search)


def test_ledger_bill_uses_card_and_marks_cancelled(db):
    customer, prod, _ = _setup(db)
    create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    confirm_received_order(db, customer.id)
    backdate = date.today() - timedelta(days=3)
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
        bill_date=backdate,
    )
    db.flush()
    prod.our_product_id = "RENAMED"
    db.flush()
    cancel_customer_bill(db, bill_id=bill.id, reason="customer backed out", actor_name="Test")
    db.commit()
    db.refresh(bill)

    entries = build_customer_ledger(db, customer.id)
    bill_rows = [e for e in entries if e.event_type == "customer_bill"]
    assert len(bill_rows) == 1
    assert bill_rows[0].title.startswith("Cancelled")
    assert "RENAMED" not in bill_rows[0].summary
    assert bill_rows[0].occurred_at.date() == bill.bill_date or bill.bill_date is None


def test_payment_edit_replaces_amount_in_place(db):
    from app.models.accounts_receivable import ArLedgerEntry
    from app.routers.accounts_receivable import patch_ar_payment, settle_customer_ar
    from app.schemas.accounts_receivable import ArPaymentPatchIn, ArSettlementIn
    from app.services.ar_ledger import post_bill_entry as post_ar_bill
    from app.services.money import mag

    customer, _prod, _ = _setup(db)
    post_ar_bill(
        db,
        customer_id=customer.id,
        bill_id=None,
        amount=Decimal("100.00"),
        description="seed due",
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
    )
    db.commit()
    settle_customer_ar(
        customer.id,
        ArSettlementIn(amount=Decimal("100.00"), payment_ref="CASH"),
        db,
        AUTH,
    )
    pay = (
        db.query(ArLedgerEntry)
        .filter(ArLedgerEntry.entry_type == "payment", ArLedgerEntry.deleted_at.is_(None))
        .one()
    )
    new_day = date.today() - timedelta(days=2)
    patch_ar_payment(
        pay.id,
        ArPaymentPatchIn(
            amount=Decimal("40.00"),
            value_date=new_day,
            payment_mode="UPI",
            description="Corrected payment",
        ),
        db,
        AUTH,
    )
    rows = db.query(ArLedgerEntry).filter(ArLedgerEntry.entry_type == "payment").all()
    assert len(rows) == 1
    assert mag(rows[0].amount) == Decimal("40.00")
    assert rows[0].value_date == new_day
    assert rows[0].payment_mode == "UPI"
    assert rows[0].description == "Corrected payment"


def test_ap_payment_patch_updates_same_row(db):
    from app.models.accounts_payable import ApLedgerEntry
    from app.routers.accounts_payable import patch_ap_payment, settle_vendor_ap
    from app.schemas.accounts_payable import ApPaymentPatchIn, ApSettlementIn
    from app.services.ap_ledger import post_bill_entry as post_ap_bill
    from app.services.money import as_signed_decrease

    vendor = _vendor(db)
    post_ap_bill(
        db,
        vendor_id=vendor.id,
        receipt_id=None,
        amount=Decimal("100.00"),
        description="seed due",
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
    )
    db.commit()
    settle_vendor_ap(
        vendor.id,
        ApSettlementIn(amount=Decimal("100.00"), payment_ref="NEFT-1"),
        db,
        AUTH,
    )
    pay = (
        db.query(ApLedgerEntry)
        .filter(ApLedgerEntry.entry_type == "payment", ApLedgerEntry.deleted_at.is_(None))
        .one()
    )
    entry_id = pay.id
    new_day = date.today() - timedelta(days=2)
    patch_ap_payment(
        pay.id,
        ApPaymentPatchIn(
            amount=Decimal("40.00"),
            value_date=new_day,
            payment_mode="UPI",
            description="Corrected payment",
        ),
        db,
        AUTH,
    )
    rows = db.query(ApLedgerEntry).filter(ApLedgerEntry.entry_type == "payment").all()
    assert len(rows) == 1
    assert rows[0].id == entry_id
    assert rows[0].amount == as_signed_decrease(Decimal("40.00"))
    assert rows[0].value_date == new_day
    assert rows[0].payment_mode == "UPI"
    assert rows[0].description == "Corrected payment"


def test_expense_edit_updates_row_in_place(db):
    from app.models.expense import Expense
    from app.routers.expenses import ExpenseIn, create_expense, patch_expense

    old_day = date.today() - timedelta(days=5)
    new_day = date.today() - timedelta(days=1)
    created = create_expense(
        ExpenseIn(
            expense_date=old_day,
            category="misc",
            description="typo",
            amount=Decimal("100.00"),
            reference="R1",
        ),
        db,
        AUTH,
    )
    patch_expense(
        created.id,
        ExpenseIn(
            expense_date=new_day,
            category="travel",
            description="fixed",
            amount=Decimal("40.00"),
            reference="R2",
        ),
        db,
        AUTH,
    )
    rows = db.query(Expense).all()
    assert len(rows) == 1
    assert rows[0].amount == Decimal("40.00")
    assert rows[0].expense_date == new_day
    assert rows[0].category == "travel"
    assert rows[0].description == "fixed"
    assert rows[0].reference == "R2"


def test_portal_order_history_uses_bill_card_and_live_open(db, monkeypatch):
    from app.routers import shop as shop_router

    monkeypatch.setattr(shop_router, "presigned_url", lambda key: f"https://img/{key}")

    customer, prod, _ = _setup(db)
    prod.image_keys = ["old-key"]
    db.flush()
    old_code = prod.our_product_id

    create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    confirm_received_order(db, customer.id)
    process_customer_bill(
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

    prod.our_product_id = "RENAMED"
    prod.image_keys = ["new-key"]
    db.flush()

    create_received_placement(
        db,
        customer_id=customer.id,
        customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 1}],
    )
    db.flush()

    history = shop_router.list_order_history(db=db, customer=customer)

    billed_line = next(
        ln for h in history for ln in h.lines if ln.quantity_shipped > 0
    )
    assert billed_line.our_product_id == old_code
    assert billed_line.our_product_id != "RENAMED"
    assert "new-key" not in billed_line.image_url
    assert "old-key" in billed_line.image_url

    open_line = next(
        ln for h in history for ln in h.lines if ln.quantity_shipped == 0 and ln.quantity == 1
    )
    assert open_line.our_product_id == "RENAMED"
    assert "new-key" in open_line.image_url


def test_catalog_rename_invalidates_open_document_caches(db, monkeypatch):
    from app.routers import catalog as catalog_router
    from app.schemas.catalog import CatalogUpdate
    from app.services import response_cache

    _, prod, _ = _setup(db)
    calls: list[str] = []
    monkeypatch.setattr(response_cache, "invalidate", lambda prefix="": calls.append(prefix))

    catalog_router.update_product(
        prod.id,
        CatalogUpdate(our_product_id="RENAMED-P1"),
        db=db,
        auth=AUTH,
    )

    assert "catalog:" in calls
    assert "stock:" in calls
    assert "shop:" in calls
