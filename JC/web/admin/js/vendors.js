/** Vendor module — CRUD, wizard, detail, edit */
const Vendors = (() => {
  let ctx = {};
  let vendors = [];
  let vendorLedger = [];
  let currentVendorId = null;
  let wizardStep = 1;
  let wizardForm = {};
  let editingId = null;

  const VENDOR_COLS = [
    { key: "business", label: "Business", get: v => `${v.business_name} ${v.alias || ""}` },
    { key: "phone", label: "Phone", get: v => v.phone },
    { key: "city", label: "City", get: v => v.city_name || "" },
    { key: "contact", label: "Contact", get: v => v.person_name || "" },
    { key: "_actions", label: "", filterable: false, sortable: false },
  ];

  function init(context) {
    ctx = context;
    TableUtils.register("vendors", renderTable);
  }

  function parseCityId(raw) {
    const v = parseInt(String(raw || "").trim(), 10);
    return Number.isInteger(v) ? v : null;
  }

  async function load() {
    const q = document.getElementById("vendor-search-input")?.value.trim() || "";
    ctx.showLoading?.();
    try {
      vendors = await ctx.api(`/vendors${q ? "?search=" + encodeURIComponent(q) : ""}`, {}, 0);
      if (ctx.setVendors) ctx.setVendors(vendors);
      renderTable();
    } finally {
      ctx.hideLoading?.();
    }
  }

  async function reload() {
    ctx.invalidateCache?.("/vendors");
    ctx.invalidateCache?.("/stats");
    ctx.showLoading?.();
    try {
      await load();
      if (ctx.refreshStats) await ctx.refreshStats();
      ctx.toast("Vendor list refreshed", "success");
    } catch (e) {
      ctx.toast(e.message, "error");
    } finally {
      ctx.hideLoading?.();
    }
  }

  function renderTable() {
    const el = document.getElementById("vendors-table");
    if (!el) return;
    if (!vendors.length) {
      el.innerHTML = '<div class="empty-state"><p>No vendors yet.</p><button class="btn btn-primary btn-lg" style="margin-top:16px;" onclick="Vendors.openWizard()">+ Add First Vendor</button></div>';
      return;
    }
    const rows = TableUtils.apply(vendors, "vendors", VENDOR_COLS);
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("vendors", VENDOR_COLS)}<tbody>
      ${rows.map(v => `<tr class="clickable" onclick="Vendors.openDetail(${v.id})">
        <td><strong>${ctx.esc(v.business_name)}</strong>${v.alias ? `<br><span style="font-size:12px;color:var(--muted);">${ctx.esc(v.alias)}</span>` : ""}</td>
        <td>${ctx.esc(v.phone)}</td>
        <td>${ctx.esc(v.city_name || "—")}</td>
        <td>${v.person_name ? ctx.esc(v.person_name) : "—"}</td>
        <td onclick="event.stopPropagation()"></td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  let vendorAp = null;
  let vendorLedgerExpanded = null;

  function fmtMoney(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });
  }

  async function openDetail(id) {
    currentVendorId = id;
    vendorLedgerExpanded = null;
    vendorAp = null;
    const v = await ctx.api(`/vendors/${id}`);
    vendorLedger = [];
    ctx.openDetail("Vendor Profile", `
      <div class="profile-hero" style="margin:-24px -24px 24px;border-radius:0;">
        <h2>${ctx.esc(v.business_name)}</h2>
        <p>${ctx.esc(v.person_name || "No contact person")}</p>
        <div class="profile-meta">
          <span class="badge badge-blue">${ctx.esc(v.phone)}</span>
          ${v.alias ? `<span class="badge badge-gray">${ctx.esc(v.alias)}</span>` : ""}
          <span class="badge badge-green">${ctx.esc(v.city_name || "—")}</span>
        </div>
      </div>
      <div class="review-grid">
        ${ctx.reviewRow("Secondary Phone", v.secondary_phone)}
        ${ctx.reviewRow("GST Number", v.gst_number)}
        ${ctx.reviewRow("Address", v.address)}
        ${ctx.reviewRow("Created", ctx.fmtDate(v.created_at))}
        ${ctx.reviewRow("Last Updated", ctx.fmtDate(v.updated_at))}
      </div>
      <div id="vendor-ledger-wrap"><div class="detail-section"><h4>Ledger</h4><p style="color:var(--muted);font-size:13px;">Loading…</p></div></div>
      ${ctx.isAdmin?.() ? `<div id="vendor-ap-wrap"><div class="detail-section"><h4>Accounts Payable</h4><p style="color:var(--muted);font-size:13px;">Loading…</p></div></div>` : ""}
      ${ctx.changeHistoryTable ? ctx.changeHistoryTable(v.change_history) : ""}`,
      `${ctx.canWrite?.("vendors") ? `<button class="btn btn-danger btn-sm" onclick="Vendors.deleteVendor(${v.id})">Delete</button>
       <button class="btn btn-secondary btn-sm" onclick="Vendors.openEdit(${v.id})">Edit</button>
       <button class="btn btn-secondary btn-sm" onclick="Vendors.createOrder(${v.id})">Create Order</button>` : ""}
       <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "md"
    );
    await refreshVendorLedger(id);
  }

  async function refreshVendorLedger(id) {
    const wrap = document.getElementById("vendor-ledger-wrap");
    try {
      const [ledgerRes, ap] = await Promise.all([
        ctx.api(`/vendors/${id}/ledger`, {}, 0),
        ctx.isAdmin?.() ? ctx.api(`/accounts-payable/vendor/${id}`, {}, 0).catch(() => null) : Promise.resolve(null),
      ]);
      vendorLedger = ledgerRes.items || [];
      vendorAp = ap;
      if (wrap) wrap.innerHTML = renderVendorStatement(id);
      if (ctx.isAdmin?.() && ap) {
        const apWrap = document.getElementById("vendor-ap-wrap");
        if (apWrap) {
          apWrap.innerHTML = `<div class="detail-section">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;gap:8px;">
              <h4 style="margin:0;">Accounts Payable</h4>
              <div style="display:flex;gap:6px;flex-wrap:wrap;">
                ${Number(ap.outstanding) > 0 ? `<button class="btn btn-primary btn-sm" onclick="Vendors.settlePayment(${id})">Settle Payment</button>` : ""}
                <button class="btn btn-secondary btn-sm" onclick="Finance.showApFromVendor(${id})">Full AP →</button>
              </div>
            </div>
            <div class="review-grid">
              ${ctx.reviewRow("Outstanding", fmtMoney(ap.outstanding))}
              ${ctx.reviewRow("Bills", fmtMoney(ap.bill_total))}
              ${ctx.reviewRow("Debit notes", fmtMoney(ap.debit_note_total))}
              ${ctx.reviewRow("Paid", fmtMoney(ap.payment_total))}
            </div>
          </div>`;
        }
      }
    } catch (e) {
      if (wrap) wrap.innerHTML = `<div class="detail-section"><h4>Ledger</h4><p style="color:var(--danger);font-size:13px;">${ctx.esc(e.message)}</p></div>`;
    }
  }

  function renderVendorStatement(vendorId) {
    const orders = vendorLedger.filter(e => e.event_type === "order_placed" || e.event_type === "order_cancelled");
    const bills = vendorLedger.filter(e => e.event_type === "stock_received");
    const payments = vendorLedger.filter(e => e.event_type === "ap_payment");
    // Nest debit notes under matching bill/receipt
    const dnsByReceipt = {};
    for (const e of vendorLedger.filter(x => x.event_type === "debit_note")) {
      const rid = e.details?.receipt_id;
      if (!rid) continue;
      (dnsByReceipt[rid] || (dnsByReceipt[rid] = [])).push(e);
    }

    const sections = [];
    sections.push(`<div class="vled-toolbar">
      <button class="btn btn-secondary btn-sm" onclick="Vendors.createOrder(${vendorId})">+ Place order</button>
      <button class="btn btn-secondary btn-sm" onclick="Stock.openOfflineForVendor(${vendorId})">Offline bill</button>
      ${ctx.isAdmin?.() && vendorAp && Number(vendorAp.outstanding) > 0
        ? `<button class="btn btn-primary btn-sm" onclick="Vendors.settlePayment(${vendorId})">Settle payment</button>` : ""}
    </div>`);

    sections.push(renderLedgerGroup("Orders placed", orders, "order", (e) => {
      const d = e.details || {};
      const open = vendorLedgerExpanded === e.id;
      const lines = d.lines || [];
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="Vendors.toggleLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">${e.event_type === "order_cancelled" ? "Cancelled" : "Placed"} · #${d.placement_id || "—"}</div>
            <div class="vled-meta">${ctx.fmtDate(e.occurred_at)} · ${lines.length} lines · ${ctx.esc(e.summary || "")}</div>
          </div>
          <span class="vled-chevron">${open ? "▾" : "▸"}</span>
        </button>
        ${open ? `<div class="vled-body">
          <table class="data fin-mini"><thead><tr><th>Product</th><th>Qty</th><th>Price</th></tr></thead><tbody>
            ${lines.map(l => `<tr><td>${ctx.esc(l.our_product_id)}</td><td>${l.quantity ?? "—"}</td><td>${fmtMoney(l.buying_price)}</td></tr>`).join("") || "<tr><td colspan=3>—</td></tr>"}
          </tbody></table>
          <div class="vled-actions">
            <button class="btn btn-secondary btn-sm" onclick="Vendors.openOrderFromLedger('${e.id}')">Open in Orders</button>
          </div>
        </div>` : ""}
      </div>`;
    }));

    sections.push(renderLedgerGroup("Bills / received", bills, "bill", (e) => {
      const d = e.details || {};
      const open = vendorLedgerExpanded === e.id;
      const rid = d.receipt_id;
      const dns = rid ? (dnsByReceipt[rid] || []) : [];
      const lines = d.lines || [];
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="Vendors.toggleLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">Bill ${ctx.esc(d.bill_number || `#${rid || d.placement_id || ""}`)}</div>
            <div class="vled-meta">${ctx.fmtDate(e.occurred_at)} · ${lines.length} lines
              ${d.bill_amount != null ? ` · Bill ${fmtMoney(d.bill_amount)}` : ""}
              ${dns.length ? ` · ${dns.length} debit note${dns.length === 1 ? "" : "s"}` : ""}
              ${d.net_payable != null ? ` · Net ${fmtMoney(d.net_payable)}` : ""}</div>
          </div>
          <span class="vled-chevron">${open ? "▾" : "▸"}</span>
        </button>
        ${open ? `<div class="vled-body">
          <table class="data fin-mini"><thead><tr><th>Product</th><th>Recv</th><th>Billed</th></tr></thead><tbody>
            ${lines.map(l => `<tr><td>${ctx.esc(l.our_product_id)}</td><td>${l.quantity_received ?? l.quantity ?? "—"}</td><td>${l.quantity_billed ?? "—"}</td></tr>`).join("") || "<tr><td colspan=3>—</td></tr>"}
          </tbody></table>
          ${dns.length ? `<div class="fin-dn-block"><div class="fin-dn-title">Debit notes</div>
            ${dns.map(dn => {
              const nd = dn.details || {};
              return `<div class="fin-dn-row">
                <div><strong>${ctx.esc(nd.our_product_id || nd.note_type || "Note")}${nd.quantity != null ? ` × ${nd.quantity}` : ""}</strong>
                  ${nd.notes ? `<div class="fin-dn-note">${ctx.esc(nd.notes)}</div>` : ""}
                </div>
                <strong>${fmtMoney(nd.amount)}</strong>
              </div>`;
            }).join("")}
          </div>` : ""}
          <div class="vled-actions">
            ${rid ? `<button class="btn btn-primary btn-sm" onclick="VendorOrders.openReceiptDoc(${rid})">Bill Receipt</button>` : ""}
            ${d.bill_file_url ? `<button class="btn btn-secondary btn-sm" onclick="window.open('${ctx.esc(d.bill_file_url)}','_blank')">Vendor Bill</button>` : ""}
            ${rid ? `<button class="btn btn-secondary btn-sm" onclick="Vendors.openBillDebitNotes(${vendorId}, ${rid})">Debit Note</button>` : ""}
            <button class="btn btn-secondary btn-sm" onclick="Vendors.openOrderFromLedger('${e.id}')">Open in Orders</button>
          </div>
        </div>` : ""}
      </div>`;
    }));

    sections.push(renderLedgerGroup("Payments", payments, "pay", (e) => {
      const d = e.details || {};
      const open = vendorLedgerExpanded === e.id;
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="Vendors.toggleLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">Payment ${ctx.esc(d.payment_ref || "")}</div>
            <div class="vled-meta">${ctx.fmtDate(e.occurred_at)} · ${fmtMoney(d.amount)}${d.comment ? ` · ${ctx.esc(d.comment)}` : ""}</div>
          </div>
          <span class="vled-chevron">${open ? "▾" : "▸"}</span>
        </button>
        ${open ? `<div class="vled-body">
          <div class="review-grid">
            ${ctx.reviewRow("Reference", d.payment_ref || "—")}
            ${ctx.reviewRow("Amount", fmtMoney(d.amount))}
            ${d.comment ? ctx.reviewRow("Comment", d.comment) : ""}
          </div>
          <div class="vled-actions">
            ${d.payment_receipt_url ? `<a class="btn btn-secondary btn-sm" href="${ctx.esc(d.payment_receipt_url)}" target="_blank">Payment receipt</a>` : ""}
            ${ctx.isAdmin?.() ? `<button class="btn btn-primary btn-sm" onclick="Vendors.settlePayment(${vendorId})">Settle again</button>` : ""}
            <button class="btn btn-secondary btn-sm" onclick="Finance.showApFromVendor(${vendorId})">Open AP</button>
          </div>
        </div>` : ""}
      </div>`;
    }));

    if (!orders.length && !bills.length && !payments.length) {
      return `<div class="detail-section"><h4>Ledger</h4><p style="color:var(--muted);font-size:13px;">No ledger entries yet.</p>${sections[0]}</div>`;
    }
    return `<div class="detail-section"><h4>Ledger</h4><p class="vled-hint">Bill-wise statement — expand a row for details</p>${sections.join("")}</div>`;
  }

  function renderLedgerGroup(title, items, _key, rowFn) {
    if (!items.length) return "";
    return `<div class="vled-group"><div class="vled-group-title">${ctx.esc(title)}</div>${items.map(rowFn).join("")}</div>`;
  }

  function toggleLedgerRow(id) {
    vendorLedgerExpanded = vendorLedgerExpanded === id ? null : id;
    const wrap = document.getElementById("vendor-ledger-wrap");
    if (wrap && currentVendorId) wrap.innerHTML = renderVendorStatement(currentVendorId);
  }

  function openOrderFromLedger(entryId) {
    const e = vendorLedger.find(x => x.id === entryId);
    if (!e) return;
    const d = e.details || {};
    if (!d.vendor_order_id) return ctx.toast?.("Order link missing", "error");
    const bucket = d.bucket === "cancelled" ? "cancelled" : d.bucket === "placed" ? "placed" : "billed";
    ctx.closeDetail?.();
    ctx.showView?.("orders");
    VendorOrders.openDetail(d.vendor_order_id, bucket, d.vendor_id || currentVendorId || undefined);
  }

  async function openBillDebitNotes(vendorId, receiptId) {
    if (typeof DebitNotes === "undefined") return ctx.toast?.("Debit notes module failed — hard refresh", "error");
    await DebitNotes.openForReceipt({
      vendorId,
      receiptId,
      receivingLines: [],
      onDone: async () => { await refreshVendorLedger(vendorId); },
    });
  }

  function settlePayment(vendorId) {
    if (typeof Finance === "undefined") return;
    Finance.showApFromVendor(vendorId);
    setTimeout(() => Finance.openSettle?.(), 400);
  }

  function openDebitNote(noteId) {
    DebitNotes.openEdit(noteId, () => { if (currentVendorId) openDetail(currentVendorId); });
  }

  function openLedgerEntry(entryId) {
    const e = vendorLedger.find(x => x.id === entryId);
    if (!e) return;
    vendorLedgerExpanded = entryId;
    const wrap = document.getElementById("vendor-ledger-wrap");
    if (wrap && currentVendorId) wrap.innerHTML = renderVendorStatement(currentVendorId);
    // keep legacy deep-links for activity
    const d = e.details || {};
    if (e.event_type === "debit_note" && d.debit_note_id) {
      openDebitNote(d.debit_note_id);
    }
  }

  function openWizard() {
    const cities = ctx.getCities();
    if (!cities.length) {
      ctx.toast("Add cities in Setup first", "error");
      return;
    }
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
    document.getElementById("vendor-wizard-steps").innerHTML = ["Business Info", "Review & Create"].map((label, i) => {
      const n = i + 1;
      const cls = n < wizardStep ? "done" : n === wizardStep ? "active" : "";
      return `<div class="step ${cls}"><div class="step-num">${n < wizardStep ? "✓" : n}</div>${label}</div>`;
    }).join("");

    const body = document.getElementById("vendor-wizard-body");
    const footer = document.getElementById("vendor-wizard-footer");

    if (wizardStep === 1) {
      body.innerHTML = `<div style="display:grid;gap:16px;">
        <div><label class="label">Business Name *</label><input id="vw-business_name" class="input" value="${ctx.esc(wizardForm.business_name)}" placeholder="e.g. ABC Supplies" /></div>
        <div><label class="label">Primary Phone *</label><input id="vw-phone" class="input" type="tel" maxlength="10" value="${ctx.esc(wizardForm.phone)}" placeholder="10-digit mobile" /></div>
        <div><label class="label">City *</label>
          <select id="vw-city_id" class="input"><option value="">— Select city —</option>
            ${cities.map(c => `<option value="${c.id}" ${wizardForm.city_id == c.id ? "selected" : ""}>${ctx.esc(c.name)}</option>`).join("")}
          </select></div>
        <div><label class="label">Person Name</label><input id="vw-person_name" class="input" value="${ctx.esc(wizardForm.person_name)}" placeholder="Optional" /></div>
        <div><label class="label">Secondary Phone</label><input id="vw-secondary_phone" class="input" type="tel" maxlength="10" value="${ctx.esc(wizardForm.secondary_phone)}" /></div>
        <div><label class="label">Alias</label><input id="vw-alias" class="input" value="${ctx.esc(wizardForm.alias)}" placeholder="Short search name" /></div>
        <div><label class="label">GST Number</label><input id="vw-gst_number" class="input" value="${ctx.esc(wizardForm.gst_number)}" /></div>
        <div><label class="label">Address</label><textarea id="vw-address" class="input" rows="2">${ctx.esc(wizardForm.address)}</textarea></div>
      </div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="Vendors.closeWizard()">Cancel</button>
        <button class="btn btn-primary" style="flex:1;" onclick="Vendors.wizardNext()">Review →</button>`;
    } else if (wizardStep === 2) {
      const city = cities.find(c => c.id == wizardForm.city_id);
      body.innerHTML = `<div class="review-grid">
        ${ctx.reviewRow("Business", wizardForm.business_name)}
        ${ctx.reviewRow("Phone", wizardForm.phone)}
        ${ctx.reviewRow("City", city?.name)}
        ${ctx.reviewRow("Person", wizardForm.person_name)}
        ${ctx.reviewRow("Secondary", wizardForm.secondary_phone)}
        ${ctx.reviewRow("Alias", wizardForm.alias)}
        ${ctx.reviewRow("GST", wizardForm.gst_number)}
        ${ctx.reviewRow("Address", wizardForm.address)}
      </div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="Vendors.wizardBack()">← Back</button>
        <button class="btn btn-primary" style="flex:1;" id="vendor-create-btn" onclick="Vendors.create()">Create Vendor</button>`;
    } else if (wizardStep === 3) {
      body.innerHTML = `<div style="text-align:center;padding:24px 0;">
        <div class="success-icon">✓</div><h3 style="margin:0 0 8px;">Vendor Created!</h3>
        <p style="color:var(--muted);">${ctx.esc(wizardForm._result?.business_name)}</p>
      </div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="Vendors.openWizard()">+ Another</button>
        <button class="btn btn-primary" style="flex:1;" onclick="Vendors.closeWizard()">Done</button>`;
    }
  }

  function collectWizard() {
    ["business_name","phone","person_name","secondary_phone","alias","gst_number","address"].forEach(k => {
      const el = document.getElementById(`vw-${k}`);
      if (el) wizardForm[k] = el.value.trim();
    });
    const cityEl = document.getElementById("vw-city_id");
    if (cityEl) wizardForm.city_id = parseCityId(cityEl.value);
  }

  function wizardBack() { collectWizard(); wizardStep = 1; renderWizard(); }

  function wizardNext() {
    collectWizard();
    if (!wizardForm.business_name) return ctx.toast("Business name required", "error");
    const phone = (wizardForm.phone || "").replace(/\D/g, "");
    if (phone.length !== 10) return ctx.toast("Phone must be 10 digits", "error");
    wizardForm.phone = phone;
    if (!wizardForm.city_id) return ctx.toast("Please select a city", "error");
    wizardStep = 2;
    renderWizard();
  }

  async function create() {
    const cityId = parseCityId(wizardForm.city_id);
    if (!wizardForm.business_name || !wizardForm.phone) return ctx.toast("Go back and fill required fields", "error");
    if (!cityId) return ctx.toast("Please select a city", "error");
    const btn = document.getElementById("vendor-create-btn");
    if (btn) btn.disabled = true;
    try {
      const result = await ctx.api("/vendors", { method: "POST", body: JSON.stringify({
        business_name: wizardForm.business_name,
        phone: wizardForm.phone,
        city_id: cityId,
        person_name: wizardForm.person_name || null,
        secondary_phone: wizardForm.secondary_phone || null,
        alias: wizardForm.alias || null,
        gst_number: wizardForm.gst_number || null,
        address: wizardForm.address || null,
      })});
      wizardForm._result = result;
      wizardStep = 3;
      renderWizard();
      await load();
      ctx.invalidateCache?.("/vendors");
      ctx.invalidateCache?.("/stats");
      if (ctx.refreshStats) await ctx.refreshStats();
      ctx.toast("Vendor created", "success");
    } catch (e) {
      ctx.toast(e.message, "error");
      if (btn) btn.disabled = false;
    }
  }

  async function openEdit(id) {
    const v = await ctx.api(`/vendors/${id}`);
    editingId = id;
    const cities = ctx.getCities();
    document.getElementById("vendor-edit-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Business Name *</label><input id="ve-business_name" class="input" value="${ctx.esc(v.business_name)}" /></div>
        <div><label class="label">Primary Phone *</label><input id="ve-phone" class="input" value="${ctx.esc(v.phone)}" /></div>
        <div><label class="label">City *</label>
          <select id="ve-city_id" class="input"><option value="">— Select city —</option>
            ${cities.map(c => `<option value="${c.id}" ${v.city_id == c.id ? "selected" : ""}>${ctx.esc(c.name)}</option>`).join("")}
          </select></div>
        <div><label class="label">Person Name</label><input id="ve-person_name" class="input" value="${ctx.esc(v.person_name || "")}" /></div>
        <div><label class="label">Secondary Phone</label><input id="ve-secondary_phone" class="input" value="${ctx.esc(v.secondary_phone || "")}" /></div>
        <div><label class="label">Alias</label><input id="ve-alias" class="input" value="${ctx.esc(v.alias || "")}" /></div>
        <div><label class="label">GST</label><input id="ve-gst_number" class="input" value="${ctx.esc(v.gst_number || "")}" /></div>
        <div><label class="label">Address</label><textarea id="ve-address" class="input" rows="2">${ctx.esc(v.address || "")}</textarea></div>
      </div>`;
    document.getElementById("vendor-edit-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="Vendors.closeEdit()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Vendors.save()">Save Changes</button>`;
    document.getElementById("vendor-edit-modal").classList.remove("hidden");
  }

  function closeEdit() {
    document.getElementById("vendor-edit-modal").classList.add("hidden");
    editingId = null;
  }

  async function save() {
    if (!editingId) return;
    const cityId = parseCityId(document.getElementById("ve-city_id").value);
    if (!cityId) return ctx.toast("Please select a city", "error");
    try {
      await ctx.api(`/vendors/${editingId}`, { method: "PATCH", body: JSON.stringify({
        business_name: document.getElementById("ve-business_name").value.trim(),
        phone: document.getElementById("ve-phone").value.trim(),
        city_id: cityId,
        person_name: document.getElementById("ve-person_name").value.trim() || null,
        secondary_phone: document.getElementById("ve-secondary_phone").value.trim() || null,
        alias: document.getElementById("ve-alias").value.trim() || null,
        gst_number: document.getElementById("ve-gst_number").value.trim() || null,
        address: document.getElementById("ve-address").value.trim() || null,
      })});
      const id = editingId;
      closeEdit();
      App.closeDetail();
      await load();
      ctx.toast("Vendor updated", "success");
      openDetail(id);
    } catch (e) { ctx.toast(e.message, "error"); }
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

  function createOrder(vendorId) {
    App.closeDetail();
    App.showView("orders");
    App.setOrdersType("vendor");
    VendorOrders.showCreateMenuFromVendor(vendorId);
  }

  return {
    init, load, reload, openDetail, openLedgerEntry, openDebitNote,
    toggleLedgerRow, openOrderFromLedger, openBillDebitNotes, settlePayment,
    openWizard, closeWizard, wizardBack, wizardNext, create, openEdit, closeEdit, save, deleteVendor, createOrder,
  };
})();
