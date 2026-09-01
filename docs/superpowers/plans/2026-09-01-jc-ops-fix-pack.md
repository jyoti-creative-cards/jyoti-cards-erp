# JC ERP Ops Fix Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship six isolated JC ERP ops fixes in one backend + admin change: extra-as-advance payments, collection `value_date`, FOC/zero bills, vendor alias on Buying, vendor leaves To bill after bill, purchase rate on Receive Goods.

**Architecture:** No schema migrations. Reuse signed ledger (`as_signed_decrease`, `customer_ar_totals` / `vendor_ap_totals`), existing nullable `value_date`, `bill_status`, `Vendor.alias`, and `hide_cost`. U1 and U2 share the four settle/record-payment endpoints — sequence them so those files change in order. U4 and U5 both touch Buying hub JS — keep diffs in separate tasks. Do not touch root `backend/` (different app). Do not mix unrelated dirty admin files already in the working tree.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, vanilla admin JS (`JC/web/admin/`), pytest (sqlite in-memory, same pattern as `JC/backend/tests/test_void_service.py`).

**Spec:** `docs/superpowers/specs/2026-09-01-jc-ops-fix-pack-design.md` (commit `20393a5c38eb48b8e83f899cc9f0aa0e9f49d411`)

## Global Constraints

- JC ERP only: `JC/backend/`, `JC/web/admin/`. Root `backend/` is a different app — ignore it.
- Money: one signed payment row via `as_signed_decrease`. Outstanding = sum of signed amounts. UI must not re-sum raw rows; use `dues_snapshot()` / existing totals helpers.
- Dates: `created_at` stays real UTC. Report/daybook IST days use `ist_day_bounds_utc` / `ist_range_bounds_utc`.
- Soft delete: ledger aggregates keep `deleted_at is None`.
- Cost visibility: `hide_cost` / `costs.read` unchanged. Receive rate is visible only when the actor can already see buying price (admin or `costs.read`). Staff without that permission still see "—".
- No schema migrations. `value_date`, `bill_status`, `alias`, and signed amounts already exist.
- Do not change signed-ledger math, `dues_snapshot()`, or IST date-bound helpers.
- Do not split payment into due + advance rows. Do not add an `advance` entry type.
- Extra-as-advance applies only when outstanding `> 0` and amount exceeds it. Still reject when outstanding `<= 0`.
- No FOC/sample badge on bill UI or PDF. No total-qty footer on Receive Goods.
- Customer / Selling to-bill stuck is out of scope.
- Implementation commits must not include unrelated dirty files (`JC/web/admin/js/catalog.js`, `products.js`, `styles.css`, and unrelated `index.html` / `stock.js` hunks already in the working tree).

## File map

- Create: `JC/backend/tests/test_ops_fix_pack.py` — U1/U2/U3/U5 sqlite tests
- Modify: `JC/backend/app/services/pricing.py` — explicit sell `0` stays set
- Modify: `JC/backend/app/schemas/accounts_receivable.py` — `ArSettlementIn.value_date`
- Modify: `JC/backend/app/schemas/accounts_payable.py` — `ApSettlementIn.value_date`
- Modify: `JC/backend/app/services/ar_ledger.py` — `post_payment_entry(..., value_date=)`
- Modify: `JC/backend/app/services/ap_ledger.py` — `post_payment_entry(..., value_date=)`
- Modify: `JC/backend/app/routers/accounts_receivable.py` — drop exceed-due; pass `value_date`
- Modify: `JC/backend/app/routers/accounts_payable.py` — drop exceed-due; pass `value_date`
- Modify: `JC/backend/app/services/reports.py` — daybook + `list_payments` bucket by `value_date`
- Modify: `JC/backend/app/services/customer_bill_process.py` — allow sell/grand `0`
- Modify: `JC/backend/app/services/customer_order_flow.py` — allow sell `0` on place/update
- Modify: `JC/backend/app/schemas/vendor_order.py` — `alias` on hub/detail summaries
- Modify: `JC/backend/app/routers/vendor_orders.py` — pass `vendor.alias` into summaries
- Modify: `JC/backend/app/routers/stock.py` — None-safe `buying_price` on placed-for-receipt
- Modify: `JC/web/admin/js/finance.js` — date picker + optional over-due hint
- Modify: `JC/web/admin/js/stock.js` — vendor alias on picker cards; await hub refresh after bill; receive rate fallback
- Modify: `JC/web/admin/js/vendor-orders.js` — hub alias + `refreshIfOpen` / `loadList` after bill

Do **not** modify: `JC/backend/app/routers/finance.py` (other outstanding check), `JC/backend/app/routers/shop.py` (shop price gate), freight settle, expense dates, bill/opening `value_date` posters.

---

### Task 1: Extra collection (AR + AP)

**Files:**
- Create: `JC/backend/tests/test_ops_fix_pack.py`
- Modify: `JC/backend/app/routers/accounts_receivable.py:119-123` and `:188-192`
- Modify: `JC/backend/app/routers/accounts_payable.py:118-122` and `:168-172`

**Interfaces:**
- Consumes: `post_payment_entry` (AR/AP) as they exist today (no `value_date` yet); `customer_ar_totals` / `vendor_ap_totals`; `ArSettlementIn` / `ApSettlementIn`
- Produces: four endpoints accept `amount > outstanding` when `outstanding > 0`; one payment row of `as_signed_decrease(full amount)`; outstanding may be negative

- [ ] **Step 1: Write the failing tests**

Create `JC/backend/tests/test_ops_fix_pack.py` with sqlite fixtures matching `test_void_service.py`. Do not import root `backend/`.

```python
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
from app.models.customer import Customer
from app.models.vendor import Vendor
from app.routers.accounts_payable import record_vendor_payment, settle_vendor_ap
from app.routers.accounts_receivable import record_customer_payment, settle_customer_ar
from app.schemas.accounts_payable import ApSettlementIn
from app.schemas.accounts_receivable import ArSettlementIn
from app.services.ap_ledger import post_bill_entry as post_ap_bill, vendor_ap_totals
from app.services.ar_ledger import post_bill_entry as post_ar_bill, customer_ar_totals
from app.services.money import as_signed_decrease

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
```

If `post_ar_bill(..., bill_id=None)` or `post_ap_bill(..., receipt_id=None)` hits a NOT NULL / FK on this sqlite schema, seed with a raw ledger row instead:

```python
db.add(ArLedgerEntry(
    customer_id=customer_id, entry_type="bill", amount=amount,
    description="seed due", created_by_type="admin", created_by_name="Test",
))
```

Same idea for AP (`ApLedgerEntry`). Keep one seed path only.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd JC/backend && python3 -m pytest tests/test_ops_fix_pack.py::test_ar_settle_over_due_becomes_advance tests/test_ops_fix_pack.py::test_ap_settle_over_due_becomes_advance tests/test_ops_fix_pack.py::test_ar_record_payment_over_due_ok tests/test_ops_fix_pack.py::test_ap_record_payment_over_due_ok -v`

Expected: FAIL with `HTTPException` 400 (`payment cannot exceed outstanding` or the accountant wording).

- [ ] **Step 3: Remove the exceed-due rejects**

In `JC/backend/app/routers/accounts_receivable.py` `settle_customer_ar` and `record_customer_payment`, **delete only** the `if amount > outstanding:` blocks. Keep `if outstanding <= 0:` and the existing messages. Keep `amount` from `body.amount.quantize(Decimal("0.01"))` (`ArSettlementIn.amount` is already `gt=0`).

In `JC/backend/app/routers/accounts_payable.py` `settle_vendor_ap` and `record_vendor_payment`, **delete only** the matching `if amount > outstanding:` blocks. Keep `outstanding <= 0` rejects.

Do not split the payment. Do not add an `advance` entry type. `post_payment_entry` already stores one negative signed row for the full amount.

Do not change `JC/backend/app/routers/finance.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd JC/backend && python3 -m pytest tests/test_ops_fix_pack.py -k "over_due or zero_outstanding or non_positive" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add JC/backend/tests/test_ops_fix_pack.py \
  JC/backend/app/routers/accounts_receivable.py \
  JC/backend/app/routers/accounts_payable.py
git commit -m "$(cat <<'EOF'
Allow AR/AP collect and pay amounts above due as advance.

EOF
)"
```

---

### Task 2: Collection date (`value_date` + daybook)

**Files:**
- Modify: `JC/backend/app/schemas/accounts_receivable.py:61-65`
- Modify: `JC/backend/app/schemas/accounts_payable.py:65-69`
- Modify: `JC/backend/app/services/ar_ledger.py:218-246`
- Modify: `JC/backend/app/services/ap_ledger.py:339-371`
- Modify: `JC/backend/app/routers/accounts_receivable.py` (both payment posters)
- Modify: `JC/backend/app/routers/accounts_payable.py` (both payment posters)
- Modify: `JC/backend/app/services/reports.py` (`list_payments`, `daybook` payment_in/payment_out)
- Modify: `JC/backend/tests/test_ops_fix_pack.py`

**Interfaces:**
- Consumes: Task 1 four endpoints; `today_ist()` from `app.services.biz_date`; `_day_bounds` / `_range_bounds` already in `reports.py`
- Produces: `ArSettlementIn.value_date: Optional[date] = None` and `ApSettlementIn.value_date: Optional[date] = None`; `post_payment_entry(..., value_date: Optional[date] = None)` on AR and AP; omitted `value_date` stores `today_ist()`; daybook/`list_payments` include a payment on the IST calendar day of `value_date` when set, else `created_at` bounds

- [ ] **Step 1: Write the failing date tests**

Append to `JC/backend/tests/test_ops_fix_pack.py`:

```python
from app.services.biz_date import today_ist
from app.services.reports import daybook, list_payments


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
```

`daybook` returns `{"date", "entries", "totals"}`. Assert against `entries`.

- [ ] **Step 2: Run date tests to verify they fail**

Run: `cd JC/backend && python3 -m pytest tests/test_ops_fix_pack.py::test_ar_settle_persists_past_value_date tests/test_ops_fix_pack.py::test_ar_settle_omitted_value_date_is_today_ist tests/test_ops_fix_pack.py::test_daybook_uses_value_date_not_created_at -v`

Expected: FAIL — `ArSettlementIn` has no `value_date`, or payment `value_date` is `None`, or daybook misses the past day.

- [ ] **Step 3: Add `value_date` on settlement schemas**

`JC/backend/app/schemas/accounts_receivable.py` — `date` is already imported:

```python
class ArSettlementIn(BaseModel):
    payment_ref: Optional[str] = Field(None, max_length=120)
    payment_mode_id: Optional[int] = None
    amount: Decimal = Field(..., gt=0)
    comment: Optional[str] = None
    value_date: Optional[date] = None
```

`JC/backend/app/schemas/accounts_payable.py`:

```python
class ApSettlementIn(BaseModel):
    payment_ref: str = Field(..., min_length=1, max_length=120)
    amount: Decimal = Field(..., gt=0)
    payment_receipt_key: Optional[str] = None
    comment: Optional[str] = None
    value_date: Optional[date] = None
```

Pydantic `date` rejects a time-of-day string. Unparseable JSON dates fail request validation. Do not accept datetime.

- [ ] **Step 4: Persist `value_date` on `post_payment_entry`**

AR `JC/backend/app/services/ar_ledger.py` — add `value_date: Optional[date] = None` after `payment_mode` and set it on `ArLedgerEntry`:

```python
def post_payment_entry(
    db: Session,
    *,
    customer_id: int,
    amount: Decimal,
    payment_ref: str,
    payment_comment: Optional[str],
    description: str,
    actor_type: str,
    actor_id: Optional[int],
    actor_name: str,
    payment_mode: Optional[str] = None,
    value_date: Optional[date] = None,
) -> ArLedgerEntry:
    get_or_create_ar_account(db, customer_id)
    entry = ArLedgerEntry(
        customer_id=customer_id,
        entry_type="payment",
        amount=as_signed_decrease(amount),
        payment_ref=payment_ref,
        payment_mode=payment_mode,
        payment_comment=payment_comment,
        description=description,
        value_date=value_date,
        created_by_type=actor_type,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(entry)
    db.flush()
    return entry
```

Add `from datetime import date` if not already imported in this module (it is used by opening-balance).

AP `JC/backend/app/services/ap_ledger.py` — same extra kwarg and `value_date=value_date` on `ApLedgerEntry`. Do not change bill / opening-balance posters.

- [ ] **Step 5: Wire routers — default omitted date to today IST**

In all four endpoints, after amount/mode checks and before `post_payment_entry`:

```python
from app.services.biz_date import today_ist

pay_day = body.value_date or today_ist()
```

Pass `value_date=pay_day` into `post_payment_entry`. Accountant `record-payment` has no date picker — omitted body field becomes today IST, not 400.

Do not set `created_at` on the payment row (real UTC save time stays).

- [ ] **Step 6: Daybook and `list_payments` match `value_date`**

In `JC/backend/app/services/reports.py` add (near `_day_bounds`):

```python
from sqlalchemy import and_, or_


def _payment_on_ist_day(model, day: date):
    start, end = _day_bounds(day)
    return or_(
        model.value_date == day,
        and_(
            model.value_date.is_(None),
            model.created_at >= start,
            model.created_at <= end,
        ),
    )


def _payment_in_ist_range(model, from_date: Optional[date], to_date: Optional[date]):
    start, end = _range_bounds(from_date, to_date)
    created_clause = True
    if start is not None:
        created_clause = and_(created_clause, model.created_at >= start)
    if end is not None:
        created_clause = and_(created_clause, model.created_at <= end)
    value_clause = True
    if from_date is not None:
        value_clause = and_(value_clause, model.value_date >= from_date)
    if to_date is not None:
        value_clause = and_(value_clause, model.value_date <= to_date)
    if from_date is None and to_date is None:
        return True
    return or_(
        and_(model.value_date.isnot(None), value_clause),
        and_(model.value_date.is_(None), created_clause),
    )
```

Replace AR/AP **payment** filters only (not bills, opening, freight, sales):

`daybook` payment_in / payment_out — delete `created_at >= start` / `<= end` on those two queries; add `_payment_on_ist_day(ArLedgerEntry, day)` / `_payment_on_ist_day(ApLedgerEntry, day)`.

`list_payments` AR/AP payment queries — replace `created_at` start/end filters with `_payment_in_ist_range(...)`. Keep freight on `created_at`.

For AR/AP payment row dicts in `list_payments`, set:

```python
"date": (e.value_date.isoformat() if e.value_date else (e.created_at.date().isoformat() if e.created_at else None)),
```

Leave `created_at` as the real timestamp. Do not change other daybook kinds.

- [ ] **Step 7: Run date tests**

Run: `cd JC/backend && python3 -m pytest tests/test_ops_fix_pack.py -k "value_date or daybook or list_payments or over_due" -v`

Expected: PASS. Existing `tests/test_biz_date.py` still PASS.

- [ ] **Step 8: Commit**

```bash
git add JC/backend/app/schemas/accounts_receivable.py \
  JC/backend/app/schemas/accounts_payable.py \
  JC/backend/app/services/ar_ledger.py \
  JC/backend/app/services/ap_ledger.py \
  JC/backend/app/routers/accounts_receivable.py \
  JC/backend/app/routers/accounts_payable.py \
  JC/backend/app/services/reports.py \
  JC/backend/tests/test_ops_fix_pack.py
git commit -m "$(cat <<'EOF'
Persist collect/pay value_date and bucket daybook on that IST day.

EOF
)"
```

---

### Task 3: Collect / pay form date + over-due hint

**Files:**
- Modify: `JC/web/admin/js/finance.js` (`openSettle` ~1000-1024, `submitSettle` ~1034-1062, `openArSettle` ~1448-1479, `submitArSettle` ~1484-1502)

**Interfaces:**
- Consumes: Task 1 (API accepts over-due); Task 2 (`value_date` on settle body)
- Produces: required `<input type="date">` defaulting to local IST calendar today; POST includes `value_date`; optional one-line hint when amount > due; no client max; success still uses `settleSuccess` `balanceAfter` (may be negative)

- [ ] **Step 1: Add `localToday()` in `finance.js`**

Place near the other helpers at the top of the IIFE (finance.js has no `localToday` today). Match `stock.js`:

```javascript
  function localToday() {
    const n = new Date();
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
  }
```

Browser local date on this staff app is IST. Do not add a date field to accountant prompt `record-payment`.

- [ ] **Step 2: AR collect modal — date + hint**

In `openArSettle`, after the Due review row and before the amount input, add:

```javascript
      <label class="label">Collection date</label>
      <input type="date" class="input" id="ar-settle-date" value="${ctx.esc(localToday())}" required style="margin-bottom:12px;" />
      <label class="label">Amount (₹)</label>
      <input type="number" step="0.01" class="input" id="ar-settle-amount" value="" placeholder="Enter amount" style="margin-bottom:8px;" oninput="Finance.onArSettleAmount()" />
      <p id="ar-settle-over-hint" class="hidden" style="font-size:12px;color:var(--muted);margin:0 0 12px;">Extra will sit as credit on this customer.</p>
```

Keep mode / ref / comment. Do not set `max` on the amount input.

Add:

```javascript
  function onArSettleAmount() {
    const due = Number(arDetail?.outstanding) || 0;
    const amount = parseFloat(document.getElementById("ar-settle-amount")?.value || "0");
    const hint = document.getElementById("ar-settle-over-hint");
    if (hint) hint.classList.toggle("hidden", !(due > 0 && amount > due));
  }
```

Export `onArSettleAmount` on the `Finance` return object next to `submitArSettle`.

In `submitArSettle`, after amount `<= 0` toast:

```javascript
    const valueDate = (document.getElementById("ar-settle-date")?.value || "").trim();
    if (!valueDate) return ctx.toast("Enter collection date", "error");
```

Add `value_date: valueDate` to the JSON body. Do not cap amount.

- [ ] **Step 3: AP pay modal — date + hint**

In `openSettle`, after Due and before amount:

```javascript
      <label class="label">Payment date</label>
      <input type="date" class="input" id="settle-date" value="${ctx.esc(localToday())}" required style="margin-bottom:12px;" />
      <label class="label">Amount (₹)</label>
      <input type="number" step="0.01" class="input" id="settle-amount" value="" placeholder="Enter amount" style="margin-bottom:8px;" oninput="Finance.onApSettleAmount()" />
      <p id="settle-over-hint" class="hidden" style="font-size:12px;color:var(--muted);margin:0 0 12px;">Extra will sit as credit on this vendor.</p>
```

Keep ref / comment / file. Add `onApSettleAmount` (same show/hide vs `apDetail.outstanding`). Export it.

In `submitSettle`, after amount check:

```javascript
    const valueDate = (document.getElementById("settle-date")?.value || "").trim();
    if (!valueDate) return ctx.toast("Enter payment date", "error");
```

POST body becomes `{ payment_ref: ref, amount, payment_receipt_key: key, comment, value_date: valueDate }`.

Do not change freight settle/advance. Do not edit `index.html` — settle bodies are injected.

- [ ] **Step 4: Manual / browser check (no pytest)**

Admin Collect: date defaults to today; amount > due shows hint and submits; ledger row shows chosen date (`value_date`). Same for AP Pay. Over-due success panel may show negative "Balance after".

- [ ] **Step 5: Commit**

```bash
git add JC/web/admin/js/finance.js
git commit -m "$(cat <<'EOF'
Add collect/pay date picker and allow extra as credit.

EOF
)"
```

Stage only `finance.js`. Leave other dirty admin files unstaged.

---

### Task 4: Zero-amount / sample bills

**Files:**
- Modify: `JC/backend/app/services/pricing.py:7-26`
- Modify: `JC/backend/app/services/customer_bill_process.py:700-701` and `:1129-1133`
- Modify: `JC/backend/app/services/customer_order_flow.py:429-433` and `:696-701`
- Modify: `JC/backend/tests/test_ops_fix_pack.py`

**Interfaces:**
- Consumes: `effective_selling_price(buying_price, selling_price) -> Optional[Decimal]`; `process_offline_customer_order`; `create_received_placement`; `edit_customer_bill`
- Produces: explicit sell `0` is set (including buy `0`); `None` still "sell price not set"; grand total `0` allowed; stock still moves; AR still posts one bill entry of `0`

- [ ] **Step 1: Write failing pricing + FOC tests**

Append:

```python
from app.models.bill_series import BillSeries
from app.models.catalog_product import CatalogProduct
from app.models.stock import StockBalance
from app.services.customer_bill_process import process_offline_customer_order
from app.services.pricing import coerce_selling_price, effective_selling_price
from app.services.stock_receipt import add_stock


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
```

- [ ] **Step 2: Run FOC tests to verify they fail**

Run: `cd JC/backend && python3 -m pytest tests/test_ops_fix_pack.py::test_effective_selling_price_keeps_explicit_zero tests/test_ops_fix_pack.py::test_foc_offline_bill_moves_stock_and_posts_zero_ar -v`

Expected: FAIL — `effective_selling_price(0, 0)` is `None` and/or offline bill raises "sell price not set".

- [ ] **Step 3: Keep explicit `0` in pricing**

Replace `effective_selling_price` and `coerce_selling_price` in `JC/backend/app/services/pricing.py`:

```python
def effective_selling_price(buying_price, selling_price) -> Optional[Decimal]:
    """Sell is unset when null, or when it was copied equal to buy (not a real sell).

    Explicit 0 is a real FOC price, including when buy is also 0.
    """
    if selling_price is None:
        return None
    sell = Decimal(str(selling_price))
    if sell == 0:
        return Decimal("0")
    buy = Decimal(str(buying_price or 0))
    if sell == buy:
        return None
    return sell


def coerce_selling_price(buying_price, selling_price) -> Optional[Decimal]:
    """Normalize inbound sell for storage — equal-to-buy becomes null, except explicit 0."""
    if selling_price is None:
        return None
    sell = Decimal(str(selling_price)).quantize(Decimal("0.01"))
    if sell == 0:
        return sell
    buy = Decimal(str(buying_price or 0)).quantize(Decimal("0.01"))
    if sell == buy:
        return None
    return sell
```

- [ ] **Step 4: Allow `0` on bill and order-flow gates**

`process_offline_customer_order` (`customer_bill_process.py` ~700):

```python
        if prod.selling_price is None:
            raise HTTPException(400, f"sell price not set for {prod.our_product_id}")
```

`edit_customer_bill` (~1129):

```python
        from app.services.pricing import effective_selling_price
        unit_price = old.unit_price if old else effective_selling_price(prod.buying_price, prod.selling_price)
        if unit_price is None:
            raise HTTPException(400, f"sell price not set for {prod.our_product_id}")
```

Do **not** use `or Decimal("0")` then `<= 0` — that rejects FOC.

Order update (~429) and `create_received_placement` (~696) in `customer_order_flow.py`:

```python
        from app.services.pricing import effective_selling_price

        unit_price = effective_selling_price(prod.buying_price, prod.selling_price)
        if unit_price is None:
            raise ValueError(f"sell price not set for {prod.our_product_id}")
```

For `create_received_placement`, if `raw.get("unit_price")` is present, `Decimal(str(unit_price))` including `0` is valid. Only call `effective_selling_price` when `unit_price is None`. Then `if unit_price is None: raise`. Remove `if unit_price <= 0`.

`process_customer_bill` uses open-line `unit_price` already stored at place time — no extra gate. Do not add a minimum grand-total check. Do not skip `post_bill_entry` when grand is 0. Do not add a FOC badge. Do not change `shop.py`.

- [ ] **Step 5: Run FOC tests**

Run: `cd JC/backend && python3 -m pytest tests/test_ops_fix_pack.py -k "foc or effective_selling" tests/test_bill_math.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add JC/backend/app/services/pricing.py \
  JC/backend/app/services/customer_bill_process.py \
  JC/backend/app/services/customer_order_flow.py \
  JC/backend/tests/test_ops_fix_pack.py
git commit -m "$(cat <<'EOF'
Allow sell price 0 sample bills with stock and zero AR.

EOF
)"
```

---

### Task 5: Vendor alias on Buying pickers and hub cards

**Files:**
- Modify: `JC/backend/app/schemas/vendor_order.py:89-102` and `:105-116`
- Modify: `JC/backend/app/routers/vendor_orders.py` (every `VendorOrderSummary(` / `VendorOrderDetail(` builder)
- Modify: `JC/web/admin/js/vendor-orders.js` (`filterHubOrders`, hub cards, place-order picker)
- Modify: `JC/web/admin/js/stock.js` (receive / bill / offline vendor cards + search placeholder)

**Interfaces:**
- Consumes: `Vendor.alias`; `OrdersUI.filterAndRankParties` / `partySearchRank` (already match `party.alias`); `/catalog/vendors` and `/vendors` already return `alias`
- Produces: `VendorOrderSummary.alias: Optional[str] = None` and `VendorOrderDetail.alias: Optional[str] = None`; hub filter objects keep `alias`; cards show alias on the line under the business name when present; empty alias adds no line and no "—"

- [ ] **Step 1: Add `alias` on summary/detail schemas**

```python
class VendorOrderSummary(BaseModel):
    id: int
    vendor_id: int
    vendor_name: str
    vendor_city: Optional[str]
    vendor_label: str
    alias: Optional[str] = None
    status: str
    # ...unchanged fields...
```

```python
class VendorOrderDetail(BaseModel):
    id: int
    vendor_id: int
    vendor_name: str
    vendor_city: Optional[str]
    vendor_label: str
    alias: Optional[str] = None
    status: str
    # ...unchanged fields...
```

- [ ] **Step 2: Pass `alias=vendor.alias` at every builder**

In `vendor_orders.py` add `alias=vendor.alias` to:

- `_build_detail` `VendorOrderDetail(...)`
- `_summary_from_order` `VendorOrderSummary(...)`
- `_summaries_from_orders` loop
- open bucket `to_receive` and `to_bill` `VendorOrderSummary(...)`
- closed / billed summary constructors in the same file

Do not change `_vendor_label` (still `business — city`). Do not add customer alias work.

- [ ] **Step 3: Hub search passes `alias` through**

`filterHubOrders` already spreads `o`. After backend adds `alias`, `partySearchRank` matches it. Keep the `business_name` / `city_name` mapping. Add an explicit fallback only if needed:

```javascript
        alias: o.alias || "",
```

Search placeholder on the hub bar may stay "Search vendor…".

- [ ] **Step 4: Shared alias subtitle for hub cards**

In `vendor-orders.js` add:

```javascript
  function aliasUnderTitle(o) {
    const alias = String(o?.alias || "").trim();
    return alias ? ctx.esc(alias) : "";
  }

  function hubCardMeta(o, restHtml) {
    const alias = aliasUnderTitle(o);
    return alias ? `${alias} · ${restHtml}` : restHtml;
  }
```

`partyCard` already renders `meta` under `title`. Use that slot. Empty alias: `restHtml` only, no "—".

Update `renderOpenHubCard`, `renderPlacedHubCard`, `renderReceivedHubCard`, `renderBilledHubCard`, `renderNoteHubCard`:

```javascript
      title: o.vendor_label,
      meta: hubCardMeta(o, `${o.line_count} ...existing meta...`),
```

Keep existing count copy. Do not replace `vendor_label` as the title.

- [ ] **Step 5: Place-order picker card + search**

In the step-1 vendor card (`vendor-orders.js` ~1836):

```javascript
            const alias = (v.alias || "").trim();
            return `<button type="button" class="vo-wiz-vendor-card${selectedCls}" onclick="VendorOrders.pickVendor(${v.id})">
              <span class="vo-wiz-vendor-letter">${ctx.esc((v.business_name || "?").slice(0, 1).toUpperCase())}</span>
              <span class="vo-wiz-vendor-meta">
                <strong>${ctx.esc(v.business_name || "Vendor")}</strong>
                ${alias ? `<span>${ctx.esc(alias)}</span>` : ""}
                <span>${city ? ctx.esc(city) : "No city"}${v.phone ? ` · ${ctx.esc(v.phone)}` : ""}</span>
              </span>
              <span class="vo-wiz-vendor-check">${wizardVendorId === v.id ? "✓" : ""}</span>
            </button>`;
```

Placeholder: `Search vendor name, alias, city, or phone…`. `filterAndRankParties` already uses `alias` if the `/vendors` row has it (`ensureWizardVendors`). Do not change `orders-ui.js` unless a picker object truly lacks `alias` — then copy it from the vendor payload when caching vendors.

- [ ] **Step 6: Receive / bill / offline picker cards in `stock.js`**

There are two vendor lists (receive/bill ~575, offline ~618). Same card pattern: business strong, alias span if present, city span. Update both placeholders to include alias.

If a list object lacks `alias` after fetch, map it when filling `offlineVendorsCache`:

```javascript
offlineVendorsCache = (await ctx.api("/catalog/vendors", {}, 0) || []).map(v => ({
  ...v,
  alias: v.alias || "",
}));
```

Do not add a qty footer. Do not restyle People cards.

- [ ] **Step 7: Manual check**

Receive + bill + place-order pickers: typing alias hits the vendor; alias shows under the name. Hub Open/To receive/To bill/Billed/Closed cards show alias under title when set. Vendor with empty alias looks as today.

- [ ] **Step 8: Commit**

```bash
git add JC/backend/app/schemas/vendor_order.py \
  JC/backend/app/routers/vendor_orders.py \
  JC/web/admin/js/vendor-orders.js \
  JC/web/admin/js/stock.js
git commit -m "$(cat <<'EOF'
Show and search vendor alias on Buying pickers and hub cards.

EOF
)"
```

If `stock.js` / `vendor-orders.js` already have unrelated dirty hunks, stage with care (`git add -p` is interactive — do not use `-i` / `-p`). Copy only the alias hunks into a clean edit, or stash unrelated work first. Do not commit catalog/products/styles.

---

### Task 6: Vendor leaves To bill after bill

**Files:**
- Modify: `JC/backend/tests/test_ops_fix_pack.py`
- Modify: `JC/backend/app/services/vendor_receive_bill.py:226` (verify; fix only if a path skips the flip)
- Modify: `JC/web/admin/js/stock.js` `submitReceipt` bill-success path (~1539-1628)
- Modify: `JC/web/admin/js/vendor-orders.js` `refreshIfOpen` (~1323) and `loadList` (~248)

**Interfaces:**
- Consumes: `bill_receipt` already sets `receipt.bill_status = "billed"` then `db.commit()`; `POST /stock/receipts/{id}/bill` already calls `bill_receipt`; open/to-bill query is `StockReceipt.bill_status == "pending_bill"` and `deleted_at is None`; hub "To bill" stage is `currentBucket === "received"` (`BUCKET_LABELS.received === "To bill"`)
- Produces: billed receipt is `billed`; vendor omitted from pending-bill open query unless another pending receipt exists; after save, `/vendor-orders` cache cleared, hub expand cache for that vendor cleared, Open/To-bill list refetched; Done on the success panel also refreshes

- [ ] **Step 1: Write failing to-bill tests**

Need a real `bill_receipt` call. Reuse `_vendor` / `_receipt` from `test_void_service.py` (copy the helpers into this module — do not import from that test file). `VendorBillIn` lives in `app.schemas.stock`.

```python
from app.models.stock import StockReceipt, StockReceiptLine
from app.schemas.stock import VendorBillIn, VendorBillLineIn
from app.services.stock_receipt import add_stock
from app.services.vendor_receive_bill import bill_receipt


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
```

If `VendorBillIn` / `VendorBillLineIn` names differ, use the actual classes in `JC/backend/app/schemas/stock.py`. If `bill_receipt` already flips status, these tests PASS immediately — that is OK; do not add a second billing service. Then the remaining work is the admin refresh.

- [ ] **Step 2: Run to-bill tests**

Run: `cd JC/backend && python3 -m pytest tests/test_ops_fix_pack.py -k "bill_receipt" -v`

Expected: PASS if flip already exists; FAIL only if a required field on `VendorBillIn` is missing — fix the test fixture, not a second bill service.

- [ ] **Step 3: Confirm every admin bill-save path**

`POST /stock/receipts/{id}/bill` (`create_receipt_bill`) already calls `bill_receipt`. Edit-as-bill is `update_vendor_receipt` → `_edit_bill` on an already-`billed` row — do not add another flip. If you find a wizard path that bills without `bill_receipt`, route it through `bill_receipt` instead of copying status logic.

If `bill_receipt` ever returned success without setting `billed`, set `receipt.bill_status = "billed"` **before** `db.commit()` (it already does at line 226). Do not toast success in JS if the request failed.

- [ ] **Step 4: `refreshIfOpen` always refetches To bill**

`loadList` already uses `cacheTtl=0`. Still call `ctx.invalidateCache?.("/vendor-orders")` at the start of `loadList` so any other cached GET cannot win.

Replace `refreshIfOpen` with:

```javascript
  async function refreshIfOpen(vendorId) {
    if (!vendorId) return;
    clearHubCacheForVendor(vendorId);
    ctx.invalidateCache?.("/vendor-orders");
    ctx.invalidateCache?.("/stock");
    if (isDetailVisible() && detailVendorId === vendorId) {
      await openDetail(0, currentBucket === "received" ? "billed" : currentBucket, vendorId);
    }
    const hubEl = document.getElementById("orders-hub");
    const hubVisible = hubEl && !hubEl.classList.contains("hidden");
    if (hubVisible) {
      hubExpandedVendorId = null;
      hubExpandedPlacementId = null;
      await loadList();
    }
  }
```

Do not early-return before clearing cache. After a bill, the `received` ("To bill") list must drop that vendor when no other `pending_bill` receipts remain. They already appear in `billed` via the existing billed query — do not invent a stage.

- [ ] **Step 5: Await refresh after bill; Done reloads hub**

In `submitReceipt` bill-success path, **await** the refresh (today it is fire-and-forget):

```javascript
      ctx.invalidateCache?.("/stock");
      ctx.invalidateCache?.("/vendor-orders");
      ctx.invalidateCache?.("/accounts-payable");
      if (typeof VendorOrders !== "undefined" && VendorOrders.refreshIfOpen) {
        await VendorOrders.refreshIfOpen(savedVendorId);
      }
```

Change the success-panel Done button from `App.closeDetail()` to:

```javascript
        `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail(); if(typeof VendorOrders!=='undefined'){ App.showView('buying'); VendorOrders.setBucket('received'); }">Done</button>`
```

`setBucket('received')` already calls `loadList()`. That is the To bill stage.

Do not change customer/Selling hub.

- [ ] **Step 6: Run backend tests + commit**

Run: `cd JC/backend && python3 -m pytest tests/test_ops_fix_pack.py -k "bill_receipt" -q`

Expected: PASS

```bash
git add JC/backend/tests/test_ops_fix_pack.py \
  JC/backend/app/services/vendor_receive_bill.py \
  JC/web/admin/js/stock.js \
  JC/web/admin/js/vendor-orders.js
git commit -m "$(cat <<'EOF'
Flip billed receipts off To bill and refresh the Buying list.

EOF
)"
```

Only add `vendor_receive_bill.py` if you actually changed it.

---

### Task 7: Receive Goods purchase rate

**Files:**
- Modify: `JC/backend/app/routers/stock.py:557-565`
- Modify: `JC/web/admin/js/stock.js` receive_goods step 2 (~803-850)

**Interfaces:**
- Consumes: `GET /stock/vendor-order/{id}/placed` → `PlacedLineForReceipt.buying_price` via `hide_cost`; offline picker already shows `p.buying_price`
- Produces: each against-order receive line shows that same catalog buying price (or "—" when hidden / missing). No qty-total footer. No line-amount column.

- [ ] **Step 1: None-safe placed-line price (same source as offline)**

`get_placed_order_for_receipt` currently does `format(prod.buying_price, "f")`, which throws when `buying_price` is `None` (column is nullable). Match the catalog/stock list pattern:

```python
                buying_price=hide_cost(
                    format(prod.buying_price, "f") if prod.buying_price is not None else None,
                    auth,
                ),
```

Do not read a second price field. Do not change `hide_cost`.

- [ ] **Step 2: Copy and render `buying_price` on wizard lines**

When mapping `placedOrder.lines` (~803), keep `buying_price: l.buying_price`. The Price column already exists (`fmtPrice(l.buying_price)`). If a line is still blank for admin/`costs.read`, fall back to the placed payload:

```javascript
            buying_price: l.buying_price != null && l.buying_price !== ""
              ? l.buying_price
              : null,
```

`fmtPrice` already maps `null` / `""` / `"—"` to "—". Do **not** add a tfoot qty total. Do **not** add a line-amount or receive-total column. Review step: do not add a totals footer.

- [ ] **Step 3: Manual check**

Against-order Receive Goods, admin or `costs.read`: each line shows catalog buy price, same number as offline picker for that product. Staff without `costs.read` see "—". Receive still saves without a rate.

- [ ] **Step 4: Run the full JC backend suite**

Run: `cd JC/backend && python3 -m pytest tests/ -q`

Expected: PASS (all existing tests + `test_ops_fix_pack.py`)

- [ ] **Step 5: Commit**

```bash
git add JC/backend/app/routers/stock.py JC/web/admin/js/stock.js
git commit -m "$(cat <<'EOF'
Show catalog purchase rate on against-order receive lines.

EOF
)"
```

---

## Self-review (spec coverage)

| Spec unit | Task |
|---|---|
| U1 extra collection, one payment, negative outstanding, still 400 when due `<= 0` | Task 1 + Task 3 hint |
| U2 date picker, `value_date`, daybook/`list_payments` IST day | Task 2 + Task 3 |
| U3 sell 0 / grand 0, stock moves, AR posts 0, no badge | Task 4 |
| U4 alias search + subtitle on receive/bill/hub/place-order | Task 5 |
| U5 `billed` flip, leave To bill, refresh list | Task 6 |
| U6 purchase rate, no qty footer | Task 7 |
| No Selling to-bill, no split advance, no schema migration, no freight | Global constraints / omitted files |

Placeholder scan: no TBD/TODO, no "tests for the above", no "similar to Task N". Types: `value_date: Optional[date]`, `alias: Optional[str]`, `post_payment_entry(..., value_date=)`. Hub "To bill" = `received` bucket.
