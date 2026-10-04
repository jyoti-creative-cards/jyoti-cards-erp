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
    if (it.kind === "addon") return "";
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

  function showAddons() {
    addonMode = true;
    const title = document.getElementById("products-panel-title");
    const sub = document.getElementById("products-panel-sub");
    if (title) title.textContent = "Add-ons";
    if (sub) sub.textContent = "Names and stock · not part of the product catalog";
    document.getElementById("products-mode")?.classList.add("hidden");
    document.getElementById("products-filters-toggle")?.classList.add("hidden");
    document.getElementById("products-filters-wrap")?.classList.add("hidden");
    const back = document.getElementById("products-addons-btn");
    if (back) {
      back.textContent = "← Products";
      back.onclick = () => Products.showProducts();
    }
    updatePrimaryAction();
    load();
  }

  function showProducts() {
    addonMode = false;
    document.getElementById("products-mode")?.classList.remove("hidden");
    document.getElementById("products-filters-toggle")?.classList.remove("hidden");
    const back = document.getElementById("products-addons-btn");
    if (back) {
      back.textContent = "Add-ons";
      back.onclick = () => Products.showAddons();
    }
    setMainTab(mainTab || "stock");
  }

  function updatePrimaryAction() {
    const action = document.getElementById("products-action-btn");
    if (!action) return;
    if (addonMode) {
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
    if (addonMode) {
      const addonItems = (items || []).filter(it => it.kind === "addon");
      const ac = {
        all: addonItems.length,
        low_stock: addonItems.filter(it => it.stock_status === "low_stock").length,
        out_of_stock: addonItems.filter(it => it.stock_status === "out_of_stock").length,
        negative_stock: addonItems.filter(it => it.stock_status === "negative_stock").length,
      };
      OrdersUI.actionChips({
        hostId: "products-action-chips",
        active: attentionFilter,
        onclickFn: "Products.setAttentionFilter",
        items: [
          { id: "all", label: "All", count: ac.all },
          { id: "low_stock", label: "Low", count: ac.low_stock },
          { id: "out_of_stock", label: "Out", count: ac.out_of_stock },
          { id: "negative_stock", label: "Negative", count: ac.negative_stock },
        ],
      });
      return;
    }
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
    return !!(filters.vendor_id || filters.category || filters.year_group || filters.price_min || filters.price_max || filters.stock_status || filters.no_sell_price || filters.no_addons);
  }

  function onFilterChange() {
    filters.vendor_id = document.getElementById("pf-vendor")?.value || "";
    filters.category = document.getElementById("pf-category")?.value || "";
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
      lookups.categories = await ctx.api("/catalog/categories") || [];
    } catch (_) {
      lookups.categories = lookups.categories || [];
    }
    try {
      lookups.year_groups = await ctx.api("/catalog/year-groups") || [];
    } catch (_) {
      lookups.year_groups = lookups.year_groups || [];
    }
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

  function stockStatusMeta(status) {
    const map = {
      in_stock: { cls: "is-ok", label: "In stock" },
      low_stock: { cls: "is-low", label: "Low stock" },
      out_of_stock: { cls: "is-out", label: "Out of stock" },
      negative_stock: { cls: "is-neg", label: "Negative" },
    };
    return map[status] || { cls: "is-out", label: status || "—" };
  }

