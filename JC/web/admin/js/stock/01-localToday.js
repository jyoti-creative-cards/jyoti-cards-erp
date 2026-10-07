  function localToday() {
    const n = new Date();
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
  }
  let enteredFromAddStock = false;
  let receivePrefill = null;
  let offlineProductSearch = "";
  let offlineVendorSearch = "";
  let offlineVendorsCache = [];
  let wizardProducts = [];
  let offlineQtyPopupId = null; // legacy; product pick now uses inline qty
  let focusQtyProductId = null;
  let editReceiptId = null;
  let editReceiptType = null; // vendor_receive | vendor_bill | offline_vendor | vendor_order
  let editAddPickerOpen = false;
  let editAddSearch = "";
  const STOCK_COLS = [
    { key: "our_product_id", label: "Product ID", get: p => p.our_product_id },
    { key: "vendor", label: "Vendor", get: p => p.vendor_label || "" },
    { key: "qty", label: "On Hand", get: p => String(p.quantity_on_hand), numeric: true },
    { key: "price", label: "Sell Price", get: p => p.selling_price || "" },
  ];
  function init(context) { ctx = context; TableUtils.register("stock", () => {}); }
  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }
  function dnPayableEffect(dn) {
    if (dn._payable_effect != null) return Number(dn._payable_effect) || 0;
    if (dn.payable_effect != null) return Number(dn.payable_effect) || 0;
    const amt = Number(dn._amount ?? dn.amount) || 0;
    return dn.note_type === "item" ? -amt : amt;
  }
  function thumb(url) {
    if (url) return `<img src="${ctx.esc(url)}" alt="" class="vo-thumb" />`;
    return `<div class="vo-thumb vo-thumb-empty">—</div>`;
  }
  function reservedByPartyTable(rows) {
    if (!rows || !rows.length) return "";
    const body = rows.map(r => {
      const billId = Number(r.bill_id) || 0;
      const click = billId
        ? `Stock.openVoucher('customer_bill', ${billId})`
        : `Stock.toastNoBill()`;
      return `<tr class="clickable" onclick="${click}">
        <td>${ctx.esc(r.customer_name)}</td>
        <td>${r.unconfirmed || 0}</td>
        <td>${r.to_bill || 0}</td>
        <td>${r.billed_not_dispatched || 0}</td>
        <td><strong>${r.total_held || 0}</strong></td>
      </tr>`;
    }).join("");
    return `<div class="detail-section">
        <h4>Reserved by party</h4>
        <p style="color:var(--muted);font-size:12px;margin:0 0 8px;">Who is holding this stock right now — New (not yet confirmed), To bill (confirmed, unbilled), Billed (invoiced, not yet dispatched). Click a party to open that bill.</p>
        <table class="data history-table"><thead><tr>
          <th>Party</th><th>New</th><th>To bill</th><th>Billed (not dispatched)</th><th>Total held</th>
        </tr></thead><tbody>${body}</tbody></table>
      </div>`;
  }
  async function load() {
    if (typeof Products !== "undefined" && Products.refreshHub) await Products.refreshHub();
  }
  function setViewMode() { /* legacy no-op — Products hub owns view */ }
  function render() { /* legacy no-op */ }
  function renderGrid() { /* legacy — Products hub owns list */ }
  function renderTable() { /* legacy — Products hub owns list */ }
  async function openDetail(id) {
    if (typeof Products !== "undefined" && Products.openProductDetail) {
      return Products.openProductDetail(id, "stock");
    }
    ctx.showLoading?.();
    try {
      const p = await ctx.api(`/stock/products/${id}`, {}, 0);
      const altRows = (p.alternatives || []).length
        ? `<div class="alt-chip-row">${(p.alternatives || []).map(a => {
            const img = (a.image_urls && a.image_urls[0]) || "";
            const place = [a.vendor_name, a.vendor_city].filter(Boolean).join(" · ");
            return `<button type="button" class="alt-chip" onclick="event.stopPropagation();Products.enlargeImage(decodeURIComponent('${encodeURIComponent(img || "")}'))">
              ${img ? `<img src="${ctx.esc(img)}" alt="" />` : `<span class="alt-chip-empty"></span>`}
              <span class="alt-chip-body">
                <strong>${ctx.esc(a.our_product_id)}</strong>
                <span>${ctx.esc(place || "—")}</span>
                <span>${fmtPrice(a.buying_price)}${a.selling_price ? ` / ${fmtPrice(a.selling_price)}` : ""}</span>
              </span>
            </button>`;
          }).join("")}</div>`
        : `<p style="color:var(--muted);font-size:13px;margin:0;">No alternatives</p>`;
      const ledgerRows = ledgerTableHtml(p.ledger);
      const img = (p.image_urls && p.image_urls[0]) || "";
      const realSell = p.selling_price != null && p.selling_price !== ""
        && Number(p.selling_price) !== Number(p.buying_price);
      const sellHtml = realSell
        ? `<div class="stock-price-row"><strong>${fmtPrice(p.selling_price)}</strong>
            ${ctx.isAdmin?.() ? `<button class="btn btn-secondary btn-sm" onclick="Stock.setSellingPrice(${p.catalog_product_id}, '${ctx.esc(String(p.selling_price))}')">Set</button>` : ""}</div>`
        : `<div class="stock-price-row"><span class="prod-price-missing">Not set</span>
            ${ctx.isAdmin?.() ? `<button class="btn btn-primary btn-sm" onclick="Stock.setSellingPrice(${p.catalog_product_id}, '')">Set sell price</button>` : ""}</div>`;
      const statusBadge = p.stock_status === "in_stock" ? "badge-green"
        : p.stock_status === "low_stock" ? "badge-amber"
        : p.stock_status === "negative_stock" ? "badge-red" : "badge-gray";
      ctx.openDetail(p.our_product_id, `
        <div style="display:flex;gap:16px;margin-bottom:20px;align-items:flex-start;">
          ${img ? `<img src="${ctx.esc(img)}" class="stock-detail-img" onclick="Products.enlargeImage(decodeURIComponent('${encodeURIComponent(img)}'))" style="cursor:zoom-in;" />` : ""}
          <div>
            <div style="font-size:13px;color:var(--muted);">${ctx.esc(p.vendor_label)}${p.year_group ? ` · ${ctx.esc(p.year_group)}` : ""}</div>
            <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
              <span class="badge badge-blue">On hand: ${p.quantity_on_hand}</span>
              <span class="badge ${statusBadge}">${ctx.esc((p.stock_status || "").replace(/_/g, " "))}</span>
              <span class="badge badge-gray" title="Vendor inbound goods not yet received — not a customer reservation">Pending order (vendor inbound): ${p.quantity_pending}</span>
              ${ctx.isAdmin?.() ? `<button class="btn btn-secondary btn-sm" onclick="Stock.adjustStock(${p.catalog_product_id}, ${p.quantity_on_hand})">Adjust stock</button>` : ""}
            </div>
          </div>
        </div>
        <div class="stock-price-panel">
          <div class="stock-price-block">
            <span class="stock-price-label">Sell price</span>
            ${sellHtml}
          </div>
          <div class="stock-price-block">
            <span class="stock-price-label">Buy price</span>
            <strong>${fmtPrice(p.buying_price)}</strong>
          </div>
          <div class="stock-price-block">
            <span class="stock-price-label">Low stock threshold</span>
            <div class="stock-price-row">
              <strong>${p.low_stock_threshold ?? 5}</strong>
              ${ctx.canWrite?.("stock") || ctx.canWrite?.("catalog")
                ? `<button class="btn btn-threshold" onclick="Stock.editThreshold(${p.catalog_product_id}, ${p.low_stock_threshold ?? 5})">Set threshold</button>`
                : ""}
            </div>
          </div>
        </div>
        <div class="review-grid" style="margin:16px 0 20px;">
          ${ctx.reviewRow("Vendor product ID", p.vendor_product_id || "—")}
          ${ctx.reviewRow("Year group", p.year_group || "—")}
          ${ctx.reviewRow("Category", p.category || "—")}
        </div>
        <div style="margin-bottom:16px;"><strong style="font-size:13px;">Alternatives</strong><div style="margin-top:8px;">${altRows}</div></div>
        ${reservedByPartyTable(p.reserved_by_party)}
        <div class="detail-section">
          <h4>Stock Ledger</h4>
          <p style="font-size:12px;color:var(--muted);margin:0 0 8px;">Click a row to open that bill.</p>
          ${ledgerRows}
        </div>`,
        `${(ctx.canWrite?.("catalog") || ctx.isAdmin?.()) ? `<button type="button" class="btn btn-secondary btn-sm" onclick="event.stopPropagation();Catalog.openEdit(${p.catalog_product_id}, 'stock')">Edit</button>` : ""}
         <button class="btn btn-secondary btn-sm" onclick="Catalog.openDetail(${p.catalog_product_id})">Catalog view</button>
         <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
        "lg"
      );
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  function openAddWizard() {
    wizardStep = 1; wizardMode = null; wizardVendorId = null; placedOrder = null;
    wizardLines = []; billFile = null; billFileKey = null; pendingDebitNotes = [];
    offlineVendorsCache = []; wizardProducts = []; // always fetch fresh on open
    enteredFromAddStock = true;
    receiptMeta = { billNumber: "", orderReceiptNumber: "", additionalCharges: "", totalBilledAmount: "", billingPct: "", gstPct: "", notes: "", eventDate: localToday() };
    document.getElementById("stock-wizard")?.classList.remove("hidden");
    renderWizard();
  }
  function closeWizard() {
    document.getElementById("stock-wizard")?.classList.add("hidden");
    document.querySelector("#stock-wizard .modal-header h3").textContent = "Add Stock";
    document.querySelector("#stock-wizard .stock-wiz-modal")?.classList.remove("stock-wiz-wide");
    offlineQtyPopupId = null;
    editReceiptId = null;
    editReceiptType = null;
    editAddPickerOpen = false;
    editAddSearch = "";
  }
  async function openReceiveForVendor(vendorId, prefill) {
    wizardStep = vendorId ? 2 : 1;
    wizardMode = "receive_goods";
    wizardVendorId = vendorId || null;
    placedOrder = null;
    wizardLines = [];
    billFile = null;
    billFileKey = null;
    pendingDebitNotes = [];
    offlineVendorSearch = "";
    offlineVendorsCache = [];
    receivePrefill = prefill || null;
    enteredFromAddStock = false;
    receiptMeta = { billNumber: "", orderReceiptNumber: "", additionalCharges: "", totalBilledAmount: "", billingPct: "", gstPct: "", notes: "", eventDate: localToday() };
    document.getElementById("stock-wizard")?.classList.remove("hidden");
    document.querySelector("#stock-wizard .modal-header h3").textContent = "Receive Goods";
    await renderWizard();
  }
  async function openBillForVendor(vendorId, prefill) {
    wizardStep = vendorId ? 2 : 1;
    wizardMode = "bill_received";
    wizardVendorId = vendorId || null;
    placedOrder = null;
    wizardLines = [];
    billFile = null;
    billFileKey = null;
    pendingDebitNotes = [];
    offlineVendorSearch = "";
    offlineVendorsCache = [];
    receivePrefill = prefill || null;
    enteredFromAddStock = false;
    wizardReceiptId = null;
    wizardPendingBillList = null;
    billingTerms = null;
    billPreview = null;
    receiptMeta = { billNumber: "", orderReceiptNumber: "", additionalCharges: "", totalBilledAmount: "", billingPct: "", gstPct: "", notes: "", eventDate: localToday() };
    document.getElementById("stock-wizard")?.classList.remove("hidden");
    document.querySelector("#stock-wizard .modal-header h3").textContent = "Bill Order";
    await renderWizard();
  }
  async function openOfflineWizard(vendorId) {
    wizardStep = vendorId ? 2 : 1;
    wizardMode = "offline_vendor";
    wizardVendorId = vendorId || null;
    placedOrder = vendorId ? { vendor_id: vendorId, vendor_label: "Receive without order" } : null;
    wizardProducts = [];
    wizardLines = [];
    offlineProductSearch = "";
    offlineVendorSearch = "";
    offlineVendorsCache = [];
    billFile = null;
    billFileKey = null;
    pendingDebitNotes = [];
    receiptMeta = { billNumber: "", orderReceiptNumber: "", additionalCharges: "", totalBilledAmount: "", billingPct: "", gstPct: "", notes: "", eventDate: localToday() };
    document.getElementById("stock-wizard")?.classList.remove("hidden");
    document.querySelector("#stock-wizard .modal-header h3").textContent = "Receive without order";
    if (vendorId) {
      try {
        const v = await ctx.api(`/vendors/${vendorId}`, {}, 60000);
        placedOrder = { vendor_id: vendorId, vendor_label: v.city_name ? `${v.business_name} — ${v.city_name}` : v.business_name };
      } catch (_) {}
    }
    await renderWizard();
  }
  function openOfflineForVendor(vendorId) { return openOfflineWizard(vendorId); }
  function billedRateInputValue(l) {
    // billed_rate is null when the underlying buying_price is hidden (no
    // costs.read) and the biller hasn't typed one in yet — don't fall back to
    // Number(l.buying_price) here, since that's the masked "—" string and
    // renders as a bogus "NaN".
    if (l.billed_rate != null && Number.isFinite(Number(l.billed_rate))) return Number(l.billed_rate).toFixed(2);
    if (Number.isFinite(Number(l.buying_price))) return Number(l.buying_price).toFixed(2);
    return "";
  }
  function billedAmountInputValue(l) {
    if (l.billed_amount != null && Number.isFinite(Number(l.billed_amount))) return Number(l.billed_amount).toFixed(2);
    return "";
  }
  function productIdLabel(p) {
    const our = p?.our_product_id || "";
    const year = p?.year_group ? ` [${p.year_group}]` : "";
    const vid = p?.vendor_product_id;
    const base = vid ? `${our}${year} / (${vid})` : `${our}${year}`;
    return base;
  }
  function filterOfflineProducts() {
    const q = offlineProductSearch.trim().toLowerCase();
    if (!q) return wizardProducts;
    const scored = [];
    for (const p of wizardProducts) {
      const id = String(p.our_product_id || "").toLowerCase();
      const vid = String(p.vendor_product_id || "").toLowerCase();
      const cat = String(p.category || "").toLowerCase();
      let score = 0;
      if (id === q || vid === q) score = 100;
      else if (id.startsWith(q) || vid.startsWith(q)) score = 80;
      else if (id.includes(q) || vid.includes(q)) score = 40;
      else if (cat.startsWith(q)) score = 30;
      else if (cat.includes(q)) score = 10;
      else continue;
      scored.push({ p, score, id });
    }
    scored.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
    return scored.map(x => x.p);
  }
  function onOfflineProductSearch(val) {
    const prev = document.getElementById("stock-offline-product-search");
    const start = prev?.selectionStart;
    offlineProductSearch = val || "";
    Promise.resolve(renderWizard()).then(() => {
      const inp = document.getElementById("stock-offline-product-search");
      if (!inp) return;
      inp.focus();
      if (typeof start === "number") {
        try { inp.setSelectionRange(start, start); } catch (_) {}
      }
    });
  }
  function pickMode(mode) {
    if (mode === "manual") {
      wizardMode = "offline_vendor";
      wizardStep = 1;
      wizardVendorId = null;
      placedOrder = null;
      wizardProducts = [];
      wizardLines = [];
      offlineProductSearch = "";
      billFile = null;
      billFileKey = null;
      pendingDebitNotes = [];
      receiptMeta = { billNumber: "", orderReceiptNumber: "", additionalCharges: "", totalBilledAmount: "", billingPct: "", gstPct: "", notes: "", eventDate: localToday() };
      document.querySelector("#stock-wizard .modal-header h3").textContent = "Receive without order";
      renderWizard();
      return;
    }
    if (mode === "vendor_order") {
      wizardMode = "receive_goods";
      wizardStep = 1;
      wizardVendorId = null;
      placedOrder = null;
      wizardLines = [];
      billFile = null;
      billFileKey = null;
      pendingDebitNotes = [];
      enteredFromAddStock = true;
      receiptMeta = { billNumber: "", orderReceiptNumber: "", additionalCharges: "", totalBilledAmount: "", billingPct: "", gstPct: "", notes: "", eventDate: localToday() };
      document.querySelector("#stock-wizard .modal-header h3").textContent = "Receive Goods";
      renderWizard();
      return;
    }
    wizardMode = mode; wizardStep = 2; renderWizard();
  }
  function setStockWizardChrome(title, sub) {
    const t = document.getElementById("stock-wizard-title");
    const s = document.getElementById("stock-wizard-sub");
    if (t) t.textContent = title;
    if (s) s.textContent = sub;
  }
  function dnDisplayLabel(dn) {
    const dirLabels = {
      short: "Short delivery",
      extra: "Extra goods",
      over: "Bill overcharged",
      under: "Bill undercharged",
    };
    const dir = dn.direction || dn._direction;
    const dirLabel = dn._direction_label || dirLabels[dir] || "";
    // Value-type notes can be tied to one line (rate/amount mismatch on that item) or to
    // the whole bill (total mismatch, no product) — show the item when we have one, same
    // as item-type (qty mismatch) notes already do, instead of a bare "₹X" figure.
    const itemLabel = dn._label || (dn.our_product_id || dn.catalog_product_id ? productIdLabel(dn) : "");
    if (dirLabel) {
      if (dn.note_type === "item") return `${dirLabel}: ${itemLabel} × ${Math.abs(dn.quantity || 0)}`;
      const amt = fmtPrice(Math.abs(Number(dn.amount) || Number(dn._amount) || 0));
      return itemLabel ? `${dirLabel}: ${itemLabel} — ${amt}` : `${dirLabel}: ${amt}`;
    }
    if (dn.note_type === "item") return `${itemLabel} × ${dn.quantity}`;
    return itemLabel ? `Value adjustment: ${itemLabel}` : "Value adjustment";
  }
  /** Lines eligible for debit notes: received or billed > 0 */
  function billableLines() {
    return wizardLines.filter(l => (l.quantity_received || 0) > 0 || (l.quantity_billed || 0) > 0);
  }
  function wizardQtySum(field) {
    return wizardLines.reduce((s, l) => s + (Number(l[field]) || 0), 0);
  }
  function lineQtySum(lines, field) {
    return (lines || []).reduce((s, l) => s + (Number(l[field]) || 0), 0);
  }
  function refreshQtyFooter() {
    const billed = document.getElementById("stock-tfoot-billed");
    if (billed) billed.textContent = String(wizardQtySum("quantity_billed"));
    const recv = document.getElementById("stock-tfoot-received");
    if (recv) recv.textContent = String(wizardQtySum("quantity_received"));
    const pending = document.getElementById("stock-tfoot-pending");
    if (pending) pending.textContent = String(wizardQtySum("quantity_ordered"));
    const amt = document.getElementById("stock-tfoot-amount");
    if (amt) amt.textContent = fmtPrice(wizardQtySum("billed_amount"));
  }
  function receivedLines() {
    return wizardLines.filter(l => (l.quantity_received || 0) > 0);
  }
  function renderVendorBillingTermsCard() {
    if (!billingTerms) return "";
    const t = billingTerms;
    const isSplit = Number(t.billing_pct) < 100;
    const rows = [];
    rows.push(`<tr><td>Billing</td><td>${Number(t.billing_pct)}% of item value${isSplit ? " (split billing)" : ""}</td></tr>`);
    if (Number(t.discount_pct) > 0) rows.push(`<tr><td>Discount</td><td>${Number(t.discount_pct)}%</td></tr>`);
    if (Number(t.additional_charge) > 0) rows.push(`<tr><td>${ctx.esc(t.additional_charge_label || "Additional charge")}</td><td>+${fmtPrice(t.additional_charge)}</td></tr>`);
    rows.push(`<tr><td>GST</td><td>${t.gst_included ? `${Number(t.gst_rate_pct)}% included` : "Not included"}</td></tr>`);
    return `
      <div class="stock-bill-card" style="margin-bottom:12px;background:#f0f9ff;border:1px solid #bae6fd;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
          <span style="font-weight:600;font-size:14px;">Vendor billing terms</span>
        </div>
        ${t.billing_notes ? `<p style="font-size:13px;color:var(--muted);margin:0 0 8px;">${ctx.esc(t.billing_notes)}</p>` : ""}
        <table class="data" style="font-size:13px;margin:0;width:100%;"><tbody>${rows.join("")}</tbody></table>
      </div>`;
  }
  async function selectPendingReceipt(receiptId) {
    wizardReceiptId = receiptId;
    ctx.showLoading?.();
    try {
      const detail = await ctx.api(`/stock/receipts/${receiptId}/for-bill`, {}, 0);
      billingTerms = detail.billing_terms || null;
      placedOrder = detail;
      wizardLines = (detail.lines || []).map(l => {
        // buying_price is the masked "—" placeholder (see cost_visibility.hide_cost)
        // for staff without costs.read — Number("—")||0 used to silently seed a real,
        // submittable billed_amount of 0 for real goods received (the backend only
        // falls back to its own real buying_price when the client sends null, not an
        // explicit 0). Leave both null so the input renders blank and the biller must
        // type the vendor's paper rate/amount manually.
        const priceKnown = Number.isFinite(Number(l.buying_price));
        return {
          catalog_product_id: l.catalog_product_id,
          our_product_id: l.our_product_id,
          vendor_product_id: l.vendor_product_id || "",
          year_group: l.year_group || "",
          quantity_received: l.quantity_received,
          quantity_billed: l.quantity_received,
          billed_amount: priceKnown ? (Number(l.quantity_received) || 0) * Number(l.buying_price) : null,
          billed_rate: priceKnown ? l.buying_price : null,
          _priceHidden: !priceKnown,
          buying_price: l.buying_price,
          unit: l.unit,
          image_urls: l.image_urls || [],
        };
      });
      receiptMeta.totalBilledAmount = detail.expected_bill_amount || "";
      receiptMeta.billingPct = billingTerms ? String(Number(billingTerms.billing_pct)) : "";
      receiptMeta.gstPct = billingTerms ? String(Number(billingTerms.gst_rate_pct)) : "";
      billPreview = null;
      pendingDebitNotes = [];
    } catch (e) {
      ctx.toast(e.message, "error");
      wizardReceiptId = null;
    } finally { ctx.hideLoading?.(); }
    await renderWizard();
  }
  function changePendingReceipt() {
    wizardReceiptId = null;
    wizardLines = [];
    billingTerms = null;
    billPreview = null;
    pendingDebitNotes = [];
    renderWizard();
  }
  function billingPctOverridePayload() {
    const pct = parseFloat(receiptMeta.billingPct);
    return (pct > 0 && pct <= 100) ? { billing_pct_override: pct } : {};
  }
  function gstPctOverridePayload() {
    const pct = parseFloat(receiptMeta.gstPct);
    return (pct >= 0 && pct <= 100) ? { gst_rate_pct_override: pct } : {};
  }
  async function refreshBillPreview() {
    const total = parseFloat(receiptMeta.totalBilledAmount) || 0;
    try {
      const preview = await ctx.api(`/stock/receipts/${wizardReceiptId}/bill-preview`, {
        method: "POST",
        body: JSON.stringify({
          total_billed_amount: total,
          lines: wizardLines.map(l => ({
            catalog_product_id: l.catalog_product_id,
            quantity_billed: l.quantity_billed || 0,
            billed_amount: l.billed_amount != null ? l.billed_amount : null,
          })),
          ...billingPctOverridePayload(),
          ...gstPctOverridePayload(),
        }),
      }, 0);
      billPreview = preview;
      pendingDebitNotes = pendingDebitNotes.filter(dn => !dn._auto_suggested);
      for (const s of preview.suggested_debit_notes || []) {
        const amt = Number(s.amount) || 0;
        pendingDebitNotes.push({
          note_type: s.note_type,
          direction: s.direction,
          catalog_product_id: s.catalog_product_id,
          quantity: null,
          amount: amt,
          notes: s.notes,
          source: "auto",
          _auto_suggested: true,
          _label: s.our_product_id ? productIdLabel(s) : null,
          _amount: amt,
          _payable_effect: s.direction === "over" ? -amt : amt,
        });
      }
    } catch (e) { ctx.toast(e.message, "error"); }
  }
