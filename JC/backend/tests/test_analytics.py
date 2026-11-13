"""Analytics: collected percent, today's stock, active parties, and the alert list."""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.accounts_receivable import ArLedgerEntry
from app.models.catalog_product import CatalogProduct
from app.models.city import City
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill, CustomerBillLine
from app.models.our_catalog import OurCatalog, OurCatalogIssue
from app.models.stock import StockBalance, StockLedger
from app.models.vendor import Vendor
from app.services.analytics.core import (
    collected_percent,
    party_activity_report,
    sale_balance_report,
    set_default_threshold,
    set_threshold,
    stock_report,
    threshold_list,
    under_threshold,
)
from app.services.analytics.pdf import party_pdf, sale_pdf, stock_pdf, threshold_pdf
from app.services.biz_date import ist_day_bounds_utc, today_ist


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_collected_is_money_already_received():
    assert collected_percent(Decimal("100"), Decimal("20")) == Decimal("20.00")
    assert collected_percent(Decimal("0"), Decimal("20")) is None
    assert under_threshold(Decimal("1000"), Decimal("199"), Decimal("20")) is True
    assert under_threshold(Decimal("1000"), Decimal("200"), Decimal("20")) is False


def test_reports_use_today_stock_and_skip_switched_off_parties():
    db = _db()
    day = today_ist()
    stamp = ist_day_bounds_utc(day)[0] + timedelta(hours=2)
    city = City(name="Dewas")
    vendor = Vendor(business_name="Shivam Press", phone="9000000001", alias="SHIV")
    db.add_all([city, vendor])
    db.flush()
    low = CatalogProduct(
        our_product_id="LOW-1", vendor_id=vendor.id, vendor_product_id="V-LOW",
        category="BOX", second_category="RED", category_3="2026", year_group="2026",
        buying_price=Decimal("4"),
    )
    healthy = CatalogProduct(
        our_product_id="HEALTHY-1", vendor_id=vendor.id, vendor_product_id="V-OK",
        buying_price=Decimal("2"),
    )
    live = Customer(business_name="Live Press", phone="9000000002", password_hash="x", city_id=city.id)
    gone = Customer(business_name="Gone Press", phone="9000000003", password_hash="x", is_active=False)
    db.add_all([low, healthy, live, gone])
    db.flush()
    db.add_all([
        StockLedger(catalog_product_id=low.id, entry_type="received", quantity_delta=1000, balance_after=1000, created_at=stamp),
        StockLedger(catalog_product_id=healthy.id, entry_type="received", quantity_delta=100, balance_after=100, created_at=stamp),
        StockBalance(catalog_product_id=low.id, quantity_on_hand=150),
        StockBalance(catalog_product_id=healthy.id, quantity_on_hand=80),
    ])
    live_bill = CustomerBill(
        customer_id=live.id, bill_number="A1", bill_date=day,
        subtotal_inclusive=Decimal("100"), grand_total=Decimal("100"),
        created_by_type="admin", created_by_name="Admin",
    )
    gone_bill = CustomerBill(
        customer_id=gone.id, bill_number="A2", bill_date=day,
        subtotal_inclusive=Decimal("50"), grand_total=Decimal("50"),
        created_by_type="admin", created_by_name="Admin",
    )
    db.add_all([live_bill, gone_bill])
    db.flush()
    db.add(CustomerBillLine(
        bill_id=live_bill.id, catalog_product_id=low.id, our_product_id="2027 ALBUM NO. 03",
        quantity_shipped=10, unit_price=Decimal("10"), line_total=Decimal("100"),
    ))
    handed = OurCatalog(name="BP ALBUM 2027", copies_made=1)
    inferred = OurCatalog(name="2027 ALBUM NO. 05", copies_made=1)
    db.add_all([handed, inferred])
    db.flush()
    db.add_all([
        OurCatalogIssue(catalog_id=handed.id, customer_id=live.id, copies=1, issued_on=day, note="Given by hand"),
        OurCatalogIssue(catalog_id=inferred.id, customer_id=live.id, copies=1, issued_on=day, note="From bill A1"),
    ])
    db.add_all([
        ArLedgerEntry(customer_id=live.id, entry_type="bill", amount=Decimal("100"), description="bill", created_by_type="admin", created_by_name="Admin", value_date=day),
        ArLedgerEntry(customer_id=live.id, entry_type="payment", amount=Decimal("-20"), description="cash", created_by_type="admin", created_by_name="Admin", value_date=day),
    ])
    db.flush()

    stock = stock_report(db, from_date=day, categories=["BOX"], year_group="2026")
    assert [row["item"] for row in stock["items"]] == ["LOW-1"]
    row = stock["items"][0]
    assert "city" not in row
    assert row["alias"] == "SHIV"
    assert row["party"] == "Shivam Press"
    assert row["category_1"] == "BOX"
    assert row["category_2"] == "RED"
    assert row["category_3"] == "2026"
    assert row["bills"] == 1
    assert row["inward"] == "1000"
    assert row["outward"] == "10"
    assert row["closing_stock"] == "150"
    assert row["closing_value"] == "600.00"
    assert row["percent"] == "15.00"
    assert row["last_received"] == day.isoformat()
    assert stock["to_date"] == day.isoformat()

    sales = {row["party"]: row for row in sale_balance_report(db, from_date=day, to_date=day)["items"]}
    assert sales["Live Press"]["collected_percent"] == "20.00"
    assert sales["Live Press"]["sale"] == "100.00"
    assert sales["Live Press"]["balance"] == "80.00"
    assert sales["Live Press"]["receipts"] == 1
    assert sales["Live Press"]["last_payment"] == day.isoformat()
    assert sales["Live Press"]["city"] == "Dewas"
    assert "Gone Press" in sales

    parties = {row["party"]: row for row in party_activity_report(db, from_date=day, to_date=day)["items"]}
    assert "Gone Press" not in parties
    assert parties["Live Press"]["albums"] == "2027 ALBUM NO. 03, BP ALBUM 2027"
    assert parties["Live Press"]["bills"] == 1
    assert parties["Live Press"]["last_payment"] == day.isoformat()

    listed = {row["item"]: row for row in threshold_list(db)["items"]}
    assert listed["LOW-1"]["below"] is True
    assert listed["LOW-1"]["percent"] == "20.00"
    assert "HEALTHY-1" not in listed
    found = {row["item"]: row for row in threshold_list(db, q="HEALTHY")["items"]}
    assert found["HEALTHY-1"]["below"] is False

    set_threshold(db, low.id, Decimal("10"))
    assert "LOW-1" not in {row["item"] for row in threshold_list(db)["items"]}
    set_default_threshold(db, Decimal("20"))
    assert "LOW-1" in {row["item"] for row in threshold_list(db)["items"]}

    assert stock_pdf(db, from_date=day, categories=["BOX"], year_group="2026").startswith(b"%PDF")
    assert sale_pdf(db, from_date=day, to_date=day).startswith(b"%PDF")
    assert party_pdf(db, from_date=day, to_date=day).startswith(b"%PDF")
    assert threshold_pdf(db).startswith(b"%PDF")
