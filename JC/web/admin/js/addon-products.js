/** Addon products — list/grid, wizard, detail, edit */
const AddonProducts = (() => {
  let ctx = {};
  let addons = [];
  let categories = [];
  let units = [];
  let vendors = [];
  let viewMode = "list";
  let wizardStep = 1;
  let wizardForm = {};
  let editingId = null;

  const ADDON_COLS = [
    { key: "our_product_id", label: "Product ID", get: a => a.our_product_id },
    { key: "vendor", label: "Vendor", get: a => a.vendor_name || "" },
    { key: "unit", label: "Unit", get: a => a.unit },
    { key: "price", label: "Buying Price", get: a => a.buying_price || "" },
    { key: "_actions", label: "", filterable: false, sortable: false },
  ];

  function init(context) {
    ctx = context;
    TableUtils.register("addons", renderView);
  }

  async function ensureLookups() {
    if (categories.length && units.length) return;
    try {
      const rows = await ctx.api("/lookups");
      categories = rows.filter(r => r.lookup_type === "category").map(r => r.value);
      units = rows.filter(r => r.lookup_type === "unit").map(r => r.value);
    } catch (_) {
      categories = [];
      units = [];
    }
  }

  async function ensureVendors() {
    if (ctx.getVendors) {
      vendors = ctx.getVendors() || [];
      if (vendors.length) return;
    }
    vendors = await ctx.api("/vendors");
  }

  async function load() {
    await Promise.all([ensureLookups(), ensureVendors()]);
    const q = document.getElementById("addon-search-input")?.value.trim() || "";
    addons = await ctx.api(`/addons${q ? "?search=" + encodeURIComponent(q) : ""}`);
    renderView();
    if (ctx.onCountChange) ctx.onCountChange(addons.length);
  }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = parseFloat(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function thumbHtml(a, size) {
    const s = size || 40;
    if (a.image_urls && a.image_urls[0]) {
      return `<img src="${ctx.esc(a.image_urls[0])}" alt="" style="width:${s}px;height:${s}px;object-fit:cover;border-radius:8px;border:1px solid var(--border);" />`;
    }
    return `<div style="width:${s}px;height:${s}px;border-radius:8px;background:#f1f5f9;border:1px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:var(--muted);">${ctx.esc((a.our_product_id || "?").slice(0, 3))}</div>`;
  }

  function setViewMode(mode) {
    viewMode = mode;
    document.getElementById("addon-view-grid")?.classList.toggle("active", viewMode === "grid");
    document.getElementById("addon-view-list")?.classList.toggle("active", viewMode === "list");
    renderView();
  }

  function renderView() {
    if (viewMode === "grid") renderGrid();
    else renderTable();
  }

  function renderToolbar() {
    const el = document.getElementById("addons-toolbar");
    if (!el) return;
    el.innerHTML = `
      <div style="display:flex;gap:8px;">
        <button class="btn btn-sm ${viewMode === "list" ? "btn-primary" : "btn-secondary"}" onclick="AddonProducts.setViewMode('list')">List</button>
        <button class="btn btn-sm ${viewMode === "grid" ? "btn-primary" : "btn-secondary"}" onclick="AddonProducts.setViewMode('grid')">Grid</button>
      </div>`;
  }

  function addonEmptyHtml() {
    return ctx.canWrite?.("addons")
      ? '<div class="empty-state"><p style="font-size:15px;font-weight:600;color:var(--text);">No addon products yet</p><p>Add your first addon to track vendor buying prices.</p><button class="btn btn-primary btn-lg" style="margin-top:16px;" onclick="AddonProducts.openWizard()">Add Addon Product</button></div>'
      : '<div class="empty-state"><p>No addon products yet.</p></div>';
  }

  function renderTable() {
    renderToolbar();
    const el = document.getElementById("addons-table");
    if (!el) return;
    if (!addons.length) {
      el.innerHTML = addonEmptyHtml();
      return;
    }
    const rows = TableUtils.apply(addons, "addons", ADDON_COLS);
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("addons", ADDON_COLS)}<tbody>
      ${rows.map(a => `<tr class="clickable" onclick="AddonProducts.openDetail(${a.id})">
        <td><div style="display:flex;align-items:center;gap:12px;">
          ${thumbHtml(a, 44)}
          <div><strong>${ctx.esc(a.our_product_id)}</strong>${a.name ? `<br><span style="font-size:12px;color:var(--muted);">${ctx.esc(a.name)}</span>` : ""}</div>
        </div></td>
        <td>${ctx.esc(a.vendor_name || "—")}</td>
        <td><span class="badge badge-gray">${ctx.esc(a.unit)}</span></td>
        <td><strong>${fmtPrice(a.buying_price)}</strong></td>
        <td onclick="event.stopPropagation()"><button class="btn btn-ghost btn-sm" onclick="AddonProducts.openDetail(${a.id})">Open</button></td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  function renderGrid() {
    renderToolbar();
    const el = document.getElementById("addons-table");
    if (!el) return;
    if (!addons.length) {
      el.innerHTML = addonEmptyHtml();
      return;
    }
    const rows = TableUtils.apply(addons, "addons", ADDON_COLS);
    el.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;">
      ${rows.map(a => `<div class="card clickable" style="padding:16px;cursor:pointer;" onclick="AddonProducts.openDetail(${a.id})">
        <div style="display:flex;justify-content:center;margin-bottom:12px;">${thumbHtml(a, 72)}</div>
        <div style="font-weight:700;font-size:15px;margin-bottom:4px;">${ctx.esc(a.our_product_id)}</div>
        ${a.name ? `<div style="font-size:13px;color:var(--muted);margin-bottom:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${ctx.esc(a.name)}</div>` : ""}
        <div style="display:flex;justify-content:space-between;align-items:center;font-size:13px;">
          <span style="color:var(--muted);">${ctx.esc(a.vendor_name || "—")}</span>
          <span class="badge badge-gray">${ctx.esc(a.unit)}</span>
        </div>
        <div style="margin-top:10px;font-size:16px;font-weight:700;color:var(--brand);">${fmtPrice(a.buying_price)}</div>
      </div>`).join("")}
    </div>`;
  }

  async function uploadImage(vendorId, ourProductId, file) {
    if (ctx.uploadImage) return ctx.uploadImage(vendorId, ourProductId, file);
    if (ctx.apiForm) return ctx.apiForm("/catalog/upload-image", buildImageForm(vendorId, ourProductId, file));
    const fd = buildImageForm(vendorId, ourProductId, file);
    const base = ctx.apiBase || "";
    const key = ctx.adminKey || "";
    const res = await fetch(`${base}/catalog/upload-image`, {
      method: "POST",
      headers: { "X-Admin-Key": key },
      body: fd,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const msg = typeof err.detail === "string" ? err.detail : `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return res.json();
  }

  function buildImageForm(vendorId, ourProductId, file) {
    const fd = new FormData();
    fd.append("vendor_id", String(vendorId));
    fd.append("our_product_id", ourProductId);
    fd.append("image_index", "1");
    fd.append("file", file);
    return fd;
  }

  async function openDetail(id) {
    const a = await ctx.api(`/addons/${id}`);
    const heroImg = a.image_urls && a.image_urls[0]
      ? `<img src="${ctx.esc(a.image_urls[0])}" alt="" style="width:72px;height:72px;object-fit:cover;border-radius:12px;border:1px solid var(--border);" />`
      : `<div style="width:72px;height:72px;border-radius:12px;background:#e2e8f0;display:flex;align-items:center;justify-content:center;font-weight:700;color:var(--muted);">${ctx.esc((a.our_product_id || "").slice(0, 3))}</div>`;

    const priceRows = (a.price_history || []).length
      ? `<table class="data"><thead><tr><th>Price</th><th>Recorded</th></tr></thead><tbody>
          ${a.price_history.map(p => `<tr><td><strong>${fmtPrice(p.buying_price)}</strong></td><td style="font-size:13px;color:var(--muted);">${ctx.fmtDate(p.recorded_at)}</td></tr>`).join("")}
        </tbody></table>`
      : '<p style="color:var(--muted);font-size:14px;margin:0;">No price changes recorded yet.</p>';

    const changeHist = ctx.changeHistoryTable
      ? ctx.changeHistoryTable(a.change_history)
      : '<p style="color:var(--muted);font-size:14px;margin:0;">No field changes recorded yet.</p>';

    ctx.openDetail("Addon Product", `
      <div class="profile-hero" style="margin:-24px -24px 24px;border-radius:0;">
        <div style="display:flex;align-items:center;gap:16px;">
          ${heroImg}
          <div>
            <h2 style="margin:0 0 4px;">${ctx.esc(a.our_product_id)}</h2>
            <p style="margin:0;">${ctx.esc(a.name || a.vendor_product_id || "No display name")}</p>
            <div class="profile-meta">
              <span class="badge badge-blue">${ctx.esc(a.vendor_name || "—")}</span>
              <span class="badge badge-gray">${ctx.esc(a.unit)}</span>
              ${a.category ? `<span class="badge badge-green">${ctx.esc(a.category)}</span>` : ""}
              <span class="badge badge-amber">${fmtPrice(a.buying_price)}</span>
            </div>
          </div>
        </div>
      </div>
      <div class="review-grid" style="margin-bottom:24px;">
        ${ctx.reviewRow("Vendor Product ID", a.vendor_product_id)}
        ${ctx.reviewRow("Description", a.description)}
        ${ctx.reviewRow("Category", a.category)}
        ${ctx.reviewRow("Created", ctx.fmtDate(a.created_at))}
        ${ctx.reviewRow("Last Updated", ctx.fmtDate(a.updated_at))}
      </div>
      <div class="detail-section">
        <h4>Price History</h4>
        ${priceRows}
      </div>
      ${changeHist}`,
      `${ctx.canWrite?.("addons") ? `<button class="btn btn-danger btn-sm" onclick="AddonProducts.deleteAddon(${a.id})">Delete</button>
       <button class="btn btn-secondary btn-sm" onclick="AddonProducts.openEdit(${a.id})">Edit</button>` : ""}
       <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "lg"
    );
  }

  async function openWizard() {
    await Promise.all([ensureLookups(), ensureVendors()]);
    if (!vendors.length) {
      ctx.toast("Add vendors in People first", "error");
      return;
    }
    wizardStep = 1;
    wizardForm = { image_keys: [] };
    document.getElementById("addon-wizard").classList.remove("hidden");
    renderWizard();
  }

  function closeWizard() {
    document.getElementById("addon-wizard").classList.add("hidden");
    wizardForm = {};
    wizardStep = 1;
  }

  function renderWizard() {
    const stepsEl = document.getElementById("addon-wizard-steps");
    const body = document.getElementById("addon-wizard-body");
    const footer = document.getElementById("addon-wizard-footer");
    if (!stepsEl || !body || !footer) return;

    const labels = ["Product Info", "Pricing & Unit", "Review & Create"];
    stepsEl.innerHTML = labels.map((label, i) => {
      const n = i + 1;
      const cls = n < wizardStep ? "done" : n === wizardStep ? "active" : "";
      const num = n < wizardStep ? "Done" : String(n);
      return `<div class="step ${cls}"><div class="step-num">${num}</div>${label}</div>`;
    }).join("");

    if (wizardStep === 1) {
      const vendorOpts = vendors.map(v =>
        `<option value="${v.id}" ${wizardForm.vendor_id == v.id ? "selected" : ""}>${ctx.esc(v.business_name)}</option>`
      ).join("");
      const preview = wizardForm._imagePreview
        ? `<img src="${ctx.esc(wizardForm._imagePreview)}" alt="" style="width:80px;height:80px;object-fit:cover;border-radius:8px;border:1px solid var(--border);" />`
        : wizardForm._pendingFile
          ? `<div style="width:80px;height:80px;border-radius:8px;background:#eff6ff;border:1px solid #bfdbfe;display:flex;align-items:center;justify-content:center;font-size:11px;color:var(--brand);text-align:center;padding:4px;">Pending upload</div>`
          : `<div style="width:80px;height:80px;border-radius:8px;background:#f1f5f9;border:1px dashed var(--border);display:flex;align-items:center;justify-content:center;font-size:11px;color:var(--muted);">No image</div>`;

      body.innerHTML = `<div style="display:grid;gap:16px;">
        <div><label class="label">Vendor *</label>
          <select id="aw-vendor_id" class="input" onchange="AddonProducts.syncField('vendor_id', this.value)"><option value="">Select vendor</option>${vendorOpts}</select></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Our Product ID *</label><input id="aw-our_product_id" class="input" value="${ctx.esc(wizardForm.our_product_id)}" placeholder="e.g. ADD-001" oninput="AddonProducts.syncField('our_product_id', this.value)" /></div>
          <div><label class="label">Vendor Product ID *</label><input id="aw-vendor_product_id" class="input" value="${ctx.esc(wizardForm.vendor_product_id)}" placeholder="Vendor SKU" oninput="AddonProducts.syncField('vendor_product_id', this.value)" /></div>
        </div>
        <div><label class="label">Display Name</label><input id="aw-name" class="input" value="${ctx.esc(wizardForm.name)}" placeholder="Optional" oninput="AddonProducts.syncField('name', this.value)" /></div>
        <div><label class="label">Description</label><textarea id="aw-description" class="input" rows="2" placeholder="Optional" oninput="AddonProducts.syncField('description', this.value)">${ctx.esc(wizardForm.description)}</textarea></div>
        <div><label class="label">Product Image</label>
          <div style="display:flex;align-items:center;gap:16px;">
            ${preview}
            <div style="flex:1;">
              <input id="aw-image" type="file" accept="image/*" class="input" onchange="AddonProducts.onWizardImagePick(this)" />
              <p style="margin:6px 0 0;font-size:12px;color:var(--muted);">Optional. Uploaded to vendor folder on save.</p>
            </div>
          </div>
        </div>
      </div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="AddonProducts.closeWizard()">Cancel</button>
        <button class="btn btn-primary" style="flex:1;" onclick="AddonProducts.wizardNext()">Continue</button>`;
    } else if (wizardStep === 2) {
      const catOpts = ['<option value="">No category</option>'].concat(
        categories.map(c => `<option value="${ctx.esc(c)}" ${wizardForm.category === c ? "selected" : ""}>${ctx.esc(c)}</option>`)
      ).join("");
      const unitOpts = ['<option value="">Select unit</option>'].concat(
        units.map(u => `<option value="${ctx.esc(u)}" ${wizardForm.unit === u ? "selected" : ""}>${ctx.esc(u)}</option>`)
      ).join("");
      const customUnit = wizardForm.unit && !units.includes(wizardForm.unit)
        ? `<option value="${ctx.esc(wizardForm.unit)}" selected>${ctx.esc(wizardForm.unit)}</option>` : "";

      body.innerHTML = `<div style="display:grid;gap:16px;">
        <div><label class="label">Category</label>
          <select id="aw-category" class="input" onchange="AddonProducts.syncField('category', this.value)">${catOpts}</select></div>
        <div><label class="label">Unit *</label>
          <select id="aw-unit" class="input" onchange="AddonProducts.syncField('unit', this.value)">${unitOpts}${customUnit}</select>
          <p style="margin:6px 0 0;font-size:12px;color:var(--muted);">Manage units in catalog lookups.</p></div>
        <div><label class="label">Buying Price (INR) *</label>
          <input id="aw-buying_price" class="input" type="number" min="0" step="0.01" value="${ctx.esc(wizardForm.buying_price)}" placeholder="0.00" oninput="AddonProducts.syncField('buying_price', this.value)" /></div>
      </div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="AddonProducts.wizardBack()">Back</button>
        <button class="btn btn-primary" style="flex:1;" onclick="AddonProducts.wizardNext()">Review</button>`;
    } else if (wizardStep === 3) {
      const vendor = vendors.find(v => v.id == wizardForm.vendor_id);
      const imgReview = wizardForm._imagePreview
        ? `<img src="${ctx.esc(wizardForm._imagePreview)}" alt="" style="width:48px;height:48px;object-fit:cover;border-radius:6px;" />`
        : "None";
      body.innerHTML = `<div class="review-grid">
        ${ctx.reviewRow("Vendor", vendor?.business_name)}
        ${ctx.reviewRow("Our Product ID", wizardForm.our_product_id)}
        ${ctx.reviewRow("Vendor Product ID", wizardForm.vendor_product_id)}
        ${ctx.reviewRow("Name", wizardForm.name)}
        ${ctx.reviewRow("Description", wizardForm.description)}
        ${ctx.reviewRow("Category", wizardForm.category)}
        ${ctx.reviewRow("Unit", wizardForm.unit)}
        ${ctx.reviewRow("Buying Price", fmtPrice(wizardForm.buying_price))}
        ${ctx.reviewRow("Image", imgReview, true)}
      </div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="AddonProducts.wizardBack()">Back</button>
        <button class="btn btn-primary" style="flex:1;" id="addon-create-btn" onclick="AddonProducts.create()">Create Addon</button>`;
    } else if (wizardStep === 4) {
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
    else wizardForm[key] = typeof val === "string" ? val : val;
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

  async function create() {
    const btn = document.getElementById("addon-create-btn");
    if (btn) btn.disabled = true;
    try {
      if (wizardForm._pendingFile) await maybeUploadWizardImage();
      const result = await ctx.api("/addons", { method: "POST", body: JSON.stringify({
        our_product_id: wizardForm.our_product_id,
        vendor_id: wizardForm.vendor_id,
        vendor_product_id: wizardForm.vendor_product_id,
        name: wizardForm.name || null,
        description: wizardForm.description || null,
        category: wizardForm.category || null,
        unit: wizardForm.unit,
        buying_price: wizardForm.buying_price,
        image_keys: wizardForm.image_keys || [],
      })});
      wizardForm._result = result;
      wizardStep = 4;
      renderWizard();
      await load();
      ctx.invalidateCache?.("/addons");
      ctx.invalidateCache?.("/stats");
      if (ctx.refreshStats) await ctx.refreshStats();
      ctx.toast("Addon product created", "success");
    } catch (e) {
      ctx.toast(e.message, "error");
      if (btn) btn.disabled = false;
    }
  }

  async function openEdit(id) {
    await Promise.all([ensureLookups(), ensureVendors()]);
    const a = await ctx.api(`/addons/${id}`);
    editingId = id;
    const catOpts = ['<option value="">No category</option>'].concat(
      categories.map(c => `<option value="${ctx.esc(c)}" ${a.category === c ? "selected" : ""}>${ctx.esc(c)}</option>`)
    ).join("");
    const unitOpts = units.map(u =>
      `<option value="${ctx.esc(u)}" ${a.unit === u ? "selected" : ""}>${ctx.esc(u)}</option>`
    ).join("");
    const customUnit = a.unit && !units.includes(a.unit)
      ? `<option value="${ctx.esc(a.unit)}" selected>${ctx.esc(a.unit)}</option>` : "";
    const imgPreview = a.image_urls && a.image_urls[0]
      ? `<img id="ae-preview" src="${ctx.esc(a.image_urls[0])}" alt="" style="width:80px;height:80px;object-fit:cover;border-radius:8px;border:1px solid var(--border);" />`
      : `<div id="ae-preview" style="width:80px;height:80px;border-radius:8px;background:#f1f5f9;border:1px dashed var(--border);display:flex;align-items:center;justify-content:center;font-size:11px;color:var(--muted);">No image</div>`;

    document.getElementById("addon-edit-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div class="card" style="padding:12px 16px;background:#f8fafc;">
          <div style="font-size:12px;color:var(--muted);margin-bottom:4px;">Our Product ID</div>
          <div style="font-weight:700;">${ctx.esc(a.our_product_id)}</div>
          <div style="font-size:12px;color:var(--muted);margin-top:8px;">Vendor: ${ctx.esc(a.vendor_name || "—")}</div>
        </div>
        <div><label class="label">Vendor Product ID</label><input id="ae-vendor_product_id" class="input" value="${ctx.esc(a.vendor_product_id)}" /></div>
        <div><label class="label">Display Name</label><input id="ae-name" class="input" value="${ctx.esc(a.name || "")}" /></div>
        <div><label class="label">Description</label><textarea id="ae-description" class="input" rows="2">${ctx.esc(a.description || "")}</textarea></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Category</label><select id="ae-category" class="input">${catOpts}</select></div>
          <div><label class="label">Unit *</label><select id="ae-unit" class="input"><option value="">Select unit</option>${unitOpts}${customUnit}</select></div>
        </div>
        <div><label class="label">Buying Price (INR) *</label><input id="ae-buying_price" class="input" type="number" min="0" step="0.01" value="${ctx.esc(a.buying_price)}" /></div>
        <div><label class="label">Product Image</label>
          <div style="display:flex;align-items:center;gap:16px;">
            ${imgPreview}
            <div style="flex:1;">
              <input id="ae-image" type="file" accept="image/*" class="input" />
              <input type="hidden" id="ae-image_keys" value="${ctx.esc((a.image_keys || []).join(","))}" />
              <p style="margin:6px 0 0;font-size:12px;color:var(--muted);">Replace image (optional).</p>
            </div>
          </div>
        </div>
      </div>`;
    document.getElementById("addon-edit-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="AddonProducts.closeEdit()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="AddonProducts.save()">Save Changes</button>`;
    document.getElementById("addon-edit-modal").classList.remove("hidden");
  }

  function closeEdit() {
    document.getElementById("addon-edit-modal").classList.add("hidden");
    editingId = null;
  }

  async function save() {
    if (!editingId) return;
    const unit = document.getElementById("ae-unit").value.trim();
    if (!unit) return ctx.toast("Unit required", "error");
    const price = parseFloat(document.getElementById("ae-buying_price").value);
    if (Number.isNaN(price) || price < 0) return ctx.toast("Enter a valid buying price", "error");

    let imageKeys = (document.getElementById("ae-image_keys").value || "")
      .split(",").map(s => s.trim()).filter(Boolean);
    const fileEl = document.getElementById("ae-image");
    const file = fileEl && fileEl.files && fileEl.files[0];
    if (file) {
      try {
        const detail = await ctx.api(`/addons/${editingId}`);
        const result = await uploadImage(detail.vendor_id, detail.our_product_id, file);
        imageKeys = result.key ? [result.key] : imageKeys;
      } catch (e) {
        return ctx.toast("Image upload failed: " + e.message, "error");
      }
    }

    try {
      await ctx.api(`/addons/${editingId}`, { method: "PATCH", body: JSON.stringify({
        vendor_product_id: document.getElementById("ae-vendor_product_id").value.trim(),
        name: document.getElementById("ae-name").value.trim() || null,
        description: document.getElementById("ae-description").value.trim() || null,
        category: document.getElementById("ae-category").value.trim() || null,
        unit,
        buying_price: price,
        image_keys: imageKeys,
      })});
      const id = editingId;
      closeEdit();
      App.closeDetail();
      await load();
      ctx.toast("Addon updated", "success");
      openDetail(id);
    } catch (e) {
      ctx.toast(e.message, "error");
    }
  }

  async function deleteAddon(id) {
    if (!confirm("Move this addon product to recycle bin?")) return;
    try {
      await ctx.api(`/addons/${id}`, { method: "DELETE" });
      App.closeDetail();
      await load();
      ctx.invalidateCache?.("/addons");
      ctx.invalidateCache?.("/stats");
      if (ctx.refreshStats) await ctx.refreshStats();
      ctx.toast("Addon moved to recycle bin", "success");
    } catch (e) {
      ctx.toast(e.message, "error");
    }
  }

  return {
    init, load, setViewMode, openDetail, openWizard, closeWizard,
    wizardBack, wizardNext, onWizardImagePick, syncField, create,
    openEdit, closeEdit, save, deleteAddon,
  };
})();
