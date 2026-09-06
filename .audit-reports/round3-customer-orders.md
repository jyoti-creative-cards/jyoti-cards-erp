# JC ERP — Round 3 Audit: Customer Order / Returns FRONTEND

Scope: read-only review of the customer order + returns admin frontend —
`JC/web/admin/js/{customer-orders.js,returns.js,order-menus.js,orders-ui.js}` — covering
the placement wizard, New/Confirm/Billed/Cancelled/Closed bucket tabs, bill create/edit
wizard, dispatch/freight pick UI, returns wizard, addon display, credit-limit banner,
WhatsApp/PDF share buttons. This round intentionally does **not** repeat backend-logic
findings already reported in `.audit-reports/round2-customer-orders.md` (the stuck-Billed
bill bug, the client-side edit-bill-review GST gap, the dead credit-override toggle, the
`_get_or_create_open_line` race, etc.) — those are re-verified as still open but not
re-described here.

Method: read every line of the four in-scope files, traced every `onclick` handler to its
JS function to its API call, then cross-referenced the actual backend endpoint
(`app/routers/customer_orders.py`, `app/routers/customer_returns.py`,
`app/routers/freight_agents.py`, `app/routers/share.py`) and permission decorator
(`app/deps.py` `require_admin`/`require_permission`, `app/services/permissions.py`) to
confirm whether each apparent UI bug is real.

---

## Findings

### CRITICAL

**1. The entire "Dispatch" stage — the button most staff will click right after billing — 403s for every non-admin, even ones explicitly granted "Customer Orders: write".**
`JC/web/admin/index.html:519` renders the "Dispatch" stage chip unconditionally (no
permission check at all) inside `#co-bucket-bar`, which every staff member with
`customer_orders.read` sees. Clicking it calls `CustomerOrders.setBucket('dispatch')` →
`loadDispatch()` (`JC/web/admin/js/customer-orders.js:306-321`), which fetches
`GET /freight-agents/parcels`. The frontend also surfaces "Dispatch" as the **primary
action button on every Billed-bucket order card** regardless of write permission
(`customer-orders.js:537-538`, `581` — the ternary explicitly includes
`currentBucket === "billed"` as a case where the primary button renders even when
`canWrite` is false), as the primary action inside the Billed detail toolbar
(`:759`), and as a button in the "Bill created" success popup shown to whoever just
placed the bill (`:2075`). Every one of these routes to the same dispatch flow, and once
there, the pick/reassign actions are gated only by `canWrite = ctx.canWrite("customer_orders")`
(`:338`, `:369-373`) — i.e. `customer_orders.write`, described in
`app/services/permissions.py:16` as "Place & bill customer orders".

But on the backend, **`GET /freight-agents/parcels` (list), `POST
/freight-agents/parcels/{bill_id}/pick`, and `PATCH /freight-agents/parcels/{bill_id}`
(`app/routers/freight_agents.py:166-221`) are all gated by `require_admin`** — full
admin (`X-Admin-Key`), not any staff permission. A staff member with `customer_orders.write`
(or even one who can already view Billed orders with only `.read`) who opens the Dispatch
tab gets an immediate 403 on the parcel list (empty/error list, no clear reason why), and
if they somehow trigger pick/reassign, that 403s too. This isn't a narrow edge case — it's
the very next step after every single bill creation, permanently unreachable by anyone
but an admin account, even though nothing else in this flow (creating the bill, editing
it, viewing it) requires admin. The router comment at `freight_agents.py:85-92`
(`_can_see_freight_money`) explicitly acknowledges that non-admin `customer_orders.write`
staff are expected to use "this endpoint... while dispatching" (referring to the sibling
`GET /freight-agents` agent-picker endpoint, correctly scoped to
`require_any_permission(...,"customer_orders.write")`) — strongly suggesting the
parcels endpoints' `require_admin` is an oversight, not intended lockdown.
**Fix:** change `list_all_parcels`, `pick_freight_parcel`, and `reassign_freight_parcel`
in `freight_agents.py` to `require_permission("customer_orders.write")` (read-only list
could use `.read`), consistent with every other write action in this lifecycle. Until
fixed, hide the Dispatch chip/buttons from non-admin staff so they don't hit a dead end.

---

### HIGH

**2. The "WhatsApp" share button on every bill is shown to any staff who can view the bill — but the backend endpoint it calls is admin-only, so it always 403s for non-admins.**
`JC/web/admin/js/customer-orders.js:784` (bill card "more" menu) and `:2080` (post-create
success popup) both render a `WhatsApp` button unconditionally — not gated by `canWrite`
or `isAdmin?.()`, unlike the neighboring "Cancel bill"/"Void" items in the same menu
which correctly check `canEditBill`/`ctx.isAdmin?.()`. Clicking it calls
`shareBillWhatsApp(billId)` (`:2117`) → `DocShare.whatsapp({kind:"bill",...})`
(`js/share.js:44-45`) → `POST /share/whatsapp`. That endpoint
(`app/routers/share.py:158-162`) is gated by `Depends(require_admin)` for **every**
`kind`, with no permission-based alternative at all — unlike `GET /share/bills/{id}/pdf`
(Print/Download), which correctly uses `require_permission("customer_orders.read")`
(`share.py:47`). So any staff member — including one with full `customer_orders.write`,
who can create, edit, and cancel this exact bill — sees a working "Print"/"Download PDF"
button right next to a "WhatsApp" button that always fails with a bare `admin only` toast,
with nothing in the UI hinting that WhatsApp specifically needs a different, higher
permission than everything else on the same menu.
**Fix:** either gate the button with `ctx.isAdmin?.()` (matching the actual backend
requirement, same pattern already used for "Void" two lines below it at `:792`), or —
better — relax `/share/whatsapp` to `require_permission("customer_orders.write")` for the
`bill` kind so it matches `/share/bills/{id}/pdf`'s permission level.

**3. Returns wizard: switching customer mid-wizard keeps the previous customer's credit amount and note — a staff member reviewing quickly can submit the wrong AR credit tied to the wrong item mix.**
`JC/web/admin/js/returns.js:238-243` (`pickCustomer`) resets `wizard.customer_id`,
`wizard.returnable`, and `wizard.qtys` when a customer is (re)selected, but never resets
`wizard.credit_amount` or `wizard.notes`. These two fields are only ever set to `""` at
wizard creation time (`openCreate`, `:203-214`) — not when the customer is changed via the
in-wizard "Change" button (`returns.js:349`, calls `Returns.pickCustomer(null)`, which per
`:239-241` clears only `returnable`/`qtys`). Sequence to reproduce: pick Customer A, enter
return qty for a ₹5,000 item → advance to step 2, where `next()` (`:288-293`) auto-fills
`credit_amount = "5000"` since it was empty; go **Back** to step 1, click **Change**, pick
Customer B, enter qty for a completely different, ₹800 item; advance to step 2 again —
`next()`'s `if (!wizard.credit_amount)` guard (`:293`) is now false (it's `"5000"` from
Customer A), so the stale ₹5,000 is what pre-fills the "Credit amount (final AR)" input
for Customer B's return, not the freshly recalculated ₹800. The field is technically
visible and editable on screen (`:401-404`), so a careful reviewer could catch it, but the
UI gives no warning that the number shown is stale/from a different customer — it looks
exactly like a normal pre-filled calculated default, which is precisely what makes this
dangerous (staff are trained to trust it, per the same screen's own copy: "Calculated
(qty × sold)" right above it).
**Fix:** reset `wizard.credit_amount = ""` and `wizard.notes = ""` inside `pickCustomer`
whenever the customer actually changes (not just on full wizard reopen).

---

### MEDIUM

**4. "Cancel bill" pops a second, redundant native `confirm()` after the reason has already been entered and confirmed — the exact anti-pattern a neighboring function's own code comment says was fixed.**
`JC/web/admin/js/customer-orders.js:1216-1218` — `cancelBill`'s `onOk` callback (invoked
by `promptReason` **after** its styled reason-modal has already been confirmed and closed,
per `promptReason`'s own `App.closeModal(); onOk(reason);` at `:1049-1050`) immediately
shows a second, plain browser `confirm("Cancel this bill? Order stays open to bill
again.")` — with no mention of the reason just typed, so if the user hits Cancel here
after already typing and submitting a reason, nothing happens and the reason is silently
discarded with no toast/feedback. Compare `voidBill` four functions later (`:1234-1236`),
whose comment explicitly documents removing this exact double-dialog: *"The promptReason
modal's title already states the consequence and has its own Confirm/Cancel buttons — a
second native confirm() after it was a redundant double dialog."* `cancelBill`'s title
(`"Cancel bill — qty returns to To bill. Freight cleared."`) already does the same
job — it just never got the same cleanup.
**Fix:** delete the `if (!confirm(...)) return;` line at `:1218`; the `promptReason` modal
already serves as the single confirmation, exactly as `voidBill`/`voidPlacement`/
`closeBillLine` do today.

**5. "Mark dispatched" confirm text always claims the freight amount posts to an agent's dues — false for self-pickup/transport parcels, and for zero-charge bus parcels too.**
`JC/web/admin/js/customer-orders.js:395-396` — `pickParcel`'s confirm dialog is
`"Mark picked? Freight amount goes to this agent's dues in Money → Freight."` — shown
verbatim for **every** transport mode, including when the button itself reads "Mark
dispatched" for non-bus parcels (`:370`: `mode === "bus" ? "✓ Picked" : "Mark dispatched"`).
Verified against the backend: `pick_parcel` (`app/services/freight_parcels.py:106-118`)
only sets `freight_picked_at`/`freight_picked_by` for any `mode != "bus"` — there is no
agent, and no dues entry is ever created. Even for `mode === "bus"`, if `freight_charges`
is 0 the function still skips the dues-posting branch entirely (`:121-126`). So the
confirm text is accurate only for the bus-with-a-positive-charge case, yet it's shown
identically for self-pickup and transport parcels, where "this agent's dues" is
nonsensical (there is no agent).
**Fix:** branch the confirm text on `mode`/whether an agent+charge is actually present —
e.g. `"Mark dispatched?"` alone for self-pickup/transport, keeping the dues-specific
wording only for bus mode with `freight_charges > 0`.

---

### LOW

**6. Void confirmation UX is inconsistent between Returns (skippable native `prompt()`) and Bills/Placements (required-reason styled modal) — same backend contract (`reason` optional) in all three cases, different UI weight.**
`JC/web/admin/js/returns.js:167-169` (`voidReturn`) uses a plain browser `prompt(...)`
with an explicit blank-is-OK reason, matching `void_customer_return`'s
`reason: Optional[str]` (`app/services/void_service.py:438`, and the schema backing
`POST /customer-returns/{id}/void`). `voidBill`/`voidPlacement`
(`customer-orders.js:1234-1263`) instead route through `promptReason(...)`, whose textarea
is enforced client-side as required (`:1046-1048`: empty reason blocks with a toast) —
even though the backend `VoidIn.reason` they call into
(`app/schemas/stock.py:12-13`, used by both `bills/{id}/void` and
`placements/{id}/void`) is **also** `Optional[str] = None`, i.e. the backend never
required it either. Same action class ("Admin void → recycle bin, restorable"), same
backend leniency, but one path forces a note and the other doesn't — cosmetically minor,
but confusing for admins who move between the two screens expecting the same rule.
**Fix:** pick one behavior (recommend: keep reason optional everywhere, since the backend
already allows it, and drop the client-side "required" enforcement in `promptReason`'s
void callers — or, if a note is valuable for audit trail, require it in all three
equally, including returns).

**7. Dead code: several exported functions are never called from anywhere in the admin app.**
In `customer-orders.js`: `setDiscMode` (defined `:1918`, exported `:2729`, superseded by
`setDiscToggle` which is what the radio buttons at `:1691-1697` actually call — no caller
anywhere uses `CustomerOrders.setDiscMode`), `setOfflineCustomer` (defined `:2509`,
exported `:2737` — the offline wizard's customer picker actually calls
`pickOfflineCustomer`, never `setOfflineCustomer`), and `addOfflineProduct` (defined
`:2584`, exported `:2738` — the product grid calls `toggleOfflineProduct` directly, never
this wrapper). Also `runHubAction`/`runDetailAction` (`:2138-2145`, exported `:2724`) have
no caller in any `.html`/`.js` file in the admin app (the identical pattern also exists,
unused, in `vendor-orders.js:1722-1735` — a shared leftover from an earlier single-button
action design that was replaced by the current per-card button/menu layout). None of
these are reachable, so they're safe to delete, but they add surface area for a future
edit to "fix" the wrong one (e.g. editing dead `setDiscMode` instead of the live
`setDiscToggle`).
**Fix:** delete the four dead functions (and their exports) from `customer-orders.js`,
and consider the same cleanup in `vendor-orders.js` if that file is ever revisited.

---

## Verified NOT bugs (checked because they matched the requested bug class, ruled out)

- **`cancelBill`'s label "qty returns to To bill. Freight cleared."`** — verified
  against `cancel_customer_bill` (`customer_bill_process.py:492-636`): it does restore
  stock + re-reserve for open, push qty back onto `CustomerOpenLine.quantity_open`, and
  unconditionally clear `freight_agent_id`/`freight_charges`/`freight_picked_at` plus the
  agent-dues charge via `remove_charge_for_bill`. Label is accurate.
- **`voidReturn`'s label "Stock and AR credit will be reversed"`** — verified against
  `void_customer_return` (`void_service.py:438-490`): negatively adjusts stock by the
  returned qty (undoing the restock) and soft-deletes the AR ledger credit entries. Accurate.
- **`saveBillNumber`'s "Must be unique among open bills"`** — verified against
  `patch_bill_number` (`customer_orders.py:1106-1160`): clash check filters
  `cancelled_at.is_(None)`, i.e. scoped to non-cancelled bills exactly as labeled.
- **Editing received/open line qty down to 0 when some qty is already billed** — the
  "Qty" editor (`editReceivedLine`, `customer-orders.js:933`) lets staff type `0` even on
  a fully-billed line, but `edit_customer_placement_line_qty`/`edit_customer_open_qty`
  (`customer_order_flow.py:194-195`, `:238-239`) both hard-reject with a clear "quantity
  cannot be below billed (N)" 400 before anything is touched — not a silent-failure risk,
  just a validated no-op with visible feedback.
- **`closeBillLine`/`close-batch` permission alignment** — `POST
  /bill-lines/{id}/close` and `POST /close-batch` both require `customer_orders.write`
  (`customer_orders.py:927`, `:1223`), matching the frontend's `canWrite` gates exactly;
  no gap here (contrast Finding 1/2 above, which are gaps).
- **WhatsApp/PDF buttons passing the wrong ID** — traced every call site
  (`openBillDoc`/`shareBillWhatsApp` in `customer-orders.js`, `openDoc` in `returns.js`):
  all correctly pass `bill_id`/`return_id` matching the record just created or the one the
  button lives on; no cross-wired IDs found.
- **Returns wizard "Back" data loss** — stepping back and forward through the 3-step
  returns wizard preserves `qtys`/`credit_amount`/`notes` correctly; the only stale-data
  path found is the customer-switch case (Finding 3), not plain Back navigation.
- **Bucket tab routing (`setBucket`/`openDetail`/`switchBucket`)** — traced all five
  bucket transitions (`received→open` via confirm, `open→billed` via bill, `billed→closed`
  via close-batch, cancel paths) and their post-action `openDetail`/`loadList` refresh
  calls; each correctly re-fetches with the new target bucket and invalidates the
  `/customer-orders` cache first. No stale-bucket-after-action cases found beyond the
  already-reported Round 2 CRITICAL (bill-fully-closed-but-still-in-Billed).

---

*Report generated via static code review — no code was modified. Findings above focus on
frontend wiring/labels/permission gating, cross-checked against actual backend endpoint
behavior; Round 2's backend-logic findings are not repeated.*
