  function cityOptionLabel(c) {
    const route = c.route_name ? ` (${c.route_name})` : "";
    return `${c.name || "City"}${route}`;
  }

  function cityRouteHint(cityId) {
    const cities = ctx.getCities();
    const city = cities.find(c => c.id == cityId);
    if (!city) return `<p class="people-field-hint">City is for this supplier’s location. Routes are for customer delivery.</p>`;
    return `<p class="people-field-hint">Location: <strong>${ctx.esc(city.name)}</strong>${
      city.route_name ? ` · route area <strong>${ctx.esc(city.route_name)}</strong>` : ""
    }. Routes are for customer delivery.</p>`;
  }

  function normalizePhone(raw) {
    return String(raw || "").replace(/\D/g, "");
  }

  function normalizeGst(raw) {
    return String(raw || "").replace(/\s+/g, "").toUpperCase();
  }

  function validateGst(raw) {
    const gst = normalizeGst(raw);
    if (!gst) return { ok: true, value: null };
    const re = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
    if (!re.test(gst)) return { ok: false, value: gst };
    return { ok: true, value: gst };
  }

  function validateSecondaryPhone(raw) {
    const p = normalizePhone(raw);
    if (!p) return { ok: true, value: null };
    if (p.length !== 10) return { ok: false, value: p };
    return { ok: true, value: p };
  }

  function openWizard() {
    wizardStep = 1;
    wizardForm = {};
    document.getElementById("vendor-wizard").classList.remove("hidden");
    renderWizard();
  }

  function closeWizard() {
    document.getElementById("vendor-wizard").classList.add("hidden");
  }

  function renderWizard() {
    const cities = ctx.getCities();
    const stepsEl = document.getElementById("vendor-wizard-steps");
    if (stepsEl) { stepsEl.innerHTML = ""; stepsEl.classList.add("hidden"); }

    const body = document.getElementById("vendor-wizard-body");
    const footer = document.getElementById("vendor-wizard-footer");
    const today = new Date().toISOString().slice(0, 10);

    if (wizardStep === 1) {
      body.innerHTML = `<div class="create-form">
        <div><label class="label">Business name *</label><input id="vw-business_name" class="input" value="${ctx.esc(wizardForm.business_name || "")}" autofocus /></div>
        <div><label class="label">Phone *</label><input id="vw-phone" class="input" type="tel" maxlength="10" value="${ctx.esc(wizardForm.phone || "")}" /></div>
        <div class="create-field-row">
          <div><label class="label">Opening (₹)</label><input id="vw-opening_due" class="input" type="number" min="0" step="0.01" value="${ctx.esc(wizardForm.opening_balance_due || "")}" /></div>
          <div><label class="label">As on</label><input id="vw-opening_as_on" class="input" type="date" value="${ctx.esc(wizardForm.opening_balance_as_on || today)}" /></div>
        </div>
        <details class="create-details">
          <summary>More</summary>
          <div class="create-details-body">
            <div><label class="label">Person</label><input id="vw-person_name" class="input" value="${ctx.esc(wizardForm.person_name || "")}" /></div>
            <div class="create-field-row">
              <div><label class="label">Secondary phone</label><input id="vw-secondary_phone" class="input" type="tel" maxlength="10" value="${ctx.esc(wizardForm.secondary_phone || "")}" /></div>
              <div><label class="label">Alias</label><input id="vw-alias" class="input" value="${ctx.esc(wizardForm.alias || "")}" /></div>
            </div>
            <div><label class="label">City</label>
              <select id="vw-city_id" class="input" onchange="Vendors.onWizardCityChange(this.value)">
                <option value="">— Optional —</option>
                ${cities.map(c => `<option value="${c.id}" ${wizardForm.city_id == c.id ? "selected" : ""}>${ctx.esc(cityOptionLabel(c))}</option>`).join("")}
              </select>
              <div id="vw-city-hint">${cityRouteHint(wizardForm.city_id)}</div>
            </div>
            <div><label class="label">GST</label><input id="vw-gst_number" class="input" value="${ctx.esc(wizardForm.gst_number || "")}" maxlength="15" style="text-transform:uppercase;" /></div>
            <div><label class="label">Address</label><textarea id="vw-address" class="input" rows="2">${ctx.esc(wizardForm.address || "")}</textarea></div>
          </div>
        </details>
      </div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="Vendors.closeWizard()">Cancel</button>
        <button class="btn btn-primary" style="flex:1;" id="vendor-create-btn" onclick="Vendors.create()">Create</button>`;
    } else {
      const id = wizardForm._result?.id;
      body.innerHTML = `<div style="text-align:center;padding:20px 0 8px;">
        <div class="success-icon">✓</div><h3 style="margin:0 0 8px;">Vendor created</h3>
        <p style="color:var(--muted);margin:0;">${ctx.esc(wizardForm._result?.business_name || "")}</p>
      </div>`;
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="Vendors.openWizard()">+ Another</button>
        ${id ? `<button class="btn btn-secondary" onclick="Vendors.finishOpen(${id})">Open</button>
        <button class="btn btn-secondary" onclick="Vendors.finishAddProducts(${id})">Add products</button>
        <button class="btn btn-primary" style="flex:1;" onclick="Vendors.finishPlaceOrder(${id})">Place order →</button>`
          : `<button class="btn btn-primary" style="flex:1;" onclick="Vendors.closeWizard()">Done</button>`}`;
    }
  }

  function onWizardCityChange(val) {
    wizardForm.city_id = parseCityId(val);
    const hint = document.getElementById("vw-city-hint");
    if (hint) hint.innerHTML = cityRouteHint(wizardForm.city_id);
  }

  function collectWizard() {
    ["business_name","phone","person_name","secondary_phone","alias","gst_number","address"].forEach(k => {
      const el = document.getElementById(`vw-${k}`);
      if (el) wizardForm[k] = el.value.trim();
    });
    const cityEl = document.getElementById("vw-city_id");
    if (cityEl) wizardForm.city_id = parseCityId(cityEl.value);
    const od = document.getElementById("vw-opening_due");
    if (od) wizardForm.opening_balance_due = od.value.trim();
    const oa = document.getElementById("vw-opening_as_on");
    if (oa) wizardForm.opening_balance_as_on = oa.value;
  }

  function wizardBack() {
    collectWizard();
    wizardStep = 1;
    renderWizard();
  }

  function wizardNext() {
    create();
  }

  async function create() {
    collectWizard();
    if (!wizardForm.business_name) return ctx.toast("Business name required", "error");
    const phone = normalizePhone(wizardForm.phone);
    if (phone.length !== 10) return ctx.toast("Phone must be 10 digits", "error");
    wizardForm.phone = phone;
    const cityId = parseCityId(wizardForm.city_id);
    const sec = validateSecondaryPhone(wizardForm.secondary_phone);
    if (!sec.ok) return ctx.toast("Secondary phone must be 10 digits or blank", "error");
    const gst = validateGst(wizardForm.gst_number);
    if (!gst.ok) return ctx.toast("GST looks invalid — use 15-char GSTIN or leave blank", "error");
    const btn = document.getElementById("vendor-create-btn");
    if (btn) btn.disabled = true;
    try {
      const openingDue = wizardForm.opening_balance_due ? parseFloat(wizardForm.opening_balance_due) : 0;
      const result = await ctx.api("/vendors", { method: "POST", body: JSON.stringify({
        business_name: wizardForm.business_name,
        phone: wizardForm.phone,
        city_id: cityId || null,
        person_name: wizardForm.person_name || null,
        secondary_phone: sec.value,
        alias: wizardForm.alias || null,
        gst_number: gst.value,
        address: wizardForm.address || null,
        opening_balance_due: openingDue > 0 ? openingDue : null,
        opening_balance_as_on: openingDue > 0 ? (wizardForm.opening_balance_as_on || null) : null,
      })});
      wizardForm._result = result;
      wizardStep = 2;
      renderWizard();
      ctx.invalidateCache?.("/vendors");
      ctx.invalidateCache?.("/stats");
      ctx.invalidateCache?.("/catalog/vendors");
      // Soft refresh list — do not block UI on full refreshAll (spinner stuck).
      try {
        vendors = await ctx.api("/vendors", {}, 0);
        if (ctx.setVendors) ctx.setVendors(vendors);
        renderTable();
      } catch (_) {}
      ctx.toast("Vendor created", "success");
    } catch (e) {
      ctx.toast(e.message, "error");
    } finally {
      if (btn) btn.disabled = false;
      ctx.hideLoading?.();
    }
  }

  function finishOpen(id) {
    closeWizard();
    openDetail(id);
  }

  function finishPlaceOrder(id) {
    closeWizard();
    // Force fresh vendor list so the new vendor is visible in the order wizard.
    ctx.invalidateCache?.("/vendors");
    if (typeof VendorOrders !== "undefined" && VendorOrders.primeVendors) {
      VendorOrders.primeVendors(null);
    }
    placeOrder(id);
  }

  function finishAddProducts(id) {
    closeWizard();
    App.showView("products");
    if (typeof Products !== "undefined" && Products.setMainTab) Products.setMainTab("catalog");
    if (typeof Catalog !== "undefined" && Catalog.openWizardForVendor) Catalog.openWizardForVendor(id);
    else if (typeof Catalog !== "undefined") Catalog.openWizard();
  }

  async function openEdit(id) {
    const v = await ctx.api(`/vendors/${id}`);
    editingId = id;
    const cities = ctx.getCities();
    const billing = v.billing_terms || {
      billing_pct: 100,
      additional_charge: 100,
      additional_charge_label: "Additional charge",
      discount_pct: 0,
      gst_included: true,
      gst_rate_pct: 18,
      cash_discount_equals_gst: false,
      billing_notes: "",
    };
    document.getElementById("vendor-edit-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Business Name *</label><input id="ve-business_name" class="input" value="${ctx.esc(v.business_name)}" /></div>
        <div><label class="label">Primary Phone *</label><input id="ve-phone" class="input" type="tel" maxlength="10" value="${ctx.esc(v.phone)}" /></div>
        <div><label class="label">City</label>
          <select id="ve-city_id" class="input" onchange="Vendors.onEditCityChange(this.value)">
            <option value="">— Optional —</option>
            ${cities.map(c => `<option value="${c.id}" ${v.city_id == c.id ? "selected" : ""}>${ctx.esc(cityOptionLabel(c))}</option>`).join("")}
          </select>
          <div id="ve-city-hint">${cityRouteHint(v.city_id)}</div>
        </div>
        <div><label class="label">Contact person</label><input id="ve-person_name" class="input" value="${ctx.esc(v.person_name || "")}" /></div>
        <div><label class="label">Secondary Phone</label><input id="ve-secondary_phone" class="input" type="tel" maxlength="10" value="${ctx.esc(v.secondary_phone || "")}" placeholder="10 digits or blank" /></div>
        <div><label class="label">Alias / search name</label><input id="ve-alias" class="input" value="${ctx.esc(v.alias || "")}" /></div>
        <div><label class="label">GST Number</label><input id="ve-gst_number" class="input" value="${ctx.esc(v.gst_number || "")}" placeholder="22AAAAA0000A1Z5" maxlength="15" style="text-transform:uppercase;" /></div>
        <div><label class="label">Address</label><textarea id="ve-address" class="input" rows="2">${ctx.esc(v.address || "")}</textarea></div>
        ${ctx.isAdmin?.() ? `
          <div style="border-top:1px solid var(--line);padding-top:16px;">
            <div style="font-weight:600;margin-bottom:12px;">Billing terms (admin only)</div>
            <div style="display:grid;gap:16px;">
              <div class="create-field-row">
                <div><label class="label">Billing %</label><input id="ve-billing_pct" class="input" type="number" min="0.01" max="100" step="0.01" value="${ctx.esc(String(billing.billing_pct ?? 100))}" /></div>
                <div><label class="label">Additional charge</label><input id="ve-additional_charge" class="input" type="number" min="0" step="0.01" value="${ctx.esc(String(billing.additional_charge ?? 100))}" /></div>
              </div>
              <div><label class="label">Additional charge label</label><input id="ve-additional_charge_label" class="input" maxlength="50" value="${ctx.esc(billing.additional_charge_label || "Additional charge")}" /></div>
              <div class="create-field-row">
                <div><label class="label">Discount %</label><input id="ve-discount_pct" class="input" type="number" min="0" max="100" step="0.01" value="${ctx.esc(String(billing.discount_pct ?? 0))}" /></div>
                <div><label class="label">GST rate %</label><input id="ve-gst_rate_pct" class="input" type="number" min="0" max="100" step="0.01" value="${ctx.esc(String(billing.gst_rate_pct ?? 18))}" /></div>
              </div>
              <label style="display:flex;align-items:center;gap:8px;"><input id="ve-gst_included" type="checkbox" ${billing.gst_included !== false ? "checked" : ""} /> GST included</label>
              <label style="display:flex;align-items:center;gap:8px;"><input id="ve-cash_discount_equals_gst" type="checkbox" ${billing.cash_discount_equals_gst ? "checked" : ""} /> Cash discount = GST (tax-saving split billing)</label>
              <div style="font-size:12px;color:var(--muted);margin-top:-6px;">When on, the cash (untaxed) portion is reduced by the GST amount charged on the paper bill — so paper + cash together still equal the real item value, no markup for tax. Only matters when Billing % is below 100.</div>
              <div><label class="label">Billing notes</label><textarea id="ve-billing_notes" class="input" rows="3">${ctx.esc(billing.billing_notes || "")}</textarea></div>
            </div>
          </div>
        ` : ""}
      </div>`;
    document.getElementById("vendor-edit-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="Vendors.closeEdit()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" id="vendor-save-btn" onclick="Vendors.save()">Save Changes</button>`;
    document.getElementById("vendor-edit-modal").classList.remove("hidden");
  }

  function onEditCityChange(val) {
    const hint = document.getElementById("ve-city-hint");
    if (hint) hint.innerHTML = cityRouteHint(parseCityId(val));
  }

  function closeEdit() {
    document.getElementById("vendor-edit-modal").classList.add("hidden");
    editingId = null;
  }

  async function save() {
    if (!editingId) return;
    const business = document.getElementById("ve-business_name").value.trim();
    const phone = normalizePhone(document.getElementById("ve-phone").value);
    const cityId = parseCityId(document.getElementById("ve-city_id").value);
    if (!business) return ctx.toast("Business name required", "error");
    if (phone.length !== 10) return ctx.toast("Phone must be 10 digits", "error");
    const sec = validateSecondaryPhone(document.getElementById("ve-secondary_phone").value);
    if (!sec.ok) return ctx.toast("Secondary phone must be 10 digits or blank", "error");
    const gst = validateGst(document.getElementById("ve-gst_number").value);
    if (!gst.ok) return ctx.toast("GST looks invalid — use 15-char GSTIN or leave blank", "error");
    const billingPct = ctx.isAdmin?.() ? parseFloat(document.getElementById("ve-billing_pct").value) : null;
    const additionalCharge = ctx.isAdmin?.() ? parseFloat(document.getElementById("ve-additional_charge").value) : null;
    const additionalChargeLabel = ctx.isAdmin?.() ? document.getElementById("ve-additional_charge_label").value.trim() : null;
    const discountPct = ctx.isAdmin?.() ? parseFloat(document.getElementById("ve-discount_pct").value) : null;
    const gstRatePct = ctx.isAdmin?.() ? parseFloat(document.getElementById("ve-gst_rate_pct").value) : null;
    const gstIncluded = ctx.isAdmin?.() ? document.getElementById("ve-gst_included").checked : null;
    const cashDiscountEqualsGst = ctx.isAdmin?.() ? document.getElementById("ve-cash_discount_equals_gst").checked : null;
    const billingNotes = ctx.isAdmin?.() ? (document.getElementById("ve-billing_notes").value.trim() || null) : null;
    if (ctx.isAdmin?.()) {
      if (!Number.isFinite(billingPct) || billingPct <= 0 || billingPct > 100) return ctx.toast("Billing % must be between 0.01 and 100", "error");
      if (!Number.isFinite(additionalCharge) || additionalCharge < 0) return ctx.toast("Additional charge must be 0 or more", "error");
      if (!additionalChargeLabel) return ctx.toast("Additional charge label required", "error");
      if (additionalChargeLabel.length > 50) return ctx.toast("Additional charge label too long", "error");
      if (!Number.isFinite(discountPct) || discountPct < 0 || discountPct > 100) return ctx.toast("Discount % must be between 0 and 100", "error");
      if (!Number.isFinite(gstRatePct) || gstRatePct < 0 || gstRatePct > 100) return ctx.toast("GST rate % must be between 0 and 100", "error");
    }
    const btn = document.getElementById("vendor-save-btn");
    if (btn) btn.disabled = true;
    ctx.showLoading?.();
    try {
      await ctx.api(`/vendors/${editingId}`, { method: "PATCH", body: JSON.stringify({
        business_name: business,
        phone,
        city_id: cityId || null,
        person_name: document.getElementById("ve-person_name").value.trim() || null,
        secondary_phone: sec.value,
        alias: document.getElementById("ve-alias").value.trim() || null,
        gst_number: gst.value,
        address: document.getElementById("ve-address").value.trim() || null,
      })});
      if (ctx.isAdmin?.()) {
        await ctx.api(`/vendors/${editingId}/billing-terms`, { method: "PATCH", body: JSON.stringify({
          billing_pct: billingPct,
          additional_charge: additionalCharge,
          additional_charge_label: additionalChargeLabel,
          discount_pct: discountPct,
          gst_included: gstIncluded,
          gst_rate_pct: gstRatePct,
          cash_discount_equals_gst: cashDiscountEqualsGst,
          billing_notes: billingNotes,
        })});
      }
      const id = editingId;
      closeEdit();
      App.closeDetail();
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/stock");
      ctx.invalidateCache?.("/catalog");
      ctx.invalidateCache?.("/vendor-orders");
      await load();
      ctx.toast("Vendor updated", "success");
      openDetail(id);
    } catch (e) {
      ctx.toast(e.message, "error");
    } finally {
      if (btn) btn.disabled = false;
      ctx.hideLoading?.();
    }
  }

  async function deleteVendor(id) {
    if (!confirm("Move vendor to recycle bin?")) return;
    try {
      await ctx.api(`/vendors/${id}`, { method: "DELETE" });
      App.closeDetail();
      await load();
      ctx.invalidateCache?.("/vendors");
      ctx.invalidateCache?.("/stats");
      if (ctx.refreshStats) await ctx.refreshStats();
      ctx.toast("Vendor moved to recycle bin", "success");
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  /** Place order first (then receive later). */
  function placeOrder(vendorId) {
    App.closeDetail();
    App.showView("buying");
    VendorOrders.openWizard?.(vendorId);
  }

  /** Goods already here — offline receive for this vendor. */
  function stockIn(vendorId) {
    App.closeDetail();
    Stock.openOfflineForVendor(vendorId);
  }

  /** Legacy: create menu with both paths. */
  function createOrder(vendorId) {
    App.closeDetail();
    App.showView("buying");
    VendorOrders.showCreateMenuFromVendor(vendorId);
  }

  function receiveGoods(vendorId) {
    App.closeDetail();
    Stock.openReceiveForVendor(vendorId);
  }

  function openMoney(vendorId) {
    App.closeDetail();
    App.showView("money");
    Finance.openVendorAp?.(vendorId);
  }

  /** Open this vendor’s order screen (past stages). */
  function openBuying(vendorId) {
    App.closeDetail();
    App.showView("buying");
    VendorOrders.setBucket?.("placed");
    VendorOrders.openDetail(0, "placed", vendorId).then?.(() => App.updateGlobalBack?.());
    App.updateGlobalBack?.();
  }

