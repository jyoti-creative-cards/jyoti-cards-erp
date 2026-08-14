# Bill Discount + Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bills always show original rate, discount %, and net rate (overall XOR per-item; disc XOR net). Bill wizard gains a Mode of transport step (bus / transport / self-pickup).

**Architecture:** Pure helpers `normalize_transport` and `assert_discount_xor` own validation. `compute_bill_totals` always emits original rate + net_rate per line. Bill stores `transport_mode` + optional receipt; reuses `freight_charges`. Wizard inserts a Transport step. PDF/list/dispatch consume the same fields.

**Tech Stack:** FastAPI, SQLAlchemy, Postgres (boot migrations), vanilla admin JS, ReportLab, pytest.

## Global Constraints

- Original rate = catalog selling price; locked
- Overall % XOR per-item; per-item disc % XOR net (if both arrive, disc % wins)
- `transport_mode`: `bus` | `transport` | `self_pickup`
- Bus: agent + charges required. Transport: charges required, receipt optional. Self-pickup: clear agent/charges/receipt
- Reuse `freight_charges`; do not add `transport_charges`
- Charges go on customer bill total
- Dispatch lists all bills; freight ledger only for bus after pick
- No git commits unless the user asks

## File map

- Create: `JC/backend/app/services/transport_mode.py`
- Create: `JC/backend/tests/test_transport_mode.py`
- Modify: `JC/backend/app/services/customer_bill_math.py`
- Modify: `JC/backend/tests/test_bill_math.py`
- Modify: `JC/backend/app/models/customer_bill.py`
- Modify: `JC/backend/app/db/session.py`
- Modify: `JC/backend/app/schemas/customer_order.py`
- Modify: `JC/backend/app/services/customer_bill_process.py`
- Modify: `JC/backend/app/routers/customer_orders.py`
- Modify: `JC/backend/app/services/customer_bill_pdf.py`
- Modify: `JC/backend/app/services/freight_parcels.py`
- Modify: `JC/web/admin/js/customer-orders.js`

---

### Task 1: Transport normalize + discount XOR helpers

**Files:**
- Create: `JC/backend/app/services/transport_mode.py`
- Create: `JC/backend/tests/test_transport_mode.py`
- Modify: `JC/backend/app/services/customer_bill_math.py`
- Modify: `JC/backend/tests/test_bill_math.py`

**Interfaces:**
- Produces: `normalize_transport(...)` → `{transport_mode, freight_agent_id, freight_charges, transport_receipt_number}` or HTTP 400
- Produces: `assert_discount_xor(overall, lines)` or HTTP 400
- Produces: `compute_bill_totals` lines always include `net_rate` (unit after discount) and original `rate_inclusive`

- [ ] **Step 1: Write failing tests** (`test_transport_mode.py` + net_rate cases in `test_bill_math.py`)
- [ ] **Step 2: Run tests — expect FAIL**
- [ ] **Step 3: Implement helpers + always-on `net_rate`**
- [ ] **Step 4: Run tests — expect PASS**

---

### Task 2: Model, migration, schemas, process/edit/preview

**Files:**
- Modify: `JC/backend/app/models/customer_bill.py`
- Modify: `JC/backend/app/db/session.py`
- Modify: `JC/backend/app/schemas/customer_order.py`
- Modify: `JC/backend/app/services/customer_bill_process.py`
- Modify: `JC/backend/app/routers/customer_orders.py`

**Interfaces:**
- Consumes: `normalize_transport`, `assert_discount_xor`
- Produces: bills persist `transport_mode` + `transport_receipt_number`; API in/out include them

- [ ] **Step 1: Columns + backfill migration**
- [ ] **Step 2: Schemas + process/edit/preview/get serializers**
- [ ] **Step 3: Run bill math + transport tests — expect PASS**

---

### Task 3: PDF columns + dispatch

**Files:**
- Modify: `JC/backend/app/services/customer_bill_pdf.py`
- Modify: `JC/backend/app/services/freight_parcels.py`
- Modify: `JC/backend/tests/test_bill_math.py`

- [ ] **Step 1: Failing test for Rate / Disc / Net headers**
- [ ] **Step 2: PDF columns + freight vs transport totals labels**
- [ ] **Step 3: Dispatch lists all bills; pick posts ledger only for bus**
- [ ] **Step 4: Run tests — expect PASS**

---

### Task 4: Admin wizard + list + dispatch UI

**Files:**
- Modify: `JC/web/admin/js/customer-orders.js`

- [ ] **Step 1: Lines always Rate | Disc % | Net; overall XOR per-line**
- [ ] **Step 2: New Transport wizard step; Charges loses freight agent**
- [ ] **Step 3: Review, bill card, dispatch cards show mode + correct labels**
