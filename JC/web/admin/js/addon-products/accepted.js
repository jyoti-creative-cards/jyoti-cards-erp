/** Addon products — list/grid, wizard, detail, edit */
const AddonProducts = (() => {
  let ctx = {};
  let addons = [];
  let categories = [];
  let units = [];
  let vendors = [];
  let wizardStep = 1;
  let wizardForm = {};
  let editingId = null;

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
    // Live hub is Products (addons tab)
    if (typeof Products !== "undefined" && Products.refreshHub) {
      await Products.refreshHub();
      return;
    }
    addons = await ctx.api("/addons");
    if (ctx.onCountChange) ctx.onCountChange(addons.length);
  }

  async function refreshAfterMutation() {
    ctx.invalidateCache?.("/addons");
    if (typeof Products !== "undefined" && Products.refreshHub) await Products.refreshHub();
    else await load();
  }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = parseFloat(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function stockBadge(a) {
    const map = {
      in_stock: ["badge-green", "In stock"],
      low_stock: ["badge-amber", "Low stock"],
      out_of_stock: ["badge-gray", "Out of stock"],
      negative_stock: ["badge-red", "Negative"],
    };
    const [cls, label] = map[a.stock_status] || ["badge-gray", "—"];
    return `<span class="badge ${cls}">${ctx.esc(a.quantity_on_hand ?? 0)} on hand · ${label}</span>`;
  }

  function renderView() { /* legacy — Products hub owns list; kept only for TableUtils.register above */ }

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

    const changeHist = ctx.changeHistoryTable
      ? ctx.changeHistoryTable(a.change_history)
      : '<p style="color:var(--muted);font-size:14px;margin:0;">No field changes recorded yet.</p>';

    const moveRows = (a.stock_movements || []).length
      ? `<table class="data"><thead><tr><th>When</th><th>Type</th><th>Δ</th><th>Balance</th><th>Note</th></tr></thead><tbody>
          ${a.stock_movements.map(m => `<tr>
            <td style="font-size:13px;color:var(--muted);">${ctx.fmtDate(m.created_at)}</td>
            <td>${ctx.esc((m.entry_type || "").replace(/_/g, " "))}</td>
            <td><strong style="color:${m.quantity_delta < 0 ? "var(--danger, #dc2626)" : "var(--brand-green, #16a34a)"};">${m.quantity_delta > 0 ? "+" : ""}${m.quantity_delta}</strong></td>
            <td>${m.balance_after}</td>
            <td style="font-size:13px;color:var(--muted);">${ctx.esc(m.notes || m.party || "")}</td>
          </tr>`).join("")}
        </tbody></table>`
      : '<p style="color:var(--muted);font-size:14px;margin:0;">No stock movements recorded yet.</p>';

    ctx.openDetail("Addon Product", `
      <div class="profile-hero" style="margin:-24px -24px 24px;border-radius:0;">
        <div style="display:flex;align-items:center;gap:16px;">
          ${heroImg}
          <div>
            <h2 style="margin:0 0 4px;">${ctx.esc(a.our_product_id)}</h2>
            <p style="margin:0;">${ctx.esc(a.description || "")}</p>
            <div class="profile-meta">
              ${stockBadge(a)}
            </div>
          </div>
        </div>
      </div>
      <div class="review-grid" style="margin-bottom:24px;">
        ${ctx.reviewRow("Created", ctx.fmtDate(a.created_at))}
        ${ctx.reviewRow("Last Updated", ctx.fmtDate(a.updated_at))}
      </div>
      <div class="detail-section">
        <h4>Stock Movements</h4>
        ${moveRows}
      </div>
      ${changeHist}`,
      `${ctx.canWrite?.("addons") ? `<button class="btn btn-danger btn-sm" onclick="AddonProducts.deleteAddon(${a.id})">Delete</button>
       <button class="btn btn-secondary btn-sm" onclick="AddonProducts.openAdjustStock(${a.id})">Adjust Stock</button>
       <button class="btn btn-secondary btn-sm" onclick="AddonProducts.openReceiveStock(${a.id})">Receive Stock</button>
       <button class="btn btn-secondary btn-sm" onclick="AddonProducts.openEdit(${a.id})">Edit</button>` : ""}
       <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "lg"
    );
  }

  function openReceiveStock(id) {
    // Single modal with all 3 fields — was a 3-prompt() chain (qty, cost, note).
    document.getElementById("modal-title").textContent = "Receive addon stock";
    document.getElementById("modal-body").innerHTML = `
      <label class="label">Quantity received</label>
      <input class="input" id="addon-rs-qty" type="number" step="1" min="1" style="width:100%;margin-bottom:10px;" />
      <label class="label">Note (optional)</label>
      <textarea class="input" id="addon-rs-note" rows="2" style="width:100%;"></textarea>`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" id="addon-rs-ok">Save</button>`;
    document.getElementById("addon-rs-ok").onclick = async () => {
      const q = parseInt(document.getElementById("addon-rs-qty").value, 10);
      if (!Number.isFinite(q) || q <= 0) return ctx.toast("Enter a valid quantity", "error");
      const note = (document.getElementById("addon-rs-note").value || "").trim() || null;
      try {
        // Close only after a successful save — this used to close first, so a
        // failure (e.g. no finance.write when a cost is entered) silently dropped
        // every typed field with nothing left on screen to retry from.
        await ctx.api(`/addons/${id}/receive-stock`, { method: "POST", body: JSON.stringify({ quantity: q, note }) });
        App.closeModal();
        App.closeDetail();
        await refreshAfterMutation();
        ctx.toast("Stock received", "success");
        openDetail(id);
      } catch (e) {
        ctx.toast(e.message, "error");
      }
    };
    document.getElementById("modal").classList.remove("hidden");
  }

  function openAdjustStock(id) {
    // Single modal with both fields — was a 2-prompt() chain (delta, then reason).
    document.getElementById("modal-title").textContent = "Adjust addon stock";
    document.getElementById("modal-body").innerHTML = `
      <label class="label">Adjustment (e.g. -3 or 10)</label>
      <input class="input" id="addon-as-delta" type="number" step="1" style="width:100%;margin-bottom:10px;" />
      <label class="label">Reason (required)</label>
      <textarea class="input" id="addon-as-reason" rows="2" style="width:100%;"></textarea>`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" id="addon-as-ok">Save</button>`;
    document.getElementById("addon-as-ok").onclick = async () => {
      const d = parseInt(document.getElementById("addon-as-delta").value, 10);
      if (!Number.isFinite(d) || d === 0) return ctx.toast("Enter a non-zero number", "error");
      const reason = (document.getElementById("addon-as-reason").value || "").trim();
      if (!reason) return ctx.toast("Reason required", "error");
      try {
        await ctx.api(`/addons/${id}/adjust-stock`, { method: "POST", body: JSON.stringify({ delta: d, reason }) });
        App.closeModal();
        App.closeDetail();
        await refreshAfterMutation();
        ctx.toast("Stock adjusted", "success");
        openDetail(id);
      } catch (e) {
        ctx.toast(e.message, "error");
      }
    };
    document.getElementById("modal").classList.remove("hidden");
  }

  async function openWizard() {
    wizardStep = 1;
    wizardForm = { image_keys: [], quantity: "" };
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

  async function create() {
    const btn = document.getElementById("addon-create-btn");
    if (btn) btn.disabled = true;
    const name = (document.getElementById("aw-our_product_id")?.value || wizardForm.our_product_id || "").trim();
    const qtyRaw = document.getElementById("aw-quantity")?.value ?? wizardForm.quantity ?? "0";
    const quantity = parseInt(qtyRaw, 10) || 0;
    if (!name) {
      if (btn) btn.disabled = false;
      return ctx.toast("Add-on name required", "error");
    }
    if (quantity < 0) {
      if (btn) btn.disabled = false;
      return ctx.toast("Quantity cannot be negative", "error");
    }
    try {
      const result = await ctx.api("/addons", { method: "POST", body: JSON.stringify({
        our_product_id: name,
        quantity,
      })});
      wizardForm._result = result;
      wizardForm.our_product_id = name;
      wizardStep = 2;
      renderWizard();
      await refreshAfterMutation();
      ctx.invalidateCache?.("/stats");
      if (ctx.refreshStats) await ctx.refreshStats();
      ctx.toast("Addon product created", "success");
    } catch (e) {
      ctx.toast(e.message, "error");
      if (btn) btn.disabled = false;
    }
  }

  async function openEdit(id) {
    const a = await ctx.api(`/addons/${id}`);
    editingId = id;
    document.getElementById("addon-edit-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Name</label><input id="ae-our_product_id" class="input" value="${ctx.esc(a.our_product_id)}" /></div>
        <div><label class="label">Description</label><textarea id="ae-description" class="input" rows="2">${ctx.esc(a.description || "")}</textarea></div>
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
    const name = document.getElementById("ae-our_product_id").value.trim();
    if (!name) return ctx.toast("Name required", "error");
    const body = {
      our_product_id: name,
      description: document.getElementById("ae-description").value.trim() || null,
    };
    try {
      await ctx.api(`/addons/${editingId}`, { method: "PATCH", body: JSON.stringify(body) });
      const id = editingId;
      closeEdit();
      App.closeDetail();
      await refreshAfterMutation();
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
      await refreshAfterMutation();
      ctx.invalidateCache?.("/stats");
      if (ctx.refreshStats) await ctx.refreshStats();
      ctx.toast("Addon moved to recycle bin", "success");
    } catch (e) {
      ctx.toast(e.message, "error");
    }
  }

  return {
    init, load, openDetail, openWizard, closeWizard,
    wizardBack, wizardNext, onWizardImagePick, syncField, create,
    openEdit, closeEdit, save, deleteAddon, openReceiveStock, openAdjustStock,
  };
})();
