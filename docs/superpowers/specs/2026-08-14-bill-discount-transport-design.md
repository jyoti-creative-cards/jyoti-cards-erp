# Bill discount + mode of transport

Date: 2026-08-14
Status: approved in chat; pending user review of this file

## Goal

Customer bills always show **original rate**, **discount %**, and **net rate**. Discount is either overall or per-item, never both. Per-item input is discount **or** net rate, never both.

Bill create/edit has a dedicated **Mode of transport** wizard step: Bus, Transport, or Self-pickup. Charges go on the customer bill total.

## Discount

### Rules

- Original rate = catalog selling price. Locked. Not editable on the bill.
- Three visible values on every line: original rate, discount %, net rate (unit, not line total).
- Empty discount means net = original rate.
- **Overall XOR per-item.** Never both on one bill.
- **Overall:** one % for the whole bill. Every line gets that %. Line disc % and net are calculated and read-only.
- **Per-item:** type disc % **or** net rate on a line. The other fills automatically. Last field typed wins; do not send both to the API.
- Backend: client sends **one** of disc % or net per line. If both arrive, disc % wins and net is ignored. If only net is set, derive %. Reject if overall % > 0 **and** any line disc/net is set.

### UI (Lines step)

- Columns always: Product, Rate, Ship qty, Disc %, Net rate.
- Toggle: Off (no discount) / Per-line / Overall.
- Overall: one % input above the table. Line disc/net fill from that %.
- Per-line: disc and net inputs enabled. Typing one updates the other.

### Persistence

- Bill: `discount_percent` set only in overall mode.
- Line: `discount_percent` set only in per-item mode (derived from net when net was typed).
- `unit_price` stays original catalog rate. Line total uses net.

## Mode of transport

### Stored on `jc_customer_bills`

| Field | Meaning |
|---|---|
| `transport_mode` | `bus` \| `transport` \| `self_pickup` (required on new/edited bills) |
| `freight_agent_id` | Required if `bus`. Null otherwise |
| `freight_charges` | Required (numeric, >= 0) if `bus` or `transport`. Null if self-pickup. Same column for both modes; label in UI/PDF depends on mode |
| `transport_receipt_number` | Optional. Only used when `transport`. Empty allowed. Show on UI/PDF only when non-empty |

Do not add a second charges column.

### Wizard (new step after Lines)

Steps: **Lines → Transport → Charges → Narration → Review**

Transport step:

- Three choices: Bus / Transport / Self-pickup. Must pick one before Next.
- **Bus:** freight agent select (required) + charges (required).
- **Transport:** charges (required) + receipt number (optional, may be empty).
- **Self-pickup:** no extra fields. Clear agent, charges, receipt.

Charges step keeps packaging, additional charges, GST, bill series. Freight agent is **not** on this step.

Review shows mode, agent name (bus), receipt if present (transport), and charges with the correct label.

Edit-bill uses the same steps and fields.

### Dispatch

All billed orders still go to Dispatch.

- **Bus:** agent pick (existing). Freight dues post to that agent after pick.
- **Transport / Self-pickup:** no freight-agent ledger. No agent required.

### Old bills

Migration backfill:

- Has `freight_agent_id` → `transport_mode = bus`
- Else → `transport_mode = self_pickup`

## PDF + bill list

Line columns (GST and non-GST): original Rate, Disc %, Net, Amount.

Totals:

- Bus: “Freight charges” + agent name
- Transport: “Transport charges” + receipt number only if set
- Self-pickup: no transport money line

Bill cards / review tables use the same Rate / Disc / Net. Mode visible on the bill card.

## Validation

Reject create/edit when:

- `transport_mode` missing or invalid
- `bus` without `freight_agent_id`
- `bus` or `transport` without charges
- `self_pickup`: backend clears agent, charges, and receipt (do not keep leftovers)
- `transport`: backend clears `freight_agent_id` (do not keep a leftover agent)
- overall discount **and** any line disc/net
- a line ships qty but catalog rate missing

Receipt number is never required.

## Tests

- Overall % → line nets match rate × (1 − %)
- Line disc % → net fills; stored line % used for money
- Line net → disc % derived; money uses net
- Overall + line disc rejected
- Bus without agent rejected; bus/transport without charges rejected
- Transport with empty receipt accepted; receipt printed only when set
- Self-pickup stores null charges/agent/receipt
- PDF columns include Rate, Disc %, Net

## Files (expected)

- `JC/backend/app/models/customer_bill.py` — columns
- `JC/backend/app/db/session.py` — migrate + backfill
- `JC/backend/app/schemas/customer_order.py` — process/edit payloads
- `JC/backend/app/services/customer_bill_process.py` — save/validate
- `JC/backend/app/services/customer_bill_math.py` — net on line totals for PDF
- `JC/backend/app/services/customer_bill_pdf.py` — columns + labels
- `JC/backend/app/routers/customer_orders.py` — API in/out
- `JC/backend/app/services/freight_parcels.py` — dispatch only needs agent for bus
- `JC/web/admin/js/customer-orders.js` — wizard, list, review
- `JC/backend/tests/test_bill_math.py` (+ transport validation tests)

## Out of scope

- Changing catalog prices from the bill
- Mixing overall and per-item discount
- Separate `transport_charges` column
- Making receipt number mandatory
- Skipping Dispatch for transport/self-pickup
