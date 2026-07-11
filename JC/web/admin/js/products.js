/** Products — Stock / Catalog tabs with unified Products + Add-ons views */
const Products = (() => {
  let ctx = {};
  let mainTab = "stock";
  let typeFilter = "all";
  let searchQuery = "";
  let filters = { vendor_id: "", category: "", series: "", price_min: "", price_max: "", stock_status: "", no_sell_price: false, no_addons: false };
  let catalogProducts = [];
  let stockProducts = [];
  let addons = [];
  let lookups = { categories: [], series: [] };
  let viewMode = "grid";

  function init(context) { ctx = context; }

  function showHub() { setMainTab(mainTab || "stock"); }

  function setMainTab(tab) {
    mainTab = tab;
    document.getElementById("ptab-stock")?.classList.toggle("active", tab === "stock");
    document.getElementById("ptab-catalog")?.classList.toggle("active", tab === "catalog");
    const title = document.getElementById("products-panel-title");
    const sub = document.getElementById("products-panel-sub");
    const action = document.getElementById("products-action-btn");
    if (title) title.textContent = tab === "stock" ? "Stock" : "Catalog";
    if (sub) sub.textContent = tab === "stock"
      ? "Qty on hand first — tap a tile or status chip to filter"
      : "All products you sell — tap a tile to open or edit";
    const search = document.getElementById("products-search-input");
    if (search) {
      search.placeholder = tab === "stock"
        ? "Search stock by product ID, vendor, or category…"
        : "Search by product ID, vendor, or category…";
    }
    if (action) {
      if (tab === "stock") {
        action.textContent = "+ Add Stock";
        action.onclick = () => Stock.openAddWizard();
        action.classList.remove("hidden");
      } else {
        action.textContent = "+ New Product";
        action.onclick = () => Catalog.openWizard();
        action.classList.toggle("hidden", !ctx.canWrite?.("catalog"));
      }
    }
    load();
  }

  function setTypeFilter(t) {
    typeFilter = t;
    ["all", "products", "addons"].forEach(k => {
      document.getElementById(`ptype-${k}`)?.classList.toggle("active", k === t);
    });
    render();
  }

  function setViewMode(mode) {
    viewMode = mode;
    document.getElementById("products-view-grid")?.classList.toggle("active", mode === "grid");
    document.getElementById("products-view-list")?.classList.toggle("active", mode === "list");
    render();
  }

  function onSearch(val) {
    searchQuery = val;
    document.getElementById("products-search-clear")?.classList.toggle("hidden", !String(val || "").trim());
    debouncedLoad();
  }

  function clearSearch() {
    searchQuery = "";
    const input = document.getElementById("products-search-input");
    if (input) input.value = "";
    document.getElementById("products-search-clear")?.classList.add("hidden");
    load();
  }

  const debouncedLoad = (() => {
    let t;
    return () => { clearTimeout(t); t = setTimeout(() => load(), 300); };
  })();

  function hasActiveFilters() {
    return !!(filters.vendor_id || filters.category || filters.series || filters.price_min || filters.price_max || filters.stock_status || filters.no_sell_price || filters.no_addons);
  }

  function onFilterChange() {
    filters.vendor_id = document.getElementById("pf-vendor")?.value || "";
    filters.category = document.getElementById("pf-category")?.value || "";
    filters.series = document.getElementById("pf-series")?.value || "";
    filters.price_min = document.getElementById("pf-price-min")?.value || "";
    filters.price_max = document.getElementById("pf-price-max")?.value || "";
    filters.stock_status = document.getElementById("pf-stock-status")?.value || "";
    filters.no_sell_price = !!document.getElementById("pf-no-sell")?.checked;
    filters.no_addons = !!document.getElementById("pf-no-addons")?.checked;
    document.getElementById("products-clear-filters")?.classList.toggle("hidden", !hasActiveFilters());
    render();
  }

  function clearFilters() {
    filters = { vendor_id: "", category: "", series: "", price_min: "", price_max: "", stock_status: "", no_sell_price: false, no_addons: false };
    renderFilters();
    document.getElementById("products-clear-filters")?.classList.add("hidden");
    render();
  }

  async function ensureLookups() {
    if (lookups.categories.length) return;
    try {
      const rows = await ctx.api("/lookups", {}, 120000);
      lookups.categories = rows.filter(r => r.lookup_type === "category").map(r => r.value);
      lookups.series = rows.filter(r => r.lookup_type === "series").map(r => r.value);
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
      <label class="prod-filter-field prod-filter-price">
        <span class="prod-filter-label">Price</span>
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
        No sell price
      </label>
      <label class="prod-filter-chip ${filters.no_addons ? "is-on" : ""}">
        <input type="checkbox" id="pf-no-addons" ${filters.no_addons ? "checked" : ""} onchange="Products.onFilterChange()" />
        No add-ons
      </label>
      <button type="button" class="btn btn-secondary btn-sm" onclick="Products.openAlternativesManager()">Manage alternatives</button>`;
    document.getElementById("products-clear-filters")?.classList.toggle("hidden", !hasActiveFilters());
  }

  async function load() {
    ctx.showLoading?.();
    try {
      await ensureLookups();
      const q = searchQuery.trim();
      const searchParam = q ? `?search=${encodeURIComponent(q)}` : "";
      if (mainTab === "stock") {
        stockProducts = await ctx.api(`/stock/products${searchParam}`, {}, q ? 0 : 60000);
        if (ctx.canRead?.("addons")) {
          addons = await ctx.api(`/addons${searchParam}`, {}, q ? 0 : 60000);
        } else addons = [];
      } else {
        const catR = await ctx.api(`/catalog/products?limit=200${q ? "&search=" + encodeURIComponent(q) : ""}`, {}, q ? 0 : 60000);
        catalogProducts = catR.items || catR || [];
        if (ctx.canRead?.("addons")) {
          addons = await ctx.api(`/addons${searchParam}`, {}, q ? 0 : 60000);
        } else addons = [];
      }
      renderFilters();
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
    const counts = { in_stock: 0, low_stock: 0, out_of_stock: 0, negative_stock: 0 };
    let units = 0;
    productsOnly.forEach(it => {
      if (counts[it.stock_status] != null) counts[it.stock_status] += 1;
      units += Number(it.qty) || 0;
    });
    const chip = (key, label, cls) => {
      const n = counts[key] || 0;
      const active = filters.stock_status === key;
      return `<button type="button" class="prod-stock-chip ${cls}${active ? " active" : ""}" onclick="Products.setStockChip('${key}')">
        <strong>${n}</strong><span>${label}</span>
      </button>`;
    };
    return `<div class="prod-stock-summary">
      <div class="prod-stock-units">
        <strong>${units.toLocaleString("en-IN")}</strong>
        <span>units on hand</span>
      </div>
      <div class="prod-stock-chips">
        ${chip("in_stock", "In stock", "chip-ok")}
        ${chip("low_stock", "Low", "chip-low")}
        ${chip("out_of_stock", "Out", "chip-out")}
        ${chip("negative_stock", "Negative", "chip-neg")}
        ${filters.stock_status ? `<button type="button" class="prod-stock-chip chip-clear" onclick="Products.setStockChip('')">Show all</button>` : ""}
      </div>
    </div>`;
  }

  function setStockChip(status) {
    filters.stock_status = filters.stock_status === status ? "" : status;
    const sel = document.getElementById("pf-stock-status");
    if (sel) sel.value = filters.stock_status;
    document.getElementById("products-clear-filters")?.classList.toggle("hidden", !hasActiveFilters());
    render();
  }

  function buildItems() {
    const items = [];
    if (mainTab === "stock") {
      if (typeFilter !== "addons") {
        stockProducts.forEach(p => items.push({
          kind: "product",
          id: p.catalog_product_id,
          our_product_id: p.our_product_id,
          vendor_name: p.vendor_name,
          category: p.category,
          series: p.series,
          vendor_id: p.vendor_id,
          price: p.selling_price, // sell price only on stock cards
          buying_price: p.buying_price,
          selling_price: p.selling_price,
          addon_count: p.addon_count || 0,
          qty: p.quantity_on_hand,
          stock_status: p.stock_status,
          image_urls: p.image_urls,
          open: () => Stock.openDetail(p.catalog_product_id),
        }));
      }
      if (typeFilter !== "products" && ctx.canRead?.("addons")) {
        addons.forEach(a => items.push({
          kind: "addon",
          id: a.id,
          our_product_id: a.our_product_id,
          vendor_name: a.vendor_name,
          category: a.category,
          series: null,
          vendor_id: a.vendor_id,
          price: a.buying_price,
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
          vendor_name: p.vendor_name,
          category: p.category,
          series: p.series,
          vendor_id: p.vendor_id,
          price: p.selling_price || p.buying_price,
          buying_price: p.buying_price,
          selling_price: p.selling_price,
          addon_count: p.addon_count || 0,
          qty: null,
          stock_status: null,
          image_urls: p.image_urls,
          open: () => Catalog.openDetail(p.id),
        }));
      }
      if (typeFilter !== "products" && ctx.canRead?.("addons")) {
        addons.forEach(a => items.push({
          kind: "addon",
          id: a.id,
          our_product_id: a.our_product_id,
          vendor_name: a.vendor_name,
          category: a.category,
          series: null,
          vendor_id: a.vendor_id,
          price: a.buying_price,
          qty: null,
          stock_status: null,
          image_urls: a.image_urls,
          open: () => AddonProducts.openDetail(a.id),
        }));
      }
    }
    return items;
  }

  function applyFilters(items, { ignoreStockStatus = false } = {}) {
    return items.filter(it => {
      if (filters.vendor_id && String(it.vendor_id) !== String(filters.vendor_id)) return false;
      if (filters.category && (it.category || "") !== filters.category) return false;
      if (filters.series && (it.series || "") !== filters.series) return false;
      const price = Number(it.price);
      if (filters.price_min && !Number.isNaN(price) && price < Number(filters.price_min)) return false;
      if (filters.price_max && !Number.isNaN(price) && price > Number(filters.price_max)) return false;
      if (!ignoreStockStatus && mainTab === "stock" && filters.stock_status && it.stock_status !== filters.stock_status) return false;
      if (filters.no_sell_price && it.kind === "product") {
        if (it.selling_price != null && it.selling_price !== "") return false;
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

  function updateResultCount(shown, total) {
    const el = document.getElementById("products-result-count");
    if (!el) return;
    if (!total && !shown) {
      el.textContent = "";
      return;
    }
    if (shown === total) el.textContent = `${shown} item${shown === 1 ? "" : "s"}`;
    else el.textContent = `Showing ${shown} of ${total}`;
  }

  function render() {
    const el = document.getElementById("products-content");
    if (!el) return;
    const rawCount = mainTab === "stock"
      ? (typeFilter === "addons" ? addons.length : typeFilter === "products" ? stockProducts.length : stockProducts.length + addons.length)
      : (typeFilter === "addons" ? addons.length : typeFilter === "products" ? catalogProducts.length : catalogProducts.length + addons.length);
    const items = normalizeItems();
    updateResultCount(items.length, rawCount);

    if (!items.length) {
      if (!rawCount) {
        const canCatalog = ctx.canWrite?.("catalog");
        const canAddon = ctx.canWrite?.("addons");
        if (typeFilter === "addons") {
          el.innerHTML = `<div class="empty-state prod-empty">
            <p class="prod-empty-title">No add-ons yet</p>
            <p class="prod-empty-sub">Create add-ons from Catalog, or switch to Products.</p>
            ${canAddon ? `<button class="btn btn-primary btn-lg" onclick="AddonProducts.openWizard()">+ New Add-on</button>` : ""}
          </div>`;
        } else if (mainTab === "catalog") {
          el.innerHTML = `<div class="empty-state prod-empty">
            <p class="prod-empty-title">Catalog is empty</p>
            <p class="prod-empty-sub">Add products here first. Stock fills after you receive vendor orders.</p>
            <div class="prod-empty-actions">
              ${canCatalog ? `<button class="btn btn-primary btn-lg" onclick="Catalog.openWizard()">+ New Product</button>` : ""}
              ${canAddon ? `<button class="btn btn-secondary btn-lg" onclick="AddonProducts.openWizard()">+ New Add-on</button>` : ""}
            </div>
          </div>`;
        } else {
          el.innerHTML = `<div class="empty-state prod-empty">
            <p class="prod-empty-title">No stock yet</p>
            <p class="prod-empty-sub">Create catalog products, place a vendor order, then bill/receive to build stock.</p>
            <div class="prod-empty-actions">
              ${canCatalog ? `<button class="btn btn-primary btn-lg" onclick="Products.setMainTab('catalog')">Go to Catalog</button>` : ""}
              <button class="btn btn-secondary btn-lg" onclick="Stock.openAddWizard()">+ Add Stock</button>
            </div>
          </div>`;
        }
      } else {
        const summaryEmpty = stockSummaryHtml(applyFilters(buildItems(), { ignoreStockStatus: true }));
        el.innerHTML = `${summaryEmpty}<div class="empty-state prod-empty">
          <p class="prod-empty-title">No items match</p>
          <p class="prod-empty-sub">Clear search or filters to see ${rawCount} item${rawCount === 1 ? "" : "s"}.</p>
          <button class="btn btn-secondary" onclick="Products.clearSearch();Products.clearFilters();">Clear all</button>
        </div>`;
      }
      window._productsItems = [];
      return;
    }

    const summary = stockSummaryHtml(applyFilters(buildItems(), { ignoreStockStatus: true }));

    if (viewMode === "grid") {
      const cards = items.map(it => {
        if (mainTab === "stock" && it.kind === "product") {
          const st = stockStatusMeta(it.stock_status);
          return `<button type="button" class="prod-card prod-card-stock ${st.cls}" onclick="Products.openItem('${it.kind}', ${it.id})">
            <div class="prod-card-media">
              ${cardImage(it)}
              <span class="prod-card-status ${st.cls}">${st.label}</span>
            </div>
            <div class="prod-card-body">
              <div class="prod-card-id">${ctx.esc(it.our_product_id)}</div>
              <div class="prod-card-vendor">${ctx.esc(it.vendor_name || "—")}</div>
              ${it.category ? `<div class="prod-card-cat">${ctx.esc(it.category)}${it.series ? ` · ${ctx.esc(it.series)}` : ""}</div>` : ""}
              <div class="prod-card-qty-block">
                <span class="prod-card-qty-num">${it.qty ?? 0}</span>
                <span class="prod-card-qty-label">on hand</span>
              </div>
              <div class="prod-card-foot">
                <strong class="prod-card-price">${it.selling_price ? fmtPrice(it.selling_price) : '<span class="prod-price-missing">No sell price</span>'}</strong>
                <span class="badge badge-blue">Product</span>
              </div>
            </div>
          </button>`;
        }
        return `<button type="button" class="prod-card" onclick="Products.openItem('${it.kind}', ${it.id})">
          <div class="prod-card-media">
            ${cardImage(it)}
            <span class="prod-card-kind ${it.kind === "addon" ? "is-addon" : "is-product"}">${it.kind === "addon" ? "Add-on" : "Product"}</span>
          </div>
          <div class="prod-card-body">
            <div class="prod-card-id">${ctx.esc(it.our_product_id)}</div>
            <div class="prod-card-vendor">${ctx.esc(it.vendor_name || "—")}</div>
            ${it.category ? `<div class="prod-card-cat">${ctx.esc(it.category)}${it.series ? ` · ${ctx.esc(it.series)}` : ""}</div>` : ""}
            <div class="prod-card-foot">
              <strong class="prod-card-price">${fmtPrice(it.price)}</strong>
              ${it.kind === "addon" ? `<span class="badge badge-amber">Add-on</span>` : ""}
            </div>
          </div>
        </button>`;
      }).join("");
      el.innerHTML = `${summary}<div class="prod-grid">${cards}</div>`;
    } else {
      el.innerHTML = `${summary}<div class="card table-wrap prod-table-wrap"><table class="data prod-table"><thead><tr>
        <th class="prod-th-thumb"></th>
        <th>Product</th>
        <th>Type</th>
        <th>Vendor</th>
        <th>Category</th>
        ${mainTab === "stock" ? "<th>On hand</th><th>Status</th>" : ""}
        <th>Price</th>
      </tr></thead><tbody>
        ${items.map(it => {
          const st = it.stock_status ? stockStatusMeta(it.stock_status) : null;
          return `<tr class="clickable" onclick="Products.openItem('${it.kind}', ${it.id})">
          <td>${listThumb(it)}</td>
          <td>
            <strong class="prod-list-id">${ctx.esc(it.our_product_id)}</strong>
            ${it.series ? `<div class="prod-list-sub">${ctx.esc(it.series)}</div>` : ""}
          </td>
          <td><span class="badge ${it.kind === "addon" ? "badge-amber" : "badge-blue"}">${it.kind === "addon" ? "Add-on" : "Product"}</span></td>
          <td>${ctx.esc(it.vendor_name || "—")}</td>
          <td>${ctx.esc(it.category || "—")}</td>
          ${mainTab === "stock" ? `<td class="prod-list-qty-cell">${it.kind === "product" ? `<strong class="prod-list-qty-big">${it.qty ?? 0}</strong>` : "—"}</td>
          <td>${st ? `<span class="badge ${st.cls === "is-ok" ? "badge-green" : st.cls === "is-low" ? "badge-amber" : st.cls === "is-neg" ? "badge-red" : "badge-gray"}">${st.label}</span>` : "—"}</td>` : ""}
          <td class="prod-list-price">${mainTab === "stock" && it.kind === "product" ? (it.selling_price ? fmtPrice(it.selling_price) : '<span class="prod-price-missing">—</span>') : fmtPrice(it.price)}</td>
        </tr>`;
        }).join("")}
      </tbody></table></div>`;
    }
    window._productsItems = items;
  }

  function openItem(kind, id) {
    const it = (window._productsItems || []).find(x => x.kind === kind && x.id === id);
    if (it && it.open) it.open();
    else if (kind === "product") {
      if (mainTab === "stock") Stock.openDetail(id);
      else Catalog.openDetail(id);
    } else AddonProducts.openDetail(id);
  }


  let altsBoardRows = [];
  let altsBoardSearch = "";
  let altsPickerForId = null;
  let altsPickerQuery = "";
  let altsPickerStock = [];
  let altsPickerTimer = null;

  async function openAlternativesManager() {
    ctx.showLoading?.();
    try {
      altsBoardRows = await ctx.api("/catalog/alternatives-board", {}, 0);
      altsBoardSearch = "";
      altsPickerForId = null;
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
    return altsBoardRows.filter(p => {
      const hay = [
        p.our_product_id, p.vendor_name, p.vendor_city,
        ...(p.alternatives || []).map(a => a.our_product_id),
      ].join(" ").toLowerCase();
      return hay.includes(q);
    });
  }

  function renderAlternativesBoard() {
    const body = document.getElementById("alts-board-body");
    if (!body) return;
    const rows = filteredAltsBoard();
    const canWrite = !!ctx.canWrite?.("catalog");

    body.innerHTML = `
      <div class="alts-toolbar">
        <input class="input search-big" id="alts-board-search" placeholder="Search product ID, vendor…"
          value="${ctx.esc(altsBoardSearch)}" oninput="Products.onAltsBoardSearch(this.value)" autocomplete="off" />
        <span class="alts-toolbar-count">${rows.length} product${rows.length === 1 ? "" : "s"}</span>
      </div>
      <div class="alts-col-head">
        <div>Main product</div>
        <div>Alternative 1</div>
        <div>Alternative 2</div>
        <div>Alternative 3</div>
      </div>
      <div class="alts-grid-wrap">
        ${rows.length ? rows.map(p => renderAltBoardRow(p, canWrite)).join("") : `<div class="empty-state"><p>No products match.</p></div>`}
      </div>
      ${altsPickerForId ? renderAltPicker(canWrite) : ""}`;

    if (altsPickerForId) {
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
    const hits = (altsPickerStock || []).filter(s => {
      if (linked.has(s.our_product_id)) return false;
      if (!q) return true;
      return String(s.our_product_id || "").toLowerCase().includes(q)
        || String(s.vendor_name || "").toLowerCase().includes(q);
    }).slice(0, 40);

    return `<div class="alts-picker-overlay" onclick="if(event.target===this)Products.closeAltPicker()">
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
    onFilterChange, clearFilters, setStockChip, load, openItem,
    openAlternativesManager, closeAlternativesManager, onAltsBoardSearch,
    openAltPicker, closeAltPicker, onAltPickerSearch, addAlternative, removeAlternative,
    enlargeImage, closeLightbox,
    getTab: () => mainTab,
  };
})();
