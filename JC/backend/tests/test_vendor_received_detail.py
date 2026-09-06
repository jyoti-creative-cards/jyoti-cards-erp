"""Round-3 audit HIGH fix (H1, round3-vendor-stock.md): the 'Received' tab's full-page
per-vendor detail hardcoded aggregated_lines: [] since there's no real VendorOrder id
for this bucket either (one-receipt-per-bill model) — stat pills ('Received qty',
'Unbilled') always showed 0 and every receipt card showed '0 products' with no expand.
build_vendor_received_detail() (StockReceipt-backed, mirroring build_vendor_billed_detail)
fixes that."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.catalog_product import CatalogProduct
from app.models.stock import StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.services.stock_receipt import build_vendor_received_detail

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


def _setup(db):
    vendor = Vendor(business_name="Test Vendor", phone="9999999999")
    db.add(vendor)
    db.flush()
    prod = CatalogProduct(our_product_id="P1", vendor_id=vendor.id, vendor_product_id="V1", buying_price=Decimal("10"))
    db.add(prod)
    db.flush()
    receipt = StockReceipt(
        vendor_id=vendor.id, bill_status="pending_bill", order_receipt_number="ORN-1",
        received_at=datetime.now(timezone.utc),
        received_by_type="admin", received_by_name="Test",
    )
    db.add(receipt)
    db.flush()
    db.add(StockReceiptLine(
        receipt_id=receipt.id, catalog_product_id=prod.id, our_product_id=prod.our_product_id,
        quantity_received=10, quantity_billed=4, buying_price=Decimal("10"),
    ))
    db.commit()
    return vendor, receipt, prod


def test_build_vendor_received_detail_returns_real_data(db):
    vendor, receipt, prod = _setup(db)
    detail = build_vendor_received_detail(db, vendor.id, AUTH)

    assert detail["vendor_id"] == vendor.id
    assert len(detail["placements"]) == 1
    p = detail["placements"][0]
    assert p["id"] == receipt.id  # Stock.openEditReceipt keys off this
    assert p["order_receipt_number"] == "ORN-1"
    assert p["total_quantity"] == 10

    assert len(detail["aggregated_lines"]) == 1
    line = detail["aggregated_lines"][0]
    assert line["our_product_id"] == "P1"
    assert line["total_quantity"] == 10
    assert line["total_pending"] == 6  # 10 received - 4 already billed
    assert len(line["breakdown"]) == 1
    b = line["breakdown"][0]
    assert b["placement_id"] == receipt.id
    assert b["quantity"] == 10
    assert b["quantity_billed"] == 4
    assert b["quantity_remaining"] == 6


def test_build_vendor_received_detail_excludes_billed_receipts(db):
    vendor, receipt, prod = _setup(db)
    receipt.bill_status = "billed"
    db.commit()

    detail = build_vendor_received_detail(db, vendor.id, AUTH)
    assert detail["placements"] == []
    assert detail["aggregated_lines"] == []
