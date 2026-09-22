# Task 1 Report

## What I implemented

- Added `JC/backend/app/services/document_present.py` with:
  - `is_locked(kind, row)`
  - `freeze_card(db, kind, row)`
  - `present(db, kind, row)`
- Implemented Task 1 scope only:
  - locked snapshot read for `customer_bill`
  - live read for unlocked `customer_order`
  - lock rules for all kinds listed in the brief
- Added nullable `card_json` model columns on:
  - `CustomerBill`
  - `CustomerOrderPlacement`
  - `VendorOrderPlacement`
  - `StockReceipt`
- Added alembic revision `0bd4b909f1d2_add_document_card_json_columns.py`
- Wired `freeze_card(db, "customer_bill", bill)` into `process_customer_bill()` after bill lines exist.

## Tests and results

### TDD RED

Command:

```bash
cd /Users/sourabh/Desktop/personal/anshul/.worktrees/document-consistency/JC/backend && python3 -m pytest tests/test_document_consistency.py::test_saved_customer_bill_keeps_card_after_rename tests/test_document_consistency.py::test_open_order_follows_rename -q
```

Output:

```text
FF                                                                       [100%]
E       NameError: name 'present' is not defined
2 failed in 0.55s
```

Why expected:

- `present()` did not exist yet.
- This proved the new regression tests were actually exercising missing behavior before implementation.

### Additional RED while tightening lock rule

Command:

```bash
cd /Users/sourabh/Desktop/personal/anshul/.worktrees/document-consistency/JC/backend && python3 -m pytest tests/test_document_consistency.py::test_closed_customer_order_locks_by_parent_bucket tests/test_document_consistency.py::test_is_locked_covers_document_kinds -q
```

Output:

```text
F.                                                                       [100%]
E       AssertionError: assert False is True
1 failed, 1 passed in 0.55s
```

Why expected:

- `is_locked("customer_order", placement)` initially missed the parent order bucket check when only `CustomerOrder.bucket` changed.
- I fixed this by resolving the parent order through the SQLAlchemy session.

### GREEN

Focused command:

```bash
cd /Users/sourabh/Desktop/personal/anshul/.worktrees/document-consistency/JC/backend && python3 -m pytest tests/test_document_consistency.py -q
```

Focused output:

```text
....                                                                     [100%]
4 passed in 0.49s
```

Full-suite command:

```bash
cd /Users/sourabh/Desktop/personal/anshul/.worktrees/document-consistency/JC/backend && python3 -m pytest tests/ -q
```

Full-suite output:

```text
169 passed, 1 warning in 38.64s
```

Warning seen:

- Existing `boto3` Python 3.9 deprecation warning from `tests/test_audit_fixes_2.py`

## Files changed

- `JC/backend/app/services/document_present.py`
- `JC/backend/tests/test_document_consistency.py`
- `JC/backend/app/models/customer_bill.py`
- `JC/backend/app/models/customer_order.py`
- `JC/backend/app/models/vendor_order.py`
- `JC/backend/app/models/stock.py`
- `JC/backend/alembic/versions/0bd4b909f1d2_add_document_card_json_columns.py`
- `JC/backend/app/services/customer_bill_process.py`

## Self-review

- Scope stayed inside Task 1 only. I did not implement vendor bill freeze, ledger presentation, reports, portal, or admin UI work.
- `present()` fully covers:
  - saved `customer_bill` using frozen `card_json`
  - unlocked `customer_order` using live `CatalogProduct` data
- `display_date` uses `bill.bill_date` for customer bills and `placement.placed_at` for customer orders, as required.
- `is_locked()` covers every kind listed in the brief.
- `freeze_card()` copies product snapshot fields, add-ons, alternatives, customer snapshot fields, bill-series metadata, and freight-agent name.
- Tests assert real behavior:
  - saved bill stays frozen after catalog rename
  - open order follows live rename
  - closed order locks by parent bucket
  - all listed lock-rule kinds are covered

## Concerns

- `present()` is intentionally implemented only for the Task 1 behaviors requested: `customer_bill` and `customer_order`. Other document kinds are left for later tasks and currently raise if `present()` is called for them.

## Fix: closed customer order freeze

Updated `freeze_card()` to support `customer_order`, using the same card shape as `present()` for live customer orders, and called it from `close_bill_line()` after the closed placement line exists. Added a regression test that closes a bill line, renames the catalog product, and verifies the closed customer order card stays frozen.

Pytest command:

```bash
cd /Users/sourabh/Desktop/personal/anshul/.worktrees/document-consistency/JC/backend && python3 -m pytest tests/test_document_consistency.py -q
```

Output:

```text
.....                                                                    [100%]
5 passed in 0.44s
```

Pytest command:

```bash
cd /Users/sourabh/Desktop/personal/anshul/.worktrees/document-consistency/JC/backend && python3 -m pytest tests/ -q
```

Output:

```text
........................................................................ [ 42%]
........................................................................ [ 84%]
..........................                                               [100%]
=============================== warnings summary ===============================
tests/test_audit_fixes_2.py::test_single_bill_line_return_still_works
  /Users/sourabh/Library/Python/3.9/lib/python/site-packages/boto3/compat.py:89: PythonDeprecationWarning: Boto3 will no longer support Python 3.9 starting April 29, 2026. To continue receiving service updates, bug fixes, and security updates please upgrade to Python 3.10 or later. More information can be found here: https://aws.amazon.com/blogs/developer/python-support-policy-updates-for-aws-sdks-and-tools/
    warnings.warn(warning, PythonDeprecationWarning)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
170 passed, 1 warning in 34.34s
```

## Important review fix

Pytest command:

```bash
cd /Users/sourabh/Desktop/personal/anshul/.worktrees/document-consistency/JC/backend && python3 -m pytest tests/test_document_consistency.py -q
```

Output:

```text
.....                                                                    [100%]
5 passed in 0.57s
```

Pytest command:

```bash
cd /Users/sourabh/Desktop/personal/anshul/.worktrees/document-consistency/JC/backend && python3 -m pytest tests/test_document_consistency.py -q
```

Output:

```text
......                                                                   [100%]
6 passed in 0.46s
```

## Important review fix 2

Pytest command:

```bash
cd /Users/sourabh/Desktop/personal/anshul/.worktrees/document-consistency/JC/backend && python3 -m pytest tests/test_document_consistency.py -q
```

Output:

```text
......                                                                   [100%]
6 passed in 0.50s
```
