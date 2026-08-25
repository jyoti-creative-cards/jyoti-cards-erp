# Vendor Billing Model Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace vendor `billing_context` JSON with typed columns; simplify vendor receive→bill to one-receipt-per-bill; auto-suggest debit notes for qty and amount deviation; post 1 or 2 AP entries depending on vendor's billing %.

**Architecture:** A new pure module `vendor_billing_math.py` owns all money formulas (billing %, discount, GST, additional charge, split-billing extra cash, and the two deviation-debit-note calculators) so both `receive` and `bill` call the same tested code. `StockReceipt` becomes a single row per shipment that transitions `pending_bill → billed` in place (no more separate `vendor_bill`-type rows, no more shadow `VendorOrder` "received"/"billed" bucket rows). Frontend keeps the existing wizard shape but the bill step now always shows an editable total and reads receipt-scoped lines instead of vendor-wide aggregation.

**Tech Stack:** FastAPI, SQLAlchemy, Postgres (boot migrations in `app/db/session.py`), vanilla admin JS, pytest.

Spec: `docs/superpowers/specs/2026-08-25-vendor-billing-redesign-design.md`

## Global Constraints

- `billing_pct` 50 or 100 (VEE PEE=50, all others=100 unless later changed by admin)
- Formula: `on_paper = actual_value × billing_pct/100`; `after_discount = on_paper × (1 − discount_pct/100)`; `base = after_discount + additional_charge`; `gst = base × gst_rate_pct/100` (if `gst_included`); `bill_total = base + gst`; `extra_cash = actual_value × (1 − billing_pct/100)` — only posted/shown when `billing_pct < 100`
- GARG keeps 18% GST (confirmed in chat)
- Stock is never touched by billing-time quantity deviations — only by the original receive action. Auto qty-deviation debit notes are always `note_type='value'`, never `'item'`
- One `StockReceipt` row per shipment, transitioning `bill_status`: `pending_bill` → `billed`. No aggregation of multiple receipts into one bill.
- `expected_bill_amount`/`expected_extra_cash` are frozen at receive time using the vendor's billing columns *at that moment*; never recomputed retroactively if vendor settings change later
- "Total bill amount" in the bill wizard is always a plain editable number input — no admin-lock behavior
- Real data (84 `vendor_receive` receipts) must survive migration with stock untouched; only test/demo bills + junk vendors are deleted
- Do not commit unless the user asks

## File map

- Create: `JC/backend/app/services/vendor_billing_math.py`
- Create: `JC/backend/tests/test_vendor_billing_math.py`
- Create: `JC/backend/scripts/cleanup_vendor_billing_test_data.py`
- Modify: `JC/backend/app/models/vendor.py`
- Modify: `JC/backend/app/models/stock.py`
- Modify: `JC/backend/app/models/debit_note.py`
- Modify: `JC/backend/app/db/session.py`
- Modify: `JC/backend/app/schemas/vendor.py`
- Modify: `JC/backend/app/schemas/stock.py`
- Modify: `JC/backend/app/schemas/debit_note.py`
- Modify: `JC/backend/app/routers/vendors.py`
- Modify: `JC/backend/app/routers/stock.py`
- Modify: `JC/backend/app/routers/vendor_orders.py`
- Modify: `JC/backend/app/services/vendor_receive_bill.py`
- Modify: `JC/backend/app/services/debit_notes.py`
- Modify: `JC/backend/app/services/receipt_edit.py`
- Modify: `JC/backend/app/services/ledger.py`
- Modify: `JC/web/admin/js/vendors.js`
- Modify: `JC/web/admin/js/stock.js`
- Modify: `JC/web/admin/js/vendor-orders.js`

---

### Task 1: Vendor billing columns (model, migration, schema, API, admin form)

**Files:**
- Modify: `JC/backend/app/models/vendor.py`
- Modify: `JC/backend/app/db/session.py`
- Modify: `JC/backend/app/schemas/vendor.py`
- Modify: `JC/backend/app/routers/vendors.py`
- Modify: `JC/web/admin/js/vendors.js`

**Interfaces:**
- Produces: `Vendor.billing_pct/additional_charge/additional_charge_label/discount_pct/gst_included/gst_rate_pct/billing_notes` columns
- Produces: `VendorBillingTerms` pydantic schema (replaces `VendorBillingContext`)
- Produces: `GET/PATCH /vendors/{id}/billing-terms`
- Consumes: nothing new (self-contained)

Steps:

- [ ] **Step 1:** Add 7 columns to `Vendor` model in `app/models/vendor.py` (after `billing_context`, keep `billing_context` untouched):
  ```python
  billing_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("100"), server_default="100")
  additional_charge: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("100"), server_default="100")
  additional_charge_label: Mapped[str] = mapped_column(String(50), nullable=False, default="Additional charge", server_default="Additional charge")
  discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"), server_default="0")
  gst_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sql_true())
  gst_rate_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("18"), server_default="18")
  billing_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
  ```
  Add `Decimal` and `Numeric` to the existing imports at the top of the file.

- [ ] **Step 2:** Add `_migrate_vendor_billing_terms()` to `app/db/session.py`, following the exact pattern of `_migrate_bill_transport()` (idempotent `ADD COLUMN IF NOT EXISTS`, one `try/except` per statement, `_is_sqlite` strip for the `IF NOT EXISTS` clause), then seed the 3 known vendors by name and set defaults everywhere else:
  ```python
  def _migrate_vendor_billing_terms() -> None:
      """Typed billing columns replacing billing_context JSON."""
      stmts = [
          "ALTER TABLE jc_vendors ADD COLUMN IF NOT EXISTS billing_pct NUMERIC(5,2) NOT NULL DEFAULT 100",
          "ALTER TABLE jc_vendors ADD COLUMN IF NOT EXISTS additional_charge NUMERIC(10,2) NOT NULL DEFAULT 100",
          "ALTER TABLE jc_vendors ADD COLUMN IF NOT EXISTS additional_charge_label VARCHAR(50) NOT NULL DEFAULT 'Additional charge'",
          "ALTER TABLE jc_vendors ADD COLUMN IF NOT EXISTS discount_pct NUMERIC(5,2) NOT NULL DEFAULT 0",
          "ALTER TABLE jc_vendors ADD COLUMN IF NOT EXISTS gst_included BOOLEAN NOT NULL DEFAULT TRUE",
          "ALTER TABLE jc_vendors ADD COLUMN IF NOT EXISTS gst_rate_pct NUMERIC(5,2) NOT NULL DEFAULT 18",
          "ALTER TABLE jc_vendors ADD COLUMN IF NOT EXISTS billing_notes TEXT",
          "UPDATE jc_vendors SET billing_pct = 50, additional_charge = 100, additional_charge_label = 'Packing charges', discount_pct = 0, gst_included = TRUE, gst_rate_pct = 18 WHERE business_name = 'VEE PEE CREATIONS'",
          "UPDATE jc_vendors SET billing_pct = 100, additional_charge = 0, additional_charge_label = 'Additional charge', discount_pct = 0, gst_included = TRUE, gst_rate_pct = 18 WHERE business_name = 'SINGHAL PRINT & GRAPHICS'",
          "UPDATE jc_vendors SET billing_pct = 100, additional_charge = 100, additional_charge_label = 'Freight charges', discount_pct = 6, gst_included = TRUE, gst_rate_pct = 18 WHERE business_name = 'GARG ENTERPRISES'",
      ]
      for stmt in stmts:
          try:
              with engine.begin() as conn:
                  s = stmt.replace(" ADD COLUMN IF NOT EXISTS ", " ADD COLUMN ") if _is_sqlite else stmt
                  conn.execute(text(s))
          except Exception:
              log.warning("Migration step skipped", exc_info=True)
  ```
  Register the call in the `init_db()` sequence right after `_migrate_bill_transport()`.

- [ ] **Step 3:** In `app/schemas/vendor.py`, replace `VendorBillingContext` with:
  ```python
  class VendorBillingTerms(BaseModel):
      billing_pct: float = Field(100.0, gt=0, le=100)
      additional_charge: float = Field(100.0, ge=0)
      additional_charge_label: str = Field("Additional charge", max_length=50)
      discount_pct: float = Field(0.0, ge=0, le=100)
      gst_included: bool = True
      gst_rate_pct: float = Field(18.0, ge=0, le=100)
      billing_notes: Optional[str] = None
  ```
  In `VendorPublic`, replace `billing_context: Optional[VendorBillingContext] = None` with `billing_terms: VendorBillingTerms`.

- [ ] **Step 4:** In `app/routers/vendors.py`:
  - In `_to_public()`, replace the `billing_context=...` line with:
    ```python
    billing_terms=VendorBillingTerms(
        billing_pct=float(row.billing_pct), additional_charge=float(row.additional_charge),
        additional_charge_label=row.additional_charge_label, discount_pct=float(row.discount_pct),
        gst_included=row.gst_included, gst_rate_pct=float(row.gst_rate_pct), billing_notes=row.billing_notes,
    ),
    ```
    Also add `billing_terms=...` (same construction) to the `list_vendors` per-row `VendorPublic(...)` block so the list view carries it too.
  - Replace the `GET/PATCH /vendors/{vendor_id}/billing-context` routes with `GET/PATCH /vendors/{vendor_id}/billing-terms`: `GET` returns `_to_public(row, db).billing_terms`; `PATCH` keeps the existing `if not auth.is_admin: raise 403` guard, then sets each of the 7 columns from `body: VendorBillingTerms` directly onto `row` (no JSON blob), commits, returns the updated `VendorBillingTerms`.

- [ ] **Step 5:** In `JC/web/admin/js/vendors.js`, find the vendor create/edit form section that currently renders/edits the JSON "Billing terms (admin only)" block (search for `billing_context` or `billing-context` in the file) and replace it with 7 plain labeled inputs bound to `billing_pct`, `additional_charge`, `additional_charge_label`, `discount_pct`, `gst_included` (checkbox), `gst_rate_pct`, `billing_notes` (textarea). Keep the existing admin-only gating. On save, call `PATCH /vendors/{id}/billing-terms` with the flat object instead of the old nested shape. Update any other reads of `vendor.billing_context` in this file to `vendor.billing_terms`.

- [ ] **Step 6:** Manually verify: start the backend locally, `GET /vendors/2` (SINGHAL) and confirm `billing_terms.billing_pct == 100`, `GET /vendors/5` (VEE PEE) confirm `billing_pct == 50`, `additional_charge_label == "Packing charges"`.

---

### Task 2: Pure billing math module (TDD)

**Files:**
- Create: `JC/backend/app/services/vendor_billing_math.py`
- Create: `JC/backend/tests/test_vendor_billing_math.py`

**Interfaces:**
- Consumes: nothing (pure `Decimal` math, no DB/ORM)
- Produces:
  - `compute_bill_totals(*, total_actual_value: Decimal, billing_pct: Decimal, additional_charge: Decimal, discount_pct: Decimal, gst_included: bool, gst_rate_pct: Decimal) -> tuple[Decimal, Decimal]` → `(bill_total, extra_cash)`
  - `qty_deviation_debit_note(*, billed_qty: int, received_qty: int, buying_price: Decimal, billing_pct: Decimal) -> Optional[dict]` → `{"direction": "over"|"under", "amount": Decimal}` or `None`
  - `amount_deviation_debit_note(*, expected_bill_total: Decimal, entered_bill_total: Decimal) -> Optional[dict]` → same shape or `None`

- [ ] **Step 1: Write failing tests** in `tests/test_vendor_billing_math.py`:
  ```python
  from decimal import Decimal
  from app.services.vendor_billing_math import (
      compute_bill_totals, qty_deviation_debit_note, amount_deviation_debit_note,
  )

  def test_100pct_no_discount_with_gst():
      # Singhal-style: 100 units @ 10 = 1000 actual value, 0 discount, 0 charge, 18% gst
      bill_total, extra_cash = compute_bill_totals(
          total_actual_value=Decimal("1000"), billing_pct=Decimal("100"),
          additional_charge=Decimal("0"), discount_pct=Decimal("0"),
          gst_included=True, gst_rate_pct=Decimal("18"),
      )
      assert bill_total == Decimal("1180.00")
      assert extra_cash == Decimal("0.00")

  def test_garg_discount_charge_gst():
      # 1000 actual value, 6% discount, +100 charge, 18% gst
      bill_total, extra_cash = compute_bill_totals(
          total_actual_value=Decimal("1000"), billing_pct=Decimal("100"),
          additional_charge=Decimal("100"), discount_pct=Decimal("6"),
          gst_included=True, gst_rate_pct=Decimal("18"),
      )
      # after_discount = 940, base = 1040, gst = 187.20, total = 1227.20
      assert bill_total == Decimal("1227.20")
      assert extra_cash == Decimal("0.00")

  def test_veepee_half_billing_with_packing_and_extra_cash():
      # 100 units @ 10 = 1000 actual value, 50% billing, +100 packing, 18% gst, no discount
      bill_total, extra_cash = compute_bill_totals(
          total_actual_value=Decimal("1000"), billing_pct=Decimal("50"),
          additional_charge=Decimal("100"), discount_pct=Decimal("0"),
          gst_included=True, gst_rate_pct=Decimal("18"),
      )
      # on_paper = 500, base = 600, gst = 108, bill_total = 708; extra_cash = 500
      assert bill_total == Decimal("708.00")
      assert extra_cash == Decimal("500.00")

  def test_qty_deviation_billed_more_than_received_is_over():
      dn = qty_deviation_debit_note(
          billed_qty=110, received_qty=100, buying_price=Decimal("10"), billing_pct=Decimal("100"),
      )
      assert dn == {"direction": "over", "amount": Decimal("-100.00")}

  def test_qty_deviation_received_more_than_billed_is_under():
      dn = qty_deviation_debit_note(
          billed_qty=90, received_qty=100, buying_price=Decimal("10"), billing_pct=Decimal("100"),
      )
      assert dn == {"direction": "under", "amount": Decimal("100.00")}

  def test_qty_deviation_none_when_equal():
      assert qty_deviation_debit_note(
          billed_qty=100, received_qty=100, buying_price=Decimal("10"), billing_pct=Decimal("100"),
      ) is None

  def test_qty_deviation_applies_billing_pct():
      # VEE PEE: 10 unit gap at 50% billing → only half the value is disputed
      dn = qty_deviation_debit_note(
          billed_qty=110, received_qty=100, buying_price=Decimal("10"), billing_pct=Decimal("50"),
      )
      assert dn == {"direction": "over", "amount": Decimal("-50.00")}

  def test_amount_deviation_entered_more_than_expected_is_over():
      dn = amount_deviation_debit_note(
          expected_bill_total=Decimal("1180.00"), entered_bill_total=Decimal("1200.00"),
      )
      assert dn == {"direction": "over", "amount": Decimal("-20.00")}

  def test_amount_deviation_none_when_equal():
      assert amount_deviation_debit_note(
          expected_bill_total=Decimal("1180.00"), entered_bill_total=Decimal("1180.00"),
      ) is None
  ```

- [ ] **Step 2: Run tests, confirm FAIL** with `ModuleNotFoundError`:
  `cd JC/backend && python -m pytest tests/test_vendor_billing_math.py -v`

- [ ] **Step 3: Implement** `app/services/vendor_billing_math.py`:
  ```python
  from __future__ import annotations

  from decimal import Decimal
  from typing import Optional

  _CENTS = Decimal("0.01")
  _HUNDRED = Decimal("100")


  def compute_bill_totals(
      *,
      total_actual_value: Decimal,
      billing_pct: Decimal,
      additional_charge: Decimal,
      discount_pct: Decimal,
      gst_included: bool,
      gst_rate_pct: Decimal,
  ) -> tuple[Decimal, Decimal]:
      """Returns (bill_total, extra_cash) per the vendor billing formula.

      bill_total is the paper-invoice amount (Entry 1 in AP).
      extra_cash is the untaxed remainder for split-billing vendors (0 when billing_pct == 100).
      """
      on_paper = (total_actual_value * billing_pct / _HUNDRED).quantize(_CENTS)
      after_discount = (on_paper * (_HUNDRED - discount_pct) / _HUNDRED).quantize(_CENTS)
      base = after_discount + additional_charge
      gst_amount = (base * gst_rate_pct / _HUNDRED).quantize(_CENTS) if gst_included else Decimal("0.00")
      bill_total = (base + gst_amount).quantize(_CENTS)
      extra_cash = (total_actual_value * (_HUNDRED - billing_pct) / _HUNDRED).quantize(_CENTS)
      return bill_total, extra_cash


  def qty_deviation_debit_note(
      *, billed_qty: int, received_qty: int, buying_price: Decimal, billing_pct: Decimal,
  ) -> Optional[dict]:
      """Value-type debit note for a line's billed-vs-received mismatch, scaled by billing_pct.

      billed > received → vendor's paper claims more than physically arrived → 'over' → reduces payable.
      received > billed → vendor billed less than arrived → 'under' → increases payable.
      """
      diff = billed_qty - received_qty
      if diff == 0:
          return None
      amount_abs = (abs(Decimal(diff)) * buying_price * billing_pct / _HUNDRED).quantize(_CENTS)
      direction = "over" if diff > 0 else "under"
      amount = -amount_abs if direction == "over" else amount_abs
      return {"direction": direction, "amount": amount}


  def amount_deviation_debit_note(
      *, expected_bill_total: Decimal, entered_bill_total: Decimal,
  ) -> Optional[dict]:
      """Value-type debit note for the whole-bill total vs the rule-calculated expectation."""
      diff = (entered_bill_total - expected_bill_total).quantize(_CENTS)
      if diff == 0:
          return None
      direction = "over" if diff > 0 else "under"
      amount = -abs(diff) if direction == "over" else abs(diff)
      return {"direction": direction, "amount": amount}
  ```

- [ ] **Step 4: Run tests, confirm PASS**:
  `cd JC/backend && python -m pytest tests/test_vendor_billing_math.py -v`

---

### Task 3: StockReceipt + DebitNote schema additions

**Files:**
- Modify: `JC/backend/app/models/stock.py`
- Modify: `JC/backend/app/models/debit_note.py`
- Modify: `JC/backend/app/db/session.py`

**Interfaces:**
- Produces: `StockReceipt.bill_status` (`pending_bill`|`billed`), `expected_bill_amount`, `expected_extra_cash`, `billed_at`; `DebitNote.source` (`auto`|`manual`)

- [ ] **Step 1:** In `app/models/stock.py`, add to `StockReceipt` (after `actual_ap_amount`):
  ```python
  bill_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_bill", server_default="pending_bill", index=True)
  expected_bill_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
  expected_extra_cash: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
  billed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
  ```

- [ ] **Step 2:** In `app/models/debit_note.py`, add:
  ```python
  source: Mapped[str] = mapped_column(String(10), nullable=False, default="manual", server_default="manual")
  ```

- [ ] **Step 3:** In `app/db/session.py`, add `_migrate_vendor_billing_v2()`:
  ```python
  def _migrate_vendor_billing_v2() -> None:
      """One-receipt-per-bill: bill_status + frozen expected amounts + debit note source."""
      stmts = [
          "ALTER TABLE jc_stock_receipts ADD COLUMN IF NOT EXISTS bill_status VARCHAR(20) NOT NULL DEFAULT 'pending_bill'",
          "ALTER TABLE jc_stock_receipts ADD COLUMN IF NOT EXISTS expected_bill_amount NUMERIC(14,2)",
          "ALTER TABLE jc_stock_receipts ADD COLUMN IF NOT EXISTS expected_extra_cash NUMERIC(14,2)",
          "ALTER TABLE jc_stock_receipts ADD COLUMN IF NOT EXISTS billed_at TIMESTAMPTZ",
          "ALTER TABLE jc_debit_notes ADD COLUMN IF NOT EXISTS source VARCHAR(10) NOT NULL DEFAULT 'manual'",
          "UPDATE jc_stock_receipts SET bill_status = 'billed', billed_at = received_at WHERE receipt_type = 'vendor_bill'",
      ]
      for stmt in stmts:
          try:
              with engine.begin() as conn:
                  s = stmt.replace(" ADD COLUMN IF NOT EXISTS ", " ADD COLUMN ") if _is_sqlite else stmt
                  conn.execute(text(s))
          except Exception:
              log.warning("Migration step skipped", exc_info=True)
  ```
  Register right after `_migrate_vendor_billing_terms()`.

  Note: there is deliberately no `UPDATE ... SET bill_status = 'pending_bill' WHERE receipt_type = 'vendor_receive'` statement — the column's `DEFAULT 'pending_bill'` already gives every existing `vendor_receive` row the correct value the moment the column is added, and this migration re-runs on every app boot. An explicit unconditional `UPDATE` here would re-fire on every boot and stomp the `bill_status` of receipts that Task 5's `bill_receipt()` has since legitimately flipped to `'billed'` (since `receipt_type` stays `'vendor_receive'` for a batch's entire lifecycle in this design — that value never changes to signal "this one is now billed"). The `vendor_bill` backfill statement is safe to leave unconditional: `receipt_type = 'vendor_bill'` only ever matches the old pre-redesign rows (which Task 4 deletes anyway), never a row created by the new flow, so repeating it is a harmless no-op.

- [ ] **Step 4:** Manually verify column presence: `\d jc_stock_receipts` and `\d jc_debit_notes` via psql, or re-run the earlier psycopg2 introspection pattern used in this chat.

---

### Task 4: Data cleanup script (test bills, test debit note, junk vendors)

**Files:**
- Create: `JC/backend/scripts/cleanup_vendor_billing_test_data.py`

**Interfaces:**
- Consumes: nothing (standalone script reading `DATABASE_URL` from `.env` like other one-off scripts in this repo)
- Produces: none (data-only side effects)

**Corrected scope (superseding an earlier undercount):** the original design check only looked for `vendor_bill`-type rows and missed that each of the 3 junk-vendor test bills also has a paired `vendor_receive` row created alongside it under the pre-redesign flow (same vendor, created back-to-back). Verified against the live DB on 2026-08-25: `test vendor` has 2 receipts (`id=81` vendor_receive `order_receipt_number='1234'`, `id=82` vendor_bill `bill_number='1234'` ₹1000), `delete ven` has 4 (`id=18` receive `'658'` / `id=19` bill `'886'` ₹8000, `id=20` receive `'786'` / `id=21` bill `'8757'` ₹45688), and `DEV PRINT & PACK PRIVATE LIMITED` (a REAL vendor — do not touch its other receipts) has exactly 2 test rows among its 9 total (`id=15` receive `order_receipt_number='OLD YEAR'`, `id=16` bill `bill_number='direct opening demo'` ₹15000) plus 7 genuinely real receives (`order_receipt_number` in `'08','34','41','48','77','62','75'`) that must survive untouched. Total `jc_stock_receipts` rows to delete: **8**, not 4. The live `vendor_receive`-type count today is 84, of which 4 (`id 81, 18, 20, 15`) are these junk-paired rows — after cleanup, 80 real `vendor_receive` rows remain, not 84.

- [ ] **Step 1:** Write the script. It must, in order, inside one transaction:
  1. For vendors `test vendor` and `delete ven` (100% junk — no real data, being fully deactivated in step 5 below regardless): find and print ALL `jc_stock_receipts` rows for these two vendor_ids, with no number filtering — expect exactly 2 rows for `test vendor` (ids 81, 82) and exactly 4 for `delete ven` (ids 18, 19, 20, 21). Abort if the counts don't match these exact expectations (safety check).
  2. For vendor `DEV PRINT & PACK PRIVATE LIMITED` (a REAL vendor — must not touch its other data): find exactly the row where `bill_number = 'direct opening demo'` and exactly the row where `order_receipt_number = 'OLD YEAR'`. Abort if either match count is not exactly 1, or if a third row for this vendor is accidentally matched.
  3. Combine steps 1+2 into one list of exactly 8 `StockReceipt` ids. Print each one's id, vendor, receipt_type, order_receipt_number/bill_number, and amount before deleting.
  4. For each of the 8 matched receipt ids: delete `jc_debit_notes` rows where `receipt_id` matches, delete `jc_ap_ledger_entries` rows where `receipt_id` matches, delete `jc_stock_receipt_lines` rows where `receipt_id` matches, delete the `jc_stock_receipts` row itself.
  5. Delete any remaining `jc_ap_ledger_entries` for vendors named `test vendor`, `delete ven`, or `agrawal test vendor` (their opening-balance/payment/payment_reversal test rows).
  6. Delete `jc_vendor_orders`/`jc_vendor_order_placements`/`jc_vendor_order_lines` rows belonging to vendors `test vendor`, `delete ven`, `agrawal test vendor` (cascade via placement id).
  7. Soft-delete the 3 junk vendors: `UPDATE jc_vendors SET is_active=false, deleted_at=now() WHERE business_name IN ('test vendor','delete ven','agrawal test vendor')`.
  8. Print a final summary (rows deleted per table) before committing. Require typing `yes` at a confirmation prompt before committing (matches the caution used earlier in this chat for destructive operations).

- [ ] **Step 2:** Run it against the real DB, review the printed summary carefully, confirm, and verify afterward with a quick count query that `jc_stock_receipts` has 80 `vendor_receive`-origin rows and 0 `vendor_bill`-type rows, and that `DEV PRINT & PACK PRIVATE LIMITED` still has exactly 7 receipts.

---

### Task 5: Rewrite receive + bill service (`vendor_receive_bill.py`)

**Files:**
- Modify: `JC/backend/app/services/vendor_receive_bill.py`
- Modify: `JC/backend/app/schemas/stock.py`

**Interfaces:**
- Consumes: `compute_bill_totals`, `qty_deviation_debit_note`, `amount_deviation_debit_note` (Task 2)
- Produces:
  - `receive_vendor_goods(db, auth, body: VendorReceiptCreate, *, offline=False) -> dict` (same signature, now freezes expected amounts, no received-bucket `VendorOrder` scaffolding)
  - `bill_receipt(db, auth, receipt_id: int, body: VendorBillIn) -> dict` (**new**, replaces `bill_from_received`)
  - New schema `VendorBillLineIn(catalog_product_id: int, quantity_billed: Optional[int] = None)` and `VendorBillIn(total_billed_amount: Decimal, lines: List[VendorBillLineIn] = [], bill_number: Optional[str] = None, bill_file_key: Optional[str] = None, notes: Optional[str] = None, debit_notes: List[DebitNoteIn] = [])` in `app/schemas/stock.py`

Steps:

- [ ] **Step 1:** Add `VendorBillLineIn` and `VendorBillIn` to `app/schemas/stock.py` (near `VendorReceiptCreate`).

- [ ] **Step 2:** In `receive_vendor_goods`, remove the `received_order = get_or_create_open_order(db, body.vendor_id, "received", "received")` block and the `VendorOrderPlacement`/`VendorOrderLine` creation tied to it (the loop currently adds one `VendorOrderLine` per stock line inside the `for ln in stock_lines:` block alongside the `StockReceiptLine` — delete only the `VendorOrderLine(...)` add, keep the `StockReceiptLine` add and `add_stock()` call). Remove `placement = VendorOrderPlacement(...)` / `db.add(placement)` / `db.flush()` for the received order, and set `receipt.received_placement_id = None` explicitly (field stays on the model per the spec, just unused going forward). After all lines are added, before `db.commit()`, compute and freeze:
  ```python
  from app.services.vendor_billing_math import compute_bill_totals

  total_actual_value = sum((db.get(CatalogProduct, ln.catalog_product_id).buying_price * int(ln.quantity_received or 0) for ln in stock_lines), Decimal("0"))
  bill_total, extra_cash = compute_bill_totals(
      total_actual_value=total_actual_value,
      billing_pct=vendor.billing_pct, additional_charge=vendor.additional_charge,
      discount_pct=vendor.discount_pct, gst_included=vendor.gst_included, gst_rate_pct=vendor.gst_rate_pct,
  )
  receipt.expected_bill_amount = bill_total
  receipt.expected_extra_cash = extra_cash if vendor.billing_pct < 100 else None
  receipt.bill_status = "pending_bill"
  ```
  (Reuse the `prod` objects already fetched in the existing loop instead of a second `db.get` per line, to avoid an extra query — accumulate `total_actual_value` inside the existing `for ln in stock_lines:` loop where `prod` is already available.)

- [ ] **Step 3:** `unbilled_received_qty_by_product` and `reduce_unbilled_received` become dead code after this rewrite (no longer needed — one-to-one model), but Tasks 6–7–8 still import and call them (`app/routers/stock.py`, `app/services/receipt_edit.py`, `app/routers/vendor_orders.py`). Leave both functions in place for now — Task 6 Step 5 deletes them once every call site has been migrated.

- [ ] **Step 4:** Replace `_compute_billing_totals` and `bill_from_received` with the new `bill_receipt`:
  ```python
  def bill_receipt(db: Session, auth: AuthContext, receipt_id: int, body: VendorBillIn) -> dict:
      """Bill a single pending receipt in place. One-to-one: no cross-receipt aggregation."""
      receipt = db.get(StockReceipt, receipt_id)
      if not receipt:
          raise HTTPException(404, "receipt not found")
      if receipt.bill_status != "pending_bill":
          raise HTTPException(400, "receipt is not open for billing")

      vendor = db.get(Vendor, receipt.vendor_id)
      if not vendor or vendor.deleted_at:
          raise HTTPException(404, "vendor not found")
      label = _vendor_label(db, vendor)

      lines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt_id).all()
      lines_by_pid = {ln.catalog_product_id: ln for ln in lines}
      billed_qty_in = {ln_in.catalog_product_id: ln_in.quantity_billed for ln_in in (body.lines or [])}

      normalized: list[tuple[StockReceiptLine, int]] = []
      for ln in lines:
          bq = billed_qty_in.get(ln.catalog_product_id)
          bq = int(bq) if bq is not None else int(ln.quantity_received or 0)
          if bq < 0:
              raise HTTPException(400, f"billed qty for {ln.our_product_id} cannot be negative")
          normalized.append((ln, bq))
      if not any(bq > 0 for _, bq in normalized):
          raise HTTPException(400, "enter billed quantity on at least one row")

      total_actual_value = sum((ln.buying_price * bq for ln, bq in normalized), Decimal("0"))
      bill_total, extra_cash = compute_bill_totals(
          total_actual_value=total_actual_value,
          billing_pct=vendor.billing_pct, additional_charge=vendor.additional_charge,
          discount_pct=vendor.discount_pct, gst_included=vendor.gst_included, gst_rate_pct=vendor.gst_rate_pct,
      )
      entered_total = body.total_billed_amount.quantize(Decimal("0.01"))
      is_split = vendor.billing_pct < 100

      from app.services.biz_date import as_biz_date, resolve_biz_dt
      now = resolve_biz_dt(None)

      for ln, bq in normalized:
          ln.quantity_billed = bq
          ln.billed_amount = (ln.buying_price * vendor.billing_pct / 100 * bq).quantize(Decimal("0.01"))

      receipt.bill_number = (body.bill_number or "").strip() or None
      receipt.bill_file_key = body.bill_file_key
      receipt.additional_charges = vendor.additional_charge.quantize(Decimal("0.01"))
      receipt.total_billed_amount = entered_total
      receipt.actual_ap_amount = (entered_total + extra_cash).quantize(Decimal("0.01")) if extra_cash > 0 else None
      if body.notes is not None:
          receipt.notes = (body.notes or "").strip() or None
      receipt.bill_status = "billed"
      receipt.billed_at = now

      bill_num_label = receipt.bill_number or str(receipt.id)
      post_bill_entry(
          db, vendor_id=receipt.vendor_id, receipt_id=receipt.id, amount=entered_total,
          description=f"Bill {bill_num_label} — ₹{entered_total}",
          actor_type=auth.actor_type, actor_id=auth.actor_id, actor_name=auth.actor_name,
          value_date=as_biz_date(now), created_at=now,
      )
      if is_split and extra_cash > 0:
          post_bill_entry(
              db, vendor_id=receipt.vendor_id, receipt_id=receipt.id, amount=extra_cash,
              description=f"Bill {bill_num_label} — extra cash (half-price balance) ₹{extra_cash}",
              actor_type=auth.actor_type, actor_id=auth.actor_id, actor_name=auth.actor_name,
              value_date=as_biz_date(now), created_at=now,
          )

      bill_product_ids = {ln.catalog_product_id for ln, _ in normalized}
      for dn_in in body.debit_notes or []:
          if dn_in.note_type == "item" and dn_in.catalog_product_id not in bill_product_ids:
              raise HTTPException(400, "debit note item must be from billed lines")
          create_debit_note(db, auth, vendor_id=receipt.vendor_id, receipt_id=receipt.id, body=dn_in, source="manual")

      log_from_auth(
          db, auth, action="bill_received", entity_type="stock_receipt", entity_id=receipt.id,
          entity_label=label, detail=f"billed {len(normalized)} line(s), total ₹{entered_total}",
      )
      db.commit()
      return {
          "ok": True, "receipt_id": receipt.id, "vendor_id": receipt.vendor_id,
          "message": f"Billed {len(normalized)} product(s)", "document_url": None,
      }
  ```
  Note: `create_debit_note` signature changes in Task 6 to accept `source`; auto-suggested notes arriving from the frontend in `body.debit_notes` are tagged `source='manual'` here because by the time they reach this function they've been reviewed/approved by the operator — see Task 6 for why the distinction still matters for stock-touching logic.

- [ ] **Step 5:** Add a preview helper used by the new stock router endpoint (Task 6) to compute suggestions before the operator submits:
  ```python
  def preview_bill_deviations(
      db: Session, vendor: Vendor, lines: list[StockReceiptLine], billed_qty_by_pid: dict[int, int], entered_total: Decimal,
  ) -> dict:
      """Returns expected totals + suggested (unsaved) debit notes for the bill-review UI."""
      from app.services.vendor_billing_math import (
          amount_deviation_debit_note, compute_bill_totals, qty_deviation_debit_note,
      )

      suggestions = []
      total_actual_value = Decimal("0")
      for ln in lines:
          bq = billed_qty_by_pid.get(ln.catalog_product_id, int(ln.quantity_received or 0))
          total_actual_value += ln.buying_price * bq
          dn = qty_deviation_debit_note(
              billed_qty=bq, received_qty=int(ln.quantity_received or 0),
              buying_price=ln.buying_price, billing_pct=vendor.billing_pct,
          )
          if dn:
              suggestions.append({
                  "note_type": "value", "direction": dn["direction"], "amount": str(abs(dn["amount"])),
                  "catalog_product_id": ln.catalog_product_id, "our_product_id": ln.our_product_id,
                  "notes": f"Auto: billed {bq} vs received {ln.quantity_received} for {ln.our_product_id}",
                  "source": "auto",
              })
      bill_total, extra_cash = compute_bill_totals(
          total_actual_value=total_actual_value, billing_pct=vendor.billing_pct,
          additional_charge=vendor.additional_charge, discount_pct=vendor.discount_pct,
          gst_included=vendor.gst_included, gst_rate_pct=vendor.gst_rate_pct,
      )
      amt_dn = amount_deviation_debit_note(expected_bill_total=bill_total, entered_bill_total=entered_total)
      if amt_dn:
          suggestions.append({
              "note_type": "value", "direction": amt_dn["direction"], "amount": str(abs(amt_dn["amount"])),
              "catalog_product_id": None, "our_product_id": None,
              "notes": f"Auto: entered total ₹{entered_total} vs expected ₹{bill_total}",
              "source": "auto",
          })
      return {
          "expected_bill_total": str(bill_total), "expected_extra_cash": str(extra_cash) if vendor.billing_pct < 100 else None,
          "suggested_debit_notes": suggestions,
      }
  ```

---

### Task 6: Debit note `source` field + stock router endpoints

**Files:**
- Modify: `JC/backend/app/services/debit_notes.py`
- Modify: `JC/backend/app/schemas/debit_note.py`
- Modify: `JC/backend/app/schemas/stock.py`
- Modify: `JC/backend/app/routers/stock.py`

**Interfaces:**
- Consumes: `bill_receipt`, `preview_bill_deviations` (Task 5)
- Produces: `create_debit_note(db, auth, *, vendor_id, receipt_id, body, source="manual") -> DebitNote`; `GET /stock/vendor-order/{vendor_id}/received` (new response shape, list of pending receipts); `POST /stock/receipts/{receipt_id}/bill-preview`; `POST /stock/receipts/{receipt_id}/bill`

Steps:

- [ ] **Step 1:** In `app/schemas/debit_note.py`, add `source: Literal["auto", "manual"] = "manual"` to `DebitNoteOut` (for display badges) — `DebitNoteIn` does not need it since the caller passes it as a separate kwarg, not part of the note body.

- [ ] **Step 2:** In `app/services/debit_notes.py`, change `create_debit_note` signature to `create_debit_note(db, auth, *, vendor_id, receipt_id, body, source: str = "manual") -> DebitNote` and pass `source=source` into the `DebitNote(...)` constructor call. No other logic changes — the existing `if note.note_type == "item" and ...: add_stock(...)` block is untouched; it only ever runs for genuinely manual item-type notes because Task 5's auto-suggestions are always `note_type='value'`.

- [ ] **Step 3:** In `app/schemas/stock.py`, replace `ReceivedLineForBill`/`VendorReceivedForBill` with:
  ```python
  class PendingBillReceipt(BaseModel):
      receipt_id: int
      order_receipt_number: Optional[str] = None
      received_at: datetime
      expected_bill_amount: Optional[str] = None
      expected_extra_cash: Optional[str] = None
      line_count: int
      total_quantity: int

  class VendorPendingBillList(BaseModel):
      vendor_id: int
      vendor_label: str
      receipts: List[PendingBillReceipt] = []

  class ReceiptLineForBill(BaseModel):
      catalog_product_id: int
      our_product_id: str
      quantity_received: int
      buying_price: str
      unit: Optional[str] = None
      image_urls: List[str] = []

  class ReceiptForBillDetail(BaseModel):
      receipt_id: int
      vendor_id: int
      vendor_label: str
      order_receipt_number: Optional[str] = None
      expected_bill_amount: Optional[str] = None
      expected_extra_cash: Optional[str] = None
      billing_terms: dict
      lines: List[ReceiptLineForBill] = []

  class BillPreviewIn(BaseModel):
      total_billed_amount: Decimal = Field(..., ge=0)
      lines: List[VendorBillLineIn] = []

  class BillPreviewOut(BaseModel):
      expected_bill_total: str
      expected_extra_cash: Optional[str] = None
      suggested_debit_notes: List[dict] = []
  ```
  Remove the now-unused `ReceivedLineForBill`/`VendorReceivedForBill` — grep for both names across `app/` first to confirm only `stock.py` router uses them (it does, per Task 6 Step 4).

- [ ] **Step 4:** In `app/routers/stock.py`:
  - Replace `get_received_for_bill` (`GET /stock/vendor-order/{vendor_id}/received`) to query `StockReceipt` directly:
    ```python
    @router.get("/vendor-order/{vendor_id}/received", response_model=VendorPendingBillList)
    def get_pending_bill_receipts(vendor_id: int, db: Session = Depends(get_db), auth: AuthContext = Depends(get_auth_context)) -> VendorPendingBillList:
        vendor = db.get(Vendor, vendor_id)
        if not vendor or vendor.deleted_at:
            raise HTTPException(404, "vendor not found")
        label = _vendor_label(vendor, _vendor_city(db, vendor))
        rows = (
            db.query(StockReceipt)
            .filter(StockReceipt.vendor_id == vendor_id, StockReceipt.bill_status == "pending_bill")
            .order_by(StockReceipt.received_at.asc())
            .all()
        )
        receipts = []
        for r in rows:
            lines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == r.id).all()
            receipts.append(PendingBillReceipt(
                receipt_id=r.id, order_receipt_number=r.order_receipt_number, received_at=r.received_at,
                expected_bill_amount=format(r.expected_bill_amount, "f") if r.expected_bill_amount is not None else None,
                expected_extra_cash=format(r.expected_extra_cash, "f") if r.expected_extra_cash is not None else None,
                line_count=len(lines), total_quantity=sum(l.quantity_received for l in lines),
            ))
        return VendorPendingBillList(vendor_id=vendor_id, vendor_label=label, receipts=receipts)
    ```
  - Add `GET /stock/receipts/{receipt_id}/for-bill` → `ReceiptForBillDetail` (404 if `bill_status != 'pending_bill'`), listing that receipt's lines with product/image lookups (same pattern as the old `get_received_for_bill` line-building loop) plus `billing_terms` from the vendor (7 fields, same shape as `VendorBillingTerms`).
  - Add `POST /stock/receipts/{receipt_id}/bill-preview` → `BillPreviewOut`, calling `preview_bill_deviations` (Task 5) after loading the receipt's `StockReceiptLine`s and the vendor.
  - Replace the body of `create_vendor_bill_from_received` with a new route `POST /stock/receipts/{receipt_id}/bill` taking `VendorBillIn`, calling `bill_receipt(db, auth, receipt_id, body)`.
  - Delete the `/stock/receipts/vendor-order` route (`create_vendor_receipt`) and the dead `_finalize_vendor_receipt` function — confirmed unused by any frontend call (grepped, only `/stock/receipts/vendor-receive`, `/stock/receipts/vendor-bill`, `/stock/receipts/offline-vendor` are called from `stock.js`).
  - Delete the old `/stock/receipts/vendor-bill` route entirely (superseded by `/stock/receipts/{receipt_id}/bill`).
  - Update imports at the top of the file: remove `unbilled_received_qty_by_product`, `ReceivedLineForBill`, `VendorReceivedForBill`; add `bill_receipt`, `preview_bill_deviations`, `PendingBillReceipt`, `VendorPendingBillList`, `ReceiptLineForBill`, `ReceiptForBillDetail`, `BillPreviewIn`, `BillPreviewOut`.

- [ ] **Step 5:** Now finish Task 5 Step 3's deferred cleanup: delete `unbilled_received_qty_by_product` and `reduce_unbilled_received` from `vendor_receive_bill.py` (all call sites are gone after Step 4 above and Task 8).

---

### Task 7: Update `receipt_edit.py` for the new one-receipt model

**Files:**
- Modify: `JC/backend/app/services/receipt_edit.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `update_vendor_receipt` still dispatches on `receipt.bill_status` instead of `receipt.receipt_type`

- [ ] **Step 1:** Change `update_vendor_receipt`'s dispatch:
  ```python
  def update_vendor_receipt(db, auth, receipt_id: int, body: VendorReceiptCreate) -> dict:
      receipt = db.get(StockReceipt, receipt_id)
      if not receipt:
          raise HTTPException(404, "receipt not found")
      if body.vendor_id != receipt.vendor_id:
          raise HTTPException(400, "cannot change vendor on an existing bill")
      if receipt.bill_status == "billed":
          return _edit_bill(db, auth, receipt, body)
      return _edit_receive(db, auth, receipt, body)
  ```
  Delete `_edit_combined` (only used by the now-deleted `vendor_order`/`offline_vendor` combined flow — confirm via grep that no receipt in the DB has `receipt_type` outside `vendor_receive`/`vendor_bill`/`offline_vendor` before deleting; `offline_vendor` receipts still go through `_edit_receive` since they're receive-only, `bill_status` starts `pending_bill` for them too).

- [ ] **Step 2:** Simplify `_edit_bill` — since billing is now scoped to one receipt with no cross-receipt unbilled pool, remove the entire "Restore unbilled received from old billed qty... reduce_unbilled_received(...)" block (roughly the code between `restore = [...]` and `reduce_unbilled_received(db, receipt.vendor_id, apply)`). Replace with directly updating `StockReceiptLine.quantity_billed`/`billed_amount` for the lines in `body.lines` (same pattern as the new `bill_receipt` in Task 5, reusing `vendor.billing_pct` to compute `billed_amount`). Remove the `VendorOrderLine`/`billed_placement_id` block entirely (no longer created). Keep the debit-note reverse-and-recreate logic and the `sync_receipt_bill_ledger` call for the primary bill entry; if `vendor.billing_pct < 100`, also reconcile the second AP entry the same way `sync_receipt_bill_ledger` does for the first (new small helper or inline: find the existing extra-cash `ApLedgerEntry` for this `receipt_id` with description containing `"extra cash"`, and adjust via `post_ap_adjustment` the same way).

- [ ] **Step 3:** Manual test: bill a real pending receipt via the new flow, then edit that bill (change billed qty on one line), confirm the AP ledger shows a compensating `adjustment` row rather than a mutated original row (matches the "never mutate prior AP rows" rule already enforced by `sync_receipt_bill_ledger`).

---

### Task 8: `vendor_orders.py` — "to bill" listing off `StockReceipt`, and vendor ledger rewrite

**Files:**
- Modify: `JC/backend/app/routers/vendor_orders.py`
- Modify: `JC/backend/app/services/ledger.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `GET /vendor-orders?bucket=open` "to bill" section now sourced from `StockReceipt.bill_status`; `build_vendor_ledger` reads `StockReceipt`/`StockReceiptLine` only

- [ ] **Step 1:** In the `bucket == "open"` branch of `list_vendor_orders`, replace the "Yet to bill (unbilled received)" block (the one iterating `VendorOrder.filter(bucket == "received", is_open == True)` and calling `unbilled_received_qty_by_product`) with a direct `StockReceipt` group-by:
  ```python
  pending_rows = (
      db.query(StockReceipt.vendor_id, func.count(StockReceipt.id), func.coalesce(func.sum(StockReceiptLine.quantity_received), 0))
      .join(StockReceiptLine, StockReceiptLine.receipt_id == StockReceipt.id)
      .filter(StockReceipt.bill_status == "pending_bill")
      .group_by(StockReceipt.vendor_id)
      .all()
  )
  for vendor_id, receipt_count, total_qty in pending_rows:
      vid = int(vendor_id)
      if today_bill is not None and vid not in today_bill:
          continue
      try:
          vendor, city_name, label = _vendor_context(db, vid, require_active=False)
      except HTTPException:
          continue
      latest = (
          db.query(func.max(StockReceipt.received_at))
          .filter(StockReceipt.vendor_id == vid, StockReceipt.bill_status == "pending_bill")
          .scalar()
      )
      out.append(VendorOrderSummary(
          id=0, vendor_id=vid, vendor_name=vendor.business_name, vendor_city=city_name, vendor_label=label,
          status="to_bill", bucket="open", is_open=True, placement_count=int(receipt_count),
          line_count=int(receipt_count), total_quantity=int(total_qty or 0),
          updated_at=latest or datetime.now(timezone.utc), open_kind="to_bill",
      ))
  ```
  `today_bill` (the `_vids_with_placement_today(("received","billed"))` helper) stops being meaningful for the removed buckets — replace its definition with a `StockReceipt`-based version filtering `received_at`/`billed_at` within the day window, or drop day-filtering for `to_bill` entirely if the existing "Today" toggle isn't exercised for this section (check `JC/web/admin/js/vendor-orders.js` for whether it actually calls this endpoint with `day=today` for the to-bill section before deciding — if unused, simplify by removing the `today_bill` gate).

- [ ] **Step 2:** In the `bucket == "closed"` branch, replace the block iterating `VendorOrder.filter(bucket == "billed", is_open == True)` with a `StockReceipt.bill_status == "billed"` grouped query (same shape: vendor_id, count, total qty, latest `billed_at`), building `VendorOrderSummary(status="closed", bucket="closed", ...)` entries the same way the existing "closed" open-lines section does.

- [ ] **Step 3:** `_build_detail` and `_summary_from_order` still branch on `order.bucket in ("received", "billed")` for the (now never-created) shadow buckets — leave those branches in place (dead code for `bucket in ("received","billed")` since no new rows will have that bucket, but harmless) EXCEPT remove the `from app.services.vendor_receive_bill import unbilled_received_qty_by_product` import at the top of `list_vendor_orders` (function deleted in Task 6 Step 5).

- [ ] **Step 4:** Rewrite `build_vendor_ledger` in `app/services/ledger.py` to drop the placement-iteration block entirely (the `placements = db.query(VendorOrderPlacement, VendorOrder)...` loop and its `if order.bucket == "received"/"billed"` branches) and instead build both "received" and "billed" ledger entries directly from `StockReceipt`/`StockReceiptLine`:
  ```python
  receipts = (
      db.query(StockReceipt)
      .filter(StockReceipt.vendor_id == vendor_id)
      .order_by(StockReceipt.received_at.desc())
      .all()
  )
  for receipt in receipts:
      rlines = db.query(StockReceiptLine).filter(StockReceiptLine.receipt_id == receipt.id).all()
      line_details = [
          LedgerLineDetail(
              our_product_id=ln.our_product_id, quantity_received=ln.quantity_received,
              quantity_billed=ln.quantity_billed, billed_amount=_fmt_amount(ln.billed_amount),
              buying_price=format(ln.buying_price, "f"),
          )
          for ln in rlines
      ]
      summary = ", ".join(f"{ln.our_product_id} +{ln.quantity_received}" for ln in rlines[:8]) or "—"
      entries.append((
          receipt.received_at,
          EntityLedgerEntry(
              id=f"receipt-{receipt.id}", event_type="stock_received", title="Stock receipt", summary=summary,
              occurred_at=receipt.received_at,
              **_actor_fields(receipt.received_by_name, receipt.received_by_type, show_actor),
              details={
                  "receipt_id": receipt.id, "order_receipt_number": receipt.order_receipt_number,
                  "expected_bill_amount": _fmt_amount(receipt.expected_bill_amount), "lines": [l.model_dump() for l in line_details],
              },
          ),
      ))
      if receipt.bill_status == "billed":
          bill_amt = receipt_bill_amount(db, receipt.id)
          dn_total = receipt_debit_note_total(db, receipt.id)
          entries.append((
              receipt.billed_at or receipt.received_at,
              EntityLedgerEntry(
                  id=f"bill-{receipt.id}", event_type="vendor_bill", title="Bill",
                  summary=f"{receipt.bill_number or receipt.id} — ₹{bill_amt}", occurred_at=receipt.billed_at or receipt.received_at,
                  **_actor_fields(receipt.received_by_name, receipt.received_by_type, show_actor),
                  details={
                      "receipt_id": receipt.id, "bill_number": receipt.bill_number,
                      "bill_amount": format(bill_amt, "f"), "debit_note_total": format(dn_total, "f"),
                      "net_payable": format(bill_amt + dn_total, "f"),
                      "additional_charges": _fmt_amount(receipt.additional_charges),
                      "bill_file_url": presigned_url(receipt.bill_file_key) if receipt.bill_file_key else None,
                      "lines": [l.model_dump() for l in line_details],
                  },
              ),
          ))
  ```
  Remove the old separate "receipts" fallback loop at the bottom of the function (the `seen_placement_ids` dedup block) since the block above now fully replaces it. Keep the debit-note and AP-payment sections unchanged.

- [ ] **Step 5:** Manual test: open a real vendor with pending receipts in the admin UI's vendor ledger view, confirm entries render with no errors and match what existed before the rewrite (same receipts, same summaries).

---

### Task 9: Frontend — bill wizard rewrite (`stock.js`)

**Files:**
- Modify: `JC/web/admin/js/stock.js`

**Interfaces:**
- Consumes: `GET /stock/vendor-order/{vendor_id}/received` (now `VendorPendingBillList`), `GET /stock/receipts/{receipt_id}/for-bill`, `POST /stock/receipts/{receipt_id}/bill-preview`, `POST /stock/receipts/{receipt_id}/bill`

- [ ] **Step 1:** Where the wizard currently calls `ctx.api('/stock/vendor-order/${wizardVendorId}/received', {}, 0)` (line ~859) to load unbilled lines for a vendor, change the wizard's "to bill" step: this call now returns `{vendor_id, vendor_label, receipts: [...]}` — render a picker list of pending receipts (order receipt number, received date, expected amount) instead of a flat product table. Selecting one calls `GET /stock/receipts/{receiptId}/for-bill` to load that receipt's lines + `billing_terms` + `expected_bill_amount`/`expected_extra_cash`, and stores `wizardReceiptId`.

- [ ] **Step 2:** Rebuild the billed-quantity step table: columns "Received" (read-only, from `for-bill` response) | "Price" (`buying_price`) | "Billed qty" (input, pre-filled with `quantity_received`, editable). Add a "Total bill amount" number input, always visible/editable, pre-filled with `expected_bill_amount` from the `for-bill` response.

- [ ] **Step 3:** Remove the old client-side `_billingCalc()`/`computedBillTotal()`/`autoSuggestDebitNotes()` functions that read `wizardBillingCtx`/`vendorBillingCtx` (JSON-shaped) — replace the debit-note-suggestion step with a call to `POST /stock/receipts/{wizardReceiptId}/bill-preview` (body: `{total_billed_amount, lines: [{catalog_product_id, quantity_billed}]}`) whenever the operator advances past the billed-quantity step. Populate `pendingDebitNotes` from the response's `suggested_debit_notes` (each tagged `source: 'auto'` for the "auto" badge already built in the debit-note step UI), keeping them editable/removable exactly as today, and letting the operator add manual ones on top.

- [ ] **Step 4:** Update the review/summary step to show, when `expected_extra_cash` is present: "Entry 1 (bill): ₹{total_billed_amount}" and "Entry 2 (extra cash): ₹{expected_extra_cash}" as two distinct lines, using the preview response's `expected_extra_cash` (recomputed fresh from the final billed quantities via the last `bill-preview` call before submit).

- [ ] **Step 5:** Update `submitReceipt` (the function building the final POST body around line ~1428-1431): for the bill path, call `POST /stock/receipts/${wizardReceiptId}/bill` with `{total_billed_amount, lines: [{catalog_product_id, quantity_billed}], bill_number, bill_file_key, notes, debit_notes: pendingDebitNotes}` instead of the old `/stock/receipts/vendor-bill` vendor-wide payload. The receive path (`/stock/receipts/vendor-receive`) is unchanged.

- [ ] **Step 6:** Manual browser test end-to-end: receive goods for a real pending order for a 100%-billing vendor, then bill that exact receipt with a matching total (expect 1 AP entry, no debit notes), then repeat with a deliberately mismatched quantity and amount (expect 2 auto-suggested debit notes, editable), then repeat the full flow for VEE PEE (50% billing) and confirm both AP entries appear with the packing-charge/GST math matching Task 2's test cases.

---

### Task 10: Frontend — "to bill" hub card + vendor form label wiring

**Files:**
- Modify: `JC/web/admin/js/vendor-orders.js`

**Interfaces:**
- Consumes: `GET /vendor-orders?bucket=open` (Task 8's new "to_bill" summaries — same `VendorOrderSummary` shape, no frontend schema change needed)

- [ ] **Step 1:** The "to bill" vendor card in the hub already renders from `VendorOrderSummary` (`status: "to_bill"`) — no shape change needed since Task 8 preserves that schema. Update the card's line/qty caption if it currently assumes "1 vendor = 1 aggregate to-bill entry" wording that would read oddly for "N pending receipts" (e.g. change "X items pending" copy to "N shipment(s) pending" using `placement_count`, which now holds the receipt count per Task 8 Step 1).

- [ ] **Step 2:** Where `vendor-orders.js` calls `GET /stock/vendor-order/${vendorId}/received` (line ~741) for its own preview/summary purposes, update to read the new `{receipts: [...]}` shape instead of a flat `lines` array — confirm what that call site actually displays before changing (read the surrounding ~30 lines) and adapt the summary text (e.g. total pending receipts / total qty across `receipts`).

- [ ] **Step 3:** Manual browser test: open the Orders hub, confirm the "to bill" vendor cards render correctly and clicking one leads into the new per-receipt picker built in Task 9 Step 1.

---

### Task 11: Deploy

**Files:** none (deployment only)

- [ ] **Step 1:** Run the backend test suite: `cd JC/backend && python -m pytest -v` — confirm no regressions beyond the tests this plan intentionally changes.
- [ ] **Step 2:** Run `JC/scripts/prepare-publish.sh` to regenerate `_publish/jc-api` and `_publish/jc-admin`.
- [ ] **Step 3:** Push `_publish/jc-api` to its Railway-connected remote and `_publish/jc-admin` to its Vercel-connected remote, per the existing deployment process used earlier in this project.
- [ ] **Step 4:** Smoke-test on the live Railway API: `GET /api/v1/vendors/5` shows `billing_terms.billing_pct == 50`; `GET /api/v1/stock/vendor-order/5/received` returns the new `receipts` shape.
- [ ] **Step 5:** Smoke-test on the live Vercel admin app: run the same end-to-end billing flow as Task 9 Step 6 against production data for one real pending receipt.
