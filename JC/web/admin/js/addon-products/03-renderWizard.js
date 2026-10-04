  function renderWizard() {
    const stepsEl = document.getElementById("addon-wizard-steps");
    const body = document.getElementById("addon-wizard-body");
    const footer = document.getElementById("addon-wizard-footer");
    if (!stepsEl || !body || !footer) return;

    const labels = ["Add-on"];
    stepsEl.innerHTML = labels.map((label, i) => {
      const n = i + 1;
      const cls = n < wizardStep ? "done" : n === wizardStep ? "active" : "";
      const num = n < wizardStep ? "Done" : String(n);
      return `<div class="step ${cls}"><div class="step-num">${num}</div>${label}</div>`;
    }).join("");

    if (wizardStep === 1) {
      body.innerHTML = `<div style="display:grid;gap:16px;">
        <div><label class="label">Add-on name *</label>
          <input id="aw-our_product_id" class="input" value="${ctx.esc(wizardForm.our_product_id)}" placeholder="e.g. FLOWER" oninput="AddonProducts.syncField('our_product_id', this.value)" /></div>
        <div><label class="label">Quantity in stock</label>
          <input id="aw-quantity" class="input" type="number" min="0" step="1" value="${ctx.esc(wizardForm.quantity)}" placeholder="0" oninput="AddonProducts.syncField('quantity', this.value)" /></div>
      </div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="AddonProducts.closeWizard()">Cancel</button>
        <button class="btn btn-primary" style="flex:1;" id="addon-create-btn" onclick="AddonProducts.create()">Create add-on</button>`;
    } else {
      body.innerHTML = `<div style="text-align:center;padding:24px 0;">
        <div class="success-icon" style="font-size:28px;font-weight:700;">OK</div>
        <h3 style="margin:0 0 8px;">Addon Created</h3>
        <p style="color:var(--muted);">${ctx.esc(wizardForm._result?.our_product_id || "")}</p>
      </div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="AddonProducts.openWizard()">Add Another</button>
        <button class="btn btn-primary" style="flex:1;" onclick="AddonProducts.closeWizard()">Done</button>`;
    }
  }

  function syncField(key, val) {
    if (key === "vendor_id") wizardForm.vendor_id = parseInt(val, 10) || null;
    else wizardForm[key] = val;
  }

  function onWizardImagePick(input) {
    const file = input.files && input.files[0];
    if (!file) return;
    collectWizardStep1();
    wizardForm._pendingFile = file;
    if (wizardForm._imagePreview) try { URL.revokeObjectURL(wizardForm._imagePreview); } catch (_) {}
    wizardForm._imagePreview = URL.createObjectURL(file);
    renderWizard();
  }

  function collectWizardStep1() {
    const vendorEl = document.getElementById("aw-vendor_id");
    if (vendorEl) wizardForm.vendor_id = parseInt(vendorEl.value, 10) || null;
    ["our_product_id", "vendor_product_id", "name", "description"].forEach(k => {
      const el = document.getElementById(`aw-${k}`);
      if (el) wizardForm[k] = el.value.trim();
    });
    const fileEl = document.getElementById("aw-image");
    if (fileEl && fileEl.files && fileEl.files[0]) wizardForm._pendingFile = fileEl.files[0];
  }

  function collectWizardStep2() {
    const catEl = document.getElementById("aw-category");
    if (catEl) wizardForm.category = catEl.value.trim() || null;
    const unitEl = document.getElementById("aw-unit");
    if (unitEl) wizardForm.unit = unitEl.value.trim();
    const priceEl = document.getElementById("aw-buying_price");
    if (priceEl) wizardForm.buying_price = priceEl.value.trim();
  }

  async function maybeUploadWizardImage() {
    if (!wizardForm._pendingFile) return;
    if (!wizardForm.vendor_id || !wizardForm.our_product_id) return;
    try {
      const result = await uploadImage(wizardForm.vendor_id, wizardForm.our_product_id, wizardForm._pendingFile);
      wizardForm.image_keys = result.key ? [result.key] : [];
      if (result.url) wizardForm._imagePreview = result.url;
      wizardForm._pendingFile = null;
    } catch (e) {
      throw new Error("Image upload failed: " + e.message);
    }
  }

  async function wizardNext() {
    if (wizardStep === 1) {
      collectWizardStep1();
      if (!wizardForm.vendor_id) return ctx.toast("Select a vendor", "error");
      if (!wizardForm.our_product_id) return ctx.toast("Our product ID required", "error");
      if (!wizardForm.vendor_product_id) return ctx.toast("Vendor product ID required", "error");
      wizardStep = 2;
      renderWizard();
      return;
    }
    if (wizardStep === 2) {
      collectWizardStep2();
      if (!wizardForm.unit) return ctx.toast("Select a unit", "error");
      const price = parseFloat(wizardForm.buying_price);
      if (Number.isNaN(price) || price < 0) return ctx.toast("Enter a valid buying price", "error");
      wizardForm.buying_price = price;
      wizardStep = 3;
      renderWizard();
    }
  }

  function wizardBack() {
    if (wizardStep === 2) collectWizardStep2();
    if (wizardStep === 3) collectWizardStep1();
    wizardStep = Math.max(1, wizardStep - 1);
    renderWizard();
  }

