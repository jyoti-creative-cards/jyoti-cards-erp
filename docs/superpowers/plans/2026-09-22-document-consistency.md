# Document consistency implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every screen shows one date and one status for a document, live masters everywhere except a saved customer bill, a saved vendor bill, and a closed order, which keep the card copied at lock time.

**Architecture:** One module, `document_present.present()`, is the only reader of names, photos, prices, dates, and status. Locked documents store `card_json` at lock time. Unlocked documents (receipts, debit notes, expenses, freight, payments, returns, open orders) call the live master through the same function. Admin JS prints `present()` fields and does not format `created_at` for a document date.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, vanilla admin JS (`JC/web/admin/`), pytest sqlite in-memory.

**Spec:** `docs/superpowers/specs/2026-09-22-document-consistency-design.md`

## Global Constraints

- JC ERP only: `JC/backend/`, `JC/web/admin/`, portal routes in `JC/backend/app/routers/shop.py`. Root `backend/` is a different app. Do not edit it.
- Locked, and later master edits do not flow in: saved customer bill, saved vendor bill, closed customer order, closed customer bill, closed vendor order.
- Not locked, live masters, and a correction of the row shows everywhere: open orders, vendor goods receipts, debit notes, expenses, freight charges and settlements, customer and vendor payments, customer returns.
- Editing a receipt does not rewrite a vendor bill that is already locked.
- Business date only for document display and Today/Past: customer order `placed_at`, customer bill `bill_date`, vendor order `placed_at`, vendor receipt `received_at`, vendor bill `billed_at`, payment `value_date`, expense `expense_date`, manual loss `loss_date`. `created_at` / `updated_at` are audit clocks, not the Today tab.
- Activity log and price history keep their own event time.
- Stock on hand, outstanding, credit limit, freight balance due, shop catalog, ageing, and today's route list stay live.
- Amounts on a locked bill stay the amounts stored on that bill. Reports group by `catalog_product_id` / `customer_id` / `vendor_id` so a rename does not split one party into two rows.
- New schema is an Alembic revision. Do not add columns inside `init_db()` in `app/db/session.py`. That migrator is frozen.
- Money stays signed-ledger. Do not re-sum raw rows in the UI. Use `dues_snapshot()` / existing totals helpers.
- IST day bounds use `ist_day_bounds_utc` / `ist_range_bounds_utc`.
- Soft delete: normal lists keep `deleted_at is None`. Voided rows show only in the recycle bin, with status `voided`.

## File map

- Create: `JC/backend/app/services/document_present.py` — `is_locked`, `freeze_card`, `present`
- Create: `JC/backend/alembic/versions/<rev>_document_card_json.py` — `card_json` JSON null on locked-document tables
- Create: `JC/backend/tests/test_document_consistency.py`
- Modify: `JC/backend/app/models/customer_bill.py` — `CustomerBill.card_json`
- Modify: `JC/backend/app/models/customer_order.py` — `CustomerOrderPlacement.card_json`
- Modify: `JC/backend/app/models/vendor_order.py` — `VendorOrderPlacement.card_json`
- Modify: `JC/backend/app/models/stock.py` — `StockReceipt.card_json` (used only once `bill_status == "billed"`)
- Modify: `JC/backend/app/services/customer_bill_process.py` — freeze on bill save; do not refreeze from catalog on an unrelated master edit
- Modify: `JC/backend/app/services/vendor_receive_bill.py` — freeze on `bill_receipt`, not on `receive_vendor_goods`
- Modify: `JC/backend/app/services/customer_order_flow.py` — freeze when a placement moves to the closed bucket
- Modify: `JC/backend/app/routers/vendor_orders.py` — freeze when a vendor placement is closed
- Modify: `JC/backend/app/services/ledger.py` — bill/order rows go through `present()`
- Modify: `JC/backend/app/routers/customer_orders.py` — Today filter uses business date, not `updated_at`
- Modify: `JC/backend/app/routers/shop.py` — order history and bill PDF inputs go through `present()`
- Modify: `JC/backend/app/services/doc_gen.py` — no live `image_keys` / addon fallback for a locked document
- Modify: `JC/backend/app/services/reports.py` and `reports_extended.py` — labels via `present()`, group by id
- Modify: `JC/backend/app/routers/expenses.py` — `PATCH` to correct an expense in place
- Modify: `JC/backend/app/routers/accounts_receivable.py` and `accounts_payable.py` — `PATCH` payment in place
- Modify: `JC/web/admin/js/customer-orders.js`, `stock.js`, `finance.js`, `vendor-orders.js` — print `display_date` / `display_name` from the API
- Modify: `JC/web/admin/index.html` — bump cache-bust versions for those JS files

---

### Task 1: `present()` and the lock rule

**Files:**
- Create: `JC/backend/app/services/document_present.py`
- Create: `JC/backend/tests/test_document_consistency.py`
- Modify: `JC/backend/app/models/customer_bill.py` (add `card_json`)
- Modify: `JC/backend/app/models/stock.py` (add `StockReceipt.card_json`)
- Modify: `JC/backend/app/models/customer_order.py` (add `CustomerOrderPlacement.card_json`)
- Modify: `JC/backend/app/models/vendor_order.py` (add `VendorOrderPlacement.card_json`)
- Create: Alembic revision adding those four nullable JSON columns

**Interfaces:**
- Consumes: `CatalogProduct`, `Customer`, `Vendor`, `CustomerBill`, `StockReceipt`
- Produces:
  - `is_locked(kind: str, row) -> bool`
  - `freeze_card(db, kind: str, row) -> dict` writes `row.card_json` and returns it
  - `present(db, kind: str, row) -> dict` with keys `locked`, `display_date`, `status`, `party_name`, `lines` (each line: `catalog_product_id`, `our_product_id`, `unit_price`, `image_keys`, `addons`, `alternatives`)

- [ ] **Step 1: Write the failing test**

Create `JC/backend/tests/test_document_consistency.py`. Use the sqlite fixture pattern from `JC/backend/tests/test_stock_ledger_fixes.py` (`_setup`, `_bill_series`, `process_customer_bill`, `create_received_placement`).

```python
def test_saved_customer_bill_keeps_card_after_rename(db):
    customer, prod, _ = _setup(db)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    confirm_received_order(db, customer.id)
    bill = process_customer_bill(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines_in=[{"catalog_product_id": prod.id, "quantity_to_ship": 2}],
        overall_discount_percent=None, gst_enabled=False, gst_rate_percent=Decimal("0"),
        freight_agent_id=None, freight_charges=None, packaging_charges=None,
        additional_charges=None, bill_series_id=_bill_series(db).id, narration=None,
        actor_type="admin", actor_id=1, actor_name="Test", transport_mode="self_pickup",
    )
    db.flush()
    before = present(db, "customer_bill", bill)
    prod.our_product_id = "RENAMED"
    prod.category = "NEW-CAT"
    db.flush()
    after = present(db, "customer_bill", bill)
    assert after["locked"] is True
    assert after["lines"][0]["our_product_id"] == before["lines"][0]["our_product_id"]
    assert after["lines"][0]["our_product_id"] != "RENAMED"
    assert after["lines"][0].get("category") != "NEW-CAT"


def test_open_order_follows_rename(db):
    customer, prod, _ = _setup(db)
    placement = create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 2}],
    )
    db.flush()
    prod.our_product_id = "RENAMED"
    db.flush()
    view = present(db, "customer_order", placement)
    assert view["locked"] is False
    assert view["lines"][0]["our_product_id"] == "RENAMED"
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd JC/backend && python3 -m pytest tests/test_document_consistency.py::test_saved_customer_bill_keeps_card_after_rename tests/test_document_consistency.py::test_open_order_follows_rename -q`

Expected: FAIL, `present` is not defined.

- [ ] **Step 3: Add the columns and implement `present()`**

Alembic revision, nullable JSON, no server default required:

```python
def upgrade():
    op.add_column("jc_customer_bills", sa.Column("card_json", sa.JSON(), nullable=True))
    op.add_column("jc_customer_order_placements", sa.Column("card_json", sa.JSON(), nullable=True))
    op.add_column("jc_vendor_order_placements", sa.Column("card_json", sa.JSON(), nullable=True))
    op.add_column("jc_stock_receipts", sa.Column("card_json", sa.JSON(), nullable=True))
```

`is_locked`:

- `customer_bill`: locked once the row exists (a saved bill).
- `vendor_bill`: `StockReceipt.bill_status == "billed"`.
- `customer_order`: locked when the placement's order `bucket == "closed"` or `placement.closed_at` is set.
- `vendor_order`: locked when the placement status is `closed` or the order bucket is `closed`.
- `customer_receipt` / `debit_note` / `expense` / `payment` / `freight` / `customer_return`: always `False`.

`freeze_card` for `customer_bill` reads the current `CatalogProduct` (code, prices, `image_keys`, add-on links, alternatives), the customer (name, phone, address, city name, route name, GST, party number, markers), the bill series name and prefix, and the freight agent name. Store that dict on `bill.card_json`. Call it at the end of `process_customer_bill` in `customer_bill_process.py`, after lines exist.

`present` for a locked row with `card_json` returns that card plus current status:

```python
def _status(row) -> str:
    if getattr(row, "deleted_at", None):
        return "voided"
    if getattr(row, "cancelled_at", None):
        return "cancelled"
    if getattr(row, "closed_at", None):
        return "closed"
    return "open"
```

`display_date` for a customer bill is `bill.bill_date`, never `bill.created_at`.

`present` for an unlocked customer order joins `CatalogProduct` live for `our_product_id`, prices, images, add-ons, and alternatives. `display_date` is `placement.placed_at`.

- [ ] **Step 4: Run the tests**

Run: `cd JC/backend && python3 -m pytest tests/test_document_consistency.py -q`

Expected: the two tests PASS.

- [ ] **Step 5: Commit**

```bash
git add JC/backend/app/services/document_present.py JC/backend/app/models/customer_bill.py JC/backend/app/models/customer_order.py JC/backend/app/models/vendor_order.py JC/backend/app/models/stock.py JC/backend/alembic/versions JC/backend/tests/test_document_consistency.py JC/backend/app/services/customer_bill_process.py
git commit -m "Add present() so a saved customer bill keeps its card after a rename."
```

---

### Task 2: Vendor bill locks; goods receipt stays live

**Files:**
- Modify: `JC/backend/app/services/vendor_receive_bill.py` (`bill_receipt` calls `freeze_card`; `receive_vendor_goods` does not)
- Modify: `JC/backend/app/services/document_present.py` (`kind="vendor_receipt"` live, `kind="vendor_bill"` card)
- Test: `JC/backend/tests/test_document_consistency.py`

**Interfaces:**
- Consumes: `freeze_card`, `present` from Task 1
- Produces: a billed `StockReceipt` has `card_json`; a pending receipt does not, and `present(db, "vendor_receipt", receipt)` follows a rename

- [ ] **Step 1: Write the failing test**

```python
def test_vendor_bill_locks_and_receipt_stays_live(db):
    vendor, prod = _vendor_and_product(db)
    body = VendorReceiveCreate(
        vendor_id=vendor.id,
        lines=[VendorReceiptLineIn(catalog_product_id=prod.id, quantity_received=5)],
        order_receipt_number="R1",
    )
    receive_vendor_goods(db, AUTH, body, offline=True)
    receipt = db.query(StockReceipt).one()
    prod.our_product_id = "RENAMED"
    db.flush()
    live = present(db, "vendor_receipt", receipt)
    assert live["locked"] is False
    assert live["lines"][0]["our_product_id"] == "RENAMED"
    # bill_receipt freezes the name at bill time
    prod.our_product_id = "AT-BILL"
    db.flush()
    bill_receipt(db, AUTH, receipt.id, _min_vendor_bill(receipt))
    db.flush()
    prod.our_product_id = "AFTER"
    db.flush()
    locked = present(db, "vendor_bill", receipt)
    assert locked["locked"] is True
    assert locked["lines"][0]["our_product_id"] == "AT-BILL"
    again = present(db, "vendor_receipt", receipt)
    assert again["lines"][0]["our_product_id"] == "AFTER"
```

`_min_vendor_bill` builds a `VendorBillIn` with `total_billed_amount` equal to qty × buying price and `lines` billed qty 5. Copy the field names from `app/schemas/stock.py` `VendorBillIn`.

- [ ] **Step 2: Run it and confirm FAIL**

Run: `cd JC/backend && python3 -m pytest tests/test_document_consistency.py::test_vendor_bill_locks_and_receipt_stays_live -q`

Expected: FAIL because `bill_receipt` does not write `card_json`.

- [ ] **Step 3: Freeze only inside `bill_receipt`**

At the end of `bill_receipt`, after debit notes are created, call `freeze_card(db, "vendor_bill", receipt)`. Do not call it from `receive_vendor_goods`.

`present` for `vendor_receipt` always joins `CatalogProduct` live, even when `card_json` is set. `present` for `vendor_bill` returns `card_json` when `bill_status == "billed"`.

- [ ] **Step 4: Run the test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add JC/backend/app/services/vendor_receive_bill.py JC/backend/app/services/document_present.py JC/backend/tests/test_document_consistency.py
git commit -m "Lock the vendor bill card and keep the goods receipt live."
```

---

### Task 3: Today and Past use the business date

**Files:**
- Modify: `JC/backend/app/routers/customer_orders.py` (`list_orders`, the `day == "today"` branches around the `updated_at` / `CustomerBill.created_at` filters)
- Modify: `JC/backend/app/routers/vendor_orders.py` (the `received_at` / `updated_at` day filters — receipt day stays `received_at`; placed-order day uses `placed_at`, not `updated_at`)
- Test: `JC/backend/tests/test_document_consistency.py`

**Interfaces:**
- Consumes: `ist_day_bounds_utc` from `app/services/biz_date.py`; `present()["display_date"]`
- Produces: a placement with `placed_at` yesterday is absent from `day=today` and present in `day=all`

- [ ] **Step 1: Write the failing test**

Place an order with `placed_on=date.today() - timedelta(days=1)`. Call the same query helper the Today list uses (extract the filter into `orders_for_day(db, bucket, day)` if it is inline, and test that function).

```python
def test_backdated_order_is_not_in_today(db):
    customer, prod, _ = _setup(db)
    create_received_placement(
        db, customer_id=customer.id, customer_name=customer.business_name,
        lines=[{"catalog_product_id": prod.id, "quantity": 1}],
        placed_on=date.today() - timedelta(days=1),
    )
    db.flush()
    today_ids = orders_for_day(db, bucket="received", day="today")
    all_ids = orders_for_day(db, bucket="received", day="all")
    assert customer.id not in today_ids
    assert customer.id in all_ids
```

- [ ] **Step 2: Run it and confirm FAIL**

Expected: FAIL because Today currently filters `CustomerOrder.updated_at`, which is real now, so the backdated order is in Today.

- [ ] **Step 3: Filter on the business date**

For bucket `received`, `day=today` includes a customer only when some non-deleted placement in the received bucket has `placed_at` inside `ist_day_bounds_utc(today_ist())`. Do not use `CustomerOrder.updated_at`.

For bucket `billed`, `day=today` uses `CustomerBill.bill_date == today_ist()`, not `CustomerBill.created_at`.

Sort the list by that business date descending. The API field the admin already calls `updated_at` on hub cards must be set from the business date so the card does not print click-time. Add `display_date` on the hub row and set it to that same value. Keep `updated_at` equal to `display_date` until Task 11 removes the old read, so old JS does not show today for a backdated order.

- [ ] **Step 4: Run the test and the existing order tests**

Run: `cd JC/backend && python3 -m pytest tests/test_document_consistency.py tests/test_stock_ledger_fixes.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add JC/backend/app/routers/customer_orders.py JC/backend/app/routers/vendor_orders.py JC/backend/tests/test_document_consistency.py
git commit -m "Filter Today and Past by the business date, not the click time."
```

---

### Task 4: Party ledger and PDFs use `present()`

**Files:**
- Modify: `JC/backend/app/services/ledger.py` (`build_customer_ledger`, `build_vendor_ledger`)
- Modify: `JC/backend/app/services/doc_gen.py` (`generate_customer_bill_document`, `generate_customer_order_document`, `generate_vendor_receipt_document`)
- Test: `JC/backend/tests/test_document_consistency.py`

**Interfaces:**
- Consumes: `present(db, kind, row) -> dict`
- Produces: ledger `occurred_at` is the business date; a cancelled bill title starts with `Cancelled`; a renamed product does not change a locked bill line in the ledger or the PDF payload

- [ ] **Step 1: Write the failing test**

```python
def test_ledger_bill_uses_card_and_marks_cancelled(db):
    # save bill, rename product, cancel bill
    entries = build_customer_ledger(db, customer.id)
    bill_rows = [e for e in entries if e.event_type == "customer_bill"]
    assert len(bill_rows) == 1
    assert bill_rows[0].title.startswith("Cancelled")
    assert "RENAMED" not in bill_rows[0].summary
    assert bill_rows[0].occurred_at.date() == bill.bill_date or bill.bill_date is None
```

Use a backdated `bill_date` so the assertion is real: `occurred_at` date equals `bill_date`, not `date.today()`.

- [ ] **Step 2: Run it and confirm FAIL**

Expected: FAIL. `build_customer_ledger` uses `bill.created_at` and does not look at `cancelled_at` (`JC/backend/app/services/ledger.py` around the customer bill loop).

- [ ] **Step 3: Switch the ledger and PDF builders**

In `build_customer_ledger`, replace the bill loop's `our_product_id` / `occurred_at` / title with `view = present(db, "customer_bill", bill)`. Title is `Cancelled bill {number}` when `view["status"] == "cancelled"`, else `Bill {number}`. `occurred_at` is `view["display_date"]` as a datetime at IST noon converted to UTC if the value is a `date`. Skip rows with `status == "voided"` (`deleted_at` set). Same for vendor bills via `present(db, "vendor_bill", receipt)`.

In `doc_gen.generate_customer_bill_document`, build PDF lines from `present()` for a locked bill. Delete the fallback `ln.addons_json or addon_snapshots_for_product(...)` and the live `prod.image_keys` read on that path. Open-order PDFs use `present(db, "customer_order", placement)`, which is live.

- [ ] **Step 4: Run the test**

Expected: PASS. Also run `cd JC/backend && python3 -m pytest tests/test_stock_ledger_fixes.py::test_ledger_has_one_placed_row_after_bill -q`.

- [ ] **Step 5: Commit**

```bash
git add JC/backend/app/services/ledger.py JC/backend/app/services/doc_gen.py JC/backend/tests/test_document_consistency.py
git commit -m "Party ledger and PDFs read present(), including cancelled bills."
```

---

### Task 5: Debit notes, expenses, freight, and payments stay live

**Files:**
- Modify: `JC/backend/app/services/document_present.py`
- Modify: `JC/backend/app/services/ledger.py` (debit note and payment rows)
- Modify: `JC/backend/app/services/ap_ledger.py` `build_ap_ledger`
- Modify: `JC/backend/app/services/ar_ledger.py` `build_ar_ledger`
- Test: `JC/backend/tests/test_document_consistency.py`

**Interfaces:**
- Consumes: `present` unlocked kinds
- Produces: after a product rename, `present(db, "debit_note", note)["lines"][0]["our_product_id"]` is the new name; a locked vendor bill that includes that note's receipt still shows the old card

- [ ] **Step 1: Write the failing test**

Create a debit note on a pending receipt (`create_debit_note`), rename the product, assert `present(db, "debit_note", note)` shows the new code. Then bill the receipt, rename again, assert the vendor bill card does not change and the debit note still shows the newest name.

- [ ] **Step 2: Run it and confirm FAIL**

- [ ] **Step 3: Implement live `present` for those kinds**

`debit_note`: join `CatalogProduct` for item notes. `display_date` is the parent receipt's `billed_at` when the note was created with a bill, else `note.created_at`.

`expense`: `display_date` is `expense_date`. Party label for a freight agent or add-on is the live `FreightAgent.name` / `AddonProduct.our_product_id`.

`freight`: live agent name. Date is the linked bill's `bill_date` when `customer_bill_id` is set, else the entry's business date column from Task 6.

`payment`: live customer or vendor name. `display_date` is `value_date`.

Do not copy these into `card_json`.

- [ ] **Step 4: Run the test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add JC/backend/app/services/document_present.py JC/backend/app/services/ledger.py JC/backend/app/services/ap_ledger.py JC/backend/app/services/ar_ledger.py JC/backend/tests/test_document_consistency.py
git commit -m "Debit notes, expenses, freight, and payments follow the live master."
```

---

### Task 6: Correct a payment or an expense in place

**Files:**
- Modify: `JC/backend/app/routers/expenses.py`
- Modify: `JC/backend/app/routers/accounts_receivable.py`
- Modify: `JC/backend/app/routers/accounts_payable.py`
- Modify: `JC/backend/app/schemas/accounts_receivable.py` and `accounts_payable.py` and the expense schema
- Test: `JC/backend/tests/test_document_consistency.py`

**Interfaces:**
- Consumes: `ArLedgerEntry` / `ApLedgerEntry` payment rows; `Expense`
- Produces:
  - `PATCH /expenses/{id}` body `{expense_date, category, description, amount, reference}` updates that row
  - `PATCH /accounts-receivable/payments/{entry_id}` and `PATCH /accounts-payable/payments/{entry_id}` body `{amount, value_date, payment_mode, description}` updates that payment row's `amount` via `as_signed_decrease` and does not insert a second row

- [ ] **Step 1: Write the failing test**

```python
def test_payment_edit_replaces_amount_in_place(db):
    # post a 100 payment, then patch to 40
    rows = db.query(ArLedgerEntry).filter(ArLedgerEntry.entry_type == "payment").all()
    assert len(rows) == 1
    assert mag(rows[0].amount) == Decimal("40.00")
```

Same shape for an expense: one row, amount changed, `expense_date` changed.

- [ ] **Step 2: Run it and confirm FAIL**

Expected: FAIL, route missing (404 / no attribute).

- [ ] **Step 3: Add the PATCH handlers**

Reject the patch when `entry_type != "payment"` or the row has `deleted_at`. Do not call `post_payment_entry`. Assign the new signed amount on the existing row. Outstanding is the sum of active rows, so it follows the edit with no extra code.

Expense PATCH loads `Expense` by id and assigns the body fields. It does not insert.

- [ ] **Step 4: Run the test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add JC/backend/app/routers/expenses.py JC/backend/app/routers/accounts_receivable.py JC/backend/app/routers/accounts_payable.py JC/backend/app/schemas/accounts_receivable.py JC/backend/app/schemas/accounts_payable.py JC/backend/tests/test_document_consistency.py
git commit -m "Correct a payment or an expense by editing that same row."
```

Wire the admin buttons in Task 11. This task is the API.

---

### Task 7: Reports and search

**Files:**
- Modify: `JC/backend/app/services/reports_extended.py` (item aggregation, GST, revenue lines)
- Modify: `JC/backend/app/services/reports.py` (daybook labels)
- Modify: the customer and vendor order list search in `JC/backend/app/routers/customer_orders.py` and `vendor_orders.py`
- Test: `JC/backend/tests/test_document_consistency.py`

**Interfaces:**
- Consumes: `present`
- Produces: sales-by-item returns one bucket per `catalog_product_id` after a rename; the locked bill line label is the card name; the receipt line label is the live name

- [ ] **Step 1: Write the failing test**

Save a customer bill for product P, rename P to RENAMED, receive more of P. Item report groups: one group, id = `prod.id`. The bill line label is the pre-rename code. The receipt line label is `RENAMED`.

- [ ] **Step 2: Run it and confirm FAIL**

- [ ] **Step 3: Group by id and label via `present()`**

Where a report row is built from `CustomerBillLine.our_product_id` or `StockReceiptLine.our_product_id`, replace the label with `present(...)["lines"]`. The group key stays `catalog_product_id`.

Search for a customer order matches live `CatalogProduct.our_product_id` for unlocked placements and `card_json` line names for locked ones. Also match `catalog_product_id` so the new name still finds a locked bill.

- [ ] **Step 4: Run the test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add JC/backend/app/services/reports.py JC/backend/app/services/reports_extended.py JC/backend/app/routers/customer_orders.py JC/backend/app/routers/vendor_orders.py JC/backend/tests/test_document_consistency.py
git commit -m "Reports and search use present() and do not split a renamed product."
```

---

### Task 8: Customer portal

**Files:**
- Modify: `JC/backend/app/routers/shop.py` `list_order_history` (the loop that sets `image_url=_image_url(prod)` and `category=prod.category`)
- Test: `JC/backend/tests/test_document_consistency.py`

**Interfaces:**
- Consumes: `present(db, "customer_order", placement)` and `present(db, "customer_bill", bill)`
- Produces: a billed history line uses the bill card's photo and name; an open placement uses the live catalog; `product_search` is unchanged

- [ ] **Step 1: Write the failing test**

Bill a line, rename the product, change `image_keys` to `["new-key"]`. History line for that billed qty keeps the old code and does not use `new-key`. An unbilled placement for the same product uses `RENAMED` and `new-key`.

- [ ] **Step 2: Run it and confirm FAIL**

Expected: FAIL. `list_order_history` currently sets `image_url` from the live product (`shop.py` around line 661).

- [ ] **Step 3: Read images and names from `present()`**

For each history line, if a bill exists, use `present(db, "customer_bill", bill)`. Otherwise use `present(db, "customer_order", placement)`. Do not call `_image_url(prod)` for a locked bill.

Leave `product_search` / `product_suggestions` on the live catalog.

- [ ] **Step 4: Run the test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add JC/backend/app/routers/shop.py JC/backend/tests/test_document_consistency.py
git commit -m "Portal history uses the locked bill card and live data for open orders."
```

---

### Task 9: Cache

**Files:**
- Modify: catalog, customer, and vendor update handlers that already call `record_entity_history` — also call `response_cache.invalidate` for `catalog:`, `stock:`, `shop:`, and the open-order list prefixes those routers already use
- Modify: `JC/web/admin/js/catalog.js`, `vendors.js`, and the customer save path in `app.js` — `ctx.invalidateCache?.("/customer-orders")`, `"/stock"`, `"/catalog"`, `"/vendor-orders"` after a master save
- Test: a unit test that a catalog rename calls `response_cache.invalidate` with those prefixes (mock `response_cache`)

- [ ] **Step 1: Write the failing test**

Patch `response_cache.invalidate` and save a catalog product rename through the service the router uses. Assert `"catalog:"`, `"stock:"`, and `"shop:"` were invalidated.

- [ ] **Step 2: Run it and confirm FAIL**

- [ ] **Step 3: Invalidate on master save**

Do not cache `present()` for locked bills across a bill edit. Bill save already invalidates stock in `customer_orders.py`. Add the same invalidation on vendor bill save and on the new payment and expense PATCH routes (`ledger` prefixes the finance screens use).

- [ ] **Step 4: Run the test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add JC/backend/app/routers/catalog.py JC/backend/app/services/customer_bill_process.py JC/backend/app/services/vendor_receive_bill.py JC/web/admin/js/catalog.js JC/web/admin/js/vendors.js JC/web/admin/app.js JC/backend/tests/test_document_consistency.py
git commit -m "Drop open-document caches when a master or a corrected row changes."
```

The catalog router path may be a service call rather than the router itself. Invalidate in the function that already writes `EntityHistory` for `catalog_product`, so every rename hits it once.

---

### Task 10: Backfill locked cards

**Files:**
- Create: `JC/backend/app/services/document_card_backfill.py`
- Modify: the Alembic revision from Task 1, or a second revision that runs the backfill in `upgrade()` after the columns exist
- Test: `JC/backend/tests/test_document_consistency.py`

**Interfaces:**
- Consumes: `freeze_card`, `EntityHistory`
- Produces: `backfill_locked_cards(db) -> int` sets `card_json` on saved bills and closed placements that have none

- [ ] **Step 1: Write the failing test**

Insert a `CustomerBill` and lines without `card_json` (set the column null after `process_customer_bill`, or insert directly). Rename the product. Call `backfill_locked_cards`. `present()` still shows the pre-rename code, because backfill must prefer line columns and history over the catalog as it is now.

Backfill order, matching the spec:

1. Line `our_product_id` and `unit_price` already on the bill line win over the live catalog.
2. `EntityHistory` for that product with `valid_from <= bill business date` and (`valid_to` is null or `valid_to > bill date`) fills image and add-on fields the line does not store.
3. If history has nothing, copy the current live image once, then never join live again.

- [ ] **Step 2: Run it and confirm FAIL**

- [ ] **Step 3: Implement `backfill_locked_cards`**

Walk `CustomerBill` where `card_json is None` and `deleted_at is None`, `StockReceipt` where `bill_status == "billed"` and `card_json is None`, and placements whose bucket is `closed` and `card_json is None`. Build the card with the precedence above. Do not walk debit notes, receipts that are still `pending_bill`, expenses, or payments.

- [ ] **Step 4: Run the test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add JC/backend/app/services/document_card_backfill.py JC/backend/alembic/versions JC/backend/tests/test_document_consistency.py
git commit -m "Backfill cards for bills and closed orders already in the database."
```

---

### Task 11: Admin screens print `present()` fields

**Files:**
- Modify: `JC/web/admin/js/customer-orders.js` (hub meta and bill rows that use `b.created_at` / `p.placed_at` — print `display_date`)
- Modify: `JC/web/admin/js/stock.js` and `vendor-orders.js` (receipt and bill labels use `display_name` from the API)
- Modify: `JC/web/admin/js/finance.js` (payment and expense rows use `display_date`; add Edit that calls the Task 6 PATCH)
- Modify: `JC/web/admin/index.html` cache-bust query on those scripts
- The list endpoints must already return `display_date`, `display_name`, and `status` from `present()` before this task. If a list DTO is missing them, add the fields in the router in this task and cover it with one API test.

**Interfaces:**
- Consumes: hub and ledger JSON `display_date`, `display_name`, `status`
- Produces: the Selling hub does not call `new Date(p.placed_at)` or `ctx.fmtDate(b.created_at)` for the document date

- [ ] **Step 1: Find the date prints**

```bash
cd JC/web/admin && rg -n "fmtDate\\(b\\.created_at\\)|fmtDate\\(.*updated_at|new Date\\(p\\.placed_at\\)" js/customer-orders.js js/stock.js js/finance.js js/vendor-orders.js
```

- [ ] **Step 2: Replace each document date with `display_date`**

Leave activity-log tables on `created_at`. Those are edit events, not documents.

Expense and payment detail get an Edit button that PATCHes the same id and then reloads the ledger. Disable it while the request is in flight (`saveBusy`), same pattern as `debit-notes.js` `saveBusy`.

- [ ] **Step 3: Bump cache-bust versions in `index.html`**

- [ ] **Step 4: Syntax-check the JS**

Brace counts must match. Run the full backend suite:

`cd JC/backend && python3 -m pytest tests/ -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add JC/web/admin/js/customer-orders.js JC/web/admin/js/stock.js JC/web/admin/js/finance.js JC/web/admin/js/vendor-orders.js JC/web/admin/index.html
git commit -m "Admin screens show the present() date and name, and can correct a payment or expense."
```

---

## Spec coverage

| Spec section | Task |
|---|---|
| Locked customer bill, vendor bill, closed orders | 1, 2, 10 |
| Receipt, debit note, expense, freight, payment stay live | 2, 5 |
| Receipt edit does not rewrite a locked vendor bill | 2 (`present` split); receipt edit already writes the receipt row in `receipt_edit.py` and must not call `freeze_card` again unless the user is editing the bill itself |
| Business date Today/Past | 3 |
| Ledger cancelled status and PDF card | 4 |
| Payment and expense correction in place | 6 |
| Reports and search | 7 |
| Portal | 8 |
| Cache | 9 |
| Backfill | 10 |
| Admin UI | 11 |
| Category lookup rename updates live products only | Task 5's live join plus the existing catalog save; locked card ignores it. Add one assertion to the Task 1 rename test that `prod.category` change does not change `card_json`. |
| Activity log and price history keep event time | No task changes those tables. Task 11 leaves their `created_at` prints alone. |

## Self-review notes

- `freeze_card` / `present` / `is_locked` names are the same in every task.
- Vendor receipt stays live after the bill locks. That is the spec, not an accident.
- Schema is Alembic, not `init_db()`.
- Task 6 does not insert a second payment row.
