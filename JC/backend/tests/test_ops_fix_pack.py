"""JC ERP ops fix pack — extra collection, value_date, FOC bills, to-bill flip."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.deps import AuthContext
from app.models.accounts_payable import ApLedgerEntry
from app.models.accounts_receivable import ArLedgerEntry
from app.models.bill_series import BillSeries
from app.models.catalog_product import CatalogProduct
from app.models.customer import Customer
from app.models.stock import StockBalance, StockReceipt, StockReceiptLine
from app.models.vendor import Vendor
from app.services.customer_bill_process import process_offline_customer_order
from app.services.pricing import coerce_selling_price, effective_selling_price
from app.services.stock_receipt import add_stock
from app.routers.accounts_payable import record_vendor_payment, settle_vendor_ap
from app.routers.accounts_receivable import record_customer_payment, settle_customer_ar
from app.schemas.accounts_payable import ApSettlementIn
from app.schemas.accounts_receivable import ArSettlementIn
from app.services.ap_ledger import post_bill_entry as post_ap_bill, vendor_ap_totals
from app.services.ar_ledger import post_bill_entry as post_ar_bill, customer_ar_totals
from app.services.biz_date import today_ist
from app.services.money import as_signed_decrease
from app.schemas.stock import VendorBillIn, VendorBillLineIn
from app.services.reports import daybook, list_payments
from app.services.vendor_receive_bill import bill_receipt

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


def _customer(db) -> Customer:
    c = Customer(business_name="AR Party", phone="8111111111", password_hash="x")
    db.add(c)
    db.flush()
    return c


def _vendor(db) -> Vendor:
    v = Vendor(business_name="AP Party", phone="9111111111")
    db.add(v)
    db.flush()
    return v


def _ar_due(db, customer_id: int, amount: Decimal) -> None:
    post_ar_bill(
        db, customer_id=customer_id, bill_id=None, amount=amount,
        description="seed due", actor_type="admin", actor_id=1, actor_name="Test",
    )
    db.commit()


def _ap_due(db, vendor_id: int, amount: Decimal) -> None:
    post_ap_bill(
        db, vendor_id=vendor_id, receipt_id=None, amount=amount,
        description="seed due", actor_type="admin", actor_id=1, actor_name="Test",
    )
    db.commit()


def test_ar_settle_over_due_becomes_advance(db):
    c = _customer(db)
    _ar_due(db, c.id, Decimal("100.00"))
    body = ArSettlementIn(amount=Decimal("150.00"), payment_ref="CASH")
    settle_customer_ar(c.id, body, db, AUTH)
    pays = db.query(ArLedgerEntry).filter(
        ArLedgerEntry.customer_id == c.id,
        ArLedgerEntry.entry_type == "payment",
        ArLedgerEntry.deleted_at.is_(None),
    ).all()
    assert len(pays) == 1
    assert pays[0].amount == as_signed_decrease(Decimal("150.00"))
    assert customer_ar_totals(db, c.id)["outstanding"] == Decimal("-50.00")


def test_ap_settle_over_due_becomes_advance(db):
    v = _vendor(db)
    _ap_due(db, v.id, Decimal("100.00"))
    body = ApSettlementIn(amount=Decimal("150.00"), payment_ref="NEFT-1")
    settle_vendor_ap(v.id, body, db, AUTH)
    pays = db.query(ApLedgerEntry).filter(
        ApLedgerEntry.vendor_id == v.id,
        ApLedgerEntry.entry_type == "payment",
        ApLedgerEntry.deleted_at.is_(None),
    ).all()
    assert len(pays) == 1
    assert pays[0].amount == as_signed_decrease(Decimal("150.00"))
    assert vendor_ap_totals(db, v.id)["outstanding"] == Decimal("-50.00")


def test_ar_record_payment_over_due_ok(db):
    c = _customer(db)
    _ar_due(db, c.id, Decimal("100.00"))
    body = ArSettlementIn(amount=Decimal("150.00"), payment_ref="CASH")
    out = record_customer_payment(c.id, body, db, AUTH)
    assert out["ok"] is True
    assert customer_ar_totals(db, c.id)["outstanding"] == Decimal("-50.00")


def test_ap_record_payment_over_due_ok(db):
    v = _vendor(db)
    _ap_due(db, v.id, Decimal("100.00"))
    body = ApSettlementIn(amount=Decimal("150.00"), payment_ref="NEFT-1")
    out = record_vendor_payment(v.id, body, db, AUTH)
    assert out["ok"] is True
    assert vendor_ap_totals(db, v.id)["outstanding"] == Decimal("-50.00")


def test_ar_settle_zero_outstanding_still_400(db):
    c = _customer(db)
    body = ArSettlementIn(amount=Decimal("10.00"), payment_ref="CASH")
    with pytest.raises(HTTPException) as ei:
        settle_customer_ar(c.id, body, db, AUTH)
    assert ei.value.status_code == 400
    assert "no outstanding" in str(ei.value.detail).lower()


def test_ap_settle_zero_outstanding_still_400(db):
    v = _vendor(db)
    body = ApSettlementIn(amount=Decimal("10.00"), payment_ref="NEFT-1")
    with pytest.raises(HTTPException) as ei:
        settle_vendor_ap(v.id, body, db, AUTH)
    assert ei.value.status_code == 400


def test_ar_settle_non_positive_amount_rejected():
    with pytest.raises(Exception):
        ArSettlementIn(amount=Decimal("0"), payment_ref="CASH")


def test_ar_settle_persists_past_value_date(db):
    c = _customer(db)
    _ar_due(db, c.id, Decimal("100.00"))
    past = date(2024, 1, 15)
    body = ArSettlementIn(amount=Decimal("40.00"), payment_ref="CASH", value_date=past)
    before = datetime.now(timezone.utc)
    settle_customer_ar(c.id, body, db, AUTH)
    pay = db.query(ArLedgerEntry).filter(ArLedgerEntry.entry_type == "payment").one()
    assert pay.value_date == past
    assert pay.created_at is not None
    created = pay.created_at if pay.created_at.tzinfo else pay.created_at.replace(tzinfo=timezone.utc)
    assert created >= before.replace(microsecond=0)


def test_ar_settle_omitted_value_date_is_today_ist(db):
    c = _customer(db)
    _ar_due(db, c.id, Decimal("100.00"))
    body = ArSettlementIn(amount=Decimal("10.00"), payment_ref="CASH")
    settle_customer_ar(c.id, body, db, AUTH)
    pay = db.query(ArLedgerEntry).filter(ArLedgerEntry.entry_type == "payment").one()
    assert pay.value_date == today_ist()


def test_daybook_uses_value_date_not_created_at(db):
    c = _customer(db)
    _ar_due(db, c.id, Decimal("100.00"))
    past = date(2024, 1, 15)
    settle_customer_ar(
        c.id,
        ArSettlementIn(amount=Decimal("40.00"), payment_ref="CASH", value_date=past),
        db, AUTH,
    )
    book_past = daybook(db, past)
    book_today = daybook(db, today_ist())
    past_ids = {r["ref_id"] for r in book_past["entries"] if r["kind"] == "payment_in"}
    today_ids = {r["ref_id"] for r in book_today["entries"] if r["kind"] == "payment_in"}
    pay = db.query(ArLedgerEntry).filter(ArLedgerEntry.entry_type == "payment").one()
    assert pay.id in past_ids
    if past != today_ist():
        assert pay.id not in today_ids


def test_list_payments_includes_value_date_day(db):
    c = _customer(db)
    _ar_due(db, c.id, Decimal("100.00"))
    past = date(2024, 1, 15)
    settle_customer_ar(
        c.id,
        ArSettlementIn(amount=Decimal("40.00"), payment_ref="CASH", value_date=past),
        db, AUTH,
    )
    rows = list_payments(db, from_date=past, to_date=past)
    assert any(r["doc_type"] == "ar_payment" for r in rows)


def test_effective_selling_price_keeps_explicit_zero():
    assert effective_selling_price(Decimal("10"), None) is None
    assert effective_selling_price(Decimal("0"), Decimal("0")) == Decimal("0")
    assert effective_selling_price(Decimal("10"), Decimal("0")) == Decimal("0")
    assert effective_selling_price(Decimal("50"), Decimal("50")) is None
    assert coerce_selling_price(Decimal("0"), Decimal("0")) == Decimal("0.00")
    assert coerce_selling_price(Decimal("50"), Decimal("50")) is None


def test_foc_offline_bill_moves_stock_and_posts_zero_ar(db):
    c = _customer(db)
    v = _vendor(db)
    series = BillSeries(name="FOC", prefix="F", start_num=1, end_num=99, current_num=0, is_active=True)
    db.add(series)
    db.flush()
    prod = CatalogProduct(
        our_product_id="FOC-1", vendor_id=v.id, vendor_product_id="V-FOC",
        buying_price=Decimal("0"), selling_price=Decimal("0"), is_active=True,
    )
    db.add(prod)
    db.flush()
    add_stock(db, catalog_product_id=prod.id, our_product_id="FOC-1", quantity=5,
              entry_type="receive", reference_type="seed", reference_id=0)
    db.commit()
    bill, _ = process_offline_customer_order(
        db,
        customer_id=c.id,
        customer_name=c.business_name,
        lines_in=[{"catalog_product_id": prod.id, "quantity": 2}],
        overall_discount_percent=None,
        gst_enabled=False,
        gst_rate_percent=Decimal("0"),
        additional_charges=None,
        bill_series_id=series.id,
        narration="sample",
        actor_type="admin",
        actor_id=1,
        actor_name="Test",
    )
    db.commit()
    assert bill.grand_total == Decimal("0")
    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == prod.id).one()
    assert bal.quantity_on_hand == 3
    ar = db.query(ArLedgerEntry).filter(
        ArLedgerEntry.bill_id == bill.id, ArLedgerEntry.entry_type == "bill"
    ).one()
    assert ar.amount == Decimal("0.00")


def test_foc_rejects_unset_sell_price(db):
    c = _customer(db)
    v = _vendor(db)
    series = BillSeries(name="FOC2", prefix="G", start_num=1, end_num=99, current_num=0, is_active=True)
    db.add(series)
    db.flush()
    prod = CatalogProduct(
        our_product_id="NO-SELL", vendor_id=v.id, vendor_product_id="V-NS",
        buying_price=Decimal("10"), selling_price=None, is_active=True,
    )
    db.add(prod)
    db.flush()
    add_stock(db, catalog_product_id=prod.id, our_product_id="NO-SELL", quantity=5,
              entry_type="receive", reference_type="seed", reference_id=0)
    db.commit()
    with pytest.raises(HTTPException) as ei:
        process_offline_customer_order(
            db,
            customer_id=c.id,
            customer_name=c.business_name,
            lines_in=[{"catalog_product_id": prod.id, "quantity": 1}],
            overall_discount_percent=None,
            gst_enabled=False,
            gst_rate_percent=Decimal("0"),
            additional_charges=None,
            bill_series_id=series.id,
            narration=None,
            actor_type="admin",
            actor_id=1,
            actor_name="Test",
        )
    assert ei.value.status_code == 400
    assert "sell price not set" in str(ei.value.detail)


def _pending_receipt(db, vendor_id: int, qty: int = 10, price=Decimal("10")):
    r = StockReceipt(
        vendor_id=vendor_id, receipt_type="vendor_order", bill_status="pending_bill",
        received_by_type="admin", received_by_name="Test",
    )
    db.add(r)
    db.flush()
    ln = StockReceiptLine(
        receipt_id=r.id, catalog_product_id=1, our_product_id="P1",
        quantity_received=qty, buying_price=price,
    )
    db.add(ln)
    db.flush()
    add_stock(db, catalog_product_id=1, our_product_id="P1", quantity=qty, entry_type="receive",
              reference_type="stock_receipt", reference_id=r.id)
    db.commit()
    return r, ln


def test_bill_receipt_flips_pending_bill_to_billed(db):
    v = _vendor(db)
    r, ln = _pending_receipt(db, v.id)
    body = VendorBillIn(
        total_billed_amount=Decimal("100.00"),
        lines=[VendorBillLineIn(catalog_product_id=ln.catalog_product_id, quantity_billed=10)],
    )
    bill_receipt(db, AUTH, r.id, body)
    r2 = db.get(StockReceipt, r.id)
    assert r2.bill_status == "billed"
    still = (
        db.query(StockReceipt)
        .filter(
            StockReceipt.vendor_id == v.id,
            StockReceipt.bill_status == "pending_bill",
            StockReceipt.deleted_at.is_(None),
        )
        .count()
    )
    assert still == 0


def test_bill_receipt_keeps_vendor_when_other_pending_exists(db):
    v = _vendor(db)
    r1, ln1 = _pending_receipt(db, v.id)
    r2, ln2 = _pending_receipt(db, v.id)
    body = VendorBillIn(
        total_billed_amount=Decimal("100.00"),
        lines=[VendorBillLineIn(catalog_product_id=ln1.catalog_product_id, quantity_billed=10)],
    )
    bill_receipt(db, AUTH, r1.id, body)
    assert db.get(StockReceipt, r1.id).bill_status == "billed"
    assert db.get(StockReceipt, r2.id).bill_status == "pending_bill"
