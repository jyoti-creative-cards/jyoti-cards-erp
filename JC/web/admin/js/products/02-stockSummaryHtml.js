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

  function buildItems() {
    const items = [];
    if (addonMode) {
      if (ctx.canRead?.("addons")) {
        addons.forEach(a => items.push({
          kind: "addon",
          id: a.id,
          our_product_id: a.our_product_id,
          vendor_name: a.vendor_name,
          qty: a.quantity_on_hand,
          stock_status: a.stock_status,
          image_urls: a.image_urls,
          open: () => AddonProducts.openDetail(a.id),
        }));
      }
    } else if (mainTab === "stock") {
      if (typeFilter !== "addons") {
        stockProducts.forEach(p => items.push({
          kind: "product",
          id: p.catalog_product_id,
          our_product_id: p.our_product_id,
          vendor_product_id: p.vendor_product_id,
          vendor_name: p.vendor_name,
          vendor_city: p.vendor_city,
          category: p.category,
          second_category: p.second_category,
          series: p.series,
          year_group: p.year_group,
          marking: p.marking,
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
          second_category: p.second_category,
          series: p.series,
          year_group: p.year_group,
          marking: p.marking,
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
    }
    items.sort((a, b) => {
      const idCmp = String(a.our_product_id || "").localeCompare(String(b.our_product_id || ""), undefined, { sensitivity: "base" });
      if (idCmp) return idCmp;
      return String(a.year_group || "").localeCompare(String(b.year_group || ""));
    });
    return items;
  }

  function applyFilters(items, { ignoreStockStatus = false } = {}) {
    if (addonMode) {
      return items.filter(it => !filters.stock_status || it.stock_status === filters.stock_status);
    }
    const catalogServer = mainTab === "catalog";
    return items.filter(it => {
      // Catalog products already filtered on server
      if (catalogServer && it.kind === "product") return true;
      if (filters.vendor_id && String(it.vendor_id) !== String(filters.vendor_id)) return false;
      if (filters.category && (it.category || "") !== filters.category && (it.second_category || "") !== filters.category) return false;
      if (filters.year_group && (it.year_group || "") !== filters.year_group) return false;
      const sellOrBuy = it.kind === "product"
        ? Number(it.selling_price != null && it.selling_price !== "" ? it.selling_price : it.buying_price)
        : Number(it.price);
      if (filters.price_min && !Number.isNaN(sellOrBuy) && sellOrBuy < Number(filters.price_min)) return false;
      if (filters.price_max && !Number.isNaN(sellOrBuy) && sellOrBuy > Number(filters.price_max)) return false;
      if (!ignoreStockStatus && filters.stock_status && (mainTab === "stock" || it.kind === "addon") && it.stock_status !== filters.stock_status) return false;
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
    const canSetSell = !!ctx.isAdmin?.();
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
        const showsAddonStock = it.kind === "addon";
        const st = (isStockProduct || showsAddonStock) ? stockStatusMeta(it.stock_status) : null;
        return `<button type="button" class="prod-card${st ? ` prod-card-stock ${st.cls}` : ""}" onclick="Products.openItem('${it.kind}', ${it.id})">
          <div class="prod-card-media">
            ${cardImage(it)}
            ${st
              ? `<span class="prod-card-status ${st.cls}">${st.label}</span>`
              : `<span class="prod-card-kind ${it.kind === "addon" ? "is-addon" : "is-product"}">${it.kind === "addon" ? "Add-on" : "Product"}</span>`}
          </div>
          <div class="prod-card-body">
            ${itemIdHtml(it)}
            ${it.kind === "addon" ? "" : `<div class="prod-card-vendor">${ctx.esc(vendorLine(it))}</div>`}
            ${it.kind === "addon" ? "" : (it.category
              ? `<div class="prod-card-cat"><span class="prod-cat-badge">${ctx.esc(it.category)}</span>${it.second_category ? `<span class="prod-cat-badge">${ctx.esc(it.second_category)}</span>` : ""}</div>`
              : `<div class="prod-card-cat"><span class="prod-cat-badge is-empty">No category</span></div>`)}
            ${it.marking ? `<div class="prod-card-cat"><span class="badge badge-blue" style="font-size:10px;">${ctx.esc(it.marking)}</span></div>` : ""}
            ${(isStockProduct || showsAddonStock) ? `<div class="prod-card-qty-block">
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
            ${it.marking ? `<div class="prod-list-sub"><span class="badge badge-blue" style="font-size:10px;">${ctx.esc(it.marking)}</span></div>` : ""}
          </td>
          <td><span class="badge ${it.kind === "addon" ? "badge-amber" : "badge-blue"}">${it.kind === "addon" ? "Add-on" : "Product"}</span></td>
          <td>${ctx.esc(vendorLine(it))}</td>
          <td>${ctx.esc(it.category || "—")}${it.second_category ? ` · ${ctx.esc(it.second_category)}` : ""}</td>
          ${mainTab === "stock" ? `<td class="prod-list-qty-cell">${(it.kind === "product" || it.kind === "addon") ? `<strong class="prod-list-qty-big">${it.qty ?? 0}</strong>` : "—"}</td>
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

