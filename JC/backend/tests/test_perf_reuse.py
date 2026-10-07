"""Stored vendor-order PDFs, paged stock, and batched route dues."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.accounts_receivable import ArLedgerEntry
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.stock import StockBalance
from app.models.vendor import Vendor
from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement
from app.services.ar_ledger import batch_customer_ar_totals, customer_ar_totals
from app.services.cost_visibility import HIDDEN
from app.services import doc_gen, doc_jobs
from app.routers.stock.list_stock import browse_stock

ADMIN = AuthContext("admin", 1, "Admin")
STAFF = AuthContext("staff", 2, "Staff", set())


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


def test_batch_ar_totals_match_one_customer(db):
    one = Customer(business_name="One", phone="9000000001", password_hash="x")
    two = Customer(business_name="Two", phone="9000000002", password_hash="x")
    db.add_all([one, two])
    db.flush()
    db.add_all([
        ArLedgerEntry(
            customer_id=one.id, entry_type="bill", amount=Decimal("100.00"),
            description="bill", created_by_type="admin", created_by_name="Admin",
        ),
        ArLedgerEntry(
            customer_id=one.id, entry_type="payment", amount=Decimal("-40.00"),
            description="pay", created_by_type="admin", created_by_name="Admin",
        ),
        ArLedgerEntry(
            customer_id=two.id, entry_type="bill", amount=Decimal("15.50"),
            description="bill", created_by_type="admin", created_by_name="Admin",
        ),
    ])
    db.commit()
    batched = batch_customer_ar_totals(db, [one.id, two.id])
    assert batched[one.id] == customer_ar_totals(db, one.id)
    assert batched[two.id] == customer_ar_totals(db, two.id)
    assert batched[one.id]["outstanding"] == Decimal("60.00")
    assert batched[one.id]["payment_total"] == Decimal("40.00")


def _placement(db):
    vendor = Vendor(business_name="Press", phone="9000000010")
    db.add(vendor)
    db.flush()
    product = CatalogProduct(
        our_product_id="A-1", vendor_id=vendor.id, vendor_product_id="V-1",
        buying_price=Decimal("12.00"), image_keys=[],
    )
    db.add(product)
    db.flush()
    order = VendorOrder(vendor_id=vendor.id, bucket="placed", status="placed", is_open=True)
    db.add(order)
    db.flush()
    placement = VendorOrderPlacement(
        vendor_order_id=order.id, status="placed",
        placed_by_type="admin", placed_by_name="Admin",
    )
    db.add(placement)
    db.flush()
    db.add(VendorOrderLine(
        placement_id=placement.id, catalog_product_id=product.id,
        our_product_id=product.our_product_id, quantity=3, quantity_remaining=3,
        buying_price=Decimal("12.00"),
    ))
    db.commit()
    return placement


def test_vendor_placement_pdf_is_stored_once_per_viewer(db, monkeypatch):
    calls = []

    def fake_render(**kwargs):
        calls.append(kwargs)
        return b"%PDF-vendor"

    monkeypatch.setattr(doc_gen, "render_vendor_placement_pdf", fake_render)
    monkeypatch.setattr(doc_gen, "upload_bytes", lambda *a, **k: None)
    monkeypatch.setattr(doc_gen, "presigned_urls", lambda keys: [])
    placement = _placement(db)
    placement.document_key = "JCC/vendor/Press/orders/placement_1.pdf"
    db.commit()

    safe = doc_jobs.placement_pdf_key(db, placement.id, STAFF)
    assert safe.endswith("_safe.pdf")
    assert len(calls) == 1
    assert calls[0]["lines"][0]["unit_price"] == HIDDEN

    again = doc_jobs.placement_pdf_key(db, placement.id, STAFF)
    assert again == safe
    assert len(calls) == 1

    cost = doc_jobs.placement_pdf_key(db, placement.id, ADMIN)
    assert cost.endswith("_cost.pdf")
    assert len(calls) == 2
    assert calls[1]["lines"][0]["unit_price"] == "12.00"
    doc_jobs.placement_pdf_key(db, placement.id, ADMIN)
    assert len(calls) == 2


def test_stock_page_does_not_return_the_whole_list(db):
    vendor = Vendor(business_name="Mill", phone="9000000020")
    db.add(vendor)
    db.flush()
    for i, qty in enumerate((10, 0, -2)):
        product = CatalogProduct(
            our_product_id=f"P-{i}", vendor_id=vendor.id, vendor_product_id=f"V-{i}",
            buying_price=Decimal("5.00"), selling_price=Decimal("8.00") if i == 0 else Decimal("5.00"),
            image_keys=[],
        )
        db.add(product)
        db.flush()
        db.add(StockBalance(catalog_product_id=product.id, quantity_on_hand=qty, low_stock_threshold=5))
    db.commit()
    page = browse_stock(db, ADMIN, limit=2, offset=0)
    assert page.total == 3
    assert len(page.items) == 2
    assert page.counts.all == 3
    assert page.counts.negative_stock == 1
    assert page.counts.out_of_stock == 1
    assert page.units_on_hand == 8
    rest = browse_stock(db, ADMIN, limit=2, offset=2)
    assert len(rest.items) == 1
    low = browse_stock(db, ADMIN, stock_status="negative_stock", limit=100)
    assert low.total == 1
    assert low.counts.all == 3
