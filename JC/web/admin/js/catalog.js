/** Catalog module — grid, wizard, detail, edit */
const Catalog = (() => {
  let ctx = {};
  let products = [];
  let productsTotal = 0;
  let productsOffset = 0;
  const PAGE_SIZE = 60;
  let addons = [];
  let viewMode = "grid";
  let wizardStep = 1;
  let wizardVendorId = null;
  let wizardRows = [];
  let wizardSelectedRowIdx = 0;
  let editingId = null;
  let editReturnTo = null;
  let wizardCreatedProducts = [];
  let catalogVendors = [];
  let wizardDupes = [];

  const MAX_ALTERNATIVES = 3;
  const STEP_LABELS = ["Vendor & Products", "Details & Pricing", "Alternatives & Add-ons", "Review & Create"];

  const CATALOG_COLS = [
    { key: "our_product_id", label: "Product ID", get: p => p.our_product_id },
    { key: "vendor", label: "Vendor", get: p => `${p.vendor_name || ""} ${p.vendor_city || ""}` },
    { key: "category", label: "Category", get: p => p.category || "" },
    { key: "buying_price", label: "Buy Price", get: p => p.buying_price || "" },
    { key: "selling_price", label: "Sell Price", get: p => p.selling_price || "" },
    { key: "_actions", label: "", filterable: false, sortable: false },
  ];

  let _rowCounter = 0;
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

  async function checkWizardDuplicates() {
    const filled = filledWizardRows();
    if (!filled.length) { wizardDupes = []; return; }
    try {
      const res = await ctx.api("/catalog/products/check-duplicates", {
        method: "POST",
        body: JSON.stringify({ our_product_ids: filled.map(r => r.our_product_id.trim()) }),
      });
      wizardDupes = res.duplicates || [];
    } catch (_) {
      wizardDupes = filled.filter(r => products.some(p => p.our_product_id.toLowerCase() === r.our_product_id.trim().toLowerCase())).map(r => r.our_product_id);
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

  function emptyWizardRow() {
    const ygs = lookups("year_group");
    return {
      _key: newRowKey(),
      selected: false,
      our_product_id: "",
      vendor_product_id: "",
      imageFiles: [],
      category: "",
      series: "",
      unit: lookups("unit")[0] || "pcs",
      year_group: ygs[0] || "",
      buying_price: "",
      selling_price: "",
      alternative_our_product_ids: [],
      addon_links: [],
    };
  }

  function filledWizardRows() {
    return wizardRows.filter(r => r.our_product_id.trim() && r.vendor_product_id.trim());
  }

  function productImage(p) {
    const url = (p.image_urls && p.image_urls[0]) || "";
    if (url) return `<img src="${ctx.esc(url)}" alt="" class="catalog-card-img" />`;
    return `<div class="catalog-card-img catalog-card-img-empty">No image</div>`;
  }

  function init(context) {
    ctx = context;
    TableUtils.register("catalog", renderTable);
  }

  async function loadAddons() {
    try {
      addons = await ctx.api("/addons");
    } catch (_) {
      addons = [];
    }
  }

  async function load(append = false) {
    if (!append) productsOffset = 0;
    ensureVendors().catch(() => {});
    const q = document.getElementById("catalog-search-input")?.value.trim() || "";
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(productsOffset) });
    if (q) params.set("search", q);
    ctx.showLoading?.();
    try {
      const res = await ctx.api(`/catalog/products?${params}`);
      const items = res.items || res;
      productsTotal = res.total ?? items.length;
      products = append ? products.concat(items) : items;
      productsOffset = products.length;
      render();
    } finally {
      ctx.hideLoading?.();
    }
  }

  function loadMore() {
    if (products.length >= productsTotal) return;
    load(true);
  }

  function setViewMode(mode) {
    viewMode = mode === "list" ? "list" : "grid";
    document.getElementById("catalog-view-grid")?.classList.toggle("active", viewMode === "grid");
    document.getElementById("catalog-view-list")?.classList.toggle("active", viewMode === "list");
    document.getElementById("catalog-grid")?.classList.toggle("hidden", viewMode === "list");
    document.getElementById("catalog-table")?.classList.toggle("hidden", viewMode !== "list");
    render();
  }

  function render() {
    if (viewMode === "list") renderTable();
    else renderGrid();
  }

  function renderGrid() {
    const el = document.getElementById("catalog-grid");
    if (!el) return;
    if (!products.length) {
      el.innerHTML = '<div class="empty-state"><p>No catalog products yet.</p><button class="btn btn-primary btn-lg" style="margin-top:16px;" onclick="Catalog.openWizard()">+ Add Products</button></div>';
      return;
    }
    el.innerHTML = `<div class="catalog-grid">${products.map(p => `
      <button type="button" class="catalog-card" onclick="Catalog.openDetail(${p.id})">
        ${productImage(p)}
        <div class="catalog-card-body">
          <div class="catalog-card-title">${ctx.esc(p.our_product_id)}</div>
          <div class="catalog-card-vendor">${ctx.esc(p.vendor_name || "—")}</div>
          <div class="catalog-card-city">${ctx.esc(p.vendor_city || "—")}</div>
          <div class="catalog-card-price">${fmtPrice(p.buying_price)}</div>
        </div>
      </button>`).join("")}</div>
      ${products.length < productsTotal ? `<div style="text-align:center;margin-top:20px;"><button class="btn btn-secondary" onclick="Catalog.loadMore()">Load more (${products.length} of ${productsTotal})</button></div>` : `<p style="text-align:center;margin-top:12px;color:var(--muted);font-size:13px;">Showing all ${productsTotal} products</p>`}`;
  }

  function renderTable() {
    const el = document.getElementById("catalog-table");
    if (!el) return;
    if (!products.length) {
      el.innerHTML = '<div class="empty-state"><p>No catalog products yet.</p><button class="btn btn-primary btn-lg" style="margin-top:16px;" onclick="Catalog.openWizard()">+ Add Products</button></div>';
      return;
    }
    const rows = TableUtils.apply(products, "catalog", CATALOG_COLS);
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("catalog", CATALOG_COLS)}<tbody>
      ${rows.map(p => `<tr class="clickable" onclick="Catalog.openDetail(${p.id})">
        <td><strong>${ctx.esc(p.our_product_id)}</strong><br><span style="font-size:12px;color:var(--muted);">${ctx.esc(p.vendor_product_id)}</span></td>
        <td>${ctx.esc(p.vendor_name || "—")}<br><span style="font-size:12px;color:var(--muted);">${ctx.esc(p.vendor_city || "—")}</span></td>
        <td>${ctx.esc(p.category || "—")}</td>
        <td>${fmtPrice(p.buying_price)}</td>
        <td>${p.selling_price ? fmtPrice(p.selling_price) : "—"}</td>
        <td onclick="event.stopPropagation()"></td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  async function openDetail(id) {
    const p = await ctx.api(`/catalog/products/${id}`);
    let stockRow = null;
    try { stockRow = await ctx.api(`/stock/products/${id}`, {}, 0); } catch (_) {}
    const stockHtml = stockRow ? `<div class="detail-section" style="margin-bottom:20px;">
      <h4>Stock Status</h4>
      <div class="review-grid">
        ${ctx.reviewRow("On hand", stockRow.quantity_on_hand)}
        ${ctx.reviewRow("Status", stockRow.stock_status?.replace(/_/g, " "))}
        ${ctx.reviewRow("Low threshold", stockRow.low_stock_threshold)}
      </div></div>` : "";
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

    ctx.openDetail("Product Details", `
      <div class="profile-hero" style="margin:-24px -24px 24px;border-radius:0;">
        <h2>${ctx.esc(p.our_product_id)}</h2>
        <p>${ctx.esc(p.vendor_name || "—")}${p.vendor_city ? ` · ${ctx.esc(p.vendor_city)}` : ""}</p>
        <div class="profile-meta">
          <span class="badge badge-blue">${fmtPrice(p.buying_price)}</span>
          ${p.selling_price ? `<span class="badge badge-green">${fmtPrice(p.selling_price)} sell</span>` : ""}
          ${p.category ? `<span class="badge badge-gray">${ctx.esc(p.category)}</span>` : ""}
        </div>
        ${images}
      </div>
      <div class="review-grid" style="margin-bottom:20px;">
        ${ctx.reviewRow("Vendor Product ID", p.vendor_product_id)}
        ${ctx.reviewRow("Series", p.series)}
        ${ctx.reviewRow("Unit", p.unit)}
        ${ctx.reviewRow("Year Group", p.year_group)}
        ${ctx.reviewRow("Created", ctx.fmtDate(p.created_at))}
        ${ctx.reviewRow("Updated", ctx.fmtDate(p.updated_at))}
      </div>
      <div class="detail-section"><h4>Alternatives</h4>${altHtml}</div>
      <div class="detail-section"><h4>Add-on Links</h4>${addonHtml}</div>
      ${stockHtml}
      <div class="detail-section"><h4>Price History</h4>${priceHist}</div>
      ${changeHist}`,
      `${ctx.canWrite?.("catalog") ? `<button class="btn btn-danger btn-sm" onclick="Catalog.deleteProduct(${p.id})">Delete</button>
       <button class="btn btn-secondary btn-sm" onclick="Catalog.openEdit(${p.id})">Edit</button>` : ""}
       <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "lg"
    );
  }

  async function openWizard() {
    ctx.showLoading?.();
    try {
      await ensureVendors();
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
    wizardVendorId = null;
    wizardRows = [emptyWizardRow()];
    wizardSelectedRowIdx = 0;
    wizardCreatedProducts = [];
    document.getElementById("catalog-wizard")?.classList.remove("hidden");
    loadAddons().then(renderWizard);
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

  function lookupOptions(type, selected) {
    const vals = lookups(type);
    return vals.map(v => `<option value="${ctx.esc(v)}" ${selected === v ? "selected" : ""}>${ctx.esc(v)}</option>`).join("");
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
      <div style="display:grid;gap:16px;">
        <div>
          <label class="label">Vendor *</label>
          <select id="cw-vendor_id" class="input" onchange="Catalog.setWizardVendor(this.value)">
            <option value="">— Select vendor —</option>
            ${catalogVendors.map(v => `<option value="${v.id}" ${wizardVendorId == v.id ? "selected" : ""}>${ctx.esc(vendorLabel(v))}</option>`).join("")}
          </select>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <p style="margin:0;font-size:13px;color:var(--muted);">Add product rows with images</p>
          <div style="display:flex;gap:8px;">
            <button type="button" class="btn btn-secondary btn-sm" onclick="Catalog.addWizardRow()">+ Add Row</button>
            <button type="button" class="btn btn-secondary btn-sm" onclick="Catalog.removeWizardRows()">Remove Selected</button>
          </div>
        </div>
        <div class="table-wrap">
          <table class="data">
            <thead><tr>
              <th style="width:36px;"><input type="checkbox" onchange="Catalog.toggleAllWizardRows(this.checked)" /></th>
              <th>Our Product ID *</th>
              <th>Vendor Product ID *</th>
              <th>Images</th>
            </tr></thead>
            <tbody>
              ${wizardRows.map((row, idx) => `
                <tr>
                  <td><input type="checkbox" ${row.selected ? "checked" : ""} onchange="Catalog.toggleWizardRow(${idx}, this.checked)" /></td>
                  <td><input class="input" style="font-size:13px;" value="${ctx.esc(row.our_product_id)}" placeholder="e.g. BC-001"
                    oninput="Catalog.updateWizardRow(${idx}, 'our_product_id', this.value)"
                    onblur="Catalog.maybeAddWizardRow(${idx})" /></td>
                  <td><input class="input" style="font-size:13px;" value="${ctx.esc(row.vendor_product_id)}" placeholder="Vendor SKU"
                    oninput="Catalog.updateWizardRow(${idx}, 'vendor_product_id', this.value)"
                    onblur="Catalog.maybeAddWizardRow(${idx})" /></td>
                  <td>
                    <input type="file" multiple accept="image/*" class="input" style="font-size:12px;padding:6px;"
                      onchange="Catalog.setWizardImages(${idx}, this.files)" />
                    ${wizardImageThumbs(row)}
                  </td>
                </tr>`).join("")}
            </tbody>
          </table>
        </div>
      </div>`;
    footer.innerHTML = `
      <button class="btn btn-secondary" onclick="Catalog.closeWizard()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Catalog.wizardNext()">Continue</button>`;
  }

  function renderWizardStep2(body, footer) {
    const filled = filledWizardRows();
    body.innerHTML = `
      <div class="card" style="padding:16px;background:#eff6ff;border-color:#bfdbfe;margin-bottom:16px;">
        <div style="font-size:12px;font-weight:700;color:var(--brand);margin-bottom:10px;">Apply to selected rows</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;align-items:end;">
          <div><label class="label">Category</label><select id="cw-bulk-category" class="input" style="font-size:13px;"><option value="">—</option>${lookupOptions("category")}</select></div>
          <div><label class="label">Series</label><select id="cw-bulk-series" class="input" style="font-size:13px;"><option value="">—</option>${lookupOptions("series")}</select></div>
          <div><label class="label">Unit</label><select id="cw-bulk-unit" class="input" style="font-size:13px;"><option value="">—</option>${lookupOptions("unit")}</select></div>
          <div><label class="label">Year Group</label><select id="cw-bulk-year_group" class="input" style="font-size:13px;"><option value="">—</option>${lookupOptions("year_group")}</select></div>
          <div><label class="label">Buy Price</label><input id="cw-bulk-buying_price" class="input" type="number" min="0" step="0.01" style="font-size:13px;" /></div>
          <div><label class="label">Sell Price</label><input id="cw-bulk-selling_price" class="input" type="number" min="0" step="0.01" style="font-size:13px;" /></div>
          <button type="button" class="btn btn-primary btn-sm" onclick="Catalog.applyBulkFields()">Apply</button>
        </div>
      </div>
      <div class="table-wrap">
        <table class="data" style="font-size:13px;">
          <thead><tr>
            <th style="width:36px;"></th>
            <th>Product ID</th>
            <th>Category</th>
            <th>Series</th>
            <th>Unit</th>
            <th>Year Group</th>
            <th>Buy</th>
            <th>Sell</th>
          </tr></thead>
          <tbody>
            ${filled.map((row) => {
              const idx = wizardRows.indexOf(row);
              return `<tr>
                <td><input type="checkbox" ${row.selected ? "checked" : ""} onchange="Catalog.toggleWizardRow(${idx}, this.checked)" /></td>
                <td><strong>${ctx.esc(row.our_product_id)}</strong></td>
                <td><select class="input" style="font-size:12px;" onchange="Catalog.updateWizardRow(${idx}, 'category', this.value)">
                  <option value="">—</option>${lookupOptions("category", row.category)}</select></td>
                <td><select class="input" style="font-size:12px;" onchange="Catalog.updateWizardRow(${idx}, 'series', this.value)">
                  <option value="">—</option>${lookupOptions("series", row.series)}</select></td>
                <td><select class="input" style="font-size:12px;" onchange="Catalog.updateWizardRow(${idx}, 'unit', this.value)">${lookupOptions("unit", row.unit)}</select></td>
                <td><select class="input" style="font-size:12px;" onchange="Catalog.updateWizardRow(${idx}, 'year_group', this.value)">${lookupOptions("year_group", row.year_group)}</select></td>
                <td><input class="input" type="number" min="0" step="0.01" style="font-size:12px;width:90px;" value="${ctx.esc(row.buying_price)}"
                  oninput="Catalog.updateWizardRow(${idx}, 'buying_price', this.value)" /></td>
                <td><input class="input" type="number" min="0" step="0.01" style="font-size:12px;width:90px;" value="${ctx.esc(row.selling_price)}"
                  oninput="Catalog.updateWizardRow(${idx}, 'selling_price', this.value)" /></td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>`;
    footer.innerHTML = `
      <button class="btn btn-secondary" onclick="Catalog.wizardBack()">Back</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Catalog.wizardNext()">Continue</button>`;
  }

  function allProductOptions(excludeOurId) {
    const batch = filledWizardRows()
      .filter(r => r.our_product_id !== excludeOurId)
      .map(r => ({ value: r.our_product_id, label: `${r.our_product_id} (new)` }));
    const existing = products
      .filter(p => p.our_product_id !== excludeOurId)
      .map(p => ({ value: p.our_product_id, label: `${p.our_product_id}${p.category ? ` (${p.category})` : ""}` }));
    return [...batch, ...existing];
  }

  function viceVersaPreview(row) {
    const ours = row.our_product_id;
    const alts = (row.alternative_our_product_ids || []).filter(Boolean);
    if (!alts.length) return '<p style="color:var(--muted);font-size:13px;">No bidirectional links yet</p>';
    const lines = alts.map(alt => `
      <div class="review-row"><span>${ctx.esc(ours)} ↔ ${ctx.esc(alt)}</span><span class="badge badge-blue">linked</span></div>`);
    const mirrored = filledWizardRows().filter(r => {
      if (r.our_product_id === ours) return false;
      return (r.alternative_our_product_ids || []).includes(ours);
    });
    mirrored.forEach(r => {
      if (!alts.includes(r.our_product_id)) {
        lines.push(`<div class="review-row"><span>${ctx.esc(r.our_product_id)} ↔ ${ctx.esc(ours)}</span><span class="badge badge-green">mirror</span></div>`);
      }
    });
    return `<div class="review-grid">${lines.join("")}</div>`;
  }

  function renderWizardStep3(body, footer) {
    const filled = filledWizardRows();
    if (!filled.length) {
      body.innerHTML = '<p style="color:var(--muted);">No products to configure.</p>';
      footer.innerHTML = `<button class="btn btn-secondary" onclick="Catalog.wizardBack()">Back</button>`;
      return;
    }
    if (wizardSelectedRowIdx >= filled.length) wizardSelectedRowIdx = 0;
    const row = filled[wizardSelectedRowIdx];
    const rowIdx = wizardRows.indexOf(row);
    const options = allProductOptions(row.our_product_id);

    body.innerHTML = `
      <div style="display:grid;gap:16px;">
        <div>
          <label class="label">Select product row</label>
          <select class="input" onchange="Catalog.setWizardSelectedRow(parseInt(this.value, 10))">
            ${filled.map((r, i) => `<option value="${i}" ${i === wizardSelectedRowIdx ? "selected" : ""}>${ctx.esc(r.our_product_id)}</option>`).join("")}
          </select>
        </div>
        <div class="card" style="padding:16px;">
          <div style="font-weight:600;margin-bottom:12px;">${ctx.esc(row.our_product_id)} — alternatives (max ${MAX_ALTERNATIVES})</div>
          <div id="cw-alt-slots">
            ${[0, 1, 2].map(i => {
              const val = row.alternative_our_product_ids[i] || "";
              const used = row.alternative_our_product_ids.filter((a, j) => j !== i && a);
              return `<div style="display:flex;gap:8px;margin-bottom:8px;">
                <select class="input" style="font-size:13px;flex:1;" onchange="Catalog.setWizardAlt(${rowIdx}, ${i}, this.value)">
                  <option value="">— none —</option>
                  ${options.filter(o => !used.includes(o.value)).map(o => `<option value="${ctx.esc(o.value)}" ${val === o.value ? "selected" : ""}>${ctx.esc(o.label)}</option>`).join("")}
                </select>
              </div>`;
            }).join("")}
          </div>
          <div style="margin-top:16px;">
            <div style="font-size:11px;font-weight:700;text-transform:uppercase;color:var(--muted);margin-bottom:8px;">Vice-versa preview</div>
            ${viceVersaPreview(row)}
          </div>
        </div>
        <div class="card" style="padding:16px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
            <div style="font-weight:600;">Add-on links</div>
            <button type="button" class="btn btn-secondary btn-sm" onclick="Catalog.addWizardAddon(${rowIdx})">+ Add link</button>
          </div>
          ${!addons.length ? '<p style="color:var(--muted);font-size:13px;">No add-ons available. Create add-ons first.</p>' : ""}
          ${(row.addon_links.length ? row.addon_links : []).map((link, li) => `
            <div style="display:flex;gap:8px;margin-bottom:8px;">
              <select class="input" style="font-size:13px;flex:1;" onchange="Catalog.setWizardAddon(${rowIdx}, ${li}, 'addon_our_product_id', this.value)">
                <option value="">— select add-on —</option>
                ${addons.map(a => `<option value="${ctx.esc(a.our_product_id)}" ${link.addon_our_product_id === a.our_product_id ? "selected" : ""}>${ctx.esc(a.our_product_id)}${a.name ? ` — ${ctx.esc(a.name)}` : ""}</option>`).join("")}
              </select>
              <input class="input" type="number" min="1" style="width:72px;font-size:13px;" value="${link.quantity || 1}"
                oninput="Catalog.setWizardAddon(${rowIdx}, ${li}, 'quantity', this.value)" />
              <button type="button" class="btn btn-ghost btn-sm" onclick="Catalog.removeWizardAddon(${rowIdx}, ${li})">Remove</button>
            </div>`).join("")}
          ${!row.addon_links.length && addons.length ? '<p style="color:var(--muted);font-size:13px;">No add-on links yet.</p>' : ""}
        </div>
      </div>`;
    footer.innerHTML = `
      <button class="btn btn-secondary" onclick="Catalog.wizardBack()">Back</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Catalog.wizardNext()">Review</button>`;
  }

  function renderWizardStep4(body, footer) {
    const vendor = catalogVendors.find(v => v.id == wizardVendorId);
    const filled = filledWizardRows();
    const dupes = wizardDupes.length ? wizardDupes : filled.filter(r => products.some(p => p.our_product_id.toLowerCase() === r.our_product_id.trim().toLowerCase()));

    body.innerHTML = `
      ${dupes.length ? `<div class="card" style="padding:14px;margin-bottom:16px;background:#fffbeb;border-color:#fde68a;">
        <strong style="color:#b45309;">${dupes.length} duplicate ID(s)</strong>
        <p style="margin:6px 0 0;font-size:13px;color:#92400e;">${dupes.map(r => ctx.esc(r.our_product_id)).join(", ")} already exist. Remove or rename before creating.</p>
      </div>` : ""}
      <div class="review-grid" style="margin-bottom:16px;">
        ${ctx.reviewRow("Vendor", vendor ? vendorLabel(vendor) : "—")}
        ${ctx.reviewRow("Products", String(filled.length))}
      </div>
      <div class="table-wrap">
        <table class="data" style="font-size:13px;">
          <thead><tr>
            <th>Our ID</th><th>Vendor ID</th><th>Category</th><th>Unit</th><th>Buy</th><th>Alts</th><th>Add-ons</th><th>Images</th>
          </tr></thead>
          <tbody>
            ${filled.map(r => `<tr>
              <td><strong>${ctx.esc(r.our_product_id)}</strong></td>
              <td>${ctx.esc(r.vendor_product_id)}</td>
              <td>${ctx.esc(r.category || "—")}</td>
              <td>${ctx.esc(r.unit || "—")}</td>
              <td>${r.buying_price ? fmtPrice(r.buying_price) : "—"}</td>
              <td>${(r.alternative_our_product_ids || []).filter(Boolean).map(ctx.esc).join(", ") || "—"}</td>
              <td>${(r.addon_links || []).filter(l => l.addon_our_product_id).map(l => `${ctx.esc(l.addon_our_product_id)} x${l.quantity || 1}`).join(", ") || "—"}</td>
              <td>${wizardImageThumbs(r) || "—"}</td>
            </tr>`).join("")}
          </tbody>
        </table>
      </div>`;
    footer.innerHTML = `
      <button class="btn btn-secondary" onclick="Catalog.wizardBack()">Back</button>
      <button class="btn btn-primary" style="flex:1;" id="catalog-create-btn" onclick="Catalog.createAll()" ${dupes.length ? "disabled" : ""}>Create All</button>`;
  }

  function renderWizardStep5(body, footer) {
    const vendor = catalogVendors.find(v => v.id == wizardVendorId);
    const rows = wizardCreatedProducts.length ? wizardCreatedProducts : filledWizardRows();
    body.innerHTML = `
      <div style="text-align:center;padding:8px 0 16px;">
        <div class="success-icon">✓</div>
        <h3 style="margin:0 0 4px;">Products Created</h3>
        <p style="color:var(--muted);margin:0;">${wizardCreatedProducts.length || filledWizardRows().length} product(s) added${vendor ? ` for ${ctx.esc(vendorLabel(vendor))}` : ""}</p>
      </div>
      <div class="table-wrap">
        <table class="data" style="font-size:13px;">
          <thead><tr>
            <th></th><th>Our ID</th><th>Vendor ID</th><th>Category</th><th>Unit</th><th>Buy</th><th>Sell</th>
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
                <td>${ctx.esc(p.unit || "—")}</td>
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

  function renderWizard() {
    renderWizardSteps();
    const body = document.getElementById("catalog-wizard-body");
    const footer = document.getElementById("catalog-wizard-footer");
    if (!body || !footer) return;

    if (wizardStep === 1) renderWizardStep1(body, footer);
    else if (wizardStep === 2) renderWizardStep2(body, footer);
    else if (wizardStep === 3) renderWizardStep3(body, footer);
    else if (wizardStep === 4) renderWizardStep4(body, footer);
    else if (wizardStep === 5) renderWizardStep5(body, footer);
  }

  function setWizardVendor(val) {
    wizardVendorId = val ? parseInt(val, 10) : null;
  }

  function addWizardRow() {
    wizardRows.push(emptyWizardRow());
    renderWizard();
  }

  function removeWizardRows() {
    const kept = wizardRows.filter(r => !r.selected);
    wizardRows = kept.length ? kept : [emptyWizardRow()];
    renderWizard();
  }

  function toggleWizardRow(idx, checked) {
    if (wizardRows[idx]) wizardRows[idx].selected = checked;
  }

  function toggleAllWizardRows(checked) {
    wizardRows.forEach(r => { r.selected = checked; });
    renderWizard();
  }

  function updateWizardRow(idx, field, value) {
    if (!wizardRows[idx]) return;
    wizardRows[idx][field] = value;
  }

  function maybeAddWizardRow(idx) {
    if (idx !== wizardRows.length - 1) return;
    const row = wizardRows[idx];
    if (!row?.our_product_id.trim() || !row?.vendor_product_id.trim()) return;
    wizardRows.push(emptyWizardRow());
    renderWizard();
  }

  function setWizardImages(idx, files) {
    if (!wizardRows[idx]) return;
    const row = wizardRows[idx];
    if (row._previewUrls) row._previewUrls.forEach(u => { try { URL.revokeObjectURL(u); } catch (_) {} });
    row.imageFiles = files ? Array.from(files) : [];
    row._previewUrls = row.imageFiles.map(f => URL.createObjectURL(f));
    renderWizard();
  }

  function applyBulkFields() {
    const patch = {};
    const cat = document.getElementById("cw-bulk-category")?.value;
    const ser = document.getElementById("cw-bulk-series")?.value;
    const unit = document.getElementById("cw-bulk-unit")?.value;
    const yg = document.getElementById("cw-bulk-year_group")?.value;
    const buy = document.getElementById("cw-bulk-buying_price")?.value;
    const sell = document.getElementById("cw-bulk-selling_price")?.value;
    if (cat) patch.category = cat;
    if (ser) patch.series = ser;
    if (unit) patch.unit = unit;
    if (yg) patch.year_group = yg;
    if (buy) patch.buying_price = buy;
    if (sell) patch.selling_price = sell;
    if (!Object.keys(patch).length) return ctx.toast("Select at least one field to apply", "error");
    let applied = 0;
    wizardRows.forEach(r => {
      if (!r.selected || !r.our_product_id.trim()) return;
      Object.assign(r, patch);
      applied++;
    });
    if (!applied) return ctx.toast("Select rows with checkboxes first", "error");
    ctx.toast(`Applied to ${applied} row(s)`, "success");
    renderWizard();
  }

  function setWizardSelectedRow(idx) {
    wizardSelectedRowIdx = idx;
    renderWizard();
  }

  function setWizardAlt(rowIdx, slot, value) {
    const row = wizardRows[rowIdx];
    if (!row) return;
    const prev = row.alternative_our_product_ids[slot] || "";
    const next = [...row.alternative_our_product_ids];
    while (next.length <= slot) next.push("");
    next[slot] = value;
    row.alternative_our_product_ids = next.filter((_, i) => i <= slot || next[i]).slice(0, MAX_ALTERNATIVES);

    if (prev && prev !== value) mirrorAltRemove(row.our_product_id, prev);
    if (value && value !== row.our_product_id) mirrorAltAdd(value, row.our_product_id);
    renderWizard();
  }

  function mirrorAltAdd(targetOurId, sourceOurId) {
    const target = wizardRows.find(r => r.our_product_id === targetOurId);
    if (!target) return;
    const alts = [...(target.alternative_our_product_ids || [])].filter(Boolean);
    if (!alts.includes(sourceOurId) && alts.length < MAX_ALTERNATIVES) {
      alts.push(sourceOurId);
      target.alternative_our_product_ids = alts.slice(0, MAX_ALTERNATIVES);
    }
  }

  function mirrorAltRemove(sourceOurId, removedAlt) {
    const target = wizardRows.find(r => r.our_product_id === removedAlt);
    if (!target) return;
    target.alternative_our_product_ids = (target.alternative_our_product_ids || []).filter(a => a !== sourceOurId);
  }

  function addWizardAddon(rowIdx) {
    const row = wizardRows[rowIdx];
    if (!row) return;
    row.addon_links = [...(row.addon_links || []), { addon_our_product_id: "", quantity: 1 }];
    renderWizard();
  }

  function setWizardAddon(rowIdx, linkIdx, field, value) {
    const row = wizardRows[rowIdx];
    if (!row || !row.addon_links[linkIdx]) return;
    if (field === "quantity") row.addon_links[linkIdx].quantity = Math.max(1, parseInt(value, 10) || 1);
    else row.addon_links[linkIdx].addon_our_product_id = value;
  }

  function removeWizardAddon(rowIdx, linkIdx) {
    const row = wizardRows[rowIdx];
    if (!row) return;
    row.addon_links = row.addon_links.filter((_, i) => i !== linkIdx);
    renderWizard();
  }

  function validateStep1() {
    if (!wizardVendorId) return ctx.toast("Select a vendor", "error"), false;
    const filled = filledWizardRows();
    if (!filled.length) return ctx.toast("Add at least one product row", "error"), false;
    const ids = filled.map(r => r.our_product_id.trim().toLowerCase());
    if (ids.length !== new Set(ids).size) return ctx.toast("Duplicate our_product_id in batch", "error"), false;
    return true;
  }

  function validateStep2() {
    const filled = filledWizardRows();
    for (const r of filled) {
      if (!r.category) return ctx.toast(`Category required for ${r.our_product_id}`, "error"), false;
      if (!r.unit) return ctx.toast(`Unit required for ${r.our_product_id}`, "error"), false;
      if (!r.buying_price || Number(r.buying_price) < 0) return ctx.toast(`Buying price required for ${r.our_product_id}`, "error"), false;
    }
    return true;
  }

  function wizardBack() {
    if (wizardStep > 1) wizardStep--;
    renderWizard();
  }

  async function wizardNext() {
    if (wizardStep === 1 && !validateStep1()) return;
    if (wizardStep === 2 && !validateStep2()) return;
    if (wizardStep === 3) await checkWizardDuplicates();
    if (wizardStep < 4) wizardStep++;
    renderWizard();
  }

  async function uploadImage(vendorId, ourProductId, imageIndex, file) {
    if (ctx.uploadImage) return ctx.uploadImage(vendorId, ourProductId, file, imageIndex);
    const fd = new FormData();
    fd.append("vendor_id", String(vendorId));
    fd.append("our_product_id", ourProductId);
    fd.append("image_index", String(imageIndex));
    fd.append("file", file);
    let res;
    try {
      res = await fetch(`${apiBase()}/catalog/upload-image`, {
        method: "POST",
        headers: { "X-Admin-Key": adminKey() },
        body: fd,
      });
    } catch (e) {
      throw new Error("Network error uploading image");
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const msg = typeof err.detail === "string" ? err.detail : `Upload failed (${res.status})`;
      throw new Error(msg);
    }
    return res.json();
  }

  async function createAll() {
    if (!validateStep1() || !validateStep2()) return;
    const dupes = filledWizardRows().filter(r => wizardDupes.map(d => d.toLowerCase()).includes(r.our_product_id.trim().toLowerCase()));
    if (dupes.length) return ctx.toast("Fix duplicate product IDs first", "error");

    const btn = document.getElementById("catalog-create-btn");
    const btnLabel = btn?.textContent || "Create All";
    if (btn) { btn.disabled = true; btn.textContent = "Creating…"; }
    ctx.showLoading?.();
    try {
      const ok = await (ctx.checkBackend ? ctx.checkBackend() : Promise.resolve(true));
      if (!ok) throw new Error("Backend not reachable — start JC backend on port 8003");

      const filled = filledWizardRows();
      const items = [];
      for (let ri = 0; ri < filled.length; ri++) {
        const row = filled[ri];
        const imageKeys = [];
        if (row.imageFiles.length) {
          if (btn) btn.textContent = `Uploading images ${ri + 1}/${filled.length}…`;
          for (let i = 0; i < row.imageFiles.length; i++) {
            try {
              const up = await uploadImage(wizardVendorId, row.our_product_id.trim(), i + 1, row.imageFiles[i]);
              if (up.key) imageKeys.push(up.key);
            } catch (e) {
              throw new Error(`Image upload failed for ${row.our_product_id}: ${e.message}`);
            }
          }
        }
        items.push({
          our_product_id: row.our_product_id.trim(),
          vendor_product_id: row.vendor_product_id.trim(),
          category: row.category || null,
          series: row.series || null,
          unit: row.unit || null,
          year_group: row.year_group || null,
          buying_price: Number(row.buying_price),
          selling_price: row.selling_price ? Number(row.selling_price) : null,
          image_keys: imageKeys,
          alternative_our_product_ids: (row.alternative_our_product_ids || []).filter(Boolean).slice(0, MAX_ALTERNATIVES),
          addon_links: (row.addon_links || [])
            .filter(l => l.addon_our_product_id)
            .map(l => ({ addon_our_product_id: l.addon_our_product_id, quantity: l.quantity || 1 })),
        });
      }

      if (btn) btn.textContent = "Saving products…";
      const created = await ctx.api("/catalog/products/bulk", {
        method: "POST",
        body: JSON.stringify({ vendor_id: wizardVendorId, items }),
      });

      wizardCreatedProducts = Array.isArray(created) ? created : [];
      wizardStep = 5;
      renderWizard();
      ctx.invalidateCache?.("/catalog");
      ctx.invalidateCache?.("/stats");
      ctx.toast("Products created", "success");
      try { await load(); } catch (_) {}
      try { if (ctx.refreshStats) await ctx.refreshStats(); } catch (_) {}
    } catch (e) {
      ctx.toast(e.message || "Create failed", "error");
      if (btn) btn.disabled = false;
    } finally {
      ctx.hideLoading?.();
      if (btn && wizardStep !== 5) btn.textContent = btnLabel;
    }
  }

  async function openEdit(id, returnTo) {
    const p = await ctx.api(`/catalog/products/${id}`);
    editingId = id;
    editReturnTo = returnTo || null;
    await loadAddons();

    document.getElementById("catalog-edit-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Our Product ID *</label>
          <input id="ce-our_product_id" class="input" value="${ctx.esc(p.our_product_id)}" /></div>
        <div><label class="label">Vendor Product ID</label>
          <input id="ce-vendor_product_id" class="input" value="${ctx.esc(p.vendor_product_id)}" /></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Category</label>
            <select id="ce-category" class="input"><option value="">—</option>${lookupOptions("category", p.category)}</select></div>
          <div><label class="label">Series</label>
            <select id="ce-series" class="input"><option value="">—</option>${lookupOptions("series", p.series)}</select></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Unit</label>
            <select id="ce-unit" class="input">${lookupOptions("unit", p.unit)}</select></div>
          <div><label class="label">Year Group</label>
            <select id="ce-year_group" class="input">${lookupOptions("year_group", p.year_group)}</select></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Buying Price</label>
            <input id="ce-buying_price" class="input" type="number" min="0" step="0.01" value="${ctx.esc(p.buying_price)}" /></div>
          <div><label class="label">Selling Price</label>
            <input id="ce-selling_price" class="input" type="number" min="0" step="0.01" value="${ctx.esc(p.selling_price || "")}" /></div>
        </div>
        <div>
          <label class="label">Alternatives (max ${MAX_ALTERNATIVES})</label>
          ${[0, 1, 2].map(i => {
            const val = (p.alternatives || []).map(a => a.alternative_our_product_id)[i] || "";
            const opts = products.filter(x => x.id !== p.id).map(x => `<option value="${ctx.esc(x.our_product_id)}" ${val === x.our_product_id ? "selected" : ""}>${ctx.esc(x.our_product_id)}</option>`).join("");
            return `<select id="ce-alt-${i}" class="input" style="margin-bottom:8px;"><option value="">— none —</option>${opts}</select>`;
          }).join("")}
        </div>
        <div>
          <label class="label">Add-on Links</label>
          <div id="ce-addon-links">
            ${(p.addon_links || []).map((l, i) => `
              <div style="display:flex;gap:8px;margin-bottom:8px;" data-addon-row="${i}">
                <select class="input ce-addon-id" style="flex:1;">
                  <option value="">—</option>
                  ${addons.map(a => `<option value="${ctx.esc(a.our_product_id)}" ${l.addon_our_product_id === a.our_product_id ? "selected" : ""}>${ctx.esc(a.our_product_id)}</option>`).join("")}
                </select>
                <input class="input ce-addon-qty" type="number" min="1" style="width:72px;" value="${l.quantity}" />
              </div>`).join("")}
          </div>
          <button type="button" class="btn btn-secondary btn-sm" onclick="Catalog.addEditAddonRow()">+ Add link</button>
        </div>
      </div>`;

    document.getElementById("catalog-edit-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="Catalog.closeEdit()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Catalog.saveEdit()">Save Changes</button>`;
    document.getElementById("catalog-edit-modal").classList.remove("hidden");
  }

  function addEditAddonRow() {
    const wrap = document.getElementById("ce-addon-links");
    if (!wrap) return;
    const div = document.createElement("div");
    div.style.cssText = "display:flex;gap:8px;margin-bottom:8px;";
    div.innerHTML = `
      <select class="input ce-addon-id" style="flex:1;"><option value="">—</option>
        ${addons.map(a => `<option value="${ctx.esc(a.our_product_id)}">${ctx.esc(a.our_product_id)}</option>`).join("")}
      </select>
      <input class="input ce-addon-qty" type="number" min="1" style="width:72px;" value="1" />`;
    wrap.appendChild(div);
  }

  function closeEdit() {
    document.getElementById("catalog-edit-modal")?.classList.add("hidden");
    editingId = null;
    editReturnTo = null;
  }

  async function saveEdit() {
    if (!editingId) return;
    const altIds = [0, 1, 2]
      .map(i => document.getElementById(`ce-alt-${i}`)?.value.trim())
      .filter(Boolean);
    const addonRows = document.querySelectorAll("#ce-addon-links > div");
    const addonLinks = [];
    addonRows.forEach(row => {
      const id = row.querySelector(".ce-addon-id")?.value.trim();
      const qty = parseInt(row.querySelector(".ce-addon-qty")?.value, 10) || 1;
      if (id) addonLinks.push({ addon_our_product_id: id, quantity: qty });
    });

    try {
      await ctx.api(`/catalog/products/${editingId}`, {
        method: "PATCH",
        body: JSON.stringify({
          our_product_id: document.getElementById("ce-our_product_id").value.trim(),
          vendor_product_id: document.getElementById("ce-vendor_product_id").value.trim(),
          category: document.getElementById("ce-category").value || null,
          series: document.getElementById("ce-series").value || null,
          unit: document.getElementById("ce-unit").value || null,
          year_group: document.getElementById("ce-year_group").value || null,
          buying_price: Number(document.getElementById("ce-buying_price").value),
          selling_price: document.getElementById("ce-selling_price").value
            ? Number(document.getElementById("ce-selling_price").value) : null,
          alternative_our_product_ids: altIds,
          addon_links: addonLinks,
        }),
      });
      const id = editingId;
      const ret = editReturnTo;
      closeEdit();
      App.closeDetail();
      await load();
      ctx.invalidateCache?.("/stock");
      ctx.toast("Product updated", "success");
      if (ret === "stock") Stock.openDetail(id);
      else openDetail(id);
    } catch (e) {
      ctx.toast(e.message, "error");
    }
  }

  async function deleteProduct(id) {
    if (!confirm("Move product to recycle bin?")) return;
    try {
      await ctx.api(`/catalog/products/${id}`, { method: "DELETE" });
      App.closeDetail();
      await load();
      ctx.invalidateCache?.("/catalog");
      ctx.invalidateCache?.("/stats");
      if (ctx.refreshStats) await ctx.refreshStats();
      ctx.toast("Product deleted", "success");
    } catch (e) {
      ctx.toast(e.message, "error");
    }
  }

  return {
    init, load, loadMore, setViewMode, renderGrid, renderTable, openDetail, openWizard, closeWizard,
    wizardBack, wizardNext, createAll, setWizardVendor, addWizardRow, maybeAddWizardRow, removeWizardRows,
    toggleWizardRow, toggleAllWizardRows, updateWizardRow, setWizardImages, applyBulkFields,
    setWizardSelectedRow, setWizardAlt, addWizardAddon, setWizardAddon, removeWizardAddon,
    openEdit, closeEdit, saveEdit, addEditAddonRow, deleteProduct, setVendors,
  };
})();
