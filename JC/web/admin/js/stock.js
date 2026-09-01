/** Stock — inventory, vendor order receipts */
const Stock = (() => {
  let ctx = {};
  let products = [];
  let viewMode = "grid";
  let wizardStep = 1;
  let wizardMode = null;
  let wizardVendorId = null;
  let placedOrder = null;
  let wizardLines = [];
  let billFile = null;
  let billFileKey = null;
  let pendingDebitNotes = [];
  let receiptMeta = { billNumber: "", orderReceiptNumber: "", additionalCharges: "", totalBilledAmount: "", notes: "", eventDate: "" };
  let wizardReceiptId = null; // selected pending-bill receipt (bill_received mode)
  let wizardPendingBillList = null; // { vendor_id, vendor_label, receipts } from /stock/vendor-order/{id}/received
  let billingTerms = null; // vendor's typed billing terms, loaded with the chosen receipt
  let billPreview = null; // { expected_bill_total, expected_extra_cash, suggested_debit_notes } from /bill-preview
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
  let editReceiptId = null;
  let editReceiptType = null; // vendor_receive | vendor_bill | offline_vendor | vendor_order
  const STOCK_COLS = [
    { key: "our_product_id", label: "Product ID", get: p => p.our_product_id },
    { key: "vendor", label: "Vendor", get: p => p.vendor_label || "" },
    { key: "qty", label: "On Hand", get: p => String(p.quantity_on_hand) },
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
  async function load() {
    // Live hub is Products — keep picker cache warm, then refresh hub
    try {
      products = await ctx.api("/stock/products", {}, 0);
    } catch (_) { products = []; }
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
      const ledgerRows = (p.ledger || []).length ? (p.ledger || []).map(e => `<tr class="clickable ledger-row" data-handler="stock" data-entry-id="${e.id}">
        <td style="font-size:12px;">${new Date(e.created_at).toLocaleString()}</td>
        <td><span class="badge badge-blue">${ctx.esc(e.entry_type)}</span></td>
        <td>${e.quantity_delta > 0 ? "+" : ""}${e.quantity_delta}</td>
        <td>${e.balance_after}</td>
        <td style="font-size:12px;color:var(--muted);">${ctx.esc(e.notes || "—")}</td>
      </tr>`).join("") : `<tr><td colspan="5" style="color:var(--muted);">No movements yet</td></tr>`;
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
              <span class="badge badge-gray">Pending order: ${p.quantity_pending}</span>
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
          ${ctx.reviewRow("Series", p.series || "—")}
          ${ctx.reviewRow("Unit", p.unit || "—")}
          ${ctx.reviewRow("Category", p.category || "—")}
        </div>
        <div style="margin-bottom:16px;"><strong style="font-size:13px;">Alternatives</strong><div style="margin-top:8px;">${altRows}</div></div>
        <div class="detail-section">
          <h4>Stock Ledger</h4>
          <table class="data history-table"><thead><tr>
            <th>Date</th><th>Type</th><th>Qty</th><th>Balance</th><th>Notes</th>
          </tr></thead><tbody>${ledgerRows}
          <tr style="opacity:0.5;"><td colspan="5" style="font-size:12px;font-style:italic;">Sales entries will appear here later</td></tr>
          </tbody></table>
        </div>`,
        `${ctx.canWrite?.("catalog") ? `<button class="btn btn-secondary btn-sm" onclick="Catalog.openEdit(${p.catalog_product_id}, 'stock')">Edit</button>` : ""}
         <button class="btn btn-secondary btn-sm" onclick="Catalog.openDetail(${p.catalog_product_id})">Catalog view</button>
         <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
        "lg"
      );
      ctx.bindLedgerRowClicks?.();
      document.getElementById("detail-body")?.querySelectorAll(".ledger-row[data-handler='stock']").forEach(row => {
        row.onclick = () => Stock.openLedgerDetail(parseInt(row.getAttribute("data-entry-id"), 10));
      });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  function openAddWizard() {
    wizardStep = 1; wizardMode = null; wizardVendorId = null; placedOrder = null;
    wizardLines = []; billFile = null; billFileKey = null; pendingDebitNotes = [];
    offlineVendorsCache = []; wizardProducts = []; // always fetch fresh on open
    enteredFromAddStock = true;
    receiptMeta = { billNumber: "", orderReceiptNumber: "", additionalCharges: "", totalBilledAmount: "", notes: "", eventDate: localToday() };
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
    receiptMeta = { billNumber: "", orderReceiptNumber: "", additionalCharges: "", totalBilledAmount: "", notes: "", eventDate: localToday() };
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
    receiptMeta = { billNumber: "", orderReceiptNumber: "", additionalCharges: "", totalBilledAmount: "", notes: "", eventDate: localToday() };
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
    receiptMeta = { billNumber: "", orderReceiptNumber: "", additionalCharges: "", totalBilledAmount: "", notes: "", eventDate: localToday() };
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
      const series = String(p.series || "").toLowerCase();
      let score = 0;
      if (id === q || vid === q) score = 100;
      else if (id.startsWith(q) || vid.startsWith(q)) score = 80;
      else if (id.includes(q) || vid.includes(q)) score = 40;
      else if (cat.startsWith(q) || series.startsWith(q)) score = 30;
      else if (cat.includes(q) || series.includes(q)) score = 10;
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
      receiptMeta = { billNumber: "", orderReceiptNumber: "", additionalCharges: "", totalBilledAmount: "", notes: "", eventDate: localToday() };
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
      receiptMeta = { billNumber: "", orderReceiptNumber: "", additionalCharges: "", totalBilledAmount: "", notes: "", eventDate: localToday() };
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
    if (dirLabel) {
      if (dn.note_type === "item") return `${dirLabel}: ${dn._label || ""} × ${Math.abs(dn.quantity || 0)}`;
      return `${dirLabel}: ${fmtPrice(Math.abs(Number(dn.amount) || Number(dn._amount) || 0))}`;
    }
    if (dn.note_type === "item") return `${dn._label || ""} × ${dn.quantity}`;
    return "Value adjustment";
  }
  /** Lines eligible for debit notes: received or billed > 0 */
  function billableLines() {
    return wizardLines.filter(l => (l.quantity_received || 0) > 0 || (l.quantity_billed || 0) > 0);
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
      wizardLines = (detail.lines || []).map(l => ({
        catalog_product_id: l.catalog_product_id,
        our_product_id: l.our_product_id,
        quantity_received: l.quantity_received,
        quantity_billed: l.quantity_received,
        buying_price: l.buying_price,
        unit: l.unit,
        image_urls: l.image_urls || [],
      }));
      receiptMeta.totalBilledAmount = detail.expected_bill_amount || "";
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
  async function refreshBillPreview() {
    const total = parseFloat(receiptMeta.totalBilledAmount) || 0;
    try {
      const preview = await ctx.api(`/stock/receipts/${wizardReceiptId}/bill-preview`, {
        method: "POST",
        body: JSON.stringify({
          total_billed_amount: total,
          lines: wizardLines.map(l => ({ catalog_product_id: l.catalog_product_id, quantity_billed: l.quantity_billed || 0 })),
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
  async function renderWizard() {
    const stepsEl = document.getElementById("stock-wizard-steps");
    const bodyEl = document.getElementById("stock-wizard-body");
    const footerEl = document.getElementById("stock-wizard-footer");
    if (!stepsEl || !bodyEl || !footerEl) return;
    const labels = wizardMode === "edit_receipt"
      ? ["Edit bill"]
      : wizardMode === "offline_vendor"
      ? ["Vendor", "Products", "Receipt", "Review"]
      : wizardMode === "receive_goods"
      ? ["Vendor", "Receive", "Review"]
      : wizardMode === "bill_received"
      ? ["Vendor", "Bill", "Debit Note", "Review"]
      : ["Source"];
    stepsEl.innerHTML = labels.map((lbl, i) => {
      const n = i + 1;
      const cls = n === wizardStep ? "step active" : n < wizardStep ? "step done" : "step";
      return `<div class="${cls}"><span class="step-num">${n < wizardStep ? "✓" : n}</span><span class="step-label">${lbl}</span></div>`;
    }).join("");
    if (wizardMode === "edit_receipt") {
      const isRecvEdit = editReceiptType === "vendor_receive";
      const isBillEdit = editReceiptType === "vendor_bill";
      setStockWizardChrome(
        isRecvEdit ? "Edit Receive" : "Edit Vendor Bill",
        `Receipt #${editReceiptId} — ${ctx.esc(placedOrder?.vendor_label || "")}`
      );
      const totals = calcReviewTotals(isBillEdit ? wizardLines.filter(l => (l.quantity_billed || 0) > 0) : billableLines());
      if (isRecvEdit) {
        bodyEl.innerHTML = `
          <div class="vo-wiz-step-head">
            <h4>Edit received quantities</h4>
            <p>Stock and open pending update on save. Cannot go below already-billed qty. Old PDF removed; history kept.</p>
          </div>
          <div class="stock-receive-table-wrap">
            <table class="data stock-receive-table"><thead><tr>
              <th>Product</th><th>Received</th>
            </tr></thead><tbody>
              ${wizardLines.map((l, i) => `<tr>
                <td><strong>${ctx.esc(productIdLabel(l))}</strong></td>
                <td><input type="number" min="0" class="input stock-qty-input" value="${l.quantity_received || ""}" onchange="Stock.setLine(${i},'quantity_received',this.value)" /></td>
              </tr>`).join("")}
            </tbody></table>
          </div>
          <div class="stock-bill-card" style="margin-top:16px;">
            <h4>Order receipt</h4>
            <div class="stock-bill-grid">
              <div><label class="label">Order receipt number *</label>
                <input class="input" id="stock-order-receipt-number" value="${ctx.esc(receiptMeta.orderReceiptNumber || "")}" required /></div>
              <div><label class="label">Replace file</label>
                <input type="file" class="input" accept=".pdf,image/*" onchange="Stock.setBillFile(this.files[0])" />
                ${billFile ? `<span class="stock-file-name">${ctx.esc(billFile.name)}</span>` : (billFileKey ? `<span class="stock-file-name">Current file kept</span>` : "")}
              </div>
              <div style="grid-column:1/-1;"><label class="label">Note</label>
                <input class="input" id="stock-receive-notes" value="${ctx.esc(receiptMeta.notes || "")}" /></div>
            </div>
          </div>`;
        footerEl.innerHTML = `
          <button class="btn btn-secondary" onclick="Stock.closeWizard()">Cancel</button>
          <button class="btn btn-primary btn-lg" onclick="Stock.submitReceipt()">Save changes</button>`;
        return;
      }
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>Edit ${isBillEdit ? "billed qty & bill" : "quantities & bill"}</h4>
          <p>${isBillEdit ? "AP, debit notes and unbilled received update on save." : "Stock, AP and debit notes update when you save."} Old PDF removed; history kept.</p>
        </div>
        <div class="stock-receive-table-wrap">
          <table class="data stock-receive-table"><thead><tr>
            <th>Product</th>${isBillEdit ? "" : "<th>Received</th>"}<th>Billed</th>
          </tr></thead><tbody>
            ${wizardLines.map((l, i) => `<tr>
              <td><strong>${ctx.esc(productIdLabel(l))}</strong></td>
              ${isBillEdit ? "" : `<td><input type="number" min="0" class="input stock-qty-input" value="${l.quantity_received || ""}" onchange="Stock.setLine(${i},'quantity_received',this.value)" /></td>`}
              <td><input type="number" min="0" class="input stock-qty-input stock-billed-input" value="${l.quantity_billed || ""}" onchange="Stock.setLine(${i},'quantity_billed',this.value)" /></td>
            </tr>`).join("")}
          </tbody></table>
        </div>
        <div class="stock-bill-card" style="margin-top:16px;">
          <h4>Vendor bill</h4>
          <div class="stock-bill-grid">
            <div><label class="label">Bill number</label><input class="input" id="stock-bill-number" value="${ctx.esc(receiptMeta.billNumber)}" /></div>
            <div class="stock-bill-total"><label class="label">Total bill amount *</label>
              <input type="number" min="0" step="0.01" class="input" id="stock-total-billed" value="${ctx.esc(receiptMeta.totalBilledAmount)}" required /></div>
            <div><label class="label">Replace bill file</label>
              <input type="file" class="input" accept=".pdf,image/*" onchange="Stock.setBillFile(this.files[0])" />
              ${billFile ? `<span class="stock-file-name">${ctx.esc(billFile.name)}</span>` : (billFileKey ? `<span class="stock-file-name">Current file kept</span>` : "")}
            </div>
          </div>
        </div>
        <div style="margin-top:16px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <strong>Debit notes</strong>
            <button type="button" class="btn btn-secondary btn-sm" onclick="Stock.openDebitNote()">+ Add / replace set</button>
          </div>
          ${pendingDebitNotes.length
            ? `<table class="data" style="font-size:13px;"><thead><tr><th>Note</th><th>Effect</th><th></th></tr></thead><tbody>
                ${pendingDebitNotes.map((dn, i) => `<tr>
                  <td>${ctx.esc(dnDisplayLabel(dn))}${dn.notes ? ` — ${ctx.esc(dn.notes)}` : ""}</td>
                  <td>${fmtPrice(dnPayableEffect(dn))}</td>
                  <td style="white-space:nowrap;">
                    <button type="button" class="btn btn-ghost btn-sm" onclick="Stock.editPendingDebitNote(${i})">Edit</button>
                    <button type="button" class="btn btn-ghost btn-sm" onclick="Stock.removeDebitNote(${i})">Remove</button>
                  </td>
                </tr>`).join("")}
              </tbody></table>`
            : `<p class="vo-muted" style="margin:0;">No debit notes on this bill.</p>`}
          <p class="vo-muted" style="margin:8px 0 0;font-size:12px;">Saving replaces all debit notes with the list above (AP updates automatically).</p>
        </div>
        <div class="review-block" style="margin-top:16px;">
          ${ctx.reviewRow("Bill amount", fmtPrice(totals.billAmount))}
          ${totals.dnAdj ? ctx.reviewRow("Debit note adj.", fmtPrice(totals.dnAdj)) : ""}
          ${ctx.reviewRow("Net payable", fmtPrice(totals.netPayable))}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.closeWizard()">Cancel</button>
        <button class="btn btn-primary btn-lg" onclick="Stock.submitReceipt()">Save changes</button>`;
      return;
    }
    if (wizardStep === 1 && (wizardMode === "receive_goods" || wizardMode === "bill_received")) {
      const isRecv = wizardMode === "receive_goods";
      setStockWizardChrome(isRecv ? "Receive Goods" : "Bill Order", "Step 1 — select vendor");
      if (!offlineVendorsCache.length) {
        try { offlineVendorsCache = (await ctx.api("/catalog/vendors", {}, 0) || []).map(v => ({ ...v, alias: v.alias || "" })); } catch (_) {
          try { offlineVendorsCache = (await ctx.api("/vendors", {}, 0) || []).map(v => ({ ...v, alias: v.alias || "" })); } catch (e2) {
            offlineVendorsCache = [];
            ctx.toast(e2.message, "error");
          }
        }
      }
      const active = offlineVendorsCache.filter(v => v.is_active !== false && !v.deleted_at);
      const q = offlineVendorSearch.trim();
      const filtered = OrdersUI.filterAndRankParties(active, offlineVendorSearch);
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>Select vendor</h4>
          <p>${isRecv ? "We’ll load placed lines yet to receive." : "We’ll load received lines yet to bill."}</p>
        </div>
        <div class="vo-wiz-search-wrap">
          <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
          <input id="stock-receive-vendor-search" class="input vo-wiz-search" type="search" placeholder="Search vendor name, alias, city, or phone…" value="${ctx.esc(offlineVendorSearch)}" oninput="Stock.onOfflineVendorSearch(this.value)" autocomplete="off" />
        </div>
        <div class="vo-wiz-vendor-list">
          ${filtered.length ? filtered.map(v => {
            const selected = wizardVendorId === v.id;
            const alias = (v.alias || "").trim();
            return `<button type="button" class="vo-wiz-vendor-card${selected ? " selected" : ""}" onclick="Stock.pickVendor(${v.id})">
              <span class="vo-wiz-vendor-letter">${ctx.esc((v.business_name || "?").slice(0, 1).toUpperCase())}</span>
              <span class="vo-wiz-vendor-meta">
                <strong>${ctx.esc(v.business_name || "Vendor")}</strong>
                ${alias ? `<span>${ctx.esc(alias)}</span>` : ""}
                <span>${ctx.esc(v.city_name || "No city")}</span>
              </span>
              <span class="vo-wiz-vendor-check">${selected ? "✓" : ""}</span>
            </button>`;
          }).join("") : HubUI.emptyState({ title: q ? "No matches" : "No vendors found", sub: q ? `No vendors match “${offlineVendorSearch}”.` : "Add vendors under People first." })}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.closeWizard()">Cancel</button>
        <button class="btn btn-primary" ${wizardVendorId ? "" : "disabled"} onclick="Stock.wizardNext()">${isRecv ? "Next: Receive →" : "Next: Bill →"}</button>`;
      setTimeout(() => {
        const inp = document.getElementById("stock-receive-vendor-search");
        if (!inp || document.activeElement === inp) return;
        inp.focus();
        const n = (offlineVendorSearch || "").length;
        try { inp.setSelectionRange(n, n); } catch (_) {}
      }, 30);
      return;
    }
    if (wizardStep === 1) {
      if (wizardMode === "offline_vendor") {
        setStockWizardChrome("Receive without order", "Step 1 — choose the vendor");
        if (!offlineVendorsCache.length) {
          try { offlineVendorsCache = (await ctx.api("/vendors", {}, 0) || []).map(v => ({ ...v, alias: v.alias || "" })); } catch (_) { offlineVendorsCache = []; }
        }
        const q = offlineVendorSearch.trim();
        const active = offlineVendorsCache.filter(v => v.is_active !== false && !v.deleted_at);
        const filtered = OrdersUI.filterAndRankParties(active, offlineVendorSearch);
        bodyEl.innerHTML = `
          <div class="vo-wiz-step-head">
            <h4>Select vendor</h4>
            <p>Goods already in godown — no prior place order. Stock now, bill later from Received.</p>
          </div>
          <div class="vo-wiz-search-wrap">
            <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
            <input id="stock-offline-vendor-search" class="input vo-wiz-search" type="search" placeholder="Search vendor name, alias, city, or phone…" value="${ctx.esc(offlineVendorSearch)}" oninput="Stock.onOfflineVendorSearch(this.value)" autocomplete="off" />
          </div>
          <div class="vo-wiz-vendor-list">
            ${filtered.length ? filtered.map(v => {
              const selected = wizardVendorId === v.id;
              const lbl = v.city_name ? `${v.business_name} — ${v.city_name}` : v.business_name;
              const alias = (v.alias || "").trim();
              return `<button type="button" class="vo-wiz-vendor-card${selected ? " selected" : ""}" onclick="Stock.pickVendor(${v.id})">
                <span class="vo-wiz-vendor-letter">${ctx.esc((v.business_name || "?").slice(0, 1).toUpperCase())}</span>
                <span class="vo-wiz-vendor-meta">
                  <strong>${ctx.esc(v.business_name || "Vendor")}</strong>
                  ${alias ? `<span>${ctx.esc(alias)}</span>` : ""}
                  <span>${ctx.esc(v.city_name || "No city")}</span>
                </span>
                <span class="vo-wiz-vendor-check">${selected ? "✓" : ""}</span>
              </button>`;
            }).join("") : HubUI.emptyState({ title: q ? "No matches" : "No vendors found", sub: q ? `No vendors match “${offlineVendorSearch}”.` : "Add vendors under People first." })}
          </div>`;
        footerEl.innerHTML = `
          <button class="btn btn-secondary" onclick="Stock.closeWizard()">Cancel</button>
          <button class="btn btn-primary" ${wizardVendorId ? "" : "disabled"} onclick="Stock.wizardNext()">Next: Products →</button>`;
        setTimeout(() => {
          const inp = document.getElementById("stock-offline-vendor-search");
          if (!inp || document.activeElement === inp) return;
          inp.focus();
          const n = (offlineVendorSearch || "").length;
          try { inp.setSelectionRange(n, n); } catch (_) {}
        }, 30);
        return;
      }
      setStockWizardChrome("Add Stock", "How did these goods arrive?");
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>Choose source</h4>
          <p>Pick the path that matches how you got the stock.</p>
        </div>
        <div class="stock-source-grid">
          <button type="button" class="create-order-card" onclick="Stock.pickMode('vendor_order')">
            <span class="create-order-letter">P</span>
            <span class="create-order-card-body">
              <strong>Against placed order</strong>
              <span>Receive goods for an order you already placed with a vendor</span>
            </span>
            <span class="create-order-arrow">→</span>
          </button>
          <button type="button" class="create-order-card create-order-card-alt" onclick="Stock.pickMode('manual')">
            <span class="create-order-letter alt">R</span>
            <span class="create-order-card-body">
              <strong>Receive without order</strong>
              <span>Ad-hoc goods in godown — stock now, bill later from Received</span>
            </span>
            <span class="create-order-arrow">→</span>
          </button>
        </div>`;
      footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.closeWizard()">Cancel</button>`;
      return;
    }
    if (wizardStep === 2 && wizardMode === "offline_vendor") {
      if (!wizardProducts.length) {
        ctx.showLoading?.();
        try { wizardProducts = await ctx.api(`/vendor-orders/vendor/${wizardVendorId}/products`, {}, 0); }
        catch (e) { ctx.toast(e.message, "error"); wizardStep = 1; return renderWizard(); }
        finally { ctx.hideLoading?.(); }
      }
      document.querySelector("#stock-wizard .stock-wiz-modal")?.classList.remove("stock-wiz-wide");
      offlineQtyPopupId = null;
      const shown = filterOfflineProducts();
      const selectedNotShown = wizardLines
        .map(l => wizardProducts.find(p => p.id === l.catalog_product_id))
        .filter(p => p && !shown.some(s => s.id === p.id));
      const list = [...selectedNotShown, ...shown];
      const cartHtml = wizardLines.length ? `
        <div class="vo-wiz-cart">
          <div class="vo-wiz-cart-head">
            <strong>Receiving now</strong>
            <span>${wizardLines.length} product${wizardLines.length === 1 ? "" : "s"} · ${wizardLines.reduce((s, l) => s + (l.quantity_received || 0), 0)} qty</span>
          </div>
          <div class="vo-wiz-cart-chips">
            ${wizardLines.map(l => {
              const p = wizardProducts.find(x => x.id === l.catalog_product_id);
              return `<span class="vo-wiz-cart-chip">
                <span>${ctx.esc(p ? productIdLabel(p) : l.our_product_id)} × ${l.quantity_received || 0}</span>
                <button type="button" title="Remove" onclick="Stock.toggleOfflineProduct(${l.catalog_product_id}, false)">×</button>
              </span>`;
            }).join("")}
          </div>
        </div>` : "";
      setStockWizardChrome("Receive without order", "Step 2 — search, tick products, set qty");
      const emptyCatalog = !wizardProducts.length;
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head vo-wiz-step-head-row">
          <div>
            <h4>Products from ${ctx.esc(placedOrder?.vendor_label || "vendor")}</h4>
            <p>${emptyCatalog ? "This vendor has no products in catalog." : `${wizardProducts.length} product${wizardProducts.length === 1 ? "" : "s"} available — same picker as place order.`}</p>
          </div>
          <div class="vo-wiz-count-pill">${wizardLines.length} selected</div>
        </div>
        ${cartHtml}
        <div class="vo-wiz-search-wrap">
          <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
          <input id="stock-offline-product-search" class="input vo-wiz-search" type="search" placeholder="Search product ID, vendor ID, category…" value="${ctx.esc(offlineProductSearch)}" oninput="Stock.onOfflineProductSearch(this.value)" autocomplete="off" />
          ${offlineProductSearch ? `<button type="button" class="vo-wiz-search-clear" onclick="Stock.onOfflineProductSearch('')">×</button>` : ""}
        </div>
        <div class="vo-wiz-product-meta">
          <span>Showing ${list.length} of ${wizardProducts.length}${offlineProductSearch ? " (search + selected)" : ""}</span>
        </div>
        <div class="vo-wiz-products">
          ${emptyCatalog ? HubUI.emptyState({ title: "No products yet", sub: "Add catalog products for this vendor first." })
            : list.length ? list.map(p => {
              const line = wizardLines.find(l => l.catalog_product_id === p.id);
              const qty = line ? (line.quantity_received || 1) : 1;
              const checked = !!line;
              const img = (p.image_urls && p.image_urls[0]) || "";
              return `<div class="vo-wiz-product ${checked ? "selected" : ""}" onclick="Stock.toggleOfflineProduct(${p.id}, ${checked ? "false" : "true"})">
                <div class="vo-wiz-product-main">
                  <input type="checkbox" ${checked ? "checked" : ""} onclick="event.stopPropagation();Stock.toggleOfflineProduct(${p.id}, this.checked)" />
                  ${thumb(img)}
                  <div class="vo-wiz-product-info">
                    <strong>${ctx.esc(productIdLabel(p))}</strong>
                    <span class="vo-wiz-product-sub">${p.category ? ctx.esc(p.category) : "Product"}${p.series ? ` · ${ctx.esc(p.series)}` : ""}</span>
                    <span class="vo-wiz-product-price">${fmtPrice(p.buying_price)}</span>
                  </div>
                </div>
                <div class="vo-wiz-qty" onclick="event.stopPropagation()">
                  <label>Qty</label>
                  <div class="vo-wiz-qty-controls">
                    <button type="button" class="vo-wiz-qty-btn" ${checked ? "" : "disabled"} onclick="Stock.bumpOfflineQty(${p.id}, -1)">−</button>
                    <input type="number" min="1" class="input vo-wiz-qty-input" value="${qty}" ${checked ? "" : "disabled"} onchange="Stock.setOfflineLine(${p.id},'quantity_received',this.value)" onclick="event.stopPropagation()" />
                    <button type="button" class="vo-wiz-qty-btn" ${checked ? "" : "disabled"} onclick="Stock.bumpOfflineQty(${p.id}, 1)">+</button>
                  </div>
                </div>
              </div>`;
            }).join("") : HubUI.emptyState({
              title: "No matches",
              sub: `No products match “${offlineProductSearch}”.`,
              ctaHtml: `<button type="button" class="btn btn-secondary" onclick="Stock.onOfflineProductSearch('')">Clear search</button>`,
            })}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
        <div class="vo-wiz-footer-mid">${wizardLines.length ? `${wizardLines.length} item${wizardLines.length === 1 ? "" : "s"} selected` : "Select at least one product"}</div>
        <button class="btn btn-primary" ${wizardLines.some(l => (l.quantity_received || 0) > 0) ? "" : "disabled"} onclick="Stock.wizardNext()">Next: Receipt →</button>`;
      setTimeout(() => document.getElementById("stock-offline-product-search")?.focus(), 30);
      return;
    }
    if (wizardStep === 3 && wizardMode === "offline_vendor") {
      document.querySelector("#stock-wizard .stock-wiz-modal")?.classList.remove("stock-wiz-wide");
      offlineQtyPopupId = null;
      setStockWizardChrome("Receive without order", "Step 3 — order receipt details");
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>${ctx.esc(placedOrder?.vendor_label || "Receive without order")}</h4>
          <p>${wizardLines.length} product${wizardLines.length === 1 ? "" : "s"} selected · enter receipt details next.</p>
        </div>
        <div class="table-wrap" style="max-height:28vh;overflow-y:auto;margin-bottom:16px;">
          <table class="data" style="font-size:13px;"><thead><tr><th>Product</th><th>Received</th></tr></thead><tbody>
            ${wizardLines.map(l => {
              const p = wizardProducts.find(x => x.id === l.catalog_product_id);
              return `<tr><td>${ctx.esc(p ? productIdLabel(p) : l.our_product_id)}</td><td>${l.quantity_received || 0}</td></tr>`;
            }).join("")}
          </tbody></table>
        </div>
        <div class="stock-bill-card">
          <h4>Order receipt</h4>
          <div class="stock-bill-grid">
            <div><label class="label">Order receipt number *</label>
              <input class="input" id="stock-order-receipt-number" value="${ctx.esc(receiptMeta.orderReceiptNumber || "")}" placeholder="Challan / delivery note #" required /></div>
            <div><label class="label">Receive date</label>
              <input type="date" class="input" id="stock-event-date" value="${ctx.esc(receiptMeta.eventDate || localToday())}" /></div>
            <div><label class="label">Upload receipt (optional)</label>
              <input type="file" class="input" accept=".pdf,image/*" onchange="Stock.setBillFile(this.files[0])" />
              ${billFile ? `<span class="stock-file-name">${ctx.esc(billFile.name)}</span>` : ""}
            </div>
            <div style="grid-column:1/-1;"><label class="label">Note</label>
              <input class="input" id="stock-receive-notes" value="${ctx.esc(receiptMeta.notes || "")}" placeholder="Optional note" /></div>
          </div>
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
        <button class="btn btn-primary" onclick="Stock.wizardNext()">Review →</button>`;
      setTimeout(() => document.getElementById("stock-order-receipt-number")?.focus(), 30);
      return;
    }
    if (wizardStep === 2 && wizardMode === "receive_goods") {
      if (!placedOrder) {
        bodyEl.innerHTML = HubUI.emptyState({ title: "Loading…", sub: "Loading placed order…" });
        footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>`;
        ctx.showLoading?.();
        try {
          placedOrder = await ctx.api(`/stock/vendor-order/${wizardVendorId}/placed`, {}, 0);
          wizardLines = (placedOrder.lines || []).map(l => ({
            catalog_product_id: l.catalog_product_id,
            our_product_id: l.our_product_id,
            vendor_product_id: l.vendor_product_id || "",
            category: l.category || "",
            quantity_ordered: l.quantity_remaining,
            buying_price: l.buying_price,
            unit: l.unit,
            image_urls: l.image_urls,
            quantity_received: 0,
            quantity_billed: 0,
          }));
          if (receivePrefill?.catalog_product_id) {
            const qty = Math.max(1, parseInt(String(receivePrefill.quantity || receivePrefill.pending_qty || 1), 10) || 1);
            const match = wizardLines.find(l => l.catalog_product_id === receivePrefill.catalog_product_id);
            if (match) {
              match.quantity_received = Math.min(qty, match.quantity_ordered || qty);
              wizardLines = [match];
            }
            receivePrefill = null;
          }
        } catch (e) { ctx.toast(e.message, "error"); wizardStep = 1; return renderWizard(); }
        finally { ctx.hideLoading?.(); }
      }
      if (!wizardLines.length) {
        setStockWizardChrome("Receive Goods", "Nothing pending");
        bodyEl.innerHTML = HubUI.emptyState({ title: "Nothing to receive", sub: "No placed lines yet to receive for this vendor." });
        footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>`;
        return;
      }
      setStockWizardChrome("Receive Goods", "Step 2 — enter received quantities");
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>${ctx.esc(placedOrder.vendor_label)}</h4>
          <p>Enter qty received. Order receipt number is required. File/note optional. Bill later from Received.</p>
        </div>
        <div class="stock-receive-table-wrap">
          <table class="data stock-receive-table"><thead><tr>
            <th></th><th>Product</th><th>Category</th><th>Pending</th><th>Price</th><th>Received</th>
          </tr></thead><tbody>
            ${wizardLines.map((l, i) => {
              const img = (l.image_urls && l.image_urls[0]) || "";
              return `<tr>
                <td>${thumb(img)}</td>
                <td><strong>${ctx.esc(productIdLabel(l))}</strong></td>
                <td>${ctx.esc(l.category || "—")}</td>
                <td>${l.quantity_ordered}</td>
                <td>${fmtPrice(l.buying_price)}</td>
                <td><input type="number" min="0" class="input stock-qty-input" value="${l.quantity_received || ""}" onchange="Stock.setLine(${i},'quantity_received',this.value)" /></td>
              </tr>`;
            }).join("")}
          </tbody></table>
        </div>
        <div class="stock-bill-card" style="margin-top:16px;">
          <h4>Order receipt</h4>
          <div class="stock-bill-grid">
            <div><label class="label">Order receipt number *</label>
              <input class="input" id="stock-order-receipt-number" value="${ctx.esc(receiptMeta.orderReceiptNumber || "")}" placeholder="Challan / delivery note #" required /></div>
            <div><label class="label">Receive date</label>
              <input type="date" class="input" id="stock-event-date" value="${ctx.esc(receiptMeta.eventDate || localToday())}" /></div>
            <div><label class="label">Upload receipt (optional)</label>
              <input type="file" class="input" accept=".pdf,image/*" onchange="Stock.setBillFile(this.files[0])" />
              ${billFile ? `<span class="stock-file-name">${ctx.esc(billFile.name)}</span>` : ""}
            </div>
            <div style="grid-column:1/-1;"><label class="label">Note</label>
              <input class="input" id="stock-receive-notes" value="${ctx.esc(receiptMeta.notes || "")}" placeholder="Optional note" /></div>
          </div>
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
        <button class="btn btn-primary" onclick="Stock.wizardNext()">Review →</button>`;
      return;
    }
    if (wizardStep === 2 && wizardMode === "bill_received" && !wizardReceiptId) {
      if (!wizardPendingBillList) {
        bodyEl.innerHTML = HubUI.emptyState({ title: "Loading…", sub: "Loading pending receipts…" });
        footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>`;
        ctx.showLoading?.();
        try { wizardPendingBillList = await ctx.api(`/stock/vendor-order/${wizardVendorId}/received`, {}, 0); }
        catch (e) { ctx.toast(e.message, "error"); wizardStep = 1; return renderWizard(); }
        finally { ctx.hideLoading?.(); }
      }
      const receipts = wizardPendingBillList.receipts || [];
      setStockWizardChrome("Bill Order", "Step 2 — pick a receipt to bill");
      if (!receipts.length) {
        bodyEl.innerHTML = HubUI.emptyState({ title: "Nothing to bill", sub: "No pending receipts for this vendor." });
        footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>`;
        return;
      }
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>${ctx.esc(wizardPendingBillList.vendor_label)}</h4>
          <p>${receipts.length} receipt${receipts.length === 1 ? "" : "s"} pending bill. One bill per receipt.</p>
        </div>
        <div class="vo-wiz-vendor-list">
          ${receipts.map(r => `
            <button type="button" class="vo-wiz-vendor-card" onclick="Stock.selectPendingReceipt(${r.receipt_id})">
              <span class="vo-wiz-vendor-letter">#${r.receipt_id}</span>
              <span class="vo-wiz-vendor-meta">
                <strong>${ctx.esc(r.order_receipt_number || `Receipt #${r.receipt_id}`)}</strong>
                <span>${new Date(r.received_at).toLocaleDateString()} · ${r.line_count} line${r.line_count === 1 ? "" : "s"} · ${r.total_quantity} qty</span>
              </span>
              <span class="vo-wiz-vendor-meta" style="text-align:right;">
                <strong>${r.expected_bill_amount != null ? fmtPrice(r.expected_bill_amount) : "—"}</strong>
                ${r.expected_extra_cash ? `<span>+ ${fmtPrice(r.expected_extra_cash)} extra cash</span>` : ""}
              </span>
            </button>`).join("")}
        </div>`;
      footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>`;
      return;
    }
    if (wizardStep === 2 && wizardMode === "bill_received" && wizardReceiptId) {
      if (!wizardLines.length) {
        setStockWizardChrome("Bill Order", "Nothing to bill");
        bodyEl.innerHTML = HubUI.emptyState({ title: "Nothing to bill", sub: "This receipt has no lines." });
        footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.changePendingReceipt()">← Choose different receipt</button>`;
        return;
      }
      setStockWizardChrome("Bill Order", "Step 2 — enter billed quantities & bill total");
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>${ctx.esc(placedOrder.vendor_label)} — receipt #${placedOrder.receipt_id}${placedOrder.order_receipt_number ? ` (${ctx.esc(placedOrder.order_receipt_number)})` : ""}</h4>
          <p>Billed qty defaults to received — edit if the vendor's bill differs. Total bill amount defaults to the calculated expectation — edit to match the paper invoice.</p>
        </div>
        <div class="stock-receive-table-wrap">
          <table class="data stock-receive-table"><thead><tr>
            <th></th><th>Product</th><th style="text-align:right;">Received</th><th style="text-align:right;">Price</th><th style="text-align:right;">Billed qty</th>
          </tr></thead><tbody>
            ${wizardLines.map((l, i) => {
              const img = (l.image_urls && l.image_urls[0]) || "";
              const diff = (l.quantity_billed || 0) - (l.quantity_received || 0);
              const diffBadge = diff !== 0
                ? `<span class="badge ${diff > 0 ? "badge-amber" : "badge-blue"}" style="font-size:10px;margin-left:4px;">${diff > 0 ? "+" : ""}${diff}</span>`
                : "";
              return `<tr>
                <td>${thumb(img)}</td>
                <td><strong>${ctx.esc(productIdLabel(l))}</strong>${diffBadge}</td>
                <td style="text-align:right;color:var(--muted);">${l.quantity_received || 0}</td>
                <td style="text-align:right;">${fmtPrice(l.buying_price)}</td>
                <td style="text-align:right;"><input type="number" min="0" class="input stock-qty-input stock-billed-input" value="${l.quantity_billed ?? ""}" onchange="Stock.setLine(${i},'quantity_billed',this.value)" /></td>
              </tr>`;
            }).join("")}
          </tbody></table>
        </div>
        ${renderVendorBillingTermsCard()}
        <div class="stock-bill-card">
          <h4>Vendor bill</h4>
          <div class="stock-bill-grid">
            <div><label class="label">Bill number</label><input class="input" id="stock-bill-number" value="${ctx.esc(receiptMeta.billNumber)}" placeholder="Vendor bill #" /></div>
            <div><label class="label">Bill date</label>
              <input type="date" class="input" id="stock-event-date" value="${ctx.esc(receiptMeta.eventDate || localToday())}" /></div>
            <div class="stock-bill-total"><label class="label">Total bill amount *</label>
              <input type="number" min="0" step="0.01" class="input" id="stock-total-billed" value="${ctx.esc(receiptMeta.totalBilledAmount)}" placeholder="₹ total on vendor bill" required /></div>
            <div><label class="label">Upload bill</label>
              <input type="file" class="input" accept=".pdf,image/*" onchange="Stock.setBillFile(this.files[0])" />
              ${billFile ? `<span class="stock-file-name">${ctx.esc(billFile.name)}</span>` : ""}
            </div>
            <div style="grid-column:1/-1;"><label class="label">Note</label>
              <input class="input" id="stock-receive-notes" value="${ctx.esc(receiptMeta.notes || "")}" placeholder="Optional note" /></div>
          </div>
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.changePendingReceipt()">← Choose different receipt</button>
        <button class="btn btn-primary" onclick="Stock.wizardNext()">Debit Notes →</button>`;
      return;
    }
    if ((wizardStep === 3 && wizardMode === "receive_goods")
      || (wizardStep === 4 && wizardMode === "offline_vendor")) {
      document.querySelector("#stock-wizard .stock-wiz-modal")?.classList.remove("stock-wiz-wide");
      saveReceiptMeta();
      const active = receivedLines();
      const vendorLabel = placedOrder?.vendor_label
        || (wizardMode === "offline_vendor" ? "Receive without order" : "");
      setStockWizardChrome("Review & Submit", wizardMode === "offline_vendor"
        ? "Confirm receive — stock now, bill later"
        : "Confirm goods received");
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>${ctx.esc(vendorLabel)}</h4>
          <p>Stock will increase. No AP yet — bill from Received when ready.</p>
        </div>
        <div class="review-block" style="margin-bottom:12px;">
          ${ctx.reviewRow("Order receipt #", receiptMeta.orderReceiptNumber || "—")}
          ${ctx.reviewRow("Receive date", receiptMeta.eventDate || localToday())}
          ${receiptMeta.notes ? ctx.reviewRow("Note", receiptMeta.notes) : ""}
        </div>
        <table class="data" style="font-size:13px;"><thead><tr><th>Product</th><th>Received</th></tr></thead><tbody>
          ${active.map(l => {
            const p = wizardProducts.find(x => x.id === l.catalog_product_id);
            const id = p ? productIdLabel(p) : (l.our_product_id || l.catalog_product_id);
            return `<tr><td>${ctx.esc(id)}</td><td>${l.quantity_received || 0}</td></tr>`;
          }).join("")}
        </tbody></table>
        ${billFile ? `<p class="vo-muted">Receipt file: ${ctx.esc(billFile.name)}</p>` : ""}`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
        <button class="btn btn-primary btn-lg" onclick="Stock.submitReceipt()">Confirm receive</button>`;
      return;
    }
    if (wizardStep === 3 && wizardMode === "bill_received") {
      setStockWizardChrome("Debit Notes", "Auto-suggested based on billed vs received");
      if (!billPreview) await refreshBillPreview();
      renderDebitNoteStep(bodyEl, footerEl);
      return;
    }
    if (wizardStep === 4 && wizardMode === "bill_received") {
      setStockWizardChrome("Review & Submit", "Confirm bill");
      renderReviewStep(bodyEl, footerEl);
      return;
    }
  }
  function saveReceiptMeta() {
    // Only overwrite fields when their inputs exist — review step has none,
    // so a blanket read was wiping total bill amount before submit.
    const billEl = document.getElementById("stock-bill-number");
    if (billEl) receiptMeta.billNumber = (billEl.value || "").trim();
    const totalEl = document.getElementById("stock-total-billed");
    if (totalEl && totalEl.tagName === "INPUT") receiptMeta.totalBilledAmount = totalEl.value || "";
    const ornEl = document.getElementById("stock-order-receipt-number");
    if (ornEl) receiptMeta.orderReceiptNumber = (ornEl.value || "").trim();
    const notesEl = document.getElementById("stock-receive-notes");
    if (notesEl) receiptMeta.notes = (notesEl.value || "").trim();
    const dateEl = document.getElementById("stock-event-date");
    if (dateEl) receiptMeta.eventDate = (dateEl.value || "").trim() || localToday();
  }
  function calcReviewTotals(active) {
    const billAmount = parseFloat(receiptMeta.totalBilledAmount) || 0;
    const dnAdj = pendingDebitNotes.reduce((s, dn) => s + dnPayableEffect(dn), 0);
    const netPayable = billAmount + dnAdj;
    return { billAmount, charges: 0, dnAdj, netPayable };
  }
  function renderDebitNoteStep(bodyEl, footerEl) {
    const billable = billableLines();
    const dnRows = pendingDebitNotes.map((dn, i) => {
      const amt = dnPayableEffect(dn);
      const payLess = amt < 0;
      const comment = dn.notes ? `<div class="dn-row-note">${ctx.esc(dn.notes)}</div>` : "";
      const autoTag = dn._auto_suggested
        ? `<span class="badge badge-blue" style="font-size:10px;margin-left:6px;">auto</span>`
        : "";
      return `<tr>
        <td>
          <strong>${ctx.esc(dnDisplayLabel(dn))}</strong>${autoTag}
          ${comment}
        </td>
        <td><span class="dn-effect-pill ${payLess ? "is-less" : "is-more"}">${payLess ? "Pay less" : "Pay more"} ${fmtPrice(Math.abs(amt))}</span></td>
        <td style="white-space:nowrap;">
          <button class="btn btn-ghost btn-sm" onclick="Stock.editPendingDebitNote(${i})">Edit</button>
          <button class="btn btn-ghost btn-sm" onclick="Stock.removeDebitNote(${i})">✕</button>
        </td>
      </tr>`;
    }).join("");
    const billDisplayAmt = parseFloat(receiptMeta.totalBilledAmount) || 0;
    bodyEl.innerHTML = `
      <div class="vo-wiz-step-head vo-wiz-step-head-row">
        <div>
          <h4>Debit notes</h4>
          <p>Auto-suggested when billed qty ≠ received qty. Edit or remove, or add more.</p>
        </div>
        <button class="btn btn-primary btn-sm" onclick="Stock.openDebitNote()" ${billable.length ? "" : "disabled"}>+ Add</button>
      </div>
      ${!billable.length ? HubUI.emptyState({ title: "No lines yet", sub: "Go back and enter quantities first." }) : ""}
      ${pendingDebitNotes.length
        ? `<div class="stock-dn-table-wrap"><table class="data"><thead><tr><th>Note</th><th>Payable effect</th><th></th></tr></thead><tbody>${dnRows}</tbody></table></div>`
        : HubUI.emptyState({ title: "No debit notes", sub: "All billed quantities match received." })}
      <div class="stock-dn-summary">
        ${ctx.reviewRow("Lines on bill", String(billable.length))}
        ${ctx.reviewRow("Bill document total", fmtPrice(billDisplayAmt))}
      </div>`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
      <button class="btn btn-primary" onclick="Stock.wizardNext()">Review →</button>`;
  }
  function renderReviewStep(bodyEl, footerEl) {
    const active = billableLines();
    const dnAdj = pendingDebitNotes.reduce((s, dn) => s + dnPayableEffect(dn), 0);
    const dnRows = pendingDebitNotes.map((dn) => {
      const amt = dnPayableEffect(dn);
      const payLess = amt < 0;
      const comment = dn.notes ? ` — ${ctx.esc(dn.notes)}` : "";
      const autoTag = dn._auto_suggested ? ` <span class="badge badge-blue" style="font-size:10px;">auto</span>` : "";
      return `<tr>
        <td>${ctx.esc(dnDisplayLabel(dn))}${autoTag}${comment}</td>
        <td><span class="dn-effect-pill ${payLess ? "is-less" : "is-more"}">${payLess ? "Pay less" : "Pay more"} ${fmtPrice(Math.abs(amt))}</span></td>
      </tr>`;
    }).join("");
    const billAmt = parseFloat(receiptMeta.totalBilledAmount) || 0;
    const extraCash = billPreview?.expected_extra_cash ? Number(billPreview.expected_extra_cash) : 0;
    const billNum = receiptMeta.billNumber || "—";
    const apSection = `
      <h4 style="margin:0 0 8px;font-size:15px;">AP entries (accounts payable)</h4>
      <div class="stock-dn-table-wrap" style="margin-bottom:16px;">
        <table class="data" style="font-size:13px;"><thead><tr><th>Entry</th><th>Amount</th></tr></thead><tbody>
          <tr>
            <td>Entry 1 — bill ${ctx.esc(billNum)} document total</td>
            <td style="font-weight:600;">${fmtPrice(billAmt)}</td>
          </tr>
          ${extraCash > 0 ? `<tr>
            <td>Entry 2 — extra cash (half-price balance, no GST)</td>
            <td style="font-weight:600;">${fmtPrice(extraCash)}</td>
          </tr>
          <tr style="border-top:2px solid var(--border);">
            <td style="font-weight:700;color:var(--primary);">Total AP (before debit notes)</td>
            <td style="font-weight:700;color:var(--primary);">${fmtPrice(billAmt + extraCash)}</td>
          </tr>` : ""}
          ${dnAdj ? `<tr>
            <td>Debit note adjustment</td>
            <td style="font-weight:600;">${fmtPrice(dnAdj)}</td>
          </tr>
          <tr style="border-top:2px solid var(--border);">
            <td style="font-weight:700;color:var(--primary);">Net payable</td>
            <td style="font-weight:700;color:var(--primary);">${fmtPrice(billAmt + extraCash + dnAdj)}</td>
          </tr>` : ""}
        </tbody></table>
      </div>`;
    bodyEl.innerHTML = `
      <div class="vo-wiz-review-hero">
        <span class="vo-wiz-review-label">Billing from</span>
        <strong>${ctx.esc(placedOrder?.vendor_label || "—")}</strong>
        <span class="vo-wiz-review-stats">${active.length} line${active.length === 1 ? "" : "s"}</span>
      </div>
      <div class="review-block" style="margin-bottom:16px;">
        ${ctx.reviewRow("Bill number", receiptMeta.billNumber || "—")}
        ${ctx.reviewRow("Bill date", receiptMeta.eventDate || localToday())}
      </div>
      <div class="stock-dn-table-wrap" style="margin-bottom:16px;">
        <table class="data"><thead><tr>
          <th>Product</th><th style="text-align:right;">Received</th><th style="text-align:right;">Billed</th><th style="text-align:right;">Diff</th>
        </tr></thead><tbody>
          ${active.map(l => {
            const diff = (l.quantity_billed || 0) - (l.quantity_received || 0);
            const diffCell = diff !== 0
              ? `<span class="badge ${diff > 0 ? "badge-amber" : "badge-blue"}" style="font-size:10px;">${diff > 0 ? "+" : ""}${diff}</span>`
              : `<span style="color:var(--muted);">—</span>`;
            return `<tr>
              <td><strong>${ctx.esc(productIdLabel(l))}</strong>${!(l.quantity_received || 0) && (l.quantity_billed || 0) ? ` <span class="badge badge-amber" style="font-size:10px;">Billed only</span>` : ""}</td>
              <td style="text-align:right;">${l.quantity_received || 0}</td>
              <td style="text-align:right;">${l.quantity_billed || 0}</td>
              <td style="text-align:right;">${diffCell}</td>
            </tr>`;
          }).join("")}
        </tbody></table>
      </div>
      ${apSection}
      ${pendingDebitNotes.length
        ? `<h4 style="margin:0 0 8px;font-size:15px;">Debit notes</h4>
           <div class="stock-dn-table-wrap"><table class="data"><thead><tr><th>Note</th><th>Effect</th></tr></thead><tbody>${dnRows}</tbody></table></div>`
        : ""}`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
      <button class="btn btn-primary btn-lg" onclick="Stock.submitReceipt()">Submit Bill</button>`;
  }
  function openDebitNote() {
    const active = billableLines();
    if (!active.length) return ctx.toast("Enter received or billed quantities first", "error");
    DebitNotes.openCreate({
      vendorId: wizardVendorId,
      receiptId: null,
      receivingLines: active.map(l => ({
        catalog_product_id: l.catalog_product_id,
        our_product_id: l.our_product_id,
        vendor_product_id: l.vendor_product_id,
        buying_price: l.buying_price || placedOrder?.lines?.find(x => x.catalog_product_id === l.catalog_product_id)?.buying_price,
        quantity_received: l.quantity_received || 0,
        quantity_billed: l.quantity_billed || 0,
      })),
      onDone: (payload) => {
        if (!payload) return;
        const line = active.find(l => l.catalog_product_id === payload.catalog_product_id);
        const price = Number(line?.buying_price || 0);
        const amt = payload.note_type === "item" ? price * payload.quantity : Number(payload.amount) || 0;
        pendingDebitNotes.push({
          ...payload,
          direction: payload.direction,
          _direction: payload.direction,
          _direction_label: payload._direction_label,
          _label: productIdLabel(line),
          _amount: Math.abs(amt),
          _payable_effect: payload.note_type === "item" ? -amt : amt,
        });
        renderWizard();
      },
    });
  }
  function removeDebitNote(idx) {
    pendingDebitNotes.splice(idx, 1);
    renderWizard();
  }
  function editPendingDebitNote(idx) {
    const active = billableLines();
    const existing = pendingDebitNotes[idx];
    if (!existing) return;
    DebitNotes.openCreate({
      vendorId: wizardVendorId,
      receiptId: null,
      receivingLines: active.map(l => ({
        catalog_product_id: l.catalog_product_id,
        our_product_id: l.our_product_id,
        vendor_product_id: l.vendor_product_id,
        buying_price: l.buying_price || placedOrder?.lines?.find(x => x.catalog_product_id === l.catalog_product_id)?.buying_price,
        quantity_received: l.quantity_received || 0,
        quantity_billed: l.quantity_billed || 0,
      })),
      prefill: existing,
      editIndex: idx,
      onDone: (payload, i) => {
        if (!payload) return;
        const line = active.find(l => l.catalog_product_id === payload.catalog_product_id);
        const price = Number(line?.buying_price || 0);
        const amt = payload.note_type === "item" ? price * payload.quantity : Number(payload.amount) || 0;
        // Full replace (not merge) — drops _auto_suggested/source:"auto" so a hand-edited
        // suggestion survives the next bill-preview refresh instead of being wiped and re-added.
        pendingDebitNotes[i] = {
          ...payload,
          direction: payload.direction,
          _direction: payload.direction,
          _direction_label: payload._direction_label,
          _label: (line ? productIdLabel(line) : null) || existing._label,
          _amount: Math.abs(amt),
          _payable_effect: payload.note_type === "item" ? -amt : amt,
        };
        renderWizard();
      },
    });
  }
  function openOfflineQtyPopup(productId) {
    offlineQtyPopupId = productId;
    renderWizard();
  }
  function closeOfflineQtyPopup() {
    offlineQtyPopupId = null;
    renderWizard();
  }
  function confirmOfflineQty() {
    const productId = offlineQtyPopupId;
    if (productId == null) return;
    const raw = document.getElementById("stock-offline-qty-input")?.value;
    const qty = Math.max(1, parseInt(String(raw || "1"), 10) || 1);
    const prod = wizardProducts.find(p => p.id === productId);
    let line = wizardLines.find(l => l.catalog_product_id === productId);
    if (!line) {
      line = {
        catalog_product_id: productId,
        our_product_id: prod?.our_product_id || "",
        vendor_product_id: prod?.vendor_product_id || "",
        buying_price: prod?.buying_price,
        image_urls: prod?.image_urls,
        quantity_received: qty,
        quantity_billed: 0,
      };
      wizardLines.push(line);
    } else {
      line.quantity_received = qty;
    }
    offlineQtyPopupId = null;
    renderWizard();
  }
  function removeOfflineLine(productId) {
    wizardLines = wizardLines.filter(l => l.catalog_product_id !== productId);
    if (offlineQtyPopupId === productId) offlineQtyPopupId = null;
    renderWizard();
  }
  function bumpOfflineQty(productId, delta) {
    const line = wizardLines.find(l => l.catalog_product_id === productId);
    if (!line) return;
    line.quantity_received = Math.max(1, (parseInt(String(line.quantity_received || 1), 10) || 1) + delta);
    renderWizard();
  }
  function toggleOfflineProduct(productId, checked) {
    if (!checked) {
      removeOfflineLine(productId);
      return;
    }
    const prod = wizardProducts.find(p => p.id === productId);
    if (!prod) return;
    let line = wizardLines.find(l => l.catalog_product_id === productId);
    if (!line) {
      wizardLines.push({
        catalog_product_id: productId,
        our_product_id: prod.our_product_id || "",
        vendor_product_id: prod.vendor_product_id || "",
        buying_price: prod.buying_price,
        image_urls: prod.image_urls,
        quantity_received: 1,
        quantity_billed: 0,
      });
    }
    renderWizard();
  }
  function onOfflineVendorSearch(val) {
    const prev = document.getElementById("stock-offline-vendor-search")
      || document.getElementById("stock-receive-vendor-search");
    const start = prev?.selectionStart;
    offlineVendorSearch = val || "";
    Promise.resolve(renderWizard()).then(() => {
      const inp = document.getElementById("stock-offline-vendor-search")
        || document.getElementById("stock-receive-vendor-search");
      if (!inp) return;
      inp.focus();
      const pos = typeof start === "number" ? start : (offlineVendorSearch || "").length;
      try { inp.setSelectionRange(pos, pos); } catch (_) {}
    });
  }
  function setOfflineLine(productId, field, raw) {
    const line = wizardLines.find(l => l.catalog_product_id === productId);
    if (!line) return;
    const n = Math.max(1, parseInt(String(raw || "1"), 10) || 1);
    line[field] = n;
  }
  function pickVendor(id) {
    wizardVendorId = id || null;
    placedOrder = null;
    wizardLines = [];
    wizardProducts = [];
    if (wizardMode === "bill_received") {
      wizardReceiptId = null;
      wizardPendingBillList = null;
      billingTerms = null;
      billPreview = null;
    }
    if (wizardMode === "offline_vendor" && wizardVendorId) {
      const v = offlineVendorsCache.find(x => x.id === wizardVendorId);
      const lbl = v
        ? (v.city_name ? `${v.business_name} — ${v.city_name}` : v.business_name)
        : "Receive without order";
      placedOrder = { vendor_id: wizardVendorId, vendor_label: lbl };
    }
    if (document.querySelector(".vo-wiz-vendor-list")) {
      renderWizard();
      return;
    }
    const nextBtn = document.querySelector("#stock-wizard-footer .btn-primary");
    if (nextBtn) nextBtn.disabled = !wizardVendorId;
  }
  function setLine(idx, field, raw) {
    if (!wizardLines[idx]) return;
    wizardLines[idx][field] = Math.max(0, parseInt(String(raw || "0"), 10) || 0);
    if (field === "quantity_received" && wizardMode !== "receive_goods" && wizardMode !== "offline_vendor") {
      wizardLines[idx].quantity_billed = wizardLines[idx].quantity_received;
      const row = document.querySelectorAll(".stock-receive-table tbody tr")[idx];
      const billedEl = row?.querySelector(".stock-billed-input");
      if (billedEl) billedEl.value = wizardLines[idx].quantity_billed || "";
    }
  }
  function setBillFile(file) { billFile = file || null; billFileKey = null; }
  function wizardBack() {
    if (wizardStep > 1) {
      wizardStep--;
      offlineQtyPopupId = null;
      // Keep entered lines/qtys when going back — only drop product cache on vendor step
      if (wizardMode === "offline_vendor" && wizardStep === 1) {
        wizardProducts = [];
        document.querySelector("#stock-wizard .stock-wiz-modal")?.classList.remove("stock-wiz-wide");
      }
      renderWizard();
    } else if ((wizardMode === "receive_goods" || wizardMode === "bill_received") && enteredFromAddStock) {
      wizardMode = null; wizardStep = 1;
      renderWizard();
    } else if (wizardMode === "receive_goods" || wizardMode === "bill_received") {
      closeWizard();
    } else if (wizardMode !== "offline_vendor") {
      wizardStep = 1; wizardMode = null; renderWizard();
    }
  }
  async function wizardNext() {
    if (wizardMode === "offline_vendor") {
      if (wizardStep === 1 && !wizardVendorId) return;
      if (wizardStep === 2) {
        offlineQtyPopupId = null;
        if (!wizardLines.some(l => (l.quantity_received || 0) > 0)) {
          return ctx.toast("Add at least one product with quantity", "error");
        }
      }
      if (wizardStep === 3) {
        saveReceiptMeta();
        if (!receiptMeta.orderReceiptNumber) {
          return ctx.toast("Enter order receipt number", "error");
        }
      }
      wizardStep++;
      await renderWizard();
      return;
    }
    if (wizardMode === "receive_goods") {
      if (wizardStep === 1 && !wizardVendorId) return;
      if (wizardStep === 2) {
        saveReceiptMeta();
        if (!wizardLines.some(l => (l.quantity_received || 0) > 0)) {
          return ctx.toast("Enter quantity received on at least one row", "error");
        }
        if (!receiptMeta.orderReceiptNumber) {
          return ctx.toast("Enter order receipt number", "error");
        }
      }
      wizardStep++;
      await renderWizard();
      return;
    }
    if (wizardMode === "bill_received") {
      if (wizardStep === 1 && !wizardVendorId) return;
      if (wizardStep === 2) {
        if (!wizardReceiptId) return; // still picking a receipt
        if (!wizardLines.some(l => (l.quantity_billed || 0) > 0)) {
          return ctx.toast("Enter billed quantity on at least one row", "error");
        }
        saveReceiptMeta();
        const total = parseFloat(receiptMeta.totalBilledAmount);
        if (!receiptMeta.totalBilledAmount || Number.isNaN(total) || total < 0) {
          return ctx.toast("Enter total bill amount", "error");
        }
        ctx.showLoading?.();
        try { await refreshBillPreview(); } finally { ctx.hideLoading?.(); }
      }
      wizardStep++;
      await renderWizard();
      return;
    }
    if (wizardStep === 2 && !wizardVendorId) return;
    wizardStep++;
    await renderWizard();
  }
  async function uploadBill() {
    const billNum = receiptMeta.billNumber || (document.getElementById("stock-bill-number")?.value || "").trim() || "receive";
    if (!billFile) return null;
    const fd = new FormData();
    fd.append("vendor_id", String(wizardVendorId));
    fd.append("bill_number", billNum);
    fd.append("file", billFile);
    const API = ctx.apiBase ? ctx.apiBase() : "http://127.0.0.1:8003/api/v1";
    const h = {};
    if (sessionStorage.getItem("jc_auth_mode") === "admin") {
      h["X-Admin-Key"] = sessionStorage.getItem("jc_admin_key") || "";
    } else {
      h["Authorization"] = `Bearer ${sessionStorage.getItem("jc_staff_token") || ""}`;
    }
    const res = await fetch(`${API}/stock/upload-bill`, { method: "POST", headers: h, body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : "Bill upload failed");
    }
    const data = await res.json();
    return data.key;
  }
  async function submitReceipt() {
    saveReceiptMeta();
    const isEdit = wizardMode === "edit_receipt" && editReceiptId;
    const isOffline = wizardMode === "offline_vendor";
    const isReceive = wizardMode === "receive_goods" || isOffline
      || (isEdit && (editReceiptType === "vendor_receive" || editReceiptType === "offline_vendor"));
    const isBill = wizardMode === "bill_received" || (isEdit && editReceiptType === "vendor_bill");
    const isNewBill = isBill && !isEdit;
    const active = isReceive
      ? receivedLines()
      : (isBill ? wizardLines.filter(l => (l.quantity_billed || 0) > 0) : billableLines());
    if (!active.length) return ctx.toast(isReceive ? "Enter received quantities" : "Enter received or billed quantities", "error");
    const endpoint = isEdit
      ? `/stock/receipts/${editReceiptId}`
      : isOffline
        ? "/stock/receipts/offline-vendor"
        : isReceive
          ? "/stock/receipts/vendor-receive"
          : `/stock/receipts/${wizardReceiptId}/bill`;
    const savedVendorId = wizardVendorId;
    const savedLabel = placedOrder?.vendor_label || "";
    const savedMode = wizardMode;
    const savedNotes = receiptMeta.notes || "";
    const savedBillNum = receiptMeta.billNumber || "";
    const savedOrderReceipt = receiptMeta.orderReceiptNumber || "";
    const savedDns = [...pendingDebitNotes];
    const savedExtraCash = billPreview?.expected_extra_cash ? Number(billPreview.expected_extra_cash) : 0;
    ctx.showLoading?.();
    try {
      let key = billFileKey;
      if (billFile) key = await uploadBill();
      const billNum = receiptMeta.billNumber || null;
      const totalBilled = receiptMeta.totalBilledAmount ? parseFloat(receiptMeta.totalBilledAmount) : null;
      if (!isReceive && (totalBilled == null || totalBilled < 0)) return ctx.toast("Enter total bill amount", "error");
      if (isReceive && !receiptMeta.orderReceiptNumber) {
        return ctx.toast("Enter order receipt number", "error");
      }
      const eventDate = receiptMeta.eventDate || localToday();
      const debitNotesPayload = pendingDebitNotes.map(dn => ({
        note_type: dn.note_type,
        direction: dn.direction || dn._direction || null,
        catalog_product_id: dn.catalog_product_id,
        quantity: dn.quantity,
        amount: dn.amount,
        notes: dn.notes || null,
      }));
      const payload = isReceive
        ? {
            vendor_id: wizardVendorId,
            order_receipt_number: receiptMeta.orderReceiptNumber,
            bill_file_key: key,
            notes: receiptMeta.notes || null,
            received_on: eventDate,
            lines: active.map(l => ({
              catalog_product_id: l.catalog_product_id,
              quantity_received: l.quantity_received || 0,
              quantity_billed: 0,
              billed_amount: 0,
            })),
          }
        : isNewBill
        ? {
            total_billed_amount: totalBilled,
            lines: active.map(l => ({
              catalog_product_id: l.catalog_product_id,
              quantity_billed: l.quantity_billed || 0,
            })),
            bill_number: billNum,
            bill_file_key: key,
            bill_date: eventDate,
            notes: receiptMeta.notes || null,
            debit_notes: debitNotesPayload,
          }
        : {
            vendor_id: wizardVendorId,
            bill_number: billNum,
            bill_file_key: key,
            notes: receiptMeta.notes || null,
            additional_charges: null,
            total_billed_amount: totalBilled,
            bill_date: eventDate,
            lines: active.map(l => ({
              catalog_product_id: l.catalog_product_id,
              quantity_received: l.quantity_received || l.quantity_billed || 0,
              quantity_billed: l.quantity_billed || 0,
              billed_amount: 0,
            })),
            debit_notes: debitNotesPayload,
          };
      const res = await ctx.api(endpoint, {
        method: isEdit ? "PATCH" : "POST",
        body: JSON.stringify(payload),
      });
      ctx.invalidateCache?.("/stock");
      ctx.invalidateCache?.("/vendor-orders");
      ctx.invalidateCache?.("/accounts-payable");
      const rid = res.receipt_id || editReceiptId;
      closeWizard();
      if (isEdit) {
        ctx.toast(isReceive ? "Receive updated" : "Bill updated", "success");
        if (rid) await openReceiptDetail(rid);
        if (typeof VendorOrders !== "undefined" && VendorOrders.refreshIfOpen) VendorOrders.refreshIfOpen(savedVendorId);
        await load();
        return;
      }
      if (isReceive) {
        const lineHtml = `<table class="data" style="font-size:13px;margin-top:12px;"><thead><tr><th>Product</th><th>Received</th></tr></thead><tbody>
          ${active.map(l => `<tr><td>${ctx.esc(productIdLabel(l))}</td><td>${l.quantity_received || 0}</td></tr>`).join("")}
        </tbody></table>`;
        const nextHint = savedMode === "offline_vendor"
          ? "In <strong>Received</strong> (unbilled). Next: Bill when vendor invoice arrives."
          : "Stock updated. Next: Bill when vendor invoice arrives.";
        ctx.openDetail?.("Goods received", `
          <div class="doc-success-banner">
            <strong>Goods in stock</strong>
            <span>Receipt #${rid} · no AP yet</span>
          </div>
          <p style="margin:0 0 12px;font-size:14px;color:var(--muted);">${nextHint}</p>
          <div class="review-block" style="margin-bottom:12px;">
            ${ctx.reviewRow("Vendor", savedLabel || "—")}
            ${ctx.reviewRow("Order receipt #", savedOrderReceipt || "—")}
            ${savedNotes ? ctx.reviewRow("Note", savedNotes) : ""}
          </div>
          ${lineHtml}`,
          `${ctx.canWrite?.("vendor_orders") !== false ? `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail(); Stock.openBillForVendor(${savedVendorId})">Bill next →</button>` : ""}
           <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail(); if(typeof VendorOrders!=='undefined'){App.showView('buying');VendorOrders.setHubMode('past');VendorOrders.setBucket('received');VendorOrders.openDetail(0,'received',${savedVendorId});}">View Received</button>`, "md");
        ctx.toast("Goods received", "success");
        if (typeof VendorOrders !== "undefined" && VendorOrders.refreshIfOpen) VendorOrders.refreshIfOpen(savedVendorId);
        await load();
        return;
      }
      const totals = calcReviewTotals(active);
      if (savedExtraCash > 0) totals.netPayable += savedExtraCash;
      let docUrl = res.document_url;
      if (!docUrl && rid) {
        try {
          const doc = await ctx.api(`/stock/receipts/${rid}/document`, {}, 0);
          docUrl = doc.document_url;
        } catch (_) {}
      }
      const dnHtml = savedDns.length
        ? `<table class="data" style="font-size:13px;margin-top:12px;"><thead><tr><th>Debit Note</th><th>Effect</th></tr></thead><tbody>
            ${savedDns.map(dn => {
              const effect = dnPayableEffect(dn);
              const payLess = effect < 0;
              const cmt = dn.notes ? ` — ${ctx.esc(dn.notes)}` : "";
              return `<tr><td>${ctx.esc(dnDisplayLabel(dn))}${cmt}</td><td>${payLess ? "Pay less" : "Pay more"} ${fmtPrice(Math.abs(effect))}</td></tr>`;
            }).join("")}
          </tbody></table>` : "";
      const lineHtml = `<table class="data" style="font-size:13px;margin-top:12px;"><thead><tr><th>Product</th><th>Received</th><th>Billed</th></tr></thead><tbody>
        ${active.map(l => `<tr><td>${ctx.esc(productIdLabel(l))}</td><td>${l.quantity_received || 0}</td><td>${l.quantity_billed || 0}</td></tr>`).join("")}
      </tbody></table>`;
      const pdfBtns = docUrl
        ? `<div class="doc-actions">
            <button class="btn btn-primary" onclick="Stock.openReceiptPdf('${docUrl}', true)">Print</button>
            <button class="btn btn-secondary" onclick="Stock.openReceiptPdf('${docUrl}', false)">Save PDF</button>
            <button class="btn btn-secondary" onclick="Stock.openReceiptPdf('${docUrl}', false)">View PDF</button>
          </div>`
        : `<div class="doc-actions">
            <button class="btn btn-primary" onclick="Stock.fetchReceiptPdf(${rid}, true)">Get PDF &amp; Print</button>
            <button class="btn btn-secondary" onclick="Stock.fetchReceiptPdf(${rid}, false)">Get PDF</button>
          </div>
          <p class="doc-actions-hint">Receipt #${rid} is saved. Tap Get PDF if the file was still generating.</p>`;
      ctx.openDetail?.("Bill saved", `
        <div class="doc-success-banner">
          <strong>Bill saved</strong>
          <span>Receipt #${rid}${savedBillNum ? ` · Bill ${ctx.esc(savedBillNum)}` : ""}</span>
        </div>
        <div class="review-block" style="margin-bottom:12px;">
          ${ctx.reviewRow("Vendor", savedLabel || "—")}
          ${ctx.reviewRow("Bill number", savedBillNum || "—")}
          ${ctx.reviewRow("Bill amount", fmtPrice(totals.billAmount))}
          ${savedExtraCash > 0 ? ctx.reviewRow("Extra cash", fmtPrice(savedExtraCash)) : ""}
          ${totals.dnAdj ? ctx.reviewRow("Debit note adj.", fmtPrice(totals.dnAdj)) : ""}
          ${ctx.reviewRow("Net payable", fmtPrice(totals.netPayable))}
        </div>
        ${lineHtml}
        ${dnHtml}
        ${pdfBtns}`,
        `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Done</button>`, "md");
      ctx.toast(savedMode === "offline_vendor" ? "Offline order created" : "Bill created", "success");
      if (typeof VendorOrders !== "undefined" && VendorOrders.refreshIfOpen) VendorOrders.refreshIfOpen(savedVendorId);
      await load();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  function openReceiptPdf(url, print) {
    if (!url) return ctx.toast("PDF not ready", "error");
    const w = window.open(url, "_blank");
    if (print && w) {
      try { w.focus(); setTimeout(() => { try { w.print(); } catch (_) {} }, 600); } catch (_) {}
    }
  }
  async function fetchReceiptPdf(receiptId, print) {
    if (!receiptId) return;
    ctx.showLoading?.();
    try {
      const doc = await ctx.api(`/stock/receipts/${receiptId}/document`, {}, 0);
      if (!doc?.document_url) throw new Error("PDF not available yet");
      openReceiptPdf(doc.document_url, print);
    } catch (e) { ctx.toast(e.message || "PDF not available", "error"); }
    finally { ctx.hideLoading?.(); }
  }
  async function openLedgerDetail(ledgerId) {
    ctx.showLoading?.();
    try {
      const d = await ctx.api(`/stock/ledger/${ledgerId}`, {}, 0);
      renderReceiptDetail("Stock movement", d.entry_type, d.quantity_delta, d.balance_after, d.created_at, d.notes, d.receipt);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  async function openReceiptDetail(receiptId) {
    ctx.showLoading?.();
    try {
      const receipt = await ctx.api(`/stock/receipts/${receiptId}`, {}, 0);
      renderReceiptDetail("Stock receipt", "receipt", null, null, receipt.received_at, null, receipt);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  async function openEditReceipt(receiptId) {
    ctx.showLoading?.();
    try {
      const receipt = await ctx.api(`/stock/receipts/${receiptId}`, {}, 0);
      editReceiptId = receipt.id;
      // One-to-one model: receipt_type stays "vendor_receive" for life; bill_status
      // (not receipt_type) tells us whether this is now a bill to edit.
      editReceiptType = receipt.bill_status === "billed" ? "vendor_bill" : (receipt.receipt_type || "vendor_order");
      wizardMode = "edit_receipt";
      wizardStep = 1;
      wizardVendorId = receipt.vendor_id;
      wizardProducts = [];
      wizardLines = (receipt.lines || []).map(l => ({
        catalog_product_id: l.catalog_product_id,
        our_product_id: l.our_product_id,
        buying_price: l.buying_price,
        quantity_received: l.quantity_received || 0,
        quantity_billed: l.quantity_billed || 0,
      }));
      billFile = null;
      billFileKey = receipt.bill_file_key || null;
      pendingDebitNotes = (receipt.debit_notes || []).map(dn => ({
        note_type: dn.note_type,
        direction: dn.direction,
        catalog_product_id: dn.catalog_product_id,
        our_product_id: dn.our_product_id,
        quantity: dn.quantity,
        amount: dn.amount,
        notes: dn.notes,
        _payable_effect: dn.payable_effect,
      }));
      receiptMeta = {
        billNumber: receipt.bill_number || "",
        orderReceiptNumber: receipt.order_receipt_number || "",
        additionalCharges: receipt.additional_charges || "",
        totalBilledAmount: receipt.total_billed_amount || receipt.bill_amount || "",
        notes: receipt.notes || "",
      };
      try {
        const v = await ctx.api(`/vendors/${receipt.vendor_id}`, {}, 60000);
        placedOrder = {
          vendor_id: receipt.vendor_id,
          vendor_label: v.city_name ? `${v.business_name} — ${v.city_name}` : v.business_name,
        };
      } catch (_) {
        placedOrder = { vendor_id: receipt.vendor_id, vendor_label: `Vendor #${receipt.vendor_id}` };
      }
      document.getElementById("stock-wizard")?.classList.remove("hidden");
      document.querySelector("#stock-wizard .modal-header h3").textContent =
        editReceiptType === "vendor_receive" ? "Edit Receive" : "Edit Vendor Bill";
      await renderWizard();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  function renderReceiptDetail(title, entryType, qtyDelta, balanceAfter, when, notes, receipt) {
    const voidedBanner = receipt?.deleted_at
      ? `<div style="background:var(--danger-bg,#fee2e2);color:var(--danger);border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:13px;">
          <strong>Voided</strong>${receipt.deleted_reason ? ` — ${ctx.esc(receipt.deleted_reason)}` : ""}. Restore it from the recycle bin to edit or bill again.
        </div>`
      : "";
    const meta = [
      entryType ? ctx.reviewRow("Type", entryType) : "",
      qtyDelta != null ? ctx.reviewRow("Quantity", (qtyDelta > 0 ? "+" : "") + qtyDelta) : "",
      balanceAfter != null ? ctx.reviewRow("Balance after", balanceAfter) : "",
      ctx.reviewRow("Date", new Date(when).toLocaleString()),
      notes ? ctx.reviewRow("Notes", notes) : "",
      receipt?.order_receipt_number ? ctx.reviewRow("Order receipt #", receipt.order_receipt_number) : "",
      receipt?.bill_number ? ctx.reviewRow("Bill number", receipt.bill_number) : "",
      receipt?.bill_amount ? ctx.reviewRow("Bill amount", fmtPrice(receipt.bill_amount)) : "",
      receipt?.debit_note_total ? ctx.reviewRow("Debit note adj.", fmtPrice(receipt.debit_note_total)) : "",
      receipt?.net_payable ? ctx.reviewRow("Net payable", fmtPrice(receipt.net_payable)) : "",
      receipt?.received_by_name && ctx.isAdmin?.() ? ctx.reviewRow("Received by", receipt.received_by_name) : "",
    ].join("");
    let table = "";
    let extra = "";
    if (receipt?.lines?.length) {
      const showAmt = receipt.lines.some(l => l.billed_amount && Number(l.billed_amount) !== 0);
      const lineRows = receipt.lines.map(l =>
        `<tr><td>${ctx.esc(productIdLabel(l))}</td><td>${l.quantity_received}</td><td>${l.quantity_billed || 0}</td>${showAmt ? `<td>${l.billed_amount ? fmtPrice(l.billed_amount) : "—"}</td>` : ""}</tr>`
      ).join("");
      table = `<table class="data" style="font-size:13px;"><thead><tr><th>Product</th><th>Received</th><th>Billed Qty</th>${showAmt ? "<th>Billed Amt</th>" : ""}</tr></thead><tbody>${lineRows}</tbody></table>`;
    }
    if (receipt?.debit_notes?.length) {
      extra += `<div style="margin-top:12px;"><strong style="font-size:13px;">Debit notes</strong>
        <table class="data" style="font-size:13px;margin-top:6px;"><thead><tr><th>Note</th><th>Effect</th></tr></thead><tbody>
        ${receipt.debit_notes.map(dn => {
          const label = dn.note_type === "item"
            ? `${ctx.esc(productIdLabel(dn))} × ${dn.quantity} (${ctx.esc(dn.direction || "")})`
            : `Value ₹${ctx.esc(dn.amount)} (${ctx.esc(dn.direction || "")})`;
          return `<tr><td>${label}${dn.notes ? ` — ${ctx.esc(dn.notes)}` : ""}</td><td>${fmtPrice(dn.payable_effect)}</td></tr>`;
        }).join("")}
        </tbody></table></div>`;
    }
    if (receipt?.bill_file_url) {
      extra += `<p style="margin-top:8px;"><a href="${ctx.esc(receipt.bill_file_url)}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm">View bill file</a></p>`;
    }
    if (receipt?.change_history?.length && ctx.changeHistoryTable) {
      extra += `<div style="margin-top:16px;">${ctx.changeHistoryTable(receipt.change_history)}</div>`;
    }
    const canWrite = ctx.canWrite?.("stock") !== false;
    const isVoided = !!receipt?.deleted_at;
    const editLabel = receipt?.receipt_type === "vendor_receive" ? "Edit receive" : "Edit bill";
    const footer = `
      ${canWrite && receipt?.id && !isVoided ? `<button class="btn btn-primary" onclick="Stock.openEditReceipt(${receipt.id})">${editLabel}</button>` : ""}
      ${ctx.isAdmin?.() && receipt?.id && !isVoided ? `<button class="btn btn-danger" onclick="Stock.voidReceipt(${receipt.id}, ${receipt.vendor_id || "null"})">Void</button>` : ""}
      ${ctx.detailFooterChild()}`;
    ctx.openDetail(title, voidedBanner + ctx.ledgerDetailCard("Receipt details", meta, table, extra), footer, "md", { push: true });
  }
  async function voidReceipt(receiptId, vendorId) {
    const reason = prompt("Why are you voiding this receipt/bill? (optional)", "");
    if (reason === null) return;
    if (!confirm("Void this receipt? Stock and AP will be reversed. It moves to the recycle bin and can be restored.")) return;
    ctx.showLoading?.();
    try {
      await ctx.api(`/stock/receipts/${receiptId}/void`, { method: "POST", body: JSON.stringify({ reason: reason || null }) });
      ctx.invalidateCache?.("/stock");
      ctx.invalidateCache?.("/vendor-orders");
      ctx.invalidateCache?.("/accounts-payable");
      ctx.closeDetail?.();
      ctx.toast("Voided — moved to recycle bin", "success");
      if (typeof VendorOrders !== "undefined" && VendorOrders.refreshIfOpen) VendorOrders.refreshIfOpen(vendorId);
      await load();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  async function editThreshold(catalogProductId, current) {
    const raw = prompt("Low stock threshold (qty below this = low stock):", String(current ?? 5));
    if (raw == null) return;
    const val = Math.max(0, parseInt(raw, 10) || 0);
    ctx.showLoading?.();
    try {
      await ctx.api(`/stock/products/${catalogProductId}/threshold`, {
        method: "PATCH",
        body: JSON.stringify({ low_stock_threshold: val }),
      });
      ctx.invalidateCache?.("/stock");
      ctx.toast("Threshold updated", "success");
      openDetail(catalogProductId);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  async function adjustStock(catalogProductId, currentQty) {
    const raw = prompt(`Adjust stock for this product.\nCurrent on hand: ${currentQty ?? 0}\n\nEnter quantity change (e.g. 5 to add 5, -3 to remove 3):`);
    if (raw == null) return;
    const delta = parseInt(String(raw).trim(), 10);
    if (!Number.isFinite(delta) || delta === 0) return ctx.toast("Enter a non-zero whole number", "error");
    const reason = prompt("Reason for this correction (required):");
    if (reason == null) return;
    const reasonTrimmed = reason.trim();
    if (!reasonTrimmed) return ctx.toast("Reason is required", "error");
    ctx.showLoading?.();
    try {
      await ctx.api(`/stock/products/${catalogProductId}/adjust`, {
        method: "POST",
        body: JSON.stringify({ quantity_delta: delta, reason: reasonTrimmed }),
      });
      ctx.invalidateCache?.("/stock");
      ctx.toast(`Stock ${delta > 0 ? "increased" : "decreased"} by ${Math.abs(delta)}`, "success");
      openDetail(catalogProductId);
      if (typeof Products !== "undefined") await Products.refreshHub?.();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  async function setSellingPrice(catalogProductId, current) {
    const raw = prompt("Selling price (₹). Leave blank to clear:", current == null ? "" : String(current));
    if (raw == null) return;
    const trimmed = String(raw).trim();
    let selling_price = null;
    if (trimmed !== "") {
      const n = parseFloat(trimmed);
      if (Number.isNaN(n) || n < 0) return ctx.toast("Enter a valid price", "error");
      selling_price = n;
    }
    ctx.showLoading?.();
    try {
      await ctx.api(`/stock/products/${catalogProductId}/selling-price`, {
        method: "PATCH",
        body: JSON.stringify({ selling_price }),
      });
      ctx.invalidateCache?.("/stock");
      ctx.invalidateCache?.("/catalog");
      ctx.toast("Sell price updated", "success");
      openDetail(catalogProductId);
      if (typeof Products !== "undefined") await Products.refreshHub?.();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  return {
    init, load, setViewMode, render, openDetail, openLedgerDetail, openReceiptDetail,
    openAddWizard, openReceiveForVendor, openBillForVendor, openOfflineWizard, openOfflineForVendor, closeWizard, pickMode, pickVendor, setLine, setBillFile,
    toggleOfflineProduct, setOfflineLine, onOfflineProductSearch, onOfflineVendorSearch,
    openOfflineQtyPopup, closeOfflineQtyPopup, confirmOfflineQty, removeOfflineLine, bumpOfflineQty,
    wizardBack, wizardNext, submitReceipt, openDebitNote, removeDebitNote, editThreshold, setSellingPrice, adjustStock,
    openReceiptPdf, fetchReceiptPdf, openEditReceipt, selectPendingReceipt, changePendingReceipt,
    voidReceipt, editPendingDebitNote,
  };
})();
