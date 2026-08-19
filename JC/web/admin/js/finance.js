/** Finance — money hub (Due / Collect / Pay / Freight / …) */
const Finance = (() => {
  let ctx = {};
  let vendors = [];
  let customers = [];
  let expenses = [];
  let overview = null;
  let currentVendor = null;
  let currentCustomer = null;
  let apDetail = null;
  let arDetail = null;
  let apTab = "statement";
  let arTab = "statement";
  let expandedBillId = null;
  let freightAgents = [];
  let freightAgentId = null;
  let freightLedger = [];
  let routeCollections = [];
  let routeDetail = null;
  let routeCustomerDetail = null;
  let activeChip = "due";
  let hubMode = "needs_action";
  let browseSection = "ap";
  let reportTab = "revenue";
  let hubSearch = "";
  let showSettled = false;
  let expenseFilters = { from_date: "", to_date: "", category: "" };
  let settleFile = null;
  let freightSettleFile = null;
  let freightPayMode = "settle"; // settle | advance
  let paymentModes = [];
  let chipCounts = { due: 0, ar: 0, ap: 0, freight: 0 };
  let dues = null; // from GET /finance/dues — single money API

  const CHART_LABELS = {
    revenue: "Cash in",
    expenses: "Expenses",
    ap_paid: "Paid vendors",
    cost: "Cash out",
    profit: "Net cash",
    net_cash: "Net cash",
  };

  const CHIP_SUB = {
    due: "Who needs money action",
    ar: "Money to collect from customers",
    ap: "Money to pay vendors",
    freight: "Freight agent dues",
    expenses: "Rent, salary, misc",
    routes: "Collect by route",
    reports: "Quick cash snapshot — full books under More → Reports",
  };

  function init(context) { ctx = context; }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function fmtPriceShort(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return "—";
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function matchSearch(label) {
    const q = hubSearch.trim().toLowerCase();
    if (!q) return true;
    return String(label || "").toLowerCase().includes(q);
  }

  /** Same fields as Vendors/Customers list search (name, alias, person, phone, city). */
  function matchParty(row, labelKey) {
    const tokens = OrdersUI.partySearchTokens(hubSearch);
    if (!tokens.length) return true;
    const party = {
      business_name: row?.business_name || row?.[labelKey] || "",
      city_name: row?.city_name || "",
      person_name: row?.person_name || "",
      alias: row?.alias || "",
      phone: row?.phone || "",
      secondary_phone: row?.secondary_phone || "",
      customer_label: row?.customer_label || "",
      vendor_label: row?.vendor_label || "",
    };
    return OrdersUI.partySearchRank(party, tokens) != null;
  }

  function rankParties(list, labelKey) {
    return OrdersUI.filterAndRankParties(
      (list || []).map(row => ({
        ...row,
        business_name: row.business_name || row[labelKey] || "",
      })),
      hubSearch,
    );
  }

  function barPct(part, whole) {
    const a = Math.max(0, Number(part) || 0);
    const b = Math.max(a, Number(whole) || 0);
    if (b <= 0) return 0;
    return Math.min(100, Math.round((a / b) * 100));
  }

  function hideAllPanels() {
    ["ap", "ar", "expenses", "freight", "routes", "reports"].forEach(k => {
      document.getElementById(`finance-panel-${k}`)?.classList.add("hidden");
    });
    document.getElementById("finance-freight-detail")?.classList.add("hidden");
    document.getElementById("finance-routes-detail")?.classList.add("hidden");
  }

  function refreshChipCounts() {
    const apN = vendors.filter(v => Number(v.outstanding) > 0).length;
    const arN = customers.filter(c => Number(c.outstanding) > 0).length;
    const frN = freightAgents.filter(a => Number(a.balance_due) > 0).length;
    chipCounts = { due: apN + arN + frN, ar: arN, ap: apN, freight: frN };
  }

  function renderHubChrome() {
    const prevSearch = document.getElementById("finance-hub-search");
    const caret = prevSearch && document.activeElement === prevSearch
      ? { start: prevSearch.selectionStart, end: prevSearch.selectionEnd }
      : null;

    const sub = document.getElementById("finance-hub-sub");
    if (sub) sub.textContent = CHIP_SUB[activeChip] || "Collect, pay, and track cash";

    OrdersUI.actionChips({
      hostId: "finance-action-chips",
      active: activeChip,
      onclickFn: "Finance.setChip",
      items: [
        { id: "due", label: "To do", count: chipCounts.due || undefined },
        { id: "ar", label: "To collect", count: chipCounts.ar || undefined },
        { id: "ap", label: "To pay", count: chipCounts.ap || undefined },
        { id: "freight", label: "Freight", count: chipCounts.freight || undefined },
        { id: "expenses", label: "Other spend" },
        { id: "routes", label: "Routes" },
        { id: "reports", label: "Cash snapshot" },
      ],
    });

    const needs = document.getElementById("finance-needs");
    if (needs) needs.classList.toggle("hidden", activeChip !== "due");

    const slot = document.getElementById("finance-search-slot");
    if (slot) {
      const ph = activeChip === "due" ? "Search parties…"
        : activeChip === "ap" ? "Search vendors…"
          : activeChip === "ar" ? "Search customers…"
            : activeChip === "freight" ? "Search agents…"
              : activeChip === "routes" ? "Search routes…"
                : "Search…";
      const showSearch = ["due", "ap", "ar", "freight", "routes"].includes(activeChip);
      slot.innerHTML = showSearch
        ? OrdersUI.searchBar({
          id: "finance-hub-search",
          value: hubSearch,
          placeholder: ph,
          oninput: "Finance.setHubSearch(this.value)",
        })
        : "";
      slot.classList.toggle("hidden", !showSearch);
      if (caret && showSearch) {
        const el = document.getElementById("finance-hub-search");
        if (el) {
          el.focus();
          try { el.setSelectionRange(caret.start, caret.end); } catch (_) { /* ignore */ }
        }
      }
    }
  }

  function showHub() {
    if (!ctx.isAdmin?.()) {
      ctx.toast?.("Finance is admin only", "error");
      ctx.showView?.("today");
      return;
    }
    document.getElementById("finance-hub")?.classList.remove("hidden");
    document.getElementById("finance-ap-detail")?.classList.add("hidden");
    document.getElementById("finance-ar-detail")?.classList.add("hidden");
    document.getElementById("finance-freight-detail")?.classList.add("hidden");
    document.getElementById("finance-routes-detail")?.classList.add("hidden");
    currentVendor = null;
    currentCustomer = null;
    apDetail = null;
    arDetail = null;
    freightAgentId = null;
    routeDetail = null;
    routeCustomerDetail = null;
    loadDuesSilent();
    loadOverviewSilent();
    setChip(activeChip || "due", true);
    App.updateGlobalBack?.();
  }

  function setHubMode(mode) {
    if (mode === "browse") setChip(browseSection === "due" ? "ap" : browseSection || "ap");
    else setChip("due");
  }

  function setChip(id, fromHub) {
    const map = { revenue: "reports", cost: "reports", pnl: "reports", needs_action: "due", browse: "ap" };
    const chip = map[id] || id || "due";
    if (chip !== activeChip) hubSearch = "";
    activeChip = chip;
    if (chip === "due") {
      hubMode = "needs_action";
      browseSection = "ap";
    } else {
      hubMode = "browse";
      browseSection = chip;
    }

    document.getElementById("finance-hub")?.classList.remove("hidden");
    document.getElementById("finance-ap-detail")?.classList.add("hidden");
    document.getElementById("finance-ar-detail")?.classList.add("hidden");
    document.getElementById("finance-freight-detail")?.classList.add("hidden");
    document.getElementById("finance-routes-detail")?.classList.add("hidden");
    hideAllPanels();
    renderHubChrome();

    if (chip === "due") {
      loadNeedsAction();
    } else if (chip === "ap") {
      document.getElementById("finance-panel-ap")?.classList.remove("hidden");
      loadApList();
    } else if (chip === "ar") {
      document.getElementById("finance-panel-ar")?.classList.remove("hidden");
      loadArList();
    } else if (chip === "freight") {
      document.getElementById("finance-panel-freight")?.classList.remove("hidden");
      loadFreightList();
    } else if (chip === "expenses") {
      document.getElementById("finance-panel-expenses")?.classList.remove("hidden");
      loadExpenses();
    } else if (chip === "routes") {
      document.getElementById("finance-panel-routes")?.classList.remove("hidden");
      loadRouteCollections();
    } else if (chip === "reports") {
      document.getElementById("finance-panel-reports")?.classList.remove("hidden");
      loadOverview().then(() => renderReportsPanel());
    }

    if (!fromHub && chip !== "due") {
      requestAnimationFrame(() => {
        document.querySelector(".fin-browse-panel:not(.hidden)")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }

  function setHubSearch(val) {
    hubSearch = val || "";
    if (activeChip === "due") renderNeedsAction();
    else if (activeChip === "ap") renderApList();
    else if (activeChip === "ar") renderArList();
    else if (activeChip === "freight") renderFreightList();
    else if (activeChip === "routes") renderRouteListFiltered();
  }

  function setBrowseSection(id, fromHub) {
    setChip(id, fromHub);
  }

  function showAp() { setChip("ap"); }
  function showAr() { setChip("ar"); }
  function showExpenses() { setChip("expenses"); }
  function showRevenue() { reportTab = "revenue"; setChip("reports"); }
  function showCost() { reportTab = "cost"; setChip("reports"); }
  function showPnl() { reportTab = "pnl"; setChip("reports"); }
  function showFreight() { setChip("freight"); }
  function showRouteCollections() { setChip("routes"); }

  async function loadDuesSilent() {
    try {
      dues = await ctx.api("/finance/dues", {}, 0);
      if (dues?.ar) {
        chipCounts = {
          due: (dues.ar.count || 0) + (dues.ap.count || 0) + (dues.freight.count || 0),
          ar: dues.ar.count || 0,
          ap: dues.ap.count || 0,
          freight: dues.freight.count || 0,
        };
      }
      renderHubChrome();
      renderHubStrip();
    } catch (_) { /* ignore */ }
  }

  async function loadOverviewSilent() {
    try {
      overview = await ctx.api("/finance/overview", {}, 0);
      if (overview?.dues) dues = overview.dues;
      renderHubStrip();
    } catch (_) { /* ignore */ }
  }

  async function loadOverview() {
    ctx.showLoading?.();
    try {
      overview = await ctx.api("/finance/overview", {}, 0);
      if (overview?.dues) dues = overview.dues;
      renderHubStrip();
      return overview;
    } catch (e) { ctx.toast(e.message, "error"); return null; }
    finally { ctx.hideLoading?.(); }
  }

  function renderHubStrip() {
    const el = document.getElementById("finance-hub-strip");
    if (!el) return;
    if (!dues && !overview) return;
    // Single money API only — never sum raw ledgers in the UI
    const collect = Number(dues?.ar?.total ?? overview?.ar_outstanding) || 0;
    const pay = Number(dues?.ap?.total ?? overview?.ap_outstanding) || 0;
    const freight = Number(dues?.freight?.total ?? overview?.freight_outstanding) || 0;
    const netCash = Number(overview?.cash_pulse?.net_cash ?? overview?.net_cash ?? overview?.profit) || 0;
    const cashIn = Number(overview?.cash_pulse?.cash_in ?? overview?.revenue) || 0;
    const cashOut = Number(overview?.cash_pulse?.cash_out ?? overview?.cost) || 0;
    const maxDue = Math.max(collect, pay, freight, 1);
    const rows = [
      { label: "Collect", value: fmtPriceShort(collect), pct: barPct(collect, maxDue), tone: "in", chip: "ar", sub: "Customer dues" },
      { label: "Pay", value: fmtPriceShort(pay), pct: barPct(pay, maxDue), tone: "out", chip: "ap", sub: "Vendor dues" },
      { label: "Freight", value: fmtPriceShort(freight), pct: barPct(freight, maxDue), tone: "sales", chip: "freight", sub: "Agent dues" },
    ];
    el.innerHTML = `
      <div class="fin-pulse-head">
        <div>
          <span class="fin-pulse-label">Cash pulse · not books P&amp;L</span>
          <strong class="fin-pulse-profit ${netCash >= 0 ? "is-pos" : "is-neg"}">${fmtPriceShort(netCash)} net cash</strong>
        </div>
        <button type="button" class="btn btn-ghost btn-sm" onclick="Finance.setChip('reports')">Pulse →</button>
      </div>
      <div class="home-pulse-bars">
        ${rows.map(r => `
          <button type="button" class="fin-pulse-row" onclick="Finance.setChip('${r.chip}')">
            <div class="home-pulse-meta">
              <span class="home-pulse-label">${r.label}</span>
              <strong class="home-pulse-val">${r.value}</strong>
            </div>
            <div class="home-pulse-track" aria-hidden="true"><span class="home-pulse-fill is-${r.tone}" style="width:${r.pct}%"></span></div>
            <span class="home-pulse-sub">${ctx.esc(r.sub)}</span>
          </button>
        `).join("")}
      </div>
      <div class="home-pulse-foot">
        <span>Cash in ${fmtPriceShort(cashIn)}</span>
        <span>· Cash out ${fmtPriceShort(cashOut)}</span>
      </div>`;
  }

  async function loadNeedsAction() {
    const el = document.getElementById("finance-needs");
    if (!el) return;
    ctx.showLoading?.();
    try {
      const [ap, ar, fr] = await Promise.all([
        ctx.api("/accounts-payable", {}, 0).catch(() => []),
        ctx.api("/accounts-receivable", {}, 0).catch(() => []),
        ctx.api("/freight-agents", {}, 0).catch(() => []),
        loadDuesSilent(),
      ]);
      vendors = Array.isArray(ap) ? ap : [];
      customers = Array.isArray(ar) ? ar : [];
      freightAgents = Array.isArray(fr) ? fr : [];
      refreshChipCounts();
      renderHubChrome();
      renderHubStrip();
      renderNeedsAction();
    } catch (e) { ctx.toast?.(e.message || "Failed to load", "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function dueRow({ name, amount, openFn, settleFn, cta, settled = false }) {
    if (settled) {
      return HubUI.partyCard({
        title: name,
        meta: "Clear",
        pillHtml: HubUI.pill("OK", "muted"),
        primaryLabel: "Open",
        primaryOnclick: openFn,
        rowOnclick: openFn,
        canWrite: true,
      });
    }
    return HubUI.partyCard({
      title: name,
      meta: `<strong>${fmtPrice(amount)}</strong> due`,
      pillHtml: HubUI.pill("Due", "danger"),
      primaryLabel: cta,
      primaryOnclick: settleFn,
      moreItems: [{ label: "Open", onclick: openFn }],
      rowOnclick: openFn,
      canWrite: true,
    });
  }

  function renderNeedsAction() {
    const el = document.getElementById("finance-needs");
    if (!el) return;
    const apDue = rankParties(vendors.filter(v => Number(v.outstanding) > 0), "vendor_label");
    const arDue = rankParties(customers.filter(c => Number(c.outstanding) > 0), "customer_label");
    const frDue = freightAgents.filter(a => Number(a.balance_due) > 0 && matchSearch(a.name));
    const total = apDue.length + arDue.length + frDue.length;

    if (!total) {
      el.innerHTML = HubUI.emptyState({
        title: hubSearch.trim() ? "No matches" : "All clear",
        sub: hubSearch.trim()
          ? "Try another name, or open Collect / Pay for full lists."
          : "When customer or vendor dues land, they show here.",
        ctaHtml: `<div class="home-clear-actions">
          <button type="button" class="btn btn-secondary btn-sm" onclick="Finance.setChip('ar')">Collect</button>
          <button type="button" class="btn btn-secondary btn-sm" onclick="Finance.setChip('ap')">Pay</button>
        </div>`,
      });
      return;
    }

    const section = (title, count, rows, moreChip) => rows.length
      ? `<section class="fin-needs-section">
          <div class="ui-toolbar fin-needs-head">
            <h3 class="fin-needs-title">${title}</h3>
            <span class="home-count">${count}</span>
            <button type="button" class="btn btn-ghost btn-sm" onclick="Finance.setChip('${moreChip}')">All →</button>
          </div>
          <div class="ord-card-list">${rows}</div>
        </section>`
      : "";

    const arRows = arDue.slice(0, 8).map(c => dueRow({
      name: c.customer_label,
      amount: c.outstanding,
      openFn: `Finance.openCustomerAr(${c.customer_id})`,
      settleFn: `Finance.openCustomerAr(${c.customer_id},{settle:true})`,
      cta: "Collect",
    })).join("");

    const apRows = apDue.slice(0, 8).map(v => dueRow({
      name: v.vendor_label,
      amount: v.outstanding,
      openFn: `Finance.openVendorAp(${v.vendor_id})`,
      settleFn: `Finance.openVendorAp(${v.vendor_id},{settle:true})`,
      cta: "Pay",
    })).join("");

    const frRows = frDue.slice(0, 8).map(a => dueRow({
      name: a.name,
      amount: a.balance_due,
      openFn: `Finance.openFreightAgent(${a.id})`,
      settleFn: `Finance.openFreightAgent(${a.id},{settle:true})`,
      cta: "Settle",
    })).join("");

    el.innerHTML = `
      <p class="fin-needs-intro">${total} part${total === 1 ? "y" : "ies"} need action</p>
      ${section("Collect", arDue.length, arRows, "ar")}
      ${section("Pay", apDue.length, apRows, "ap")}
      ${section("Freight", frDue.length, frRows, "freight")}`;
  }

  /* —— Charts —— */
  function barChart(series, keys, colors) {
    if (!series?.length) return `<div class="fin-empty-chart">No data yet</div>`;
    const vals = series.flatMap(s => keys.map(k => Math.abs(Number(s[k]) || 0)));
    const max = Math.max(...vals, 1);
    const w = 420, h = 160, pad = 28, gap = 8;
    const groupW = (w - pad * 2) / series.length;
    const barW = Math.max(6, (groupW - gap) / keys.length - 2);
    let bars = "";
    series.forEach((s, i) => {
      keys.forEach((k, ki) => {
        const v = Math.abs(Number(s[k]) || 0);
        const bh = (v / max) * (h - pad * 2);
        const x = pad + i * groupW + ki * (barW + 2);
        const y = h - pad - bh;
        const lbl = CHART_LABELS[k] || k;
        bars += `<rect x="${x}" y="${y}" width="${barW}" height="${bh}" fill="${colors[ki]}" rx="2">
          <title>${s.month} ${lbl}: ${fmtPrice(s[k])}</title></rect>`;
      });
      bars += `<text x="${pad + i * groupW + groupW / 2}" y="${h - 8}" text-anchor="middle" class="fin-chart-label">${ctx.esc((s.month || "").slice(5))}</text>`;
    });
    const legend = keys.map((k, i) => `<span class="fin-legend"><i style="background:${colors[i]}"></i>${ctx.esc(CHART_LABELS[k] || k)}</span>`).join("");
    return `<div class="fin-chart">${legend}<svg viewBox="0 0 ${w} ${h}" class="fin-svg">${bars}</svg></div>`;
  }

  function donutChart(parts, colors) {
    const items = (parts || []).map((p, i) => ({
      label: CHART_LABELS[p.label] || p.label || p.category,
      value: Math.abs(Number(p.amount) || 0),
      color: colors[i % colors.length],
    })).filter(p => p.value > 0);
    if (!items.length) return `<div class="fin-empty-chart">No data yet</div>`;
    const total = items.reduce((s, p) => s + p.value, 0) || 1;
    let angle = -Math.PI / 2;
    const cx = 70, cy = 70, r = 52, ir = 30;
    let paths = "";
    items.forEach(p => {
      const sweep = (p.value / total) * Math.PI * 2;
      const x1 = cx + r * Math.cos(angle);
      const y1 = cy + r * Math.sin(angle);
      const x2 = cx + r * Math.cos(angle + sweep);
      const y2 = cy + r * Math.sin(angle + sweep);
      const xi1 = cx + ir * Math.cos(angle + sweep);
      const yi1 = cy + ir * Math.sin(angle + sweep);
      const xi2 = cx + ir * Math.cos(angle);
      const yi2 = cy + ir * Math.sin(angle);
      const large = sweep > Math.PI ? 1 : 0;
      paths += `<path d="M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} L ${xi1} ${yi1} A ${ir} ${ir} 0 ${large} 0 ${xi2} ${yi2} Z" fill="${p.color}">
        <title>${ctx.esc(p.label)}: ${fmtPrice(p.value)}</title></path>`;
      angle += sweep;
    });
    const legend = items.map(p => `<span class="fin-legend"><i style="background:${p.color}"></i>${ctx.esc(p.label)} ${fmtPrice(p.value)}</span>`).join("");
    return `<div class="fin-chart fin-donut">${legend}<svg viewBox="0 0 140 140" class="fin-svg fin-svg-sm">${paths}</svg></div>`;
  }

  function hBarList(rows, labelKey, valueKey) {
    if (!rows?.length) return `<div class="fin-empty-chart">Nothing due</div>`;
    const max = Math.max(...rows.map(r => Math.abs(Number(r[valueKey]) || 0)), 1);
    return `<div class="fin-hbar-list">${rows.map(r => {
      const v = Math.abs(Number(r[valueKey]) || 0);
      const pct = Math.round((v / max) * 100);
      return `<div class="fin-hbar-row">
        <div class="fin-hbar-label">${ctx.esc(r[labelKey])}</div>
        <div class="fin-hbar-track"><div class="fin-hbar-fill" style="width:${pct}%"></div></div>
        <div class="fin-hbar-val">${fmtPrice(r[valueKey])}</div>
      </div>`;
    }).join("")}</div>`;
  }

  function settleSuccess({ title, party, amount, balanceAfter, reopenFn }) {
    ctx.openDetail?.(title, `
      <div class="doc-success-banner">
        <strong>Payment settled</strong>
        <span>${ctx.esc(party)} · ${fmtPrice(amount)}</span>
      </div>
      <div class="review-block">
        ${ctx.reviewRow("Party", party)}
        ${ctx.reviewRow("Amount", fmtPrice(amount))}
        ${ctx.reviewRow("Balance after", fmtPrice(balanceAfter))}
      </div>`,
      `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail();${reopenFn}">Open party</button>
       <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail();App.showView('money');Finance.showHub()">Done</button>`,
      "sm");
  }

  /* —— AP —— */
  async function loadApList() {
    if (!ctx.api) return ctx.toast?.("Finance not ready — hard refresh the page", "error");
    ctx.showLoading?.();
    try {
      vendors = await ctx.api("/accounts-payable", {}, 0);
      if (!Array.isArray(vendors)) vendors = [];
      renderApList();
    } catch (e) { ctx.toast?.(e.message || "Failed to load AP", "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderApList() {
    const el = document.getElementById("finance-ap-list");
    const sum = document.getElementById("finance-ap-summary");
    if (!el) return;
    refreshChipCounts();
    renderHubChrome();
    let list = rankParties(vendors, "vendor_label");
    if (!showSettled) list = list.filter(v => Number(v.outstanding) > 0);
    const dueVendors = vendors.filter(v => Number(v.outstanding) > 0);
    const totalOut = dueVendors.reduce((s, v) => s + (Number(v.outstanding) || 0), 0);
    if (sum) {
      sum.innerHTML = `
        <div class="home-card fin-list-sum">
          <div class="fin-list-sum-top">
            <div>
              <span class="fin-pulse-label">To pay</span>
              <strong class="fin-list-sum-val">${fmtPriceShort(totalOut)}</strong>
              <span class="fin-list-sum-sub">${dueVendors.length} vendor${dueVendors.length === 1 ? "" : "s"}</span>
            </div>
            <label class="fin-filter-chip ${showSettled ? "is-on" : ""}">
              <input type="checkbox" ${showSettled ? "checked" : ""} onchange="Finance.setShowSettled(this.checked)" />
              Show clear
            </label>
          </div>
          ${dueVendors.length ? hBarList(dueVendors.slice(0, 5), "vendor_label", "outstanding") : ""}
        </div>`;
    }
    if (!list.length) {
      const q = hubSearch.trim();
      el.innerHTML = OrdersUI.emptyState({
        title: q ? "No matches" : (showSettled ? "No vendor accounts" : "No vendors to pay"),
        sub: q
          ? "Try business name, contact, alias, phone, or city."
          : (showSettled ? "Receive stock or set opening to open AP." : "Receive stock from vendors to create bills."),
      });
      return;
    }
    el.innerHTML = `<div class="ord-card-list">${list.map(v => {
      const due = Number(v.outstanding) || 0;
      return dueRow({
        name: v.vendor_label,
        amount: due,
        openFn: `Finance.openVendorAp(${v.vendor_id})`,
        settleFn: `Finance.openVendorAp(${v.vendor_id},{settle:true})`,
        cta: "Pay",
        settled: due <= 0,
      });
    }).join("")}</div>`;
  }

  function setShowSettled(on) {
    showSettled = !!on;
    if (browseSection === "ap") renderApList();
    else if (browseSection === "ar") renderArList();
    else if (browseSection === "freight") renderFreightList();
  }

  async function openVendorAp(vendorId, opts = {}) {
    if (!ctx.isAdmin?.()) return ctx.toast?.("Finance is admin only", "error");
    ctx.showLoading?.();
    try {
      apDetail = await ctx.api(`/accounts-payable/vendor/${vendorId}`, {}, 0);
      currentVendor = vendorId;
      apTab = "statement";
      expandedBillId = null;
      document.getElementById("finance-hub")?.classList.add("hidden");
      document.getElementById("finance-ap-detail")?.classList.remove("hidden");
      renderApDetail();
      if (opts?.settle) openSettle();
      App.updateGlobalBack?.();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function setApTab(tab) {
    apTab = tab;
    renderApDetail();
  }

  function toggleBill(receiptId) {
    expandedBillId = expandedBillId === receiptId ? null : receiptId;
    renderApDetail();
  }

  function renderApDetail() {
    const hero = document.getElementById("finance-ap-hero");
    const body = document.getElementById("finance-ap-body");
    if (!apDetail || !body) return;
    const outstanding = Number(apDetail.outstanding) || 0;
    if (hero) {
      hero.innerHTML = HubUI.pageHero({
        title: apDetail.vendor_label,
        sub: `Pay vendors · ${outstanding > 0 ? `${fmtPrice(outstanding)} due` : "Clear"}`,
        actionsHtml: `
            ${outstanding > 0 ? `<button class="btn btn-primary" onclick="Finance.openSettle()">Pay</button>` : ""}
            <button class="btn btn-secondary" onclick="Finance.shareApStatement()">Print / PDF / WA</button>
            <button class="btn btn-secondary" onclick="Finance.setApOpeningBalance()">Set opening</button>
            ${typeof Vendors !== "undefined" ? `<button class="btn btn-secondary" onclick="App.showView('people');Vendors.openDetail(${currentVendor})">Open vendor</button>` : ""}`,
      });
    }
    const tabs = `
      <div class="fin-tabs">
        <button type="button" class="fin-tab ${apTab === "statement" ? "is-active" : ""}" onclick="Finance.setApTab('statement')">Statement</button>
        <button type="button" class="fin-tab ${apTab === "ledger" ? "is-active" : ""}" onclick="Finance.setApTab('ledger')">Ledger</button>
        <button type="button" class="fin-tab ${apTab === "payments" ? "is-active" : ""}" onclick="Finance.setApTab('payments')">Payments</button>
      </div>`;
    let content = "";
    if (apTab === "statement") content = renderApStatement();
    else if (apTab === "payments") content = renderApPayments();
    else content = renderApLedgerFlat();

    body.innerHTML = `
      <div class="review-grid" style="margin-bottom:20px;">
        ${ctx.reviewRow("Due", fmtPrice(apDetail.outstanding))}
        ${ctx.reviewRow("Opening", fmtPrice(apDetail.opening_total || "0"))}
        ${ctx.reviewRow("Opening as on", apDetail.opening_as_on)}
        ${ctx.reviewRow("Total bills", fmtPrice(apDetail.bill_total))}
        ${ctx.reviewRow("Bill corrections", fmtPrice(apDetail.debit_note_total))}
        ${ctx.reviewRow("Paid", fmtPrice(apDetail.payment_total))}
      </div>
      <div style="margin-bottom:12px;">${tabs}</div>
      ${content}`;
  }

  function renderApStatement() {
    const bills = apDetail.bills || [];
    if (!bills.length) return OrdersUI.emptyState({ title: "No bills yet", sub: "Bills appear after you receive/bill vendor stock." });
    return `<div class="fin-stmt">${bills.map(b => {
      const open = expandedBillId === b.receipt_id;
      const dns = b.debit_notes || [];
      return `<div class="fin-bill-card ${open ? "is-open" : ""}">
        <button type="button" class="fin-bill-head" onclick="Finance.toggleBill(${b.receipt_id})">
          <div>
            <div class="fin-bill-title">Bill ${ctx.esc(b.bill_number || `#${b.receipt_id}`)}</div>
            <div class="fin-bill-meta">${b.created_at ? new Date(b.created_at).toLocaleString() : ""} · ${dns.length} correction${dns.length === 1 ? "" : "s"}</div>
          </div>
          <div class="fin-bill-amounts">
            <span>Bill ${fmtPrice(b.bill_amount)}</span>
            <span class="fin-muted">DN ${fmtPrice(b.debit_note_total)}</span>
            <strong>Net ${fmtPrice(b.net_payable)}</strong>
          </div>
        </button>
        ${open ? `<div class="fin-bill-body">
          ${(b.lines || []).length ? `<table class="data fin-mini"><thead><tr><th>Product</th><th>Recv</th><th>Billed</th></tr></thead><tbody>
            ${b.lines.map(l => `<tr><td>${ctx.esc(l.our_product_id)}</td><td>${l.quantity_received}</td><td>${l.quantity_billed}</td></tr>`).join("")}
          </tbody></table>` : ""}
          ${dns.length ? `<div class="fin-dn-block"><div class="fin-dn-title">Bill corrections</div>
            ${dns.map(d => {
              const effect = Number(d.payable_effect ?? d.amount) || 0;
              const title = d.our_product_id
                ? `${ctx.esc(d.our_product_id)} × ${d.quantity ?? "—"} (${ctx.esc(d.direction || d.note_type || "")})`
                : `Value (${ctx.esc(d.direction || "adj.")})`;
              return `<div class="fin-dn-row">
                <div><strong>${title}</strong>${d.notes ? `<div class="fin-dn-note">${ctx.esc(d.notes)}</div>` : ""}
                <div class="fin-muted">${d.created_at ? new Date(d.created_at).toLocaleString() : ""}</div></div>
                <strong class="${effect < 0 ? "is-pos" : "is-neg"}">${fmtPrice(effect)}</strong>
              </div>`;
            }).join("")}
          </div>` : `<p class="fin-muted">No debit notes on this bill.</p>`}
          <div style="margin-top:12px;">
            <button type="button" class="btn btn-secondary btn-sm" onclick="Finance.addDebitNote(${b.receipt_id})">+ Bill correction</button>
          </div>
        </div>` : ""}
      </div>`;
    }).join("")}</div>`;
  }

  async function addDebitNote(receiptId) {
    if (!currentVendor || typeof DebitNotes === "undefined") {
      return ctx.toast?.("Debit notes module failed — hard refresh", "error");
    }
    await DebitNotes.openForReceipt({
      vendorId: currentVendor,
      receiptId,
      receivingLines: [],
      onDone: async () => {
        ctx.invalidateCache?.("/accounts-payable");
        await openVendorAp(currentVendor);
        loadOverviewSilent();
      },
    });
  }

  function renderApLedgerFlat() {
    return `<div class="card table-wrap">
      <table class="data"><thead><tr>
        <th>When</th><th>Type</th><th>Description</th><th>Amount</th><th>Balance</th>
      </tr></thead><tbody>
        ${(apDetail.entries || []).map(e => `<tr class="clickable" onclick="Finance.openEntry(${e.id})">
          <td style="font-size:12px;">${new Date(e.created_at).toLocaleString()}</td>
          <td>${ctx.esc(e.entry_type)}</td>
          <td>${ctx.esc(e.description)}</td>
          <td>${fmtPrice(e.signed_amount)}</td>
          <td><strong>${fmtPrice(e.running_balance)}</strong></td>
        </tr>`).join("")}
      </tbody></table>
    </div>`;
  }

  function renderApPayments() {
    const pays = apDetail.payments || [];
    if (!pays.length) return OrdersUI.emptyState({ title: "No payments yet", sub: "Pay above to record a payment." });
    return `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>When</th><th>Reference</th><th>Comment</th><th>Amount</th><th>Balance after</th><th></th>
    </tr></thead><tbody>
      ${pays.map(p => {
        const undone = !!p.reversed;
        return `<tr>
        <td style="font-size:12px;">${new Date(p.created_at).toLocaleString()}</td>
        <td><strong>${ctx.esc(p.payment_ref || "—")}</strong>${undone ? ` <span class="badge badge-amber">Reversed</span>` : ""}</td>
        <td>${ctx.esc(p.payment_comment || "—")}</td>
        <td>${fmtPrice(p.signed_amount)}</td>
        <td>${fmtPrice(p.running_balance_after)}</td>
        <td style="white-space:nowrap;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;">
          ${p.payment_receipt_url ? `<a href="${ctx.esc(p.payment_receipt_url)}" target="_blank" class="btn btn-secondary btn-sm">Receipt</a>` : ""}
          ${!undone && ctx.isAdmin?.() ? `
            <button type="button" class="btn btn-secondary btn-sm" onclick="Finance.undoApPayment(${p.id},'reverse')">Reverse</button>
            <button type="button" class="btn btn-ghost btn-sm" onclick="Finance.undoApPayment(${p.id},'void')">Void</button>
          ` : ""}
        </td>
      </tr>`;
      }).join("")}
    </tbody></table></div>`;
  }

  function openEntry(entryId) {
    const e = (apDetail?.entries || []).find(x => x.id === entryId);
    if (!e) return;
    let extra = "";
    if (e.entry_type === "bill") {
      extra = `${ctx.reviewRow("Bill amount", fmtPrice(e.bill_amount))}
        ${ctx.reviewRow("Debit note adj.", fmtPrice(e.debit_note_total))}
        ${ctx.reviewRow("Net payable", fmtPrice(e.net_payable))}
        ${e.bill_number ? ctx.reviewRow("Bill #", e.bill_number) : ""}`;
      if (e.details?.lines?.length) {
        extra += `<table class="data" style="margin-top:12px;font-size:13px;"><thead><tr><th>Product</th><th>Recv</th><th>Billed</th></tr></thead><tbody>
          ${e.details.lines.map(l => `<tr><td>${ctx.esc(l.our_product_id)}</td><td>${l.quantity_received}</td><td>${l.quantity_billed}</td></tr>`).join("")}
        </tbody></table>`;
      }
      if (e.details?.debit_notes?.length) {
        extra += `<p style="margin-top:12px;font-weight:600;font-size:13px;">Debit notes on this bill</p>
          <table class="data" style="font-size:13px;"><thead><tr><th>Type</th><th>Item</th><th>Note</th><th>Amount</th></tr></thead><tbody>
          ${e.details.debit_notes.map(d => `<tr><td>${ctx.esc(d.note_type)}</td><td>${ctx.esc(d.our_product_id || "—")}</td><td>${ctx.esc(d.notes || "—")}</td><td>${fmtPrice(d.payable_effect ?? d.amount)}</td></tr>`).join("")}
        </tbody></table>`;
      }
    }
    if (e.entry_type === "debit_note" && e.details?.debit_note) {
      const d = e.details.debit_note;
      extra = `${ctx.reviewRow("Type", d.note_type)}${d.our_product_id ? ctx.reviewRow("Product", d.our_product_id) : ""}${d.quantity ? ctx.reviewRow("Qty", d.quantity) : ""}${d.notes ? ctx.reviewRow("Note", d.notes) : ""}${ctx.reviewRow("Payable effect", fmtPrice(d.payable_effect ?? d.amount))}`;
    }
    if (e.entry_type === "payment") {
      extra = `${ctx.reviewRow("Payment ref", e.payment_ref || "—")}${e.payment_comment ? ctx.reviewRow("Comment", e.payment_comment) : ""}`;
      if (e.payment_receipt_url) extra += `<p style="margin-top:8px;"><a href="${ctx.esc(e.payment_receipt_url)}" target="_blank" class="btn btn-secondary btn-sm">View receipt</a></p>`;
    }
    if (e.entry_type === "payment_reversal") {
      extra = `${ctx.reviewRow("Reverses payment #", e.reverses_entry_id || "—")}${e.payment_ref ? ctx.reviewRow("Original ref", e.payment_ref) : ""}`;
    }
    const alreadyReversed = e.entry_type === "payment" && (apDetail?.entries || []).some(
      (x) => x.entry_type === "payment_reversal" && x.reverses_entry_id === e.id
    );
    const undoBtns = (e.entry_type === "payment" && !alreadyReversed && ctx.isAdmin?.())
      ? `<button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail();Finance.undoApPayment(${e.id},'reverse')">Reverse</button>
         <button class="btn btn-ghost" style="flex:1;" onclick="App.closeDetail();Finance.undoApPayment(${e.id},'void')">Void</button>`
      : "";
    ctx.openDetail(e.description, `
      <div class="review-grid">
        ${ctx.reviewRow("Type", e.entry_type)}
        ${ctx.reviewRow("Amount", fmtPrice(e.signed_amount))}
        ${ctx.reviewRow("Running balance", fmtPrice(e.running_balance))}
        ${ctx.reviewRow("When", new Date(e.created_at).toLocaleString())}
        ${ctx.reviewRow("By", e.created_by_name)}
      </div>${extra}`,
      `${undoBtns}<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`, "md");
  }

  function openSettle() {
    if (!apDetail) return;
    const outstanding = Number(apDetail.outstanding) || 0;
    const title = document.querySelector("#settle-modal h3");
    if (title) title.textContent = "Pay";
    const footerBtn = document.querySelector("#settle-modal .btn-primary");
    if (footerBtn) footerBtn.textContent = "Pay";
    document.getElementById("settle-body").innerHTML = `
      <div class="review-block" style="margin-bottom:16px;">
        ${ctx.reviewRow("Vendor", apDetail.vendor_label)}
        ${ctx.reviewRow("Due", fmtPrice(outstanding))}
      </div>
      <label class="label">Payment reference / ID</label>
      <input class="input" id="settle-ref" style="margin-bottom:12px;" placeholder="UTR, cheque #, etc." />
      <label class="label">Amount (₹)</label>
      <input type="number" step="0.01" class="input" id="settle-amount" value="" placeholder="Enter amount" style="margin-bottom:12px;" />
      <label class="label">Comment (optional)</label>
      <input class="input" id="settle-comment" style="margin-bottom:12px;" />
      <label class="label">Upload payment receipt (optional)</label>
      <input type="file" class="input" accept=".pdf,image/*" onchange="Finance.setSettleFile(this.files[0])" />
      <span id="settle-file-label" style="font-size:12px;color:var(--muted);"></span>`;
    document.getElementById("settle-modal").classList.remove("hidden");
    settleFile = null;
  }

  function setSettleFile(file) {
    settleFile = file || null;
    const el = document.getElementById("settle-file-label");
    if (el) el.textContent = file ? file.name : "";
  }

  function closeSettle() { document.getElementById("settle-modal")?.classList.add("hidden"); }

  async function submitSettle() {
    if (!currentVendor || !apDetail) return;
    const ref = (document.getElementById("settle-ref")?.value || "").trim();
    const amount = parseFloat(document.getElementById("settle-amount")?.value || "0");
    const comment = (document.getElementById("settle-comment")?.value || "").trim() || null;
    if (!ref) return ctx.toast("Enter payment reference", "error");
    if (!amount || amount <= 0) return ctx.toast("Enter valid amount", "error");
    const party = apDetail.vendor_label;
    const vid = currentVendor;
    ctx.showLoading?.();
    try {
      let key = null;
      if (settleFile) {
        const fd = new FormData();
        fd.append("vendor_id", String(currentVendor));
        fd.append("payment_ref", ref);
        fd.append("file", settleFile);
        const API = ctx.apiBase ? ctx.apiBase() : `${location.origin}/api/v1`;
        const h = {};
        if (sessionStorage.getItem("jc_auth_mode") === "admin") h["X-Admin-Key"] = sessionStorage.getItem("jc_admin_key") || "";
        else h["Authorization"] = `Bearer ${sessionStorage.getItem("jc_staff_token") || ""}`;
        const res = await fetch(`${API}/accounts-payable/upload-payment-receipt`, { method: "POST", headers: h, body: fd });
        if (!res.ok) throw new Error("Receipt upload failed");
        key = (await res.json()).key;
      }
      await ctx.api(`/accounts-payable/vendor/${currentVendor}/settle`, {
        method: "POST",
        body: JSON.stringify({ payment_ref: ref, amount, payment_receipt_key: key, comment }),
      });
      ctx.invalidateCache?.("/accounts-payable");
      ctx.invalidateCache?.("/finance");
      closeSettle();
      ctx.toast("Paid", "success");
      await openVendorAp(vid);
      const bal = Number(apDetail?.outstanding) || 0;
      settleSuccess({
        title: "Paid",
        party,
        amount,
        balanceAfter: bal,
        reopenFn: `Finance.openVendorAp(${vid})`,
      });
      loadApList();
      loadOverviewSilent();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function showApFromVendor(vendorId) {
    if (!ctx.isAdmin?.()) return ctx.toast?.("Finance is admin only", "error");
    App.closeDetail?.();
    ctx.showView?.("money");
    openVendorAp(vendorId);
  }

  function showArFromCustomer(customerId) {
    if (!ctx.isAdmin?.()) return ctx.toast?.("Finance is admin only", "error");
    App.closeDetail?.();
    ctx.showView?.("money");
    openCustomerAr(customerId);
  }

  /* —— AR —— */
  async function loadArList() {
    if (!ctx.api) return ctx.toast?.("Finance not ready — hard refresh", "error");
    ctx.showLoading?.();
    try {
      customers = await ctx.api("/accounts-receivable", {}, 0);
      if (!Array.isArray(customers)) customers = [];
      renderArList();
    } catch (e) { ctx.toast?.(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderArList() {
    const el = document.getElementById("finance-ar-list");
    const sum = document.getElementById("finance-ar-summary");
    if (!el) return;
    refreshChipCounts();
    renderHubChrome();
    let list = rankParties(customers, "customer_label");
    if (!showSettled) list = list.filter(c => Number(c.outstanding) > 0);
    const dueCustomers = customers.filter(c => Number(c.outstanding) > 0);
    const totalOut = dueCustomers.reduce((s, c) => s + (Number(c.outstanding) || 0), 0);
    if (sum) {
      sum.innerHTML = `
        <div class="home-card fin-list-sum">
          <div class="fin-list-sum-top">
            <div>
              <span class="fin-pulse-label">To collect</span>
              <strong class="fin-list-sum-val">${fmtPriceShort(totalOut)}</strong>
              <span class="fin-list-sum-sub">${dueCustomers.length} customer${dueCustomers.length === 1 ? "" : "s"}</span>
            </div>
            <label class="fin-filter-chip ${showSettled ? "is-on" : ""}">
              <input type="checkbox" ${showSettled ? "checked" : ""} onchange="Finance.setShowSettled(this.checked)" />
              Show clear
            </label>
          </div>
          ${dueCustomers.length ? hBarList(dueCustomers.slice(0, 5), "customer_label", "outstanding") : ""}
        </div>`;
    }
    if (!list.length) {
      const q = hubSearch.trim();
      el.innerHTML = OrdersUI.emptyState({
        title: q ? "No matches" : (showSettled ? "No customer accounts" : "Nothing to collect"),
        sub: q
          ? "Try business name, contact, alias, phone, or city."
          : (showSettled ? "Create bills or set opening to open AR." : "Process customer orders to create bills."),
      });
      return;
    }
    el.innerHTML = `<div class="ord-card-list">${list.map(c => {
      const due = Number(c.outstanding) || 0;
      return dueRow({
        name: c.customer_label,
        amount: due,
        openFn: `Finance.openCustomerAr(${c.customer_id})`,
        settleFn: `Finance.openCustomerAr(${c.customer_id},{settle:true})`,
        cta: "Collect",
        settled: due <= 0,
      });
    }).join("")}</div>`;
  }

  async function openCustomerAr(customerId, opts = {}) {
    if (!ctx.isAdmin?.()) return;
    ctx.showLoading?.();
    try {
      arDetail = await ctx.api(`/accounts-receivable/customer/${customerId}`, {}, 0);
      currentCustomer = customerId;
      arTab = "statement";
      document.getElementById("finance-hub")?.classList.add("hidden");
      document.getElementById("finance-ar-detail")?.classList.remove("hidden");
      renderArDetail();
      if (opts?.settle) openArSettle();
      App.updateGlobalBack?.();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function setArTab(tab) {
    arTab = tab;
    renderArDetail();
  }

  function renderArDetail() {
    const hero = document.getElementById("finance-ar-hero");
    const body = document.getElementById("finance-ar-body");
    if (!arDetail || !body) return;
    const outstanding = Number(arDetail.outstanding) || 0;
    if (hero) {
      hero.innerHTML = HubUI.pageHero({
        title: arDetail.customer_label,
        sub: `Collect · ${outstanding > 0 ? `${fmtPrice(outstanding)} due` : "Clear"}`,
        actionsHtml: `
            ${outstanding > 0 ? `<button class="btn btn-primary" onclick="Finance.openArSettle()">Collect</button>` : ""}
            <button class="btn btn-secondary" onclick="Finance.shareArStatement()">Print / PDF / WA</button>
            <button class="btn btn-secondary" onclick="Finance.setArOpeningBalance()">Set opening</button>
            <button class="btn btn-secondary" onclick="App.openCustomerDetail(${currentCustomer})">Open customer</button>`,
      });
    }
    const tabs = `
      <div class="fin-tabs">
        <button type="button" class="fin-tab ${arTab === "statement" ? "is-active" : ""}" onclick="Finance.setArTab('statement')">Statement</button>
        <button type="button" class="fin-tab ${arTab === "ledger" ? "is-active" : ""}" onclick="Finance.setArTab('ledger')">Ledger</button>
        <button type="button" class="fin-tab ${arTab === "payments" ? "is-active" : ""}" onclick="Finance.setArTab('payments')">Payments</button>
      </div>`;
    let content = "";
    if (arTab === "statement") content = renderArStatement();
    else if (arTab === "payments") content = renderArPayments();
    else content = renderArLedgerFlat();
    const creditRows = arDetail.credit_unlimited
      ? ctx.reviewRow("Credit limit", "Unlimited")
      : `${ctx.reviewRow("Credit limit", fmtPrice(arDetail.credit_limit))}
         ${ctx.reviewRow("Credit left", fmtPrice(arDetail.credit_left))}
         ${arDetail.credit_override ? ctx.reviewRow("Override", "Allowed") : ""}`;

    body.innerHTML = `
      <div class="review-grid" style="margin-bottom:20px;">
        ${ctx.reviewRow("Due", fmtPrice(arDetail.outstanding))}
        ${creditRows}
        ${ctx.reviewRow("Opening", fmtPrice(arDetail.opening_total || "0"))}
        ${ctx.reviewRow("Opening as on", arDetail.opening_as_on)}
        ${ctx.reviewRow("Total bills", fmtPrice(arDetail.bill_total))}
        ${ctx.reviewRow("Collected", fmtPrice(arDetail.payment_total))}
        ${ctx.reviewRow("Credit notes", fmtPrice(arDetail.credit_total || 0))}
      </div>
      <div style="margin-bottom:12px;">${tabs}</div>
      ${content}`;
  }

  function shareArStatement() {
    if (!currentCustomer) return;
    DocShare.shareFlow({
      kind: "ar_statement",
      id: currentCustomer,
      filename: `ar_${currentCustomer}.pdf`,
      caption: `Statement — ${arDetail?.customer_label || ""}`,
    });
  }

  function shareApStatement() {
    if (!currentVendor) return;
    DocShare.shareFlow({
      kind: "ap_statement",
      id: currentVendor,
      filename: `ap_${currentVendor}.pdf`,
      caption: `Statement — ${apDetail?.vendor_label || ""}`,
    });
  }

  async function setArOpeningBalance() {
    if (!currentCustomer || !arDetail) return;
    const today = new Date().toISOString().slice(0, 10);
    const cid = currentCustomer;
    ctx.openDetail("Opening", `
      <p style="color:var(--muted);font-size:13px;margin:0 0 16px;">Tally start they owed. Use 0 to clear. Not Due (Due = opening + bills − collected).</p>
      <label class="label">Opening (₹)</label>
      <input type="number" step="0.01" min="0" class="input" id="ar-ob-amt" value="${ctx.esc(arDetail.opening_total || "0")}" style="margin-bottom:12px;" />
      <label class="label">As on date</label>
      <input type="date" class="input" id="ar-ob-as-on" value="${ctx.esc(arDetail.opening_as_on || today)}" />
    `, `
      <button class="btn btn-secondary" onclick="App.closeDetail()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Finance.saveArOpeningBalance(${cid})">Save</button>
    `, "sm");
  }

  async function saveArOpeningBalance(customerId) {
    const amount = parseFloat(document.getElementById("ar-ob-amt")?.value || "0");
    const asOn = (document.getElementById("ar-ob-as-on")?.value || "").trim();
    if (!Number.isFinite(amount) || amount < 0) return ctx.toast("Enter a valid amount", "error");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(asOn)) return ctx.toast("Pick a valid date", "error");
    ctx.showLoading?.();
    try {
      await ctx.api(`/accounts-receivable/customer/${customerId}/opening-balance`, {
        method: "POST",
        body: JSON.stringify({ amount, as_on: asOn }),
      });
      ctx.invalidateCache?.("/accounts-receivable");
      ctx.invalidateCache?.("/customers");
      ctx.toast("Opening saved", "success");
      App.closeDetail?.();
      await openCustomerAr(customerId);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function setApOpeningBalance() {
    if (!currentVendor || !apDetail) return;
    const today = new Date().toISOString().slice(0, 10);
    const vid = currentVendor;
    ctx.openDetail("Opening", `
      <p style="color:var(--muted);font-size:13px;margin:0 0 16px;">Tally start you owed this vendor. Use 0 to clear. Not Due (Due = opening + bills − paid).</p>
      <label class="label">Opening (₹)</label>
      <input type="number" step="0.01" min="0" class="input" id="ap-ob-amt" value="${ctx.esc(apDetail.opening_total || "0")}" style="margin-bottom:12px;" />
      <label class="label">As on date</label>
      <input type="date" class="input" id="ap-ob-as-on" value="${ctx.esc(apDetail.opening_as_on || today)}" />
    `, `
      <button class="btn btn-secondary" onclick="App.closeDetail()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Finance.saveApOpeningBalance(${vid})">Save</button>
    `, "sm");
  }

  async function saveApOpeningBalance(vendorId) {
    const amount = parseFloat(document.getElementById("ap-ob-amt")?.value || "0");
    const asOn = (document.getElementById("ap-ob-as-on")?.value || "").trim();
    if (!Number.isFinite(amount) || amount < 0) return ctx.toast("Enter a valid amount", "error");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(asOn)) return ctx.toast("Pick a valid date", "error");
    ctx.showLoading?.();
    try {
      await ctx.api(`/accounts-payable/vendor/${vendorId}/opening-balance`, {
        method: "POST",
        body: JSON.stringify({ amount, as_on: asOn }),
      });
      ctx.invalidateCache?.("/accounts-payable");
      ctx.invalidateCache?.("/vendors");
      ctx.toast("Opening saved", "success");
      App.closeDetail?.();
      await openVendorAp(vendorId);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderArStatement() {
    const bills = (arDetail.entries || []).filter(e => e.entry_type === "bill" || e.entry_type === "credit_note" || e.entry_type === "opening_balance");
    if (!bills.length) return OrdersUI.emptyState({ title: "No bills yet", sub: "Bills appear after you process customer orders." });
    return `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>When</th><th>Type</th><th>Description</th><th>Amount</th><th>Balance</th>
    </tr></thead><tbody>
      ${bills.map(e => {
        const badgeCls = e.entry_type === "credit_note" ? "badge-green" : e.entry_type === "opening_balance" ? "badge-blue" : "badge-amber";
        const typeLabel = e.entry_type === "opening_balance" ? "Opening" : e.entry_type === "credit_note" ? "Credit Note" : "Bill";
        return `<tr>
        <td style="font-size:12px;">${e.value_date ? new Date(e.value_date).toLocaleDateString("en-IN") : new Date(e.created_at).toLocaleString()}</td>
        <td><span class="badge ${badgeCls}">${typeLabel}</span></td>
        <td>${ctx.esc(e.description)}${e.return_id ? ` <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();Returns.openReturn(${e.return_id})">View</button>` : ""}</td>
        <td>${fmtPrice(e.signed_amount)}</td>
        <td><strong>${fmtPrice(e.running_balance)}</strong></td>
      </tr>`;}).join("")}
    </tbody></table></div>`;
  }

  function renderArLedgerFlat() {
    return `<div class="card table-wrap">
      <table class="data"><thead><tr>
        <th>When</th><th>Type</th><th>Description</th><th>Amount</th><th>Balance</th>
      </tr></thead><tbody>
        ${(arDetail.entries || []).map(e => {
          const badgeCls = e.entry_type === "credit_note" ? "badge-green" : e.entry_type === "opening_balance" ? "badge-blue" : e.entry_type === "bill" ? "badge-amber" : e.entry_type === "payment_reversal" ? "badge-red" : "badge-green";
          const typeLabel = { bill: "Bill", credit_note: "Credit Note", opening_balance: "Opening", payment: "Payment", payment_reversal: "Reversal" }[e.entry_type] || e.entry_type;
          return `<tr>
          <td style="font-size:12px;">${e.value_date ? new Date(e.value_date).toLocaleDateString("en-IN") : new Date(e.created_at).toLocaleString()}</td>
          <td><span class="badge ${badgeCls}">${typeLabel}</span></td>
          <td>${ctx.esc(e.description)}${e.return_id ? ` <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();Returns.openReturn(${e.return_id})">View</button>` : ""}</td>
          <td>${fmtPrice(e.signed_amount)}</td>
          <td><strong>${fmtPrice(e.running_balance)}</strong></td>
        </tr>`;}).join("")}
      </tbody></table>
    </div>`;
  }

  function reversedPaymentIds(entries) {
    const ids = new Set();
    for (const e of entries || []) {
      if (e.entry_type === "payment_reversal" && e.reverses_entry_id) ids.add(e.reverses_entry_id);
    }
    return ids;
  }

  function renderArPayments() {
    const entries = arDetail.entries || [];
    const reversed = reversedPaymentIds(entries);
    const pays = entries.filter(e => e.entry_type === "payment" || e.entry_type === "payment_reversal");
    if (!pays.length) return OrdersUI.emptyState({ title: "No payments yet", sub: "Collect above when cash comes in." });
    return `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>When</th><th>Reference</th><th>Comment</th><th>Amount</th><th>Balance</th><th></th>
    </tr></thead><tbody>
      ${pays.map(p => {
        const isRev = p.entry_type === "payment_reversal";
        const undone = reversed.has(p.id);
        return `<tr>
        <td style="font-size:12px;">${new Date(p.created_at).toLocaleString()}</td>
        <td><strong>${ctx.esc(p.payment_ref || "—")}</strong>
          ${isRev ? ` <span class="badge badge-amber">Reversal</span>` : ""}
          ${undone ? ` <span class="badge badge-amber">Reversed</span>` : ""}
        </td>
        <td>${ctx.esc(p.payment_comment || p.description || "—")}</td>
        <td>${fmtPrice(p.signed_amount)}</td>
        <td>${fmtPrice(p.running_balance)}</td>
        <td style="white-space:nowrap;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;">
          ${!isRev && !undone && ctx.isAdmin?.() ? `
            <button type="button" class="btn btn-secondary btn-sm" onclick="Finance.undoArPayment(${p.id},'reverse')">Reverse</button>
            <button type="button" class="btn btn-ghost btn-sm" onclick="Finance.undoArPayment(${p.id},'void')">Void</button>
          ` : ""}
        </td>
      </tr>`;
      }).join("")}
    </tbody></table></div>`;
  }

  async function undoArPayment(entryId, mode, customerId) {
    if (!ctx.isAdmin?.()) return;
    const cid = customerId || currentCustomer;
    if (!cid) return;
    const label = mode === "void" ? "Void" : "Reverse";
    const reason = prompt(`${label} this payment — reason (required):`);
    if (reason == null) return;
    if (!String(reason).trim()) return ctx.toast("Reason required", "error");
    if (!confirm(`${label} payment #${entryId}? Due will go back up.`)) return;
    ctx.showLoading?.();
    try {
      await ctx.api(`/accounts-receivable/payments/${entryId}/${mode}`, {
        method: "POST",
        body: JSON.stringify({ reason: String(reason).trim() }),
      });
      ctx.invalidateCache?.("/accounts-receivable");
      ctx.invalidateCache?.("/finance");
      ctx.toast(`${label}d`, "success");
      App.closeDetail?.();
      ctx.showView?.("money");
      await openCustomerAr(cid);
      loadArList();
      loadOverviewSilent();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function undoApPayment(entryId, mode, vendorId) {
    if (!ctx.isAdmin?.()) return;
    const vid = vendorId || currentVendor;
    if (!vid) return;
    const label = mode === "void" ? "Void" : "Reverse";
    const reason = prompt(`${label} this payment — reason (required):`);
    if (reason == null) return;
    if (!String(reason).trim()) return ctx.toast("Reason required", "error");
    if (!confirm(`${label} payment #${entryId}? Due will go back up.`)) return;
    ctx.showLoading?.();
    try {
      await ctx.api(`/accounts-payable/payments/${entryId}/${mode}`, {
        method: "POST",
        body: JSON.stringify({ reason: String(reason).trim() }),
      });
      ctx.invalidateCache?.("/accounts-payable");
      ctx.invalidateCache?.("/finance");
      ctx.toast(`${label}d`, "success");
      App.closeDetail?.();
      ctx.showView?.("money");
      await openVendorAp(vid);
      loadApList();
      loadOverviewSilent();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openArSettle() {
    if (!arDetail) return;
    const outstanding = Number(arDetail.outstanding) || 0;
    try {
      paymentModes = await ctx.api("/payment-modes?active_only=true", {}, 30000) || [];
    } catch (_) { paymentModes = []; }
    const modeOpts = paymentModes.length
      ? `<label class="label">Payment mode</label>
        <select class="input" id="ar-settle-mode" style="margin-bottom:12px;width:100%;">
          <option value="">— Select mode —</option>
          ${paymentModes.map(m => `<option value="${m.id}">${ctx.esc(m.name)}</option>`).join("")}
        </select>
        <p style="font-size:12px;color:var(--muted);margin:-4px 0 12px;">Add modes in Setup → Payment Modes.</p>`
      : `<p style="font-size:13px;color:var(--muted);margin:0 0 12px;">No payment modes yet — <button type="button" class="btn btn-ghost btn-sm" onclick="Finance.closeArSettle();App.showView('setup');App.showSetupTab('paymodes')">add in Setup</button></p>`;
    document.getElementById("ar-settle-body").innerHTML = `
      <div class="review-block" style="margin-bottom:16px;">
        ${ctx.reviewRow("Customer", arDetail.customer_label)}
        ${ctx.reviewRow("Due", fmtPrice(outstanding))}
      </div>
      ${modeOpts}
      <label class="label">Amount (₹)</label>
      <input type="number" step="0.01" class="input" id="ar-settle-amount" value="" placeholder="Enter amount" style="margin-bottom:12px;" />
      <label class="label">Payment reference (optional)</label>
      <input class="input" id="ar-settle-ref" style="margin-bottom:12px;" placeholder="UTR, cheque #…" />
      <label class="label">Comment (optional)</label>
      <input class="input" id="ar-settle-comment" />`;
    document.getElementById("ar-settle-modal").classList.remove("hidden");
    const title = document.querySelector("#ar-settle-modal h3");
    if (title) title.textContent = "Collect";
    const footerBtn = document.querySelector("#ar-settle-modal .btn-primary");
    if (footerBtn) footerBtn.textContent = "Collect";
  }

  function closeArSettle() { document.getElementById("ar-settle-modal")?.classList.add("hidden"); }

  async function submitArSettle() {
    if (!currentCustomer || !arDetail) return;
    const ref = (document.getElementById("ar-settle-ref")?.value || "").trim();
    const amount = parseFloat(document.getElementById("ar-settle-amount")?.value || "0");
    const comment = (document.getElementById("ar-settle-comment")?.value || "").trim() || null;
    const modeRaw = document.getElementById("ar-settle-mode")?.value || "";
    const payment_mode_id = modeRaw ? parseInt(modeRaw, 10) : null;
    if (paymentModes.length && !payment_mode_id) return ctx.toast("Select payment mode", "error");
    if (!amount || amount <= 0) return ctx.toast("Enter valid amount", "error");
    const party = arDetail.customer_label;
    const cid = currentCustomer;
    ctx.showLoading?.();
    try {
      const body = { amount, comment, payment_ref: ref || null };
      if (payment_mode_id) body.payment_mode_id = payment_mode_id;
      await ctx.api(`/accounts-receivable/customer/${currentCustomer}/settle`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      ctx.invalidateCache?.("/accounts-receivable");
      ctx.invalidateCache?.("/finance");
      closeArSettle();
      ctx.toast("Collected", "success");
      await openCustomerAr(cid);
      settleSuccess({
        title: "Collected",
        party,
        amount,
        balanceAfter: Number(arDetail?.outstanding) || 0,
        reopenFn: `Finance.openCustomerAr(${cid})`,
      });
      loadArList();
      loadOverviewSilent();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  /* —— Expenses —— */
  function renderExpenseFilters() {
    const el = document.getElementById("finance-expense-filters");
    if (!el) return;
    el.innerHTML = `
      <label class="fin-exp-field"><span>From</span>
        <input type="date" class="input" id="fin-exp-from" value="${ctx.esc(expenseFilters.from_date)}" onchange="Finance.onExpenseFilterChange()" /></label>
      <label class="fin-exp-field"><span>To</span>
        <input type="date" class="input" id="fin-exp-to" value="${ctx.esc(expenseFilters.to_date)}" onchange="Finance.onExpenseFilterChange()" /></label>
      <label class="fin-exp-field"><span>Category</span>
        <select class="input" id="fin-exp-cat" onchange="Finance.onExpenseFilterChange()">
          <option value="">All</option>
          ${["rent", "salary", "electricity", "transport", "misc", "other"].map(c =>
            `<option value="${c}" ${expenseFilters.category === c ? "selected" : ""}>${c}</option>`).join("")}
        </select>
      </label>
      <button type="button" class="btn btn-secondary btn-sm" onclick="Finance.clearExpenseFilters()">Clear</button>`;
  }

  function onExpenseFilterChange() {
    expenseFilters.from_date = document.getElementById("fin-exp-from")?.value || "";
    expenseFilters.to_date = document.getElementById("fin-exp-to")?.value || "";
    expenseFilters.category = document.getElementById("fin-exp-cat")?.value || "";
    loadExpenses();
  }

  function clearExpenseFilters() {
    expenseFilters = { from_date: "", to_date: "", category: "" };
    loadExpenses();
  }

  async function loadExpenses() {
    if (!ctx.api) return ctx.toast?.("Finance not ready — hard refresh", "error");
    renderExpenseFilters();
    ctx.showLoading?.();
    try {
      const params = new URLSearchParams();
      if (expenseFilters.from_date) params.set("from_date", expenseFilters.from_date);
      if (expenseFilters.to_date) params.set("to_date", expenseFilters.to_date);
      if (expenseFilters.category) params.set("category", expenseFilters.category);
      const q = params.toString();
      expenses = await ctx.api(`/expenses${q ? `?${q}` : ""}`, {}, 0);
      if (!Array.isArray(expenses)) expenses = [];
      renderExpenses();
    } catch (e) { ctx.toast?.(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderExpenses() {
    const el = document.getElementById("finance-expenses-list");
    if (!el) return;
    if (!expenses.length) {
      el.innerHTML = OrdersUI.emptyState({
        title: "No expenses",
        sub: "Add rent, salary, or misc cash outs.",
        ctaHtml: `<button class="btn btn-primary" onclick="Finance.openExpenseForm()">+ Add expense</button>`,
      });
      return;
    }
    el.innerHTML = `<table class="data"><thead><tr>
      <th>Date</th><th>Category</th><th>Description</th><th>Amount</th><th>Ref</th><th></th>
    </tr></thead><tbody>
      ${expenses.map(e => `<tr>
        <td>${e.expense_date}</td>
        <td>${ctx.esc(e.category)}</td>
        <td>${ctx.esc(e.description || "—")}</td>
        <td>${fmtPrice(e.amount)}</td>
        <td>${ctx.esc(e.reference || "—")}</td>
        <td>${e.freight_agent_id
          ? `<span class="fin-muted">Freight</span>`
          : `<button class="btn btn-ghost btn-sm" onclick="Finance.deleteExpense(${e.id})">Delete</button>`}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  async function deleteExpense(id) {
    if (!confirm("Delete this expense?")) return;
    ctx.showLoading?.();
    try {
      await ctx.api(`/expenses/${id}`, { method: "DELETE" });
      ctx.invalidateCache?.("/expenses");
      ctx.invalidateCache?.("/finance");
      ctx.toast("Expense deleted", "success");
      await loadExpenses();
      loadOverviewSilent();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function openExpenseForm() {
    const today = new Date().toISOString().slice(0, 10);
    document.getElementById("expense-body").innerHTML = `
      <label class="label">Date</label>
      <input type="date" class="input" id="exp-date" value="${today}" style="margin-bottom:12px;" />
      <label class="label">Category</label>
      <select class="input" id="exp-cat" style="margin-bottom:12px;width:100%;">
        <option value="rent">Rent</option><option value="salary">Salary</option>
        <option value="electricity">Electricity</option><option value="transport">Freight</option>
        <option value="misc">Misc</option><option value="other">Other</option>
      </select>
      <label class="label">Description</label>
      <input class="input" id="exp-desc" style="margin-bottom:12px;" />
      <label class="label">Amount (₹)</label>
      <input type="number" step="0.01" class="input" id="exp-amount" style="margin-bottom:12px;" />
      <label class="label">Reference</label>
      <input class="input" id="exp-ref" />`;
    document.getElementById("expense-modal").classList.remove("hidden");
  }

  function closeExpenseForm() { document.getElementById("expense-modal")?.classList.add("hidden"); }

  async function submitExpense() {
    const expense_date = document.getElementById("exp-date")?.value;
    const category = document.getElementById("exp-cat")?.value || "misc";
    const description = (document.getElementById("exp-desc")?.value || "").trim() || null;
    const amount = parseFloat(document.getElementById("exp-amount")?.value || "0");
    const reference = (document.getElementById("exp-ref")?.value || "").trim() || null;
    if (!expense_date || !amount || amount <= 0) return ctx.toast("Enter date and amount", "error");
    ctx.showLoading?.();
    try {
      await ctx.api("/expenses", {
        method: "POST",
        body: JSON.stringify({ expense_date, category, description, amount, reference }),
      });
      ctx.invalidateCache?.("/expenses");
      ctx.invalidateCache?.("/finance");
      closeExpenseForm();
      ctx.toast("Expense saved", "success");
      loadExpenses();
      loadOverviewSilent();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  /* —— Reports —— */
  function renderReportsPanel() {
    const tabs = document.getElementById("finance-report-tabs");
    const body = document.getElementById("finance-reports-body");
    if (!tabs || !body) return;
    const items = [
      { id: "revenue", label: "Cash in" },
      { id: "cost", label: "Cash out" },
      { id: "pnl", label: "Net cash" },
    ];
    tabs.innerHTML = items.map(t =>
      `<button type="button" class="fin-tab ${reportTab === t.id ? "is-active" : ""}" onclick="Finance.setReportTab('${t.id}')">${t.label}</button>`
    ).join("")
      + `<button type="button" class="btn btn-secondary btn-sm" style="margin-left:auto;" onclick="App.showView('reports')">Full Reports →</button>`;
    tabs.style.display = "flex";
    tabs.style.flexWrap = "wrap";
    tabs.style.alignItems = "center";
    tabs.style.gap = "8px";
    const note = `<p style="margin:0 0 12px;font-size:13px;color:var(--muted);">Cash snapshot only (collections / payments). Books P&amp;L, daybook, ageing → <button type="button" class="btn btn-ghost btn-sm" onclick="App.showView('reports')">More → Reports</button></p>`;
    if (reportTab === "revenue") body.innerHTML = note + renderRevenueHtml();
    else if (reportTab === "cost") body.innerHTML = note + renderCostHtml();
    else body.innerHTML = note + renderPnlHtml();
  }

  function setReportTab(tab) {
    reportTab = tab;
    renderReportsPanel();
  }

  function renderRevenueHtml() {
    if (!overview) return "";
    return `
      <div class="fin-summary-grid">
        <div class="fin-card"><div class="fin-card-title">Cash collected</div><div class="fin-card-value">${fmtPrice(overview.revenue)}</div>
          <div class="fin-card-sub">AR payments received</div></div>
        <div class="fin-card"><div class="fin-card-title">Billed to customers</div><div class="fin-card-value">${fmtPrice(overview.revenue_billed)}</div></div>
        <div class="fin-card"><div class="fin-card-title">Still to collect</div><div class="fin-card-value">${fmtPrice(overview.ar_outstanding)}</div></div>
      </div>
      <div class="fin-summary-grid" style="margin-top:16px;">
        <div class="fin-card fin-card-chart"><div class="fin-card-title">Monthly collections</div>
          ${barChart(overview.month_series, ["revenue"], ["#2563eb"])}
        </div>
        <div class="fin-card fin-card-chart"><div class="fin-card-title">Pending by customer</div>
          ${hBarList(overview.ar_customers || [], "customer_label", "outstanding")}
        </div>
      </div>`;
  }

  function renderCostHtml() {
    if (!overview) return "";
    return `
      <div class="fin-summary-grid">
        <div class="fin-card"><div class="fin-card-title">Total cash out</div><div class="fin-card-value">${fmtPrice(overview.cost)}</div>
          <div class="fin-card-sub">Expenses + vendor payments</div></div>
        <div class="fin-card"><div class="fin-card-title">Expenses</div><div class="fin-card-value">${fmtPrice(overview.expense_total)}</div></div>
        <div class="fin-card"><div class="fin-card-title">Paid to vendors</div><div class="fin-card-value">${fmtPrice(overview.ap_paid)}</div>
          <div class="fin-card-sub">Still to pay ${fmtPrice(overview.ap_outstanding)}</div></div>
      </div>
      <div class="fin-summary-grid" style="margin-top:16px;">
        <div class="fin-card fin-card-chart"><div class="fin-card-title">Cost mix</div>
          ${donutChart(overview.cost_mix, ["#d97706", "#0d9488"])}
        </div>
        <div class="fin-card fin-card-chart"><div class="fin-card-title">Monthly cash out</div>
          ${barChart(overview.month_series, ["expenses", "ap_paid"], ["#d97706", "#0d9488"])}
        </div>
      </div>
      ${(overview.expense_breakdown || []).length ? `<div class="fin-card" style="margin-top:16px;"><div class="fin-card-title">Expenses by category</div>
        ${hBarList(overview.expense_breakdown, "category", "amount")}</div>` : ""}`;
  }

  function renderPnlHtml() {
    if (!overview) return "";
    const netCash = Number(overview.cash_pulse?.net_cash ?? overview.net_cash ?? overview.profit) || 0;
    const books = overview.books_snapshot || {};
    return `
      <div class="fin-summary-grid">
        <div class="fin-card"><div class="fin-card-title">Cash in</div><div class="fin-card-value">${fmtPrice(overview.cash_pulse?.cash_in ?? overview.revenue)}</div>
          <div class="fin-card-sub">Collections only</div></div>
        <div class="fin-card"><div class="fin-card-title">Cash out</div><div class="fin-card-value">${fmtPrice(overview.cash_pulse?.cash_out ?? overview.cost)}</div>
          <div class="fin-card-sub">Expenses + vendor payments</div></div>
        <div class="fin-card"><div class="fin-card-title">Manual losses</div><div class="fin-card-value">${fmtPrice(overview.manual_loss_total)}</div></div>
        <div class="fin-card"><div class="fin-card-title">Net cash</div>
          <div class="fin-card-value ${netCash >= 0 ? "is-pos" : "is-neg"}">${fmtPrice(netCash)}</div>
          <div class="fin-card-sub">Cash pulse — not books P&amp;L</div></div>
      </div>
      <div class="fin-summary-grid" style="margin-top:16px;">
        <div class="fin-card">
          <div class="fin-card-title">Books position</div>
          <div class="fin-card-sub" style="margin-bottom:10px;">Signed ledgers · due</div>
          <div style="display:grid;gap:8px;font-size:13px;">
            <div style="display:flex;justify-content:space-between;"><span>Collect</span><strong>${fmtPrice(books.ar_outstanding ?? overview.ar_outstanding)}</strong></div>
            <div style="display:flex;justify-content:space-between;"><span>Pay</span><strong>${fmtPrice(books.ap_outstanding ?? overview.ap_outstanding)}</strong></div>
            <div style="display:flex;justify-content:space-between;"><span>Freight</span><strong>${fmtPrice(books.freight_outstanding ?? overview.freight_outstanding)}</strong></div>
            <div style="display:flex;justify-content:space-between;"><span>Opening</span><strong>${fmtPrice(books.ar_opening || 0)}</strong></div>
          </div>
        </div>
        <div class="fin-card fin-card-chart"><div class="fin-card-title">Monthly net cash</div>
          ${barChart(overview.month_series, ["revenue", "cost", "profit"], ["#2563eb", "#d97706", "#16a34a"])}
        </div>
        <div class="fin-card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
            <div class="fin-card-title" style="margin:0;">Manual losses</div>
            <button class="btn btn-primary btn-sm" onclick="Finance.openLossForm()">+ Add loss</button>
          </div>
          ${(overview.losses || []).length ? `<table class="data fin-mini"><thead><tr><th>Date</th><th>Note</th><th>Amount</th></tr></thead><tbody>
            ${overview.losses.map(l => `<tr>
              <td>${l.loss_date}</td><td>${ctx.esc(l.description || "—")}</td>
              <td>${fmtPrice(l.amount)} <button class="btn-ghost btn-sm" onclick="Finance.deleteLoss(${l.id})">✕</button></td>
            </tr>`).join("")}
          </tbody></table>` : `<p class="fin-muted">No manual losses yet.</p>`}
        </div>
      </div>`;
  }

  function renderRevenue() { reportTab = "revenue"; renderReportsPanel(); }
  function renderCost() { reportTab = "cost"; renderReportsPanel(); }
  function renderPnl() { reportTab = "pnl"; renderReportsPanel(); }

  function openLossForm() {
    const today = new Date().toISOString().slice(0, 10);
    document.getElementById("loss-body").innerHTML = `
      <label class="label">Date</label>
      <input type="date" class="input" id="loss-date" value="${today}" style="margin-bottom:12px;" />
      <label class="label">Amount (₹)</label>
      <input type="number" step="0.01" class="input" id="loss-amount" style="margin-bottom:12px;" />
      <label class="label">Description</label>
      <input class="input" id="loss-desc" placeholder="Write-off, damage, etc." />`;
    document.getElementById("loss-modal").classList.remove("hidden");
  }

  function closeLossForm() { document.getElementById("loss-modal")?.classList.add("hidden"); }

  async function submitLoss() {
    const loss_date = document.getElementById("loss-date")?.value;
    const amount = parseFloat(document.getElementById("loss-amount")?.value || "0");
    const description = (document.getElementById("loss-desc")?.value || "").trim() || null;
    if (!loss_date || !amount || amount <= 0) return ctx.toast("Enter date and amount", "error");
    ctx.showLoading?.();
    try {
      await ctx.api("/finance/losses", { method: "POST", body: JSON.stringify({ loss_date, amount, description }) });
      closeLossForm();
      ctx.toast("Loss recorded", "success");
      await loadOverview();
      renderReportsPanel();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function deleteLoss(id) {
    if (!confirm("Delete this loss entry?")) return;
    ctx.showLoading?.();
    try {
      await ctx.api(`/finance/losses/${id}`, { method: "DELETE" });
      await loadOverview();
      renderReportsPanel();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  /* —— Freight —— */
  async function loadFreightList() {
    freightAgentId = null;
    document.getElementById("finance-freight-detail")?.classList.add("hidden");
    document.getElementById("finance-panel-freight")?.classList.remove("hidden");
    ctx.showLoading?.();
    try {
      freightAgents = await ctx.api("/freight-agents", {}, 0);
      renderFreightList();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderFreightList() {
    const el = document.getElementById("finance-freight-list");
    if (!el) return;
    refreshChipCounts();
    renderHubChrome();
    let list = freightAgents.filter(a => matchSearch(a.name));
    if (!showSettled) list = list.filter(a => Number(a.balance_due) > 0);
    const dueAgents = freightAgents.filter(a => Number(a.balance_due) > 0);
    const totalDue = dueAgents.reduce((s, a) => s + Number(a.balance_due || 0), 0);
    const sum = document.getElementById("finance-freight-summary");
    if (sum) {
      sum.innerHTML = `
        <div class="home-card fin-list-sum">
          <div class="fin-list-sum-top">
            <div>
              <span class="fin-pulse-label">Freight due</span>
              <strong class="fin-list-sum-val">${fmtPriceShort(totalDue)}</strong>
              <span class="fin-list-sum-sub">${dueAgents.length} agent${dueAgents.length === 1 ? "" : "s"}</span>
            </div>
            <label class="fin-filter-chip ${showSettled ? "is-on" : ""}">
              <input type="checkbox" ${showSettled ? "checked" : ""} onchange="Finance.setShowSettled(this.checked)" />
              Show clear
            </label>
          </div>
        </div>`;
    }
    if (!freightAgents.length) {
      el.innerHTML = OrdersUI.emptyState({
        title: "No freight agents",
        sub: "Create agents in Setup. Pick ops under Customer orders → Dispatch; settle here.",
        ctaHtml: `<button class="btn btn-primary" onclick="App.showView('setup');App.showSetupTab('freight')">Open Setup → Freight agents</button>`,
      });
      return;
    }
    if (!list.length) {
      el.innerHTML = OrdersUI.emptyState({ title: "No matches", sub: "Clear search or show clear." });
      return;
    }
    el.innerHTML = `<div class="ord-card-list">${list.map(a => {
      const due = Number(a.balance_due) || 0;
      const adv = Number(a.advance_left) || 0;
      const label = adv > 0 && due <= 0 ? `${a.name} · Adv ${fmtPriceShort(adv)}` : a.name;
      // Settled agents: Advance is next money step (not a dead OK card)
      if (due <= 0) {
        return HubUI.partyCard({
          title: label,
          meta: adv > 0 ? `${fmtPriceShort(adv)} advance left` : "Clear",
          pillHtml: HubUI.pill(adv > 0 ? "Advance" : "OK", "muted"),
          primaryLabel: "Advance",
          primaryOnclick: `Finance.openFreightAgent(${a.id},{advance:true})`,
          moreItems: [{ label: "Open", onclick: `Finance.openFreightAgent(${a.id})` }],
          rowOnclick: `Finance.openFreightAgent(${a.id})`,
          canWrite: true,
        });
      }
      return dueRow({
        name: label,
        amount: due,
        openFn: `Finance.openFreightAgent(${a.id})`,
        settleFn: `Finance.openFreightAgent(${a.id},{settle:true})`,
        cta: "Settle",
        settled: false,
      });
    }).join("")}</div>`;
  }

  async function openFreightAgent(id, opts = {}) {
    freightAgentId = id;
    const agent = freightAgents.find(a => a.id === id) || { id, name: "Freight agent", balance_due: 0 };
    ctx.showLoading?.();
    try {
      const [ledger, agents] = await Promise.all([
        ctx.api(`/freight-agents/${id}/ledger`, {}, 0),
        ctx.api("/freight-agents", {}, 0),
      ]);
      freightLedger = Array.isArray(ledger) ? ledger : [];
      freightAgents = Array.isArray(agents) ? agents : [];
      const a = freightAgents.find(x => x.id === id) || agent;
      document.getElementById("finance-panel-freight")?.classList.add("hidden");
      document.getElementById("finance-hub")?.classList.add("hidden");
      document.getElementById("finance-freight-detail")?.classList.remove("hidden");
      renderFreightDetail(a);
      if (opts?.settle) openFreightSettle();
      else if (opts?.advance) openFreightAdvance();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderFreightDetail(agent) {
    const hero = document.getElementById("finance-freight-hero");
    const el = document.getElementById("finance-freight-body");
    if (!el) return;
    const due = Number(agent?.balance_due || 0);
    const adv = Number(agent?.advance_left || 0);
    const bits = [];
    if (due > 0) bits.push(`${fmtPrice(due)} due`);
    if (adv > 0) bits.push(`${fmtPrice(adv)} advance left`);
    if (!bits.length) bits.push("No dues yet");
    const actions = [];
    if (due > 0) actions.push(`<button class="btn btn-primary" onclick="Finance.openFreightSettle()">Settle</button>`);
    actions.push(`<button class="btn btn-secondary" onclick="Finance.openFreightAdvance()">Pay advance</button>`);
    actions.push(`<button class="btn btn-secondary" onclick="Finance.shareFreightStatement()">Print / PDF</button>`);
    if (hero) {
      hero.innerHTML = HubUI.pageHero({
        title: agent?.name || "Freight agent",
        sub: `Freight pay · ${bits.join(" · ")}`,
        actionsHtml: actions.join(""),
      });
    }
    if (!freightLedger.length) {
      el.innerHTML = HubUI.emptyState({
        title: "No ledger entries yet",
        sub: "Mark parcels picked under Customer orders → Dispatch. Settle / advance payments here.",
        ctaHtml: `<button class="btn btn-secondary" onclick="App.showView('selling');CustomerOrders.goToDispatch()">Open Dispatch</button>`,
      });
      return;
    }
    el.innerHTML = `
      <div class="card table-wrap">
        <table class="data"><thead><tr>
          <th>Date</th><th>Type</th><th>Party</th><th>Amount</th><th>Ref</th><th></th>
        </tr></thead><tbody>
          ${freightLedger.map(r => {
            const isCharge = r.entry_type === "charge";
            const party = isCharge
              ? (r.party_label || r.notes || "—")
              : (r.transaction_ref || "—");
            const badge = r.entry_type === "charge" ? "badge-amber"
              : r.entry_type === "advance" ? "badge-blue" : "badge-green";
            const links = [];
            if (r.has_document) links.push(`<button type="button" class="btn btn-secondary btn-sm" onclick="Finance.printFreightPayment(${r.id})">Print</button>`);
            if (r.payment_receipt_url) links.push(`<a href="${ctx.esc(r.payment_receipt_url)}" target="_blank" class="btn btn-secondary btn-sm">Receipt</a>`);
            return `<tr>
              <td>${ctx.fmtDate?.(r.created_at) || r.created_at?.slice(0, 10) || "—"}</td>
              <td><span class="badge ${badge}">${ctx.esc(r.entry_type)}</span></td>
              <td><strong>${ctx.esc(party)}</strong>${r.bill_number && isCharge ? `<div style="font-size:11px;color:var(--muted);">${ctx.esc(r.bill_number)}</div>` : ""}</td>
              <td>${fmtPrice(r.amount)}</td>
              <td style="font-size:12px;color:var(--muted);">${ctx.esc(isCharge ? (r.transaction_ref || "—") : (r.notes || "—"))}</td>
              <td style="white-space:nowrap;">${links.join(" ")}</td>
            </tr>`;
          }).join("")}
        </tbody></table>
      </div>`;
  }

  function openFreightSettle() {
    freightPayMode = "settle";
    freightSettleFile = null;
    const agent = freightAgents.find(a => a.id === freightAgentId);
    if (!agent) return;
    const due = Number(agent.balance_due || 0);
    if (!(due > 0)) return ctx.toast("Nothing due — use Pay advance", "error");
    const title = document.querySelector("#freight-settle-modal .modal-header h3");
    if (title) title.textContent = "Settle freight";
    const footerBtn = document.querySelector("#freight-settle-modal .modal-footer .btn-primary");
    if (footerBtn) footerBtn.textContent = "Settle";
    document.getElementById("freight-settle-body").innerHTML = `
      <p style="margin:0 0 12px;color:var(--muted);">Pay ${ctx.esc(agent.name)} against due ${fmtPrice(due)}. Party names print on the voucher.</p>
      <label class="label">Transaction ID *</label>
      <input class="input" id="freight-settle-ref" style="margin-bottom:12px;" placeholder="UTR, cheque #, etc." />
      <label class="label">Amount (₹) *</label>
      <input type="number" step="0.01" class="input" id="freight-settle-amount" value="" placeholder="Enter amount" style="margin-bottom:12px;" />
      <label class="label">Notes</label>
      <input class="input" id="freight-settle-notes" style="margin-bottom:12px;" />
      <label class="label">Upload receipt (optional)</label>
      <input type="file" class="input" accept=".pdf,image/*" onchange="Finance.setFreightSettleFile(this.files[0])" />`;
    document.getElementById("freight-settle-modal")?.classList.remove("hidden");
  }

  function openFreightAdvance() {
    freightPayMode = "advance";
    freightSettleFile = null;
    const agent = freightAgents.find(a => a.id === freightAgentId);
    if (!agent) return;
    const adv = Number(agent.advance_left || 0);
    const title = document.querySelector("#freight-settle-modal .modal-header h3");
    if (title) title.textContent = "Pay advance";
    const footerBtn = document.querySelector("#freight-settle-modal .modal-footer .btn-primary");
    if (footerBtn) footerBtn.textContent = "Pay advance";
    document.getElementById("freight-settle-body").innerHTML = `
      <p style="margin:0 0 12px;color:var(--muted);">Prepaid to ${ctx.esc(agent.name)}. Future freight charges adjust against this${adv > 0 ? ` (now ${fmtPrice(adv)} left)` : ""}.</p>
      <label class="label">Transaction ID *</label>
      <input class="input" id="freight-settle-ref" style="margin-bottom:12px;" placeholder="UTR, cheque #, etc." />
      <label class="label">Advance amount (₹) *</label>
      <input type="number" step="0.01" class="input" id="freight-settle-amount" value="" placeholder="e.g. 5000" style="margin-bottom:12px;" />
      <label class="label">Notes</label>
      <input class="input" id="freight-settle-notes" style="margin-bottom:12px;" />
      <label class="label">Upload receipt (optional)</label>
      <input type="file" class="input" accept=".pdf,image/*" onchange="Finance.setFreightSettleFile(this.files[0])" />`;
    document.getElementById("freight-settle-modal")?.classList.remove("hidden");
  }

  function setFreightSettleFile(file) {
    freightSettleFile = file || null;
  }

  function closeFreightSettle() {
    document.getElementById("freight-settle-modal")?.classList.add("hidden");
    freightSettleFile = null;
  }

  function shareFreightStatement() {
    if (!freightAgentId) return;
    const agent = freightAgents.find(a => a.id === freightAgentId);
    DocShare.shareFlow({
      kind: "freight_statement",
      id: freightAgentId,
      filename: `freight_${freightAgentId}.pdf`,
      caption: `Freight — ${agent?.name || ""}`,
    });
  }

  function printFreightPayment(entryId) {
    DocShare.shareFlow({
      kind: "freight_payment",
      id: entryId,
      filename: `freight_pay_${entryId}.pdf`,
      caption: "Freight payment",
    });
  }

  async function submitFreightSettle() {
    if (!freightAgentId) return;
    const ref = (document.getElementById("freight-settle-ref")?.value || "").trim();
    const amount = parseFloat(document.getElementById("freight-settle-amount")?.value || "0");
    const notes = (document.getElementById("freight-settle-notes")?.value || "").trim() || null;
    if (!ref) return ctx.toast("Transaction ID required", "error");
    if (!(amount > 0)) return ctx.toast("Enter amount", "error");
    const agent = freightAgents.find(a => a.id === freightAgentId);
    const party = agent?.name || "Freight";
    const fid = freightAgentId;
    const asAdvance = freightPayMode === "advance";
    const path = asAdvance ? "advance" : "settle";
    ctx.showLoading?.();
    try {
      let key = null;
      if (freightSettleFile) {
        const API = (ctx.apiBase?.() || "").replace(/\/$/, "");
        const h = { ...(ctx.headers?.() || {}) };
        delete h["Content-Type"];
        const fd = new FormData();
        fd.append("agent_id", String(fid));
        fd.append("payment_ref", ref);
        fd.append("file", freightSettleFile);
        const res = await fetch(`${API}/freight-agents/upload-payment-receipt`, { method: "POST", headers: h, body: fd });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || "Receipt upload failed");
        }
        const up = await res.json();
        key = up.key;
      }
      const result = await ctx.api(`/freight-agents/${fid}/${path}`, {
        method: "POST",
        body: JSON.stringify({ amount, transaction_ref: ref, notes, payment_receipt_key: key }),
      });
      ctx.toast(asAdvance ? "Advance paid" : "Settled", "success");
      closeFreightSettle();
      ctx.invalidateCache?.("/freight-agents");
      freightAgents = await ctx.api("/freight-agents", {}, 0);
      await openFreightAgent(fid);
      const bal = Number(freightAgents.find(a => a.id === fid)?.balance_due || 0);
      const entryId = result?.entry_id;
      settleSuccess({
        title: asAdvance ? "Advance paid" : "Settled",
        party,
        amount,
        balanceAfter: bal,
        reopenFn: `Finance.openFreightAgent(${fid})`,
      });
      if (entryId) {
        setTimeout(() => {
          DocShare.shareFlow({
            kind: "freight_payment",
            id: entryId,
            filename: `freight_pay_${entryId}.pdf`,
            caption: `${asAdvance ? "Advance" : "Freight pay"} — ${party}`,
          });
        }, 200);
      }
      loadOverviewSilent();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  /* —— Routes —— */
  async function loadRouteCollections() {
    const el = document.getElementById("finance-routes-list");
    if (!el) return;
    ctx.showLoading?.();
    try {
      routeCollections = await ctx.api("/finance/route-collections", {}, 0);
      renderRouteListFiltered();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderRouteListFiltered() {
    const el = document.getElementById("finance-routes-list");
    if (!el) return;
    const list = (routeCollections || []).filter(r => matchSearch(r.route_name));
    if (!routeCollections.length) {
      el.innerHTML = OrdersUI.emptyState({
        title: "No routes yet",
        sub: "Add routes under Setup.",
        ctaHtml: `<button class="btn btn-secondary" onclick="App.showView('setup');App.showSetupTab('routes')">Open Setup → Routes</button>`,
      });
      return;
    }
    if (!list.length) {
      el.innerHTML = OrdersUI.emptyState({ title: "No matches", sub: "Clear search." });
      return;
    }
    el.innerHTML = list.map(r => `
      <div class="rc-card" onclick="Finance.openRouteCollection(${r.route_id})">
        <div>
          <strong>${ctx.esc(r.route_name)}</strong>
          <div class="rc-meta">${r.city_count} cities · ${r.customer_count} customers · ${r.customers_with_outstanding} with dues</div>
        </div>
        <div class="rc-amt">${fmtPrice(r.total_outstanding)}</div>
      </div>`).join("");
  }

  async function openRouteCollection(routeId) {
    ctx.showLoading?.();
    try {
      routeDetail = await ctx.api(`/finance/route-collections/${routeId}`, {}, 0);
      routeCustomerDetail = null;
      document.getElementById("finance-hub")?.classList.add("hidden");
      document.getElementById("finance-routes-detail")?.classList.remove("hidden");
      const routesHero = document.getElementById("finance-routes-hero");
      if (routesHero) {
        routesHero.innerHTML = HubUI.pageHero({
          title: routeDetail.route_name,
          sub: `Total outstanding ${fmtPrice(routeDetail.total_outstanding)} · ${(routeDetail.cities || []).map(c => c.name).join(", ") || "No cities"}`,
          actionsHtml: `<button class="btn btn-secondary" onclick="Finance.printRouteCollection()">Print / PDF</button>`,
        });
      }
      renderRouteDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderRouteDetail() {
    const el = document.getElementById("finance-routes-body");
    if (!el || !routeDetail) return;
    if (routeCustomerDetail) {
      const c = routeCustomerDetail;
      const due = Number(c.outstanding) || 0;
      el.innerHTML = `
        <button class="btn btn-secondary btn-sm" style="margin-bottom:14px;" onclick="Finance.backRouteCustomers()">← Customers</button>
        ${HubUI.pageHero({
          title: c.business_name,
          sub: `${c.person_name || ""}${c.person_name ? " · " : ""}${c.city_name || "—"} · ${c.phone || ""} · Due ${fmtPrice(c.outstanding)}`,
          actionsHtml: due > 0 ? `<button class="btn btn-primary" onclick="Finance.openCustomerAr(${c.customer_id}, {settle:true})">Collect</button>` : "",
        })}
        <div class="review-grid" style="margin-bottom:12px;">
          ${ctx.reviewRow("Due", fmtPrice(c.outstanding))}
          ${ctx.reviewRow("Bills", fmtPrice(c.bill_total))}
          ${ctx.reviewRow("Collected", fmtPrice(c.payment_total))}
        </div>
        ${!(c.ledger || []).length
          ? HubUI.emptyState({ title: "No ledger entries", sub: "Bills and payments for this customer show here." })
          : `<div class="card table-wrap">
          <table class="data"><thead><tr>
            <th>When</th><th>Type</th><th>Detail</th><th>Amount</th><th>Balance</th>
          </tr></thead><tbody>
            ${(c.ledger || []).map(e => `<tr>
              <td style="font-size:12px;">${e.created_at ? new Date(e.created_at).toLocaleString() : "—"}</td>
              <td><span class="badge ${e.entry_type === "bill" ? "badge-amber" : "badge-green"}">${ctx.esc(e.entry_type)}</span></td>
              <td>${ctx.esc(e.description || "—")}</td>
              <td>${fmtPrice(e.signed_amount || e.amount)}</td>
              <td><strong>${fmtPrice(e.running_balance)}</strong></td>
            </tr>`).join("")}
          </tbody></table>
        </div>`}`;
      return;
    }

    const rows = routeDetail.customers || [];
    el.innerHTML = rows.length ? rows.map(c => `
      <div class="rc-card" onclick="Finance.openRouteCustomer(${routeDetail.route_id}, ${c.customer_id})">
        <div>
          <strong>${ctx.esc(c.business_name)}</strong>
          <div class="rc-meta">${ctx.esc(c.city_name || "—")} · ${ctx.esc(c.phone || "")}${c.person_name ? ` · ${ctx.esc(c.person_name)}` : ""}</div>
        </div>
        <div class="rc-amt">${fmtPrice(c.outstanding)}</div>
      </div>`).join("") : OrdersUI.emptyState({ title: "No outstanding on this route", sub: "" });
  }

  function backRouteCustomers() {
    routeCustomerDetail = null;
    renderRouteDetail();
  }

  async function openRouteCustomer(routeId, customerId) {
    ctx.showLoading?.();
    try {
      routeCustomerDetail = await ctx.api(`/finance/route-collections/${routeId}/customer/${customerId}`, {}, 0);
      renderRouteDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function printRouteCollection() {
    if (!routeDetail?.route_id) return;
    ctx.showLoading?.();
    try {
      const key = sessionStorage.getItem("jc_admin_key") || "";
      const saved = localStorage.getItem("jc_api");
      const base = saved || `${location.origin}/api/v1`;
      const res = await fetch(`${base}/finance/route-collections/${routeDetail.route_id}/pdf`, {
        headers: { "X-Admin-Key": key },
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "PDF failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      ctx.toast("PDF ready — print or share", "success");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  return {
    init, showHub, setHubMode, setChip, setHubSearch, setBrowseSection, setShowSettled, setReportTab,
    showAp, showAr, showExpenses, showRevenue, showCost, showPnl, showFreight,
    showRouteCollections, openRouteCollection, openRouteCustomer, backRouteCustomers, printRouteCollection,
    showApFromVendor, showArFromCustomer, openVendorAp, openEntry, openSettle, closeSettle, submitSettle, setSettleFile,
    setApTab, toggleBill, addDebitNote,
    openCustomerAr, setArTab, openArSettle, closeArSettle, submitArSettle,
    undoArPayment, undoApPayment,
    shareArStatement, shareApStatement,
    setArOpeningBalance, setApOpeningBalance, saveArOpeningBalance, saveApOpeningBalance,
    openExpenseForm, closeExpenseForm, submitExpense, deleteExpense, onExpenseFilterChange, clearExpenseFilters,
    openLossForm, closeLossForm, submitLoss, deleteLoss,
    openFreightAgent, openFreightSettle, openFreightAdvance, closeFreightSettle, submitFreightSettle,
    setFreightSettleFile, shareFreightStatement, printFreightPayment,
  };
})();
