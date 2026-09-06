# Round 2 audit — Freight/Dispatch + PDF Document Generation

Scope: `JC/backend/` + `JC/web/admin/`. Investigation only, no fixes applied.
Date: 2026-09-06

---

## Summary table

| # | Severity | Area | File:Line |
|---|----------|------|-----------|
| 1 | **Critical** | Vendor bill PDF GST math uses vendor's *current* profile, not the bill's snapshot | `app/services/doc_gen.py:333-334` |
| 2 | Medium | "Pick" confirm dialog always claims freight-agent dues, even for self-pickup/transport | `JC/web/admin/js/customer-orders.js:395-396` |
| 3 | Medium | Freight pick/reassign audit-log detail shows raw agent ID, not name | `app/routers/freight_agents.py:188-189, 208-210` |
| 4 | Medium | Route collection sheet PDF has no page numbers (only PDF builder missing `add_page_number`) | `app/services/route_collection_pdf.py:171` |
| 5 | Low | Company brand-bar title is hardcoded, bypasses `company_lines()`/`COMPANY_NAME` env var | `app/services/pdf_documents.py:265` |
| 6 | Low | Image fetching is fully synchronous (not parallelized) on 4 PDF builders, unlike the customer-bill PDF | `app/services/pdf_documents.py:140, 184, 317` |
| 7 | Low | Bill-edit path that changes freight agent/amount on a picked parcel has no dedicated audit-log detail | `app/services/customer_bill_process.py:1247-1256` |

Verified clean (no bug found) — listed at the bottom for completeness against the specific checklist items in the brief.

---

## Finding 1 — CRITICAL: Vendor receipt/bill PDF re-derives GST split from the vendor's *current* profile, not the rate actually used to bill the receipt

**Files:**
- `app/services/doc_gen.py:333-334` (bug)
- `app/services/vendor_receive_bill.py:222-229, 249-250` (where the correct per-bill override is computed and snapshotted, and then never read back)
- `app/routers/stock.py:930-947` (`GET /stock/receipts/{id}/document` — regenerates the PDF from scratch on every single view/print/download)
- `app/models/stock.py:41-42` (the snapshot columns that exist for exactly this purpose)

**Symptom:** When a receipt is billed, staff can override the vendor's GST rate/inclusion for that one bill only via `body.gst_rate_pct_override` (`vendor_receive_bill.py:224-228`). The result is correctly snapshotted onto the receipt row (`receipt.gst_rate_pct_applied = gst_rate_pct if vendor.gst_included else None`, `vendor_receive_bill.py:250`) specifically *because* the vendor's live profile "may differ from vendor default via one-off override" (see the column comments in `stock.py:41-42`).

However, `generate_vendor_receipt_document()` — the function that actually renders the PDF shown/printed/downloaded/WhatsApp'd to accounts — ignores that snapshot entirely:

```333:334:JC/backend/app/services/doc_gen.py
        gst_included=vendor.gst_included,
        gst_rate_pct=vendor.gst_rate_pct,
```

It reads the vendor's *current* `gst_included`/`gst_rate_pct` fields live, not `receipt.gst_rate_pct_applied`. Contrast with the billing-% line right above it, which does it correctly:

```311:JC/backend/app/services/doc_gen.py
    billed_pct = receipt.billing_pct_applied if receipt.billing_pct_applied is not None else vendor.billing_pct
```

This is not a theoretical race: `GET /stock/receipts/{receipt_id}/document` **always regenerates the PDF from scratch** on every call ("Always regenerate so PDF matches current lines" — comment doesn't even mention GST, but the effect is the same regeneration path):

```938:941:JC/backend/app/routers/stock.py
    if storage_configured():
        try:
            generate_vendor_receipt_document(db, receipt.id)
            db.commit()
```

Concretely: bill a receipt today with a one-off GST override (or with the vendor's current 18% GST-inclusive profile), print the receipt PDF — correct taxable-value/GST split shown. Next month the vendor's GST profile is edited (rate change, or GST toggled off/on) for unrelated future receipts. Re-opening/re-printing/re-sharing the *same* old receipt now silently shows a different "Taxable Value"/"GST (X%)" breakdown of the same fixed `total_billed_amount`, or shows/hides the GST line entirely — a financial document that changes after the fact with no edit made to the underlying transaction. This is exactly the vendor-bill GST/override drift called out in the brief.

**Fix:** In `generate_vendor_receipt_document`, compute `gst_rate_pct = receipt.gst_rate_pct_applied if receipt.gst_rate_pct_applied is not None else vendor.gst_rate_pct` and `gst_included = receipt.gst_rate_pct_applied is not None or (receipt.billing_pct_applied is None and vendor.gst_included)` (or simpler: persist an explicit `gst_included_applied` boolean on `StockReceipt` at bill time and read that back), mirroring the existing `billing_pct_applied` fallback pattern one line above.

---

## Finding 2 — Medium: "Pick" confirmation dialog is factually wrong for self-pickup/transport parcels

**File:** `JC/web/admin/js/customer-orders.js:395-396`

```395:396:JC/web/admin/js/customer-orders.js
  async function pickParcel(billId) {
    if (!confirm("Mark picked? Freight amount goes to this agent's dues in Money → Freight.")) return;
```

This single confirm text is used for the button regardless of `transport_mode` — the button itself is correctly relabeled per mode (`mode === "bus" ? "✓ Picked" : "Mark dispatched"`, line 370), but the confirmation dialog is not. For `self_pickup` there is no freight agent at all, and for `transport` mode there is no "agent" either (transport charges are a flat line, not agent-ledger dues) — confirmed server-side: `pick_parcel()` only posts to a freight agent's ledger when `mode == "bus"`; for any other mode it just stamps `freight_picked_at`/`freight_picked_by` and returns (`app/services/freight_parcels.py:113-117`). A non-technical staffer marking a self-pickup order as dispatched will be told "Freight amount goes to this agent's dues," which is nonsensical/alarming when there is no agent and no charge involved.

**Fix:** Branch the confirm text on `mode`, e.g. only mention agent dues when `mode === "bus"`; otherwise just "Mark this parcel as dispatched?".

---

## Finding 3 — Medium: Freight pick/reassign audit-log detail records a raw agent ID, never the agent name

**File:** `app/routers/freight_agents.py:186-190` (pick) and `205-211` (reassign)

```186:190:JC/backend/app/routers/freight_agents.py
    log_from_auth(
        db, auth, action="freight_pick", entity_type="customer_bill",
        entity_id=bill.id, entity_label=bill.bill_number,
        detail=f"agent {bill.freight_agent_id} ₹{bill.freight_charges}",
    )
```

```206:210:JC/backend/app/routers/freight_agents.py
    log_from_auth(
        db, auth, action="freight_reassign", entity_type="customer_bill",
        entity_id=bill.id, entity_label=bill.bill_number,
        detail=f"→ agent {bill.freight_agent_id} ₹{bill.freight_charges}",
    )
```

The amount itself is not stale (it reflects the post-mutation `bill.freight_charges`), so this doesn't match the "swapped/stale value" failure mode, but the *party* is unreadable: `bill.freight_agent_id` is a bare integer, never resolved to the agent's name. Every other freight audit action in the same file logs a human-readable party — e.g. `freight_settle`/`freight_advance` use `entity_label=agent.name` (`freight_agents.py:330`). The activity/audit log UI (`JC/web/admin/js/reports.js:883`, `JC/web/admin/js/dashboard.js:304`) prints `detail` verbatim with no ID→name join, so a staffer auditing "who picked/reassigned this parcel to which courier" sees `agent 7 ₹350.00` instead of `agent Blue Dart Couriers ₹350.00`.

**Fix:** Resolve `agent.name` (already loaded as `agent` inside `pick_parcel`/available via a quick lookup in the router) into the detail string, e.g. `detail=f"agent {agent.name} ₹{bill.freight_charges}"`.

---

## Finding 4 — Medium: Route collection sheet PDF has no page numbers

**File:** `app/services/route_collection_pdf.py:171`

```171:JC/backend/app/services/route_collection_pdf.py
    doc.build(story)
```

Every other PDF-building call site in `pdf_documents.py`, `report_pdfs.py`, and `customer_bill_pdf.py` passes `onFirstPage=add_page_number, onLaterPages=add_page_number` (confirmed via a repo-wide grep of every `doc.build(` call — the *only* other exception is here). `render_route_collection_pdf` already imports `_ist_fmt, _safe` from `pdf_documents` but not `add_page_number`, and builds a document that is explicitly multi-customer, multi-ledger-row, and handed to a delivery/collection agent on paper (per the on-page instruction text "Share with route agent…"/signature line at the bottom) — i.e. exactly the kind of document `add_page_number`'s own docstring says it's for ("Multi-line receipts/bills/statements can silently spill onto extra pages with no visual cue"). A route with several customers each with a multi-row ledger will commonly run to 2+ pages with no way for the field agent to know if a page is missing.

**Fix:** Import `add_page_number` from `app.services.pdf_documents` and pass it to `doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)`.

---

## Finding 5 — Low: Brand-bar title on every "_header()`-based PDF is hardcoded, not sourced from `company_lines()`/`COMPANY_NAME`

**File:** `app/services/pdf_documents.py:263-278` (specifically line 265)

```263:266:JC/backend/app/services/pdf_documents.py
    brand_bar = Table(
        [[Paragraph(
            "JYOTI CREATIVE CARDS",
```

`company_info.py` defines `COMPANY_NAME` as an env-overridable value (`os.environ.get("COMPANY_NAME", "JYOTI CREATIVE CARDS")`), and every document correctly sources the seller's address/phone/GST block from `company_lines()` (e.g. `customer_bill_pdf.py:406` `our = ["From (Seller)"] + company_lines()`). But the big blue brand-bar title at the very top of the document — shared by `render_customer_order_pdf`, `render_vendor_placement_pdf`, `render_vendor_receipt_pdf`, `render_customer_return_pdf`, and (via import) every `customer_bill_pdf.py` invoice — is a literal string, not `company_lines()[0]`/`COMPANY_NAME`. If `COMPANY_NAME` is ever changed via env var (rebrand, or the monorepo's config reused for a different legal entity), the party block underneath would show the new name while the headline banner still says "JYOTI CREATIVE CARDS". Currently invisible because the env default matches the hardcoded string, but it's a latent inconsistency directly on the "is company branding applied consistently" checklist item.

**Fix:** Replace the literal with `company_lines()[0]` (or `COMPANY_NAME` directly) inside `_header()`.

---

## Finding 6 — Low: Image fetching is not parallelized in 3 of 4 line-item table builders (perf/UX, not correctness)

**File:** `app/services/pdf_documents.py:140` (`_vendor_order_table`), `:184` (`_vendor_receipt_table`), `:317` (`_items_table`, used by both `render_customer_order_pdf` and `render_customer_return_pdf`)

These three call `_fetch_image(url, ...)` once per line item, synchronously, each with its own blocking `urllib.request.urlopen(..., timeout=4)` (`pdf_documents.py:34-47`). `customer_bill_pdf.py` deliberately parallelizes the same work with a `ThreadPoolExecutor` (`_prefetch_images_parallel`, `customer_bill_pdf.py:23-41`), with a comment explaining it avoids exactly this serial cost. A vendor PO/goods-receipt or a customer order/return PDF with, say, 20 line items and a slow/degraded image host can take up to ~80s to generate (20 × 4s worst case) where the equivalent customer bill PDF would take ~4-8s. This isn't a crash (missing images already degrade gracefully to an empty cell) but is a real "staff finds this UX confusing/slow" flow issue during dispatch/receiving when a PDF is generated on-demand for print.

**Fix:** Reuse `_prefetch_images_parallel` (already generic over `Dict[int, str|None]`) in `_vendor_order_table`, `_vendor_receipt_table`, and `_items_table` instead of per-row `_fetch_image` calls.

---

## Finding 7 — Low: Editing freight agent/amount on a picked parcel via the bill editor is not separately audit-logged

**File:** `app/services/customer_bill_process.py:1247-1256`, `app/services/freight_parcels.py:42-104` (`sync_bill_freight_on_edit`)

The dedicated `/freight-agents/parcels/{id}/pick` and `PATCH /freight-agents/parcels/{id}` endpoints both log a `freight_pick`/`freight_reassign` activity entry with amount + agent. But freight fields can *also* change through the general bill-edit flow (`customer_bill_process.py` → `sync_bill_freight_on_edit`), e.g. changing `freight_charges` on an already-picked parcel, which re-posts a ledger charge (`freight_parcels.py:80-96`). That path only produces the bill's generic "edited" ledger note (`update_bill_ledger_amount(..., description=f"Bill {bill.bill_number} (edited) — ₹{new_grand}")`, `customer_bill_process.py:1258-1263`) with no mention that a freight charge was also changed, and no dedicated `freight_*` activity action. Not incorrect data, but a real gap if a non-admin ever needs to audit "who changed this agent's freight charge and when" purely from the activity log — one of the two paths that mutates freight-agent dues leaves no freight-specific trail.

**Fix:** Have `sync_bill_freight_on_edit` (or its caller) emit a `freight_edit` activity log entry with the before/after amount and agent, matching the pattern used by the dedicated pick/reassign endpoints.

---

## Verified clean — no bug found (checked against the brief's specific asks)

- **Pending-pick day-scope, all queue variants** (`app/services/freight_parcels.py:238-297`, `list_all_parcels`/`list_agent_parcels` in `app/routers/freight_agents.py:166-175, 234-244`): confirmed "pending" never day-scopes (no `day` filter branch touches it), "all" mixes pending+picked and also never day-scopes, only a pure "picked" view honors `day=today`, and the per-agent view (`/freight-agents/{id}/parcels`) doesn't even accept a `day` param. A picked parcel immediately moves buckets since `list_parcels` filters strictly on `freight_picked_at IS NULL` vs `IS NOT NULL`, and the frontend calls all these endpoints with cache TTL `0` (`customer-orders.js:311-312`), so no client-side staleness either.
- **Freight agent money masking on exports**: `_can_see_freight_money`/`_pub()` masking in `list_freight_agents` only matters for non-admin callers, but every freight PDF/statement export (`GET /share/statements/freight/{id}/pdf`, `GET /share/freight-payments/{id}/pdf`, `POST /share/whatsapp` with `kind=freight_statement|freight_payment`, and `/freight-agents/{id}/settle|advance|ledger`) is gated with `require_admin` (`app/routers/share.py:114-134, 159-162`; `app/routers/freight_agents.py`), so the JSON-only masking gap that item 6 in the brief worried about doesn't actually exist for these endpoints — there is no code path where a masked (non-admin) caller can reach a freight PDF at all.
- **Vendor-facing documents never leak customer credit-limit / customer data**: `render_vendor_placement_pdf`/`render_vendor_receipt_pdf` (`pdf_documents.py:417-565`) and their callers (`doc_gen.py:197-344`) carry zero customer fields.
- **Customer-facing documents never show `vendor_product_id`/vendor buying price, and do show outstanding**: `render_customer_order_pdf`/`render_customer_bill_pdf`/`render_customer_return_pdf` line-building in `doc_gen.py:44-97, 99-183` only ever pass `our_product_id`; `credit_limit` is accepted as a PDF-function parameter but is provably never rendered anywhere in `_build_bill_story` (`customer_bill_pdf.py:316-455`), and `outstanding` (from `customer_ar_totals`) is rendered on both the order PDF and the bill PDF.
- **Image resolution degrades gracefully everywhere**: `_fetch_image` (`pdf_documents.py:34-47`) catches all exceptions and returns `None`; every caller does `_fetch_image(...) or ""`, so a missing/broken image renders as an empty table cell, never a crash, across all four document families (customer order/bill/return, vendor placement/receipt).
- **`doc.build(` call sites in `pdf_documents.py`/`report_pdfs.py` specifically**: all 10 call sites in those two files pass `onFirstPage=add_page_number, onLaterPages=add_page_number` consistently (the one omission found, Finding 4, is in the separate `route_collection_pdf.py` module, which is in scope as "PDF generation across the app" but wasn't one of the two files named).
