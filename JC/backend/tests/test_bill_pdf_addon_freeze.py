"""Round-2 catalog audit CRITICAL C1: an already-issued customer bill's frozen
add-on snapshot (stamped once at create/edit time by _persist_totals_addons) must
survive later changes to a catalog product's live add-on links. Every PDF
regeneration (view/print/WhatsApp share/portal download) used to call
attach_addons_to_totals unconditionally and permanently overwrite totals_json with
whatever add-ons are linked *today* — silently rewriting an issued bill's history.
generate_customer_bill_document now only backfills lines that never got a snapshot
at all (missing the "addons" key entirely — pre-feature legacy bills)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.addon_product import AddonProduct
from app.models.catalog_addon_link import CatalogAddonLink
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.vendor import Vendor
from app.services import doc_gen


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


@pytest.fixture(autouse=True)
def _stub_pdf_and_storage(monkeypatch):
    monkeypatch.setattr(doc_gen, "render_customer_bill_pdf", lambda **kw: b"%PDF-fake%")
    monkeypatch.setattr(doc_gen, "upload_bytes", lambda *a, **kw: None)
    monkeypatch.setattr(doc_gen, "presigned_urls", lambda keys: [])


def _setup(db):
    vendor = Vendor(business_name="Card Vendor", phone="9998887771")
    addon_vendor = Vendor(business_name="Sticker Vendor", phone="9998887773")
    db.add_all([vendor, addon_vendor])
    db.flush()
    prod = CatalogProduct(
        our_product_id="CARD1", vendor_id=vendor.id, vendor_product_id="VCARD1",
        buying_price=Decimal("10"), selling_price=Decimal("20"),
    )
    db.add(prod)
    db.flush()
    addon = AddonProduct(
        our_product_id="STICK1", vendor_id=addon_vendor.id, vendor_product_id="VSTICK1",
        unit="pc", buying_price=Decimal("2"), quantity_on_hand=100,
    )
    db.add(addon)
    db.flush()
    db.add(CatalogAddonLink(catalog_product_id=prod.id, addon_product_id=addon.id, quantity=1))
    customer = Customer(business_name="Cust", phone="9998887772", password_hash="x")
    db.add(customer)
    db.flush()
    bill = CustomerBill(
        customer_id=customer.id, bill_number="B-1", subtotal_inclusive=Decimal("20"),
        grand_total=Decimal("20"),
        created_by_type="admin", created_by_name="Test Admin",
        totals_json={
            "lines": [
                {"catalog_product_id": prod.id, "our_product_id": "CARD1", "quantity": 1, "addons": []},
            ]
        },
    )
    db.add(bill)
    db.commit()
    return bill, prod, addon


def test_regenerating_pdf_does_not_overwrite_frozen_empty_addon_snapshot(db):
    """Line was billed with NO addons (frozen as []); a link added afterward must
    not retroactively appear on regen — the historical bill had none."""
    bill, prod, addon = _setup(db)
    addon2 = AddonProduct(
        our_product_id="LACE1", vendor_id=addon.vendor_id, vendor_product_id="VLACE1",
        unit="pc", buying_price=Decimal("3"), quantity_on_hand=50,
    )
    db.add(addon2)
    db.flush()
    db.add(CatalogAddonLink(catalog_product_id=prod.id, addon_product_id=addon2.id, quantity=5))
    db.commit()

    doc_gen.generate_customer_bill_document(db, bill.id)
    db.refresh(bill)
    assert bill.totals_json["lines"][0]["addons"] == []


def test_regenerating_pdf_backfills_legacy_line_missing_addons_key(db):
    """A pre-addons-feature bill line with no 'addons' key at all should get a
    one-time backfill from whatever is live today."""
    bill, prod, addon = _setup(db)
    bill.totals_json = {"lines": [{"catalog_product_id": prod.id, "our_product_id": "CARD1", "quantity": 1}]}
    db.commit()

    doc_gen.generate_customer_bill_document(db, bill.id)
    db.refresh(bill)
    line = bill.totals_json["lines"][0]
    assert "addons" in line
    assert line["addons"][0]["addon_product_id"] == addon.id
