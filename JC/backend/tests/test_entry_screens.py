"""Order and bill entry load their lists in one call."""
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.main import app
from app.models.catalog_product import CatalogProduct
from app.models.vendor import Vendor
from app.routers.stock.list_stock import entry_items
from app.services.report_pdfs import _pdf_day


def test_entry_lists_are_on_the_api():
    spec = app.openapi()
    assert "/api/v1/customers/entry-parties" in spec["paths"]
    assert "/api/v1/stock/entry-items" in spec["paths"]
    freight = spec["paths"]["/api/v1/freight-agents"]["get"]
    names = [p["name"] for p in freight.get("parameters") or []]
    assert "names_only" in names


def test_alt_s_search_matches_the_vendor_item_number():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    vendor = Vendor(business_name="Mill", phone="9000000540")
    db.add(vendor)
    db.flush()
    db.add(CatalogProduct(
        our_product_id="5401 PATRIKA", vendor_id=vendor.id, vendor_product_id="V-5401",
        image_keys=[],
    ))
    db.commit()
    auth = AuthContext(actor_type="admin", actor_id=None, actor_name="Admin")
    rows = entry_items(q="V-5401", db=db, auth=auth)
    assert [row["our_product_id"] for row in rows] == ["5401 PATRIKA"]
    assert rows[0]["vendor_product_id"] == "V-5401"
    assert rows[0]["marking"] is None
    db.close()
    engine.dispose()


def test_whatsapp_stays_off_until_the_switch_is_on(monkeypatch):
    from app.services import whatsapp_gate

    monkeypatch.setattr(whatsapp_gate, "_read_flag", lambda: None)
    assert whatsapp_gate.whatsapp_sends_enabled() is False
    monkeypatch.setattr(whatsapp_gate, "_read_flag", lambda: "0")
    assert whatsapp_gate.whatsapp_sends_enabled() is False
    monkeypatch.setattr(whatsapp_gate, "_read_flag", lambda: "1")
    assert whatsapp_gate.whatsapp_sends_enabled() is True


def test_customer_app_can_send_a_bag_of_items():
    from app.schemas.shop import CustomerOrderCreate

    body = CustomerOrderCreate.model_validate({
        "lines": [
            {"catalog_product_id": 12, "quantity": 50},
            {"catalog_product_id": 18, "quantity": 100},
        ],
        "customer_notes": "test",
    })
    assert body.order_lines() == [(12, 50), (18, 100)]


def test_statement_date_accepts_a_timestamp():
    assert _pdf_day(datetime(2026, 10, 20, 5, 30, tzinfo=timezone.utc)) == "2026-10-20"
    assert _pdf_day(None) == ""
    assert _pdf_day("2026-10-20T00:00:00") == "2026-10-20"
