"""Round-2 freight/PDF audit CRITICAL finding: the vendor receipt/bill PDF is fully
regenerated on every view/print/download (GET /stock/receipts/{id}/document), and used
to re-derive its GST included/rate straight from the vendor's *current* profile instead
of the bill-time snapshot (`gst_rate_pct_applied`, set specifically because GST can be
one-off overridden per bill — mirroring the already-correct `billing_pct_applied`
fallback right above it). A vendor's GST profile changing later must not retroactively
change the taxable-value/GST split shown on an already-issued receipt."""

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
from app.services import doc_gen

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


@pytest.fixture()
def captured(monkeypatch):
    calls: dict = {}

    def _fake_render(**kw):
        calls.update(kw)
        return b"%PDF-fake%"

    monkeypatch.setattr(doc_gen, "render_vendor_receipt_pdf", _fake_render)
    monkeypatch.setattr(doc_gen, "upload_bytes", lambda *a, **kw: None)
    monkeypatch.setattr(doc_gen, "presigned_urls", lambda keys: [])
    return calls


def _setup(db, *, vendor_gst_included: bool, vendor_gst_rate: Decimal, receipt_gst_applied):
    vendor = Vendor(
        business_name="Test Vendor", phone="9999999999",
        gst_included=vendor_gst_included, gst_rate_pct=vendor_gst_rate,
    )
    db.add(vendor)
    db.flush()
    prod = CatalogProduct(our_product_id="P1", vendor_id=vendor.id, vendor_product_id="V1", buying_price=Decimal("10"))
    db.add(prod)
    db.flush()
    receipt = StockReceipt(
        vendor_id=vendor.id, bill_status="billed", bill_number="B-1",
        total_billed_amount=Decimal("100"), billed_at=datetime.now(timezone.utc),
        received_by_type="admin", received_by_name="Test",
        billing_pct_applied=Decimal("100"), gst_rate_pct_applied=receipt_gst_applied,
    )
    db.add(receipt)
    db.flush()
    db.add(StockReceiptLine(
        receipt_id=receipt.id, catalog_product_id=prod.id, our_product_id=prod.our_product_id,
        quantity_received=10, quantity_billed=10, buying_price=Decimal("10"), billed_amount=Decimal("100"),
    ))
    db.commit()
    return vendor, receipt


def test_receipt_gst_snapshot_survives_later_vendor_profile_change(db, captured):
    # Billed at 18% GST-included; vendor profile later changes to GST-off.
    vendor, receipt = _setup(
        db, vendor_gst_included=True, vendor_gst_rate=Decimal("18"), receipt_gst_applied=Decimal("18")
    )
    vendor.gst_included = False
    vendor.gst_rate_pct = Decimal("0")
    db.commit()

    doc_gen.generate_vendor_receipt_document(db, receipt.id, AUTH)

    assert captured["gst_included"] is True
    assert captured["gst_rate_pct"] == Decimal("18")


def test_receipt_snapshotted_as_no_gst_stays_no_gst_even_if_vendor_now_has_gst(db, captured):
    # Billed with GST off for this bill (gst_rate_pct_applied None); vendor later turns GST on.
    vendor, receipt = _setup(
        db, vendor_gst_included=False, vendor_gst_rate=Decimal("0"), receipt_gst_applied=None
    )
    vendor.gst_included = True
    vendor.gst_rate_pct = Decimal("12")
    db.commit()

    doc_gen.generate_vendor_receipt_document(db, receipt.id, AUTH)

    assert captured["gst_included"] is False


def test_legacy_receipt_without_snapshot_falls_back_to_vendor_profile(db, captured):
    # billing_pct_applied is None => pre-snapshot legacy receipt => fall back like before.
    vendor, receipt = _setup(
        db, vendor_gst_included=True, vendor_gst_rate=Decimal("18"), receipt_gst_applied=None
    )
    receipt.billing_pct_applied = None
    db.commit()

    doc_gen.generate_vendor_receipt_document(db, receipt.id, AUTH)

    assert captured["gst_included"] is True
    assert captured["gst_rate_pct"] == Decimal("18")
