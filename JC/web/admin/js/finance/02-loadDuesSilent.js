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
    needsActionLoadFailed = false;
    try {
      const [ap, ar, fr] = await Promise.all([
        ctx.api("/accounts-payable", {}, 0).catch(() => { needsActionLoadFailed = true; return []; }),
        ctx.api("/accounts-receivable", {}, 0).catch(() => { needsActionLoadFailed = true; return []; }),
        ctx.api("/freight-agents", {}, 0).catch(() => { needsActionLoadFailed = true; return []; }),
        loadDuesSilent(),
      ]);
      vendors = Array.isArray(ap) ? ap : [];
      customers = Array.isArray(ar) ? ar : [];
      freightAgents = Array.isArray(fr) ? fr : [];
      if (needsActionLoadFailed) {
        ctx.toast?.("Some dues failed to load — the list below may be incomplete", "error");
      }
      refreshChipCounts();
      renderHubChrome();
      renderHubStrip();
      renderNeedsAction();
    } catch (e) { ctx.toast?.(e.message || "Failed to load", "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function dueRow({ name, amount, openFn, settleFn, cta, settled = false }) {
    const n = Number(amount) || 0;
    if (n < 0) {
      return HubUI.partyCard({
        title: name,
        meta: `<strong>Credit ${fmtPrice(Math.abs(n))}</strong>`,
        pillHtml: HubUI.pill("Credit", "ok"),
        primaryLabel: cta || "Collect",
        primaryOnclick: settleFn,
        moreItems: [{ label: "Open", onclick: openFn }],
        rowOnclick: openFn,
        canWrite: true,
      });
    }
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

    if (!total && needsActionLoadFailed && !hubSearch.trim()) {
      // Don't claim "All clear" when zero is really "some fetches failed" —
      // that reads as a false all-clear and can mask real outstanding dues.
      el.innerHTML = HubUI.emptyState({
        title: "Couldn't load dues",
        sub: "One or more of AP / AR / freight failed to load — this is not a confirmed all-clear.",
        ctaHtml: `<div class="home-clear-actions">
          <button type="button" class="btn btn-secondary btn-sm" onclick="Finance.loadNeedsAction()">Retry</button>
        </div>`,
      });
      return;
    }
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

  function entryDay(row) {
    const raw = row?.display_date || row?.value_date || row?.created_at || "";
    const m = String(raw).match(/(\d{4}-\d{2}-\d{2})/);
    return m ? m[1] : "";
  }

  function newestFirst(rows) {
    return [...(rows || [])].sort((a, b) => {
      const da = entryDay(a);
      const db = entryDay(b);
      if (da !== db) return da < db ? 1 : -1;
      const ia = Number(a.id || a.receipt_id) || 0;
      const ib = Number(b.id || b.receipt_id) || 0;
      return ib - ia;
    });
  }

  function showPaymentDone({ title, party, amount, valueDate, receipt, comment, mode, againFn }) {
    ctx.openDetail?.(title, `
      <div class="review-block">
        ${ctx.reviewRow("Party", party)}
        ${ctx.reviewRow("Amount", fmtPrice(amount))}
        ${valueDate ? ctx.reviewRow("Date", fmtDocDate(valueDate)) : ""}
        ${ctx.reviewRow("Receipt no.", receipt || "—")}
        ${ctx.reviewRow("Comment", comment || "—")}
        ${ctx.reviewRow("Cash / Bank", mode || "—")}
      </div>`,
      `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail();${againFn}">Create another payment</button>
       <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail()">Done</button>`,
      "sm");
  }

  function settleSuccess({ title, party, amount, balanceAfter, valueDate, reopenFn, receipt, comment, mode }) {
    ctx.openDetail?.(title, `
      <div class="doc-success-banner">
        <strong>Payment settled</strong>
        <span>${ctx.esc(party)} · ${fmtPrice(amount)}</span>
      </div>
      <div class="review-block">
        ${ctx.reviewRow("Party", party)}
        ${ctx.reviewRow("Amount", fmtPrice(amount))}
        ${valueDate ? ctx.reviewRow("Date", fmtDocDate(valueDate)) : ""}
        ${ctx.reviewRow("Receipt no.", receipt || "—")}
        ${ctx.reviewRow("Comment", comment || "—")}
        ${ctx.reviewRow("Cash / Bank", mode || "—")}
        ${ctx.reviewRow(Number(balanceAfter) < 0 ? "Credit after" : "Balance after", Number(balanceAfter) < 0 ? fmtPrice(Math.abs(balanceAfter)) : fmtPrice(balanceAfter))}
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
    if (!showSettled && !hubSearch.trim()) list = list.filter(v => Number(v.outstanding) > 0);
    const dueVendors = vendors.filter(v => Number(v.outstanding) > 0);
    const barVendors = hubSearch.trim() ? list.filter(v => Number(v.outstanding) > 0) : dueVendors;
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
          ${barVendors.length ? hBarList(barVendors.slice(0, 5), "vendor_label", "outstanding") : ""}
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
    if (!ctx.isAdmin?.() && !ctx.can?.("ap.read")) return ctx.toast?.("Not permitted", "error");
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
            ${outstanding > 0 && (ctx.isAdmin?.() || ctx.can?.("ap.write")) ? `<button class="btn btn-primary" onclick="Finance.openSettle()">Pay</button>` : ""}
            <button class="btn btn-secondary" onclick="Finance.shareApStatement()">Print / PDF / WA</button>
            ${ctx.isAdmin?.() ? `<button class="btn btn-secondary" onclick="Finance.setApOpeningBalance()">Set opening</button>` : ""}
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
      ${realEntriesBar()}
      ${content}`;
  }

