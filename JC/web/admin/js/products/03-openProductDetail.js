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
            ${ctx.isAdmin?.() ? `<button class="btn btn-secondary btn-sm" onclick="Stock.setSellingPrice(${id}, '${ctx.esc(String(sell))}')">Set</button>` : ""}</div>`
        : `<div class="stock-price-row"><span class="prod-price-missing">Not set</span>
            ${ctx.isAdmin?.() ? `<button class="btn btn-primary btn-sm" onclick="Stock.setSellingPrice(${id}, '')">Set sell price</button>` : ""}</div>`;

      const ledgerRows = Stock.ledgerTableHtml ? Stock.ledgerTableHtml(stock?.ledger) : "";
      const reservedByPartyHtml = Stock.reservedByPartyTable ? Stock.reservedByPartyTable(stock?.reserved_by_party) : "";

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
              ${ctx.canWrite?.("stock")
                ? `<button class="btn btn-threshold" onclick="Stock.editThreshold(${id}, ${stock.low_stock_threshold ?? 5})">Set threshold</button>`
                : ""}
            </div>
          </div>
        </div>
        <div class="review-grid" style="margin:16px 0 20px;">
          ${ctx.reviewRow("On hand", stock.quantity_on_hand)}
          ${ctx.reviewRow("Status", (stock.stock_status || "").replace(/_/g, " "))}
          ${ctx.reviewRow("Pending order (vendor inbound)", stock.quantity_pending)}
        </div>
        ${reservedByPartyHtml}
        <div class="detail-section">
          <h4>Stock Ledger</h4>
          <p style="font-size:12px;color:var(--muted);margin:0 0 8px;">Click a row to open that bill.</p>
          ${ledgerRows}
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
          ${ctx.reviewRow("Year Group", cat.year_group)}
          ${ctx.reviewRow("Category", cat.category)}
          ${ctx.reviewRow("Marking", cat.marking)}
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

      const addonSource = cat?.addon_links?.length ? cat.addon_links : (stock?.addon_links || []);
      const addonManageBtn = (ctx.canWrite?.("catalog") || ctx.isAdmin?.())
        ? `<button type="button" class="btn btn-secondary btn-sm" style="margin-top:10px;" onclick="Catalog.openEdit(${id}, 'addons')">Manage add-ons</button>`
        : "";
      const addonPane = addonSource.length
        ? `<div class="alt-chip-row">${addonSource.map(l => {
            const img = (l.image_urls && l.image_urls[0]) || "";
            const sku = l.addon_our_product_id || l.our_product_id;
            const name = l.addon_name || l.name || "Add-on";
            return `<div class="alt-chip is-static">
              ${img ? `<img src="${ctx.esc(img)}" alt="" onclick="Products.enlargeImage(decodeURIComponent('${encodeURIComponent(img)}'))" style="cursor:zoom-in;" />` : `<span class="alt-chip-empty"></span>`}
              <span class="alt-chip-body">
                <strong>${ctx.esc(sku)}</strong>
                <span>${ctx.esc(name)} · qty ${l.quantity}</span>
              </span>
            </div>`;
          }).join("")}</div>${addonManageBtn}`
        : `<p style="color:var(--muted);font-size:14px;margin:0;">No add-on links</p>${addonManageBtn}`;

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
            ${(cat?.marking || stock?.marking) ? `<span class="badge badge-amber">${ctx.esc(cat?.marking || stock?.marking)}</span>` : ""}
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
        `${(ctx.canWrite?.("catalog") || ctx.isAdmin?.())
          ? `<button class="btn btn-danger btn-sm" onclick="Catalog.deleteProduct(${id})">Delete</button>
             <button type="button" class="btn btn-secondary btn-sm" onclick="event.stopPropagation();Catalog.openEdit(${id}, '${sec}')">Edit</button>`
          : ""}
         <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
        "lg"
      );

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
      // Linking is bidirectional and the backend caps each side at 3 — a candidate
      // already at its own cap would 400 on select, so don't offer it at all.
      if (Number(s.alt_count || 0) >= 3) continue;
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

