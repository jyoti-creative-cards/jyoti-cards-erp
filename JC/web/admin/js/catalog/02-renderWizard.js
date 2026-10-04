  function renderWizard() {
    renderWizardSteps();
    const body = document.getElementById("catalog-wizard-body");
    const footer = document.getElementById("catalog-wizard-footer");
    if (!body || !footer) return;

    if (wizardStep === 1) renderWizardStep1(body, footer);
    else if (wizardStep === 2) renderWizardStep2(body, footer);
    else if (wizardStep === 3) renderWizardStep3(body, footer);
    else if (wizardStep === 4) renderWizardStep4(body, footer);
  }

  function setWizardVendor(val) {
    wizardVendorId = val ? parseInt(val, 10) : null;
    _loadVendorProducts(wizardVendorId);
  }

  /** Populate the `products` cache used by allProductOptions()/checkWizardDuplicates()'s
   * fallback — without this, both silently no-op against an always-empty array. */
  async function _loadVendorProducts(vendorId) {
    if (!vendorId) { products = []; return; }
    try {
      const res = await ctx.api(`/catalog/products?vendor_id=${vendorId}&limit=200`, {}, 0);
      products = res?.items || (Array.isArray(res) ? res : []);
    } catch (_) {
      products = [];
    }
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

  function deleteWizardRow(idx) {
    wizardRows.splice(idx, 1);
    if (!wizardRows.length) wizardRows = [emptyWizardRow()];
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
    const yg = document.getElementById("cw-bulk-year_group")?.value;
    const buy = document.getElementById("cw-bulk-buying_price")?.value;
    const sell = document.getElementById("cw-bulk-selling_price")?.value;
    if (cat) patch.category = cat;
    if (yg && ctx.isAdmin?.()) patch.year_group = yg;
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
    // Clear selection so next bulk apply targets a fresh set of rows.
    wizardRows.forEach(r => { r.selected = false; });
    const selectAll = document.getElementById("cw-select-all");
    if (selectAll) selectAll.checked = false;
    ctx.toast(`Applied to ${applied} row(s)`, "success");
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
    if (wizardStep === 2) await checkWizardDuplicates();
    if (wizardStep < 3) wizardStep++;
    renderWizard();
  }

  async function uploadImage(vendorId, ourProductId, imageIndex, file, yearGroup = null) {
    if (ctx.uploadImage) return ctx.uploadImage(vendorId, ourProductId, file, imageIndex, yearGroup);
    const fd = new FormData();
    fd.append("vendor_id", String(vendorId));
    fd.append("our_product_id", ourProductId);
    fd.append("image_index", String(imageIndex));
    if (yearGroup) fd.append("year_group", yearGroup);
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
    const filled = filledWizardRows();
    const dupeKeys = new Set((wizardDupes || []).map(d => String(d).toLowerCase()));
    const dupes = filled.filter(r => dupeKeys.has(skuYearKey(r.our_product_id, r.year_group)));
    if (dupes.length) return ctx.toast("Fix duplicate product IDs for the same year group first", "error");

    const btn = document.getElementById("catalog-create-btn");
    const btnLabel = btn?.textContent || "Create All";
    if (btn) { btn.disabled = true; btn.textContent = "Creating…"; }
    ctx.showLoading?.();
    try {
      const ok = await (ctx.checkBackend ? ctx.checkBackend() : Promise.resolve(true));
      if (!ok) throw new Error("Backend not reachable — start JC backend on port 8003");

      const items = [];
      for (let ri = 0; ri < filled.length; ri++) {
        const row = filled[ri];
        const imageKeys = [];
        if (row.imageFiles.length) {
          if (btn) btn.textContent = `Uploading images ${ri + 1}/${filled.length}…`;
          for (let i = 0; i < row.imageFiles.length; i++) {
            try {
              const up = await uploadImage(wizardVendorId, row.our_product_id.trim(), i + 1, row.imageFiles[i], row.year_group || null);
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
          unit: "pcs",
          year_group: ctx.isAdmin?.() ? (row.year_group || DEFAULT_YEAR_GROUP) : DEFAULT_YEAR_GROUP,
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
      wizardStep = 4;
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
      if (btn && wizardStep !== 4) btn.textContent = btnLabel;
    }
  }

  async function openEdit(id, returnTo) {
    editingId = id;
    editReturnTo = returnTo || null;
    ctx.showLoading?.();
    try {
      const [p, optRes] = await Promise.all([
        ctx.api(`/catalog/products/${id}`, {}, 0),
        ctx.api("/catalog/product-options", {}, 120000).catch(() => []),
        loadAddons(),
        ensureProductCategories(),
        ensureProductYears(),
      ]);
      if (!p || !p.id) throw new Error("Product not found");
      const altOptions = (Array.isArray(optRes) ? optRes : []).filter(x => x.id !== p.id);

      // Keep already-linked add-ons in the dropdown even if /addons list failed or filtered them out
      const linkedAddons = (p.addon_links || []).map(l => ({
        our_product_id: l.addon_our_product_id,
        name: l.addon_name || l.addon_our_product_id,
      }));
      for (const la of linkedAddons) {
        if (la.our_product_id && !addons.some(a => String(a.our_product_id).toLowerCase() === String(la.our_product_id).toLowerCase())) {
          addons.push(la);
        }
      }
      const addonWarn = !addons.length
        ? `<p style="margin:6px 0 0;font-size:12px;color:#b45309;">No add-ons available. Create them under Products → Add-ons first.</p>`
        : "";

    const imgPreview = p.image_urls && p.image_urls[0]
      ? `<img id="ce-preview" src="${ctx.esc(p.image_urls[0])}" alt="" style="width:80px;height:80px;object-fit:cover;border-radius:8px;border:1px solid var(--border);" />`
      : `<div id="ce-preview" style="width:80px;height:80px;border-radius:8px;background:#f1f5f9;border:1px dashed var(--border);display:flex;align-items:center;justify-content:center;font-size:11px;color:var(--muted);">No image</div>`;

    document.getElementById("catalog-edit-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Our Product ID *</label>
          <input id="ce-our_product_id" class="input" value="${ctx.esc(p.our_product_id)}" /></div>
        <div><label class="label">Vendor Product ID</label>
          <input id="ce-vendor_product_id" class="input" value="${ctx.esc(p.vendor_product_id)}" /></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Category</label>
            ${categoryField("ce-category", p.category)}</div>
          <div><label class="label">Second category</label>
            ${categoryField("ce-second_category", p.second_category)}</div>
        </div>
        <div>
          <label class="label">Year Group ${ctx.isAdmin?.() ? "" : "(admin only)"}</label>
          ${yearSelectHtml(p.year_group || DEFAULT_YEAR_GROUP, { id: "ce-year_group" })}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Buying Price</label>
            ${p.buying_price === "—"
              ? `<input id="ce-buying_price" class="input" type="text" value="Hidden — no cost access" disabled title="You don't have costs.read, so this can't be viewed or changed here." />`
              : `<input id="ce-buying_price" class="input" type="number" min="0" step="0.01" value="${ctx.esc(p.buying_price)}" />`}</div>
          <div><label class="label">Selling Price</label>
            <input id="ce-selling_price" class="input" type="number" min="0" step="0.01" value="${ctx.esc(p.selling_price || "")}" /></div>
        </div>
        <div style="padding:12px;border:1px dashed var(--border);border-radius:10px;background:#f8fafc;">
          <label class="label">Marking</label>
          <input id="ce-marking" class="input" maxlength="200" placeholder="e.g. Fragile, check quality" value="${ctx.esc(p.marking || "")}" />
          <p style="margin:6px 0 0;font-size:12px;color:var(--muted);">Internal only — shown on orders/bill/catalog/stock screens for staff, never on the customer's bill PDF.</p>
        </div>
        <div>
          <label class="label">Product Image</label>
          <div style="display:flex;align-items:center;gap:16px;">
            ${imgPreview}
            <div style="flex:1;">
              <input id="ce-image" type="file" accept="image/*" class="input" />
              <input type="hidden" id="ce-image_keys" value="${ctx.esc((p.image_keys || []).join(","))}" />
              <input type="hidden" id="ce-vendor_id" value="${p.vendor_id}" />
              <p style="margin:6px 0 0;font-size:12px;color:var(--muted);">${p.image_urls?.length ? "Replace image (optional)." : "Add an image now, or leave empty."}</p>
            </div>
          </div>
        </div>
        <div>
          <label class="label">Alternatives (max ${MAX_ALTERNATIVES})</label>
          ${[0, 1, 2].map(i => {
            const val = (p.alternatives || []).map(a => a.alternative_our_product_id)[i] || "";
            const opts = altOptions.map(x => `<option value="${ctx.esc(x.our_product_id)}" ${val === x.our_product_id ? "selected" : ""}>${ctx.esc(x.our_product_id)}</option>`).join("");
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
                  ${addons.map(a => `<option value="${ctx.esc(a.our_product_id)}" ${String(l.addon_our_product_id).toLowerCase() === String(a.our_product_id).toLowerCase() ? "selected" : ""}>${ctx.esc(a.our_product_id)}${a.name && a.name !== a.our_product_id ? ` — ${ctx.esc(a.name)}` : ""}</option>`).join("")}
                </select>
                <input class="input ce-addon-qty" type="number" min="1" style="width:72px;" value="${l.quantity}" />
              </div>`).join("")}
          </div>
          <button type="button" class="btn btn-secondary btn-sm" onclick="Catalog.addEditAddonRow()">+ Add link</button>
          ${addonWarn}
        </div>
      </div>`;

    document.getElementById("catalog-edit-footer").innerHTML = `
      <button type="button" class="btn btn-secondary" onclick="Catalog.closeEdit()">Cancel</button>
      <button type="button" class="btn btn-primary" style="flex:1;" onclick="Catalog.saveEdit()">Save Changes</button>`;
    document.getElementById("catalog-edit-modal")?.classList.remove("hidden");
    } catch (e) {
      ctx.toast(e.message || "Could not open editor", "error");
    } finally {
      ctx.hideLoading?.();
    }
  }

  function addEditAddonRow() {
    const wrap = document.getElementById("ce-addon-links");
    if (!wrap) return;
    const div = document.createElement("div");
    div.style.cssText = "display:flex;gap:8px;margin-bottom:8px;";
    div.innerHTML = `
      <select class="input ce-addon-id" style="flex:1;"><option value="">—</option>
        ${addons.map(a => `<option value="${ctx.esc(a.our_product_id)}">${ctx.esc(a.our_product_id)}${a.name && a.name !== a.our_product_id ? ` — ${ctx.esc(a.name)}` : ""}</option>`).join("")}
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

    const ourId = document.getElementById("ce-our_product_id").value.trim();
    if (!ourId) return ctx.toast("Our Product ID required", "error");

    let imageKeys = (document.getElementById("ce-image_keys")?.value || "")
      .split(",").map(s => s.trim()).filter(Boolean);
    const fileEl = document.getElementById("ce-image");
    const file = fileEl?.files?.[0];
    if (file) {
      try {
        const vendorId = Number(document.getElementById("ce-vendor_id")?.value || 0);
        const nextIndex = Math.max(1, imageKeys.length + 1);
        const result = await uploadImage(vendorId, ourId, nextIndex, file);
        // This control only replaces the cover photo — it used to wipe the whole
        // imageKeys array down to this one upload, silently deleting every other
        // photo a multi-image product had (e.g. from the bulk-create wizard).
        if (result?.key) imageKeys[0] = result.key;
      } catch (e) {
        return ctx.toast("Image upload failed: " + e.message, "error");
      }
    }

    // buying_price input is disabled+masked ("Hidden — no cost access") for staff
    // without costs.read (see openEdit) — a browser can't hold "—" in a type=number
    // field so it silently resets to "" and Number("") is 0, which used to zero out
    // the real cost on every single save regardless of what the user meant to edit.
    // Backend uses exclude_unset=True, so simply omitting the key entirely (not
    // sending 0/null) leaves the existing buying_price completely untouched.
    const bpEl = document.getElementById("ce-buying_price");
    const body = {
      our_product_id: ourId,
      vendor_product_id: document.getElementById("ce-vendor_product_id").value.trim(),
      category: document.getElementById("ce-category").value || null,
      second_category: document.getElementById("ce-second_category").value || null,
      marking: document.getElementById("ce-marking")?.value.trim() || null,
      year_group: ctx.isAdmin?.()
        ? (document.getElementById("ce-year_group")?.value || null)
        : undefined,
      selling_price: document.getElementById("ce-selling_price").value
        ? Number(document.getElementById("ce-selling_price").value) : null,
      image_keys: imageKeys,
      alternative_our_product_ids: altIds,
      addon_links: addonLinks,
    };
    if (!bpEl?.disabled) body.buying_price = Number(bpEl.value);
    try {
      await ctx.api(`/catalog/products/${editingId}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      const id = editingId;
      const ret = editReturnTo === "stock" ? "stock"
        : editReturnTo === "addons" ? "addons"
        : editReturnTo === "alts" ? "alts"
        : "catalog";
      closeEdit();
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/stock");
      ctx.invalidateCache?.("/catalog");
      ctx.invalidateCache?.("/vendor-orders");
      ctx.toast("Product updated", "success");
      if (typeof Products !== "undefined" && Products.openProductDetail) {
        await Products.openProductDetail(id, ret);
        Products.refreshHub?.();
      } else if (ret === "stock") {
        await load();
        Stock.openDetail(id);
      } else {
        await load();
        openDetail(id);
      }
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

