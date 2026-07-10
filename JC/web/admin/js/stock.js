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
  let receiptMeta = { billNumber: "", additionalCharges: "", totalBilledAmount: "" };
  let receivePrefill = null;

  const STOCK_COLS = [
    { key: "our_product_id", label: "Product ID", get: p => p.our_product_id },
    { key: "vendor", label: "Vendor", get: p => p.vendor_label || "" },
    { key: "qty", label: "On Hand", get: p => String(p.quantity_on_hand) },
    { key: "price", label: "Sell Price", get: p => p.selling_price || "" },
  ];

  function init(context) { ctx = context; TableUtils.register("stock", renderTable); }

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
    const q = document.getElementById("stock-search-input")?.value.trim() || "";
    ctx.showLoading?.();
    try {
      products = await ctx.api(`/stock/products${q ? "?search=" + encodeURIComponent(q) : ""}`, {}, 0);
      render();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function setViewMode(mode) {
    viewMode = mode === "list" ? "list" : "grid";
    document.getElementById("stock-view-grid")?.classList.toggle("active", viewMode === "grid");
    document.getElementById("stock-view-list")?.classList.toggle("active", viewMode === "list");
    document.getElementById("stock-grid")?.classList.toggle("hidden", viewMode === "list");
    document.getElementById("stock-table")?.classList.toggle("hidden", viewMode !== "list");
    render();
  }

  function render() {
    if (viewMode === "list") renderTable();
    else renderGrid();
  }

  function renderGrid() {
    const el = document.getElementById("stock-grid");
    if (!el) return;
    const withStock = products.filter(p => p.quantity_on_hand > 0);
    const show = withStock.length ? withStock : products;
    if (!show.length) {
      el.innerHTML = `<div class="empty-state"><p>No stock yet.</p><button class="btn btn-primary btn-lg" style="margin-top:16px;" onclick="Stock.openAddWizard()">+ Add Stock</button></div>`;
      return;
    }
    el.innerHTML = `<div class="catalog-grid">${show.map(p => {
      const img = (p.image_urls && p.image_urls[0]) || "";
      return `<button type="button" class="catalog-card" onclick="Stock.openDetail(${p.catalog_product_id})">
        ${img ? `<img src="${ctx.esc(img)}" class="catalog-card-img" />` : `<div class="catalog-card-img catalog-card-img-empty">No image</div>`}
        <div class="catalog-card-body">
          <div class="catalog-card-title">${ctx.esc(p.our_product_id)}</div>
          <div class="catalog-card-vendor">${ctx.esc(p.vendor_label)}</div>
          <div class="catalog-card-city">Qty: <strong>${p.quantity_on_hand}</strong></div>
          <div class="catalog-card-price">${p.selling_price ? fmtPrice(p.selling_price) : "—"}</div>
        </div>
      </button>`;
    }).join("")}</div>`;
  }

  function renderTable() {
    const el = document.getElementById("stock-table");
    if (!el) return;
    if (!products.length) {
      el.innerHTML = `<div class="empty-state"><p>No stock yet.</p></div>`;
      return;
    }
    const rows = TableUtils.apply(products, "stock", STOCK_COLS);
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("stock", STOCK_COLS)}<tbody>
      ${rows.map(p => `<tr class="clickable" onclick="Stock.openDetail(${p.catalog_product_id})">
        <td><strong>${ctx.esc(p.our_product_id)}</strong></td>
        <td>${ctx.esc(p.vendor_label || "—")}</td>
        <td>${p.quantity_on_hand}</td>
        <td>${p.selling_price ? fmtPrice(p.selling_price) : "—"}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  async function openDetail(id) {
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
      const sellHtml = p.selling_price
        ? `<div class="stock-price-row"><strong>${fmtPrice(p.selling_price)}</strong>
            ${ctx.canWrite?.("catalog") || ctx.canWrite?.("stock") ? `<button class="btn btn-secondary btn-sm" onclick="Stock.setSellingPrice(${p.catalog_product_id}, '${ctx.esc(String(p.selling_price))}')">Set</button>` : ""}</div>`
        : `<div class="stock-price-row"><span class="prod-price-missing">Not set</span>
            ${ctx.canWrite?.("catalog") || ctx.canWrite?.("stock") ? `<button class="btn btn-primary btn-sm" onclick="Stock.setSellingPrice(${p.catalog_product_id}, '')">Set sell price</button>` : ""}</div>`;
      ctx.openDetail(p.our_product_id, `
        <div style="display:flex;gap:16px;margin-bottom:20px;align-items:flex-start;">
          ${img ? `<img src="${ctx.esc(img)}" class="stock-detail-img" onclick="Products.enlargeImage(decodeURIComponent('${encodeURIComponent(img)}'))" style="cursor:zoom-in;" />` : ""}
          <div>
            <div style="font-size:13px;color:var(--muted);">${ctx.esc(p.vendor_label)}</div>
            <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;">
              <span class="badge badge-blue">On hand: ${p.quantity_on_hand}</span>
              <span class="badge ${p.stock_status === 'in_stock' ? 'badge-green' : p.stock_status === 'low_stock' ? 'badge-yellow' : 'badge-red'}">${ctx.esc((p.stock_status || '').replace('_', ' '))}</span>
              <span class="badge badge-gray">Pending order: ${p.quantity_pending}</span>
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
    receiptMeta = { billNumber: "", additionalCharges: "", totalBilledAmount: "" };
    document.getElementById("stock-wizard")?.classList.remove("hidden");
    renderWizard();
  }

  function closeWizard() {
    document.getElementById("stock-wizard")?.classList.add("hidden");
    document.querySelector("#stock-wizard .modal-header h3").textContent = "Add Stock";
  }

  async function openReceiveForVendor(vendorId, prefill) {
    wizardStep = 3;
    wizardMode = "vendor_order";
    wizardVendorId = vendorId;
    placedOrder = null;
    wizardLines = [];
    billFile = null;
    billFileKey = null;
    pendingDebitNotes = [];
    receivePrefill = prefill || null;
    receiptMeta = { billNumber: "", additionalCharges: "", totalBilledAmount: "" };
    document.getElementById("stock-wizard")?.classList.remove("hidden");
    await renderWizard();
  }

  async function openOfflineWizard(vendorId) {
    wizardStep = vendorId ? 2 : 1;
    wizardMode = "offline_vendor";
    wizardVendorId = vendorId || null;
    placedOrder = vendorId ? { vendor_id: vendorId, vendor_label: "Offline vendor order" } : null;
    wizardProducts = [];
    wizardLines = [];
    billFile = null;
    billFileKey = null;
    pendingDebitNotes = [];
    receiptMeta = { billNumber: "", additionalCharges: "", totalBilledAmount: "" };
    document.getElementById("stock-wizard")?.classList.remove("hidden");
    document.querySelector("#stock-wizard .modal-header h3").textContent = "Offline Vendor Order";
    if (vendorId) {
      try {
        const v = await ctx.api(`/vendors/${vendorId}`, {}, 60000);
        placedOrder = { vendor_id: vendorId, vendor_label: v.city_name ? `${v.business_name} — ${v.city_name}` : v.business_name };
      } catch (_) {}
    }
    await renderWizard();
  }
  function openOfflineForVendor(vendorId) { return openOfflineWizard(vendorId); }

  let wizardProducts = [];

  function pickMode(mode) {
    if (mode === "manual") { ctx.toast("Manual stock — coming soon", "error"); return; }
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

  async function renderWizard() {
    const stepsEl = document.getElementById("stock-wizard-steps");
    const bodyEl = document.getElementById("stock-wizard-body");
    const footerEl = document.getElementById("stock-wizard-footer");
    if (!stepsEl || !bodyEl || !footerEl) return;

    const labels = wizardMode === "offline_vendor"
      ? ["Vendor", "Products", "Bill", "Debit Note", "Review"]
      : wizardMode === "vendor_order"
      ? ["Source", "Vendor", "Receive", "Debit Note", "Review"]
      : ["Source"];
    stepsEl.innerHTML = labels.map((lbl, i) => {
      const n = i + 1;
      const cls = n === wizardStep ? "step active" : n < wizardStep ? "step done" : "step";
      return `<div class="${cls}"><span class="step-num">${n < wizardStep ? "✓" : n}</span><span class="step-label">${lbl}</span></div>`;
    }).join("");

    if (wizardStep === 1) {
      if (wizardMode === "offline_vendor") {
        setStockWizardChrome("Offline Order", "Step 1 — choose the vendor");
        let vendors = [];
        try { vendors = await ctx.api("/vendors", {}, 30000); } catch (_) {}
        bodyEl.innerHTML = `
          <div class="vo-wiz-step-head">
            <h4>Select vendor</h4>
            <p>Goods already purchased — bill and add to stock now.</p>
          </div>
          <label class="label">Vendor</label>
          <select class="input" id="stock-vendor-select" onchange="Stock.pickVendor(parseInt(this.value,10)||null)">
            <option value="">— Select vendor —</option>
            ${vendors.filter(v => v.is_active && !v.deleted_at).map(v => {
              const lbl = v.city_name ? `${v.business_name} — ${v.city_name}` : v.business_name;
              return `<option value="${v.id}" ${wizardVendorId === v.id ? "selected" : ""}>${ctx.esc(lbl)}</option>`;
            }).join("")}
          </select>`;
        footerEl.innerHTML = `
          <button class="btn btn-secondary" onclick="Stock.closeWizard()">Cancel</button>
          <button class="btn btn-primary" ${wizardVendorId ? "" : "disabled"} onclick="Stock.wizardNext()">Next →</button>`;
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
            <span class="create-order-letter">V</span>
            <span class="create-order-card-body">
              <strong>Vendor Order</strong>
              <span>Receive against a placed order — enter qty, bill, debit notes</span>
            </span>
            <span class="create-order-arrow">→</span>
          </button>
          <button type="button" class="create-order-card create-order-card-alt" onclick="Stock.pickMode('manual')">
            <span class="create-order-letter alt">M</span>
            <span class="create-order-card-body">
              <strong>Manual</strong>
              <span>Add stock without a vendor order</span>
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
      bodyEl.innerHTML = `
        <p style="margin:0 0 12px;font-size:13px;color:var(--muted);">Select products — enter qty received and qty billed.</p>
        <div class="vo-wizard-products">
          ${wizardProducts.map(p => {
            const line = wizardLines.find(l => l.catalog_product_id === p.id);
            const checked = !!line;
            const img = (p.image_urls && p.image_urls[0]) || "";
            return `<div class="vo-wizard-product ${checked ? "selected" : ""}">
              <label style="display:flex;gap:12px;align-items:flex-start;cursor:pointer;">
                <input type="checkbox" ${checked ? "checked" : ""} onchange="Stock.toggleOfflineProduct(${p.id}, this.checked)" />
                ${thumb(img)}
                <div style="flex:1;">
                  <div><strong>${ctx.esc(p.our_product_id)}</strong></div>
                  <div style="font-size:13px;margin-top:4px;">${fmtPrice(p.buying_price)}</div>
                  <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;">
                    <div><label class="label" style="font-size:11px;">Received</label>
                      <input type="number" min="0" class="input" style="width:90px;" value="${line?.quantity_received || ""}" ${checked ? "" : "disabled"} onchange="Stock.setOfflineLine(${p.id},'quantity_received',this.value)" onclick="event.stopPropagation()" /></div>
                    <div><label class="label" style="font-size:11px;">Billed</label>
                      <input type="number" min="0" class="input" style="width:90px;" value="${line?.quantity_billed || ""}" ${checked ? "" : "disabled"} onchange="Stock.setOfflineLine(${p.id},'quantity_billed',this.value)" onclick="event.stopPropagation()" /></div>
                  </div>
                </div>
              </label>
            </div>`;
          }).join("")}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
        <button class="btn btn-primary" ${wizardLines.some(l => (l.quantity_received || 0) > 0 || (l.quantity_billed || 0) > 0) ? "" : "disabled"} onclick="Stock.wizardNext()">Bill Details →</button>`;
      return;
    }

    if (wizardStep === 2) {
      setStockWizardChrome("Vendor Order", "Step 2 — which vendor is delivering?");
      let vendors = [];
      try { vendors = await ctx.api("/catalog/vendors", {}, 60000); } catch (_) {
        try { vendors = await ctx.api("/vendors", {}, 0); } catch (e2) { ctx.toast(e2.message, "error"); }
      }
      const active = (vendors || []).filter(v => v.is_active !== false && !v.deleted_at);
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>Select vendor</h4>
          <p>We’ll load open placed lines for this vendor next.</p>
        </div>
        <div class="vo-wiz-vendor-list">
          ${active.length ? active.map(v => {
            const lbl = v.city_name ? `${v.business_name} — ${v.city_name}` : v.business_name;
            const selected = wizardVendorId === v.id;
            return `<button type="button" class="vo-wiz-vendor-card${selected ? " selected" : ""}" onclick="Stock.pickVendor(${v.id})">
              <span class="vo-wiz-vendor-letter">${ctx.esc((v.business_name || "?").slice(0, 1).toUpperCase())}</span>
              <span class="vo-wiz-vendor-meta">
                <strong>${ctx.esc(v.business_name || "Vendor")}</strong>
                <span>${ctx.esc(v.city_name || "No city")}</span>
              </span>
              <span class="vo-wiz-vendor-check">${selected ? "✓" : ""}</span>
            </button>`;
          }).join("") : `<div class="vo-wiz-empty">No vendors found.</div>`}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
        <button class="btn btn-primary" ${wizardVendorId ? "" : "disabled"} onclick="Stock.wizardNext()">Next: Receive →</button>`;
      return;
    }

    if (wizardStep === 3 && wizardMode === "offline_vendor") {
      bodyEl.innerHTML = `
        <p style="margin:0 0 12px;font-size:13px;color:var(--muted);">Bill details for offline receipt</p>
        <div class="table-wrap" style="max-height:30vh;overflow-y:auto;margin-bottom:16px;">
          <table class="data" style="font-size:13px;"><thead><tr><th>Product</th><th>Received</th><th>Billed</th></tr></thead><tbody>
            ${billableLines().map(l => `<tr>
              <td>${ctx.esc(l.our_product_id)}</td><td>${l.quantity_received || 0}</td><td>${l.quantity_billed || 0}</td>
            </tr>`).join("")}
          </tbody></table>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Bill Number</label><input class="input" id="stock-bill-number" value="${ctx.esc(receiptMeta.billNumber)}" /></div>
          <div><label class="label">Total Bill Amount *</label>
            <input type="number" min="0" step="0.01" class="input" id="stock-total-billed" value="${ctx.esc(receiptMeta.totalBilledAmount)}" required /></div>
        </div>
        <div style="margin-top:12px;">
          <label class="label">Upload Bill</label>
          <input type="file" class="input" accept=".pdf,image/*" onchange="Stock.setBillFile(this.files[0])" />
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
        <button class="btn btn-primary" onclick="Stock.wizardNext()">Debit Note →</button>`;
      return;
    }

    if (wizardStep === 3) {
      if (!placedOrder) {
        bodyEl.innerHTML = `<div class="empty-state"><p>Loading placed order…</p></div>`;
        footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>`;
        ctx.showLoading?.();
        try {
          placedOrder = await ctx.api(`/stock/vendor-order/${wizardVendorId}/placed`, {}, 0);
          wizardLines = (placedOrder.lines || []).map(l => ({
            catalog_product_id: l.catalog_product_id,
            our_product_id: l.our_product_id,
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
              match.quantity_billed = match.quantity_received;
              wizardLines = [match];
            }
            receivePrefill = null;
          }
        } catch (e) { ctx.toast(e.message, "error"); wizardStep = 2; return renderWizard(); }
        finally { ctx.hideLoading?.(); }
      }
      if (!wizardLines.length) {
        setStockWizardChrome("Receive Goods", "No open lines for this vendor");
        bodyEl.innerHTML = `<div class="vo-wiz-empty"><p>No open placed lines for this vendor.</p></div>`;
        footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>`;
        return;
      }
      setStockWizardChrome("Receive Goods", "Step 3 — enter quantities and bill details");
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>${ctx.esc(placedOrder.vendor_label)}</h4>
          <p>Enter qty received and qty billed. Then fill the vendor bill details below.</p>
        </div>
        <div class="stock-receive-table-wrap">
          <table class="data stock-receive-table"><thead><tr>
            <th></th><th>Product</th><th>Ordered</th><th>Price</th>
            <th>Received</th><th>Billed</th>
          </tr></thead><tbody>
            ${wizardLines.map((l, i) => {
              const img = (l.image_urls && l.image_urls[0]) || "";
              return `<tr>
                <td>${thumb(img)}</td>
                <td><strong>${ctx.esc(l.our_product_id)}</strong></td>
                <td>${l.quantity_ordered}</td>
                <td>${fmtPrice(l.buying_price)}</td>
                <td><input type="number" min="0" class="input stock-qty-input" value="${l.quantity_received || ""}" onchange="Stock.setLine(${i},'quantity_received',this.value)" /></td>
                <td><input type="number" min="0" class="input stock-qty-input" value="${l.quantity_billed || ""}" onchange="Stock.setLine(${i},'quantity_billed',this.value)" /></td>
              </tr>`;
            }).join("")}
          </tbody></table>
        </div>
        <div class="stock-bill-card">
          <h4>Vendor bill</h4>
          <div class="stock-bill-grid">
            <div><label class="label">Bill number</label><input class="input" id="stock-bill-number" value="${ctx.esc(receiptMeta.billNumber)}" placeholder="Vendor bill #" /></div>
            <div class="stock-bill-total"><label class="label">Total bill amount *</label>
              <input type="number" min="0" step="0.01" class="input" id="stock-total-billed" value="${ctx.esc(receiptMeta.totalBilledAmount)}" placeholder="₹ total on vendor bill" required /></div>
            <div><label class="label">Upload bill</label>
              <input type="file" class="input" accept=".pdf,image/*" onchange="Stock.setBillFile(this.files[0])" />
              ${billFile ? `<span class="stock-file-name">${ctx.esc(billFile.name)}</span>` : ""}
            </div>
          </div>
          <p class="vo-muted" style="margin:10px 0 0;">Enter the full bill total. Use debit notes next if goods or amount need adjustment.</p>
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
        <button class="btn btn-primary" onclick="Stock.wizardNext()">Debit Notes →</button>`;
      return;
    }

    if (wizardStep === 4) {
      setStockWizardChrome("Debit Notes", "Step 4 — adjust payable if bill and goods differ");
      renderDebitNoteStep(bodyEl, footerEl);
      return;
    }

    if (wizardStep === 5) {
      setStockWizardChrome("Review & Submit", "Step 5 — confirm before saving");
      renderReviewStep(bodyEl, footerEl);
      return;
    }
  }

  function saveReceiptMeta() {
    receiptMeta.billNumber = (document.getElementById("stock-bill-number")?.value || "").trim();
        receiptMeta.totalBilledAmount = document.getElementById("stock-total-billed")?.value || "";
  }

  function calcReviewTotals(active) {
    const totalOverride = parseFloat(receiptMeta.totalBilledAmount);
    const billAmount = !Number.isNaN(totalOverride) && receiptMeta.totalBilledAmount !== "" ? totalOverride : 0;
    const dnAdj = pendingDebitNotes.reduce((s, dn) => s + dnPayableEffect(dn), 0);
    const netPayable = billAmount + dnAdj;
    return { billAmount, charges: 0, dnAdj, netPayable };
  }

  function renderDebitNoteStep(bodyEl, footerEl) {
    const billable = billableLines();
    const received = receivedLines();
    const dnRows = pendingDebitNotes.map((dn, i) => {
      const amt = dnPayableEffect(dn);
      const payLess = amt < 0;
      const comment = dn.notes ? `<div class="dn-row-note">${ctx.esc(dn.notes)}</div>` : "";
      return `<tr>
        <td>
          <strong>${ctx.esc(dnDisplayLabel(dn))}</strong>
          ${comment}
        </td>
        <td><span class="dn-effect-pill ${payLess ? "is-less" : "is-more"}">${payLess ? "Pay less" : "Pay more"} ${fmtPrice(Math.abs(amt))}</span></td>
        <td><button class="btn btn-ghost btn-sm" onclick="Stock.removeDebitNote(${i})">✕</button></td>
      </tr>`;
    }).join("");
    bodyEl.innerHTML = `
      <div class="vo-wiz-step-head vo-wiz-step-head-row">
        <div>
          <h4>Debit notes</h4>
          <p>Optional. Use when billed qty/amount doesn’t match what you received. Billed-only lines (0 received) are allowed.</p>
        </div>
        <button class="btn btn-primary btn-sm" onclick="Stock.openDebitNote()" ${billable.length ? "" : "disabled"}>+ Add Debit Note</button>
      </div>
      ${!billable.length ? `<div class="vo-wiz-empty"><p>No billed or received lines — go back and enter quantities first.</p></div>` : ""}
      ${pendingDebitNotes.length
        ? `<div class="stock-dn-table-wrap"><table class="data"><thead><tr><th>Note</th><th>Payable effect</th><th></th></tr></thead><tbody>${dnRows}</tbody></table></div>`
        : `<div class="vo-wiz-empty"><p>No debit notes yet. Skip if the bill matches the goods.</p></div>`}
      <div class="stock-dn-summary">
        ${ctx.reviewRow("Lines receiving", String(received.length))}
        ${ctx.reviewRow("Lines on bill", String(billable.length))}
        ${ctx.reviewRow("Total bill", fmtPrice(receiptMeta.totalBilledAmount || 0))}
      </div>`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
      <button class="btn btn-primary" onclick="Stock.wizardNext()">Review →</button>`;
  }

  function renderReviewStep(bodyEl, footerEl) {
    const active = billableLines();
    const totals = calcReviewTotals(active);
    const dnRows = pendingDebitNotes.map((dn) => {
      const amt = dnPayableEffect(dn);
      const payLess = amt < 0;
      const comment = dn.notes ? ` — ${ctx.esc(dn.notes)}` : "";
      return `<tr>
        <td>${ctx.esc(dnDisplayLabel(dn))}${comment}</td>
        <td><span class="dn-effect-pill ${payLess ? "is-less" : "is-more"}">${payLess ? "Pay less" : "Pay more"} ${fmtPrice(Math.abs(amt))}</span></td>
      </tr>`;
    }).join("");
    bodyEl.innerHTML = `
      <div class="vo-wiz-review-hero">
        <span class="vo-wiz-review-label">Receiving from</span>
        <strong>${ctx.esc(placedOrder?.vendor_label || "—")}</strong>
        <span class="vo-wiz-review-stats">${active.length} line${active.length === 1 ? "" : "s"} · bill ${fmtPrice(totals.billAmount)}</span>
      </div>
      <div class="review-block" style="margin-bottom:16px;">
        ${ctx.reviewRow("Bill number", receiptMeta.billNumber || "—")}
        ${ctx.reviewRow("Bill amount", fmtPrice(totals.billAmount))}
        ${ctx.reviewRow("Debit notes", totals.dnAdj ? `${fmtPrice(totals.dnAdj)} (${totals.dnAdj < 0 ? "pay less" : "pay more"})` : "None")}
        ${ctx.reviewRow("Net payable", fmtPrice(totals.netPayable))}
      </div>
      <div class="stock-dn-table-wrap" style="margin-bottom:16px;">
        <table class="data"><thead><tr>
          <th>Product</th><th>Received</th><th>Billed</th>
        </tr></thead><tbody>
          ${active.map(l => `<tr>
            <td><strong>${ctx.esc(l.our_product_id)}</strong>${!(l.quantity_received || 0) && (l.quantity_billed || 0) ? ` <span class="badge badge-amber">Billed only</span>` : ""}</td>
            <td>${l.quantity_received || 0}</td>
            <td>${l.quantity_billed || 0}</td>
          </tr>`).join("")}
        </tbody></table>
      </div>
      ${pendingDebitNotes.length
        ? `<h4 style="margin:0 0 8px;font-size:15px;">Debit notes</h4>
           <div class="stock-dn-table-wrap"><table class="data"><thead><tr><th>Note</th><th>Effect</th></tr></thead><tbody>${dnRows}</tbody></table></div>`
        : ""}`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
      <button class="btn btn-primary btn-lg" onclick="Stock.submitReceipt()">Submit Receipt</button>`;
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
          _label: line?.our_product_id,
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

  function toggleOfflineProduct(productId, checked) {
    const prod = wizardProducts.find(p => p.id === productId);
    if (checked) {
      if (!wizardLines.find(l => l.catalog_product_id === productId)) {
        wizardLines.push({
          catalog_product_id: productId,
          our_product_id: prod?.our_product_id || "",
          buying_price: prod?.buying_price,
          image_urls: prod?.image_urls,
          quantity_received: 1,
          quantity_billed: 1,
        });
      }
    } else {
      wizardLines = wizardLines.filter(l => l.catalog_product_id !== productId);
    }
    renderWizard();
  }

  function setOfflineLine(productId, field, raw) {
    const line = wizardLines.find(l => l.catalog_product_id === productId);
    if (!line) return;
    line[field] = Math.max(0, parseInt(String(raw || "0"), 10) || 0);
    if (field === "quantity_received" && (!line.quantity_billed || line.quantity_billed === 0)) {
      line.quantity_billed = line.quantity_received;
    }
  }

  function pickVendor(id) {
    wizardVendorId = id || null;
    placedOrder = null; wizardLines = [];
    const sel = document.getElementById("stock-vendor-select");
    if (sel) sel.value = wizardVendorId ? String(wizardVendorId) : "";
    if (wizardMode === "offline_vendor" && wizardVendorId) {
      const opt = sel?.selectedOptions?.[0];
      placedOrder = { vendor_id: wizardVendorId, vendor_label: (opt?.textContent || "").trim() || "Offline vendor order" };
    }
    // Card picker re-renders; select path only updates button
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
  }

  function setBillFile(file) { billFile = file || null; billFileKey = null; }

  function wizardBack() {
    if (wizardStep > 1) {
      wizardStep--;
      if (wizardMode === "offline_vendor" && wizardStep === 1) wizardProducts = [];
      if (wizardStep < 3 && wizardMode !== "offline_vendor") { placedOrder = null; wizardLines = []; }
      renderWizard();
    } else if (wizardMode !== "offline_vendor") {
      wizardStep = 1; wizardMode = null; renderWizard();
    }
  }

  async function wizardNext() {
    if (wizardMode === "offline_vendor") {
      if (wizardStep === 1 && !wizardVendorId) return;
      if (wizardStep === 2) {
        if (!wizardLines.some(l => (l.quantity_received || 0) > 0 || (l.quantity_billed || 0) > 0)) {
          return ctx.toast("Enter qty received or billed", "error");
        }
      }
      if (wizardStep === 3) {
        saveReceiptMeta();
        const total = parseFloat(receiptMeta.totalBilledAmount);
        if (!receiptMeta.totalBilledAmount || Number.isNaN(total) || total <= 0) return ctx.toast("Enter total bill amount", "error");
      }
      wizardStep++;
      await renderWizard();
      return;
    }
    if (wizardStep === 2 && !wizardVendorId) return;
    if (wizardStep === 3) {
      const hasBillable = wizardLines.some(l => (l.quantity_received || 0) > 0 || (l.quantity_billed || 0) > 0);
      if (!hasBillable) return ctx.toast("Enter quantity received or billed on at least one row", "error");
      saveReceiptMeta();
      const total = parseFloat(receiptMeta.totalBilledAmount);
      if (!receiptMeta.totalBilledAmount || Number.isNaN(total) || total <= 0) {
        return ctx.toast("Enter total bill amount", "error");
      }
    }
    wizardStep++;
    await renderWizard();
  }

  async function uploadBill() {
    const billNum = receiptMeta.billNumber || (document.getElementById("stock-bill-number")?.value || "").trim();
    if (!billFile || !billNum) return null;
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
    const active = billableLines();
    if (!active.length) return ctx.toast("Enter received or billed quantities", "error");
    const endpoint = wizardMode === "offline_vendor" ? "/stock/receipts/offline-vendor" : "/stock/receipts/vendor-order";
    ctx.showLoading?.();
    try {
      let key = billFileKey;
      if (billFile && !key) key = await uploadBill();
      const billNum = receiptMeta.billNumber || null;
      const totalBilled = receiptMeta.totalBilledAmount ? parseFloat(receiptMeta.totalBilledAmount) : null;
      if (!totalBilled || totalBilled <= 0) return ctx.toast("Enter total bill amount", "error");
      const res = await ctx.api(endpoint, {
        method: "POST",
        body: JSON.stringify({
          vendor_id: wizardVendorId,
          bill_number: billNum,
          bill_file_key: key,
          additional_charges: null,
          total_billed_amount: totalBilled,
          lines: active.map(l => ({
            catalog_product_id: l.catalog_product_id,
            quantity_received: l.quantity_received || 0,
            quantity_billed: l.quantity_billed || 0,
            billed_amount: 0,
          })),
          debit_notes: pendingDebitNotes.map(dn => ({
            note_type: dn.note_type,
            direction: dn.direction || dn._direction || null,
            catalog_product_id: dn.catalog_product_id,
            quantity: dn.quantity,
            amount: dn.amount,
            notes: dn.notes || null,
          })),
        }),
      });
      ctx.invalidateCache?.("/stock");
      ctx.invalidateCache?.("/vendor-orders");
      ctx.invalidateCache?.("/accounts-payable");
      closeWizard();
      const totals = calcReviewTotals(active);
      let docUrl = res.document_url;
      if (!docUrl && res.receipt_id) {
        try {
          const doc = await ctx.api(`/stock/receipts/${res.receipt_id}/document`, {}, 0);
          docUrl = doc.document_url;
        } catch (_) {}
      }
      const dnHtml = pendingDebitNotes.length
        ? `<table class="data" style="font-size:13px;margin-top:12px;"><thead><tr><th>Debit Note</th><th>Effect</th></tr></thead><tbody>
            ${pendingDebitNotes.map(dn => {
              const effect = dnPayableEffect(dn);
              const payLess = effect < 0;
              const cmt = dn.notes ? ` — ${ctx.esc(dn.notes)}` : "";
              return `<tr><td>${ctx.esc(dnDisplayLabel(dn))}${cmt}</td><td>${payLess ? "Pay less" : "Pay more"} ${fmtPrice(Math.abs(effect))}</td></tr>`;
            }).join("")}
          </tbody></table>` : "";
      const lineHtml = `<table class="data" style="font-size:13px;margin-top:12px;"><thead><tr><th>Product</th><th>Received</th><th>Billed</th></tr></thead><tbody>
        ${active.map(l => `<tr><td>${ctx.esc(l.our_product_id)}</td><td>${l.quantity_received || 0}</td><td>${l.quantity_billed || 0}</td></tr>`).join("")}
      </tbody></table>`;
      const rid = res.receipt_id;
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
      ctx.openDetail?.("Goods received", `
        <div class="doc-success-banner">
          <strong>Receipt saved</strong>
          <span>Receipt #${rid}${receiptMeta.billNumber ? ` · Bill ${ctx.esc(receiptMeta.billNumber)}` : ""}</span>
        </div>
        <div class="review-block" style="margin-bottom:12px;">
          ${ctx.reviewRow("Vendor", placedOrder?.vendor_label || "—")}
          ${ctx.reviewRow("Bill number", receiptMeta.billNumber || "—")}
          ${ctx.reviewRow("Bill amount", fmtPrice(totals.billAmount))}
          
          ${totals.dnAdj ? ctx.reviewRow("Debit note adj.", fmtPrice(totals.dnAdj)) : ""}
          ${ctx.reviewRow("Net payable", fmtPrice(totals.netPayable))}
        </div>
        ${lineHtml}
        ${dnHtml}
        ${pdfBtns}`,
        `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Done</button>`, "md");
      ctx.toast(wizardMode === "offline_vendor" ? "Offline order created" : "Stock received", "success");
      if (typeof VendorOrders !== "undefined" && VendorOrders.refreshIfOpen) VendorOrders.refreshIfOpen(wizardVendorId);
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

  function renderReceiptDetail(title, entryType, qtyDelta, balanceAfter, when, notes, receipt) {
    const meta = [
      entryType ? ctx.reviewRow("Type", entryType) : "",
      qtyDelta != null ? ctx.reviewRow("Quantity", (qtyDelta > 0 ? "+" : "") + qtyDelta) : "",
      balanceAfter != null ? ctx.reviewRow("Balance after", balanceAfter) : "",
      ctx.reviewRow("Date", new Date(when).toLocaleString()),
      notes ? ctx.reviewRow("Notes", notes) : "",
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
        `<tr><td>${ctx.esc(l.our_product_id)}</td><td>${l.quantity_received}</td><td>${l.quantity_billed || 0}</td>${showAmt ? `<td>${l.billed_amount ? fmtPrice(l.billed_amount) : "—"}</td>` : ""}</tr>`
      ).join("");
      table = `<table class="data" style="font-size:13px;"><thead><tr><th>Product</th><th>Received</th><th>Billed Qty</th>${showAmt ? "<th>Billed Amt</th>" : ""}</tr></thead><tbody>${lineRows}</tbody></table>`;
    }
    if (receipt?.bill_file_url) {
      extra = `<p style="margin-top:8px;"><a href="${ctx.esc(receipt.bill_file_url)}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm">View bill file</a></p>`;
    }
    ctx.openDetail(title, ctx.ledgerDetailCard("Receipt details", meta, table, extra), ctx.detailFooterChild(), "md", { push: true });
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
      if (typeof Products !== "undefined") Products.load?.();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  return {
    init, load, setViewMode, render, openDetail, openLedgerDetail, openReceiptDetail,
    openAddWizard, openReceiveForVendor, openOfflineWizard, openOfflineForVendor, closeWizard, pickMode, pickVendor, setLine, setBillFile,
    toggleOfflineProduct, setOfflineLine,
    wizardBack, wizardNext, submitReceipt, openDebitNote, removeDebitNote, editThreshold, setSellingPrice,
    openReceiptPdf, fetchReceiptPdf,
  };
})();
