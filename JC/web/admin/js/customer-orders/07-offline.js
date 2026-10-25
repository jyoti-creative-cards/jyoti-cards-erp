  let entryParties = null;
  let entryItems = null;

  async function ensureEntryCatalogs() {
    if (entryParties && entryItems) return;
    const [parties, items] = await Promise.all([
      ctx.api("/customers/entry-parties", {}, 0),
      ctx.api("/stock/entry-items", {}, 0),
    ]);
    entryParties = parties || [];
    entryItems = items || [];
  }

  function filterEntryParties(q) {
    const needle = String(q || "").trim().toLowerCase();
    if (!needle) return [];
    const scored = [];
    for (const c of entryParties || []) {
      const name = String(c.business_name || "").toLowerCase();
      const alias = String(c.alias || "").toLowerCase();
      const city = String(c.city_name || "").toLowerCase();
      const phone = String(c.phone || "");
      const num = String(c.party_number || "");
      let score = 0;
      if (name === needle || num === needle) score = 100;
      else if (name.startsWith(needle) || alias.startsWith(needle) || num.startsWith(needle)) score = 80;
      else if (name.includes(needle) || alias.includes(needle) || city.includes(needle) || phone.includes(needle)) score = 40;
      else continue;
      scored.push({ c, score, name });
    }
    scored.sort((a, b) => b.score - a.score || a.name.localeCompare(b.name));
    return scored.slice(0, 12).map(x => x.c);
  }

  function filterEntryItems(q) {
    const needle = String(q || "").trim().toLowerCase();
    if (!needle) return [];
    const scored = [];
    for (const p of entryItems || []) {
      const id = String(p.our_product_id || "").toLowerCase();
      let score = 0;
      if (id === needle) score = 100;
      else if (id.startsWith(needle)) score = 80;
      else if (id.includes(needle)) score = 40;
      else continue;
      scored.push({ p, score, id });
    }
    scored.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
    return scored.slice(0, 12).map(x => x.p);
  }

  async function openOfflineWizard(presetCustomerId, presetProductId) {
    const hasPreset = arguments.length > 0 && presetCustomerId != null && presetCustomerId !== "";
    const cid = hasPreset ? presetCustomerId : null;
    const productId = presetProductId != null && presetProductId !== "" ? Number(presetProductId) : 0;
    offlineEditPlacementId = null;
    offlineStep = 1;
    offlineCustomerId = null;
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
    offlineReview = false;
    offlineBusy = false;
    offlineCustomers = [];
    document.getElementById("co-offline-wizard")?.classList.remove("hidden");
    const body = document.getElementById("co-offline-body");
    if (body) body.innerHTML = `<p style="color:var(--muted);">Loading…</p>`;
    try {
      await ensureEntryCatalogs();
    } catch (e) { ctx.toast(e.message || "Could not load the lists", "error"); }
    if (cid) {
      const c = (entryParties || []).find(x => Number(x.id) === Number(cid));
      if (c) {
        offlineCustomerId = c.id;
        offlineCustomerName = c.business_name || "";
        offlinePicked = c;
      } else {
        offlineCustomerId = cid;
      }
    }
    if (productId) {
      const p = (entryItems || []).find(x => Number(x.catalog_product_id) === productId);
      if (!p) ctx.toast("That item is not on the order list", "error");
      else if (!offlineLines.some(l => l.catalog_product_id === p.catalog_product_id)) {
        offlineLines.push({
          catalog_product_id: p.catalog_product_id,
          our_product_id: p.our_product_id,
          quantity: 1,
          min_qty: 0,
          selling_price: p.selling_price,
          quantity_on_hand: p.quantity_on_hand,
          addons: (p.addons && p.addons.length) ? p.addons : (p.priced_addons || []),
          priced_addons: p.priced_addons || [],
          skip_addon_ids: [],
        });
      }
    }
    renderOfflineWizard();
  }

  function onOfflineCustomerSearch(val) {
    offlineCustomerSearch = val || "";
    const box = document.getElementById("co-order-customer-matches");
    if (!box) return;
    const rows = filterEntryParties(offlineCustomerSearch);
    box.innerHTML = rows.map(c =>
      `<button type="button" class="btn btn-secondary btn-sm" style="display:block;width:100%;text-align:left;margin-top:4px;" onclick="CustomerOrders.pickOfflineCustomer(${c.id})">${ctx.esc(c.business_name || "")}${c.city_name ? " · " + ctx.esc(c.city_name) : ""}${c.party_number ? " · #" + c.party_number : ""}</button>`
    ).join("") || (String(offlineCustomerSearch || "").trim() ? `<p style="font-size:13px;color:var(--muted);margin:6px 0 0;">No match</p>` : "");
  }

  function pickOfflineCustomer(id) {
    const c = (entryParties || []).find(x => Number(x.id) === Number(id));
    if (!c) return;
    offlineCustomerId = c.id;
    offlineCustomerName = c.business_name || "";
    offlinePicked = c;
    offlineCustomerSearch = "";
    const picked = document.getElementById("co-order-customer-picked");
    if (picked) picked.textContent = `${c.business_name || ""}${c.city_name ? " · " + c.city_name : ""}`;
    const input = document.getElementById("co-order-customer");
    if (input) input.value = "";
    const box = document.getElementById("co-order-customer-matches");
    if (box) box.innerHTML = "";
    loadBookedOrders();
    document.getElementById("co-order-item")?.focus();
  }

  function previewOrder() {
    const notesEl = document.getElementById("co-order-note");
    if (notesEl) offlineNotes = notesEl.value || "";
    const dateEl = document.getElementById("co-order-date");
    if (dateEl && dateEl.value) offlinePlacedOn = dateEl.value;
    if (!offlineCustomerId) return ctx.toast("Select a customer", "error");
    if (!offlineLines.some(l => Number(l.quantity) > 0)) return ctx.toast("Add at least one item", "error");
    offlineReview = true;
    renderOfflineWizard();
  }

  function backFromOrderPreview() {
    offlineReview = false;
    renderOfflineWizard();
  }

  function renderOrderReview(bodyEl, footerEl) {
    const lines = offlineLines.filter(l => Number(l.quantity) > 0);
    const total = lines.reduce((s, l) => s + (Number(l.selling_price) || 0) * (Number(l.quantity) || 0), 0);
    bodyEl.innerHTML = `
      <p style="margin:0 0 8px;font-size:13px;color:var(--muted);">Check this order, then save.</p>
      <p style="margin:0 0 12px;"><strong>${ctx.esc(offlineCustomerName || "")}</strong></p>
      <p style="margin:0 0 12px;font-size:13px;">${ctx.esc(offlinePlacedOn || "")}</p>
      ${offlineNotes ? `<p style="margin:0 0 12px;color:#b91c1c;font-weight:700;">${ctx.esc(offlineNotes)}</p>` : ""}
      <table class="data"><thead><tr><th>Item</th><th>Qty</th><th>Rate</th></tr></thead><tbody>
        ${lines.map(l => `<tr><td>${ctx.esc(l.our_product_id)}</td><td>${l.quantity}</td><td>${fmtPrice(l.selling_price)}</td></tr>`).join("")}
      </tbody></table>
      <p style="margin:8px 0 0;font-weight:700;">${fmtPrice(total)}</p>`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="CustomerOrders.backFromOrderPreview()">Go back</button>
      <button class="btn btn-primary" ${offlineBusy ? "disabled" : ""} onclick="CustomerOrders.submitOffline()">${offlineBusy ? "Saving…" : "Save order"}</button>`;
  }

  function closeOfflineWizard() {
    offlineReview = false;
    offlineConfirmDuplicate = false;
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
      confirm_duplicate: !!offlineConfirmDuplicate,
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
      const extras = (l.addons && l.addons.length) ? l.addons : (l.priced_addons || []);
      for (const a of extras) {
        if (skipped.has(a.addon_product_id)) continue;
        if (!(Number(a.selling_price) > 0)) continue;
        n += (Number(a.selling_price) || 0) * (Number(a.quantity) || 1) * (Number(l.quantity) || 0);
      }
      return s + n;
    }, 0);
  }

  function lineAddons(p, line) {
    if (line && Array.isArray(line.addons) && line.addons.length) return line.addons;
    if (p && Array.isArray(p.addons) && p.addons.length) return p.addons;
    return (line && line.priced_addons) || (p && p.priced_addons) || [];
  }

  function pricedAddonHtml(p, line) {
    const addons = lineAddons(p, line);
    if (!addons.length || !line) return "";
    const skipped = new Set(line.skip_addon_ids || []);
    return addons.map(a => {
      const id = a.addon_product_id;
      const name = a.name || a.our_product_id || "Add-on";
      const price = Number(a.selling_price) || 0;
      const priceBit = price > 0 ? ` · ₹${price} each` : "";
      if (skipped.has(id)) {
        return `<div class="co-addon-row" onclick="event.stopPropagation()">${ctx.esc(name)} removed · <button type="button" class="btn btn-ghost btn-sm" onclick="event.stopPropagation();CustomerOrders.skipOfflineAddon(${p.catalog_product_id}, ${id})">Add back</button></div>`;
      }
      return `<div class="co-addon-row" onclick="event.stopPropagation()">+ ${ctx.esc(name)}${priceBit} <button type="button" class="btn btn-ghost btn-sm" onclick="event.stopPropagation();CustomerOrders.skipOfflineAddon(${p.catalog_product_id}, ${id})">Remove</button></div>`;
    }).join("");
  }

  let offlineReview = false;

  function renderOfflineWizard() {
    const bodyEl = document.getElementById("co-offline-body");
    const footerEl = document.getElementById("co-offline-footer");
    const stepsEl = document.getElementById("co-offline-steps");
    if (!bodyEl || !footerEl) return;
    if (offlineReview) {
      renderOrderReview(bodyEl, footerEl);
      return;
    }
    if (stepsEl) stepsEl.innerHTML = "";
    const editing = !!offlineEditPlacementId;
    const picked = offlinePicked;
    bodyEl.innerHTML = `
      <label class="label">Customer</label>
      ${editing ? `<p style="margin:0 0 12px;"><strong>${ctx.esc(offlineCustomerName || "")}</strong></p>` : `
        <input id="co-order-customer" class="input" type="text" placeholder="Name, city, or number" autocomplete="off" oninput="CustomerOrders.onOfflineCustomerSearch(this.value)" />
        <div id="co-order-customer-picked" style="margin:6px 0;font-weight:600;">${picked ? ctx.esc((picked.business_name || "") + (picked.city_name ? " · " + picked.city_name : "")) : ""}</div>
        <div id="co-order-customer-matches"></div>`}
      <div id="co-order-booked"></div>
      <label class="label">Item number</label>
      <input id="co-order-item" class="input" type="text" placeholder="Type the item number" autocomplete="off" oninput="CustomerOrders.onOfflineSearchInput(this.value)" onkeydown="CustomerOrders.onOfflineSearchKey(event)" />
      <div id="co-order-item-matches"></div>
      <div id="co-order-lines" style="margin-top:12px;"></div>
      <div style="display:grid;grid-template-columns:160px 1fr;gap:12px;margin-top:16px;">
        <div>
          <label class="label">Date</label>
          <input id="co-order-date" type="date" class="input" value="${ctx.esc(offlinePlacedOn || localToday())}" onchange="CustomerOrders.setOfflinePlacedOn(this.value)" />
        </div>
        <div>
          <label class="label">Marking</label>
          <input id="co-order-note" class="input" style="border:2px solid #dc2626;background:#fef2f2;font-weight:700;color:#b91c1c;" placeholder="Hold. Do not bill. Bill after 5 days." value="${ctx.esc(offlineNotes || "")}" oninput="CustomerOrders.setOfflineNotes(this.value)" />
          <p style="margin:4px 0 0;font-size:12px;color:#b91c1c;">Shown in red on the bill. Use it when the quantity should stay reserved.</p>
        </div>
      </div>`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="CustomerOrders.closeOfflineWizard()">Cancel</button>
      <button class="btn btn-primary" ${offlineBusy ? "disabled" : ""} onclick="CustomerOrders.submitOffline()">${offlineBusy ? "Saving…" : "Save order"}</button>`;
    paintOrderLines();
    loadBookedOrders();
    const focusId = editing || offlineCustomerId ? "co-order-item" : "co-order-customer";
    document.getElementById(focusId)?.focus();
  }

  function bookedOrdersHtml(detail) {
    const lines = detail?.open_lines || [];
    const notes = (detail?.placements || []).map(p => p.customer_notes).filter(Boolean);
    if (!lines.length && !notes.length) {
      return `<p style="font-size:13px;color:var(--muted);margin:6px 0 10px;">No confirmed order waiting for this customer.</p>`;
    }
    const rows = lines.map(ln => `<div style="display:flex;justify-content:space-between;gap:8px;font-size:13px;padding:4px 0;border-bottom:1px solid #fecaca;"><strong>${ctx.esc(ln.our_product_id)}</strong><span>${ln.quantity_open} booked</span></div>`).join("");
    return `<div style="margin:8px 0 12px;padding:8px 10px;background:#fef2f2;border:1px solid #dc2626;border-radius:8px;">
      <strong style="color:#b91c1c;">Already booked. Bill this. Do not make a new order if they only want part of it billed.</strong>
      ${notes.length ? `<div style="color:#b91c1c;font-weight:700;margin-top:4px;">${ctx.esc(notes.join(" · "))}</div>` : ""}
      ${rows}
      <button type="button" class="btn btn-primary" style="margin-top:10px;width:100%;" onclick="CustomerOrders.billBookedOrder()">Bill this order</button>
    </div>`;
  }

  function billBookedOrder() {
    const id = offlineCustomerId;
    if (!id) return;
    closeOfflineWizard();
    processFromHub(id, "open");
  }

  async function loadBookedOrders() {
    const box = document.getElementById("co-order-booked");
    if (!box) return;
    if (!offlineCustomerId) { box.innerHTML = ""; return; }
    box.innerHTML = `<p style="font-size:13px;color:var(--muted);margin:6px 0 10px;">Checking booked orders…</p>`;
    try {
      const detail = await ctx.api(`/customer-orders/customer/${offlineCustomerId}?bucket=open`, {}, 0);
      const still = document.getElementById("co-order-booked");
      if (still) still.innerHTML = bookedOrdersHtml(detail);
    } catch (_) {
      const still = document.getElementById("co-order-booked");
      if (still) still.innerHTML = "";
    }
  }

  function paintOrderLines() {
    const box = document.getElementById("co-order-lines");
    if (!box) return;
    if (!offlineLines.length) {
      box.innerHTML = `<p style="font-size:13px;color:var(--muted);margin:0;">No items yet.</p>`;
      return;
    }
    box.innerHTML = `<table class="data"><thead><tr><th>Item</th><th>Stock</th><th>Rate</th><th>Qty</th><th></th></tr></thead><tbody>
      ${offlineLines.map(l => `<tr>
        <td><strong>${ctx.esc(l.our_product_id)}</strong>${pricedAddonHtml({ catalog_product_id: l.catalog_product_id }, l)}</td>
        <td>${l.quantity_on_hand ?? "—"}${Number(l.quantity_on_hand) <= 0 ? ` <span style="color:#b45309;">in transit</span>` : ""}</td>
        <td>${fmtPrice(l.selling_price)}</td>
        <td><input data-qty-for="${l.catalog_product_id}" type="number" class="input" style="width:72px;" min="${Number(l.min_qty) || 1}" value="${l.quantity}" oninput="CustomerOrders.setOfflineQty(${l.catalog_product_id}, this.value)" onkeydown="CustomerOrders.onOfflineQtyKey(event)" /></td>
        <td><button type="button" class="btn btn-ghost btn-sm" onclick="CustomerOrders.removeOfflineLine(${l.catalog_product_id})">Remove</button></td>
      </tr>`).join("")}
    </tbody></table>
    <p style="margin:8px 0 0;font-size:13px;">${offlineLines.length} item(s) · ${fmtPrice(offlineCartTotal())}</p>`;
  }

  function setOfflineNotes(v) { offlineNotes = v || ""; }
  function setOfflinePlacedOn(v) { offlinePlacedOn = v || localToday(); }

  function onOfflineSearchInput(val) {
    offlineSearchQuery = val || "";
    const box = document.getElementById("co-order-item-matches");
    if (!box) return;
    const rows = filterEntryItems(offlineSearchQuery);
    offlineSearchResults = rows;
    box.innerHTML = rows.map(p =>
      `<button type="button" class="btn btn-secondary btn-sm" style="display:block;width:100%;text-align:left;margin-top:4px;" onclick="CustomerOrders.pickOfflineProduct(${p.catalog_product_id})">${ctx.esc(p.our_product_id)} · stock ${p.quantity_on_hand ?? 0}${p.selling_price ? " · " + fmtPrice(p.selling_price) : ""}</button>`
    ).join("") || (String(offlineSearchQuery || "").trim() ? `<p style="font-size:13px;color:var(--muted);margin:6px 0 0;">No match</p>` : "");
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

  async   function onOfflineSearchKey(e) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const q = offlineSearchQuery.trim().toLowerCase();
    if (!q) return;
    const matches = filterEntryItems(q);
    const exact = matches.find(p => String(p.our_product_id || "").toLowerCase() === q);
    const best = exact || matches[0];
    if (!best) return ctx.toast("No product match", "error");
    pickOfflineProduct(best.catalog_product_id);
  }

  function onOfflineQtyKey(e) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    offlineSearchQuery = "";
    focusQtyProductId = null;
    const item = document.getElementById("co-order-item");
    if (item) { item.value = ""; item.focus(); }
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
    const p = (entryItems || []).find(x => x.catalog_product_id === catalogProductId)
      || offlineSearchResults.find(x => x.catalog_product_id === catalogProductId);
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
          addons: (p.addons && p.addons.length) ? p.addons : (p.priced_addons || []),
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
    const itemInput = document.getElementById("co-order-item");
    if (itemInput) itemInput.value = "";
    offlineSearchQuery = "";
    const matches = document.getElementById("co-order-item-matches");
    if (matches) matches.innerHTML = "";
    paintOrderLines();
    if (checked) {
      const el = document.querySelector(`[data-qty-for="${catalogProductId}"]`);
      if (el) { el.focus(); el.select(); }
    }
  }

  function skipOfflineAddon(catalogProductId, addonId) {
    const line = offlineLines.find(l => l.catalog_product_id === catalogProductId);
    if (!line) return;
    const id = Number(addonId);
    const skipped = new Set(line.skip_addon_ids || []);
    if (skipped.has(id)) skipped.delete(id);
    else skipped.add(id);
    line.skip_addon_ids = [...skipped];
    paintOrderLines();
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
      const p = (entryItems || []).find(x => x.catalog_product_id === cid)
        || offlineSearchResults.find(x => x.catalog_product_id === cid);
      if (p) offlineLines.push({
        catalog_product_id: p.catalog_product_id,
        our_product_id: p.our_product_id,
        quantity: qty,
        min_qty: 0,
        selling_price: p.selling_price,
        quantity_on_hand: p.quantity_on_hand,
        addons: (p.addons && p.addons.length) ? p.addons : (p.priced_addons || []),
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
    paintOrderLines();
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
    if (!offlineConfirmDuplicate) showOrderPlaced();
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
        loadList(true);
        return;
      }
      const res = await ctx.api(`/customer-orders/customer/${offlineCustomerId}/offline`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/stock");
      const cid = offlineCustomerId;
      ctx.toast("Order placed", "success");
      detailCustomerId = cid;
      currentBucket = "open";
      closeOfflineWizard();
      await processOrder({ quiet: true });
      loadList(true);
    } catch (e) {
      const matches = e.status === 409 && e.detail && e.detail.matches;
      if (matches) {
        showDuplicateWarning(e.detail);
        return;
      }
      offlineConfirmDuplicate = false;
      ctx.toast(e.message || "Could not place order", "error");
      renderOfflineWizard();
    } finally {
      offlineBusy = false;
    }
  }

  function showDuplicateWarning(detail) {
    const body = document.getElementById("co-offline-body");
    const footer = document.getElementById("co-offline-footer");
    const rows = (detail.matches || []).map((m) => {
      const bits = [];
      if (m.same_items && m.same_items.length) bits.push(`same item ${m.same_items.join(", ")}`);
      if (m.same_amount) bits.push(`same amount ₹${m.total}`);
      return `<li>Order #${m.placement_id}: ${bits.join(" · ")}</li>`;
    }).join("");
    if (body) {
      body.innerHTML = `<div style="border:2px solid #b45309;background:#fffbeb;border-radius:12px;padding:16px;">
        <strong style="font-size:18px;">This could be a duplicate entry.</strong>
        <p style="margin:8px 0;">Same date, same party. The following are the same:</p>
        <ul style="margin:0 0 8px 18px;">${rows}</ul>
        <p style="margin:0;">Do you want to proceed?</p>
      </div>`;
    }
    if (footer) {
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="CustomerOrders.backFromDuplicate()">Go back</button>
        <button class="btn btn-primary" onclick="CustomerOrders.proceedDuplicate()">Proceed</button>`;
    }
  }

  function backFromDuplicate() {
    offlineConfirmDuplicate = false;
    offlineBusy = false;
    renderOfflineWizard();
  }

  function proceedDuplicate() {
    offlineConfirmDuplicate = true;
    submitOffline();
  }

  function showOrderPlaced() {
    const body = document.getElementById("co-offline-body");
    const footer = document.getElementById("co-offline-footer");
    if (body) body.innerHTML = `<p style="margin:0;font-size:18px;"><strong>Order placed.</strong> Opening the bill…</p>`;
    if (footer) footer.innerHTML = "";
  }

