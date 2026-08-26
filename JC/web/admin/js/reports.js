/** Reports — Today / Books / Stock / Tax hub */
const Reports = (() => {
  let ctx = {};
  let mode = "today"; // today | books | stock | tax
  let chip = "daybook";
  let ledgerKind = "customers";
  const today = () => new Date().toISOString().slice(0, 10);
  let daybookDate = today();
  let fromDate = "";
  let toDate = "";
  let datePreset = "month"; // today | week | month | all | custom
  let lowThreshold = 10;
  let hubSearch = "";
  let ledgerDetail = null;
  let backLabel = "Back";
  let ageingSide = "ar";

  const MODES = [
    { id: "today", label: "Today" },
    { id: "books", label: "Books" },
    { id: "stock", label: "Stock" },
    { id: "tax", label: "Tax" },
  ];

  const CHIPS = {
    today: [
      { id: "daybook", label: "Daybook" },
      { id: "sales", label: "Sales bills" },
      { id: "purchases", label: "Purchase bills" },
      { id: "payments", label: "Payments" },
    ],
    books: [
      { id: "ledgers", label: "Ledgers" },
      { id: "ageing", label: "Due age" },
      { id: "customer-sales", label: "Customer sales" },
      { id: "vendor-purchases", label: "Vendor purchase" },
      { id: "item-sales", label: "Item sales" },
      { id: "item-purchases", label: "Item purchase" },
    ],
    stock: [
      { id: "valuation", label: "Valuation" },
      { id: "movers", label: "Fast / slow" },
      { id: "low", label: "Low stock" },
      { id: "returns", label: "Returns" },
      { id: "debit-notes", label: "Debit notes" },
    ],
    tax: [
      { id: "gst-sales", label: "GST sales" },
      { id: "gst-purchases", label: "GST purchase" },
      { id: "cashbook", label: "Cash book" },
      { id: "expense-cat", label: "Expense by category" },
      { id: "pnl", label: "Profit & loss" },
    ],
  };

  const LEDGER_KINDS = [
    { id: "customers", label: "Customers" },
    { id: "vendors", label: "Vendors" },
    { id: "products", label: "Products" },
    { id: "staff", label: "Staff" },
    { id: "routes", label: "Routes" },
    { id: "cash", label: "Cash" },
    { id: "freight", label: "Freight" },
    { id: "expenses", label: "Expense" },
  ];

  function init(context) { ctx = context; applyDatePreset(datePreset, false); }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc?.(String(val)) || String(val);
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function shiftDate(iso, days) {
    const d = new Date(`${iso || today()}T12:00:00`);
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  }

  function monthStart() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
  }

  function applyDatePreset(preset, reload = true) {
    datePreset = preset;
    if (preset === "today") { fromDate = today(); toDate = today(); }
    else if (preset === "week") { fromDate = shiftDate(today(), -6); toDate = today(); }
    else if (preset === "month") { fromDate = monthStart(); toDate = today(); }
    else if (preset === "all") { fromDate = ""; toDate = ""; }
    if (reload) loadChip();
  }

  let showQuestions = true;

  function showHub() {
    ledgerDetail = null;
    showQuestions = true;
    document.getElementById("reports-hub")?.classList.remove("hidden");
    document.getElementById("reports-ledger-detail")?.classList.add("hidden");
    renderChrome();
    renderQuestionsOrChip();
  }

  function pickQuestion(modeId, chipId) {
    showQuestions = false;
    mode = modeId;
    chip = chipId;
    hubSearch = "";
    if (modeId === "today") {
      daybookDate = today();
      applyDatePreset("today", false);
    }
    renderChrome();
    loadChip();
  }

  function renderQuestionsOrChip() {
    if (!showQuestions) {
      loadChip();
      return;
    }
    const body = document.getElementById("reports-body");
    if (!body) return;
    body.innerHTML = HubUI.tileGrid([
      { letter: "T", tag: "Today", title: "What moved today?", desc: "Daybook · sales · purchases · payments", onclick: "Reports.pickQuestion('today','daybook')", className: "setup-tile-records" },
      { letter: "B", tag: "Books", title: "Who owes us / we owe?", desc: "Due age · ledgers", onclick: "Reports.pickQuestion('books','ageing')", className: "setup-tile-billing" },
      { letter: "S", tag: "Stock", title: "What’s in stock?", desc: "Valuation · low stock · movers", onclick: "Reports.pickQuestion('stock','valuation')", className: "setup-tile-catalog" },
      { letter: "P", tag: "Tax", title: "Profit & tax?", desc: "P&L · GST · cash book", onclick: "Reports.pickQuestion('tax','pnl')", className: "setup-tile-delivery" },
    ], { style: "margin-top:8px;" })
      + `<p class="fin-muted" style="margin-top:16px;">Or pick a mode above (Today / Books / Stock / Tax).</p>`;
  }

  function setMode(m) {
    showQuestions = false;
    mode = m;
    chip = (CHIPS[m] || [])[0]?.id || "";
    hubSearch = "";
    if (m === "today") {
      daybookDate = today();
      applyDatePreset("today", false);
    } else if (datePreset === "today" && chip !== "daybook") {
      applyDatePreset("month", false);
    }
    renderChrome();
    loadChip();
  }

  function setChip(c) {
    showQuestions = false;
    chip = c;
    hubSearch = "";
    renderChrome();
    loadChip();
  }

  function setLedgerKind(k) {
    ledgerKind = k;
    hubSearch = "";
    renderChrome();
    loadChip();
  }

  function setHubSearch(v) {
    hubSearch = v || "";
    renderSearch();
    loadChip();
  }

  function matchParty(it) {
    if (!hubSearch.trim()) return true;
    return OrdersUI.partySearchRank({
      business_name: it.business_name || it.label || "",
      city_name: it.city_name || "",
      person_name: it.person_name || "",
      alias: it.alias || "",
      phone: it.phone || "",
      customer_label: it.label || it.customer_label || "",
      vendor_label: it.vendor_label || "",
    }, OrdersUI.partySearchTokens(hubSearch)) != null;
  }

  function matchSearch(...parts) {
    const q = hubSearch.trim().toLowerCase();
    if (!q) return true;
    return parts.some(p => String(p || "").toLowerCase().includes(q));
  }

  function renderChrome() {
    const bar = document.getElementById("reports-mode-bar");
    if (bar) {
      bar.innerHTML = MODES.map(m =>
        `<button type="button" class="ord-mode-btn${mode === m.id ? " active" : ""}" data-mode="${m.id}" onclick="Reports.setMode('${m.id}')">${m.label}</button>`
      ).join("");
    }
    const chipsHost = document.getElementById("reports-chips-host");
    if (chipsHost) {
      chipsHost.innerHTML = OrdersUI.stageChips({
        stages: CHIPS[mode] || [],
        active: chip,
        onclickFn: "Reports.setChip",
      });
    }
    const sub = document.getElementById("reports-subchips");
    if (sub) {
      if (mode === "books" && chip === "ledgers") {
        sub.classList.remove("hidden");
        sub.innerHTML = OrdersUI.stageChips({
          stages: LEDGER_KINDS,
          active: ledgerKind,
          onclickFn: "Reports.setLedgerKind",
        });
      } else if (mode === "books" && chip === "ageing") {
        sub.classList.remove("hidden");
        sub.innerHTML = OrdersUI.stageChips({
          stages: [{ id: "ar", label: "Customers due" }, { id: "ap", label: "Vendors due" }],
          active: ageingSide,
          onclickFn: "Reports.setAgeingSide",
        });
      } else {
        sub.classList.add("hidden");
        sub.innerHTML = "";
      }
    }
    const heroSub = document.getElementById("reports-hero-sub");
    if (heroSub) {
      const copy = {
        today: "What moved today — daybook, bills, payments",
        books: "Ledgers, who owes whom, sales & purchase by party or item",
        stock: "Value on hand, movers, returns and debit notes",
        tax: "GST registers, cash book, expenses, profit",
      };
      heroSub.textContent = copy[mode] || "Look up books, bills, and who did what";
    }
    renderDateBar();
    renderSearch();
  }

  function setAgeingSide(side) {
    ageingSide = side === "ap" ? "ap" : "ar";
    renderChrome();
    loadChip();
  }

  function renderDateBar() {
    const el = document.getElementById("reports-date-bar");
    if (!el) return;
    if (mode === "today" && chip === "daybook") {
      el.innerHTML = `<div class="rep-filters">
        <button type="button" class="btn btn-secondary btn-sm" onclick="Reports.shiftDay(-1)">←</button>
        <label class="label">Day<input type="date" class="input" id="rep-day" value="${ctx.esc(daybookDate)}" onchange="Reports.onDayChange(this.value)" /></label>
        <button type="button" class="btn btn-secondary btn-sm" onclick="Reports.shiftDay(1)">→</button>
        <button type="button" class="btn btn-secondary btn-sm" onclick="Reports.setDayToday()">Today</button>
      </div>`;
      return;
    }
    const noDates = chip === "valuation" || chip === "ageing"
      || (chip === "ledgers" && ["products", "staff", "routes", "freight"].includes(ledgerKind));
    if (noDates) {
      el.innerHTML = chip === "low"
        ? `<div class="rep-filters"><label class="label">Threshold<input type="number" class="input" id="rep-threshold" min="0" value="${lowThreshold}" onchange="Reports.onThresholdChange()" style="min-width:90px" /></label></div>`
        : "";
      return;
    }
    const presets = [
      { id: "today", label: "Today" },
      { id: "week", label: "7 days" },
      { id: "month", label: "This month" },
      { id: "all", label: "All" },
      { id: "custom", label: "Custom" },
    ];
    const showFromTo = datePreset !== "all";
    el.innerHTML = `<div class="rep-filters">
      <div class="rep-presets">
        ${presets.map(p => `<button type="button" class="rep-preset${datePreset === p.id ? " is-on" : ""}" onclick="Reports.setDatePreset('${p.id}')">${p.label}</button>`).join("")}
      </div>
      ${showFromTo ? `
        <label class="label">From<input type="date" class="input" id="rep-from" value="${ctx.esc(fromDate)}" onchange="Reports.onRangeChange()" /></label>
        <label class="label">To<input type="date" class="input" id="rep-to" value="${ctx.esc(toDate)}" onchange="Reports.onRangeChange()" /></label>
      ` : ""}
      ${chip === "low" ? `<label class="label">Threshold<input type="number" class="input" id="rep-threshold" min="0" value="${lowThreshold}" onchange="Reports.onThresholdChange()" style="min-width:90px" /></label>` : ""}
    </div>`;
  }

  function renderSearch() {
    const slot = document.getElementById("reports-search-slot");
    if (!slot) return;
    const caret = (typeof OrdersUI !== "undefined" && OrdersUI.captureSearchCaret)
      ? OrdersUI.captureSearchCaret("reports-hub-search") : null;
    const searchable = ["sales", "purchases", "payments", "ledgers", "ageing", "customer-sales", "vendor-purchases", "item-sales", "item-purchases", "valuation", "movers", "low", "returns", "debit-notes", "gst-sales", "gst-purchases", "cashbook", "expense-cat"].includes(chip);
    if (!searchable) { slot.innerHTML = ""; return; }
    const ph = chip === "ledgers"
      ? (ledgerKind === "staff" ? "Search staff…" : ledgerKind === "products" ? "Search products…" : ledgerKind === "customers" || ledgerKind === "vendors" ? "Search name, person, city…" : "Search…")
      : chip.includes("item") || chip === "valuation" || chip === "movers" || chip === "low" ? "Search product…"
        : chip === "ageing" ? "Search name, person, city…"
        : "Search…";
    slot.innerHTML = OrdersUI.searchBar({
      id: "reports-hub-search",
      value: hubSearch,
      placeholder: ph,
      oninput: "Reports.setHubSearch(this.value)",
    });
    if (caret) OrdersUI.restoreSearchCaret("reports-hub-search", caret);
  }

  function onDayChange(v) { daybookDate = v || today(); loadChip(); }
  function shiftDay(delta) { daybookDate = shiftDate(daybookDate, delta); renderDateBar(); loadChip(); }
  function setDayToday() { daybookDate = today(); renderDateBar(); loadChip(); }
  function setDatePreset(p) {
    if (p === "custom") { datePreset = "custom"; renderDateBar(); return; }
    applyDatePreset(p, true);
    renderDateBar();
  }
  function onRangeChange() {
    fromDate = document.getElementById("rep-from")?.value || "";
    toDate = document.getElementById("rep-to")?.value || "";
    datePreset = "custom";
    renderDateBar();
    loadChip();
  }
  function onThresholdChange() {
    const v = parseInt(document.getElementById("rep-threshold")?.value || "10", 10);
    lowThreshold = Number.isFinite(v) ? v : 10;
    loadChip();
  }

  function rangeQs(extra = {}) {
    const p = new URLSearchParams();
    if (fromDate) p.set("from_date", fromDate);
    if (toDate) p.set("to_date", toDate);
    Object.entries(extra).forEach(([k, v]) => { if (v != null && v !== "") p.set(k, v); });
    const s = p.toString();
    return s ? `?${s}` : "";
  }

  function empty(title, sub) {
    return OrdersUI.emptyState({
      title,
      sub,
      ctaHtml: `<button type="button" class="btn btn-secondary btn-sm" onclick="Reports.setDatePreset('month')">This month</button>
        <button type="button" class="btn btn-secondary btn-sm" onclick="Reports.setDatePreset('all')">All dates</button>`,
    });
  }

  function simpleTable(headers, rows, emptyTitle, emptySub) {
    if (!rows.length) return empty(emptyTitle, emptySub);
    return `<div class="card table-wrap"><table class="data"><thead><tr>
      ${headers.map(h => `<th>${h}</th>`).join("")}
    </tr></thead><tbody>
      ${rows.map(cells => `<tr${cells._onclick ? ` class="clickable" onclick="${cells._onclick}"` : ""}>${cells.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}
    </tbody></table></div>`;
  }

  async function loadChip() {
    const body = document.getElementById("reports-body");
    if (!body) return;
    ctx.showLoading?.();
    try {
      if (chip === "daybook") await renderDaybook(body);
      else if (chip === "sales") await renderDocList(body, "sales", "Sales bills");
      else if (chip === "purchases") await renderDocList(body, "purchases", "Purchase bills");
      else if (chip === "payments") await renderPayments(body);
      else if (chip === "ledgers") await renderLedgers(body);
      else if (chip === "ageing") await renderAgeing(body);
      else if (chip === "customer-sales") await renderPartyAgg(body, "customer-sales", "customers");
      else if (chip === "vendor-purchases") await renderPartyAgg(body, "vendor-purchases", "vendors");
      else if (chip === "item-sales") await renderItemAgg(body, "item-sales");
      else if (chip === "item-purchases") await renderItemAgg(body, "item-purchases");
      else if (chip === "valuation") await renderValuation(body);
      else if (chip === "movers") await renderMovers(body);
      else if (chip === "low") await renderLow(body);
      else if (chip === "returns") await renderReturns(body);
      else if (chip === "debit-notes") await renderDebitNotes(body);
      else if (chip === "gst-sales" || chip === "gst-purchases") await renderGst(body);
      else if (chip === "cashbook") await renderCashbook(body);
      else if (chip === "expense-cat") await renderExpenseCat(body);
      else if (chip === "pnl") await renderPnl(body);
      else body.innerHTML = empty("Nothing here", "Pick another chip.");
    } catch (e) {
      body.innerHTML = OrdersUI.emptyState({ title: "Could not load", sub: e.message });
    } finally {
      ctx.hideLoading?.();
    }
  }

  async function renderDaybook(body) {
    const data = await ctx.api(`/reports/daybook?day=${encodeURIComponent(daybookDate)}`, {}, 0);
    const t = data.totals || {};
    let rows = data.entries || [];
    rows = rows.filter(r => matchSearch(r.kind, r.party, r.label));
    body.innerHTML = `
      ${DocShare.toolbarHtml({
        printOnclick: "Reports.shareDaybook(true)",
        pdfOnclick: "Reports.shareDaybook(false)",
        waOnclick: "Reports.waDaybook()",
        excelOnclick: "Reports.exportExcel('sales_bills')",
      })}
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">Entries</span><strong>${t.count || 0}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Cash in</span><strong>${fmtPrice(t.cash_in)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Cash out</span><strong>${fmtPrice(t.cash_out)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Sales</span><strong>${t.sales_count || 0}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Purchases</span><strong>${t.purchase_count || 0}</strong></div>
      </div>
      ${simpleTable(["Time", "Type", "Party", "Particulars", "Amount"], rows.map(r => [
        r.at ? new Date(r.at).toLocaleString() : "—",
        `<span class="badge badge-blue">${ctx.esc(r.kind)}</span>`,
        ctx.esc(r.party || "—"),
        ctx.esc(r.label || "—"),
        fmtPrice(r.amount),
      ]), "Quiet day", "No entries for this date. Try another day.")}`;
  }

  async function shareDaybook(print) {
    try {
      await DocShare.openPdf(`/share/daybook/pdf?day=${encodeURIComponent(daybookDate)}`, {
        print: !!print,
        filename: `daybook_${daybookDate}.pdf`,
      });
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function waDaybook() {
    const phone = prompt("WhatsApp phone (10 digits / with country code):");
    if (!phone) return;
    ctx.showLoading?.();
    try {
      const res = await DocShare.whatsapp({ kind: "daybook", day: daybookDate, phone, caption: `Daybook ${daybookDate}` });
      if (res.ok) ctx.toast("Sent on WhatsApp", "success");
      else {
        ctx.toast(res.hint || "WA failed", "error");
        if (res.wa_me) window.open(res.wa_me, "_blank");
      }
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function exportExcel(kind) {
    ctx.showLoading?.();
    try {
      await DocShare.downloadExport(kind);
      ctx.toast("Excel downloaded", "success");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function renderDocList(body, path, title) {
    const data = await ctx.api(`/reports/${path}${rangeQs()}`, {}, 0);
    let items = (data.items || []).filter(it => matchSearch(it.doc_number, it.party_label));
    body.innerHTML = `
      <div class="fin-panel-head" style="margin-bottom:12px;">
        <div><h3 class="fin-panel-title">${title}</h3>
        <p class="fin-panel-sub">${items.length} document${items.length === 1 ? "" : "s"}</p></div>
      </div>
      ${items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Date</th><th>Number</th><th>Party</th><th>Amount</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openDoc('${it.doc_type}', ${it.id})">
          <td>${ctx.esc(it.date || "—")}</td>
          <td><strong>${ctx.esc(it.doc_number || "—")}</strong></td>
          <td>${ctx.esc(it.party_label || "—")}</td>
          <td>${fmtPrice(it.amount)}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No documents", "Widen the date range or clear search.")}`;
  }

  async function renderPayments(body) {
    const data = await ctx.api(`/reports/payments${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.doc_number, it.party_label, it.description));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Date</th><th>Dir</th><th>Ref</th><th>Party</th><th>Amount</th><th>Note</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr>
        <td>${ctx.esc(it.date || "—")}</td>
        <td><span class="badge ${it.direction === "in" ? "badge-green" : "badge-amber"}">${it.direction === "in" ? "In" : "Out"}</span></td>
        <td style="font-family:monospace;font-size:12px;">${ctx.esc(it.doc_number || "—")}</td>
        <td>${ctx.esc(it.party_label || "—")}</td>
        <td>${fmtPrice(it.amount)}</td>
        <td style="color:var(--muted);font-size:13px;">${ctx.esc(it.description || "—")}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No payments", "Widen dates to see cash in and out.");
  }

  async function renderPartyAgg(body, path, ledger) {
    const data = await ctx.api(`/reports/${path}${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchParty(it));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Party</th><th>Bills</th><th>Value</th><th>Due</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('${ledger}', ${it.id})">
        <td><strong>${ctx.esc(it.label)}</strong></td>
        <td>${it.bill_count}</td>
        <td>${fmtPrice(it.value)}</td>
        <td><strong>${fmtPrice(it.outstanding)}</strong></td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No activity", "Widen dates to see party totals.");
  }

  async function renderItemAgg(body, path) {
    const api = path === "item-purchases" ? "item-purchases" : "item-sales";
    const isSales = api === "item-sales";
    const data = await ctx.api(`/reports/${api}${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.label));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Product</th><th>Qty</th><th>Value</th><th>${isSales ? "Bills" : "Receipts"}</th><th>${isSales ? "Customers" : "Vendors"}</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr>
        <td><strong>${ctx.esc(it.label)}</strong></td>
        <td>${it.qty}</td>
        <td>${fmtPrice(it.value)}</td>
        <td>${isSales ? it.bill_count : it.receipt_count}</td>
        <td>${isSales ? it.customer_count : it.vendor_count}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No item lines", "Widen dates or check another period.");
  }

  async function renderAgeing(body) {
    const side = ageingSide === "ap" ? "ap" : "ar";
    const data = await ctx.api(`/reports/ageing/${side}`, {}, 0);
    const t = data.totals || {};
    const items = (data.items || []).filter(it => matchParty(it));
    body.innerHTML = `
      ${DocShare.toolbarHtml({
        printOnclick: "Reports.shareAgeing(true)",
        pdfOnclick: "Reports.shareAgeing(false)",
        waOnclick: "Reports.waAgeing()",
        excelOnclick: `Reports.exportExcel('${side}')`,
      })}
      <p class="fin-panel-sub" style="margin:0 0 12px;">As on ${ctx.esc(data.as_of || today())}</p>
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">0–30</span><strong>${fmtPrice(t["0-30"])}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">31–60</span><strong>${fmtPrice(t["31-60"])}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">61–90</span><strong>${fmtPrice(t["61-90"])}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">90+</span><strong>${fmtPrice(t["90+"])}</strong></div>
      </div>
      ${items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Party</th><th>Total</th><th>0–30</th><th>31–60</th><th>61–90</th><th>90+</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('${side === "ar" ? "customers" : "vendors"}', ${it.id})">
          <td><strong>${ctx.esc(it.label)}</strong></td>
          <td><strong>${fmtPrice(it.outstanding)}</strong></td>
          <td>${fmtPrice(it.b0_30)}</td>
          <td>${fmtPrice(it.b31_60)}</td>
          <td>${fmtPrice(it.b61_90)}</td>
          <td>${fmtPrice(it.b90_plus)}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("All clear", "Nothing due.");}
  }

  async function renderValuation(body) {
    const data = await ctx.api(`/reports/stock/valuation`, {}, 0);
    const t = data.totals || {};
    const items = (data.items || []).filter(it => matchSearch(it.label));
    body.innerHTML = `
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">SKUs</span><strong>${t.sku_count || 0}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Buy value</span><strong>${fmtPrice(t.buy_value)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Sell value</span><strong>${fmtPrice(t.sell_value)}</strong></div>
      </div>
      ${items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Product</th><th>Qty</th><th>Buy</th><th>Sell</th><th>Buy value</th><th>Sell value</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('products', ${it.id})">
          <td><strong>${ctx.esc(it.label)}</strong></td>
          <td>${it.qty}</td>
          <td>${fmtPrice(it.buying_price)}</td>
          <td>${it.selling_price != null ? fmtPrice(it.selling_price) : "—"}</td>
          <td>${fmtPrice(it.buy_value)}</td>
          <td>${it.sell_value != null ? fmtPrice(it.sell_value) : "—"}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No stock on hand", "Receive stock to see valuation.")}`;
  }

  async function renderMovers(body) {
    const data = await ctx.api(`/reports/stock/movers${rangeQs()}`, {}, 0);
    const fast = (data.fast || []).filter(it => matchSearch(it.label));
    const slow = (data.slow || []).filter(it => matchSearch(it.label));
    body.innerHTML = `
      <h3 class="fin-panel-title" style="margin:0 0 8px;">Fast movers</h3>
      ${fast.length ? `<div class="card table-wrap" style="margin-bottom:24px;"><table class="data"><thead><tr>
        <th>Product</th><th>Sold</th><th>Sales</th><th>On hand</th>
      </tr></thead><tbody>
        ${fast.map(it => `<tr><td>${ctx.esc(it.label)}</td><td>${it.qty_sold}</td><td>${fmtPrice(it.sales_value)}</td><td>${it.on_hand}</td></tr>`).join("")}
      </tbody></table></div>` : empty("No sales in range", "Widen dates to see movers.")}
      <h3 class="fin-panel-title" style="margin:0 0 8px;">Slow / idle</h3>
      ${slow.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Product</th><th>Sold</th><th>On hand</th>
      </tr></thead><tbody>
        ${slow.map(it => `<tr><td>${ctx.esc(it.label)}</td><td>${it.qty_sold}</td><td>${it.on_hand}</td></tr>`).join("")}
      </tbody></table></div>` : empty("No idle stock", "Everything is moving or empty.")}`;
  }

  async function renderLow(body) {
    const data = await ctx.api(`/reports/stock/low?threshold=${lowThreshold}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.label));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Product</th><th>On hand</th><th>Limit</th><th>Buy</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('products', ${it.id})">
        <td><strong>${ctx.esc(it.label)}</strong></td>
        <td>${it.qty}</td><td>${it.threshold}</td><td>${fmtPrice(it.buying_price)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("Stock looks fine", "Nothing at or below this threshold.");
  }

  async function renderReturns(body) {
    const data = await ctx.api(`/reports/returns-register${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.doc_number, it.party_label));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Date</th><th>Number</th><th>Customer</th><th>Qty</th><th>Credit</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr>
        <td>${ctx.esc(it.date || "—")}</td>
        <td>${ctx.esc(it.doc_number || "—")}</td>
        <td>${ctx.esc(it.party_label || "—")}</td>
        <td>${it.qty}</td>
        <td>${fmtPrice(it.credit_amount)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No returns", "Widen dates if you expect credit notes.");
  }

  async function renderDebitNotes(body) {
    const data = await ctx.api(`/reports/debit-notes-register${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.party_label, it.our_product_id, it.notes));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Date</th><th>Vendor</th><th>Type</th><th>Product</th><th>Amount</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr>
        <td>${ctx.esc(it.date || "—")}</td>
        <td>${ctx.esc(it.party_label || "—")}</td>
        <td>${ctx.esc(it.note_type)}/${ctx.esc(it.direction || "")}</td>
        <td>${ctx.esc(it.our_product_id || "—")}</td>
        <td>${fmtPrice(it.amount)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No debit notes", "Widen dates to see purchase adjustments.");
  }

  async function renderGst(body) {
    const path = chip === "gst-purchases" ? "gst/purchases" : "gst/sales";
    const data = await ctx.api(`/reports/${path}${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.doc_number, it.party_label));
    const note = chip === "gst-purchases"
      ? `<p class="fin-panel-sub" style="margin:0 0 12px;">Purchase GST not stored on receipts yet — GST shows as 0.</p>` : "";
    body.innerHTML = note + (items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Date</th><th>Number</th><th>Party</th><th>Rate</th><th>Taxable</th><th>GST</th><th>Total</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr>
        <td>${ctx.esc(it.date || "—")}</td>
        <td>${ctx.esc(it.doc_number || "—")}</td>
        <td>${ctx.esc(it.party_label || "—")}</td>
        <td>${it.gst_enabled ? `${it.gst_rate}%` : "Off"}</td>
        <td>${fmtPrice(it.taxable_value)}</td>
        <td>${fmtPrice(it.gst_amount)}</td>
        <td>${fmtPrice(it.grand_total)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No bills", "Widen dates for the GST register."));
  }

  async function renderCashbook(body) {
    const data = await ctx.api(`/reports/cashbook${rangeQs()}`, {}, 0);
    const t = data.totals || {};
    const entries = (data.entries || []).filter(r => matchSearch(r.kind, r.party, r.label));
    body.innerHTML = `
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">In</span><strong>${fmtPrice(t.cash_in)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Out</span><strong>${fmtPrice(t.cash_out)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Net</span><strong>${fmtPrice(t.net)}</strong></div>
      </div>
      ${entries.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Date</th><th>Type</th><th>Party</th><th>In</th><th>Out</th><th>Balance</th>
      </tr></thead><tbody>
        ${entries.map(r => `<tr>
          <td>${ctx.esc(r.date || "—")}</td>
          <td>${ctx.esc(r.kind)}</td>
          <td>${ctx.esc(r.party || "—")}</td>
          <td>${fmtPrice(r.in_amount)}</td>
          <td>${fmtPrice(r.out_amount)}</td>
          <td>${fmtPrice(r.balance)}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No cash moves", "Widen dates to build the cash book.")}`;
  }

  async function renderExpenseCat(body) {
    const data = await ctx.api(`/reports/expense-by-category${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.category));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Category</th><th>Count</th><th>Amount</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr class="clickable" onclick="Reports.openExpenseLedger('${ctx.esc(it.category)}')">
        <td><strong>${ctx.esc(it.category)}</strong></td>
        <td>${it.count}</td>
        <td>${fmtPrice(it.amount)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No expenses", "Add expenses in Finance, or widen dates.");
  }

  async function renderPnl(body) {
    const data = await ctx.api(`/reports/pnl${rangeQs()}`, {}, 0);
    body.innerHTML = `<div class="review-grid">
      ${ctx.reviewRow("Sales billed (incl. GST)", fmtPrice(data.sales_billed))}
      ${ctx.reviewRow("GST on sales", fmtPrice(data.gst_on_sales))}
      ${ctx.reviewRow("Sales, ex-GST", fmtPrice(data.sales_taxable))}
      ${ctx.reviewRow("Customer returns", data.customer_returns && Number(data.customer_returns) > 0 ? "−" + fmtPrice(data.customer_returns) : fmtPrice(data.customer_returns))}
      ${ctx.reviewRow("Net sales", fmtPrice(data.net_sales))}
      ${ctx.reviewRow("Purchases (COGS proxy)", fmtPrice(data.cogs_purchases))}
      ${ctx.reviewRow("Vendor debit notes", fmtPrice(data.vendor_debit_notes))}
      ${ctx.reviewRow("Net COGS", fmtPrice(data.cogs_net))}
      ${ctx.reviewRow("Gross profit", fmtPrice(data.gross_profit))}
      ${ctx.reviewRow("Expenses", fmtPrice(data.expenses))}
      ${ctx.reviewRow("Freight paid", fmtPrice(data.freight_paid))}
      ${ctx.reviewRow("Manual losses", fmtPrice(data.manual_losses))}
      ${ctx.reviewRow("Net profit", fmtPrice(data.net_profit))}
      ${ctx.reviewRow("Cash collected", fmtPrice(data.cash_collected))}
      ${ctx.reviewRow("Bill count", data.bill_count)}
    </div>
    <p class="fin-panel-sub" style="margin-top:12px;">Net profit = net sales (ex-GST, net of returns) − net COGS (purchases, net of vendor debit notes) − expenses − manual losses. Still a management approximation, not true inventory-costed accounting.</p>`;
  }

  async function renderLedgers(body) {
    if (ledgerKind === "cash") {
      body.innerHTML = `<div class="fin-panel-head" style="margin-bottom:16px;">
        <div><h3 class="fin-panel-title">Cash book</h3>
        <p class="fin-panel-sub">All cash in and out with running balance</p></div>
        <button type="button" class="btn btn-primary" onclick="Reports.openCashLedger()">Open cash book</button>
      </div>`;
      return;
    }
    const data = await ctx.api(`/reports/ledgers/${ledgerKind}`, {}, 0);
    let items = data.items || [];

    if (ledgerKind === "staff") {
      items = items.filter(it => matchSearch(it.label, it.phone));
      body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Name</th><th>Phone</th><th>Activities</th>
      </tr></thead><tbody>
        ${items.map(it => {
          const onclick = it.actor_type === "admin"
            ? `Reports.openStaffLedger(0, 'admin', '${ctx.esc(it.actor_name || "")}')`
            : `Reports.openStaffLedger(${it.id})`;
          return `<tr class="clickable" onclick="${onclick}">
            <td><strong>${ctx.esc(it.label)}</strong></td>
            <td>${ctx.esc(it.phone || "—")}</td>
            <td>${it.activity_count || 0}</td>
          </tr>`;
        }).join("")}
      </tbody></table></div>` : empty("No staff activity", "Staff actions show up as they use the app.");
      return;
    }

    if (ledgerKind === "expenses") {
      items = items.filter(it => matchSearch(it.label, it.category));
      body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Category</th><th>Count</th><th>Total</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openExpenseLedger('${ctx.esc(it.category || it.label)}')">
          <td><strong>${ctx.esc(it.label)}</strong></td>
          <td>${it.count || 0}</td>
          <td>${fmtPrice(it.outstanding)}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No expense categories", "Add expenses in Finance first.");
      return;
    }

    if (ledgerKind === "products") {
      items = items.filter(it => matchSearch(it.label));
      body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Name</th><th>On hand</th><th>Buy</th><th>Sell</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('products', ${it.id})">
          <td><strong>${ctx.esc(it.label)}</strong></td>
          <td>${it.qty ?? 0}</td>
          <td>${fmtPrice(it.buying_price)}</td>
          <td>${it.selling_price != null ? fmtPrice(it.selling_price) : '<span class="prod-price-missing">Not set</span>'}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No products", "Add catalog products first.");
      return;
    }

    items = items.filter(it => matchParty(it));
    const isRoute = ledgerKind === "routes";
    const isFreight = ledgerKind === "freight";
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Name</th>
      <th>${isRoute ? "Customers" : isFreight ? "Due" : "Opening"}</th>
      ${!isRoute && !isFreight ? "<th>Due</th>" : ""}
    </tr></thead><tbody>
      ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('${ledgerKind}', ${it.id})">
        <td><strong>${ctx.esc(it.label)}</strong></td>
        <td>${isRoute ? (it.customer_count ?? 0) : isFreight ? `<strong>${fmtPrice(it.outstanding)}</strong>` : fmtPrice(it.opening_total)}</td>
        ${!isRoute && !isFreight ? `<td><strong>${fmtPrice(it.outstanding)}</strong></td>` : ""}
      </tr>`).join("")}
    </tbody></table></div>` : empty("No ledgers", "Nothing to show for this list.");
  }

  async function openLedger(kind, id) {
    backLabel = "Back";
    ctx.showLoading?.();
    try {
      ledgerDetail = await ctx.api(`/reports/ledgers/${kind}/${id}`, {}, 0);
      showDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openStaffLedger(id, actorType = "staff", actorName = "") {
    backLabel = "Back to staff";
    ctx.showLoading?.();
    try {
      let url = `/reports/ledgers/staff/${id || 0}`;
      if (actorType === "admin") url += `?actor_type=admin&actor_name=${encodeURIComponent(actorName)}`;
      ledgerDetail = await ctx.api(url, {}, 0);
      showDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openExpenseLedger(category) {
    backLabel = "Back";
    ctx.showLoading?.();
    try {
      ledgerDetail = await ctx.api(`/reports/ledgers/expenses/${encodeURIComponent(category)}${rangeQs()}`, {}, 0);
      showDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openCashLedger() {
    backLabel = "Back";
    ctx.showLoading?.();
    try {
      ledgerDetail = await ctx.api(`/reports/ledgers/cash/book${rangeQs()}`, {}, 0);
      showDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function showDetail() {
    document.getElementById("reports-hub")?.classList.add("hidden");
    document.getElementById("reports-ledger-detail")?.classList.remove("hidden");
    const back = document.getElementById("reports-detail-back");
    if (back) back.textContent = `← ${backLabel}`;
    renderLedgerDetail();
    App.updateGlobalBack?.();
  }

  function backFromLedger() {
    ledgerDetail = null;
    document.getElementById("reports-ledger-detail")?.classList.add("hidden");
    document.getElementById("reports-hub")?.classList.remove("hidden");
    loadChip();
    App.updateGlobalBack?.();
  }

  function renderLedgerDetail() {
    const hero = document.getElementById("reports-ledger-hero");
    const body = document.getElementById("reports-ledger-body");
    if (!ledgerDetail || !body) return;
    const d = ledgerDetail;
    if (hero) {
      const badges = [
        d.outstanding != null ? `<span class="badge badge-amber">${fmtPrice(d.outstanding)}</span>` : "",
        d.quantity_on_hand != null ? `<span class="badge badge-blue">On hand ${d.quantity_on_hand}</span>` : "",
        d.activity_count != null ? `<span class="badge badge-blue">${d.activity_count} activities</span>` : "",
      ].filter(Boolean).join(" ");
      hero.innerHTML = HubUI.pageHero({
        title: d.party_label || d.label || "Ledger",
        sub: d.party_type || "ledger",
        actionsHtml: badges,
      });
    }
    if (d.party_type === "staff") {
      const entries = d.entries || [];
      body.innerHTML = entries.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>When</th><th>Action</th><th>What</th><th>Detail</th>
      </tr></thead><tbody>
        ${entries.map(e => `<tr>
          <td style="font-size:12px;">${e.created_at ? new Date(e.created_at).toLocaleString() : "—"}</td>
          <td>${ctx.esc(e.action || "—")}</td>
          <td>${ctx.esc([e.entity_type, e.entity_label || e.entity_id].filter(Boolean).join(" · ") || "—")}</td>
          <td style="color:var(--muted);font-size:13px;">${ctx.esc(e.detail || "—")}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No activity", "This person has no logged actions yet.");
      return;
    }
    if (d.party_type === "product") {
      const entries = d.entries || [];
      body.innerHTML = entries.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>When</th><th>Type</th><th>Δ</th><th>Balance</th><th>Party</th><th>Notes</th>
      </tr></thead><tbody>
        ${entries.map(e => `<tr>
          <td style="font-size:12px;">${e.created_at ? new Date(e.created_at).toLocaleString() : "—"}</td>
          <td>${ctx.esc(e.entry_type)}</td>
          <td>${e.quantity_delta > 0 ? "+" : ""}${e.quantity_delta}</td>
          <td>${e.balance_after}</td>
          <td>${ctx.esc(e.party || "—")}</td>
          <td style="color:var(--muted);">${ctx.esc(e.notes || "—")}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No stock moves", "No ledger lines for this product.");
      return;
    }
    const entries = d.entries || [];
    body.innerHTML = `
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        ${d.opening_total != null ? `<div class="fin-stat"><span class="fin-stat-label">Opening</span><strong>${fmtPrice(d.opening_total)}</strong></div>` : ""}
        ${d.bill_total != null ? `<div class="fin-stat"><span class="fin-stat-label">In / Bills</span><strong>${fmtPrice(d.bill_total)}</strong></div>` : ""}
        ${d.payment_total != null ? `<div class="fin-stat"><span class="fin-stat-label">Out / Paid</span><strong>${fmtPrice(d.payment_total)}</strong></div>` : ""}
        ${d.credit_total != null ? `<div class="fin-stat"><span class="fin-stat-label">Credits</span><strong>${fmtPrice(d.credit_total)}</strong></div>` : ""}
        ${d.debit_note_total != null ? `<div class="fin-stat"><span class="fin-stat-label">Debit notes</span><strong>${fmtPrice(d.debit_note_total)}</strong></div>` : ""}
        ${d.outstanding != null ? `<div class="fin-stat"><span class="fin-stat-label">Net</span><strong>${fmtPrice(d.outstanding)}</strong></div>` : ""}
      </div>
      ${entries.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>When</th><th>Type</th><th>Description</th><th>Amount</th><th>Balance</th>
      </tr></thead><tbody>
        ${[...entries].reverse().map(e => `<tr>
          <td style="font-size:12px;">${e.value_date || (e.created_at ? new Date(e.created_at).toLocaleDateString() : "—")}</td>
          <td><span class="badge badge-blue">${ctx.esc(e.entry_type)}</span></td>
          <td>${ctx.esc(e.description || "—")}</td>
          <td>${fmtPrice(e.signed_amount || e.amount)}</td>
          <td>${e.running_balance != null ? fmtPrice(e.running_balance) : "—"}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("Empty ledger", "No entries yet.")}`;
  }

  function openDoc(docType, id) {
    if (docType === "sales_bill") { CustomerOrders?.openBillDoc?.(id); return; }
    if (docType === "purchase_bill") { Stock?.openReceiptDetail?.(id); return; }
  }

  async function shareAgeing(print) {
    const side = ageingSide === "ap" ? "ap" : "ar";
    try {
      await DocShare.openPdf(`/share/ageing/pdf?side=${side}`, {
        print: !!print,
        filename: `ageing_${side}.pdf`,
      });
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function waAgeing() {
    const side = ageingSide === "ap" ? "ap" : "ar";
    const phone = prompt("WhatsApp phone (10 digits / with country code):");
    if (!phone) return;
    ctx.showLoading?.();
    try {
      const res = await DocShare.whatsapp({ kind: "ageing", side, phone, caption: `Ageing ${side.toUpperCase()}` });
      if (res.ok) ctx.toast("Sent on WhatsApp", "success");
      else {
        ctx.toast(res.hint || "WA failed", "error");
        if (res.wa_me) window.open(res.wa_me, "_blank");
      }
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  return {
    init, showHub, setMode, setChip, setLedgerKind, setAgeingSide, setHubSearch, pickQuestion,
    setDatePreset, onDayChange, shiftDay, setDayToday, onRangeChange, onThresholdChange,
    openLedger, openStaffLedger, openExpenseLedger, openCashLedger, backFromLedger, openDoc,
    shareDaybook, waDaybook, shareAgeing, waAgeing, exportExcel,
  };
})();
