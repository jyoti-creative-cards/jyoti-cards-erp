  async function openOfflineWizard(presetCustomerId) {
    const cid = presetCustomerId != null ? presetCustomerId : detailCustomerId;
    offlineEditPlacementId = null;
    offlineStep = 1;
    offlineCustomerId = cid || null;
    offlineCustomerName = "";
    offlineCustomerSearch = "";
    offlineSelectedDetail = null;
    offlineLines = [];
    offlineSearchQuery = "";
    offlineSearchResults = [];
    offlinePicked = null;
    offlineNotes = "";
    offlinePlacedOn = localToday();
    offlinePreview = null;
    offlineBusy = false;
    offlineCustomers = [];
    document.getElementById("co-offline-wizard")?.classList.remove("hidden");
    renderOfflineWizard();
    if (!cid) return;
    try {
      const c = await ctx.api(`/customers/${cid}`, {}, 0);
      offlineCustomers = [c];
      offlinePicked = c;
      offlineCustomerId = cid;
      offlineCustomerName = c.business_name || "";
      offlineSelectedDetail = c;
      renderOfflineWizard();
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  function matchOfflineCustomer(c, tokens) {
    if (!tokens.length) return true;
    return OrdersUI.partySearchRank(c, tokens) != null;
  }

  function onOfflineCustomerSearch(val) {
    offlineCustomerSearch = val || "";
    renderOfflineWizard();
    setTimeout(() => {
      const el = document.getElementById("co-offline-cust-search");
      if (!el) return;
      el.focus();
      try { el.setSelectionRange(el.value.length, el.value.length); } catch (_) {}
    }, 0);
    clearTimeout(offlineCustomerTimer);
    const q = (offlineCustomerSearch || "").trim();
    if (q.length < 1) {
      offlineCustomers = offlinePicked ? [offlinePicked] : [];
      renderOfflineWizard();
      return;
    }
    offlineCustomerTimer = setTimeout(async () => {
      try {
        const rows = await ctx.api(`/customers/quick-search?q=${encodeURIComponent(q)}`, {}, 0) || [];
        if ((offlineCustomerSearch || "").trim() !== q) return;
        offlineCustomers = rows;
        renderOfflineWizard();
      } catch (e) { ctx.toast(e.message, "error"); }
    }, 200);
  }

  async function pickOfflineCustomer(id) {
    if (!id) {
      offlineCustomerId = null;
      offlineCustomerName = "";
      offlineSelectedDetail = null;
      offlinePicked = null;
      renderOfflineWizard();
      return;
    }
    const c = (offlineCustomers || []).find(x => x.id === id);
    offlineCustomerId = id;
    offlineCustomerName = c?.business_name || "";
    offlinePicked = c || null;
    offlineSelectedDetail = c || null;
    renderOfflineWizard();
    // fetch full detail (has outstanding_balance + available_credit)
    try {
      offlineSelectedDetail = await ctx.api(`/customers/${id}`, {}, 0);
      offlinePicked = { ...(offlinePicked || {}), ...offlineSelectedDetail, id };
      renderOfflineWizard();
    } catch (_) {}
  }

  function closeOfflineWizard() {
    document.getElementById("co-offline-wizard")?.classList.add("hidden");
    offlineEditPlacementId = null;
  }

  function buildOfflineBody() {
    return {
      lines: offlineLines.filter(l => Number(l.quantity) > 0).map(l => ({
        catalog_product_id: l.catalog_product_id,
        quantity: Number(l.quantity),
        skip_addon_ids: l.skip_addon_ids || [],
      })),
      narration: (offlineNotes || "").trim() || null,
      placed_on: offlinePlacedOn || localToday(),
    };
  }

  function filterOfflineProducts() {
    const q = offlineSearchQuery.trim().toLowerCase();
    const all = offlineSearchResults || [];
    if (!q) return [];
    const scored = [];
    for (const p of all) {
      const id = String(p.our_product_id || "").toLowerCase();
      const cat = String(p.category || "").toLowerCase();
      const vendor = String(p.vendor_name || "").toLowerCase();
      let score = 0;
      if (id === q) score = 100;
      else if (id.startsWith(q)) score = 80;
      else if (id.includes(q)) score = 40;
      else if (cat.startsWith(q)) score = 30;
      else if (cat.includes(q) || vendor.includes(q)) score = 10;
      else continue;
      scored.push({ p, score, id });
    }
    scored.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
    return scored.map(x => x.p).slice(0, 40);
  }

  function offlineCartQty() {
    return offlineLines.reduce((s, l) => s + (Number(l.quantity) || 0), 0);
  }

  function offlineCartTotal() {
    return offlineLines.reduce((s, l) => {
      let n = (Number(l.selling_price) || 0) * (Number(l.quantity) || 0);
      const skipped = new Set(l.skip_addon_ids || []);
      for (const a of l.priced_addons || []) {
        if (skipped.has(a.addon_product_id)) continue;
        n += (Number(a.selling_price) || 0) * (Number(a.quantity) || 1) * (Number(l.quantity) || 0);
      }
      return s + n;
    }, 0);
  }

  function pricedAddonHtml(p, line) {
    const addons = (line && line.priced_addons) || p.priced_addons || [];
    if (!addons.length || !line) return "";
    const skipped = new Set(line.skip_addon_ids || []);
    return addons.map(a => {
      const id = a.addon_product_id;
      const price = Number(a.selling_price) || 0;
      if (skipped.has(id)) {
        return `<div class="co-addon-row" onclick="event.stopPropagation()">Name Plate removed · <button type="button" class="btn btn-ghost btn-sm" onclick="event.stopPropagation();CustomerOrders.skipOfflineAddon(${p.catalog_product_id}, ${id})">Add back</button></div>`;
      }
      return `<div class="co-addon-row" onclick="event.stopPropagation()">+ ${ctx.esc(a.name || a.our_product_id || "Name Plate")} · ₹${price} each <button type="button" class="btn btn-ghost btn-sm" onclick="event.stopPropagation();CustomerOrders.skipOfflineAddon(${p.catalog_product_id}, ${id})">Remove</button></div>`;
    }).join("");
  }

  function renderOfflineWizard() {
    const stepsEl = document.getElementById("co-offline-steps");
    const bodyEl = document.getElementById("co-offline-body");
    const footerEl = document.getElementById("co-offline-footer");
    if (!stepsEl || !bodyEl || !footerEl) return;

    const editing = !!offlineEditPlacementId;
    const labels = editing ? ["Products", "Review"] : ["Customer", "Products", "Review"];
    const stepNum = editing ? offlineStep - 1 : offlineStep;
    stepsEl.innerHTML = labels.map((lbl, i) => {
      const n = i + 1;
      const cls = n === stepNum ? "step active" : n < stepNum ? "step done" : "step";
      return `<div class="${cls}"><span class="step-num">${n < stepNum ? "✓" : n}</span><span class="step-label">${lbl}</span></div>`;
    }).join("");

    if (offlineStep === 1 && !editing) {
      const tokens = OrdersUI.partySearchTokens(offlineCustomerSearch);
      const customers = OrdersUI.filterAndRankParties(
        (offlineCustomers || []).filter(c => c.is_active !== false),
        offlineCustomerSearch,
      ).slice(0, tokens.length ? 40 : 60);
      const selected = offlineCustomerId
        ? (offlinePicked || (offlineCustomers || []).find(c => c.id === offlineCustomerId))
        : null;
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>Select customer</h4>
          <p>Search any part of name, city, or phone — e.g. <em>natraj</em> or <em>anjad</em>.</p>
        </div>
        <div class="vo-wiz-search-wrap">
          <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
          <input id="co-offline-cust-search" class="input vo-wiz-search" type="search" placeholder="Search customer, city, phone, alias…" value="${ctx.esc(offlineCustomerSearch)}" oninput="CustomerOrders.onOfflineCustomerSearch(this.value)" autocomplete="off" />
          ${offlineCustomerSearch ? `<button type="button" class="vo-wiz-search-clear" onclick="CustomerOrders.onOfflineCustomerSearch('')">×</button>` : ""}
        </div>
        ${selected ? `<div class="vo-wiz-selected-banner">
          <div>
            <span class="vo-wiz-selected-label">Selected</span>
            ${selected.party_number ? `<span style="font-size:11px;color:var(--muted);font-weight:600;margin-right:4px;">#${selected.party_number}</span>` : ""}<strong>${ctx.esc(selected.business_name || offlineCustomerName)}</strong>${selected.marker_1 ? ` <span class="badge badge-blue" style="font-size:10px;padding:2px 4px;vertical-align:middle;">${ctx.esc(selected.marker_1)}</span>` : ""}${selected.marker_2 ? ` <span class="badge badge-amber" style="font-size:10px;padding:2px 4px;vertical-align:middle;">${ctx.esc(selected.marker_2)}</span>` : ""}${(selected.payment_type === "CASH" && !(selected.marker_1 || "").toUpperCase().includes("CASH")) ? ` <span class="badge badge-amber" style="font-size:10px;padding:2px 4px;vertical-align:middle;">CASH</span>` : ""}
            ${selected.city_name ? `<span class="vo-muted"> · ${ctx.esc(selected.city_name)}</span>` : ""}
          </div>
          <button type="button" class="btn btn-ghost btn-sm" onclick="CustomerOrders.pickOfflineCustomer(null)">Change</button>
        </div>
        ${cashWarningHtml(selected)}
        ${offlineSelectedDetail ? (() => {
          const d = offlineSelectedDetail;
          const outstanding = d.outstanding_balance;
          const avail = d.available_credit;
          const limit = d.credit_limit;
          if (outstanding == null && avail == null) return "";
          const outN = Number(outstanding || 0);
          const availN = Number(avail || 0);
          const overLimit = availN < 0;
          const bg = overLimit ? "#fef2f2" : "#f0fdf4";
          const border = overLimit ? "#fecaca" : "#bbf7d0";
          return `<div style="margin:8px 0;padding:10px 14px;border-radius:8px;background:${bg};border:1px solid ${border};display:flex;gap:16px;flex-wrap:wrap;font-size:13px;">
            <span><strong>Outstanding:</strong> ${outN < 0 ? "<span style='color:#16a34a'>Credit ₹" + Math.abs(outN).toLocaleString("en-IN", {maximumFractionDigits:2}) + "</span>" : outN > 0 ? "<span style='color:#dc2626'>₹" + outN.toLocaleString("en-IN", {maximumFractionDigits:2}) + "</span>" : "₹0"}</span>
            <span><strong>Credit Limit:</strong> ₹${Number(limit || 0).toLocaleString("en-IN", {maximumFractionDigits:2})}</span>
            <span><strong>Available:</strong> ${availN < 0 ? "<span style='color:#dc2626'>-₹" + Math.abs(availN).toLocaleString("en-IN", {maximumFractionDigits:2}) + "</span>" : "<span style='color:#16a34a'>₹" + availN.toLocaleString("en-IN", {maximumFractionDigits:2}) + "</span>"}</span>
          </div>`;
        })() : (offlineCustomerId ? `<p style="font-size:12px;color:var(--muted);margin:4px 0;">Loading credit info…</p>` : "")}` : ""}
        <div class="vo-wiz-vendor-list">
          ${customers.length ? customers.map(c => {
            const selectedCls = offlineCustomerId === c.id ? " selected" : "";
            const _cm1u = (c.marker_1 || "").toUpperCase();
            return `<button type="button" class="vo-wiz-vendor-card${selectedCls}" onclick="CustomerOrders.pickOfflineCustomer(${c.id})">
              <span class="vo-wiz-vendor-letter">${ctx.esc((c.business_name || "?").slice(0, 1).toUpperCase())}</span>
              <span class="vo-wiz-vendor-meta">
                <strong>${c.party_number ? `<span style="font-size:10px;color:var(--muted);font-weight:600;margin-right:3px;">#${c.party_number}</span>` : ""}${ctx.esc(c.business_name || "Customer")}${c.marker_1 ? ` <span class="badge badge-blue" style="font-size:9px;padding:1px 4px;vertical-align:middle;">${ctx.esc(c.marker_1)}</span>` : ""}${c.marker_2 ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;vertical-align:middle;">${ctx.esc(c.marker_2)}</span>` : ""}${(c.payment_type === "CASH" && !_cm1u.includes("CASH")) ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;vertical-align:middle;">CASH</span>` : ""}</strong>
                <span>${c.city_name ? ctx.esc(c.city_name) : "No city"}${c.phone ? ` · ${ctx.esc(c.phone)}` : ""}</span>
              </span>
              <span class="vo-wiz-vendor-check">${offlineCustomerId === c.id ? "✓" : ""}</span>
            </button>`;
          }).join("") : HubUI.emptyState({
            title: tokens.length ? "No matches" : "Type to search",
            sub: tokens.length ? `No customer matches “${ctx.esc(offlineCustomerSearch)}”.` : "Name, city, or phone.",
          })}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="CustomerOrders.closeOfflineWizard()">Cancel</button>
        <button class="btn btn-primary" ${offlineCustomerId ? "" : "disabled"} onclick="CustomerOrders.offlineNext()">Next →</button>`;
      setTimeout(() => document.getElementById("co-offline-cust-search")?.focus(), 30);
      return;
    }

    if (offlineStep === 2) {
      const shown = filterOfflineProducts();
      const list = shown;
      const cartHtml = offlineLines.length ? `
        <div class="vo-wiz-cart">
          <div class="vo-wiz-cart-head">
            <strong>In this order</strong>
            <span>${offlineLines.length} product${offlineLines.length === 1 ? "" : "s"} · ${offlineCartQty()} qty</span>
          </div>
          <div class="vo-wiz-cart-chips">
            ${offlineLines.map(l => `<span class="vo-wiz-cart-chip">
              <span>${ctx.esc(l.our_product_id)} × ${l.quantity}</span>
              <button type="button" title="Remove" onclick="CustomerOrders.toggleOfflineProduct(${l.catalog_product_id}, false)">×</button>
            </span>`).join("")}
          </div>
        </div>` : "";

      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head vo-wiz-step-head-row">
          <div>
            <h4 style="margin:0;">${editing ? `Edit placement #${offlineEditPlacementId}` : `Products for ${ctx.esc(offlineCustomerName)}`}</h4>
            <p style="margin:4px 0 0;font-size:13px;color:var(--muted);">${editing ? "Add, change qty, or remove products. Stock updates on save." : "Search product ID — tick rows, set qty. Enter adds exact / best match."}</p>
          </div>
          <div class="vo-wiz-count-pill">${offlineLines.length} selected</div>
        </div>
        ${cartHtml}
        <div class="vo-wiz-search-wrap">
          <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
          <input id="co-offline-search" class="input vo-wiz-search" type="search" placeholder="Search product ID, category…" value="${ctx.esc(offlineSearchQuery)}" oninput="CustomerOrders.onOfflineSearchInput(this.value)" onkeydown="CustomerOrders.onOfflineSearchKey(event)" onfocus="this.select()" autocomplete="off" />
          ${offlineSearchQuery ? `<button type="button" class="vo-wiz-search-clear" onclick="CustomerOrders.onOfflineSearchInput('')">×</button>` : ""}
        </div>
        <div class="vo-wiz-product-meta">
          <span>Showing ${list.length}${offlineSearchQuery ? " match" : " (type to search)"}${offlineSearchResults.length ? ` · ${offlineSearchResults.length} loaded` : ""}</span>
        </div>
        <div class="vo-wiz-products" id="co-offline-product-list">
          ${!offlineSearchQuery.trim()
            ? HubUI.emptyState({ title: "Type to search", sub: "Product number, category, or vendor." })
            : offlineSearchPending && !list.length
            ? HubUI.emptyState({ title: "Searching…", sub: "Looking up products." })
            : list.length ? list.map(p => {
              const line = offlineLines.find(l => l.catalog_product_id === p.catalog_product_id);
              const qty = line ? line.quantity : 1;
              const checked = !!line;
              const img = (p.image_urls && p.image_urls[0]) || "";
              return `<div class="vo-wiz-product ${checked ? "selected" : ""}" onclick="CustomerOrders.pickOfflineProduct(${p.catalog_product_id})">
                <div class="vo-wiz-product-main">
                  <input type="checkbox" ${checked ? "checked" : ""} onclick="event.stopPropagation();CustomerOrders.toggleOfflineProduct(${p.catalog_product_id}, this.checked)" />
                  ${thumb(img)}
                  <div class="vo-wiz-product-info">
                    <strong>${ctx.esc(p.our_product_id)}${p.year_group ? ` <span class="prod-year-pill">${ctx.esc(p.year_group)}</span>` : ""}</strong>
                    <span class="vo-wiz-product-sub">${p.category ? ctx.esc(p.category) : "Product"}${p.year_group ? ` · ${ctx.esc(p.year_group)}` : ""}${p.vendor_name ? ` · ${ctx.esc(p.vendor_name)}` : ""}</span>
                    <span class="vo-wiz-product-price">${fmtPrice(p.selling_price)} · Stock ${p.quantity_on_hand ?? 0}</span>
                    ${pricedAddonHtml(p, line)}
                  </div>
                </div>
                <div class="vo-wiz-qty" onclick="event.stopPropagation()">
                  <label>Qty</label>
                  <div class="vo-wiz-qty-controls">
                    <button type="button" class="vo-wiz-qty-btn" ${checked ? "" : "disabled"} onclick="CustomerOrders.bumpOfflineQty(${p.catalog_product_id}, -1)">−</button>
                    <input type="number" min="1" class="input vo-wiz-qty-input" data-qty-for="${p.catalog_product_id}" value="${qty}" ${checked ? "" : "disabled"} onchange="CustomerOrders.setOfflineQty(${p.catalog_product_id}, this.value)" onkeydown="CustomerOrders.onOfflineQtyKey(event)" onclick="event.stopPropagation()" />
                    <button type="button" class="vo-wiz-qty-btn" ${checked ? "" : "disabled"} onclick="CustomerOrders.bumpOfflineQty(${p.catalog_product_id}, 1)">+</button>
                  </div>
                </div>
              </div>`;
            }).join("") : HubUI.emptyState({
              title: "No matches",
              sub: `No products match “${offlineSearchQuery}”.`,
              ctaHtml: `<button type="button" class="btn btn-secondary" onclick="CustomerOrders.onOfflineSearchInput('')">Clear search</button>`,
            })}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="${editing ? "CustomerOrders.closeOfflineWizard()" : "CustomerOrders.offlineBack()"}">${editing ? "Cancel" : "← Back"}</button>
        <div class="vo-wiz-footer-mid">${offlineLines.length ? `${offlineLines.length} item(s) · est. ${fmtPrice(offlineCartTotal())}` : "Select at least one product"}</div>
        <button class="btn btn-primary" ${offlineLines.length ? "" : "disabled"} onclick="CustomerOrders.offlineNext()">Review →</button>`;
      setTimeout(() => focusPendingQty("co-offline-search"), 30);
      return;
    }

    const tot = offlinePreview || {};
    const lines = tot.lines || offlineLines.map(l => ({
      our_product_id: l.our_product_id,
      quantity: l.quantity,
      unit_price: l.selling_price,
      line_total: (Number(l.selling_price) || 0) * (Number(l.quantity) || 0),
      out_of_stock: Number(l.quantity_on_hand) < Number(l.quantity),
      on_hand: l.quantity_on_hand,
    }));
    const warnings = tot.stock_warnings || lines.filter(l => l.out_of_stock).map(l => ({
      message: `${l.our_product_id}: need ${l.quantity}, have ${l.on_hand ?? 0} — will go negative`,
    }));
    const warnHtml = warnings.length
      ? `<div style="margin:0 0 14px;padding:12px 14px;background:#fffbeb;border:1px solid #fcd34d;border-radius:10px;">
          <strong style="color:#b45309;">Out of stock — order still allowed (offline)</strong>
          <ul style="margin:8px 0 0;padding-left:18px;font-size:13px;color:#92400e;">
            ${warnings.map(w => `<li>${ctx.esc(w.message || w.our_product_id)}</li>`).join("")}
          </ul>
          <p style="margin:8px 0 0;font-size:12px;color:#92400e;">Stock on hand will go negative after place. Portal customers still cannot oversell.</p>
        </div>`
      : "";
    bodyEl.innerHTML = `
      ${warnHtml}
      <div class="review-grid" style="margin-bottom:16px;">
        ${ctx.reviewRow("Customer", offlineCustomerName)}
        ${editing ? ctx.reviewRow("Placement", `#${offlineEditPlacementId}`) : ""}
        ${ctx.reviewRow("Items", String(lines.length))}
        ${ctx.reviewRow("Est. total", fmtPrice(tot.subtotal || offlineCartTotal()))}
      </div>
      ${editing ? "" : `
        <label class="label">Order date</label>
        <input type="date" class="input" style="width:100%;max-width:220px;margin-bottom:4px;" value="${ctx.esc(offlinePlacedOn || localToday())}" onchange="CustomerOrders.setOfflinePlacedOn(this.value)" />
        <p style="font-size:12px;color:var(--muted);margin:0 0 12px;">Day the call / order actually happened (backdate OK).</p>
      `}
      <label class="label">Notes (optional — shown on order)</label>
      <textarea class="input" id="co-offline-notes" rows="2" style="width:100%;margin-bottom:12px;" oninput="CustomerOrders.setOfflineNotes(this.value)">${ctx.esc(offlineNotes || "")}</textarea>
      <div class="card table-wrap">
        <table class="data"><thead><tr><th>Product</th><th>Stock</th><th>Qty</th><th>Rate</th><th>Line</th></tr></thead>
        <tbody>${lines.map(ln => `<tr>
          <td><strong>${ctx.esc(ln.our_product_id)}</strong>${ln.out_of_stock ? ` <span style="color:#b45309;font-size:11px;font-weight:700;">out of stock</span>` : ""}</td>
          <td>${ln.on_hand != null ? ln.on_hand : "—"}</td>
          <td>${ln.quantity}</td>
          <td>${fmtPrice(ln.unit_price || ln.rate_inclusive)}</td>
          <td>${fmtPrice(ln.line_total)}</td>
        </tr>`).join("")}</tbody></table>
      </div>
      <p style="margin:12px 0 0;font-size:13px;color:var(--muted);">${editing
        ? "Saves changes to this incoming order. Stock reserve adjusts automatically."
        : "Goes to <strong>To bill</strong>. Next: Bill when packed."}</p>`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="CustomerOrders.offlineBack()">← Back</button>
      <button class="btn btn-primary" ${offlineBusy ? "disabled" : ""} onclick="CustomerOrders.submitOffline()">${offlineBusy ? "Saving…" : (editing ? "Save changes" : (warnings.length ? "Place anyway" : "Place for customer"))}</button>`;
  }

  function setOfflineNotes(v) { offlineNotes = v || ""; }
  function setOfflinePlacedOn(v) { offlinePlacedOn = v || localToday(); }

  function onOfflineSearchInput(val) {
    const prev = document.getElementById("co-offline-search");
    const start = prev?.selectionStart;
    offlineSearchQuery = val || "";
    offlineSearchPending = !!(offlineSearchQuery || "").trim();
    renderOfflineWizard();
    const inp = document.getElementById("co-offline-search");
    if (inp) {
      inp.focus();
      if (typeof start === "number") {
        try { inp.setSelectionRange(start, start); } catch (_) {}
      }
    }
    clearTimeout(offlineProductTimer);
    const q = (offlineSearchQuery || "").trim();
    if (!q) {
      offlineSearchResults = [];
      offlineSearchPending = false;
      return;
    }
    offlineSearchPending = true;
    offlineProductTimer = setTimeout(() => loadOfflineProductSearch(q), 200);
  }

  async function loadOfflineProductSearch(q) {
    try {
      const rows = await ctx.api(`/stock/products?lite=1&limit=40&search=${encodeURIComponent(q)}`, {}, 0) || [];
      if ((offlineSearchQuery || "").trim() !== q) return;
      offlineSearchResults = rows;
    } catch (e) {
      offlineSearchResults = [];
      ctx.toast(e.message, "error");
    }
    offlineSearchPending = false;
    renderOfflineWizard();
  }

  function focusPendingQty(searchId) {
    if (focusQtyProductId != null) {
      const id = focusQtyProductId;
      focusQtyProductId = null;
      const el = document.querySelector(`[data-qty-for="${id}"]`);
      if (el) { el.disabled = false; el.focus(); el.select(); return; }
    }
    const inp = document.getElementById(searchId);
    if (!inp || document.activeElement === inp) return;
    inp.focus();
    try { const n = (offlineSearchQuery || "").length; inp.setSelectionRange(n, n); } catch (_) {}
  }

  async function onOfflineSearchKey(e) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const q = offlineSearchQuery.trim().toLowerCase();
    if (!q) return;
    if (!offlineSearchResults.length) {
      await loadOfflineProductSearch(offlineSearchQuery.trim());
    }
    const exact = offlineSearchResults.find(p => String(p.our_product_id || "").toLowerCase() === q);
    const best = exact || filterOfflineProducts()[0];
    if (!best) return ctx.toast("No product match", "error");
    pickOfflineProduct(best.catalog_product_id);
  }

  function onOfflineQtyKey(e) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    offlineSearchQuery = "";
    focusQtyProductId = null;
    renderOfflineWizard();
  }

  function pickOfflineProduct(catalogProductId) {
    if (offlineLines.some(l => l.catalog_product_id === catalogProductId)) {
      const el = document.querySelector(`[data-qty-for="${catalogProductId}"]`);
      if (el) { el.disabled = false; el.focus(); el.select(); }
      return;
    }
    toggleOfflineProduct(catalogProductId, true);
  }

  async function ensureOfflineProductsLoaded() {
    return;
  }

  function toggleOfflineProduct(catalogProductId, checked) {
    const p = offlineSearchResults.find(x => x.catalog_product_id === catalogProductId);
    if (!p) return;
    if (checked) {
      if (!offlineLines.find(l => l.catalog_product_id === catalogProductId)) {
        offlineLines.push({
          catalog_product_id: p.catalog_product_id,
          our_product_id: p.our_product_id,
          quantity: 1,
          min_qty: 0,
          selling_price: p.selling_price,
          quantity_on_hand: p.quantity_on_hand,
          priced_addons: p.priced_addons || [],
          skip_addon_ids: [],
        });
      }
    } else {
      const existing = offlineLines.find(l => l.catalog_product_id === catalogProductId);
      if (existing && Number(existing.min_qty) > 0) {
        existing.quantity = Number(existing.min_qty);
        return ctx.toast(`Keep billed qty (${existing.min_qty}) — cannot remove billed product`, "error");
      }
      offlineLines = offlineLines.filter(l => l.catalog_product_id !== catalogProductId);
    }
    if (checked) focusQtyProductId = catalogProductId;
    renderOfflineWizard();
  }

  function skipOfflineAddon(catalogProductId, addonId) {
    const line = offlineLines.find(l => l.catalog_product_id === catalogProductId);
    if (!line) return;
    const id = Number(addonId);
    const skipped = new Set(line.skip_addon_ids || []);
    if (skipped.has(id)) skipped.delete(id);
    else skipped.add(id);
    line.skip_addon_ids = [...skipped];
    renderOfflineWizard();
  }

  function removeOfflineLine(catalogProductId) {
    toggleOfflineProduct(catalogProductId, false);
  }

  function setOfflineQty(cid, raw) {
    const line = offlineLines.find(l => l.catalog_product_id === cid);
    const minQ = line ? (Number(line.min_qty) || 0) : 0;
    const qty = Math.max(minQ || 1, parseInt(String(raw || "1"), 10) || 1);
    if (line) line.quantity = qty;
    else {
      const p = offlineSearchResults.find(x => x.catalog_product_id === cid);
      if (p) offlineLines.push({
        catalog_product_id: p.catalog_product_id,
        our_product_id: p.our_product_id,
        quantity: qty,
        min_qty: 0,
        selling_price: p.selling_price,
        quantity_on_hand: p.quantity_on_hand,
        priced_addons: p.priced_addons || [],
        skip_addon_ids: [],
      });
    }
    const mid = document.querySelector("#co-offline-footer .vo-wiz-footer-mid");
    if (mid && offlineLines.length) mid.textContent = `${offlineLines.length} item(s) · est. ${fmtPrice(offlineCartTotal())}`;
  }

  function bumpOfflineQty(cid, delta) {
    const line = offlineLines.find(l => l.catalog_product_id === cid);
    if (!line) {
      if (delta > 0) toggleOfflineProduct(cid, true);
      return;
    }
    const minQ = Number(line.min_qty) || 0;
    line.quantity = Math.max(minQ || 1, (Number(line.quantity) || 1) + delta);
    renderOfflineWizard();
  }

  async function offlineNext() {
    if (offlineStep === 1) {
      if (!offlineCustomerId) return ctx.toast("Select a customer", "error");
      offlineStep = 2;
      renderOfflineWizard();
      return;
    }
    if (offlineStep === 2) {
      if (!offlineLines.length) return ctx.toast("Add at least one product", "error");
      ctx.showLoading?.();
      try {
        offlinePreview = await ctx.api(`/customer-orders/customer/${offlineCustomerId}/offline/preview`, {
          method: "POST",
          body: JSON.stringify(buildOfflineBody()),
        });
        offlineStep = 3;
        renderOfflineWizard();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    }
  }

  function offlineBack() {
    if (offlineEditPlacementId) {
      if (offlineStep > 2) { offlineStep -= 1; renderOfflineWizard(); }
      return;
    }
    if (offlineStep > 1) { offlineStep -= 1; renderOfflineWizard(); }
  }

  async function submitOffline() {
    if (offlineBusy || !offlineCustomerId) return;
    const notesEl = document.getElementById("co-offline-notes");
    if (notesEl) offlineNotes = notesEl.value || "";
    const body = buildOfflineBody();
    if (!body.lines || !body.lines.length) {
      return ctx.toast("Add at least one product before placing the order", "error");
    }
    offlineBusy = true;
    renderOfflineWizard();
    ctx.showLoading?.();
    try {
      if (offlineEditPlacementId) {
        const pid = offlineEditPlacementId;
        const cid = offlineCustomerId;
        await ctx.api(`/customer-orders/placements/${pid}`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/stock");
        closeOfflineWizard();
        ctx.toast("Order updated", "success");
        await openDetail(cid, "received");
        loadList();
        return;
      }
      const res = await ctx.api(`/customer-orders/customer/${offlineCustomerId}/offline`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/stock");
      closeOfflineWizard();
      const cid = offlineCustomerId;
      ctx.openDetail?.(`Order #${res.placement_id}`, `
        <div class="doc-success-banner">
          <strong>Placed for customer</strong>
          <span>Same as portal · stock reserved</span>
        </div>
        <p style="margin:12px 0;font-size:14px;color:var(--muted);">Order is in <strong>Confirmed</strong>. Bill it now, or view it first.</p>`,
        `<button class="btn btn-primary" style="flex:1;" onclick="CustomerOrders.billNow(${cid})">Bill now</button>
         <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail();CustomerOrders.openDetail(${cid}, 'open')">View order</button>`, "sm");
      ctx.toast("Order placed for customer", "success");
      hubMode = "needs_action";
      currentBucket = "open";
      syncHubChrome();
      loadList();
    } catch (e) { ctx.toast(e.message || "Could not place order", "error"); }
    finally {
      offlineBusy = false;
      ctx.hideLoading?.();
      // Re-draw so Save button unlocks after error (was stuck on “Saving…”)
      if (!document.getElementById("co-offline-wizard")?.classList.contains("hidden")) {
        renderOfflineWizard();
      }
    }
  }

