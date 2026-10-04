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
    } catch (e) {
      // Several callers (search debounce, tab switch) fire this without awaiting/
      // catching — an API failure here used to be a silent unhandled rejection
      // with the list just left stale and no explanation to the user.
      ctx.toast?.(e.message || "Could not load vendors", "error");
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
    paintVendorSummary();
    const wrap = document.getElementById("vendor-ledger-wrap");
    if (wrap && currentVendorId) wrap.innerHTML = renderVendorStatement(currentVendorId);
  }

  function paintVendorSummary() {
    const sumWrap = document.getElementById("vendor-summary-wrap");
    if (!sumWrap) return;
    if (!vendorAp) {
      sumWrap.innerHTML = "";
      return;
    }
    const channel = vendorPayModeFilter;
    if (channel === "all") {
      sumWrap.innerHTML = `<div class="person-summary-grid">
        <div><span class="person-summary-label">Due</span><strong>${fmtMoney(vendorAp.outstanding)}</strong></div>
        <div><span class="person-summary-label">Bills</span><strong>${fmtMoney(vendorAp.bill_total)}</strong></div>
        <div><span class="person-summary-label">Paid</span><strong>${fmtMoney(vendorAp.payment_total)}</strong></div>
        <div><span class="person-summary-label">Opening</span><strong>${fmtMoney(vendorAp.opening_total || "0")}</strong></div>
      </div>`;
      return;
    }
    const totals = vendorChannelTotals(channel);
    const word = channel === "bank" ? "Bank" : "Cash";
    sumWrap.innerHTML = `<div class="person-summary-grid">
      <div><span class="person-summary-label">${word} due</span><strong>${fmtMoney(totals.due)}</strong></div>
      <div><span class="person-summary-label">${word} bills</span><strong>${fmtMoney(totals.bills)}</strong></div>
      <div><span class="person-summary-label">${word} paid</span><strong>${fmtMoney(totals.paid)}</strong></div>
      <div><span class="person-summary-label">Opening</span><strong>—</strong></div>
    </div>`;
  }

  function vendorChannelTotals(channel) {
    const billInfoByReceipt = {};
    for (const e of vendorLedger.filter(x => x.event_type === "vendor_bill")) {
      const rid = e.details?.receipt_id;
      if (rid) billInfoByReceipt[rid] = e.details || {};
    }
    let bills = 0;
    for (const e of vendorLedger.filter(x => x.event_type === "stock_received")) {
      const ch = billChannels(billInfoByReceipt[e.details?.receipt_id]);
      const part = channel === "cash" ? ch.cash : ch.bank;
      if (part != null) bills += part;
    }
    let paid = 0;
    for (const e of vendorLedger.filter(x => x.event_type === "ap_payment")) {
      const d = e.details || {};
      if (d.reversed) continue;
      if (payModeBucket(d.payment_mode) !== channel) continue;
      paid += Number(d.amount) || 0;
    }
    return { bills, paid, due: bills - paid };
  }

  function payModeBucket(mode) {
    if (!mode) return null;
    return /cash/i.test(mode) ? "cash" : "bank";
  }

  function billChannels(details) {
    const d = details || {};
    const bank = Number(d.bank_amount);
    const cash = Number(d.cash_amount);
    return {
      bank: Number.isFinite(bank) && bank > 0 ? bank : null,
      cash: Number.isFinite(cash) && cash > 0 ? cash : null,
    };
  }

  function channelTags(channels) {
    const tags = [];
    if (channels.bank != null) tags.push(`<span class="badge badge-blue" style="font-size:10px;">Bank ${fmtMoney(channels.bank)}</span>`);
    if (channels.cash != null) tags.push(`<span class="badge badge-amber" style="font-size:10px;">Cash ${fmtMoney(channels.cash)}</span>`);
    return tags.join(" ");
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
    vendorPayModeFilter = "all";
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
    try {
      const [ledgerRes, ap] = await Promise.all([
        ctx.api(`/vendors/${id}/ledger`, {}, 0),
        (ctx.isAdmin?.() || ctx.can?.("ap.read")) ? ctx.api(`/accounts-payable/vendor/${id}`, {}, 0).catch(() => null) : Promise.resolve(null),
      ]);
      vendorLedger = ledgerRes.items || [];
      vendorAp = ap;
      paintVendorSummary();
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
    const channel = vendorPayModeFilter;
    const ordersShown = channel === "all" ? orders : [];
    const billsShown = channel === "all" ? bills : bills.filter(e => {
      const ch = billChannels(billInfoByReceipt[e.details?.receipt_id]);
      return channel === "cash" ? ch.cash != null : ch.bank != null;
    });

    sections.push(renderLedgerGroup("Orders placed", ordersShown, "order", (e) => {
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

    sections.push(renderLedgerGroup("Bills / received", billsShown, "bill", (e) => {
      const d = e.details || {};
      const open = vendorLedgerExpanded === e.id;
      const rid = d.receipt_id;
      const bi = rid ? (billInfoByReceipt[rid] || {}) : {};
      const dns = rid ? (dnsByReceipt[rid] || []) : [];
      const lines = d.lines || [];
      const channels = billChannels(bi);
      const tags = channel === "all"
        ? channelTags(channels)
        : (channel === "bank" && channels.bank != null
          ? `<span class="badge badge-blue" style="font-size:10px;">Bank ${fmtMoney(channels.bank)}</span>`
          : (channel === "cash" && channels.cash != null
            ? `<span class="badge badge-amber" style="font-size:10px;">Cash ${fmtMoney(channels.cash)}</span>`
            : ""));
      const channelAmt = channel === "bank" ? channels.bank : channel === "cash" ? channels.cash : null;
      // Always lead with the receipt note number entered at receive time — the
      // vendor's bill number (once billed) is shown alongside, not instead of it.
      const title = d.order_receipt_number ? `Receipt ${ctx.esc(d.order_receipt_number)}` : `Receipt #${rid || d.placement_id || ""}`;
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="Vendors.toggleLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">${title}${bi.bill_number ? ` · Bill ${ctx.esc(bi.bill_number)}` : ""} ${tags}</div>
            <div class="vled-meta">${ctx.fmtDate(e.occurred_at)} · ${lines.length} lines
              ${dns.length ? ` · ${dns.length} debit note${dns.length === 1 ? "" : "s"}` : ""}
              ${channelAmt != null ? ` · ${fmtMoney(channelAmt)}` : (bi.net_payable != null ? ` · Net ${fmtMoney(bi.net_payable)}` : "")}</div>
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

    const paymentsFiltered = channel === "all"
      ? payments
      : payments.filter(e => payModeBucket(e.details?.payment_mode) === channel);
    sections.push(renderLedgerGroup("Payments", paymentsFiltered, "pay", (e) => {
      const d = e.details || {};
      const open = vendorLedgerExpanded === e.id;
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="Vendors.toggleLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">Payment ${ctx.esc(d.payment_ref || "")}${payModeBucket(d.payment_mode) === "cash" ? ` <span class="badge badge-amber" style="font-size:10px;">Cash</span>` : ""}${payModeBucket(d.payment_mode) === "bank" ? ` <span class="badge badge-blue" style="font-size:10px;">Bank</span>` : ""}${d.payment_mode ? ` <span class="badge" style="font-size:10px;">${ctx.esc(d.payment_mode)}</span>` : ""}</div>
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

    const filterBar = `<div class="vled-group" style="margin-bottom:8px;">
      <div class="vled-group-title" style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <span>Show</span>
        <span class="ord-mode-toggle" style="margin:0;">
          <button type="button" class="ord-mode-btn${channel === "all" ? " active" : ""}" onclick="Vendors.setVendorPayModeFilter('all')">All</button>
          <button type="button" class="ord-mode-btn${channel === "bank" ? " active" : ""}" onclick="Vendors.setVendorPayModeFilter('bank')">Bank</button>
          <button type="button" class="ord-mode-btn${channel === "cash" ? " active" : ""}" onclick="Vendors.setVendorPayModeFilter('cash')">Cash</button>
        </span>
      </div>
    </div>`;
    if (!orders.length && !bills.length && !payments.length) {
      return `<div class="detail-section"><h4>Activity</h4><p style="color:var(--muted);font-size:13px;">Nothing yet. Place an order or receive goods.</p></div>`;
    }
    const nothingInFilter = channel !== "all" && !ordersShown.length && !billsShown.length && !paymentsFiltered.length;
    const emptyFilter = nothingInFilter
      ? `<p class="vo-muted" style="margin:0 0 12px;">No ${channel} entries.</p>` : "";
    return `<div class="detail-section"><h4>Activity</h4>${filterBar}${emptyFilter}${sections.join("")}</div>`;
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
    const vendorId = d.vendor_id || currentVendorId;
    if (!vendorId) return ctx.toast?.("Vendor not found", "error");
    // "stock_received" ledger entries (Bills / received cards) never carry
    // vendor_order_id — there's no VendorOrder for those in the one-receipt-per-bill
    // model — so this used to always toast "Order link missing" for that whole
    // section. openDetail resolves "received"/"billed" purely from the vendor id via
    // StockReceipt now, so no order id is needed for those buckets at all.
    let bucket;
    if (e.event_type === "stock_received") {
      const billed = vendorLedger.some(x => x.event_type === "vendor_bill" && x.details?.receipt_id === d.receipt_id);
      bucket = billed ? "billed" : "received";
    } else {
      bucket = d.bucket === "cancelled" ? "cancelled" : d.bucket === "placed" ? "placed" : "billed";
    }
    ctx.closeDetail?.();
    ctx.showView?.("buying");
    VendorOrders.openDetail(d.vendor_order_id || 0, bucket, vendorId);
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

