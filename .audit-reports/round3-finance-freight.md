# JC ERP — Finance/Dashboard/Debit-Notes/Freight FRONTEND Audit — Round 3

Scope: `JC/web/admin/js/{finance,dashboard,debit-notes,bill-series,payment-modes,freight-agents}.js`,
cross-referenced against `JC/backend/app/routers/{accounts_payable,accounts_receivable,expenses,debit_notes,freight_agents,payment_modes,bill_series,dashboard}.py`,
`JC/backend/app/services/{ap_ledger,ar_ledger,freight_ledger,money,permissions,debit_notes,payment_reverse}.py`,
`JC/web/admin/app.js` (nav/permission chrome).

Investigation only — nothing changed in the codebase. Builds on round 2
(`round2-finance.md`, `round2-freight-pdf.md`); findings already reported
there are not repeated here.

---

## Summary table

| # | Severity | One-line |
|---|----------|----------|
| H1 | High | Freight agents Setup list: masked "—" balance for read-only staff silently becomes ₹0 **and flips the status pill to "OK"** |
| H2 | High | Debit-note create preview: masked "—" buying price becomes a fake ₹0 effect (same class as round2 H2, recurred in a new module) |
| H3 | High | "Void debit note" button shown in Finance's AP bill view to any `vendor_orders.write` staffer — backend requires admin, always 403s |
| H4 | High | `finance.write`-only "quick entry" role (the documented entry-only accountant permission) can't actually use its own "Record vendor/customer payment" buttons — party search 403s |
| M1 | Medium | Freight agents & Payment Modes Setup tiles have no permission gating — visible (and broken) for any `setup.read`-only staffer |
| M2 | Medium | AR "Set opening" balance UI blocks negative (credit) amounts the backend was explicitly built to support |
| M3 | Medium | Finance AP/AR "Payments" tabs never show or filter by payment mode (Cash/Bank), despite the data being captured and returned |
| M4 | Medium | Quick Add Expense: cancelling the Date or Description prompt does not abort — expense is still recorded |
| L1 | Low | `freight-agents.js` `fmtPrice` fallback for null/empty is "₹0", inconsistent with every other module's "—" |
| L2 | Low | Bill Series Setup tile is hidden for any non-admin, even roles the backend explicitly permits to view it |
| L3 | Low | `BillSeries.openBillDoc` has no loading indicator while the PDF is generated/opened |
| L4 | Low | Home dashboard's header "Money" shortcut is admin-only even though `ar.read`/`ap.read`/`finance.write` roles can open Money from the main nav |

---

## HIGH

### H1. Freight agents Setup list: masked dues silently become ₹0 and the pill claims "OK"

**File:** `JC/web/admin/js/freight-agents.js:79-88`

```79:88:JC/web/admin/js/freight-agents.js
          const due = Number(a.balance_due) || 0;
          const adv = Number(a.advance_left) || 0;
          const balBits = [];
          if (due > 0) balBits.push(`<strong>${fmtPrice(due)}</strong> due`);
          if (adv > 0) balBits.push(`<strong>${fmtPrice(adv)}</strong> advance`);
          if (!balBits.length) balBits.push("No balance");
          return HubUI.partyCard({
            title: a.name,
            meta: `${balBits.join(" · ")}${a.notes ? ` · ${ctx.esc(a.notes)}` : ""}`,
            pillHtml: due > 0 ? HubUI.pill("Due", "danger") : (adv > 0 ? HubUI.pill("Advance", "info") : HubUI.pill("OK", "muted")),
```

Backend (`app/routers/freight_agents.py:88-113`, `_pub`/`_can_see_freight_money`) masks `balance_due`/`advance_left` to the literal string `"—"` for any authenticated caller who lacks all of `ap.read`, `ap.write`, `finance.write`, `vendor_orders.write`, `customer_orders.write`:

```89:96:JC/backend/app/routers/freight_agents.py
def _can_see_freight_money(auth: AuthContext) -> bool:
    """Freight dues are 3rd-party financial exposure, not just order data — a purely
    read-only staffer (vendor_orders.read/customer_orders.read with no write access
    anywhere) shouldn't see it, even though they need this endpoint's id/name list
    to render the agent picker while dispatching."""
    if auth.is_admin:
        return True
    return any(auth.has(p) for p in ("ap.read", "ap.write", "finance.write", "vendor_orders.write", "customer_orders.write"))
```

`GET /freight-agents` itself only requires `vendor_orders.read` **or** `customer_orders.read` (read-only) — so a staffer with e.g. only `vendor_orders.read` legitimately reaches this list, and legitimately gets `balance_due: "—"` per the backend's own design.

`Number("—") || 0` evaluates to `0`, not `NaN`/unknown — exactly the redaction-placeholder-becomes-fake-arithmetic failure mode already found once in round 2 (H2, vendor-order wizard). Here it's worse: the fake `0` doesn't just corrupt a total, it flips the **status pill** to a reassuring green/muted `"OK"` and the card body says **"No balance"** for an agent who may in fact have a large real due — actively telling a restricted-view staffer there's nothing to chase when there might be.

**Fix:** Treat `"—"`/non-numeric `balance_due`/`advance_left` as "hidden", not `0` — e.g. `const raw = a.balance_due; const due = (raw !== "—" && !Number.isNaN(Number(raw))) ? Number(raw) : null;` and render a neutral "Balance hidden" pill/meta instead of "OK"/"No balance" when `due === null`.

---

### H2. Debit-note create preview: masked buying price becomes a fake ₹0 payable effect

**File:** `JC/web/admin/js/debit-notes.js:216-229` (`calcEffect`), contrast `:130` (`fmtPrice` correctly handles it two lines above)

```216:229:JC/web/admin/js/debit-notes.js
  function calcEffect() {
    const type = state.noteType || "item";
    if (type === "item") {
      const catId = parseInt(document.getElementById("dn-product")?.value, 10);
      const qtyAbs = Math.abs(parseInt(document.getElementById("dn-qty")?.value || "0", 10) || 0);
      const line = state.lines.find(l => l.catalog_product_id === catId);
      if (!line || !qtyAbs) return null;
      const price = Number(line.buying_price) || 0;
      const signedQty = state.itemDirection === "extra" ? -qtyAbs : qtyAbs;
      const amt = price * signedQty;
      const effect = -amt; // item: positive qty → pay less
```

`state.lines` is populated from `GET /stock/receipts/{receipt_id}/lines`, which (per round 2's own C1 contrast note) correctly calls `hide_cost()` on `buying_price` for any staffer without `costs.read` — returning the literal string `"—"`. Two lines earlier in the same file (`renderForm`, line 130) the product-picker hint correctly uses `fmtPrice(l.buying_price)`, whose own `Number.isNaN` check degrades gracefully to `"—"`. But `calcEffect()` — used for the live preview shown while creating an item-type debit note, and again in the `confirm()` text right before submission (`review()`, line 268) — does `Number(line.buying_price) || 0`, so a redacted `"—"` becomes `0`.

Concretely: a staffer with `vendor_orders.write` (needed to add a bill correction) but not `costs.read` — a very plausible combination (e.g. a receiving/dispatch-only role) — creating a "Short delivery"/"Extra goods" debit note for any quantity sees the preview say **"AP reduces by ₹0 — you pay less"** and the confirm dialog **"You pay less by ₹0. Add this debit note?"**, regardless of the actual quantity entered.

This does *not* corrupt the stored data — `buildPayload()` never sends a client-computed `amount` for item-type notes; the backend independently recomputes the real amount from the receipt line's true `buying_price` (`app/services/debit_notes.py` → `_resolve_item_amount`). So the debit note that ends up on the vendor's AP statement is correct. But the person creating it is shown a meaningless ₹0 confirmation for a real financial adjustment, with no indication their input even mattered — the exact "similar client-side recomputation" pattern the brief asked to hunt for after round 2's H2.

**Fix:** Same pattern as round 2 H2's recommended fix — treat non-numeric/`"—"` `buying_price` as unknown, not `0`: skip the live preview (`"Amount hidden — you don't have cost visibility"`) rather than rendering/confirming a fake ₹0.

---

### H3. "Void debit note" button shown to `vendor_orders.write` staff in Finance's AP bill view — backend requires admin, always 403s

**File:** `JC/web/admin/js/finance.js:905-926`, contrast `JC/web/admin/js/debit-notes.js:395-396`; backend `JC/backend/app/routers/debit_notes.py:112-124`

```908:919:JC/web/admin/js/finance.js
            ${dns.map(d => {
              const effect = Number(d.payable_effect ?? d.amount) || 0;
              const title = d.our_product_id
                ? `${ctx.esc(d.our_product_id)} × ${d.quantity ?? "—"} (${ctx.esc(d.direction || d.note_type || "")})`
                : `Value (${ctx.esc(d.direction || "adj.")})`;
              const canDn = ctx.canWrite?.("vendor_orders") || ctx.isAdmin?.();
              return `<div class="fin-dn-row">
                <div><strong>${title}</strong>${d.notes ? `<div class="fin-dn-note">${ctx.esc(d.notes)}</div>` : ""}
                <div class="fin-muted">${d.created_at ? new Date(d.created_at).toLocaleString() : ""}</div>
                ${canDn && d.id ? `<div style="margin-top:6px;">
                  <button type="button" class="btn btn-ghost btn-sm" onclick="Finance.editDebitNote(${b.receipt_id},${d.id})">Edit</button>
                  <button type="button" class="btn btn-ghost btn-sm" onclick="Finance.voidDebitNote(${b.receipt_id},${d.id})">Void</button>
                </div>` : ""}
```

Both **Edit** and **Void** are gated by the *same* `canDn` flag (`vendor_orders.write` OR admin). But the backend treats them very differently — and says so explicitly in its own comment:

```112:124:JC/backend/app/routers/debit_notes.py
@router.post("/{note_id}/void")
def void_debit_note_endpoint(
    note_id: int,
    body: VoidIn,
    db: Session = Depends(get_db),
    # Void is destructive to AP history (reverses the ledger effect) — admin only,
    # same trust boundary as every other void/purge in the app. Editing (below)
    # stays at vendor_orders.write since it's a routine correction, not a reversal.
    auth: AuthContext = Depends(require_admin),
):
```

`debit-notes.js` — the module Finance itself delegates the actual void call to (`Finance.voidDebitNote` → `DebitNotes.voidFromList`) — gets this exactly right one file over, with two separate flags:

```395:396:JC/web/admin/js/debit-notes.js
      const canEdit = ctx.isAdmin?.() || ctx.canWrite?.("vendor_orders");
      const canVoid = ctx.isAdmin?.();
```

So a staffer who has `ap.read` (to reach `Finance.openVendorAp`, gated at `finance.js:817`) **and** `vendor_orders.write` (a realistic combination — e.g. a bookkeeper who both processes vendor receipts and reviews AP statements) sees a live "Void" button on every debit note in the AP bill detail view. Clicking it walks them through `DebitNotes.voidFromList`'s reason prompt, then the API call 403s (`require_admin`) — a destructive-sounding action offered and half-completed (reason already typed) before failing.

**Fix:** Split `canDn` in `finance.js:912` into `canEdit = ctx.canWrite?.("vendor_orders") || ctx.isAdmin?.()` and `canVoid = ctx.isAdmin?.()`, mirroring `debit-notes.js`'s own convention, and only show the Void button when `canVoid`.

---

### H4. The documented `finance.write`-only "entry-only accountant" role can't use its own quick-entry payment buttons

**Files:**
- `JC/web/admin/js/finance.js:221-246` (`showQuickEntry` — the screen shown to any staffer with `finance.write` and no `ar.read`/`ap.read`)
- `JC/web/admin/js/finance.js:266-280` (`_pickQuickParty` — calls `GET /vendors?search=` / `GET /customers?search=`)
- `JC/backend/app/routers/vendors.py:80` / `JC/backend/app/routers/customers.py:203-218` (both gated by `vendors.read`/`customers.read` respectively — **not** implied by or bundled with `finance.write`)
- `JC/backend/app/services/permissions.py:17` (`"finance.write"` is documented standalone: *"Record vendor/customer payments & add expenses — no totals or reports"*)
- `JC/backend/app/routers/accounts_payable.py:175-224` / `accounts_receivable.py` (`record_vendor_payment`/`record_customer_payment` — the actual POST endpoints these buttons hit — are gated by `finance.write` alone, no `vendors.read`/`customers.read` required)

`showQuickEntry()` renders exactly three buttons for this role: "Record vendor payment", "Record customer payment", "+ Add expense" (`finance.js:241-243`). The first two call `Finance.quickVendorPayment()` / `Finance.quickCustomerPayment()`, both of which start with `await _pickQuickParty("vendors"/"customers", ...)` to let the staffer search for the party by name/phone via a `prompt()`. That search hits `GET /vendors?search=` / `GET /customers?search=`, each hard-gated to `vendors.read` / `customers.read` — permissions that are **not** part of, implied by, or documented as a prerequisite for `finance.write` anywhere in `permissions.py`. The corresponding backend write endpoints these buttons ultimately call (`POST /accounts-payable/vendor/{id}/record-payment`, `POST /accounts-receivable/customer/{id}/record-payment`) only require `finance.write` — the backend was explicitly built so `finance.write` alone is sufficient to record a payment.

So a staffer granted exactly the permission the app's own permission catalog describes as sufficient (`finance.write`) hits a `403 permission denied: vendors.read` (or `customers.read`) the moment they try to search for a party — the two primary buttons on their entire screen are non-functional. In practice this is masked whenever an admin uses the bundled **"Accountant"** role preset (`JC/web/admin/js/staff.js:145-160`), which happens to also grant `vendors.read`/`customers.read` — but any admin who takes the documented permission model at face value and grants `finance.write` on its own (or unchecks the read perms while fine-tuning, which the staff-permission editor explicitly invites — *"tap a role to tick the common permissions, then fine-tune below"*) reproduces this immediately.

**Fix:** Either (a) have `_pickQuickParty` fall back to a lighter-weight lookup that only requires `finance.write` (a minimal name/id search scoped to what quick-entry needs), or (b) make the backend `finance.write` party-search path explicit — e.g. a dedicated `GET /vendors/quick-search`/`GET /customers/quick-search` gated by `require_any_permission("finance.write","vendors.read")`/`("finance.write","customers.read")` — so the documented "finance.write alone" contract actually holds end-to-end.

---

## MEDIUM

### M1. Freight agents & Payment Modes Setup tiles are shown to any `setup.read` staffer, but 403 unless they also hold unrelated permissions

**Files:**
- `JC/web/admin/app.js:77-86` (`applyNavPermissions` — gates `setup-tile-staff`, `setup-tile-activity`, `setup-tile-documents`, `setup-tile-billseries` to `isAdmin()`; **no equivalent line exists for `setup-tile-freight` or `setup-tile-paymodes`**, so both stay visible to anyone who can see the Setup section at all, i.e. anyone with `setup.read`)
- `JC/web/admin/js/freight-agents.js:24` (`FreightAgentsSetup.load()` → `GET /freight-agents`, gated by `require_any_permission("vendor_orders.read","customer_orders.read")` — `app/routers/freight_agents.py:141-144`)
- `JC/web/admin/js/payment-modes.js:13` (`PaymentModes.load()` → `GET /payment-modes`, gated by `require_any_permission("finance.write","ap.write","ar.write")` — `app/routers/payment_modes.py:41-48`)
- `JC/web/admin/js/staff.js:135-144` (the **"Setup"** quick-role preset: `keys: ["setup.read", "setup.write"]` — nothing else)

Neither `vendor_orders.read`/`customer_orders.read` nor `finance.write`/`ap.write`/`ar.write` are implied by `setup.read`. A staffer given exactly the bundled **"Setup"** preset (routes, cities, product options — its own hint text) sees both a "Freight agents" tile and a "Payment Modes" tile in Setup (unlike Bill Series/Staff/Activity/Documents, which are correctly hidden for them), clicks either, and gets a 403 + error toast with an unhelpful blank list underneath — no indication of why, since neither module renders a permission-specific empty state (`freight-agents.js:32`/`payment-modes.js:20` just `ctx.toast(e.message, "error")`).

**Fix:** Add `setup-tile-freight` / `setup-tile-paymodes` toggles to `applyNavPermissions()`, gated on the same permissions their respective list endpoints require (e.g. `canRead("vendor_orders") || canRead("customer_orders")` for freight; `can("finance.write") || can("ap.write") || can("ar.write")` for payment modes) — mirroring how `setup-tile-billseries` is already gated to match its own endpoint's requirement (though see L2 below — that one over-restricts to admin-only instead).

---

### M2. AR "Set opening" balance UI blocks negative/credit amounts the backend explicitly supports

**Files:**
- `JC/web/admin/js/finance.js:1343` (`<input type="number" step="0.01" min="0" ... id="ar-ob-amt">`)
- `JC/web/admin/js/finance.js:1353-1356` (`saveArOpeningBalance` — `if (!Number.isFinite(amount) || amount < 0) return ctx.toast("Enter a valid amount", "error");`)
- `JC/backend/app/schemas/accounts_receivable.py` (`OpeningBalanceIn.amount: Decimal` — **no `ge=0`**, with an explicit comment: `# signed: positive = customer owes us; negative = we owe customer (credit)`)
- `JC/backend/app/services/ar_ledger.py:123-161` (`set_opening_balance` — fully implements the negative/credit branch: `direction = "debit" if amt > 0 else "credit"`, with its own description text)

The AR opening-balance schema and service layer are fully built to accept a negative opening amount, representing a customer who already had a credit balance as of the tally date (e.g. migrating historical books where a customer had prepaid/overpaid before this system existed). The AP counterpart schema (`accounts_payable.py`'s `OpeningBalanceIn.amount: Decimal = Field(..., ge=0)`) deliberately does *not* support this, so the AP UI's `min="0"` + `amount < 0` rejection (`finance.js:1385-1394`) is correct there. But the same restriction was copy-pasted onto the AR modal, where it blocks a real, documented, fully-implemented backend feature. An accountant trying to set up a customer with an opening credit has no UI path to do it and must go around the app entirely.

**Fix:** Drop `min="0"` from `#ar-ob-amt` and change `saveArOpeningBalance`'s validation to `!Number.isFinite(amount)` only (no floor), updating the modal's helper text to mention that a negative value records a starting credit.

---

### M3. Finance AP/AR "Payments" tabs never surface or filter by payment mode

**Files:** `JC/web/admin/js/finance.js:975-1002` (`renderApPayments`), `:1454-1483` (`renderArPayments`), `:963-973` / `:1427-1444` (the flat ledger table variants)

Every payment row rendered in these four table builders shows When / Reference / Comment / Amount / Balance — none of them read or display `payment_mode`, even though it's captured at settle time (`Finance.submitSettle`/`submitArSettle` both send `payment_mode_id`) and comes back on every entry from the backend (`ApLedgerEntryOut.payment_mode: Optional[str]`, `ArLedgerEntryOut.payment_mode: Optional[str]`). There is no Cash/Bank filter chip anywhere in this file at all — a staffer reconciling collections/payments from inside Finance's own AP/AR detail screens (as opposed to the separate Vendors/Customer-orders ledger screens, which do have a same-purpose but separately-buggy filter per round 2 M3) has zero visibility into which of these payments were cash vs. bank from this screen.

**Fix:** Add a `payment_mode` column to the four Payments/Ledger table renderers, and — for parity with the audit's ask #6 — a Cash/Bank toggle scoped to the current vendor/customer's payment list, ideally sharing the same "untagged" handling fix recommended for `vendors.js` in round 2 M3 rather than reinventing a third variant.

---

### M4. Quick Add Expense: cancelling the Date or Description prompt does not abort — the expense is recorded anyway

**File:** `JC/web/admin/js/finance.js:356-380`

```356:369:JC/web/admin/js/finance.js
  async function quickAddExpense() {
    const category = prompt("Category (e.g. rent, salary, transport, misc):");
    if (category == null || !category.trim()) return;
    const amtRaw = prompt("Amount (₹):");
    if (amtRaw == null) return;
    const amount = Number(amtRaw);
    if (!Number.isFinite(amount) || amount <= 0) return ctx.toast("Enter a valid amount", "error");
    const description = prompt("Description (optional):") || "";
    const today = new Date().toISOString().slice(0, 10);
    const dateRaw = prompt("Date (YYYY-MM-DD):", today) || today;
    ctx.showLoading?.();
    try {
      await ctx.api("/expenses", {
        method: "POST",
        ...
```

The `category` and `amtRaw` prompts correctly abort the whole flow when the user clicks Cancel (`prompt()` returns `null`, checked explicitly). But `description` and, more importantly, `dateRaw` use the `|| fallback` pattern, which cannot distinguish "user clicked Cancel" (`null`) from "user cleared the field and clicked OK" — both silently become the fallback value and the flow **continues to the POST**. There is also no `confirm()` step anywhere in this flow (unlike `quickVendorPayment`/`quickCustomerPayment`, which open with `confirm('Record a payment for "X"?')`), so this is the only guard a staffer has if they change their mind partway through — and it doesn't work. A staffer who enters a category and amount, then thinks better of it and clicks Cancel on the date prompt expecting to abort, instead gets an expense silently recorded with today's date.

**Fix:** Check `dateRaw === null` / `description === null` explicitly and `return` (matching the `category`/`amtRaw` pattern above them), rather than using `||` to paper over a cancelled prompt.

---

## LOW

### L1. `freight-agents.js` `fmtPrice` null/empty fallback is "₹0", not "—"

**File:** `JC/web/admin/js/freight-agents.js:10-15`

```10:15:JC/web/admin/js/freight-agents.js
  function fmtPrice(val) {
    if (val == null || val === "") return "₹0";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }
```

Every other in-scope module's `fmtPrice` (`finance.js`, `dashboard.js`, `debit-notes.js`) returns `"—"` for `null`/`""`. This one alone returns `"₹0"` — a confident-looking real amount where every sibling module would show a neutral placeholder. Currently only reachable if `balance_due`/`advance_left` were ever literally missing (they aren't, today — they're always either a decimal string or the masked `"—"`, which instead hits H1 above), but it's a latent inconsistency and a footgun for future callers.

**Fix:** Change the fallback to `"—"` for consistency with the rest of the app.

### L2. Bill Series Setup tile is hidden for roles the backend explicitly permits to view it

**Files:** `JC/web/admin/app.js:80` (`setup-tile-billseries` hidden unless `isAdmin()`); `JC/backend/app/routers/bill_series.py:135,196,253,317` (list/detail/bill-detail/peek-next all gated by `require_any_permission("vendor_orders.read","customer_orders.read")`, not admin)

The opposite gap from M1: only `create`/`delete` actually need admin server-side; viewing series/bills is deliberately open to any order-facing read role. The frontend nonetheless hides the entire tile unless `isAdmin()`, so e.g. a "Sell" role-preset staffer (`customer_orders.read/write`) who might reasonably want to check "what's the next bill number in this series" has no path to it at all, despite the backend being fine with it.

**Fix:** Not urgent (safe direction — under-exposure, not a leak), but for parity, gate the tile on `canRead("vendor_orders") || canRead("customer_orders")` and keep `BillSeries.canWrite()` (already `isAdmin`-only) as the separate write gate, same pattern recommended for M1.

### L3. `BillSeries.openBillDoc` has no loading indicator

**File:** `JC/web/admin/js/bill-series.js:271-277`

```271:277:JC/web/admin/js/bill-series.js
  async function openBillDoc(billId, print) {
    try {
      const doc = await ctx.api(`/customer-orders/bills/${billId}/document`, {}, 0);
      const w = window.open(doc.document_url, "_blank");
      if (print && w) w.addEventListener("load", () => w.print());
    } catch (e) { ctx.toast(e.message, "error"); }
  }
```

Unlike almost every other async action in these six files, this has no `ctx.showLoading?.()`/`ctx.hideLoading?.()` pair. Per round 2's freight-pdf findings, bill/receipt PDFs regenerate synchronously server-side and can take a visible moment; clicking "Print"/"Download PDF" here gives no feedback until the new tab/print dialog appears, inviting a double-click.

**Fix:** Wrap with the same `ctx.showLoading?.()`/`finally { ctx.hideLoading?.(); }` pattern used everywhere else in this file.

### L4. Home dashboard's "Money" header shortcut is admin-only, stricter than the actual Money nav gate

**Files:** `JC/web/admin/js/dashboard.js:214` (`${ctx.isAdmin?.() ? '<button ...>Money</button>' : ""}`) vs. `JC/web/admin/app.js:58` (`nav-money` hidden only when `!(isAdmin() || can("finance.write") || canRead("ar") || canRead("ap"))`)

A staffer with `ar.read`, `ap.read`, or `finance.write` can already reach Money from the main nav bar, but Home's own quick-action row hides the shortcut button for anyone but a full admin — a minor, harmless inconsistency (the feature is reachable either way) rather than a functional gap.

**Fix:** Match the same condition as `nav-money`'s visibility check, or drop the admin-only gate on the Home button.

---

## Verified clean (checked against the brief's specific asks, no bug found)

- **Quick-entry leak audit**: `showQuickEntry()` never renders a running total, outstanding balance, or Delete button anywhere on screen; `record_vendor_payment`/`record_customer_payment`'s success toast text (`res.message`) is confirmed to only ever say `"Payment of ₹{amount} recorded for {name}"` — no outstanding/balance leaks through the response either.
- **Expense list/delete permission**: `GET /expenses` and `DELETE /expenses/{id}` are both `finance.write`-gated server-side (intentionally, per in-code comments), but the only frontend surface with a visible Delete button (`renderExpenses`) is only ever reached through the full admin hub's Expenses chip — never through `showQuickEntry()` — so this latent backend permission is not actually exposed by any UI path today.
- **Debit-note preview sign convention** (item-type and value-type): traced `calcEffect()`/`buildPayload()` against `normalize_signed_values`/`debit_note_payable_effect` in the backend — the "short/extra"/"over/under" sign math and the resulting "pay less"/"pay more" framing match exactly (only the cost-masking arithmetic bug at H2 is real).
- **Debit-note void reason**: frontend's optional void-reason prompt correctly matches `VoidIn.reason: Optional[str]` — not an inconsistency with the (deliberately different, required-reason) AP/AR payment reverse/void flow.
- **Freight settle/advance amount ceilings**: frontend defers entirely to backend (`_pay_freight` rejects `amount > due` for settle; advance has no ceiling) with no misleading client-side cap or hint — no drift.
- **AP/AR/Freight dues totals**: the client-side `reduce()` sums shown in the AP/AR/Freight list-page summary headers (`renderApList`/`renderArList`/`renderFreightList`) sum the same canonical per-party `outstanding` values returned by `list_ap_vendors`/`list_ar_customers`/agent totals, which the backend's own `assert_dues_consistent()` integrity check cross-verifies against `dues_snapshot()` — no independent re-derivation, no drift risk introduced by this UI.
- **Routes chip / `printRouteCollection`'s admin-key-only fetch**: confirmed the Routes chip (and Freight/Expenses/Reports) is only ever rendered when `ctx.isAdmin()` is true (traced `showHub()`'s top-level gate + `renderHubChrome()`'s `scopedArAp` chip filter), so the hand-rolled `X-Admin-Key`-only header in `printRouteCollection` never needs a staff-JWT branch in practice.
- **onclick wiring**: cross-checked every `Finance.*`, `Dashboard.*`, `DebitNotes.*`, `BillSeries.*`, `PaymentModes.*`, `FreightAgentsSetup.*` reference across the whole `web/admin` tree against each module's exported function table — no dead/missing/misnamed handlers found in any of the six in-scope files.
