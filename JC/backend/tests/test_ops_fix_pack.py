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


def test_to_bill_bucket_lists_vendor_with_pending_receipt(db):
    """Regression: VendorOrder.bucket never becomes "received" anywhere in the
    codebase, so the "To bill" hub tab must source from StockReceipt directly —
    not the legacy (permanently-empty) VendorOrder.bucket == "received" query."""
    from app.routers.vendor_orders import list_vendor_orders

    v = _vendor(db)
    _pending_receipt(db, v.id)
    rows = list_vendor_orders(bucket="received", view="default", day="all", db=db, auth=AUTH)
    assert any(r.vendor_id == v.id and r.open_kind == "to_bill" for r in rows)


def test_billed_bucket_lists_vendor_after_bill(db):
    """Regression: VendorOrder.bucket never becomes "billed" either (same dead-column
    issue as "received") — the "Billed" past-browse tab must source from
    StockReceipt.bill_status == "billed" directly, not the legacy empty query."""
    from app.routers.vendor_orders import list_vendor_orders

    v = _vendor(db)
    r, ln = _pending_receipt(db, v.id, qty=10, price=Decimal("10"))
    body = VendorBillIn(
        total_billed_amount=Decimal("100.00"),
        lines=[VendorBillLineIn(catalog_product_id=ln.catalog_product_id, quantity_billed=10)],
    )
    bill_receipt(db, AUTH, r.id, body)
    rows = list_vendor_orders(bucket="billed", view="default", day="all", db=db, auth=AUTH)
    assert any(r2.vendor_id == v.id for r2 in rows)
    to_bill_rows = list_vendor_orders(bucket="received", view="default", day="all", db=db, auth=AUTH)
    assert not any(r2.vendor_id == v.id for r2 in to_bill_rows)


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


def test_bill_receipt_one_off_billing_pct_override_ignores_vendor_default(db):
    """Vendor defaults to 100% billing, but this one invoice is split at 50% —
    override must apply split math without touching the vendor's profile."""
    v = _vendor(db)
    assert v.billing_pct == Decimal("100")
    r, ln = _pending_receipt(db, v.id, qty=100, price=Decimal("10"))
    body = VendorBillIn(
        total_billed_amount=Decimal("500.00"),
        lines=[VendorBillLineIn(catalog_product_id=ln.catalog_product_id, quantity_billed=100)],
        billing_pct_override=Decimal("50"),
    )
    bill_receipt(db, AUTH, r.id, body)
    r2 = db.get(StockReceipt, r.id)
    assert r2.bill_status == "billed"
    assert r2.billing_pct_applied == Decimal("50.00")
    assert r2.actual_ap_amount == Decimal("1000.00")  # 500 on-paper + 500 extra cash
    line = db.get(StockReceiptLine, ln.id)
    assert line.billed_amount == Decimal("500.00")  # 100 x 10 x 50%
    db.refresh(v)
    assert v.billing_pct == Decimal("100")  # vendor profile untouched


def test_bill_receipt_one_off_gst_pct_override_ignores_vendor_default(db):
    """Vendor defaults to 18% GST, but this one paper bill states 12% — override must
    apply that rate without touching the vendor's profile."""
    v = _vendor(db)
    assert v.gst_rate_pct == Decimal("18")
    r, ln = _pending_receipt(db, v.id, qty=10, price=Decimal("100"))
    body = VendorBillIn(
        total_billed_amount=Decimal("1120.00"),
        lines=[VendorBillLineIn(catalog_product_id=ln.catalog_product_id, quantity_billed=10)],
        gst_rate_pct_override=Decimal("12"),
    )
    bill_receipt(db, AUTH, r.id, body)
    r2 = db.get(StockReceipt, r.id)
    assert r2.bill_status == "billed"
    assert r2.gst_rate_pct_applied == Decimal("12.00")
    db.refresh(v)
    assert v.gst_rate_pct == Decimal("18")  # vendor profile untouched


def test_edit_bill_reuses_originally_applied_gst_pct_not_current_vendor_default(db):
    """After billing at a one-off 12% GST override, later edits to that same receipt
    must keep using 12% even if the vendor's profile GST rate has since changed."""
    from app.services.receipt_edit import update_vendor_receipt
    from app.schemas.stock import VendorReceiptCreate, VendorReceiptLineIn

    v = _vendor(db)
    r, ln = _pending_receipt(db, v.id, qty=10, price=Decimal("100"))
    bill_receipt(db, AUTH, r.id, VendorBillIn(
        total_billed_amount=Decimal("1120.00"),
        lines=[VendorBillLineIn(catalog_product_id=ln.catalog_product_id, quantity_billed=10)],
        gst_rate_pct_override=Decimal("12"),
    ))
    assert db.get(StockReceipt, r.id).gst_rate_pct_applied == Decimal("12.00")

    v.gst_rate_pct = Decimal("28")
    db.commit()

    update_vendor_receipt(db, AUTH, r.id, VendorReceiptCreate(
        vendor_id=v.id, total_billed_amount=Decimal("1130.00"),
        lines=[VendorReceiptLineIn(catalog_product_id=ln.catalog_product_id, quantity_billed=10)],
    ))
    assert db.get(StockReceipt, r.id).gst_rate_pct_applied == Decimal("12.00")


def test_edit_bill_reuses_originally_applied_pct_not_current_vendor_default(db):
    """After billing at a one-off 25% override, later edits to that same receipt
    must keep using 25% even if the vendor's profile has since changed back."""
    from app.services.receipt_edit import update_vendor_receipt
    from app.schemas.stock import VendorReceiptCreate, VendorReceiptLineIn

    v = _vendor(db)
    r, ln = _pending_receipt(db, v.id, qty=100, price=Decimal("10"))
    bill_receipt(db, AUTH, r.id, VendorBillIn(
        total_billed_amount=Decimal("250.00"),
        lines=[VendorBillLineIn(catalog_product_id=ln.catalog_product_id, quantity_billed=100)],
        billing_pct_override=Decimal("25"),
    ))
    assert db.get(StockReceipt, r.id).billing_pct_applied == Decimal("25.00")

    # Vendor's own billing_pct never changed from 100, simulating "someone else's"
    # concurrent bill or a later profile edit — the historical bill must not shift.
    update_vendor_receipt(db, AUTH, r.id, VendorReceiptCreate(
        vendor_id=v.id,
        lines=[VendorReceiptLineIn(catalog_product_id=ln.catalog_product_id, quantity_received=100, quantity_billed=100)],
        total_billed_amount=Decimal("250.00"),
    ))
    r2 = db.get(StockReceipt, r.id)
    assert r2.billing_pct_applied == Decimal("25.00")
    line = db.get(StockReceiptLine, ln.id)
    assert line.billed_amount == Decimal("250.00")  # still 100 x 10 x 25%, not x 100%


def test_to_bill_receipt_from_yesterday_still_shows_in_today_queue(db):
    """Regression: "To bill" (bucket=received) day-scoped itself by received_at — a
    receipt received yesterday and never billed would vanish from the default "Today"
    queue (same class of bug as the customer-order New/Confirmed day-scope issue)."""
    from datetime import datetime, timedelta, timezone

    from app.routers.vendor_orders import list_vendor_orders

    v = _vendor(db)
    r, ln = _pending_receipt(db, v.id, qty=10, price=Decimal("10"))
    r.received_at = datetime.now(timezone.utc) - timedelta(days=2)
    db.commit()

    today_rows = list_vendor_orders(bucket="received", view="default", day="today", db=db, auth=AUTH)
    assert any(r2.vendor_id == v.id for r2 in today_rows)
    all_rows = list_vendor_orders(bucket="received", view="default", day="all", db=db, auth=AUTH)
    assert any(r2.vendor_id == v.id for r2 in all_rows)


def test_placed_order_from_yesterday_still_shows_in_today_queue(db):
    """Same issue, one stage earlier: a vendor order placed yesterday and never
    received must not vanish from the "To receive" (bucket=placed) Today queue."""
    from datetime import datetime, timedelta, timezone

    from app.models.vendor_order import VendorOrder, VendorOrderLine, VendorOrderPlacement
    from app.routers.vendor_orders import list_vendor_orders

    v = _vendor(db)
    order = VendorOrder(vendor_id=v.id, bucket="placed", status="placed", is_open=True)
    db.add(order)
    db.flush()
    placement = VendorOrderPlacement(
        vendor_order_id=order.id, status="placed", placed_by_type="admin", placed_by_name="Test",
        placed_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    db.add(placement)
    db.flush()
    db.add(VendorOrderLine(
        placement_id=placement.id, catalog_product_id=1, our_product_id="P1",
        quantity=10, quantity_remaining=10, buying_price=Decimal("10"),
    ))
    db.commit()

    today_rows = list_vendor_orders(bucket="placed", view="default", day="today", db=db, auth=AUTH)
    assert any(r.vendor_id == v.id for r in today_rows)
    all_rows = list_vendor_orders(bucket="placed", view="default", day="all", db=db, auth=AUTH)
    assert any(r.vendor_id == v.id for r in all_rows)


def test_closeable_billed_lists_receipt_and_close_batch_archives_it(db):
    """Regression: "Close Billed Shipments" sourced from VendorOrder.bucket=="billed" /
    VendorOrderPlacement.status=="billed", which never happens in the one-receipt-per-bill
    model — the modal always opened empty and close-batch always no-opped. Must source
    from + write back to StockReceipt.closed_at instead."""
    from app.routers.vendor_orders import close_batch_placements, list_closeable_billed, list_vendor_orders
    from app.schemas.vendor_order import CloseBatchIn

    v = _vendor(db)
    r, ln = _pending_receipt(db, v.id, qty=10, price=Decimal("10"))
    bill_receipt(db, AUTH, r.id, VendorBillIn(
        total_billed_amount=Decimal("100.00"),
        lines=[VendorBillLineIn(catalog_product_id=ln.catalog_product_id, quantity_billed=10)],
    ))

    items = list_closeable_billed(vendor_id=None, db=db, auth=AUTH)
    assert any(it.id == r.id for it in items)

    result = close_batch_placements(CloseBatchIn(placement_ids=[r.id], reason="settled"), db, AUTH)
    assert result["closed"] == 1
    assert db.get(StockReceipt, r.id).closed_at is not None

    # Closed receipts drop off both the closeable list and the active "Billed" tab.
    items_after = list_closeable_billed(vendor_id=None, db=db, auth=AUTH)
    assert not any(it.id == r.id for it in items_after)
    billed_rows = list_vendor_orders(bucket="billed", view="default", day="all", db=db, auth=AUTH)
    assert not any(row.vendor_id == v.id for row in billed_rows)


def test_edit_receipt_can_remove_line_even_if_stock_already_shipped_out(db):
    """Regression: editing a receipt (reduce qty / delete a line) blocked with a 400
    the moment any of that line's received stock had already shipped out — the common
    case for a receipt more than a day old. Same "never blocks, only corrects the
    running total" philosophy as void (see void_service.py) must apply to edit too."""
    from app.models.stock import StockBalance
    from app.services.receipt_edit import update_vendor_receipt
    from app.schemas.stock import VendorReceiptCreate, VendorReceiptLineIn

    v = _vendor(db)
    p1 = CatalogProduct(id=1, our_product_id="P1", vendor_id=v.id, vendor_product_id="VP1",
                         buying_price=Decimal("10"), selling_price=Decimal("20"))
    p2 = CatalogProduct(id=2, our_product_id="P2", vendor_id=v.id, vendor_product_id="VP2",
                         buying_price=Decimal("10"), selling_price=Decimal("20"))
    db.add_all([p1, p2])
    db.flush()
    r, ln1 = _pending_receipt(db, v.id, qty=10, price=Decimal("10"))
    ln2 = StockReceiptLine(
        receipt_id=r.id, catalog_product_id=2, our_product_id="P2",
        quantity_received=5, buying_price=Decimal("10"),
    )
    db.add(ln2)
    db.flush()
    add_stock(db, catalog_product_id=2, our_product_id="P2", quantity=5, entry_type="receive",
              reference_type="stock_receipt", reference_id=r.id)
    db.commit()

    # Some of P2's stock already shipped out to a customer since it was received.
    add_stock(db, catalog_product_id=2, our_product_id="P2", quantity=-4, entry_type="reserved",
              reference_type="customer_placement", reference_id=999, party="Cust")
    db.commit()

    body = VendorReceiptCreate(
        vendor_id=v.id, order_receipt_number="R1",
        lines=[VendorReceiptLineIn(catalog_product_id=1, quantity_received=10, quantity_billed=0, billed_amount=0)],
    )
    result = update_vendor_receipt(db, AUTH, r.id, body)
    assert result["ok"] is True
    bal = db.query(StockBalance).filter(StockBalance.catalog_product_id == 2).first()
    assert bal.quantity_on_hand == -4  # corrected, allowed negative — never blocks


def test_value_debit_note_keeps_item_association_when_line_specific(db):
    """Regression: a rate/amount-mismatch debit note tied to one line lost its product
    link on save (create_debit_note only set catalog_product_id/our_product_id for
    note_type="item"), so the UI/ledger/PDF could only ever show "Value ₹X" with no way
    to tell which item it was for — unlike qty-mismatch (item-type) notes, which always
    show the item. Whole-bill-total notes (no product) must still work with None."""
    from app.services.debit_notes import create_debit_note
    from app.schemas.debit_note import DebitNoteIn

    v = _vendor(db)
    r, ln = _pending_receipt(db, v.id, qty=10, price=Decimal("10"))

    note = create_debit_note(db, AUTH, vendor_id=v.id, receipt_id=r.id, body=DebitNoteIn(
        note_type="value", direction="under", catalog_product_id=1, amount=Decimal("5.00"),
        notes="rate mismatch",
    ))
    assert note.catalog_product_id == 1
    assert note.our_product_id == "P1"

    whole_bill_note = create_debit_note(db, AUTH, vendor_id=v.id, receipt_id=r.id, body=DebitNoteIn(
        note_type="value", direction="over", amount=Decimal("3.00"), notes="total mismatch",
    ))
    assert whole_bill_note.catalog_product_id is None
    assert whole_bill_note.our_product_id is None
