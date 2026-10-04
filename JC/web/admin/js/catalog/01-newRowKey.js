  function newRowKey() { return `row-${++_rowCounter}`; }

  function apiBase() {
    const saved = localStorage.getItem("jc_api");
    if (saved) return saved;
    const host = location.hostname;
    if (host === "127.0.0.1" || host === "localhost") return "http://127.0.0.1:8003/api/v1";
    return `${location.origin}/api/v1`;
  }

  function adminKey() {
    return sessionStorage.getItem("jc_admin_key") || "";
  }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function vendorLabel(v) {
    if (!v) return "—";
    const name = v.business_name || v.alias || `Vendor #${v.id}`;
    return v.city_name ? `${name} — ${v.city_name}` : name;
  }

  function skuYearKey(sku, yearGroup) {
    const s = (sku || "").trim().toLowerCase();
    const y = (yearGroup || "").trim().toLowerCase();
    return y ? `${s}|${y}` : s;
  }

  async function checkWizardDuplicates() {
    const filled = filledWizardRows();
    if (!filled.length) { wizardDupes = []; return; }
    try {
      const res = await ctx.api("/catalog/products/check-duplicates", {
        method: "POST",
        body: JSON.stringify({
          items: filled.map(r => ({
            our_product_id: r.our_product_id.trim(),
            year_group: r.year_group || null,
          })),
        }),
      });
      wizardDupes = res.duplicates || [];
    } catch (_) {
      wizardDupes = filled
        .filter(r => products.some(p =>
          skuYearKey(p.our_product_id, p.year_group) === skuYearKey(r.our_product_id, r.year_group)
        ))
        .map(r => r.our_product_id);
    }
  }

  function setVendors(list) {
    catalogVendors = (list || []).filter(v => v.is_active !== false && !v.deleted_at);
  }

  async function ensureVendors() {
    if (catalogVendors.length) return catalogVendors;
    if (ctx.getVendors) {
      const cached = (ctx.getVendors() || []).filter(v => v.is_active && !v.deleted_at);
      if (cached.length) {
        catalogVendors = cached;
        return catalogVendors;
      }
    }
    try {
      catalogVendors = await ctx.api("/catalog/vendors", {}, 60000);
    } catch (_) {
      try {
        catalogVendors = await ctx.api("/vendors", {}, 0);
      } catch (e2) {
        catalogVendors = [];
        throw e2;
      }
    }
    catalogVendors = (catalogVendors || []).filter(v => v.is_active !== false);
    return catalogVendors;
  }

  function lookups(type) {
    const all = ctx.getLookups ? ctx.getLookups() : [];
    if (Array.isArray(all)) return all.filter(l => l.lookup_type === type).map(l => l.value);
    return all[type] || [];
  }

  const DEFAULT_YEAR_GROUP = "2026-27";

  function emptyWizardRow() {
    return {
      _key: newRowKey(),
      selected: false,
      our_product_id: "",
      vendor_product_id: "",
      imageFiles: [],
      category: "",
      series: "",
      unit: "pcs",
      year_group: DEFAULT_YEAR_GROUP,
      buying_price: "",
      selling_price: "",
      alternative_our_product_ids: [],
      addon_links: [],
    };
  }

  function yearSelectHtml(selected, { id = "", onchange = "", allowEmpty = false } = {}) {
    const admin = !!ctx.isAdmin?.();
    const chosen = (selected && String(selected).trim()) || DEFAULT_YEAR_GROUP;
    if (!admin) {
      return `<select class="input" style="font-size:12px;" disabled title="Only admin can change year group">
        <option value="${ctx.esc(DEFAULT_YEAR_GROUP)}" selected>${ctx.esc(DEFAULT_YEAR_GROUP)}</option>
      </select><input type="hidden" ${id ? `id="${id}"` : ""} value="${ctx.esc(DEFAULT_YEAR_GROUP)}" />`;
    }
    const vals = productYearGroups;
    const opts = new Set(vals);
    // Always include default so create UI can pre-select it even if lookups lag.
    if (!opts.has(DEFAULT_YEAR_GROUP)) opts.add(DEFAULT_YEAR_GROUP);
    if (chosen && !opts.has(chosen)) opts.add(chosen);
    const empty = allowEmpty ? `<option value="">—</option>` : "";
    const options = [...opts].map(v =>
      `<option value="${ctx.esc(v)}" ${chosen === v ? "selected" : ""}>${ctx.esc(v)}</option>`
    ).join("");
    return `<select ${id ? `id="${id}"` : ""} class="input" style="font-size:12px;" ${onchange ? `onchange="${onchange}"` : ""}>
      ${empty}${options}
    </select>`;
  }

  function filledWizardRows() {
    return wizardRows.filter(r => r.our_product_id.trim() && r.vendor_product_id.trim());
  }

  function init(context) {
    ctx = context;
    // List UI lives in Products hub; register no-op for legacy TableUtils callers.
    TableUtils.register("catalog", () => {});
  }

  async function loadAddons() {
    try {
      addons = await ctx.api("/addons");
    } catch (_) {
      addons = [];
    }
  }

  async function load() {
    // Live hub is Products
    if (typeof Products !== "undefined" && Products.refreshHub) await Products.refreshHub();
  }

  async function openDetail(id) {
    if (typeof Products !== "undefined" && Products.openProductDetail) {
      return Products.openProductDetail(id, "catalog");
    }
    const p = await ctx.api(`/catalog/products/${id}`);
    let stockRow = null;
    try { stockRow = await ctx.api(`/stock/products/${id}`, {}, 0); } catch (_) {}
    const stockHtml = stockRow ? `<div class="detail-section" style="margin-bottom:20px;">
      <h4>Stock</h4>
      <div class="review-grid">
        ${ctx.reviewRow("On hand", stockRow.quantity_on_hand)}
        ${ctx.reviewRow("Status", stockRow.stock_status?.replace(/_/g, " "))}
        ${ctx.reviewRow("Pending order", stockRow.quantity_pending)}
        ${ctx.reviewRow("Low threshold", stockRow.low_stock_threshold)}
      </div>
      <button type="button" class="btn btn-secondary btn-sm" style="margin-top:10px;" onclick="Stock.openDetail(${p.id})">Open stock + ledger</button>
    </div>` : `<div class="detail-section" style="margin-bottom:20px;">
      <h4>Stock</h4>
      <p style="color:var(--muted);font-size:14px;margin:0;">No stock balance yet — receive goods to create it.</p>
    </div>`;
    const images = (p.image_urls || []).length
      ? `<div class="catalog-detail-images">${p.image_urls.map(u => `<img src="${ctx.esc(u)}" alt="" onclick="Products.enlargeImage(decodeURIComponent('${encodeURIComponent(u)}'))" style="cursor:zoom-in;" />`).join("")}</div>`
      : "";

    const altHtml = p.alternatives?.length
      ? `<div class="alt-chip-row">${p.alternatives.map(a => {
          const img = (a.image_urls && a.image_urls[0]) || "";
          const place = [a.alternative_vendor_name, a.alternative_vendor_city].filter(Boolean).join(" · ");
          return `<button type="button" class="alt-chip" onclick="Products.enlargeImage(decodeURIComponent('${encodeURIComponent(img || "")}'))">
            ${img ? `<img src="${ctx.esc(img)}" alt="" />` : `<span class="alt-chip-empty"></span>`}
            <span class="alt-chip-body">
              <strong>${ctx.esc(a.alternative_our_product_id)}</strong>
              <span>${ctx.esc(place || "—")}</span>
              <span>${a.buying_price ? fmtPrice(a.buying_price) : "—"}${a.selling_price ? ` / ${fmtPrice(a.selling_price)}` : ""}</span>
            </span>
          </button>`;
        }).join("")}</div>`
      : '<p style="color:var(--muted);font-size:14px;">No alternatives</p>';

    const addonHtml = p.addon_links?.length
      ? `<div class="alt-chip-row">${p.addon_links.map(l => {
          const img = (l.image_urls && l.image_urls[0]) || "";
          return `<div class="alt-chip is-static">
            ${img ? `<img src="${ctx.esc(img)}" alt="" onclick="Products.enlargeImage(decodeURIComponent('${encodeURIComponent(img)}'))" style="cursor:zoom-in;" />` : `<span class="alt-chip-empty"></span>`}
            <span class="alt-chip-body">
              <strong>${ctx.esc(l.addon_our_product_id)}</strong>
              <span>${ctx.esc(l.addon_name || "Add-on")} · qty ${l.quantity}</span>
            </span>
          </div>`;
        }).join("")}</div>`
      : '<p style="color:var(--muted);font-size:14px;">No add-on links</p>';

    const priceHist = p.price_history?.length
      ? `<table class="data"><thead><tr><th>Buy</th><th>Sell</th><th>Recorded</th></tr></thead><tbody>
          ${p.price_history.map(h => `<tr><td>${fmtPrice(h.buying_price)}</td><td>${h.selling_price ? fmtPrice(h.selling_price) : "—"}</td><td style="font-size:13px;">${ctx.fmtDate(h.recorded_at)}</td></tr>`).join("")}
        </tbody></table>`
      : '<p style="color:var(--muted);font-size:14px;">No price history</p>';

    const changeHist = ctx.changeHistoryTable
      ? ctx.changeHistoryTable(p.change_history)
      : '<p style="color:var(--muted);font-size:14px;">No change history</p>';

    ctx.openDetail(p.our_product_id, `
      <div class="profile-hero" style="margin:-24px -24px 24px;border-radius:0;">
        <h2>${ctx.esc(p.our_product_id)}${p.year_group ? ` <span class="prod-year-pill">${ctx.esc(p.year_group)}</span>` : ""}</h2>
        <p>${ctx.esc(p.vendor_name || "—")}${p.vendor_city ? ` · ${ctx.esc(p.vendor_city)}` : ""}</p>
        <div class="profile-meta">
          <span class="badge badge-green">Sell ${p.selling_price ? fmtPrice(p.selling_price) : "—"}</span>
          <span class="badge badge-blue">Buy ${fmtPrice(p.buying_price)}</span>
          ${p.category ? `<span class="badge badge-gray">${ctx.esc(p.category)}</span>` : ""}
          ${p.second_category ? `<span class="badge badge-gray">${ctx.esc(p.second_category)}</span>` : ""}
        </div>
        ${images}
      </div>
      <div class="review-grid" style="margin-bottom:20px;">
        ${ctx.reviewRow("Vendor Product ID", p.vendor_product_id)}
        ${ctx.reviewRow("Year Group", p.year_group)}
        ${ctx.reviewRow("Created", ctx.fmtDate(p.created_at))}
        ${ctx.reviewRow("Updated", ctx.fmtDate(p.updated_at))}
      </div>
      <div class="detail-section"><h4>Alternatives</h4>${altHtml}</div>
      <div class="detail-section"><h4>Add-on Links</h4>${addonHtml}</div>
      ${stockHtml}
      <div class="detail-section"><h4>Price History</h4>${priceHist}</div>
      ${changeHist}`,
      `${(ctx.canWrite?.("catalog") || ctx.isAdmin?.()) ? `<button class="btn btn-danger btn-sm" onclick="Catalog.deleteProduct(${p.id})">Delete</button>
       <button type="button" class="btn btn-secondary btn-sm" onclick="event.stopPropagation();Catalog.openEdit(${p.id})">Edit</button>` : ""}
       <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "lg"
    );
  }

  async function openWizard(presetVendorId) {
    ctx.showLoading?.();
    // Always fetch fresh vendor list so a newly created vendor appears immediately
    catalogVendors = [];
    try {
      await ensureVendors();
      await ensureProductCategories();
      await ensureProductYears();
    } catch (e) {
      ctx.toast(e.message || "Could not load vendors", "error");
      return;
    } finally {
      ctx.hideLoading?.();
    }
    if (!catalogVendors.length) {
      ctx.toast("Add vendors in People first", "error");
      return;
    }
    wizardStep = 1;
    wizardVendorId = presetVendorId || null;
    wizardRows = [emptyWizardRow()];
    wizardCreatedProducts = [];
    products = [];
    _loadVendorProducts(wizardVendorId);
    document.getElementById("catalog-wizard")?.classList.remove("hidden");
    loadAddons().then(renderWizard);
  }

  function openWizardForVendor(vendorId) {
    return openWizard(vendorId || null);
  }

  function closeWizard() {
    document.getElementById("catalog-wizard")?.classList.add("hidden");
  }

  function renderWizardSteps() {
    const el = document.getElementById("catalog-wizard-steps");
    if (!el) return;
    el.innerHTML = STEP_LABELS.map((label, i) => {
      const n = i + 1;
      const cls = n < wizardStep ? "done" : n === wizardStep ? "active" : "";
      return `<div class="step ${cls}"><div class="step-num">${n < wizardStep ? "✓" : n}</div>${label}</div>`;
    }).join("");
  }

  let productCategories = [];
  let productYearGroups = [];

  async function ensureProductCategories() {
    if (productCategories.length) return productCategories;
    try {
      productCategories = await ctx.api("/catalog/categories") || [];
    } catch (_) {
      productCategories = [];
    }
    return productCategories;
  }

  async function ensureProductYears() {
    if (productYearGroups.length) return productYearGroups;
    try {
      productYearGroups = await ctx.api("/catalog/year-groups") || [];
    } catch (_) {
      productYearGroups = [];
    }
    if (!productYearGroups.includes(DEFAULT_YEAR_GROUP)) productYearGroups = [DEFAULT_YEAR_GROUP, ...productYearGroups];
    return productYearGroups;
  }

  function categoryField(id, selected, onchange) {
    const listId = `${id}-list`;
    const opts = productCategories.map(v => `<option value="${ctx.esc(v)}"></option>`).join("");
    return `<input id="${id}" class="input" list="${listId}" value="${ctx.esc(selected || "")}" ${onchange ? `oninput="${onchange}"` : ""} />
      <datalist id="${listId}">${opts}</datalist>`;
  }

  function wizardImageThumbs(row) {
    if (!row.imageFiles?.length) return "";
    return `<div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:4px;">${row.imageFiles.map((f, i) => {
      const url = (row._previewUrls && row._previewUrls[i]) || "";
      return url ? `<img src="${url}" alt="" style="width:40px;height:40px;object-fit:cover;border-radius:6px;border:1px solid var(--border);" />` : "";
    }).join("")}</div>`;
  }

  function renderWizardStep1(body, footer) {
    body.innerHTML = `
      <div class="create-form">
        <div class="create-band">
          <div>
            <label class="label">Vendor *</label>
            <select id="cw-vendor_id" class="input" onchange="Catalog.setWizardVendor(this.value)">
              <option value="">— Select vendor —</option>
              ${catalogVendors.map(v => `<option value="${v.id}" ${wizardVendorId == v.id ? "selected" : ""}>${ctx.esc(vendorLabel(v))}</option>`).join("")}
            </select>
          </div>
          <div style="display:flex;align-items:center;gap:8px;">
              <button type="button" class="btn btn-primary btn-sm" onclick="Catalog.addWizardRow()">+ Add product</button>
              <button type="button" class="btn btn-secondary btn-sm" onclick="Catalog.removeWizardRows()" title="Remove checked rows">Remove selected</button>
          </div>
        </div>
        <div class="table-wrap">
          <table class="data">
            <thead><tr>
              <th style="width:36px;"><input type="checkbox" onchange="Catalog.toggleAllWizardRows(this.checked)" /></th>
              <th>Our code *</th>
              <th>Vendor code *</th>
              <th>Photos</th>
              <th style="width:36px;"></th>
            </tr></thead>
            <tbody>
              ${wizardRows.map((row, idx) => `
                <tr>
                  <td><input type="checkbox" ${row.selected ? "checked" : ""} onchange="Catalog.toggleWizardRow(${idx}, this.checked)" /></td>
                  <td><input class="input" style="font-size:13px;" value="${ctx.esc(row.our_product_id)}" placeholder="e.g. BC-001"
                    oninput="Catalog.updateWizardRow(${idx}, 'our_product_id', this.value)"
                    onblur="Catalog.maybeAddWizardRow(${idx})" /></td>
                  <td><input class="input" style="font-size:13px;" value="${ctx.esc(row.vendor_product_id)}" placeholder="Their SKU"
                    oninput="Catalog.updateWizardRow(${idx}, 'vendor_product_id', this.value)"
                    onblur="Catalog.maybeAddWizardRow(${idx})" /></td>
                  <td>
                    <input type="file" multiple accept="image/*" class="input" style="font-size:12px;padding:6px;"
                      onchange="Catalog.setWizardImages(${idx}, this.files)" />
                    ${wizardImageThumbs(row)}
                  </td>
                  <td>
                    <button type="button" title="Delete row" onclick="Catalog.deleteWizardRow(${idx})"
                      style="background:none;border:none;color:var(--danger,#ef4444);font-size:18px;cursor:pointer;padding:4px 8px;line-height:1;">✕</button>
                  </td>
                </tr>`).join("")}
            </tbody>
          </table>
        </div>
      </div>`;
    footer.innerHTML = `
      <button class="btn btn-secondary" onclick="Catalog.closeWizard()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Catalog.wizardNext()">Next →</button>`;
  }

  function renderWizardStep2(body, footer) {
    const filled = filledWizardRows();
    body.innerHTML = `
      <div class="create-form">
        <div class="card" style="padding:16px;background:#eff6ff;border-color:#bfdbfe;">
          <div style="font-size:12px;font-weight:700;color:var(--brand);margin-bottom:10px;">Apply to selected rows</div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;align-items:end;">
            <div><label class="label">Category</label>${categoryField("cw-bulk-category", "")}</div>
            <div><label class="label">Year ${ctx.isAdmin?.() ? "" : "(admin)"}</label>${yearSelectHtml(DEFAULT_YEAR_GROUP, { id: "cw-bulk-year_group", allowEmpty: true })}</div>
            <div><label class="label">Buy (₹)</label><input id="cw-bulk-buying_price" class="input" type="number" min="0" step="0.01" style="font-size:13px;" /></div>
            <div><label class="label">Sell (₹)</label><input id="cw-bulk-selling_price" class="input" type="number" min="0" step="0.01" style="font-size:13px;" /></div>
            <button type="button" class="btn btn-primary btn-sm" onclick="Catalog.applyBulkFields()">Apply</button>
          </div>
        </div>
        <div class="table-wrap">
          <table class="data" style="font-size:13px;">
            <thead><tr>
              <th style="width:36px;"></th>
              <th>Our code</th>
              <th>Category</th>
              <th>Year</th>
              <th>Buy</th>
              <th>Sell</th>
            </tr></thead>
            <tbody>
              ${filled.map((row) => {
                const idx = wizardRows.indexOf(row);
                return `<tr>
                  <td><input type="checkbox" ${row.selected ? "checked" : ""} onchange="Catalog.toggleWizardRow(${idx}, this.checked)" /></td>
                  <td><strong>${ctx.esc(row.our_product_id)}</strong></td>
                  <td>${categoryField(`cw-cat-${idx}`, row.category, `Catalog.updateWizardRow(${idx}, 'category', this.value)`)}</td>
                  <td>${yearSelectHtml(row.year_group || DEFAULT_YEAR_GROUP, { onchange: `Catalog.updateWizardRow(${idx}, 'year_group', this.value)` })}</td>
                  <td><input class="input" type="number" min="0" step="0.01" style="font-size:12px;width:90px;" value="${ctx.esc(row.buying_price)}"
                    oninput="Catalog.updateWizardRow(${idx}, 'buying_price', this.value)" /></td>
                  <td><input class="input" type="number" min="0" step="0.01" style="font-size:12px;width:90px;" value="${ctx.esc(row.selling_price)}"
                    oninput="Catalog.updateWizardRow(${idx}, 'selling_price', this.value)" /></td>
                </tr>`;
              }).join("")}
            </tbody>
          </table>
        </div>
      </div>`;
    footer.innerHTML = `
      <button class="btn btn-secondary" onclick="Catalog.wizardBack()">Back</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Catalog.wizardNext()">Review →</button>`;
  }

  function renderWizardStep3(body, footer) {
    const vendor = catalogVendors.find(v => v.id == wizardVendorId);
    const filled = filledWizardRows();
    const dupes = wizardDupes.length
      ? wizardDupes
      : filled
          .filter(r => products.some(p => skuYearKey(p.our_product_id, p.year_group) === skuYearKey(r.our_product_id, r.year_group)))
          .map(r => skuYearKey(r.our_product_id, r.year_group));

    body.innerHTML = `
      ${dupes.length ? `<div class="card" style="padding:14px;margin-bottom:16px;background:#fffbeb;border-color:#fde68a;">
        <strong style="color:#b45309;">${dupes.length} duplicate ID(s)</strong>
        <p style="margin:6px 0 0;font-size:13px;color:#92400e;">${dupes.map(d => ctx.esc(typeof d === "string" ? d : d.our_product_id)).join(", ")} already exist for the same year group. Same ID is allowed in a different year group.</p>
      </div>` : ""}
      <div class="review-grid" style="margin-bottom:16px;">
        ${ctx.reviewRow("Vendor", vendor ? vendorLabel(vendor) : "—")}
        ${ctx.reviewRow("Products", String(filled.length))}
      </div>
      <div class="table-wrap">
        <table class="data" style="font-size:13px;">
          <thead><tr>
            <th>Our code</th><th>Vendor code</th><th>Category</th><th>Buy</th><th>Sell</th><th>Photos</th>
          </tr></thead>
          <tbody>
            ${filled.map(r => `<tr>
              <td><strong>${ctx.esc(r.our_product_id)}</strong></td>
              <td>${ctx.esc(r.vendor_product_id)}</td>
              <td>${ctx.esc(r.category || "—")}</td>
              <td>${r.buying_price ? fmtPrice(r.buying_price) : "—"}</td>
              <td>${r.selling_price ? fmtPrice(r.selling_price) : "—"}</td>
              <td>${wizardImageThumbs(r) || "—"}</td>
            </tr>`).join("")}
          </tbody>
        </table>
      </div>`;
    footer.innerHTML = `
      <button class="btn btn-secondary" onclick="Catalog.wizardBack()">Back</button>
      <button class="btn btn-primary" style="flex:1;" id="catalog-create-btn" onclick="Catalog.createAll()" ${dupes.length ? "disabled" : ""}>Create all</button>`;
  }

  function renderWizardStep4(body, footer) {
    const vendor = catalogVendors.find(v => v.id == wizardVendorId);
    const rows = wizardCreatedProducts.length ? wizardCreatedProducts : filledWizardRows();
    body.innerHTML = `
      <div style="text-align:center;padding:8px 0 16px;">
        <div class="success-icon">✓</div>
        <h3 style="margin:0 0 4px;">Products created</h3>
        <p style="color:var(--muted);margin:0;">${wizardCreatedProducts.length || filledWizardRows().length} product(s) added${vendor ? ` for ${ctx.esc(vendorLabel(vendor))}` : ""}</p>
      </div>
      <div class="table-wrap">
        <table class="data" style="font-size:13px;">
          <thead><tr>
            <th></th><th>Our code</th><th>Vendor code</th><th>Category</th><th>Buy</th><th>Sell</th>
          </tr></thead>
          <tbody>
            ${rows.map(p => {
              const img = (p.image_urls && p.image_urls[0]) || "";
              const thumb = img
                ? `<img src="${ctx.esc(img)}" alt="" class="vo-thumb" />`
                : `<div class="vo-thumb vo-thumb-empty">—</div>`;
              return `<tr>
                <td>${thumb}</td>
                <td><strong>${ctx.esc(p.our_product_id)}</strong></td>
                <td>${ctx.esc(p.vendor_product_id || "—")}</td>
                <td>${ctx.esc(p.category || "—")}</td>
                <td>${fmtPrice(p.buying_price)}</td>
                <td>${p.selling_price ? fmtPrice(p.selling_price) : "—"}</td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>`;
    footer.innerHTML = `
      <button class="btn btn-secondary" onclick="Catalog.openWizard()">+ Another batch</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Catalog.closeWizard()">Done</button>`;
  }

