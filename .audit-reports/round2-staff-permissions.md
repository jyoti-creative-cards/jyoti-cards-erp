# Round 2 Audit — Staff Accounts, Permissions & Auth Flow (JC ERP)

Scope: `JC/backend/` + `JC/web/admin/` only. Investigation only — nothing was
fixed. Findings ordered by severity.

Accounts referenced:
- **Nikhil** — AR + AP read/write, no cost visibility, no delete.
- **Fiza / Raj** — "Accountant" preset: quick-entry AR/AP/expenses only, no
  delete, no buying price, no finance totals, no activity logs, no
  selling-price edit.

---

## CRITICAL

### 1. "Sell" staff role-preset grants the wrong order permission (buying, not selling)

**File:** `JC/web/admin/js/staff.js:112-118`

```js
{
  id: "sell",
  label: "Sell",
  hint: "Customers + selling orders",
  keys: ["customers.read", "customers.write", "vendor_orders.read", "vendor_orders.write", "catalog.read", "addons.read"],
},
```

**Symptom:** The quick-role button labelled "Sell" (hint: "Customers +
selling orders") does not grant `customer_orders.read` /
`customer_orders.write` (the actual selling-order permission). Instead it
grants `vendor_orders.read` / `vendor_orders.write` — the *buying* permission
— which is already used verbatim by the "Buy" preset two entries below
(`staff.js:120-124`). Any admin who clicks "Sell" while creating/editing a
staff member (e.g. a future hire modeled after this preset) produces an
account that: (a) cannot see the Selling nav tile or place/bill customer
orders at all (`app.js` gates `more-tile-selling` on `canRead("customer_orders")`,
which this preset never grants), and (b) silently *can* place vendor
purchase orders, receive stock against vendors, and bill vendor receipts —
capabilities a "Sell" role should never have. This is both under-permissive
(blocks the intended job) and over-permissive (grants an unrelated, higher-risk
capability) at the same time — a classic copy-paste-from-"Buy" bug.

**Recommended fix:** Change the `sell` preset's `keys` to
`["customers.read", "customers.write", "customer_orders.read", "customer_orders.write", "returns.read", "returns.write", "catalog.read", "addons.read"]` and add a test asserting no two presets share identical `keys`.

---

### 2. Legacy permission-migration re-expands vendor-only staff on every deploy, not once

**File:** `JC/backend/app/db/session.py:167-204` (`_migrate_legacy_staff_permissions`), invoked from `init_db()` at `session.py:141`, which `main.py:34` runs via a background thread **on every process boot** (i.e. every deploy), not once.

```python
has_split = any(p.startswith("customer_orders.") or p.startswith("returns.") for p in perms)
if has_split:
    continue  # already explicit — never touch
expanded = set(perms)
if "vendor_orders.read" in expanded:
    expanded.add("customer_orders.read"); expanded.add("returns.read")
if "vendor_orders.write" in expanded:
    expanded.add("customer_orders.write"); expanded.add("returns.write")
```

**Symptom:** The function's own docstring claims "new rows saved after this
migration runs are unaffected (they only ever get what was explicitly
checked)" — that claim is false. The only guard against re-expansion is
`has_split`: a row is left alone *only if it already has some
`customer_orders.*`/`returns.*` permission*. Any staff row that has
`vendor_orders.read`/`write` but **no** `customer_orders`/`returns`
permission at all — which is exactly what the "Buy" preset in `staff.js`
produces, and exactly what an admin gets if they deliberately narrow a
staff member back down to vendor-only access — will have
`customer_orders.read/write` and `returns.read/write` silently re-added the
very next time the backend restarts (every `git push` to `main` per the
deploy pipeline). This defeats least-privilege for the "Buy" role
permanently and undoes any admin's intentional narrowing within one deploy
cycle, with no log/notification that it happened (the `changed` counter is
only written to `log.info`, not the staff activity log).

**Recommended fix:** Make this migration provably one-time: either record a
`migrated_legacy_order_perms=true` flag per staff row (or a single
`schema_migrations`-style marker), or delete the function entirely now that
it has presumably already run in production, and stop calling it from
`init_db()`.

---

## HIGH

### 3. `DELETE /expenses/{id}` is reachable by the "no-delete" accountant role via direct API

**File:** `JC/backend/app/routers/expenses.py:105-127` (`delete_expense`), also `expenses.py:54-62` (`list_expenses`)

```python
@router.delete("/{expense_id}", status_code=204)
def delete_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("finance.write")),
):
```

**Symptom:** The Accountant preset (`staff.js` `accountant` role, used for
Fiza/Raj) grants `finance.write` specifically so staff can do "entry-only"
quick payments/expenses with no totals, no reports, and — per the explicit
product requirement — **no delete**. The frontend correctly never renders a
Delete button for `finance.write`-only users (they're routed to
`Finance.showQuickEntry()` in `finance.js:221-246`, which has no expense
list/delete UI at all). However the backend endpoint that actually deletes
an expense checks only `finance.write`, the same permission the accountant
already has. Since `Expense` is hard-delete with no `deleted_at` column (no
recycle-bin recovery, per repo convention), any accountant-role staffer who
opens devtools/Postman and calls `DELETE /api/v1/expenses/{id}` directly with
their own JWT can permanently destroy an expense record — exactly the
capability the role is designed to deny. This is the concrete case the audit
asked to check: hiding the button client-side is not backed by an
independent server-side rule here.

**Recommended fix:** Gate `delete_expense` (and ideally `list_expenses`,
which is also broader than the UI needs) behind `require_admin`, or add a
dedicated `finance.delete`-style permission that the accountant preset does
not include.

---

## MEDIUM

### 4. `stock.write` permission label promises capabilities it doesn't actually grant

**File:** `JC/backend/app/services/permissions.py:20`

```python
("Stock", [("stock.read", "View stock"), ("stock.write", "Receive, edit, adjust & bill stock; edit selling prices")]),
```

**Symptom:** This is the exact label an admin sees on the staff permission
checklist (served via `GET /staff/permissions` and rendered in
`staff.js:permCheckboxes`) when deciding what to grant. The Accountant preset
(Fiza/Raj) includes `stock.write` (`staff.js:157`) specifically because they
need to receive/bill stock — but the *same permission's own label* says it
also grants "adjust" and "edit selling prices". In reality, both
`POST /stock/products/{id}/adjust` (`stock.py:508`) and
`PATCH /stock/products/{id}/selling-price` / `POST /stock/products/selling-price/bulk`
(`stock.py:410,442`) are hard-gated to `require_admin` regardless of
`stock.write` — correctly matching the "no selling-price edit" requirement
for the accountant role in practice, but only because the enforcement
ignores what its own label promises. An admin configuring a *custom* (non-preset)
staff account based on this label could reasonably — and wrongly — believe
granting `stock.write` alone hands out stock-adjust and selling-price-edit
ability, and could over- or under-grant a role based on that false premise.

**Recommended fix:** Reword the `stock.write` description to
"Receive, edit & bill stock (stock adjustment and selling-price edits are
always owner/admin-only)" so the label matches the enforced behavior.

---

### 5. Staff phone (login ID) edit sends no notification to the affected staff member

**File:** `JC/backend/app/routers/staff.py:124-153` (`update_staff`)

**Symptom:** `create_staff` (`staff.py:88-123`) and
`reset_staff_password` (`staff.py:156-174`) both call `_send_whatsapp(...)`
to tell the staff member their new credentials. `update_staff` changes
`row.phone` (the staff member's login ID) when an admin edits it — the
frontend's own copy warns the admin "Changing this changes their login
number too" (`staff.js:222`) — but nothing is sent to the staff member
informing them of the change, and no message is echoed back to the admin
about it either (only a generic "Staff updated" toast in `staff.js:257`).
A real, non-technical staff member whose number was corrected (e.g. a typo
fix, or a personal number change) will simply find their old login stops
working with no explanation, and has no message telling them the new
number to use.

**Recommended fix:** When `phone` changes in `update_staff`, send a WhatsApp
notification to the **new** number (mirroring `_send_whatsapp`, with a
"your login number was updated to X" message) and surface `whatsapp_sent`/`whatsapp_error`
in the response the same way create/reset do.

---

## LOW

### 6. `recycle.write` permission label overstates what it actually restores

**File:** `JC/backend/app/services/permissions.py:23` vs. `JC/backend/app/routers/recycle_bin.py` (restore endpoints)

**Symptom:** The `recycle.write` label reads "Restore items (permanent
delete is admin-only)", implying any staff with this permission can restore
anything in the recycle bin (purge is separately admin-gated, which is
correctly implemented). In fact, restoring routes/cities/customers/vendors/
catalog-products/addons uses `recycle.write` (`recycle_bin.py:222-328`), but
restoring **staff, stock receipts, debit notes, customer bills, customer
order placements, and customer returns** all require `require_admin`
outright (`recycle_bin.py:482-595`) — `recycle.write` does nothing for those
categories. This is low-impact (it fails closed, not open — a
`recycle.write` staffer just gets a 403 they don't expect on those entity
types) but is still a mismatched label vs. enforced behavior that could
confuse an admin about what a non-admin recycle operator can actually do.

**Recommended fix:** Either split money-relevant restores into their own
permission, or clarify the label to "Restore routes/cities/customers/vendors/
catalog & add-ons only — money-relevant restores (bills, receipts, debit
notes, staff) are admin-only."

---

## Checked and found OK (no bug — noted for completeness)

- **`canWrite()`/`isAdmin()` usage across all `js/` files**: every
  `canWrite("<resource>")` call maps to a real `<resource>.write` key in
  `ALL_STAFF_PERMISSIONS`, and every literal permission string passed to
  `can()`/`ctx.can?.()` (e.g. `"ar.read"`, `"ap.write"`, `"finance.write"`)
  is a real key. No typos found.
- **Backend permission coverage**: every router endpoint that
  reads/writes non-public data has a `require_admin` / `require_permission`
  / `require_any_permission` dependency (verified via AST scan of all router
  files, not just grep). The only endpoints without a staff/admin dependency
  are customer-portal endpoints (`shop.py`, `auth.py` login/`me`) which
  correctly use `get_current_customer` instead, and `stats.py`/`dashboard.py`,
  which are intentionally open to any authenticated actor and internally
  filter sensitive fields by permission.
- **Cost visibility (`costs.read`)**: `hide_cost()` / `hide_cost_in_diff_summary()`
  / `hide_cost_in_snapshot_json()` are consistently applied everywhere
  `buying_price` is serialized back to a client (`stock.py`, `vendor_orders.py`,
  `addons.py`, `debit_notes.py`, `catalog.py`), so Nikhil (no `costs.read`)
  cannot see buying price/cost anywhere checked.
- **AR/AP reverse/void**: both `accounts_receivable.py` and
  `accounts_payable.py` correctly require `require_admin` for
  reverse/void endpoints regardless of `ar.write`/`ap.write`, so Nikhil
  (AR+AP read/write, no delete) cannot reverse or void a payment — matches
  spec.
- **Rate limiter (`rate_limit.py`)**: lockout correctly triggers at 8 failed
  attempts within a 15-minute window, locks for 15 minutes, and
  `record_success()` clears the counter entirely on a correct login. The
  429 response's `detail` string ("too many attempts — try again in N min")
  is propagated verbatim to the login UI (`app.js:421-422`), not a generic
  500/"Login failed".
- **Staff create / reset-password WhatsApp**: both use `row.phone` (the
  staff's own login number) for both the WhatsApp recipient and the
  in-template "your login is X" text — correct field, and both leave the
  account in a working state (password/row already committed) even if the
  WhatsApp send fails, surfacing `whatsapp_error` + the plaintext temp
  password back to the admin instead.
- **Activity log visibility**: `GET /activity` is `require_admin`-only on
  the backend, and the frontend hides the Activity tile unless `isAdmin()`
  — consistent for both Nikhil and Fiza/Raj (neither is admin), matching
  the "no activity logs" requirement for the accountant role.
- **Accountant dashboard/finance totals**: `dashboard.py` strips
  `pulse`/`top_collect`/`top_pay` when the actor has neither `ar.read` nor
  `ap.read`; `finance.js showQuickEntry()` (used when a staffer has
  `finance.write` but no `ar.read`/`ap.read`) shows only 3 entry buttons
  with no ledger/balance figures — matches "no finance totals" for Fiza/Raj.

---

## Summary by severity

| Severity | Count | Most important |
|---|---|---|
| Critical | 2 | **#1 "Sell" preset grants vendor_orders instead of customer_orders** |
| High | 1 | #3 accountant can delete expenses via direct API |
| Medium | 2 | #4 misleading `stock.write` label, #5 no phone-change notification |
| Low | 1 | #6 misleading `recycle.write` label |

**Single most important finding:** **#1** — the "Sell" role preset in
`JC/web/admin/js/staff.js` is a copy-paste bug that hands out vendor/buying
order permissions under a button literally labeled "Sell", while granting
zero selling-order access. It is the most direct hit on the audit's core
question ("a permission that's supposed to hide something but doesn't, or a
button visible to the wrong role") and would affect any real staff member
onboarded with that preset today.
