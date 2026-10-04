  function wizardCartTotal() {
    let anyUnknown = false;
    let sum = 0;
    for (const l of wizardLines) {
      const p = wizardProducts.find(x => x.id === l.catalog_product_id);
      const price = p ? priceOrNull(p.buying_price) : 0;
      if (price == null) { anyUnknown = true; continue; }
      sum += price * (Number(l.quantity) || 0);
    }
    return anyUnknown ? null : sum;
  }

  function wizardCartQty() {
    return wizardLines.reduce((sum, l) => sum + (Number(l.quantity) || 0), 0);
  }

  async function renderWizard() {
    const stepsEl = document.getElementById("vo-wizard-steps");
    const bodyEl = document.getElementById("vo-wizard-body");
    const footerEl = document.getElementById("vo-wizard-footer");
    const titleEl = document.getElementById("vo-wizard-title");
    const subEl = document.getElementById("vo-wizard-sub");
    if (!stepsEl || !bodyEl || !footerEl) return;

    stepsEl.innerHTML = STEP_LABELS.map((lbl, i) => {
      const n = i + 1;
      const cls = n === wizardStep ? "step active" : n < wizardStep ? "step done" : "step";
      return `<div class="${cls}"><span class="step-num">${n < wizardStep ? "✓" : n}</span><span class="step-label">${lbl}</span></div>`;
    }).join("");

    if (wizardStep === 1) {
      if (titleEl) titleEl.textContent = "New Vendor Order";
      if (subEl) subEl.textContent = "Step 1 — choose who you are ordering from";
      const vendors = await ensureWizardVendors();
      const active = vendors.filter(v => v.is_active && !v.deleted_at).sort((a, b) => vendorLabel(a).localeCompare(vendorLabel(b)));
      const filtered = OrdersUI.filterAndRankParties(active, wizardVendorSearch);
      const selected = wizardSelectedVendor(active);
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>Select vendor</h4>
          <p>Tap a vendor card to continue. You can search if the list is long.</p>
        </div>
        <div class="vo-wiz-search-wrap">
          <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
          <input id="vo-vendor-search" class="input vo-wiz-search" type="search" placeholder="Search vendor name, alias, city, or phone…" value="${ctx.esc(wizardVendorSearch)}" oninput="VendorOrders.onVendorSearch(this.value)" autocomplete="off" />
          ${wizardVendorSearch ? `<button type="button" class="vo-wiz-search-clear" onclick="VendorOrders.onVendorSearch('')">×</button>` : ""}
        </div>
        ${selected ? `<div class="vo-wiz-selected-banner">
          <div>
            <span class="vo-wiz-selected-label">Selected</span>
            <strong>${ctx.esc(vendorLabel(selected))}</strong>
          </div>
          <button type="button" class="btn btn-ghost btn-sm" onclick="VendorOrders.pickVendor(null)">Change</button>
        </div>` : ""}
        <div class="vo-wiz-vendor-list" id="vo-vendor-list">
          ${filtered.length ? filtered.map(v => {
            const selectedCls = wizardVendorId === v.id ? " selected" : "";
            const city = v.city_name || v.city || "";
            const alias = (v.alias || "").trim();
            return `<button type="button" class="vo-wiz-vendor-card${selectedCls}" onclick="VendorOrders.pickVendor(${v.id})">
              <span class="vo-wiz-vendor-letter">${ctx.esc((v.business_name || "?").slice(0, 1).toUpperCase())}</span>
              <span class="vo-wiz-vendor-meta">
                <strong>${ctx.esc(v.business_name || "Vendor")}</strong>
                ${alias ? `<span>${ctx.esc(alias)}</span>` : ""}
                <span>${city ? ctx.esc(city) : "No city"}${v.phone ? ` · ${ctx.esc(v.phone)}` : ""}</span>
              </span>
              <span class="vo-wiz-vendor-check">${wizardVendorId === v.id ? "✓" : ""}</span>
            </button>`;
          }).join("") : HubUI.emptyState({ title: "No matches", sub: `No vendors match “${wizardVendorSearch}”.` })}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="VendorOrders.closeWizard()">Cancel</button>
        <button class="btn btn-primary" ${wizardVendorId ? "" : "disabled"} onclick="VendorOrders.wizardNext()">Next: Products →</button>`;
      setTimeout(() => document.getElementById("vo-vendor-search")?.focus(), 30);
      return;
    }

    if (wizardStep === 2) {
      if (titleEl) titleEl.textContent = "Add Products";
      if (subEl) subEl.textContent = "Step 2 — search, tick products, set quantity";
      if (!wizardProducts.length) {
        ctx.showLoading?.();
        try { wizardProducts = await ctx.api(`/vendor-orders/vendor/${wizardVendorId}/products`, {}, 0); }
        catch (e) { ctx.toast(e.message, "error"); wizardStep = 1; return renderWizard(); }
        finally { ctx.hideLoading?.(); }
      }
      const vendors = await ensureWizardVendors();
      const vendorName = vendorLabel(wizardSelectedVendor(vendors));
      const shown = filterWizardProducts();
      const list = shown;
      const cartHtml = wizardLines.length ? `
        <div class="vo-wiz-cart">
          <div class="vo-wiz-cart-head">
            <strong>In this order</strong>
            <span>${wizardLines.length} product${wizardLines.length === 1 ? "" : "s"} · ${wizardCartQty()} qty</span>
          </div>
          <div class="vo-wiz-cart-chips">
            ${wizardLines.map(l => {
              const p = wizardProducts.find(x => x.id === l.catalog_product_id);
              return `<span class="vo-wiz-cart-chip">
                <span>${ctx.esc(p ? (p.vendor_product_id ? `${p.our_product_id} / (${p.vendor_product_id})` : p.our_product_id) : l.catalog_product_id)} × ${l.quantity}</span>
                <button type="button" title="Remove" onclick="VendorOrders.toggleWizardProduct(${l.catalog_product_id}, false)">×</button>
              </span>`;
            }).join("")}
          </div>
        </div>` : "";

      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head vo-wiz-step-head-row">
          <div>
            <h4>Products from ${ctx.esc(vendorName || "vendor")}</h4>
            <p>${wizardProducts.length} product${wizardProducts.length === 1 ? "" : "s"} available — use search to find fast.</p>
          </div>
          <div class="vo-wiz-count-pill">${wizardLines.length} selected</div>
        </div>
        ${cartHtml}
        <div class="vo-wiz-search-wrap">
          <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
          <input id="vo-product-search" class="input vo-wiz-search" type="search" placeholder="Search product ID, category…" value="${ctx.esc(wizardProductSearch)}" oninput="VendorOrders.onProductSearch(this.value)" onkeydown="VendorOrders.onProductSearchKey(event)" onfocus="this.select()" autocomplete="off" />
          ${wizardProductSearch ? `<button type="button" class="vo-wiz-search-clear" onclick="VendorOrders.onProductSearch('')">×</button>` : ""}
        </div>
        <div class="vo-wiz-product-meta">
          <span>Showing ${list.length} of ${wizardProducts.length}${wizardProductSearch ? " (search + selected)" : ""}</span>
          ${wizardProductSearch && !shown.length ? `<button type="button" class="btn btn-ghost btn-sm" onclick="VendorOrders.onProductSearch('')">Clear search</button>` : ""}
        </div>
        <div class="vo-wiz-products" id="vo-product-list">
          ${list.length ? list.map(p => {
            const line = wizardLines.find(l => l.catalog_product_id === p.id);
            const qty = line ? line.quantity : 1;
            const checked = !!line;
            const img = (p.image_urls && p.image_urls[0]) || "";
            const alts = (p.alternatives || []).map(a =>
              `<button type="button" class="vo-alt-chip" onclick="event.stopPropagation();VendorOrders.swapProduct(${p.id},${a.catalog_product_id})">${ctx.esc(a.our_product_id)} · ${fmtPrice(a.buying_price)}</button>`
            ).join("");
            return `<div class="vo-wiz-product ${checked ? "selected" : ""}" onclick="VendorOrders.pickWizardProduct(${p.id})">
              <div class="vo-wiz-product-main">
                <input type="checkbox" ${checked ? "checked" : ""} onclick="event.stopPropagation();VendorOrders.toggleWizardProduct(${p.id}, this.checked)" />
                ${thumb(img)}
                <div class="vo-wiz-product-info">
                  <strong>${ctx.esc(p.our_product_id)}${p.vendor_product_id ? ` / (${ctx.esc(p.vendor_product_id)})` : ""}</strong>
                  <span class="vo-wiz-product-sub">${p.category ? ctx.esc(p.category) : "Product"}</span>
                  <span class="vo-wiz-product-price">${fmtPrice(p.buying_price)}</span>
                  ${alts ? `<div class="vo-alt-row" onclick="event.stopPropagation()">${alts}</div>` : ""}
                </div>
              </div>
              <div class="vo-wiz-qty" onclick="event.stopPropagation()">
                <label>Qty</label>
                <div class="vo-wiz-qty-controls">
                  <button type="button" class="vo-wiz-qty-btn" ${checked ? "" : "disabled"} onclick="VendorOrders.bumpWizardQty(${p.id}, -1)">−</button>
                  <input type="number" min="1" class="input vo-wiz-qty-input" data-qty-for="${p.id}" value="${qty}" ${checked ? "" : "disabled"} onchange="VendorOrders.setWizardQty(${p.id}, this.value)" onkeydown="VendorOrders.onWizardQtyKey(event)" onclick="event.stopPropagation()" />
                  <button type="button" class="vo-wiz-qty-btn" ${checked ? "" : "disabled"} onclick="VendorOrders.bumpWizardQty(${p.id}, 1)">+</button>
                </div>
              </div>
            </div>`;
          }).join("") : HubUI.emptyState({
            title: !wizardProducts.length ? "No products yet" : "No matches",
            sub: !wizardProducts.length
              ? "No products for this vendor yet."
              : `No products match “${wizardProductSearch}”.`,
            ctaHtml: wizardProductSearch
              ? `<button type="button" class="btn btn-secondary" onclick="VendorOrders.onProductSearch('')">Clear search</button>`
              : "",
          })}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="VendorOrders.wizardBack()">← Back</button>
        <div class="vo-wiz-footer-mid">${wizardLines.length ? `${wizardLines.length} item${wizardLines.length === 1 ? "" : "s"}${(() => { const t = wizardCartTotal(); return t == null ? "" : ` · est. ${fmtPrice(t)}`; })()}` : "Select at least one product"}</div>
        <button class="btn btn-primary" ${wizardLines.length ? "" : "disabled"} onclick="VendorOrders.wizardNext()">Review →</button>`;
      setTimeout(() => focusPendingQty(), 30);
      return;
    }

    if (wizardStep === 3) {
      if (titleEl) titleEl.textContent = "Review & Place";
      if (subEl) subEl.textContent = "Step 3 — confirm details, then place the order";
      const vendors = await ensureWizardVendors();
      const vendor = wizardSelectedVendor(vendors);
      const total = wizardCartTotal();
      bodyEl.innerHTML = `
        <div class="vo-wiz-review">
          <div class="vo-wiz-review-hero">
            <span class="vo-wiz-review-label">Ordering from</span>
            <strong>${ctx.esc(vendorLabel(vendor))}</strong>
            <span class="vo-wiz-review-stats">${wizardLines.length} product${wizardLines.length === 1 ? "" : "s"} · ${wizardCartQty()} total qty</span>
          </div>
          <div class="vo-wiz-review-table-wrap">
            <table class="data vo-wiz-review-table"><thead><tr>
              <th></th><th>Product</th><th>Qty</th><th>Buy price</th><th>Line</th>
            </tr></thead><tbody>
              ${wizardLines.map(l => {
                const p = wizardProducts.find(x => x.id === l.catalog_product_id);
                const img = p && p.image_urls && p.image_urls[0] ? p.image_urls[0] : "";
                const price = p ? priceOrNull(p.buying_price) : null;
                const lineTotal = price != null ? price * l.quantity : null;
                return `<tr>
                  <td>${thumb(img)}</td>
                  <td><strong>${ctx.esc(p ? (p.vendor_product_id ? `${p.our_product_id} / (${p.vendor_product_id})` : p.our_product_id) : "")}</strong>${p?.category ? `<div class="vo-wiz-product-sub">${ctx.esc(p.category)}</div>` : ""}</td>
                  <td><strong>${l.quantity}</strong></td>
                  <td>${price != null ? fmtPrice(price) : "—"}</td>
                  <td><strong>${lineTotal != null ? fmtPrice(lineTotal) : "—"}</strong></td>
                </tr>`;
              }).join("")}
            </tbody></table>
          </div>
          <div class="vo-wiz-review-total">
            <span>Estimated buy total</span>
            <strong>${total == null ? "—" : fmtPrice(total)}</strong>
          </div>
          <label class="label" style="margin-top:16px;">Order date</label>
          <input type="date" class="input" style="width:100%;max-width:220px;margin-bottom:4px;" value="${ctx.esc(wizardPlacedOn || localToday())}" onchange="VendorOrders.setWizardPlacedOn(this.value)" />
          <p class="vo-wiz-review-note">Day you placed with vendor (backdate OK). Goes to <strong>Placed</strong>. Next: Receive, then Bill.</p>
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="VendorOrders.wizardBack()">← Back</button>
        <button class="btn btn-primary btn-lg" onclick="VendorOrders.placeOrder()">Place with vendor</button>`;
    }
  }

  function setWizardPlacedOn(v) { wizardPlacedOn = v || localToday(); }

  function onVendorSearch(val) {
    const prev = document.getElementById("vo-vendor-search");
    const start = prev?.selectionStart;
    wizardVendorSearch = val || "";
    renderWizard().then(() => {
      const inp = document.getElementById("vo-vendor-search");
      if (!inp) return;
      inp.focus();
      if (typeof start === "number") {
        try { inp.setSelectionRange(start, start); } catch (_) {}
      }
    });
  }

  function onProductSearch(val) {
    const prev = document.getElementById("vo-product-search");
    const start = prev?.selectionStart;
    wizardProductSearch = val || "";
    renderWizard().then(() => {
      const inp = document.getElementById("vo-product-search");
      if (!inp) return;
      inp.focus();
      if (typeof start === "number") {
        try { inp.setSelectionRange(start, start); } catch (_) {}
      }
    });
  }

  function pickVendor(id) {
    wizardVendorId = id || null;
    wizardProducts = [];
    wizardLines = [];
    wizardProductSearch = "";
    renderWizard();
  }

  function focusPendingQty() {
    if (focusQtyProductId == null) return;
    const id = focusQtyProductId;
    focusQtyProductId = null;
    const el = document.querySelector(`[data-qty-for="${id}"]`);
    if (el) { el.disabled = false; el.focus(); el.select(); }
  }

  function toggleWizardProduct(productId, checked) {
    if (checked) {
      if (!wizardLines.find(l => l.catalog_product_id === productId)) {
        wizardLines.push({ catalog_product_id: productId, quantity: 1 });
      }
      focusQtyProductId = productId;
    } else {
      wizardLines = wizardLines.filter(l => l.catalog_product_id !== productId);
      focusQtyProductId = null;
    }
    renderWizard();
  }

  function pickWizardProduct(productId) {
    if (wizardLines.some(l => l.catalog_product_id === productId)) {
      const el = document.querySelector(`[data-qty-for="${productId}"]`);
      if (el) { el.disabled = false; el.focus(); el.select(); }
      return;
    }
    toggleWizardProduct(productId, true);
  }

  function onProductSearchKey(e) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const list = filterWizardProducts();
    if (!list.length) return;
    pickWizardProduct(list[0].id);
  }

  function onWizardQtyKey(e) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    wizardProductSearch = "";
    focusQtyProductId = null;
    Promise.resolve(renderWizard()).then(() => document.getElementById("vo-product-search")?.focus());
  }

  function setWizardQty(productId, raw) {
    const qty = Math.max(1, parseInt(String(raw || "1"), 10) || 1);
    const line = wizardLines.find(l => l.catalog_product_id === productId);
    if (line) line.quantity = qty;
    else wizardLines.push({ catalog_product_id: productId, quantity: qty });
    // soft update footer totals without full re-render of list focus
    const mid = document.querySelector(".vo-wiz-footer-mid");
    if (mid && wizardLines.length) mid.textContent = `${wizardLines.length} item${wizardLines.length === 1 ? "" : "s"} · est. ${fmtPrice(wizardCartTotal())}`;
    const pill = document.querySelector(".vo-wiz-count-pill");
    if (pill) pill.textContent = `${wizardLines.length} selected`;
  }

  function bumpWizardQty(productId, delta) {
    const line = wizardLines.find(l => l.catalog_product_id === productId);
    if (!line) {
      if (delta > 0) {
        wizardLines.push({ catalog_product_id: productId, quantity: 1 });
        renderWizard();
      }
      return;
    }
    line.quantity = Math.max(1, (Number(line.quantity) || 1) + delta);
    renderWizard();
  }

  function swapProduct(fromId, toId) {
    const idx = wizardLines.findIndex(l => l.catalog_product_id === fromId);
    const qty = idx >= 0 ? wizardLines[idx].quantity : 1;
    wizardLines = wizardLines.filter(l => l.catalog_product_id !== fromId && l.catalog_product_id !== toId);
    wizardLines.push({ catalog_product_id: toId, quantity: qty });
    renderWizard();
  }

  function wizardBack() { if (wizardStep > 1) { wizardStep--; renderWizard(); } }

  async function wizardNext() {
    if (wizardStep === 1 && !wizardVendorId) return;
    if (wizardStep === 2 && !wizardLines.length) return;
    wizardStep++;
    await renderWizard();
  }

  function openOrderPdf(url, print) {
    if (!url) return ctx.toast("PDF not ready", "error");
    const w = window.open(url, "_blank");
    if (print && w) {
      try { w.focus(); setTimeout(() => { try { w.print(); } catch (_) {} }, 600); } catch (_) {}
    }
  }

  async function fetchPlacementPdf(placementId, print) {
    if (!placementId) return;
    ctx.showLoading?.();
    try {
      const doc = await ctx.api(`/vendor-orders/placements/${placementId}/document`, {}, 0);
      if (!doc?.document_url) throw new Error("PDF not available yet");
      openOrderPdf(doc.document_url, print);
    } catch (e) { ctx.toast(e.message || "PDF not available", "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function placeOrder() {
    ctx.showLoading?.();
    try {
      const result = await ctx.api("/vendor-orders/placements", {
        method: "POST",
        body: JSON.stringify({
          vendor_id: wizardVendorId,
          lines: wizardLines,
          placed_on: wizardPlacedOn || localToday(),
        }),
      });
      ctx.invalidateCache?.("/vendor-orders");
      closeWizard();
      ctx.toast("Order placed", "success");
      const placements = result.placements || [];
      const latest = placements[placements.length - 1];
      let docUrl = null;
      if (latest?.id) {
        try {
          const doc = await ctx.api(`/vendor-orders/placements/${latest.id}/document`, {}, 0);
          docUrl = doc.document_url || null;
        } catch (_) {}
      }
      const lineRows = wizardLines.map(l => {
        const p = wizardProducts.find(x => x.id === l.catalog_product_id);
        return `<tr><td>${ctx.esc(p ? (p.vendor_product_id ? `${p.our_product_id} / (${p.vendor_product_id})` : p.our_product_id) : l.catalog_product_id)}</td><td>${l.quantity}</td><td>${p ? fmtPrice(p.buying_price) : "—"}</td></tr>`;
      }).join("");
      const pdfBtns = latest?.id
        ? (docUrl
          ? `<div class="doc-actions">
              <button class="btn btn-primary" onclick="VendorOrders.openOrderPdf('${docUrl}', true)">Print</button>
              <button class="btn btn-secondary" onclick="VendorOrders.openOrderPdf('${docUrl}', false)">Save PDF</button>
              <button class="btn btn-secondary" onclick="VendorOrders.openOrderPdf('${docUrl}', false)">View PDF</button>
            </div>`
          : `<div class="doc-actions">
              <button class="btn btn-primary" onclick="VendorOrders.fetchPlacementPdf(${latest.id}, true)">Get PDF &amp; Print</button>
              <button class="btn btn-secondary" onclick="VendorOrders.fetchPlacementPdf(${latest.id}, false)">Get PDF</button>
            </div>`)
        : "";
      ctx.openDetail?.("Order placed", `
        <div class="doc-success-banner">
          <strong>Placed with vendor</strong>
          <span>${latest?.id ? `Placement #${latest.id}` : "Saved"} · ${wizardLines.length} product${wizardLines.length === 1 ? "" : "s"}</span>
        </div>
        <p style="margin:0 0 12px;font-size:14px;color:var(--muted);">In <strong>Placed</strong>. Next: <strong>Receive</strong> when goods arrive.</p>
        <table class="data" style="font-size:13px;margin-top:12px;"><thead><tr><th>Product</th><th>Qty</th><th>Price</th></tr></thead><tbody>
          ${lineRows}
        </tbody></table>
        ${pdfBtns}`,
        `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail();Stock.openReceiveForVendor(${wizardVendorId})">Receive</button>
         <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail();VendorOrders.billVendor(${wizardVendorId})">Bill</button>
         <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail();VendorOrders.openDetail(${result.id || 0}, 'placed', ${wizardVendorId})">View</button>`, "md");
      currentBucket = "placed";
      hubMode = "browse";
      syncHubChrome();
      loadList();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function billSummaryLine(catalogProductId, pendingQty) {
    if (!detailVendorId) return;
    Stock.openReceiveForVendor(detailVendorId, { catalog_product_id: catalogProductId, quantity: pendingQty });
  }

  function receiveSummaryLine(catalogProductId, pendingQty) {
    return billSummaryLine(catalogProductId, pendingQty);
  }

  function cancelSummaryLine(catalogProductId) {
    const line = (orderSummary?.lines || []).find(l => l.catalog_product_id === catalogProductId);
    if (!line || line.total_pending <= 0) return;
    openConfirmAction({
      title: "Cancel pending qty",
      message: "Removed from Open. Recorded in Cancelled. Placed qty stays.",
      rows: [
        ["Product", ctx.esc(line.our_product_id)],
        ["Pending", String(line.total_pending)],
        ["Placed", String(line.total_placed)],
        ["Received", String(line.total_received)],
      ],
      confirmLabel: "Cancel pending",
      danger: true,
      requireReason: true,
      reasonLabel: "Cancel note",
      onConfirm: async (reason) => {
        await ctx.api(`/vendor-orders/vendor/${detailVendorId}/products/${catalogProductId}/cancel-pending`, { method: "POST", body: reasonBody(reason) });
        ctx.toast("Pending cancelled", "success");
        await reloadAfterVendorChange(detailVendorId, "summary");
      },
    });
  }

  function closeSummaryLine(catalogProductId) {
    const line = (orderSummary?.lines || []).find(l => l.catalog_product_id === catalogProductId);
    if (!line || line.total_pending <= 0) return;
    openConfirmAction({
      title: "Close pending qty",
      message: "Removes from Open and records as closed.",
      rows: [
        ["Product", ctx.esc(line.our_product_id)],
        ["Pending", String(line.total_pending)],
        ["Price", fmtPrice(line.buying_price)],
      ],
      confirmLabel: "Close",
      requireReason: true,
      reasonLabel: "Close note",
      onConfirm: async (reason) => {
        orderSummary = await ctx.api(`/vendor-orders/vendor/${detailVendorId}/products/${catalogProductId}/close-pending`, { method: "POST", body: reasonBody(reason) });
        ctx.invalidateCache?.("/vendor-orders");
        ctx.toast("Pending closed", "success");
        renderDetail();
      },
    });
  }


  async function toggleClosedRow(lineId) {
    expandedClosedId = expandedClosedId === lineId ? null : lineId;
    renderDetail();
    if (expandedClosedId) await loadClosedRowExpand(lineId);
  }

  async function loadClosedRowExpand(lineId) {
    const wrap = document.getElementById(`vo-closed-drill-${lineId}`);
    const line = (closedLines || []).find(l => l.id === lineId);
    if (!wrap || !line) return;
    let extra = "";
    if (line.source === "billed" && line.bill_number) {
      extra = `<p style="font-size:12px;color:var(--muted);margin:8px 0 0;">Closed from billed shipment — bill ${ctx.esc(line.bill_number)}</p>`;
    }
    wrap.innerHTML = `
      ${line.close_reason ? noteChip(line.close_reason, "close") : ""}
      <div class="vo-section-label">Closed line — ${ctx.esc(line.our_product_id)}</div>
      ${confirmDetailsTable([
        ["Product", ctx.esc(line.our_product_id)],
        ["Quantity", String(line.quantity)],
        ["Price", fmtPrice(line.buying_price)],
        ["Source", ctx.esc(line.source)],
        ["Bill", ctx.esc(line.bill_number || "—")],
        ["Close note", ctx.esc(line.close_reason || "—")],
        ["Closed", line.closed_at ? new Date(line.closed_at).toLocaleString() : "—"],
      ])}
      ${extra}`;
  }

  async function openPlacementDoc(placementId) {
    try {
      const doc = await ctx.api(`/vendor-orders/placements/${placementId}/document`, {}, 0);
      if (doc.document_url) window.open(doc.document_url, "_blank");
      else ctx.toast("Document not available", "error");
    } catch (e) { ctx.toast(e.message, "error"); }
  }

