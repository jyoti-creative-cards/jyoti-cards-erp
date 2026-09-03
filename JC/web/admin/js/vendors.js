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
    { key: "vendor_number", label: "#", get: v => v.vendor_number || 0 },
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
    if (typeof App !== "undefined" && App.renderPeopleVendorSearch) App.renderPeopleVendorSearch();
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
      const canAdd = !!ctx.canWrite?.("vendors");
      el.innerHTML = (typeof HubUI !== "undefined" ? HubUI.emptyState : OrdersUI.emptyState)({
        title: "No vendors yet",
        sub: "Add suppliers you buy from.",
        ctaHtml: canAdd
          ? `<button class="btn btn-primary btn-lg" onclick="Vendors.openWizard()">+ Add First Vendor</button>`
          : "",
      });
      return;
    }
    const rows = TableUtils.apply(vendors, "vendors", VENDOR_COLS);
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("vendors", VENDOR_COLS)}<tbody>
      ${rows.map(v => `<tr class="clickable" onclick="Vendors.openDetail(${v.id})">
        <td style="text-align:center;color:var(--muted);font-size:12px;font-weight:700;white-space:nowrap;padding-right:4px;">${v.vendor_number ? `#${v.vendor_number}` : "—"}</td>
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
  let vendorPayModeFilter = "all"; // "all" | "cash" | "bank"

  function setVendorPayModeFilter(mode) {
    vendorPayModeFilter = mode;
    const wrap = document.getElementById("vendor-ledger-wrap");
    if (wrap && currentVendorId) wrap.innerHTML = renderVendorStatement(currentVendorId);
  }

  function payModeBucket(mode) {
    if (!mode) return null;
    return /cash/i.test(mode) ? "cash" : "bank";
  }

  function fmtMoney(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });
  }

  async function openDetail(id, opts = {}) {
    currentVendorId = id;
    vendorLedgerExpanded = null;
    vendorAp = null;
    // legacy tab names → activity
    let tab = opts.tab || "activity";
    if (tab === "orders" || tab === "money") tab = "activity";
    const v = await ctx.api(`/vendors/${id}`);
    vendorLedger = [];
    ctx.openDetail(v.business_name, `
      <div class="profile-hero" style="margin:-24px -24px 16px;border-radius:0;">
        <h2>${v.vendor_number ? `<span style="color:var(--muted);font-size:16px;font-weight:600;margin-right:6px;">#${v.vendor_number}</span>` : ""}${ctx.esc(v.business_name)}</h2>
        <p>${ctx.esc(v.person_name || "No contact person")}</p>
        <div class="profile-meta">
          <span class="badge badge-blue">${ctx.esc(v.phone)}</span>
          ${v.alias ? `<span class="badge badge-gray">${ctx.esc(v.alias)}</span>` : ""}
          <span class="badge badge-green">${ctx.esc(v.city_name || "—")}</span>
        </div>
      </div>
      <div class="ord-mode-toggle" role="tablist" style="margin-bottom:16px;">
        <button type="button" class="ord-mode-btn ${tab === "activity" ? "active" : ""}" onclick="Vendors.openDetail(${v.id},{tab:'activity'})">Activity</button>
        <button type="button" class="ord-mode-btn ${tab === "profile" ? "active" : ""}" onclick="Vendors.openDetail(${v.id},{tab:'profile'})">Profile</button>
      </div>
      ${tab === "activity" ? `
        <div id="vendor-summary-wrap" class="person-summary"></div>
        <div id="vendor-actions-wrap" class="person-actions"></div>
        <div id="vendor-ledger-wrap"><p style="color:var(--muted);font-size:13px;">Loading activity…</p></div>
      ` : ""}
      ${tab === "profile" ? `
        <div class="review-grid">
          ${ctx.reviewRow("Secondary Phone", v.secondary_phone)}
          ${ctx.reviewRow("GST Number", v.gst_number)}
          ${ctx.reviewRow("Address", v.address)}
          ${ctx.reviewRow("Created", ctx.fmtDate(v.created_at))}
          ${ctx.reviewRow("Last Updated", ctx.fmtDate(v.updated_at))}
        </div>
        ${ctx.changeHistoryTable ? ctx.changeHistoryTable(v.change_history) : ""}
      ` : ""}`,
      `${ctx.canWrite?.("vendors") ? `<button class="btn btn-danger btn-sm" onclick="Vendors.deleteVendor(${v.id})">Delete</button>
       <button class="btn btn-secondary btn-sm" onclick="Vendors.openEdit(${v.id})">Edit</button>` : ""}
       <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "lg"
    );
    if (tab === "activity") await refreshVendorLedger(id);
  }

  function renderVendorActions(id) {
    const el = document.getElementById("vendor-actions-wrap");
    if (!el) return;
    const canBuy = !!(ctx.canWrite?.("vendors") || ctx.canWrite?.("vendor_orders"));
    const canSeeAp = !!(ctx.isAdmin?.() || ctx.can?.("ap.read"));
    const canPayAp = !!(ctx.isAdmin?.() || ctx.can?.("ap.write"));
    const due = canSeeAp && vendorAp && Number(vendorAp.outstanding) > 0;
    const bits = [];
    // Everyday jobs stay visible — place first, or goods already here (offline).
    if (canBuy) {
      bits.push(`<button class="btn btn-primary btn-sm" onclick="Vendors.placeOrder(${id})">Order</button>`);
      bits.push(`<button class="btn btn-secondary btn-sm" onclick="Vendors.stockIn(${id})">Stock in</button>`);
      bits.push(`<button class="btn btn-secondary btn-sm" onclick="Vendors.openBuying(${id})">Orders</button>`);
    }
    if (due && canPayAp) {
      bits.push(`<button class="btn btn-secondary btn-sm" onclick="Vendors.settlePayment(${id})">Pay</button>`);
    }
    const more = [];
    if (canBuy) {
      more.push(`<button type="button" onclick="Vendors.receiveGoods(${id})">Receive against order</button>`);
    }
    if (canPayAp && !due) more.push(`<button type="button" onclick="Vendors.settlePayment(${id})">Pay</button>`);
    if (canSeeAp) more.push(`<button type="button" onclick="Vendors.openMoney(${id})">Money statement</button>`);
    if (ctx.isAdmin?.()) {
      more.push(`<button type="button" onclick="Vendors.setOpeningBalance(${id})">Opening</button>`);
    }
    if (more.length) {
      bits.push(`<details class="person-more"><summary>More</summary><div class="person-more-menu">${more.join("")}</div></details>`);
    }
    el.innerHTML = bits.join("") || "";
  }

  async function refreshVendorLedger(id) {
    const wrap = document.getElementById("vendor-ledger-wrap");
    const sumWrap = document.getElementById("vendor-summary-wrap");
    try {
      const [ledgerRes, ap] = await Promise.all([
        ctx.api(`/vendors/${id}/ledger`, {}, 0),
        (ctx.isAdmin?.() || ctx.can?.("ap.read")) ? ctx.api(`/accounts-payable/vendor/${id}`, {}, 0).catch(() => null) : Promise.resolve(null),
      ]);
      vendorLedger = ledgerRes.items || [];
      vendorAp = ap;
      if (sumWrap) {
        if (ap) {
          sumWrap.innerHTML = `<div class="person-summary-grid">
            <div><span class="person-summary-label">Due</span><strong>${fmtMoney(ap.outstanding)}</strong></div>
            <div><span class="person-summary-label">Bills</span><strong>${fmtMoney(ap.bill_total)}</strong></div>
            <div><span class="person-summary-label">Paid</span><strong>${fmtMoney(ap.payment_total)}</strong></div>
            <div><span class="person-summary-label">Opening</span><strong>${fmtMoney(ap.opening_total || "0")}</strong></div>
          </div>`;
        } else {
          sumWrap.innerHTML = "";
        }
      }
      renderVendorActions(id);
      if (wrap) wrap.innerHTML = renderVendorStatement(id);
    } catch (e) {
      if (wrap) wrap.innerHTML = `<p style="color:var(--danger);font-size:13px;">${ctx.esc(e.message)}</p>`;
    }
  }

  function renderVendorStatement(vendorId) {
    const orders = vendorLedger.filter(e => e.event_type === "order_placed" || e.event_type === "order_cancelled");
    const bills = vendorLedger.filter(e => e.event_type === "stock_received");
    const payments = vendorLedger.filter(e => e.event_type === "ap_payment");
    // "stock_received" only carries the receipt note; the actual bill_number/amount
    // live on a separate "vendor_bill" event once billed — merge by receipt_id so
    // the ledger card shows the real bill number instead of falling back to the id.
    const billInfoByReceipt = {};
    for (const e of vendorLedger.filter(x => x.event_type === "vendor_bill")) {
      const rid = e.details?.receipt_id;
      if (rid) billInfoByReceipt[rid] = e.details || {};
    }
    // Nest debit notes under matching bill/receipt
    const dnsByReceipt = {};
    for (const e of vendorLedger.filter(x => x.event_type === "debit_note")) {
      const rid = e.details?.receipt_id;
      if (!rid) continue;
      (dnsByReceipt[rid] || (dnsByReceipt[rid] = [])).push(e);
    }

    const sections = [];

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
            ${lines.map(l => `<tr><td>${ctx.esc(ctx.productIdLabel(l))}</td><td>${l.quantity ?? "—"}</td><td>${fmtMoney(l.buying_price)}</td></tr>`).join("") || "<tr><td colspan=3>—</td></tr>"}
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
      const bi = rid ? (billInfoByReceipt[rid] || {}) : {};
      const dns = rid ? (dnsByReceipt[rid] || []) : [];
      const lines = d.lines || [];
      // Always lead with the receipt note number entered at receive time — the
      // vendor's bill number (once billed) is shown alongside, not instead of it.
      const title = d.order_receipt_number ? `Receipt ${ctx.esc(d.order_receipt_number)}` : `Receipt #${rid || d.placement_id || ""}`;
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="Vendors.toggleLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">${title}${bi.bill_number ? ` · Bill ${ctx.esc(bi.bill_number)}` : ""}</div>
            <div class="vled-meta">${ctx.fmtDate(e.occurred_at)} · ${lines.length} lines
              ${bi.bill_amount != null ? ` · Bill ${fmtMoney(bi.bill_amount)}` : ""}
              ${dns.length ? ` · ${dns.length} debit note${dns.length === 1 ? "" : "s"}` : ""}
              ${bi.net_payable != null ? ` · Net ${fmtMoney(bi.net_payable)}` : ""}</div>
          </div>
          <span class="vled-chevron">${open ? "▾" : "▸"}</span>
        </button>
        ${open ? `<div class="vled-body">
          <table class="data fin-mini"><thead><tr><th>Product</th><th>Recv</th><th>Billed</th></tr></thead><tbody>
            ${lines.map(l => `<tr><td>${ctx.esc(ctx.productIdLabel(l))}</td><td>${l.quantity_received ?? l.quantity ?? "—"}</td><td>${l.quantity_billed ?? "—"}</td></tr>`).join("") || "<tr><td colspan=3>—</td></tr>"}
          </tbody></table>
          ${dns.length ? `<div class="fin-dn-block"><div class="fin-dn-title">Debit notes</div>
            ${dns.map(dn => {
              const nd = dn.details || {};
              return `<div class="fin-dn-row">
                <div><strong>${ctx.esc(nd.our_product_id ? ctx.productIdLabel(nd) : (nd.note_type || "Note"))}${nd.quantity != null ? ` × ${nd.quantity}` : ""}</strong>
                  ${nd.notes ? `<div class="fin-dn-note">${ctx.esc(nd.notes)}</div>` : ""}
                </div>
                <strong>${fmtMoney(nd.amount)}</strong>
              </div>`;
            }).join("")}
          </div>` : ""}
          <div class="vled-actions">
            ${rid ? `<button class="btn btn-primary btn-sm" onclick="VendorOrders.openReceiptDoc(${rid})">Bill Receipt</button>` : ""}
            ${(bi.bill_file_url || d.bill_file_url) ? `<button class="btn btn-secondary btn-sm" onclick="window.open('${ctx.esc(bi.bill_file_url || d.bill_file_url)}','_blank')">Vendor Bill</button>` : ""}
            ${rid ? `<button class="btn btn-secondary btn-sm" onclick="Vendors.openBillDebitNotes(${vendorId}, ${rid})">Debit Note</button>` : ""}
            <button class="btn btn-secondary btn-sm" onclick="Vendors.openOrderFromLedger('${e.id}')">Open in Orders</button>
          </div>
        </div>` : ""}
      </div>`;
    }));

    const paymentsFiltered = vendorPayModeFilter === "all"
      ? payments
      : payments.filter(e => payModeBucket(e.details?.payment_mode) === vendorPayModeFilter);
    const payFilterChips = payments.length ? `<div class="vled-group">
      <div class="vled-group-title" style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <span>Payments</span>
        <span class="ord-mode-toggle" style="margin:0;">
          <button type="button" class="ord-mode-btn${vendorPayModeFilter === "all" ? " active" : ""}" onclick="Vendors.setVendorPayModeFilter('all')">All</button>
          <button type="button" class="ord-mode-btn${vendorPayModeFilter === "cash" ? " active" : ""}" onclick="Vendors.setVendorPayModeFilter('cash')">Cash</button>
          <button type="button" class="ord-mode-btn${vendorPayModeFilter === "bank" ? " active" : ""}" onclick="Vendors.setVendorPayModeFilter('bank')">Bank</button>
        </span>
      </div>
    </div>` : "";
    const payEmptyHtml = payments.length && !paymentsFiltered.length
      ? `<p class="vo-muted" style="margin:0 0 12px;">No ${vendorPayModeFilter} payments.</p>` : "";
    sections.push(payFilterChips + payEmptyHtml + renderLedgerGroup("", paymentsFiltered, "pay", (e) => {
      const d = e.details || {};
      const open = vendorLedgerExpanded === e.id;
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="Vendors.toggleLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">Payment ${ctx.esc(d.payment_ref || "")}${d.payment_mode ? ` <span class="badge badge-blue" style="font-size:10px;">${ctx.esc(d.payment_mode)}</span>` : ""}</div>
            <div class="vled-meta">${ctx.fmtDate(e.occurred_at)} · ${fmtMoney(d.amount)}${d.comment ? ` · ${ctx.esc(d.comment)}` : ""}</div>
          </div>
          <span class="vled-chevron">${open ? "▾" : "▸"}</span>
        </button>
        ${open ? `<div class="vled-body">
          <div class="review-grid">
            ${ctx.reviewRow("Reference", d.payment_ref || "—")}
            ${ctx.reviewRow("Amount", fmtMoney(d.amount))}
            ${d.payment_mode ? ctx.reviewRow("Mode", d.payment_mode) : ""}
            ${d.comment ? ctx.reviewRow("Comment", d.comment) : ""}
          </div>
          <div class="vled-actions">
            ${d.payment_receipt_url ? `<a class="btn btn-secondary btn-sm" href="${ctx.esc(d.payment_receipt_url)}" target="_blank">Payment receipt</a>` : ""}
            ${(ctx.isAdmin?.() || ctx.can?.("ap.write")) ? `<button class="btn btn-primary btn-sm" onclick="Vendors.settlePayment(${vendorId})">Pay again</button>` : ""}
            ${ctx.isAdmin?.() && d.ledger_entry_id && !d.reversed ? `
              <button class="btn btn-secondary btn-sm" onclick="Finance.undoApPayment(${d.ledger_entry_id},'reverse',${vendorId})">Reverse</button>
              <button class="btn btn-ghost btn-sm" onclick="Finance.undoApPayment(${d.ledger_entry_id},'void',${vendorId})">Void</button>
            ` : ""}
            ${d.reversed ? `<span class="badge badge-amber">Reversed</span>` : ""}
            <button class="btn btn-secondary btn-sm" onclick="Finance.showApFromVendor(${vendorId})">Open AP</button>
          </div>
        </div>` : ""}
      </div>`;
    }));

    if (!orders.length && !bills.length && !payments.length) {
      return `<div class="detail-section"><h4>Activity</h4><p style="color:var(--muted);font-size:13px;">Nothing yet. Place an order or receive goods.</p></div>`;
    }
    return `<div class="detail-section"><h4>Activity</h4>${sections.join("")}</div>`;
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
    ctx.showView?.("buying");
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
    if (!ctx.isAdmin?.() && !ctx.can?.("ap.write")) return ctx.toast?.("Not permitted", "error");
    App.closeDetail();
    App.showView("money");
    Finance.openVendorAp?.(vendorId, { settle: true });
  }

  async function setOpeningBalance(vendorId) {
    if (!ctx.isAdmin?.()) return ctx.toast?.("Admin only", "error");
    const ap = vendorAp;
    const today = new Date().toISOString().slice(0, 10);
    ctx.openDetail("Opening", `
      <p style="color:var(--muted);font-size:13px;margin:0 0 16px;">Tally start you owed this vendor. Use 0 to clear. Not Due (Due = opening + bills − paid).</p>
      <label class="label">Opening (₹)</label>
      <input type="number" step="0.01" min="0" class="input" id="vob-amt" value="${ctx.esc(ap?.opening_total || "0")}" style="margin-bottom:12px;" />
      <label class="label">As on date</label>
      <input type="date" class="input" id="vob-as-on" value="${ctx.esc(ap?.opening_as_on || today)}" />
    `, `
      <button class="btn btn-secondary" onclick="App.closeDetail();Vendors.openDetail(${vendorId},{tab:'activity'})">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Vendors.saveOpeningBalance(${vendorId})">Save</button>
    `, "sm");
  }

  async function saveOpeningBalance(vendorId) {
    if (!ctx.isAdmin?.()) return;
    const amount = parseFloat(document.getElementById("vob-amt")?.value || "0");
    const asOn = (document.getElementById("vob-as-on")?.value || "").trim();
    if (!Number.isFinite(amount) || amount < 0) return ctx.toast("Enter a valid amount", "error");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(asOn)) return ctx.toast("Pick a valid date", "error");
    ctx.showLoading?.();
    try {
      await ctx.api(`/accounts-payable/vendor/${vendorId}/opening-balance`, {
        method: "POST",
        body: JSON.stringify({ amount, as_on: asOn }),
      });
      ctx.invalidateCache?.("/vendors");
      ctx.invalidateCache?.("/accounts-payable");
      ctx.toast("Opening saved", "success");
      await openDetail(vendorId, { tab: "activity" });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
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
              <select id="vw-city_id" class="input">
                <option value="">— Optional —</option>
                ${cities.map(c => `<option value="${c.id}" ${wizardForm.city_id == c.id ? "selected" : ""}>${ctx.esc(cityOptionLabel(c))}</option>`).join("")}
              </select>
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
              <div><label class="label">Billing notes</label><textarea id="ve-billing_notes" class="input" rows="3">${ctx.esc(billing.billing_notes || "")}</textarea></div>
            </div>
          </div>
        ` : ""}
      </div>`;
    document.getElementById("vendor-edit-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="Vendors.closeEdit()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Vendors.save()">Save Changes</button>`;
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
    const billingNotes = ctx.isAdmin?.() ? (document.getElementById("ve-billing_notes").value.trim() || null) : null;
    if (ctx.isAdmin?.()) {
      if (!Number.isFinite(billingPct) || billingPct <= 0 || billingPct > 100) return ctx.toast("Billing % must be between 0.01 and 100", "error");
      if (!Number.isFinite(additionalCharge) || additionalCharge < 0) return ctx.toast("Additional charge must be 0 or more", "error");
      if (!additionalChargeLabel) return ctx.toast("Additional charge label required", "error");
      if (additionalChargeLabel.length > 50) return ctx.toast("Additional charge label too long", "error");
      if (!Number.isFinite(discountPct) || discountPct < 0 || discountPct > 100) return ctx.toast("Discount % must be between 0 and 100", "error");
      if (!Number.isFinite(gstRatePct) || gstRatePct < 0 || gstRatePct > 100) return ctx.toast("GST rate % must be between 0 and 100", "error");
    }
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
          billing_notes: billingNotes,
        })});
      }
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

  return {
    init, load, reload, openDetail, openLedgerEntry, openDebitNote,
    toggleLedgerRow, openOrderFromLedger, openBillDebitNotes, settlePayment, setOpeningBalance, saveOpeningBalance,
    setVendorPayModeFilter,
    openWizard, closeWizard, wizardBack, wizardNext, create, openEdit, closeEdit, save, deleteVendor,
    placeOrder, stockIn, createOrder, receiveGoods, openMoney, openBuying,
    onWizardCityChange, onEditCityChange, finishOpen, finishPlaceOrder, finishAddProducts,
  };
})();
