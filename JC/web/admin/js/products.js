/** Products — Stock / Catalog tabs with unified Products + Add-ons views */
const Products = (() => {
  let ctx = {};
  let mainTab = "stock";
  let typeFilter = "all";
  let searchQuery = "";
  let filters = { vendor_id: "", category: "", series: "", year_group: "", price_min: "", price_max: "", stock_status: "", no_sell_price: false, no_addons: false };
  let catalogProducts = [];
  let catalogTotal = 0;
  let catalogOffset = 0;
  const CATALOG_PAGE = 100;
  let stockProducts = [];
  let addons = [];
  let lookups = { categories: [], series: [], year_groups: [] };
  let viewMode = "grid";
  let filtersOpen = false;
  let attentionFilter = "all"; // all | low_stock | out_of_stock | negative_stock | no_sell | no_addons

  function init(context) { ctx = context; }

  function showHub() {
    renderSearchBar();
    setMainTab(mainTab || "stock");
  }

  function vendorLine(it) {
    const name = it.vendor_name || "—";
    const city = it.vendor_city;
    return city ? `${name} · ${city}` : name;
  }

  function itemIdHtml(it) {
    const year = it.year_group ? `<span class="prod-year-pill">${ctx.esc(it.year_group)}</span>` : "";
    const vid = it.vendor_product_id
      ? `<div class="prod-card-vsku">Vendor # ${ctx.esc(it.vendor_product_id)}</div>`
      : "";
    return `<div class="prod-card-id-row"><div class="prod-card-id">${ctx.esc(it.our_product_id)}</div>${year}</div>${vid}`;
  }

  function hasRealSell(it) {
    if (it.selling_price == null || it.selling_price === "") return false;
    // sell copied equal to buy is not a real sell price
    if (it.buying_price != null && it.buying_price !== "" && Number(it.selling_price) === Number(it.buying_price)) return false;
    return true;
  }

  function priceFootHtml(it, { stockMode = false } = {}) {
    if (it.kind === "addon") {
      return `<div class="prod-card-foot">
        <div class="prod-price-stack"><span class="prod-price-label">Buy</span><strong class="prod-card-price">${fmtPrice(it.price)}</strong></div>
        <span class="badge badge-amber">Add-on</span>
      </div>`;
    }
    if (stockMode) {
      // Stock cards already show qty — keep foot to prices only (no clipped Product badge)
      const sell = hasRealSell(it)
        ? `<div class="prod-price-stack"><span class="prod-price-label">Sell</span><strong class="prod-card-price">${fmtPrice(it.selling_price)}</strong></div>`
        : `<div class="prod-price-stack"><span class="prod-price-label">Sell</span><span class="prod-price-missing">Not set</span></div>`;
      const buy = it.buying_price != null && it.buying_price !== ""
        ? `<div class="prod-price-stack is-muted"><span class="prod-price-label">Buy</span><span>${fmtPrice(it.buying_price)}</span></div>`
        : "";
      return `<div class="prod-card-foot"><div class="prod-price-pair">${sell}${buy}</div></div>`;
    }
    const sell = hasRealSell(it)
      ? `<div class="prod-price-stack"><span class="prod-price-label">Sell</span><strong class="prod-card-price">${fmtPrice(it.selling_price)}</strong></div>`
      : `<div class="prod-price-stack"><span class="prod-price-label">Sell</span><span class="prod-price-missing">Not set</span></div>`;
    const buy = it.buying_price != null && it.buying_price !== ""
      ? `<div class="prod-price-stack is-muted"><span class="prod-price-label">Buy</span><span>${fmtPrice(it.buying_price)}</span></div>`
      : "";
    return `<div class="prod-card-foot">
      <div class="prod-price-pair">${sell}${buy}</div>
      <span class="badge badge-blue">Product</span>
    </div>`;
  }

  function fmtQty(n) {
    const num = Number(n);
    if (!Number.isFinite(num)) return "0";
    return num.toLocaleString("en-IN");
  }

  function updatePrimaryAction() {
    const action = document.getElementById("products-action-btn");
    if (!action) return;
    if (typeFilter === "addons") {
      action.textContent = "+ New Add-on";
      action.onclick = () => AddonProducts.openWizard();
      action.classList.toggle("hidden", !ctx.canWrite?.("addons"));
      return;
    }
    if (mainTab === "stock") {
      action.textContent = "+ Receive stock";
      action.onclick = () => Stock.openAddWizard();
      action.classList.remove("hidden");
      return;
    }
    action.textContent = "+ New product";
    action.onclick = () => Catalog.openWizard();
    action.classList.toggle("hidden", !ctx.canWrite?.("catalog"));
  }

  function setMainTab(tab) {
    mainTab = tab === "catalog" ? "catalog" : "stock";
    catalogOffset = 0;
    attentionFilter = "all";
    filters.stock_status = "";
    document.getElementById("ptab-stock")?.classList.toggle("active", mainTab === "stock");
    document.getElementById("ptab-catalog")?.classList.toggle("active", mainTab === "catalog");
    const title = document.getElementById("products-panel-title");
    const sub = document.getElementById("products-panel-sub");
    if (title) title.textContent = "Products";
    if (sub) {
      sub.textContent = mainTab === "stock"
        ? "What you have in godown · tap a card to edit"
        : "Full catalog · set sell price, add-ons, alternatives";
    }
    renderSearchBar();
    updatePrimaryAction();
    syncFiltersVisibility();
    load();
  }

  function toggleFilters() {
    filtersOpen = !filtersOpen;
    syncFiltersVisibility();
  }

  function syncFiltersVisibility() {
    const wrap = document.getElementById("products-filters-wrap");
    const btn = document.getElementById("products-filters-toggle");
    wrap?.classList.toggle("hidden", !filtersOpen);
    if (btn) {
      btn.classList.toggle("active", filtersOpen || hasActiveFilters());
      btn.textContent = filtersOpen ? "Hide filters" : (hasActiveFilters() ? "Filters · on" : "Filters");
    }
  }

  function setAttentionFilter(id) {
    if (attentionFilter === id) attentionFilter = "all";
    else attentionFilter = id || "all";
    // Map stock status chips into existing filter
    if (["low_stock", "out_of_stock", "negative_stock", "in_stock"].includes(attentionFilter)) {
      filters.stock_status = attentionFilter;
      filters.no_sell_price = false;
      filters.no_addons = false;
    } else if (attentionFilter === "no_sell") {
      filters.stock_status = "";
      filters.no_sell_price = true;
      filters.no_addons = false;
    } else if (attentionFilter === "no_addons") {
      filters.stock_status = "";
      filters.no_sell_price = false;
      filters.no_addons = true;
    } else {
      filters.stock_status = "";
      filters.no_sell_price = false;
      filters.no_addons = false;
    }
    const sel = document.getElementById("pf-stock-status");
    if (sel) sel.value = filters.stock_status;
    const noSell = document.getElementById("pf-no-sell");
    if (noSell) noSell.checked = filters.no_sell_price;
    const noAdd = document.getElementById("pf-no-addons");
    if (noAdd) noAdd.checked = filters.no_addons;
    document.getElementById("products-clear-filters")?.classList.toggle("hidden", !hasActiveFilters());
    syncFiltersVisibility();
    if (mainTab === "catalog" && (attentionFilter === "no_sell" || attentionFilter === "no_addons" || attentionFilter === "all")) {
      load();
    } else {
      render();
    }
  }

  function attentionCounts(items) {
    const products = (items || []).filter(it => it.kind === "product");
    const counts = {
      all: products.length,
      low_stock: 0,
      out_of_stock: 0,
      negative_stock: 0,
      no_sell: 0,
      no_addons: 0,
    };
    products.forEach(it => {
      if (it.stock_status === "low_stock") counts.low_stock += 1;
      if (it.stock_status === "out_of_stock") counts.out_of_stock += 1;
      if (it.stock_status === "negative_stock") counts.negative_stock += 1;
      if (!hasRealSell(it)) counts.no_sell += 1;
      if (!(it.addon_count > 0)) counts.no_addons += 1;
    });
    return counts;
  }

  function syncActionChips(items) {
    const host = document.getElementById("products-action-chips");
    if (!host || typeof OrdersUI === "undefined") return;
    const c = attentionCounts(items);
    if (mainTab === "stock") {
      OrdersUI.actionChips({
        hostId: "products-action-chips",
        active: attentionFilter,
        onclickFn: "Products.setAttentionFilter",
        items: [
          { id: "all", label: "All", count: c.all },
          { id: "low_stock", label: "Low", count: c.low_stock },
          { id: "out_of_stock", label: "Out", count: c.out_of_stock },
          { id: "negative_stock", label: "Negative", count: c.negative_stock },
          { id: "no_sell", label: "No sell price", count: c.no_sell },
        ],
      });
    } else {
      OrdersUI.actionChips({
        hostId: "products-action-chips",
        active: attentionFilter,
        onclickFn: "Products.setAttentionFilter",
        items: [
          { id: "all", label: "All", count: c.all },
          { id: "no_sell", label: "No sell price", count: c.no_sell },
          { id: "no_addons", label: "No add-ons", count: c.no_addons },
        ],
      });
    }
  }

  function setTypeFilter(t) {
    typeFilter = t;
    ["all", "products", "addons"].forEach(k => {
      document.getElementById(`ptype-${k}`)?.classList.toggle("active", k === t);
    });
    updatePrimaryAction();
    render();
  }

  function setViewMode(mode) {
    viewMode = mode;
    document.getElementById("products-view-grid")?.classList.toggle("active", mode === "grid");
    document.getElementById("products-view-list")?.classList.toggle("active", mode === "list");
    render();
  }

  function renderSearchBar() {
    const slot = document.getElementById("products-search-slot");
    if (!slot) return;
    const active = document.activeElement?.id === "products-search-input";
    const caret = active
      ? { start: document.activeElement.selectionStart, end: document.activeElement.selectionEnd }
      : null;
    slot.innerHTML = HubUI.searchBar({
      id: "products-search-input",
      value: searchQuery,
      placeholder: "Search product code, vendor, city, category…",
      oninput: "Products.onSearch(this.value)",
    });
    if (caret) {
      const el = document.getElementById("products-search-input");
      if (el) {
        el.focus();
        try { el.setSelectionRange(caret.start, caret.end); } catch (_) { /* ignore */ }
      }
    }
  }

  function onSearch(val) {
    searchQuery = val;
    const clear = document.querySelector("#products-search-slot .ord-search-clear");
    clear?.classList.toggle("hidden", !String(val || "").trim());
    debouncedLoad();
  }

  function clearSearch() {
    searchQuery = "";
    renderSearchBar();
    load();
  }

  const debouncedLoad = (() => {
    let t;
    return () => { clearTimeout(t); t = setTimeout(() => load(), 300); };
  })();

  function hasActiveFilters() {
    return !!(filters.vendor_id || filters.category || filters.series || filters.year_group || filters.price_min || filters.price_max || filters.stock_status || filters.no_sell_price || filters.no_addons);
  }

  function onFilterChange() {
    filters.vendor_id = document.getElementById("pf-vendor")?.value || "";
    filters.category = document.getElementById("pf-category")?.value || "";
    filters.series = document.getElementById("pf-series")?.value || "";
    filters.year_group = document.getElementById("pf-year")?.value || "";
    filters.price_min = document.getElementById("pf-price-min")?.value || "";
    filters.price_max = document.getElementById("pf-price-max")?.value || "";
    filters.stock_status = document.getElementById("pf-stock-status")?.value || "";
    filters.no_sell_price = !!document.getElementById("pf-no-sell")?.checked;
    filters.no_addons = !!document.getElementById("pf-no-addons")?.checked;
    if (filters.no_sell_price) attentionFilter = "no_sell";
    else if (filters.no_addons) attentionFilter = "no_addons";
    else if (filters.stock_status) attentionFilter = filters.stock_status;
    else attentionFilter = "all";
    document.getElementById("products-clear-filters")?.classList.toggle("hidden", !hasActiveFilters());
    syncFiltersVisibility();
    if (mainTab === "catalog") load();
    else render();
  }

  function clearFilters() {
    filters = { vendor_id: "", category: "", series: "", year_group: "", price_min: "", price_max: "", stock_status: "", no_sell_price: false, no_addons: false };
    attentionFilter = "all";
    renderFilters();
    document.getElementById("products-clear-filters")?.classList.add("hidden");
    syncFiltersVisibility();
    if (mainTab === "catalog") load();
    else render();
  }

  function catalogQueryParams(offset = 0) {
    const params = new URLSearchParams({
      limit: String(CATALOG_PAGE),
      offset: String(offset),
    });
    const q = searchQuery.trim();
    if (q) params.set("search", q);
    if (filters.vendor_id) params.set("vendor_id", filters.vendor_id);
    if (filters.category) params.set("category", filters.category);
    if (filters.series) params.set("series", filters.series);
    if (filters.year_group) params.set("year_group", filters.year_group);
    if (filters.price_min) params.set("price_min", filters.price_min);
    if (filters.price_max) params.set("price_max", filters.price_max);
    if (filters.no_sell_price) params.set("no_sell_price", "true");
    if (filters.no_addons) params.set("no_addons", "true");
    return params;
  }

  async function refreshHub() {
    ctx.invalidateCache?.("/stock");
    ctx.invalidateCache?.("/catalog");
    ctx.invalidateCache?.("/addons");
    await load();
  }

  async function ensureLookups() {
    if (lookups.categories.length && lookups.year_groups.length) return;
    try {
      const rows = await ctx.api("/lookups", {}, 120000);
      lookups.categories = rows.filter(r => r.lookup_type === "category").map(r => r.value);
      lookups.series = rows.filter(r => r.lookup_type === "series").map(r => r.value);
      lookups.year_groups = rows.filter(r => r.lookup_type === "year_group").map(r => r.value);
    } catch (_) {}
  }

  function renderFilters() {
    const el = document.getElementById("products-filters");
    if (!el) return;
    const vendors = (ctx.getVendors?.() || []).filter(v => v.is_active);
    el.innerHTML = `
      <label class="prod-filter-field">
        <span class="prod-filter-label">Vendor</span>
        <select id="pf-vendor" class="input filter-input" onchange="Products.onFilterChange()">
          <option value="">All</option>
          ${vendors.map(v => `<option value="${v.id}" ${filters.vendor_id == v.id ? "selected" : ""}>${ctx.esc(v.business_name)}</option>`).join("")}
        </select>
      </label>
      <label class="prod-filter-field">
        <span class="prod-filter-label">Category</span>
        <select id="pf-category" class="input filter-input" onchange="Products.onFilterChange()">
          <option value="">All</option>
          ${lookups.categories.map(c => `<option value="${ctx.esc(c)}" ${filters.category === c ? "selected" : ""}>${ctx.esc(c)}</option>`).join("")}
        </select>
      </label>
      <label class="prod-filter-field">
        <span class="prod-filter-label">Series</span>
        <select id="pf-series" class="input filter-input" onchange="Products.onFilterChange()">
          <option value="">All</option>
          ${lookups.series.map(s => `<option value="${ctx.esc(s)}" ${filters.series === s ? "selected" : ""}>${ctx.esc(s)}</option>`).join("")}
        </select>
      </label>
      <label class="prod-filter-field">
        <span class="prod-filter-label">Year group</span>
        <select id="pf-year" class="input filter-input" onchange="Products.onFilterChange()">
          <option value="">All years</option>
          ${(lookups.year_groups || []).map(y => `<option value="${ctx.esc(y)}" ${filters.year_group === y ? "selected" : ""}>${ctx.esc(y)}</option>`).join("")}
        </select>
      </label>
      <label class="prod-filter-field prod-filter-price">
        <span class="prod-filter-label">Sell price</span>
        <div class="prod-price-range">
          <input id="pf-price-min" class="input filter-input" type="number" min="0" step="0.01" placeholder="Min" value="${ctx.esc(filters.price_min)}" oninput="Products.onFilterChange()" />
          <span class="prod-price-sep">–</span>
          <input id="pf-price-max" class="input filter-input" type="number" min="0" step="0.01" placeholder="Max" value="${ctx.esc(filters.price_max)}" oninput="Products.onFilterChange()" />
        </div>
      </label>
      <label class="prod-filter-field ${mainTab !== "stock" ? "hidden" : ""}" id="products-stock-status-filter">
        <span class="prod-filter-label">Stock</span>
        <select id="pf-stock-status" class="input filter-input" onchange="Products.onFilterChange()">
          <option value="">All</option>
          <option value="in_stock" ${filters.stock_status === "in_stock" ? "selected" : ""}>In stock</option>
          <option value="low_stock" ${filters.stock_status === "low_stock" ? "selected" : ""}>Low stock</option>
          <option value="out_of_stock" ${filters.stock_status === "out_of_stock" ? "selected" : ""}>Out of stock</option>
          <option value="negative_stock" ${filters.stock_status === "negative_stock" ? "selected" : ""}>Negative</option>
        </select>
      </label>
      <label class="prod-filter-chip ${filters.no_sell_price ? "is-on" : ""}">
        <input type="checkbox" id="pf-no-sell" ${filters.no_sell_price ? "checked" : ""} onchange="Products.onFilterChange()" />
        Needs sell price
      </label>
      <label class="prod-filter-chip ${filters.no_addons ? "is-on" : ""}">
        <input type="checkbox" id="pf-no-addons" ${filters.no_addons ? "checked" : ""} onchange="Products.onFilterChange()" />
        No add-ons
      </label>
      <button type="button" class="btn btn-secondary btn-sm" onclick="Products.openAlternativesManager()">Manage alternatives</button>`;
    document.getElementById("products-clear-filters")?.classList.toggle("hidden", !hasActiveFilters());
  }

  async function load() {
    const q = searchQuery.trim();
    const stockParams = new URLSearchParams();
    if (q) stockParams.set("search", q);
    if (filters.year_group) stockParams.set("year_group", filters.year_group);
    const stockQs = stockParams.toString();
    const searchParam = q ? `?search=${encodeURIComponent(q)}` : "";
    const stockPath = `/stock/products${stockQs ? `?${stockQs}` : ""}`;
    catalogOffset = 0;
    const catPath = `/catalog/products?${catalogQueryParams(0)}`;
    const addonPath = `/addons${searchParam}`;
    const ttl = q || hasActiveFilters() ? 0 : 90000;

    if (mainTab === "stock") {
      const cached = ctx.peekCache?.(stockPath);
      if (cached) { stockProducts = cached; renderFilters(); render(); }
    } else {
      const cached = ctx.peekCache?.(catPath);
      if (cached) {
        catalogProducts = cached.items || cached || [];
        catalogTotal = cached.total ?? catalogProducts.length;
        renderFilters();
        render();
      }
    }
    const showSpin = !stockProducts.length && !catalogProducts.length;
    if (showSpin) ctx.showLoading?.();

    try {
      await ensureLookups();
      if (mainTab === "stock") {
        const tasks = [ctx.api(stockPath, {}, ttl)];
        if (ctx.canRead?.("addons")) tasks.push(ctx.api(addonPath, {}, ttl));
        const [stockR, addonR] = await Promise.all(tasks);
        stockProducts = stockR;
        addons = addonR || [];
      } else {
        const tasks = [ctx.api(catPath, {}, ttl)];
        if (ctx.canRead?.("addons")) tasks.push(ctx.api(addonPath, {}, ttl));
        const [catR, addonR] = await Promise.all(tasks);
        catalogProducts = catR.items || catR || [];
        catalogTotal = catR.total ?? catalogProducts.length;
        catalogOffset = catalogProducts.length;
        addons = addonR || [];
      }
      renderFilters();
      render();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { if (showSpin) ctx.hideLoading?.(); }
  }

  async function loadMoreCatalog() {
    if (mainTab !== "catalog") return;
    if (catalogProducts.length >= catalogTotal) return;
    const path = `/catalog/products?${catalogQueryParams(catalogOffset)}`;
    ctx.showLoading?.();
    try {
      const catR = await ctx.api(path, {}, 0);
      const more = catR.items || [];
      catalogProducts = catalogProducts.concat(more);
      catalogTotal = catR.total ?? catalogProducts.length;
      catalogOffset = catalogProducts.length;
      render();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function stockBadge(status) {
    const map = {
      in_stock: ["badge-green", "In stock"],
      low_stock: ["badge-amber", "Low"],
      out_of_stock: ["badge-gray", "Out"],
      negative_stock: ["badge-red", "Negative"],
    };
    const [cls, lbl] = map[status] || ["badge-gray", status || "—"];
    return `<span class="badge ${cls}">${lbl}</span>`;
  }

  function stockStatusMeta(status) {
    const map = {
      in_stock: { cls: "is-ok", label: "In stock" },
      low_stock: { cls: "is-low", label: "Low stock" },
      out_of_stock: { cls: "is-out", label: "Out of stock" },
      negative_stock: { cls: "is-neg", label: "Negative" },
    };
    return map[status] || { cls: "is-out", label: status || "—" };
  }

  function stockSummaryHtml(items) {
    if (mainTab !== "stock") return "";
    const productsOnly = items.filter(it => it.kind === "product");
    if (!productsOnly.length) return "";
    let units = 0;
    productsOnly.forEach(it => { units += Number(it.qty) || 0; });
    return `<div class="prod-stock-summary prod-stock-summary-slim">
      <div class="prod-stock-units">
        <strong>${units.toLocaleString("en-IN")}</strong>
        <span>units on hand</span>
      </div>
    </div>`;
  }

  function setStockChip(status) {
    setAttentionFilter(status || "all");
  }

  function buildItems() {
    const items = [];
    if (mainTab === "stock") {
      if (typeFilter !== "addons") {
        stockProducts.forEach(p => items.push({
          kind: "product",
          id: p.catalog_product_id,
          our_product_id: p.our_product_id,
          vendor_product_id: p.vendor_product_id,
          vendor_name: p.vendor_name,
          vendor_city: p.vendor_city,
          category: p.category,
          series: p.series,
          year_group: p.year_group,
          vendor_id: p.vendor_id,
          price: p.selling_price,
          buying_price: p.buying_price,
          selling_price: p.selling_price,
          addon_count: p.addon_count || 0,
          qty: p.quantity_on_hand,
          stock_status: p.stock_status,
          image_urls: p.image_urls,
          open: () => openProductDetail(p.catalog_product_id, "stock"),
        }));
      }
      if (typeFilter !== "products" && ctx.canRead?.("addons")) {
        addons.forEach(a => items.push({
          kind: "addon",
          id: a.id,
          our_product_id: a.our_product_id,
          vendor_name: a.vendor_name,
          vendor_city: a.vendor_city,
          category: a.category,
          series: null,
          year_group: null,
          vendor_id: a.vendor_id,
          price: a.buying_price,
          buying_price: a.buying_price,
          selling_price: null,
          qty: null,
          stock_status: null,
          image_urls: a.image_urls,
          open: () => AddonProducts.openDetail(a.id),
        }));
      }
    } else {
      if (typeFilter !== "addons") {
        catalogProducts.forEach(p => items.push({
          kind: "product",
          id: p.id,
          our_product_id: p.our_product_id,
          vendor_product_id: p.vendor_product_id,
          vendor_name: p.vendor_name,
          vendor_city: p.vendor_city,
          category: p.category,
          series: p.series,
          year_group: p.year_group,
          vendor_id: p.vendor_id,
          price: p.selling_price,
          buying_price: p.buying_price,
          selling_price: p.selling_price,
          addon_count: p.addon_count || 0,
          qty: null,
          stock_status: null,
          image_urls: p.image_urls,
          open: () => openProductDetail(p.id, "catalog"),
        }));
      }
      if (typeFilter !== "products" && ctx.canRead?.("addons")) {
        addons.forEach(a => items.push({
          kind: "addon",
          id: a.id,
          our_product_id: a.our_product_id,
          vendor_name: a.vendor_name,
          vendor_city: a.vendor_city,
          category: a.category,
          series: null,
          year_group: null,
          vendor_id: a.vendor_id,
          price: a.buying_price,
          buying_price: a.buying_price,
          selling_price: null,
          qty: null,
          stock_status: null,
          image_urls: a.image_urls,
          open: () => AddonProducts.openDetail(a.id),
        }));
      }
    }
    items.sort((a, b) => {
      const idCmp = String(a.our_product_id || "").localeCompare(String(b.our_product_id || ""), undefined, { sensitivity: "base" });
      if (idCmp) return idCmp;
      return String(a.year_group || "").localeCompare(String(b.year_group || ""));
    });
    return items;
  }

  function applyFilters(items, { ignoreStockStatus = false } = {}) {
    const catalogServer = mainTab === "catalog";
    return items.filter(it => {
      // Catalog products already filtered on server
      if (catalogServer && it.kind === "product") return true;
      if (filters.vendor_id && String(it.vendor_id) !== String(filters.vendor_id)) return false;
      if (filters.category && (it.category || "") !== filters.category) return false;
      if (filters.series && (it.series || "") !== filters.series) return false;
      if (filters.year_group && (it.year_group || "") !== filters.year_group) return false;
      const sellOrBuy = it.kind === "product"
        ? Number(it.selling_price != null && it.selling_price !== "" ? it.selling_price : it.buying_price)
        : Number(it.price);
      if (filters.price_min && !Number.isNaN(sellOrBuy) && sellOrBuy < Number(filters.price_min)) return false;
      if (filters.price_max && !Number.isNaN(sellOrBuy) && sellOrBuy > Number(filters.price_max)) return false;
      if (!ignoreStockStatus && mainTab === "stock" && filters.stock_status && it.stock_status !== filters.stock_status) return false;
      if (filters.no_sell_price && it.kind === "product") {
        if (hasRealSell(it)) return false;
      }
      if (filters.no_addons && it.kind === "product") {
        if ((it.addon_count || 0) > 0) return false;
      }
      if ((filters.no_sell_price || filters.no_addons) && it.kind === "addon") return false;
      return true;
    });
  }

  function normalizeItems() {
    return applyFilters(buildItems());
  }

  function cardImage(it) {
    const url = (it.image_urls || [])[0];
    if (url) return `<img src="${ctx.esc(url)}" alt="" class="prod-card-img" />`;
    const initials = ctx.esc((it.our_product_id || "?").slice(0, 3).toUpperCase());
    return `<div class="prod-card-img prod-card-img-empty"><span>${initials}</span></div>`;
  }

  function listThumb(it) {
    const url = (it.image_urls || [])[0];
    if (url) return `<img src="${ctx.esc(url)}" alt="" class="prod-list-thumb" />`;
    return `<div class="prod-list-thumb prod-list-thumb-empty">${ctx.esc((it.our_product_id || "?").slice(0, 2).toUpperCase())}</div>`;
  }

  function updateResultCount(shown, total, { loaded = null, more = false } = {}) {
    const el = document.getElementById("products-result-count");
    if (!el) return;
    if (!total && !shown) {
      el.textContent = "";
      return;
    }
    if (more && loaded != null) {
      el.textContent = `Showing ${shown} · ${loaded} of ${total} loaded`;
      return;
    }
    if (shown === total) el.textContent = `${shown} item${shown === 1 ? "" : "s"}`;
    else el.textContent = `Showing ${shown} of ${total}`;
  }

  function loadMoreHtml() {
    if (mainTab !== "catalog" || typeFilter === "addons") return "";
    if (catalogProducts.length >= catalogTotal) return "";
    const left = catalogTotal - catalogProducts.length;
    return `<div class="prod-load-more">
      <button type="button" class="btn btn-secondary" onclick="Products.loadMoreCatalog()">Load more · ${left} left</button>
    </div>`;
  }

  function render() {
    const el = document.getElementById("products-content");
    if (!el) return;
    const allItems = buildItems();
    syncActionChips(allItems);
    const addonFiltered = applyFilters(
      (ctx.canRead?.("addons") ? addons : []).map(a => ({
        kind: "addon", vendor_id: a.vendor_id, category: a.category, series: null,
        price: a.buying_price, selling_price: null, addon_count: 0,
      }))
    ).length;
    const rawCount = mainTab === "stock"
      ? (typeFilter === "addons" ? addons.length : typeFilter === "products" ? stockProducts.length : stockProducts.length + addons.length)
      : (typeFilter === "addons" ? addons.length : typeFilter === "products" ? catalogTotal : catalogTotal + addonFiltered);
    const items = normalizeItems();
    const catalogMore = mainTab === "catalog" && typeFilter !== "addons" && catalogProducts.length < catalogTotal;
    updateResultCount(items.length, rawCount, {
      loaded: mainTab === "catalog" && typeFilter !== "addons" ? catalogProducts.length : null,
      more: catalogMore,
    });

    if (!items.length) {
      if (!rawCount) {
        const canCatalog = ctx.canWrite?.("catalog");
        const canAddon = ctx.canWrite?.("addons");
        if (typeFilter === "addons") {
          el.innerHTML = HubUI.emptyState({
            title: "No add-ons yet",
            sub: "Add-ons link to catalog products (envelopes, inserts). Switch to Products if you need a full SKU.",
            ctaHtml: canAddon ? `<button class="btn btn-primary btn-lg" onclick="AddonProducts.openWizard()">+ New Add-on</button>` : "",
          });
        } else if (mainTab === "catalog") {
          el.innerHTML = HubUI.emptyState({
            title: "Catalog is empty",
            sub: "Add products here first. On-hand qty fills after you receive vendor orders.",
            ctaHtml: `<div class="prod-empty-actions">
              ${canCatalog ? `<button class="btn btn-primary btn-lg" onclick="Catalog.openWizard()">+ New catalog product</button>` : ""}
              ${canAddon ? `<button class="btn btn-secondary btn-lg" onclick="AddonProducts.openWizard()">+ New Add-on</button>` : ""}
            </div>`,
          });
        } else {
          el.innerHTML = HubUI.emptyState({
            title: "Nothing on hand yet",
            sub: "Create catalog products, place a vendor order, then receive goods.",
            ctaHtml: `<div class="prod-empty-actions">
              ${canCatalog ? `<button class="btn btn-primary btn-lg" onclick="Products.setMainTab('catalog')">Go to Catalog</button>` : ""}
              <button class="btn btn-secondary btn-lg" onclick="Stock.openAddWizard()">+ Receive stock</button>
            </div>`,
          });
        }
      } else {
        const summaryEmpty = stockSummaryHtml(allItems);
        el.innerHTML = `${summaryEmpty}${HubUI.emptyState({
          title: "No items match",
          sub: `Clear search or filters to see ${rawCount} item${rawCount === 1 ? "" : "s"}.`,
          ctaHtml: `<button class="btn btn-secondary" onclick="Products.clearSearch();Products.clearFilters();">Clear all</button>`,
        })}`;
      }
      window._productsItems = [];
      return;
    }

    const summary = stockSummaryHtml(allItems);
    const canSetSell = !!(ctx.canWrite?.("catalog") || ctx.canWrite?.("stock"));
    const bulkSell = filters.no_sell_price && canSetSell && items.some(it => it.kind === "product");

    if (bulkSell) {
      const rows = items.filter(it => it.kind === "product");
      el.innerHTML = `${summary}
        <div class="prod-bulk-sell-bar">
          <div>
            <strong>Set sell prices</strong>
            <span>${rows.length} product${rows.length === 1 ? "" : "s"} — enter sell ₹, then Save</span>
          </div>
          <button type="button" class="btn btn-primary" onclick="Products.saveBulkSellPrices()">Save sell prices</button>
        </div>
        <div class="card table-wrap prod-table-wrap"><table class="data prod-table"><thead><tr>
          <th class="prod-th-thumb"></th>
          <th>Product ID</th>
          <th>Vendor</th>
          <th>Buy</th>
          <th>Sell ₹</th>
        </tr></thead><tbody>
          ${rows.map(it => `<tr data-bulk-id="${it.id}">
            <td>${listThumb(it)}</td>
            <td>
              <strong class="prod-list-id">${ctx.esc(it.our_product_id)}</strong>
              ${it.year_group ? `<span class="prod-year-pill">${ctx.esc(it.year_group)}</span>` : ""}
              <div class="prod-list-sub prod-price-missing">Sell not set</div>
            </td>
            <td>${ctx.esc(vendorLine(it))}</td>
            <td class="prod-list-price is-buy">${fmtPrice(it.buying_price)}</td>
            <td onclick="event.stopPropagation()">
              <input type="number" min="0" step="0.01" class="input prod-bulk-sell-input" data-id="${it.id}"
                placeholder="Sell ₹" value="" />
            </td>
          </tr>`).join("")}
        </tbody></table></div>${loadMoreHtml()}`;
      window._productsItems = items;
      return;
    }

    if (viewMode === "grid") {
      const cards = items.map(it => {
        const isStockProduct = mainTab === "stock" && it.kind === "product";
        const st = isStockProduct ? stockStatusMeta(it.stock_status) : null;
        return `<button type="button" class="prod-card${isStockProduct ? ` prod-card-stock ${st.cls}` : ""}" onclick="Products.openItem('${it.kind}', ${it.id})">
          <div class="prod-card-media">
            ${cardImage(it)}
            ${st
              ? `<span class="prod-card-status ${st.cls}">${st.label}</span>`
              : `<span class="prod-card-kind ${it.kind === "addon" ? "is-addon" : "is-product"}">${it.kind === "addon" ? "Add-on" : "Product"}</span>`}
          </div>
          <div class="prod-card-body">
            ${itemIdHtml(it)}
            <div class="prod-card-vendor">${ctx.esc(vendorLine(it))}</div>
            ${it.category
              ? `<div class="prod-card-cat"><span class="prod-cat-badge">${ctx.esc(it.category)}</span>${it.series ? `<span class="prod-card-series">${ctx.esc(it.series)}</span>` : ""}</div>`
              : `<div class="prod-card-cat"><span class="prod-cat-badge is-empty">No category</span></div>`}
            ${isStockProduct ? `<div class="prod-card-qty-block">
              <span class="prod-card-qty-num">${fmtQty(it.qty ?? 0)}</span>
              <span class="prod-card-qty-label">on hand</span>
            </div>` : ""}
            ${priceFootHtml(it, { stockMode: isStockProduct })}
          </div>
        </button>`;
      }).join("");
      el.innerHTML = `${summary}<div class="prod-grid">${cards}</div>${loadMoreHtml()}`;
    } else {
      el.innerHTML = `${summary}<div class="card table-wrap prod-table-wrap"><table class="data prod-table"><thead><tr>
        <th class="prod-th-thumb"></th>
        <th>Product ID</th>
        <th>Type</th>
        <th>Vendor</th>
        <th>Category</th>
        ${mainTab === "stock" ? "<th>On hand</th><th>Status</th>" : ""}
        <th>Sell</th>
        <th>Buy</th>
      </tr></thead><tbody>
        ${items.map(it => {
          const st = it.stock_status ? stockStatusMeta(it.stock_status) : null;
          return `<tr class="clickable" onclick="Products.openItem('${it.kind}', ${it.id})">
          <td>${listThumb(it)}</td>
          <td>
            <strong class="prod-list-id">${ctx.esc(it.our_product_id)}</strong>
            ${it.year_group ? `<span class="prod-year-pill">${ctx.esc(it.year_group)}</span>` : ""}
            ${it.vendor_product_id ? `<div class="prod-list-sub">Vendor # ${ctx.esc(it.vendor_product_id)}</div>` : ""}
            ${it.series ? `<div class="prod-list-sub">${ctx.esc(it.series)}</div>` : ""}
          </td>
          <td><span class="badge ${it.kind === "addon" ? "badge-amber" : "badge-blue"}">${it.kind === "addon" ? "Add-on" : "Product"}</span></td>
          <td>${ctx.esc(vendorLine(it))}</td>
          <td>${ctx.esc(it.category || "—")}</td>
          ${mainTab === "stock" ? `<td class="prod-list-qty-cell">${it.kind === "product" ? `<strong class="prod-list-qty-big">${it.qty ?? 0}</strong>` : "—"}</td>
          <td>${st ? `<span class="badge ${st.cls === "is-ok" ? "badge-green" : st.cls === "is-low" ? "badge-amber" : st.cls === "is-neg" ? "badge-red" : "badge-gray"}">${st.label}</span>` : "—"}</td>` : ""}
          <td class="prod-list-price">${it.kind === "product" ? (hasRealSell(it) ? fmtPrice(it.selling_price) : '<span class="prod-price-missing">Not set</span>') : "—"}</td>
          <td class="prod-list-price is-buy">${it.buying_price != null && it.buying_price !== "" ? fmtPrice(it.buying_price) : "—"}</td>
        </tr>`;
        }).join("")}
      </tbody></table></div>${loadMoreHtml()}`;
    }
    window._productsItems = items;
  }

  async function saveBulkSellPrices() {
    const inputs = [...document.querySelectorAll(".prod-bulk-sell-input")];
    const items = [];
    for (const inp of inputs) {
      const raw = String(inp.value || "").trim();
      if (!raw) continue;
      const n = parseFloat(raw);
      if (!Number.isFinite(n) || n < 0) return ctx.toast("Enter valid sell prices", "error");
      items.push({ catalog_product_id: Number(inp.dataset.id), selling_price: n });
    }
    if (!items.length) return ctx.toast("Enter at least one sell price", "error");
    ctx.showLoading?.();
    try {
      const res = await ctx.api("/stock/products/selling-price/bulk", {
        method: "POST",
        body: JSON.stringify({ items }),
      });
      ctx.invalidateCache?.("/stock");
      ctx.invalidateCache?.("/catalog");
      ctx.toast(`Saved ${res.updated || items.length} sell price(s)`, "success");
      await load();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function openItem(kind, id) {
    const it = (window._productsItems || []).find(x => x.kind === kind && x.id === id);
    if (it && it.open) it.open();
    else if (kind === "product") openProductDetail(id, mainTab === "stock" ? "stock" : "catalog");
    else AddonProducts.openDetail(id);
  }

  async function openProductDetail(id, section = "stock") {
    const sec = ["stock", "catalog", "addons", "alts"].includes(section) ? section : "stock";
    ctx.showLoading?.();
    try {
      let cat = null;
      let stock = null;
      try { cat = await ctx.api(`/catalog/products/${id}`, {}, 0); } catch (_) {}
      try { stock = await ctx.api(`/stock/products/${id}`, {}, 0); } catch (_) {}
      if (!cat && !stock) throw new Error("Product not found");

      const ourId = cat?.our_product_id || stock?.our_product_id || "Product";
      const year = cat?.year_group || stock?.year_group;
      const vendorName = cat?.vendor_name || stock?.vendor_name || (stock?.vendor_label || "—");
      const vendorCity = cat?.vendor_city || stock?.vendor_city || "";
      const buy = cat?.buying_price ?? stock?.buying_price;
      const rawSell = cat?.selling_price ?? stock?.selling_price;
      const sell = (rawSell != null && rawSell !== "" && Number(rawSell) !== Number(buy)) ? rawSell : null;
      const imgs = (cat?.image_urls?.length ? cat.image_urls : (stock?.image_urls || []));
      const images = imgs.length
        ? `<div class="catalog-detail-images">${imgs.map(u => `<img src="${ctx.esc(u)}" alt="" onclick="Products.enlargeImage(decodeURIComponent('${encodeURIComponent(u)}'))" style="cursor:zoom-in;" />`).join("")}</div>`
        : "";

      const statusBadge = stock
        ? (stock.stock_status === "in_stock" ? "badge-green"
          : stock.stock_status === "low_stock" ? "badge-amber"
          : stock.stock_status === "negative_stock" ? "badge-red" : "badge-gray")
        : "badge-gray";

      const sellHtml = sell != null && sell !== ""
        ? `<div class="stock-price-row"><strong>${fmtPrice(sell)}</strong>
            ${ctx.canWrite?.("catalog") || ctx.canWrite?.("stock") ? `<button class="btn btn-secondary btn-sm" onclick="Stock.setSellingPrice(${id}, '${ctx.esc(String(sell))}')">Set</button>` : ""}</div>`
        : `<div class="stock-price-row"><span class="prod-price-missing">Not set</span>
            ${ctx.canWrite?.("catalog") || ctx.canWrite?.("stock") ? `<button class="btn btn-primary btn-sm" onclick="Stock.setSellingPrice(${id}, '')">Set sell price</button>` : ""}</div>`;

      const ledgerRows = stock?.ledger?.length
        ? stock.ledger.map(e => `<tr class="clickable ledger-row" data-handler="stock" data-entry-id="${e.id}">
            <td style="font-size:12px;">${new Date(e.created_at).toLocaleString()}</td>
            <td><span class="badge badge-blue">${ctx.esc(e.entry_type)}</span></td>
            <td>${e.quantity_delta > 0 ? "+" : ""}${e.quantity_delta}</td>
            <td>${e.balance_after}</td>
            <td style="font-size:12px;color:var(--muted);">${ctx.esc(e.notes || "—")}</td>
          </tr>`).join("")
        : `<tr><td colspan="5" style="color:var(--muted);">No movements yet</td></tr>`;

      const stockPane = stock ? `
        <div class="stock-price-panel">
          <div class="stock-price-block">
            <span class="stock-price-label">Sell price</span>
            ${sellHtml}
          </div>
          <div class="stock-price-block">
            <span class="stock-price-label">Buy price</span>
            <strong>${fmtPrice(buy)}</strong>
          </div>
          <div class="stock-price-block">
            <span class="stock-price-label">Low stock threshold</span>
            <div class="stock-price-row">
              <strong>${stock.low_stock_threshold ?? 5}</strong>
              ${ctx.canWrite?.("stock") || ctx.canWrite?.("catalog")
                ? `<button class="btn btn-threshold" onclick="Stock.editThreshold(${id}, ${stock.low_stock_threshold ?? 5})">Set threshold</button>`
                : ""}
            </div>
          </div>
        </div>
        <div class="review-grid" style="margin:16px 0 20px;">
          ${ctx.reviewRow("On hand", stock.quantity_on_hand)}
          ${ctx.reviewRow("Status", (stock.stock_status || "").replace(/_/g, " "))}
          ${ctx.reviewRow("Pending order", stock.quantity_pending)}
        </div>
        <div class="detail-section">
          <h4>Stock Ledger</h4>
          <table class="data history-table"><thead><tr>
            <th>Date</th><th>Type</th><th>Qty</th><th>Balance</th><th>Notes</th>
          </tr></thead><tbody>${ledgerRows}</tbody></table>
        </div>`
        : `<div class="detail-section">
          <p style="color:var(--muted);font-size:14px;margin:0 0 12px;">No stock balance yet — receive goods to create it.</p>
          <button type="button" class="btn btn-primary btn-sm" onclick="App.closeDetail();Stock.openAddWizard()">+ Receive stock</button>
        </div>`;

      const priceHist = cat?.price_history?.length
        ? `<table class="data"><thead><tr><th>Buy</th><th>Sell</th><th>Recorded</th></tr></thead><tbody>
            ${cat.price_history.map(h => `<tr><td>${fmtPrice(h.buying_price)}</td><td>${h.selling_price ? fmtPrice(h.selling_price) : "—"}</td><td style="font-size:13px;">${ctx.fmtDate(h.recorded_at)}</td></tr>`).join("")}
          </tbody></table>`
        : '<p style="color:var(--muted);font-size:14px;">No price history</p>';

      const changeHist = cat && ctx.changeHistoryTable
        ? ctx.changeHistoryTable(cat.change_history)
        : "";

      const catalogPane = cat ? `
        <div class="review-grid" style="margin-bottom:20px;">
          ${ctx.reviewRow("Vendor Product ID", cat.vendor_product_id)}
          ${ctx.reviewRow("Series", cat.series)}
          ${ctx.reviewRow("Unit", cat.unit)}
          ${ctx.reviewRow("Year Group", cat.year_group)}
          ${ctx.reviewRow("Category", cat.category)}
          ${ctx.reviewRow("Created", ctx.fmtDate(cat.created_at))}
          ${ctx.reviewRow("Updated", ctx.fmtDate(cat.updated_at))}
        </div>
        <div class="detail-section"><h4>Price History</h4>${priceHist}</div>
        ${changeHist}`
        : `<p style="color:var(--muted);font-size:14px;">Catalog record unavailable.</p>`;

      const altSource = cat?.alternatives?.length ? cat.alternatives : (stock?.alternatives || []);
      const altManageBtn = `<button type="button" class="btn btn-secondary btn-sm" style="margin-top:10px;" onclick="Products.openAlternativesManager(${id})">Manage alternatives</button>`;
      const altPane = altSource.length
        ? `<div class="alt-chip-row">${altSource.map(a => {
            const img = (a.image_urls && a.image_urls[0]) || "";
            const place = [a.alternative_vendor_name || a.vendor_name, a.alternative_vendor_city || a.vendor_city].filter(Boolean).join(" · ");
            const altId = a.alternative_our_product_id || a.our_product_id;
            const altPid = a.alternative_product_id || a.catalog_product_id || a.id;
            return `<button type="button" class="alt-chip" onclick="event.stopPropagation();${altPid ? `Products.openProductDetail(${altPid}, 'alts')` : `Products.enlargeImage(decodeURIComponent('${encodeURIComponent(img || "")}'))`}">
              ${img ? `<img src="${ctx.esc(img)}" alt="" />` : `<span class="alt-chip-empty"></span>`}
              <span class="alt-chip-body">
                <strong>${ctx.esc(altId)}</strong>
                <span>${ctx.esc(place || "—")}</span>
                <span>${fmtPrice(a.buying_price)}${a.selling_price ? ` / ${fmtPrice(a.selling_price)}` : ""}</span>
              </span>
            </button>`;
          }).join("")}</div>${altManageBtn}`
        : `<p style="color:var(--muted);font-size:14px;margin:0;">No alternatives</p>${altManageBtn}`;

      const addonPane = cat?.addon_links?.length
        ? `<div class="alt-chip-row">${cat.addon_links.map(l => {
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

      const tabBtn = (key, label) =>
        `<button type="button" class="prod-detail-tab${sec === key ? " active" : ""}" onclick="Products.openProductDetail(${id}, '${key}')">${label}</button>`;

      ctx.openDetail(ourId, `
        <div class="profile-hero prod-detail-hero" style="margin:-24px -24px 16px;border-radius:0;">
          <h2>${ctx.esc(ourId)}${year ? ` <span class="prod-year-pill">${ctx.esc(year)}</span>` : ""}</h2>
          <p>${ctx.esc(vendorName)}${vendorCity ? ` · ${ctx.esc(vendorCity)}` : ""}</p>
          <div class="profile-meta">
            <span class="badge badge-green">Sell ${sell != null && sell !== "" ? fmtPrice(sell) : "—"}</span>
            <span class="badge badge-blue">Buy ${buy != null ? fmtPrice(buy) : "—"}</span>
            ${stock
              ? `<span class="badge badge-blue">On hand: ${stock.quantity_on_hand}</span>
                 <span class="badge ${statusBadge}">${ctx.esc((stock.stock_status || "").replace(/_/g, " "))}</span>`
              : `<span class="badge badge-gray">No stock yet</span>`}
            ${cat?.category ? `<span class="badge badge-gray">${ctx.esc(cat.category)}</span>` : ""}
          </div>
          ${images}
        </div>
        <div class="prod-detail-tabs">
          ${tabBtn("stock", "Stock / Ledger")}
          ${tabBtn("catalog", "Catalog")}
          ${tabBtn("addons", "Add-ons")}
          ${tabBtn("alts", "Alternatives")}
        </div>
        <div class="prod-detail-pane" data-pane="stock" style="${sec === "stock" ? "" : "display:none;"}">${stockPane}</div>
        <div class="prod-detail-pane" data-pane="catalog" style="${sec === "catalog" ? "" : "display:none;"}">${catalogPane}</div>
        <div class="prod-detail-pane" data-pane="addons" style="${sec === "addons" ? "" : "display:none;"}">${addonPane}</div>
        <div class="prod-detail-pane" data-pane="alts" style="${sec === "alts" ? "" : "display:none;"}">${altPane}</div>`,
        `${ctx.canWrite?.("catalog") && cat
          ? `<button class="btn btn-danger btn-sm" onclick="Catalog.deleteProduct(${id})">Delete</button>
             <button class="btn btn-secondary btn-sm" onclick="Catalog.openEdit(${id}, '${sec === "stock" ? "stock" : "catalog"}')">Edit</button>`
          : ""}
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


  let altsBoardRows = [];
  let altsBoardSearch = "";
  let altsPickerForId = null;
  let altsPickerQuery = "";
  let altsPickerStock = [];
  let altsPickerTimer = null;

  async function openAlternativesManager(productId) {
    ctx.showLoading?.();
    try {
      altsBoardRows = await ctx.api("/catalog/alternatives-board", {}, 0);
      altsBoardSearch = "";
      altsPickerForId = null;
      // Prefill board search with the product you opened from (main product).
      if (productId != null && productId !== "") {
        const pid = Number(productId);
        const hit = (altsBoardRows || []).find(p => Number(p.id) === pid);
        if (hit?.our_product_id) {
          altsBoardSearch = String(hit.our_product_id);
        } else {
          try {
            const cat = await ctx.api(`/catalog/products/${pid}`, {}, 0);
            if (cat?.our_product_id) altsBoardSearch = String(cat.our_product_id);
          } catch (_) { /* ignore */ }
        }
      }
      renderAlternativesBoard();
      document.getElementById("alts-board-modal")?.classList.remove("hidden");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function closeAlternativesManager() {
    document.getElementById("alts-board-modal")?.classList.add("hidden");
    altsPickerForId = null;
  }

  function onAltsBoardSearch(val) {
    altsBoardSearch = val || "";
    renderAlternativesBoard();
  }

  function filteredAltsBoard() {
    const q = altsBoardSearch.trim().toLowerCase();
    if (!q) return altsBoardRows;
    const scored = [];
    for (const p of altsBoardRows) {
      const id = String(p.our_product_id || "").toLowerCase();
      const vendor = String(p.vendor_name || "").toLowerCase();
      const city = String(p.vendor_city || "").toLowerCase();
      const altIds = (p.alternatives || []).map(a => String(a.our_product_id || "").toLowerCase());
      let score = 0;
      if (id === q) score = 100;
      else if (id.startsWith(q)) score = 80;
      else if (id.includes(q)) score = 40;
      else if (vendor.startsWith(q) || altIds.some(a => a === q || a.startsWith(q))) score = 30;
      else if (vendor.includes(q) || city.includes(q) || altIds.some(a => a.includes(q))) score = 10;
      else continue;
      scored.push({ p, score });
    }
    scored.sort((a, b) => b.score - a.score || String(a.p.our_product_id).localeCompare(String(b.p.our_product_id)));
    return scored.map(x => x.p);
  }

  function renderAlternativesBoard() {
    const body = document.getElementById("alts-board-body");
    if (!body) return;
    const rows = filteredAltsBoard();
    const canWrite = !!ctx.canWrite?.("catalog");
    const boardEl = document.getElementById("alts-board-search");
    const boardCaret = boardEl && document.activeElement === boardEl
      ? { start: boardEl.selectionStart, end: boardEl.selectionEnd }
      : null;
    const pickerEl = document.getElementById("alts-picker-search");
    const pickerCaret = pickerEl && document.activeElement === pickerEl
      ? { start: pickerEl.selectionStart, end: pickerEl.selectionEnd }
      : null;

    body.innerHTML = `
      <div class="alts-toolbar">
        <div class="alts-search-slot" style="flex:1;min-width:200px;">
          ${HubUI.searchBar({
            id: "alts-board-search",
            value: altsBoardSearch,
            placeholder: "Search product ID, vendor…",
            oninput: "Products.onAltsBoardSearch(this.value)",
          })}
        </div>
        <span class="alts-toolbar-count">${rows.length} product${rows.length === 1 ? "" : "s"}</span>
      </div>
      <div class="alts-col-head">
        <div>Main product</div>
        <div>Alternative 1</div>
        <div>Alternative 2</div>
        <div>Alternative 3</div>
      </div>
      <div class="alts-grid-wrap">
        ${rows.length ? rows.map(p => renderAltBoardRow(p, canWrite)).join("") : HubUI.emptyState({ title: "No products match", sub: "Clear search or add catalog products first." })}
      </div>
      ${altsPickerForId ? renderAltPicker(canWrite) : ""}`;

    if (pickerCaret) {
      const el = document.getElementById("alts-picker-search");
      if (el) {
        el.focus();
        try { el.setSelectionRange(pickerCaret.start, pickerCaret.end); } catch (_) { /* ignore */ }
      }
    } else if (boardCaret) {
      const el = document.getElementById("alts-board-search");
      if (el) {
        el.focus();
        try { el.setSelectionRange(boardCaret.start, boardCaret.end); } catch (_) { /* ignore */ }
      }
    } else if (altsPickerForId && !altsPickerQuery) {
      setTimeout(() => document.getElementById("alts-picker-search")?.focus(), 0);
    }
  }

  function renderAltBoardRow(p, canWrite) {
    const alts = [...(p.alternatives || [])];
    while (alts.length < 3) alts.push(null);
    const slots = alts.slice(0, 3).map((a, i) => {
      if (a) {
        const img = (a.image_urls && a.image_urls[0]) || "";
        return `<div class="alts-slot filled">
          ${img ? `<img src="${ctx.esc(img)}" alt="" onclick="Products.enlargeImage(decodeURIComponent('${encodeURIComponent(img)}'))" />` : `<div class="alts-slot-ph"></div>`}
          <strong>${ctx.esc(a.our_product_id)}</strong>
          <span>${ctx.esc(a.vendor_name || "—")}${a.vendor_city ? ` · ${ctx.esc(a.vendor_city)}` : ""}</span>
          <span class="alts-slot-price">${fmtPrice(a.buying_price)}${a.selling_price ? ` / ${fmtPrice(a.selling_price)}` : ""}</span>
          ${canWrite ? `<button type="button" class="btn btn-ghost btn-sm" onclick="Products.removeAlternative(${p.id}, '${ctx.esc(a.our_product_id).replace(/'/g, "\\'")}')">Remove</button>` : ""}
        </div>`;
      }
      return `<div class="alts-slot empty">
        <p>No alternative</p>
        ${canWrite ? `<button type="button" class="btn btn-secondary btn-sm" onclick="Products.openAltPicker(${p.id})">+ Add</button>` : ""}
      </div>`;
    }).join("");

    const img = (p.image_urls && p.image_urls[0]) || "";
    return `<div class="alts-row" data-product-id="${p.id}">
      <div class="alts-slot main">
        ${img ? `<img src="${ctx.esc(img)}" alt="" onclick="Products.enlargeImage(decodeURIComponent('${encodeURIComponent(img)}'))" />` : `<div class="alts-slot-ph"></div>`}
        <strong>${ctx.esc(p.our_product_id)}</strong>
        <span>${ctx.esc(p.vendor_name || "—")}${p.vendor_city ? ` · ${ctx.esc(p.vendor_city)}` : ""}</span>
        <span class="alts-slot-price">Buy ${fmtPrice(p.buying_price)}${p.selling_price ? ` · Sell ${fmtPrice(p.selling_price)}` : ""}</span>
      </div>
      ${slots}
    </div>`;
  }

  function renderAltPicker(canWrite) {
    const main = altsBoardRows.find(p => p.id === altsPickerForId);
    const linked = new Set((main?.alternatives || []).map(a => a.our_product_id));
    linked.add(main?.our_product_id);
    const q = altsPickerQuery.trim().toLowerCase();
    const scored = [];
    for (const s of (altsPickerStock || [])) {
      if (linked.has(s.our_product_id)) continue;
      if (!q) { scored.push({ s, score: 0 }); continue; }
      const id = String(s.our_product_id || "").toLowerCase();
      const vendor = String(s.vendor_name || "").toLowerCase();
      let score = 0;
      if (id === q) score = 100;
      else if (id.startsWith(q)) score = 80;
      else if (id.includes(q)) score = 40;
      else if (vendor.startsWith(q)) score = 30;
      else if (vendor.includes(q)) score = 10;
      else continue;
      scored.push({ s, score });
    }
    scored.sort((a, b) => b.score - a.score || String(a.s.our_product_id).localeCompare(String(b.s.our_product_id)));
    const hits = scored.map(x => x.s).slice(0, 40);

    return `<div class="alts-picker-overlay">
      <div class="alts-picker" onclick="event.stopPropagation()">
        <div class="alts-picker-head">
          <div>
            <strong>Add alternative</strong>
            <p>for ${ctx.esc(main?.our_product_id || "")} — tap a product to link</p>
          </div>
          <button type="button" class="btn-ghost" onclick="Products.closeAltPicker()">✕</button>
        </div>
        <input class="input" id="alts-picker-search" placeholder="Filter by product ID…"
          value="${ctx.esc(altsPickerQuery)}" oninput="Products.onAltPickerSearch(this.value)" autocomplete="off" />
        <div class="alts-picker-list">
          ${hits.length ? hits.map(s => {
            const img = (s.image_urls && s.image_urls[0]) || "";
            return `<button type="button" class="alts-picker-item" onclick="Products.addAlternative(${altsPickerForId}, '${ctx.esc(s.our_product_id).replace(/'/g, "\\'")}')">
              ${img ? `<img src="${ctx.esc(img)}" alt="" />` : `<div class="alts-slot-ph sm"></div>`}
              <div class="alts-picker-meta">
                <strong>${ctx.esc(s.our_product_id)}</strong>
                <span>${ctx.esc(s.vendor_name || "—")} · Stock ${s.quantity_on_hand ?? 0}</span>
                <span>${s.selling_price ? `Sell ${fmtPrice(s.selling_price)}` : `Buy ${fmtPrice(s.buying_price)}`}</span>
              </div>
              <span class="btn btn-primary btn-sm">Add</span>
            </button>`;
          }).join("") : `<p class="alts-picker-empty">${q ? "No matches" : "Loading products…"}</p>`}
        </div>
      </div>
    </div>`;
  }

  async function openAltPicker(productId) {
    const main = altsBoardRows.find(p => p.id === productId);
    if ((main?.alternatives || []).length >= 3) {
      ctx.toast("Max 3 alternatives", "error");
      return;
    }
    altsPickerForId = productId;
    altsPickerQuery = "";
    renderAlternativesBoard();
    try {
      altsPickerStock = await ctx.api("/stock/products?lite=1", {}, 120000);
      renderAlternativesBoard();
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  function closeAltPicker() {
    altsPickerForId = null;
    renderAlternativesBoard();
  }

  function onAltPickerSearch(val) {
    altsPickerQuery = val || "";
    if (altsPickerTimer) clearTimeout(altsPickerTimer);
    altsPickerTimer = setTimeout(() => renderAlternativesBoard(), 120);
  }

  async function addAlternative(productId, altOurId) {
    ctx.showLoading?.();
    try {
      await ctx.api(`/catalog/products/${productId}/alternatives`, {
        method: "POST",
        body: JSON.stringify({ alternative_our_product_id: altOurId }),
      });
      ctx.toast("Alternative added", "success");
      altsBoardRows = await ctx.api("/catalog/alternatives-board", {}, 0);
      altsPickerForId = null;
      ctx.invalidateCache?.("/catalog");
      ctx.invalidateCache?.("/stock");
      renderAlternativesBoard();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function removeAlternative(productId, altOurId) {
    if (!confirm(`Remove alternative ${altOurId}?`)) return;
    ctx.showLoading?.();
    try {
      await ctx.api(`/catalog/products/${productId}/alternatives/${encodeURIComponent(altOurId)}`, { method: "DELETE" });
      ctx.toast("Alternative removed", "success");
      altsBoardRows = await ctx.api("/catalog/alternatives-board", {}, 0);
      ctx.invalidateCache?.("/catalog");
      renderAlternativesBoard();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function enlargeImage(url) {
    if (!url) return;
    const ov = document.getElementById("img-lightbox");
    const img = document.getElementById("img-lightbox-img");
    if (!ov || !img) return;
    img.src = url;
    ov.classList.remove("hidden");
  }

  function closeLightbox() {
    document.getElementById("img-lightbox")?.classList.add("hidden");
    const img = document.getElementById("img-lightbox-img");
    if (img) img.src = "";
  }

  return {
    init, showHub, setMainTab, setTypeFilter, setViewMode, onSearch, clearSearch,
    onFilterChange, clearFilters, setStockChip, setAttentionFilter, toggleFilters,
    load, loadMoreCatalog, refreshHub,
    openItem, openProductDetail, saveBulkSellPrices,
    openAlternativesManager, closeAlternativesManager, onAltsBoardSearch,
    openAltPicker, closeAltPicker, onAltPickerSearch, addAlternative, removeAlternative,
    enlargeImage, closeLightbox,
    getTab: () => mainTab,
  };
})();
