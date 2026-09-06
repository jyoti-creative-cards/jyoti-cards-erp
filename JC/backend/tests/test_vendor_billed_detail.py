"""Round-2 audit CRITICAL/M3 fix: the 'Billed' tab's per-vendor drill-down (hub inline
expand, full detail page, and per-bill Close) always rendered empty / 400'd, because it
tried to resolve a VendorOrder id that never exists for this bucket in the
one-receipt-per-bill model. build_vendor_billed_detail() (StockReceipt-backed) and the
StockReceipt-backed close_billed_placement fix that."""

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
from app.services.stock_receipt import build_vendor_billed_detail

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
        vendor_id=vendor.id, bill_status="billed", bill_number="B-1",
        total_billed_amount=Decimal("100"), billed_at=datetime.now(timezone.utc),
        received_by_type="admin", received_by_name="Test",
    )
    db.add(receipt)
    db.flush()
    db.add(StockReceiptLine(
        receipt_id=receipt.id, catalog_product_id=prod.id, our_product_id=prod.our_product_id,
        quantity_received=10, quantity_billed=10, buying_price=Decimal("10"), billed_amount=Decimal("100"),
    ))
    db.commit()
    return vendor, receipt, prod


def test_build_vendor_billed_detail_returns_real_data(db):
    vendor, receipt, prod = _setup(db)
    detail = build_vendor_billed_detail(db, vendor.id, AUTH)

    assert detail["vendor_id"] == vendor.id
    assert len(detail["placements"]) == 1
    p = detail["placements"][0]
    assert p["id"] == receipt.id  # id must equal receipt_id — close/edit/debit-note buttons key off this
    assert p["bill_number"] == "B-1"
    assert p["closed_at"] is None

    assert len(detail["aggregated_lines"]) == 1
    line = detail["aggregated_lines"][0]
    assert line["our_product_id"] == "P1"
    assert len(line["breakdown"]) == 1
    assert line["breakdown"][0]["placement_id"] == receipt.id
    assert line["breakdown"][0]["quantity"] == 10


def test_closing_a_bill_via_receipt_id_removes_it_from_open_placements(db):
    from app.routers.vendor_orders import close_billed_placement
    from app.schemas.vendor_order import ReasonIn

    vendor, receipt, prod = _setup(db)
    result = close_billed_placement(receipt.id, ReasonIn(reason="paid in full"), db=db, auth=AUTH)
    assert result["placements"][0]["closed_at"] is not None
    assert result["placements"][0]["close_reason"] == "paid in full"

    db.refresh(receipt)
    assert receipt.closed_at is not None
