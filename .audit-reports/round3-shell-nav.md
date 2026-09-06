# Round 3 Audit — App Shell: Login, Nav, Permission Gating, Modals, Activity/Recycle (JC ERP)

Scope: `JC/web/admin/app.js` (2700 lines) + `JC/web/admin/index.html` (1143
lines) only — the top-level app shell (login, session, global nav, permission
gating, Today dashboard wiring, activity log, recycle bin, global modals).
Cross-referenced against `JC/backend/app/services/permissions.py`,
`JC/backend/app/routers/recycle_bin.py`, `dashboard.py`, `export.py`,
`freight_agents.py`, `payment_modes.py`, and `JC/web/admin/js/staff.js` /
`dashboard.js` where a shell-level bug required following the call chain into
those files. Investigation only — nothing was fixed. Findings ordered by
severity.

This round runs on top of a codebase that has already absorbed prior fixes
(`permissions.py` labels and the legacy-migration issue from round 2 are
already corrected, and the recycle-bin *purge* button is already correctly
admin-gated with an explanatory code comment). The bugs below are new,
independently traced ones found by walking every `onclick` in the shell to
its backend endpoint.

---

## HIGH

### 1. Three Setup tiles (Freight Agents, Payment Modes, Export & Backup) are shown to any staffer who can see the Setup hub, but two of them require permissions — and one requires admin — that a `setup.read`-only staffer doesn't have

**File:** `JC/web/admin/app.js:64` (`more-tile-setup` gate) and `app.js:77-80`
(`applyNavPermissions`) vs. `JC/web/admin/index.html:162` (`setup-tile-freight`),
`index.html:183` (`setup-tile-paymodes`), `index.html:211` (`setup-tile-export`)

```js
document.getElementById("more-tile-setup")?.classList.toggle("hidden", !canRead("setup"));
...
document.getElementById("setup-tile-staff")?.classList.toggle("hidden", !isAdmin());
document.getElementById("setup-tile-activity")?.classList.toggle("hidden", !isAdmin());
document.getElementById("setup-tile-documents")?.classList.toggle("hidden", !isAdmin());
document.getElementById("setup-tile-billseries")?.classList.toggle("hidden", !isAdmin());
```

**Symptom:** `applyNavPermissions()` is the single place the app decides which
Setup-hub tiles to show. It explicitly hides `setup-tile-staff`,
`setup-tile-activity`, `setup-tile-documents` and `setup-tile-billseries` for
non-admins. It does **not** mention `setup-tile-freight`, `setup-tile-paymodes`,
or `setup-tile-export` anywhere — those three `<button id="setup-tile-*">`
elements in `index.html` have no hidden-toggle at all, so they render for
*any* staffer who merely has `setup.read` (enough to open the Setup hub).

This is directly reachable: `js/staff.js:138-143` ships a built-in "Setup"
quick-role preset with `keys: ["setup.read", "setup.write"]` — nothing else.
An admin who clicks that preset while creating a staff member produces an
account that sees all three tiles and gets a 403 on every one of them:

- **Freight Agents** → `FreightAgentsSetup.load()` → `GET /freight-agents`,
  which requires `require_any_permission("vendor_orders.read", "customer_orders.read")`
  (`JC/backend/app/routers/freight_agents.py:139`) — the Setup preset has
  neither.
- **Payment Modes** → `GET /payment-modes`, which requires
  `require_any_permission("finance.write", "ap.write", "ar.write")`
  (`JC/backend/app/routers/payment_modes.py:48`) — the Setup preset has none
  of these either.
- **Export & Backup** → any `App.downloadExportKind()` / `downloadBackupZip()`
  button hits `/export/{kind}.xlsx` or `/export/backup.zip`, both
  `require_admin`-only (`JC/backend/app/routers/export.py:21,26,60`) — a
  non-admin can never succeed here regardless of any permission.

Contrast with the sibling **Safety** page (`more-tile-safety`,
`app.js:65`, `more-safety-recycle`/`more-safety-backup` toggles at
`app.js:66-67`), where the exact same kind of two-button page *is* correctly
gated per-button (`canRead("recycle")` for the recycle-bin link,
`isAdmin()` for the backup link) — showing this is an inconsistency within
the same file, not a fundamental design constraint.

**Recommended fix:** In `applyNavPermissions()`, add:
```js
document.getElementById("setup-tile-freight")?.classList.toggle("hidden",
  !(isAdmin() || canRead("vendor_orders") || canRead("customer_orders")));
document.getElementById("setup-tile-paymodes")?.classList.toggle("hidden",
  !(isAdmin() || can("finance.write") || can("ap.write") || can("ar.write")));
document.getElementById("setup-tile-export")?.classList.toggle("hidden", !isAdmin());
```

---

### 2. Recycle bin "Restore" button is shown for every entity type to any `recycle.write` staffer, but 5 of the 12 types are actually `require_admin`-only server-side

**File:** `JC/web/admin/app.js:2062-2066` (list view) and `app.js:2195-2196`
(detail view) vs. `JC/backend/app/routers/recycle_bin.py:486-600`

```js
const canRecycleWrite = canWrite("recycle");
// Purge (permanent delete) is require_admin server-side for EVERY entity type,
// regardless of recycle.write — ...
const canRestore = i => canRecycleWrite;
const canPurge = () => isAdmin();
```

**Symptom:** The code comment correctly documents that *purge* is
admin-only for every type and gates `canPurge()` on `isAdmin()` — that fix
already landed. But `canRestore` was left as a flat `canRecycleWrite` check
for **every** type, including `receipt`, `debit_note`, `customer_bill`,
`customer_placement`, and `customer_return`. On the backend, restore for
those five types is *also* `require_admin`-only
(`recycle_bin.py:486-600` — `restore_receipt_endpoint`,
`restore_debit_note_endpoint`, `restore_customer_bill_endpoint`,
`restore_customer_placement_endpoint`, `restore_customer_return_endpoint` all
depend on `require_admin`, not `require_permission("recycle.write")`), unlike
`route`/`city`/`customer`/`vendor`/`catalog_product`/`addon` restore, which
correctly only need `recycle.write` (`recycle_bin.py:222-338`).

So a non-admin staffer with `recycle.write` (e.g. the "Setup" preset from
finding #1 if also given `recycle.write`, or any custom staff role built for
"undo my own mistakes on routes/customers") opens the Recycle Bin, filters to
"Receipts/Bills" or "Customer Orders" or "Customer Returns", sees a normal
**Restore** button exactly like on every other tab, clicks it, and gets a
403 with no indication beforehand that this category behaves differently
from the other 7. This is the exact same class of bug the `canPurge` fix
already solved for the Delete-Forever button — it just wasn't applied to
Restore.

**Recommended fix:** Add a set of admin-only recycle types and use it for
both `canRestore` and `canPurge`:
```js
const ADMIN_ONLY_RECYCLE_TYPES = new Set(["receipt", "debit_note", "customer_bill", "customer_placement", "customer_return", "staff"]);
const canRestore = i => isAdmin() || (canRecycleWrite && !ADMIN_ONLY_RECYCLE_TYPES.has(i.type));
```
(note `staff` restore is also `require_admin`-only per `recycle_bin.py:482`,
but it's already excluded from non-admins because the `staff` tab itself is
only added to the tab list `...(isAdmin() ? [...] : [])` at `app.js:2012` —
worth folding into the same constant for clarity/consistency anyway.)

---

### 3. Today dashboard's "Collect next / Pay next" panel is hidden from non-admin AR/AP staff, even though the backend explicitly builds it for them

**File:** `JC/web/admin/js/dashboard.js:267` vs.
`JC/backend/app/routers/dashboard.py:44-54`

```js
// dashboard.js
if (ctx.isAdmin?.() && (collect.length || pay.length)) {
  html += `<section class="home-money"> ... Collect next ... Pay next ... </section>`;
}
```
```python
# dashboard.py
# Pulse/top-collect/top-pay are finance-adjacent figures — only strip them for
# staff with no AR/AP visibility at all. ar.read/ap.read staff (e.g. an
# accountant handed real AR/AP access) should see the same Home numbers admin does.
can_see_ar = auth.has("ar.read") or auth.has("ar.write")
can_see_ap = auth.has("ap.read") or auth.has("ap.write")
if not can_see_ar and not can_see_ap:
    data["pulse"] = None
if not can_see_ar:
    data["top_collect"] = []
if not can_see_ap:
    data["top_pay"] = []
```

**Symptom:** The backend has a deliberate, explicitly-commented design: a
non-admin staffer with `ar.read`/`ar.write` or `ap.read`/`ap.write` (the
"Nikhil" persona from the round 2 audit — AR+AP read/write, no admin) gets
real `top_collect`/`top_pay` arrays back from `GET /dashboard`, specifically
so their Today screen looks like admin's. But `dashboard.js` renders that
whole section only `if (ctx.isAdmin?.())` — it never checks
`ctx.canRead("ar")`/`ctx.canRead("ap")`/`ctx.can("ar.write")` etc. the way
`app.js`'s own `nav-money` gate does
(`isAdmin() || can("finance.write") || canRead("ar") || canRead("ap")`,
`app.js:58`). The same `isAdmin?.()`-only gate is also used for the header's
"Money" quick-nav button at the top of Today
(`dashboard.js` render header, `App.showView('money')` button), which is a
smaller instance of the identical mismatch.

Net effect: the exact staff persona the backend comment calls out by name
("an accountant handed real AR/AP access") does real AR/AP work every day
via the Money tab, but their Today/Home screen — the first thing they see —
never shows "who to collect from" / "who to pay" even though the data is
sitting unused in the API response the page already fetched.

**Recommended fix:** In `dashboard.js`, replace the `ctx.isAdmin?.()` check
guarding the `home-money` section (and the header "Money" button) with the
same permission check `app.js` uses for the Money nav tile:
```js
const canSeeMoneyFocus = ctx.isAdmin?.() || ctx.can?.("ar.read") || ctx.can?.("ar.write") || ctx.can?.("ap.read") || ctx.can?.("ap.write");
if (canSeeMoneyFocus && (collect.length || pay.length)) { ... }
```

---

## MEDIUM

### 4. No modal in the app shell closes on Escape or backdrop click, despite ~20 modals carrying a vestigial `onclick="event.stopPropagation()"` that implies it should

**File:** `JC/web/admin/index.html` — every `.modal-overlay` block from
`#wizard` (line 782) through `#alts-board-modal` (line 1096), e.g.:
```html
<div id="wizard" class="modal-overlay hidden">
  <div class="modal" style="max-width:560px;" onclick="event.stopPropagation()">
```

**Symptom:** ~20 of the app's modal overlays (`wizard`, `vendor-wizard`,
`vendor-edit-modal`, `catalog-wizard`, `catalog-edit-modal`, `addon-wizard`,
`addon-edit-modal`, `staff-modal`, `vo-wizard`, `vo-edit-modal`,
`stock-wizard`, `debit-note-modal`, `settle-modal`, `co-wizard`,
`order-create-menu`, `close-order-modal`, `vo-confirm-modal`,
`co-offline-wizard`, `ar-settle-modal`, `freight-settle-modal`,
`expense-modal`, `loss-modal`, `alts-board-modal`) put
`onclick="event.stopPropagation()"` on the inner `.modal` div — a pattern
that only makes sense if the *outer* `.modal-overlay` div has a click
handler that closes the modal on backdrop click. It doesn't: none of these
outer divs have an `onclick` attribute, and a full-project grep for a
delegated click handler (`document.addEventListener("click", ...)` checking
`e.target.classList.contains("modal-overlay")`, or similar) finds nothing in
any `js/*.js` file. So clicking the dimmed backdrop around any of these ~20
modals does **nothing** — the `stopPropagation()` calls are dead code.

Separately, a full-project grep for `keydown`/`Escape` finds exactly one
implementation: `js/customer-orders.js:649-650,660`, which wires Escape to
close the customer-orders slide-over panel only. Every other modal — the
generic `#modal`, the customer/vendor/catalog/addon/staff wizards and edit
modals, all the settle/expense/loss/debit-note modals — does not respond to
Escape at all.

The one place backdrop-click *is* correctly wired is `#co-slide-backdrop`
(`index.html:532`, `onclick="CustomerOrders.closeSlidePanel()"`) and the
image lightbox `#img-lightbox` (`index.html:1112-1114`,
`onclick="Products.closeLightbox()"` on the outer div, with
`event.stopPropagation()` correctly used on the inner `<img>` to prevent the
image itself from closing the box) — proving the team knows the correct
pattern and simply didn't apply it to the other ~20 overlays.

**Recommended fix:** Add `onclick="if(event.target===this) App.closeModal()"`
(with the module-specific close function) to each `.modal-overlay` div, and
add one delegated `document.addEventListener("keydown", e => { if (e.key ===
"Escape") { /* close topmost open .modal-overlay:not(.hidden) */ } })` in
`app.js` `init()` so all modals get Escape-to-close for free instead of
requiring each module to reimplement it (as `customer-orders.js` did).

---

### 5. Session-expiry ("Session expired — please sign in again") message is generated but the user never actually sees it

**File:** `JC/web/admin/app.js:150-153` (`api()`) and `app.js:440-446`
(`logout()`)

```js
if (res.status === 401) {
  logout();
  throw new Error("Session expired — please sign in again");
}
...
function logout() {
  sessionStorage.removeItem("jc_admin_key");
  sessionStorage.removeItem("jc_staff_token");
  sessionStorage.removeItem("jc_staff_user");
  sessionStorage.removeItem("jc_auth_mode");
  location.reload();
}
```

**Symptom:** On any API call that comes back `401` (token expired /
revoked / staff deactivated mid-session), `api()` calls `logout()` *first*,
which immediately clears session storage and calls `location.reload()`,
and only *then* throws the "Session expired" `Error`. Because
`location.reload()` schedules a navigation rather than halting script
execution synchronously, the thrown error does still propagate to whatever
`catch (e) { toast(e.message, "error") }` block called `api()` — but that
toast, if it manages to paint at all, is destroyed within the same tick by
the page reload that's already in flight. Unlike the admin/staff login
failure paths (`login()`/`staffLogin()`, `app.js:406-408,437-438`), which
call `showLoginShell(e.message)` — a function that explicitly re-shows the
login screen with the message visible in `#login-error`
(`app.js:330-341`) — the 401-mid-session path never calls
`showLoginShell()` at all. A user whose session expires while working is
silently dropped back to a blank login screen with **no indication of why**,
indistinguishable from opening the app fresh.

**Recommended fix:** Change `logout(msg)` to optionally stash the message
(e.g. `sessionStorage.setItem("jc_logout_msg", msg)`) before reloading, and
in `init()` check for and consume that key, calling
`showLoginShell(msg)` after `setLoginTab(...)` instead of reloading blind.

---

## LOW

### 6. Admin login collapses every failure mode into a hardcoded "Invalid admin key" message

**File:** `JC/web/admin/app.js:386-407`

```js
async function login() {
  ...
  try {
    const h = { "Content-Type": "application/json", "X-Admin-Key": key };
    const res = await fetch(`${API}/routes`, { headers: h });
    if (!res.ok) throw new Error("Invalid admin key");
    ...
  } catch (e) {
    showLoginShell(e.message);
  }
}
```

**Symptom:** Unlike `staffLogin()` (`app.js:410-438`), which parses the
response body and surfaces the backend's actual `detail` string (so a
staff-login rate-limit lockout shows the real "too many attempts..."
message, per round 2's audit), `login()` never inspects the response body
or distinguishes failure causes at all — a genuinely wrong key, a `500` from
a backend bug, and a network failure (backend down, DNS failure — which
throws before `res` even exists) are all reported identically as "Invalid
admin key." An admin debugging a backend outage via this login screen would
be told their key is wrong when the real problem is the server isn't
reachable at all.

**Recommended fix:** Mirror `staffLogin()`'s pattern — parse `err.detail`
when `!res.ok`, and catch network-level failures (`e.name ===
"TypeError"`/fetch rejection) separately with a "Could not reach server —
check your connection" message.

---

### 7. Dead code: several `App`-exposed shell functions and one HTML wiring gap are unreachable

**File:** `JC/web/admin/app.js` (various)

**Symptom (verified via full-project cross-reference — every `App.xxx`
reference across `app.js`, `index.html`, and all of `js/*.js` was diffed
against the `App` module's public return object):**

- `onCustomerWizardCityChange` (`app.js:2482`) is defined and exported, but
  the **create**-customer wizard's city `<select id="wf-city_id">`
  (`app.js:2415-2419`, step 1 of `renderWizard()`) has no `onchange`
  attribute and there is no `#wf-city-hint` element in that template at all
  — so the function can never fire. Compare with the **edit**-customer form,
  where the equivalent   `<select id="ed-city_id" ... onchange="App.onCustomerEditCityChange(this.value)">`
  (`app.js:1807`) plus `<div id="ed-city-hint">` (`app.js:1811`) is wired
  correctly and shows the "Route: X · from city Y" hint live. Net effect:
  the helpful route/city hint that exists when *editing* a customer is
  silently missing when *creating* one — a one-line HTML omission, not a
  logic bug, but real: new-customer creation never shows which delivery
  route a chosen city maps to.
- `addLookup` (`app.js:2326-2328`, a thin wrapper around `submitLookup`),
  `wizardBack` / `wizardNext` (`app.js:2609-2610`, an old two-step-wizard
  helper pair — the current wizard's Back/Next buttons call
  `App.closeWizard()`/`App.createCustomer()` directly instead), and
  `debouncedCatalogSearch` / `debouncedAddonSearch` / `debouncedStockSearch`
  (`app.js:128-131`, defined alongside the two that *are* used —
  `debouncedLoadCustomers`/`debouncedVendorSearch` — but never referenced
  from any `oninput`/module) are all exported on `App` and completely
  unreferenced anywhere in the codebase.
- `openCustomerLedgerEntry` (`app.js:1752-1756`) is defined, exported, but
  never called — the working equivalent used everywhere else is
  `App.openSelling(...)`.

**Recommended fix:** Wire the create-wizard's city hint the same way the
edit form does it (one `onchange` + one `<div>`); delete the other unused
functions, or if any was meant to be wired up somewhere (e.g. `wizardBack`
for a real multi-step flow), do that instead of leaving both a live path
and a dead one.

---

## Checked and found OK (no bug — noted for completeness)

- **Every `App.xxx(...)` reference in `index.html` and all inline-HTML
  generated by `app.js`** (67 distinct call sites, cross-referenced by
  script) resolves to a real function in `App`'s returned object — no
  onclick pointing at a removed/renamed/typo'd function was found in the
  shell.
- **Recycle-bin *purge* gating** (`app.js:2065-2067,2196-2197`) is correctly
  restricted to `isAdmin()` for every entity type, matching
  `recycle_bin.py`'s uniform `require_admin` on every `DELETE
  /recycle-bin/*` route — this was a round 2 finding (#6) and the fix has
  fully landed, including an explanatory code comment.
- **Recycle-bin restore/purge confirm copy accuracy**: "Restoring un-hides
  the bill/order only — it stays cancelled if it already was" (shown for
  `customer_bill`/`customer_placement` recycle detail,
  `app.js:2172,2182`) exactly matches `void_service.py`'s
  `restore_customer_bill`/`restore_customer_placement` docstrings and
  behavior (`"""Un-hide only — does not un-cancel."""`) — label doesn't lie.
- **Safety page gating** (`more-safety-recycle` → `canRead("recycle")`,
  `more-safety-backup` → `isAdmin()`, `app.js:66-67`) is correctly
  per-button and matches backend permission requirements exactly — a good
  contrast showing finding #1's bug is an inconsistency, not a hard
  constraint of the codebase.
- **`goBack()` / global back-bar state machine** (`app.js:465-547`): every
  branch that can make the back bar visible (detail overlay, CO slide panel,
  VO/Returns/Reports/Finance sub-details, Setup/More/People sub-tabs, and
  the view-history stack) has a matching `goBack()` branch that unwinds it
  in the same order `updateGlobalBack()` checks it, and `showView()` /
  `closeDetail()` reset `detailStack`/`viewStack` correctly on direct nav —
  no state where the back button would appear but do nothing, or disappear
  while a detail is still open, was found by tracing all ~10 branches.
- **`openCustomerWizard()` / `openCustomerEdit()` state reset**: both
  correctly reset their working state (`wizardStep = 1; wizardForm = {}`
  for the wizard; a fresh `api()` fetch + full innerHTML re-render for edit)
  every time they're opened — no stale-data-on-reopen bug found for these
  two (the ones actually owned by `app.js`; per-module wizards like
  `VendorOrders`/`Stock`/`CustomerOrders` wizards were out of scope, already
  covered by prior rounds).
- **Activity log admin gating**: `setup-tile-activity` is `isAdmin()`-only
  in the frontend (`app.js:78`) and `loadActivity()` itself no-ops for
  non-admins (`app.js:911`, `if (!isAdmin()) return;`) — belt-and-suspenders
  correct, consistent with `GET /activity` being `require_admin` on the
  backend.
- **No distinct "global search" feature exists** to audit — each section
  (People/customers, People/vendors, Products) has its own local,
  debounced, section-scoped search box; there is no top-level omnisearch
  bar in the shell to check for cross-module leakage or wrong-endpoint
  wiring.
- **`checkBackend()` / 401 interceptor's cache/loading-state cleanup**:
  `showLoginShell()` unconditionally zeroes `loadingCount` and hides the
  loading overlay (`app.js:332-334`) so a session expiry (or any login
  failure) can't leave a spinner stuck on-screen forever, even though
  finding #5 shows the *message* itself doesn't survive the reload.

---

## Summary by severity

| Severity | Count | Most important |
|---|---|---|
| High | 3 | **#1 Freight/Payment Modes/Export tiles shown to `setup.read`-only staff, all three 403** |
| Medium | 2 | #4 no modal responds to Escape/backdrop-click, #5 session-expiry message never shown |
| Low | 2 | #6 admin-login error masking, #7 dead code cluster |

**Single most important finding:** **#1** — the built-in "Setup" staff
preset (`js/staff.js:138-143`, `keys: ["setup.read","setup.write"]`) is a
real, one-click way for an admin to create a staff account that immediately
sees three Setup-hub tiles it cannot use, because `applyNavPermissions()`
in `app.js` never learned about `setup-tile-freight`/`setup-tile-paymodes`/
`setup-tile-export` when they were added — the exact same class of
nav/permission drift round 2 found in `staff.js`'s "Sell" preset, just on
the read side this time (shown-but-broken instead of hidden-but-should-show,
though #3 is that exact opposite case). None of round 3's findings are
security holes (every gap fails closed — 403 from the backend — never
open), but #1-#3 are all real, traceable instances of the frontend's
permission model drifting out of sync with the backend's, which is precisely
what this round was asked to hunt for.
