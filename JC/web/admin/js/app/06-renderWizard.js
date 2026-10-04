  function renderWizard() {
    const steps = document.getElementById("wizard-steps");
    if (steps) { steps.innerHTML = ""; steps.classList.add("hidden"); }
    const body = document.getElementById("wizard-body");
    const footer = document.getElementById("wizard-footer");
    const today = new Date().toISOString().slice(0, 10);

    if (wizardStep === 1) {
      body.innerHTML = `<div class="create-form">
        <div><label class="label">Business name *</label><input id="wf-business_name" class="input" value="${esc(wizardForm.business_name || "")}" autofocus /></div>
        <div class="create-field-row">
          <div><label class="label">Phone *</label><input id="wf-phone" class="input" type="tel" maxlength="10" value="${esc(wizardForm.phone || "")}" /></div>
          <div><label class="label">City *</label>
            <select id="wf-city_id" class="input">
              <option value="">— Select —</option>
              ${cities.map(c => `<option value="${c.id}" ${wizardForm.city_id == c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}
            </select>
          </div>
        </div>
        <div class="create-field-row">
          <div>
            <label class="label">Payment type *</label>
            <div style="display:flex;gap:8px;margin-top:4px;">
              <label id="wf-label-cash" style="display:flex;align-items:center;gap:6px;font-size:14px;cursor:pointer;padding:8px 14px;border:1px solid var(--border);border-radius:8px;flex:1;justify-content:center;${(wizardForm.payment_type||'CREDIT')==='CASH'?'background:#fef3c7;border-color:#f59e0b;font-weight:600;':''}">
                <input type="radio" name="wf-payment_type" value="CASH" ${(wizardForm.payment_type||'CREDIT')==='CASH'?'checked':''} onchange="App.onWizardPaymentTypeChange('CASH')" /> CASH
              </label>
              <label id="wf-label-credit" style="display:flex;align-items:center;gap:6px;font-size:14px;cursor:pointer;padding:8px 14px;border:1px solid var(--border);border-radius:8px;flex:1;justify-content:center;${(wizardForm.payment_type||'CREDIT')==='CREDIT'?'background:#eff6ff;border-color:#3b82f6;font-weight:600;':''}">
                <input type="radio" name="wf-payment_type" value="CREDIT" ${(wizardForm.payment_type||'CREDIT')==='CREDIT'?'checked':''} onchange="App.onWizardPaymentTypeChange('CREDIT')" /> CREDIT
              </label>
            </div>
          </div>
          <div id="wf-credit-limit-wrap" style="${(wizardForm.payment_type||'CREDIT')==='CASH'?'display:none':''}">
            <label class="label">Credit limit (₹)</label>
            <input id="wf-credit_limit" class="input" type="number" min="0" step="0.01" value="${esc(wizardForm.credit_limit || "")}" />
          </div>
        </div>
        <div class="create-field-row">
          <div><label class="label">Opening (₹)</label><input id="wf-opening_due" class="input" type="number" min="0" step="0.01" value="${esc(wizardForm.opening_balance_due || "")}" /></div>
          <div><label class="label">As on</label><input id="wf-opening_as_on" class="input" type="date" value="${esc(wizardForm.opening_balance_as_on || today)}" /></div>
        </div>
        <details class="create-details">
          <summary>More</summary>
          <div class="create-details-body">
            <div><label class="label">Person</label><input id="wf-person_name" class="input" value="${esc(wizardForm.person_name || "")}" /></div>
            <div class="create-field-row">
              <div><label class="label">Secondary phone</label><input id="wf-secondary_phone" class="input" type="tel" maxlength="10" value="${esc(wizardForm.secondary_phone || "")}" /></div>
              <div><label class="label">Alias</label><input id="wf-alias" class="input" value="${esc(wizardForm.alias || "")}" /></div>
            </div>
            <div><label class="label">GST</label><input id="wf-gst_number" class="input" value="${esc(wizardForm.gst_number || "")}" maxlength="15" style="text-transform:uppercase;" /></div>
            <div><label class="label">Address</label><textarea id="wf-address" class="input" rows="2">${esc(wizardForm.address || "")}</textarea></div>
            <div class="create-field-row">
              <div><label class="label">Marking 1</label><input id="wf-marker_1" class="input" maxlength="100" placeholder="e.g. Genuine party" value="${esc(wizardForm.marker_1 || "")}" /></div>
              <div><label class="label">Marking 2</label><input id="wf-marker_2" class="input" maxlength="100" placeholder="e.g. Only cash" value="${esc(wizardForm.marker_2 || "")}" /></div>
            </div>
            <div><label class="label">Notes</label><textarea id="wf-additional_details" class="input" rows="2">${esc(wizardForm.additional_details || "")}</textarea></div>
          </div>
        </details>
      </div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="App.closeWizard()">Cancel</button>
        <button class="btn btn-primary" style="flex:1;" id="wizard-create-btn" onclick="App.createCustomer()">Create</button>`;
    } else {
      const id = wizardForm._result?.id;
      const waOk = !!wizardForm._result?.whatsapp_sent;
      body.innerHTML = `<div style="text-align:center;padding:20px 0 8px;">
        <div class="success-icon">✓</div><h3 style="margin:0 0 8px;">Customer created</h3>
        <p style="color:var(--muted);margin:0 0 16px;">${esc(wizardForm._result?.business_name || "")}</p>
        <div class="review-grid" style="text-align:left;">
          ${reviewRow("Phone", wizardForm._result?.phone)}
          ${reviewRow("Password", wizardForm._result?.portal_password || "— (check WhatsApp)")}
          ${reviewRow("WhatsApp", waOk ? "Sent" : ("Not sent — " + (wizardForm._result?.whatsapp_error || "try again")))}
        </div>
        ${!waOk && id ? `<p class="people-field-hint" style="margin:12px 0 0;">Customer saved. Retry WhatsApp issues a new password.</p>` : ""}
      </div>`;
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="App.openCustomerWizard()">+ Another</button>
        ${!waOk && id ? `<button class="btn btn-secondary" onclick="App.resendWhatsApp(${id})">Retry WhatsApp</button>` : ""}
        ${id ? `<button class="btn btn-secondary" onclick="App.finishCustomerOpen(${id})">Open profile</button>
        <button class="btn btn-primary" style="flex:1;" onclick="App.finishCustomerPlace(${id})">Place order →</button>`
          : `<button class="btn btn-primary" style="flex:1;" onclick="App.closeWizard();App.showPeopleTab('customers')">View Customers</button>`}`;
    }
  }

  function onCustomerWizardCityChange(val) {
    wizardForm.city_id = val ? parseInt(val, 10) : null;
    const hint = document.getElementById("wf-city-hint");
    if (hint) hint.innerHTML = customerCityHint(wizardForm.city_id);
  }

  function onWizardPaymentTypeChange(val) {
    wizardForm.payment_type = val;
    // Show/hide credit limit — do NOT re-render the form (would wipe user input)
    const wrap = document.getElementById("wf-credit-limit-wrap");
    if (wrap) wrap.style.display = val === "CASH" ? "none" : "";
    if (val === "CASH") {
      const el = document.getElementById("wf-credit_limit");
      if (el) el.value = "";
      wizardForm.credit_limit = "";
    }
    // Update label highlight styles in place
    const cashLabel = document.getElementById("wf-label-cash");
    const creditLabel = document.getElementById("wf-label-credit");
    if (cashLabel) {
      cashLabel.style.background = val === "CASH" ? "#fef3c7" : "";
      cashLabel.style.borderColor = val === "CASH" ? "#f59e0b" : "";
      cashLabel.style.fontWeight = val === "CASH" ? "600" : "";
    }
    if (creditLabel) {
      creditLabel.style.background = val === "CREDIT" ? "#eff6ff" : "";
      creditLabel.style.borderColor = val === "CREDIT" ? "#3b82f6" : "";
      creditLabel.style.fontWeight = val === "CREDIT" ? "600" : "";
    }
  }

  function finishCustomerOpen(id) {
    closeWizard();
    openCustomerDetail(id);
  }

  function finishCustomerPlace(id) {
    closeWizard();
    createCustomerOrder(id);
  }

  function reviewRow(label, val, rawHtml = false) {
    const empty = val == null || val === "";
    if (empty && !rawHtml) {
      return `<div class="review-row"><span class="review-label">${label}</span><span class="review-value review-empty">—</span></div>`;
    }
    const content = rawHtml ? val : esc(String(val));
    return `<div class="review-row"><span class="review-label">${label}</span><span class="review-value">${content}</span></div>`;
  }

  // Vendor bills using their own product id, we track ours — show both so nothing gets
  // mismatched. Returns a plain (unescaped) string; wrap with esc()/ctx.esc() at the call site.
  function productIdLabel(p) {
    const our = p?.our_product_id || "";
    const year = p?.year_group ? ` [${p.year_group}]` : "";
    const vid = p?.vendor_product_id;
    return vid ? `${our}${year} / (${vid})` : `${our}${year}`;
  }

  function changeHistoryTable(history) {
    if (!history?.length) return "";
    const rows = [];
    history.forEach(h => {
      const summary = h.change_summary || "Updated";
      const parts = summary === "updated" ? ["Updated"] : summary.split("; ").map(p => p.trim()).filter(Boolean);
      parts.forEach((part, i) => {
        const m = part.match(/^([^:]+):\s*(.*?)\s*→\s*(.*)$/);
        rows.push({
          field: m ? m[1].trim().replace(/_/g, " ") : "—",
          from: m ? m[2].trim() : "—",
          to: m ? m[3].trim() : part,
          at: h.valid_from,
          showDate: i === 0,
        });
      });
    });
    return `<div class="detail-section"><h4>Change History</h4>
      <table class="data history-table"><thead><tr>
        <th>Field</th><th>Previous</th><th>New</th><th>Changed</th>
      </tr></thead><tbody>${rows.map(r => `<tr>
        <td><span class="history-field">${esc(r.field)}</span></td>
        <td class="history-old">${esc(r.from)}</td>
        <td class="history-new"><strong>${esc(r.to)}</strong></td>
        <td class="history-date">${r.showDate ? fmtDate(r.at) : ""}</td>
      </tr>`).join("")}</tbody></table></div>`;
  }

  async function uploadImage(vendorId, ourProductId, file, imageIndex = 1, yearGroup = null) {
    const fd = new FormData();
    fd.append("vendor_id", String(vendorId));
    fd.append("our_product_id", ourProductId);
    fd.append("image_index", String(imageIndex));
    if (yearGroup) fd.append("year_group", yearGroup);
    fd.append("file", file);
    const h = {};
    if (authMode === "admin" && adminKey) h["X-Admin-Key"] = adminKey;
    else if (authMode === "staff" && staffToken) h["Authorization"] = `Bearer ${staffToken}`;
    let res;
    try {
      res = await fetch(`${API}/catalog/upload-image`, { method: "POST", headers: h, body: fd });
    } catch (e) {
      throw new Error("Network error uploading image — is the backend running?");
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const msg = typeof err.detail === "string" ? err.detail : `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return res.json();
  }

  function collectWizard() {
    ["business_name","person_name","phone","secondary_phone","alias","gst_number","address","additional_details","credit_limit","marker_1","marker_2"].forEach(k => {
      const el = document.getElementById(`wf-${k}`); if (el) wizardForm[k] = el.value.trim();
    });
    const cityEl = document.getElementById("wf-city_id");
    if (cityEl) wizardForm.city_id = cityEl.value ? parseInt(cityEl.value) : null;
    const ov = document.getElementById("wf-credit_override");
    if (ov) wizardForm.credit_override = ov.checked;
    const ptEl = document.querySelector('input[name="wf-payment_type"]:checked');
    if (ptEl) wizardForm.payment_type = ptEl.value;
    const od = document.getElementById("wf-opening_due");
    if (od) wizardForm.opening_balance_due = od.value.trim();
    const oa = document.getElementById("wf-opening_as_on");
    if (oa) wizardForm.opening_balance_as_on = oa.value;
  }

  function wizardBack() { collectWizard(); wizardStep = 1; renderWizard(); }
  function wizardNext() { createCustomer(); }

  async function createCustomer() {
    collectWizard();
    if (!wizardForm.business_name) return toast("Business name required", "error");
    const phone = normalizePhoneDigits(wizardForm.phone);
    if (phone.length !== 10) return toast("Phone must be 10 digits", "error");
    wizardForm.phone = phone;
    if (!wizardForm.city_id) return toast("Please select a city", "error");
    const sec = validateOptionalPhone(wizardForm.secondary_phone);
    if (!sec.ok) return toast("Secondary phone must be 10 digits or blank", "error");
    const gst = validateGstin(wizardForm.gst_number);
    if (!gst.ok) return toast("GST looks invalid — use 15-char GSTIN or leave blank", "error");
    const btn = document.getElementById("wizard-create-btn");
    if (btn) btn.disabled = true;
    try {
      const openingDue = wizardForm.opening_balance_due ? parseFloat(wizardForm.opening_balance_due) : 0;
      const result = await api("/customers", { method: "POST", body: JSON.stringify({
        business_name: wizardForm.business_name, person_name: wizardForm.person_name || null,
        phone: wizardForm.phone, secondary_phone: sec.value,
        alias: wizardForm.alias || null, city_id: wizardForm.city_id,
        gst_number: gst.value, address: wizardForm.address || null,
        marker_1: wizardForm.marker_1 || null, marker_2: wizardForm.marker_2 || null,
        additional_details: wizardForm.additional_details || null,
        payment_type: wizardForm.payment_type || "CREDIT",
        credit_limit: (wizardForm.payment_type === "CASH") ? 0 : (wizardForm.credit_limit ? parseFloat(wizardForm.credit_limit) : null),
        credit_override: !!wizardForm.credit_override,
        opening_balance_due: openingDue > 0 ? openingDue : null,
        opening_balance_as_on: openingDue > 0 ? (wizardForm.opening_balance_as_on || null) : null,
      })});
      wizardForm._result = result; wizardStep = 2; renderWizard();
      invalidateCache("/customers");
      invalidateCache("/stats");
      await refreshAll();
      if (peopleTab === "customers") await loadCustomers();
      toast("Customer created", "success");
      if (!result.whatsapp_sent) toast(result.whatsapp_error || "WhatsApp not sent — use Retry", "error");
    } catch (e) { toast(e.message, "error"); if (btn) btn.disabled = false; }
  }

  function closeModal() { document.getElementById("modal").classList.add("hidden"); }

  async function init() {
    authMode = sessionStorage.getItem("jc_auth_mode") || "";
    adminKey = sessionStorage.getItem("jc_admin_key") || "";
    staffToken = sessionStorage.getItem("jc_staff_token") || "";
    try { staffUser = JSON.parse(sessionStorage.getItem("jc_staff_user") || "null"); } catch (_) { staffUser = null; }
    permissions = new Set((staffUser && staffUser.permissions) || []);
    setLoginTab("admin");
    const logoutMsg = sessionStorage.getItem("jc_logout_msg");
    if (logoutMsg) {
      sessionStorage.removeItem("jc_logout_msg");
      showLoginShell(logoutMsg);
    }
    TableUtils.register("routes", renderRoutesTable);
    TableUtils.register("cities", renderCitiesTable);
    TableUtils.register("customers", renderCustomersTable);
    TableUtils.register("recycle", renderRecycleTable);
    if ((authMode === "admin" && adminKey) || (authMode === "staff" && staffToken)) {
      try {
        await enterApp();
      } catch (e) {
        showLoginShell(e?.message || "Could not open app — check login / network");
      }
    }
  }

  /** @deprecated use showView('buying'|'selling') — kept for older deep-links */
  function setOrdersType(type) {
    ordersType = type === "customer" ? "customer" : "vendor";
    showView(ordersType === "customer" ? "selling" : "buying");
  }

