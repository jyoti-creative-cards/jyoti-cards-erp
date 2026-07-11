/** Finance — AP, AR, Expenses, Revenue, Cost, PnL */
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
  let financeView = "hub";
  let apTab = "statement";
  let arTab = "ledger";
  let expandedBillId = null;
  let freightAgents = [];
  let freightAgentId = null;
  let freightLedger = [];
  let routeCollections = [];
  let routeDetail = null;
  let routeCustomerDetail = null;

  function init(context) { ctx = context; }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function setHubFocus(active) {
    const tiles = document.getElementById("finance-tiles");
    if (!tiles) return;
    const inSection = !!active && active !== "hub";
    tiles.classList.toggle("finance-tiles-compact", inSection);
    tiles.classList.toggle("finance-tiles-dim", inSection);
    tiles.querySelectorAll(".big-tile").forEach(btn => {
      const key = btn.getAttribute("data-finance");
      btn.classList.toggle("is-active", key === active);
      btn.classList.toggle("is-dim", inSection && key !== active);
    });
  }

  function hideAllPanels() {
    ["ap", "ar", "expenses", "revenue", "cost", "pnl", "freight", "routes"].forEach(k => {
      document.getElementById(`finance-panel-${k}`)?.classList.add("hidden");
    });
    document.getElementById("finance-freight-detail")?.classList.add("hidden");
    document.getElementById("finance-routes-detail")?.classList.add("hidden");
    document.getElementById("finance-pick")?.classList.add("hidden");
  }

  function showHub() {
    if (!ctx.isAdmin?.()) {
      ctx.toast?.("Finance is admin only", "error");
      ctx.showView?.("products");
      return;
    }
    financeView = "hub";
    document.getElementById("finance-hub")?.classList.remove("hidden");
    document.getElementById("finance-ap-detail")?.classList.add("hidden");
    document.getElementById("finance-ar-detail")?.classList.add("hidden");
    document.getElementById("finance-freight-detail")?.classList.add("hidden");
    document.getElementById("finance-routes-detail")?.classList.add("hidden");
    hideAllPanels();
    document.getElementById("finance-pick")?.classList.remove("hidden");
    setHubFocus("hub");
    currentVendor = null;
    currentCustomer = null;
    apDetail = null;
    arDetail = null;
    freightAgentId = null;
    routeDetail = null;
    routeCustomerDetail = null;
    loadOverviewSilent();
  }

  function showPanel(name, loader) {
    financeView = name;
    document.getElementById("finance-ap-detail")?.classList.add("hidden");
    document.getElementById("finance-ar-detail")?.classList.add("hidden");
    document.getElementById("finance-freight-detail")?.classList.add("hidden");
    document.getElementById("finance-routes-detail")?.classList.add("hidden");
    document.getElementById("finance-hub")?.classList.remove("hidden");
    hideAllPanels();
    const panel = document.getElementById(`finance-panel-${name}`);
    panel?.classList.remove("hidden");
    setHubFocus(name);
    loader?.();
    requestAnimationFrame(() => {
      panel?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function showAp() { showPanel("ap", loadApList); }
  function showAr() { showPanel("ar", loadArList); }
  function showExpenses() { showPanel("expenses", loadExpenses); }
  function showRevenue() { showPanel("revenue", () => loadOverview().then(renderRevenue)); }
  function showCost() { showPanel("cost", () => loadOverview().then(renderCost)); }
  function showPnl() { showPanel("pnl", () => loadOverview().then(renderPnl)); }
  function showFreight() { showPanel("freight", loadFreightList); }
  function showRouteCollections() { showPanel("routes", loadRouteCollections); }

  async function loadOverviewSilent() {
    try {
      overview = await ctx.api("/finance/overview", {}, 0);
      renderHubStrip();
    } catch (_) { /* ignore */ }
  }

  async function loadOverview() {
    ctx.showLoading?.();
    try {
      overview = await ctx.api("/finance/overview", {}, 0);
      renderHubStrip();
      return overview;
    } catch (e) { ctx.toast(e.message, "error"); return null; }
    finally { ctx.hideLoading?.(); }
  }

  function renderHubStrip() {
    const el = document.getElementById("finance-hub-strip");
    if (!el || !overview) return;
    el.innerHTML = `
      <div class="fin-stat"><span class="fin-stat-label">Revenue</span><strong>${fmtPrice(overview.revenue)}</strong></div>
      <div class="fin-stat"><span class="fin-stat-label">Cost</span><strong>${fmtPrice(overview.cost)}</strong></div>
      <div class="fin-stat"><span class="fin-stat-label">Profit</span><strong class="${Number(overview.profit) >= 0 ? "is-pos" : "is-neg"}">${fmtPrice(overview.profit)}</strong></div>
      <div class="fin-stat"><span class="fin-stat-label">AP due</span><strong>${fmtPrice(overview.ap_outstanding)}</strong></div>
      <div class="fin-stat"><span class="fin-stat-label">AR due</span><strong>${fmtPrice(overview.ar_outstanding)}</strong></div>
      <div class="fin-stat"><span class="fin-stat-label">Freight due</span><strong>${fmtPrice(overview.freight_outstanding || 0)}</strong></div>`;
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
        bars += `<rect x="${x}" y="${y}" width="${barW}" height="${bh}" fill="${colors[ki]}" rx="2">
          <title>${s.month} ${k}: ${fmtPrice(s[k])}</title></rect>`;
      });
      bars += `<text x="${pad + i * groupW + groupW / 2}" y="${h - 8}" text-anchor="middle" class="fin-chart-label">${ctx.esc((s.month || "").slice(5))}</text>`;
    });
    const legend = keys.map((k, i) => `<span class="fin-legend"><i style="background:${colors[i]}"></i>${ctx.esc(k)}</span>`).join("");
    return `<div class="fin-chart">${legend}<svg viewBox="0 0 ${w} ${h}" class="fin-svg">${bars}</svg></div>`;
  }

  function donutChart(parts, colors) {
    const items = (parts || []).map((p, i) => ({
      label: p.label || p.category,
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
    if (!rows?.length) return `<div class="fin-empty-chart">Nothing outstanding</div>`;
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

  /* —— AP —— */
  async function loadApList() {
    if (!ctx.api) {
      ctx.toast?.("Finance not ready — hard refresh the page", "error");
      return;
    }
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
    const totalOut = vendors.reduce((s, v) => s + (Number(v.outstanding) || 0), 0);
    if (sum) {
      sum.innerHTML = `
        <div class="fin-summary-grid">
          <div class="fin-card">
            <div class="fin-card-title">Total outstanding</div>
            <div class="fin-card-value">${fmtPrice(totalOut)}</div>
            <div class="fin-card-sub">${vendors.length} vendor${vendors.length === 1 ? "" : "s"}</div>
          </div>
          <div class="fin-card fin-card-chart">
            <div class="fin-card-title">Who we owe</div>
            ${hBarList(vendors.slice(0, 6), "vendor_label", "outstanding")}
          </div>
        </div>`;
    }
    if (!vendors.length) {
      el.innerHTML = `<div class="empty-state"><p>No accounts payable yet. Receive stock from vendors to create bills.</p></div>`;
      return;
    }
    el.innerHTML = `<table class="data"><thead><tr>
      <th>Vendor</th><th>Outstanding</th><th>Bills</th><th>Debit Notes</th><th>Paid</th><th>Txns</th>
    </tr></thead><tbody>
      ${vendors.map(v => `<tr class="clickable" onclick="Finance.openVendorAp(${v.vendor_id})">
        <td><strong>${ctx.esc(v.vendor_label)}</strong></td>
        <td><strong>${fmtPrice(v.outstanding)}</strong></td>
        <td>${fmtPrice(v.bill_total)}</td>
        <td>${fmtPrice(v.debit_note_total)}</td>
        <td>${fmtPrice(v.payment_total)}</td>
        <td>${v.transaction_count}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  async function openVendorAp(vendorId) {
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
    const title = document.getElementById("finance-ap-title");
    const body = document.getElementById("finance-ap-body");
    if (!apDetail || !body) return;
    if (title) title.textContent = apDetail.vendor_label;
    const outstanding = Number(apDetail.outstanding) || 0;
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
        ${ctx.reviewRow("Outstanding", fmtPrice(apDetail.outstanding))}
        ${ctx.reviewRow("Total bills", fmtPrice(apDetail.bill_total))}
        ${ctx.reviewRow("Debit note adjustments", fmtPrice(apDetail.debit_note_total))}
        ${ctx.reviewRow("Payments made", fmtPrice(apDetail.payment_total))}
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
        ${tabs}
        ${outstanding > 0 ? `<button class="btn btn-primary" onclick="Finance.openSettle()">Settle Payment</button>` : ""}
      </div>
      ${content}`;
  }

  function renderApStatement() {
    const bills = apDetail.bills || [];
    if (!bills.length) return `<div class="empty-state"><p>No bills yet.</p></div>`;
    return `<div class="fin-stmt">${bills.map(b => {
      const open = expandedBillId === b.receipt_id;
      const dns = b.debit_notes || [];
      return `<div class="fin-bill-card ${open ? "is-open" : ""}">
        <button type="button" class="fin-bill-head" onclick="Finance.toggleBill(${b.receipt_id})">
          <div>
            <div class="fin-bill-title">Bill ${ctx.esc(b.bill_number || `#${b.receipt_id}`)}</div>
            <div class="fin-bill-meta">${b.created_at ? new Date(b.created_at).toLocaleString() : ""} · ${dns.length} debit note${dns.length === 1 ? "" : "s"}</div>
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
          ${dns.length ? `<div class="fin-dn-block"><div class="fin-dn-title">Debit notes</div>
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
        </div>` : ""}
      </div>`;
    }).join("")}</div>`;
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
    if (!pays.length) return `<div class="empty-state"><p>No payments recorded yet.</p></div>`;
    return `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>When</th><th>Reference</th><th>Comment</th><th>Amount</th><th>Balance after</th><th></th>
    </tr></thead><tbody>
      ${pays.map(p => `<tr>
        <td style="font-size:12px;">${new Date(p.created_at).toLocaleString()}</td>
        <td><strong>${ctx.esc(p.payment_ref || "—")}</strong></td>
        <td>${ctx.esc(p.payment_comment || "—")}</td>
        <td>${fmtPrice(p.signed_amount)}</td>
        <td>${fmtPrice(p.running_balance_after)}</td>
        <td>${p.payment_receipt_url ? `<a href="${ctx.esc(p.payment_receipt_url)}" target="_blank" class="btn btn-secondary btn-sm">Receipt</a>` : ""}</td>
      </tr>`).join("")}
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
    ctx.openDetail(e.description, `
      <div class="review-grid">
        ${ctx.reviewRow("Type", e.entry_type)}
        ${ctx.reviewRow("Amount", fmtPrice(e.signed_amount))}
        ${ctx.reviewRow("Running balance", fmtPrice(e.running_balance))}
        ${ctx.reviewRow("When", new Date(e.created_at).toLocaleString())}
        ${ctx.reviewRow("By", e.created_by_name)}
      </div>${extra}`,
      `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`, "md");
  }

  let settleFile = null;

  function openSettle() {
    if (!apDetail) return;
    const outstanding = Number(apDetail.outstanding) || 0;
    document.getElementById("settle-body").innerHTML = `
      <div class="review-block" style="margin-bottom:16px;">
        ${ctx.reviewRow("Vendor", apDetail.vendor_label)}
        ${ctx.reviewRow("Outstanding", fmtPrice(outstanding))}
      </div>
      <label class="label">Payment reference / ID</label>
      <input class="input" id="settle-ref" style="margin-bottom:12px;" placeholder="UTR, cheque #, etc." />
      <label class="label">Amount (₹)</label>
      <input type="number" step="0.01" class="input" id="settle-amount" value="${outstanding}" style="margin-bottom:12px;" />
      <label class="label">Comment (optional)</label>
      <input class="input" id="settle-comment" style="margin-bottom:12px;" />
      <label class="label">Upload payment receipt</label>
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
    ctx.showLoading?.();
    try {
      let key = null;
      if (settleFile) {
        const fd = new FormData();
        fd.append("vendor_id", String(currentVendor));
        fd.append("payment_ref", ref);
        fd.append("file", settleFile);
        const API = ctx.apiBase ? ctx.apiBase() : "http://127.0.0.1:8003/api/v1";
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
      closeSettle();
      ctx.toast("Payment recorded", "success");
      await openVendorAp(currentVendor);
      loadApList();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function showApFromVendor(vendorId) {
    if (!ctx.isAdmin?.()) return ctx.toast?.("Finance is admin only", "error");
    ctx.showView?.("finance");
    showAp();
    openVendorAp(vendorId);
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
    const totalOut = customers.reduce((s, c) => s + (Number(c.outstanding) || 0), 0);
    if (sum) {
      sum.innerHTML = `
        <div class="fin-summary-grid">
          <div class="fin-card">
            <div class="fin-card-title">Total receivable</div>
            <div class="fin-card-value">${fmtPrice(totalOut)}</div>
            <div class="fin-card-sub">${customers.length} customer${customers.length === 1 ? "" : "s"}</div>
          </div>
          <div class="fin-card fin-card-chart">
            <div class="fin-card-title">Who owes us</div>
            ${hBarList(customers.slice(0, 6), "customer_label", "outstanding")}
          </div>
        </div>`;
    }
    if (!customers.length) {
      el.innerHTML = `<div class="empty-state"><p>No accounts receivable yet. Process customer orders to create bills.</p></div>`;
      return;
    }
    el.innerHTML = `<table class="data"><thead><tr>
      <th>Customer</th><th>Outstanding</th><th>Bills</th><th>Paid</th><th>Txns</th>
    </tr></thead><tbody>
      ${customers.map(c => `<tr class="clickable" onclick="Finance.openCustomerAr(${c.customer_id})">
        <td><strong>${ctx.esc(c.customer_label)}</strong></td>
        <td><strong>${fmtPrice(c.outstanding)}</strong></td>
        <td>${fmtPrice(c.bill_total)}</td>
        <td>${fmtPrice(c.payment_total)}</td>
        <td>${c.transaction_count}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  async function openCustomerAr(customerId) {
    if (!ctx.isAdmin?.()) return;
    ctx.showLoading?.();
    try {
      arDetail = await ctx.api(`/accounts-receivable/customer/${customerId}`, {}, 0);
      currentCustomer = customerId;
      document.getElementById("finance-hub")?.classList.add("hidden");
      document.getElementById("finance-ar-detail")?.classList.remove("hidden");
      renderArDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderArDetail() {
    const title = document.getElementById("finance-ar-title");
    const body = document.getElementById("finance-ar-body");
    if (!arDetail || !body) return;
    if (title) title.textContent = arDetail.customer_label;
    const outstanding = Number(arDetail.outstanding) || 0;
    body.innerHTML = `
      <div class="review-grid" style="margin-bottom:20px;">
        ${ctx.reviewRow("Outstanding", fmtPrice(arDetail.outstanding))}
        ${ctx.reviewRow("Total bills", fmtPrice(arDetail.bill_total))}
        ${ctx.reviewRow("Payments received", fmtPrice(arDetail.payment_total))}
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <h3 style="margin:0;font-size:18px;">AR Ledger</h3>
        ${outstanding > 0 ? `<button class="btn btn-primary" onclick="Finance.openArSettle()">Record Payment</button>` : ""}
      </div>
      <div class="card table-wrap">
        <table class="data"><thead><tr>
          <th>When</th><th>Type</th><th>Description</th><th>Amount</th><th>Balance</th>
        </tr></thead><tbody>
          ${(arDetail.entries || []).map(e => `<tr>
            <td style="font-size:12px;">${new Date(e.created_at).toLocaleString()}</td>
            <td>${ctx.esc(e.entry_type)}</td>
            <td>${ctx.esc(e.description)}</td>
            <td>${fmtPrice(e.signed_amount)}</td>
            <td><strong>${fmtPrice(e.running_balance)}</strong></td>
          </tr>`).join("")}
        </tbody></table>
      </div>`;
  }

  function openArSettle() {
    if (!arDetail) return;
    const outstanding = Number(arDetail.outstanding) || 0;
    document.getElementById("ar-settle-body").innerHTML = `
      <div class="review-block" style="margin-bottom:16px;">
        ${ctx.reviewRow("Customer", arDetail.customer_label)}
        ${ctx.reviewRow("Outstanding", fmtPrice(outstanding))}
      </div>
      <label class="label">Payment reference</label>
      <input class="input" id="ar-settle-ref" style="margin-bottom:12px;" />
      <label class="label">Amount (₹)</label>
      <input type="number" step="0.01" class="input" id="ar-settle-amount" value="${outstanding}" style="margin-bottom:12px;" />
      <label class="label">Comment (optional)</label>
      <input class="input" id="ar-settle-comment" />`;
    document.getElementById("ar-settle-modal").classList.remove("hidden");
  }

  function closeArSettle() { document.getElementById("ar-settle-modal")?.classList.add("hidden"); }

  async function submitArSettle() {
    if (!currentCustomer || !arDetail) return;
    const ref = (document.getElementById("ar-settle-ref")?.value || "").trim();
    const amount = parseFloat(document.getElementById("ar-settle-amount")?.value || "0");
    const comment = (document.getElementById("ar-settle-comment")?.value || "").trim() || null;
    if (!ref) return ctx.toast("Enter payment reference", "error");
    if (!amount || amount <= 0) return ctx.toast("Enter valid amount", "error");
    ctx.showLoading?.();
    try {
      await ctx.api(`/accounts-receivable/customer/${currentCustomer}/settle`, {
        method: "POST",
        body: JSON.stringify({ payment_ref: ref, amount, comment }),
      });
      ctx.invalidateCache?.("/accounts-receivable");
      closeArSettle();
      ctx.toast("Payment recorded", "success");
      await openCustomerAr(currentCustomer);
      loadArList();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  /* —— Expenses —— */
  async function loadExpenses() {
    if (!ctx.api) return ctx.toast?.("Finance not ready — hard refresh", "error");
    ctx.showLoading?.();
    try {
      expenses = await ctx.api("/expenses", {}, 0);
      if (!Array.isArray(expenses)) expenses = [];
      renderExpenses();
    } catch (e) { ctx.toast?.(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderExpenses() {
    const el = document.getElementById("finance-expenses-list");
    if (!el) return;
    if (!expenses.length) {
      el.innerHTML = `<div class="empty-state"><p>No expenses recorded yet.</p></div>`;
      return;
    }
    el.innerHTML = `<table class="data"><thead><tr>
      <th>Date</th><th>Category</th><th>Description</th><th>Amount</th><th>Ref</th>
    </tr></thead><tbody>
      ${expenses.map(e => `<tr>
        <td>${e.expense_date}</td>
        <td>${ctx.esc(e.category)}</td>
        <td>${ctx.esc(e.description || "—")}</td>
        <td>${fmtPrice(e.amount)}</td>
        <td>${ctx.esc(e.reference || "—")}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  function openExpenseForm() {
    const today = new Date().toISOString().slice(0, 10);
    document.getElementById("expense-body").innerHTML = `
      <label class="label">Date</label>
      <input type="date" class="input" id="exp-date" value="${today}" style="margin-bottom:12px;" />
      <label class="label">Category</label>
      <select class="input" id="exp-cat" style="margin-bottom:12px;width:100%;">
        <option value="rent">Rent</option><option value="salary">Salary</option>
        <option value="electricity">Electricity</option><option value="transport">Transport</option>
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
      closeExpenseForm();
      ctx.toast("Expense saved", "success");
      loadExpenses();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  /* —— Revenue / Cost / PnL —— */
  function renderRevenue() {
    const el = document.getElementById("finance-revenue-body");
    if (!el || !overview) return;
    el.innerHTML = `
      <div class="fin-summary-grid">
        <div class="fin-card"><div class="fin-card-title">Cash received (AR)</div><div class="fin-card-value">${fmtPrice(overview.revenue)}</div></div>
        <div class="fin-card"><div class="fin-card-title">Billed to customers</div><div class="fin-card-value">${fmtPrice(overview.revenue_billed)}</div></div>
        <div class="fin-card"><div class="fin-card-title">Still pending</div><div class="fin-card-value">${fmtPrice(overview.ar_outstanding)}</div></div>
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

  function renderCost() {
    const el = document.getElementById("finance-cost-body");
    if (!el || !overview) return;
    el.innerHTML = `
      <div class="fin-summary-grid">
        <div class="fin-card"><div class="fin-card-title">Total cost (paid)</div><div class="fin-card-value">${fmtPrice(overview.cost)}</div>
          <div class="fin-card-sub">Expenses + vendor payments</div></div>
        <div class="fin-card"><div class="fin-card-title">Expenses</div><div class="fin-card-value">${fmtPrice(overview.expense_total)}</div></div>
        <div class="fin-card"><div class="fin-card-title">Vendor payments</div><div class="fin-card-value">${fmtPrice(overview.ap_paid)}</div>
          <div class="fin-card-sub">AP still due ${fmtPrice(overview.ap_outstanding)}</div></div>
      </div>
      <div class="fin-summary-grid" style="margin-top:16px;">
        <div class="fin-card fin-card-chart"><div class="fin-card-title">Cost mix</div>
          ${donutChart(overview.cost_mix, ["#d97706", "#0d9488"])}
        </div>
        <div class="fin-card fin-card-chart"><div class="fin-card-title">Monthly cost</div>
          ${barChart(overview.month_series, ["expenses", "ap_paid"], ["#d97706", "#0d9488"])}
        </div>
      </div>
      ${(overview.expense_breakdown || []).length ? `<div class="fin-card" style="margin-top:16px;"><div class="fin-card-title">Expenses by category</div>
        ${hBarList(overview.expense_breakdown, "category", "amount")}</div>` : ""}`;
  }

  function renderPnl() {
    const el = document.getElementById("finance-pnl-body");
    if (!el || !overview) return;
    const profit = Number(overview.profit) || 0;
    el.innerHTML = `
      <div class="fin-summary-grid">
        <div class="fin-card"><div class="fin-card-title">Revenue</div><div class="fin-card-value">${fmtPrice(overview.revenue)}</div></div>
        <div class="fin-card"><div class="fin-card-title">Cost</div><div class="fin-card-value">${fmtPrice(overview.cost)}</div></div>
        <div class="fin-card"><div class="fin-card-title">Manual losses</div><div class="fin-card-value">${fmtPrice(overview.manual_loss_total)}</div></div>
        <div class="fin-card"><div class="fin-card-title">Profit</div>
          <div class="fin-card-value ${profit >= 0 ? "is-pos" : "is-neg"}">${fmtPrice(overview.profit)}</div>
          <div class="fin-card-sub">Revenue − Cost − Losses</div></div>
      </div>
      <div class="fin-summary-grid" style="margin-top:16px;">
        <div class="fin-card fin-card-chart"><div class="fin-card-title">Monthly profit</div>
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
      renderPnl();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function deleteLoss(id) {
    if (!confirm("Delete this loss entry?")) return;
    ctx.showLoading?.();
    try {
      await ctx.api(`/finance/losses/${id}`, { method: "DELETE" });
      await loadOverview();
      renderPnl();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  /* —— Freight agents —— */
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
    const totalDue = freightAgents.reduce((s, a) => s + Number(a.balance_due || 0), 0);
    const sum = document.getElementById("finance-freight-summary");
    if (sum) sum.innerHTML = `<div class="fin-stat"><span class="fin-stat-label">Total outstanding</span><strong>${fmtPrice(totalDue)}</strong></div>`;
    el.innerHTML = `<table class="data"><thead><tr>
      <th>Agent</th><th>Outstanding</th><th>Notes</th>
    </tr></thead><tbody>
      ${freightAgents.map(a => `<tr class="clickable" onclick="Finance.openFreightAgent(${a.id})">
        <td><strong>${ctx.esc(a.name)}</strong></td>
        <td>${fmtPrice(a.balance_due)}</td>
        <td style="color:var(--muted);">${ctx.esc(a.notes || "—")}</td>
      </tr>`).join("")}
      ${!freightAgents.length ? `<tr><td colspan="3" style="text-align:center;padding:32px;color:var(--muted);">No freight agents. Create one in Setup.</td></tr>` : ""}
    </tbody></table>`;
  }

  async function openFreightAgent(id) {
    freightAgentId = id;
    const agent = freightAgents.find(a => a.id === id);
    ctx.showLoading?.();
    try {
      freightLedger = await ctx.api(`/freight-agents/${id}/ledger`, {}, 0);
      document.getElementById("finance-panel-freight")?.classList.add("hidden");
      document.getElementById("finance-hub")?.classList.add("hidden");
      document.getElementById("finance-freight-detail")?.classList.remove("hidden");
      document.getElementById("finance-freight-title").textContent = agent?.name || "Freight agent";
      renderFreightDetail(agent);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderFreightDetail(agent) {
    const el = document.getElementById("finance-freight-body");
    if (!el) return;
    const due = Number(agent?.balance_due || 0);
    el.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:12px;">
        <div class="fin-stat"><span class="fin-stat-label">Balance due</span><strong>${fmtPrice(due)}</strong></div>
        ${due > 0 ? `<button class="btn btn-primary" onclick="Finance.openFreightSettle()">Settle</button>` : ""}
      </div>
      <div class="card table-wrap">
        <table class="data"><thead><tr>
          <th>Date</th><th>Type</th><th>Amount</th><th>Txn / Bill</th><th>Notes</th><th>By</th>
        </tr></thead><tbody>
          ${freightLedger.map(r => `<tr>
            <td>${ctx.fmtDate?.(r.created_at) || r.created_at?.slice(0, 10) || "—"}</td>
            <td><span class="badge ${r.entry_type === "charge" ? "badge-amber" : "badge-green"}">${ctx.esc(r.entry_type)}</span></td>
            <td>${fmtPrice(r.amount)}</td>
            <td style="font-family:monospace;font-size:12px;">${ctx.esc(r.transaction_ref || (r.customer_bill_id ? `Bill #${r.customer_bill_id}` : "—"))}</td>
            <td style="color:var(--muted);">${ctx.esc(r.notes || "—")}</td>
            <td>${ctx.esc(r.created_by_name || "—")}</td>
          </tr>`).join("")}
          ${!freightLedger.length ? `<tr><td colspan="6" style="text-align:center;padding:32px;color:var(--muted);">No ledger entries yet.</td></tr>` : ""}
        </tbody></table>
      </div>`;
  }

  function openFreightSettle() {
    const agent = freightAgents.find(a => a.id === freightAgentId);
    if (!agent) return;
    const outstanding = Number(agent.balance_due || 0);
    document.getElementById("freight-settle-body").innerHTML = `
      <p style="margin:0 0 12px;color:var(--muted);">Pay ${ctx.esc(agent.name)}. Saves as transport expense (hits Cost / PnL).</p>
      <label class="label">Transaction ID *</label>
      <input class="input" id="freight-settle-ref" style="margin-bottom:12px;" placeholder="UTR, cheque #, etc." />
      <label class="label">Amount (₹) *</label>
      <input type="number" step="0.01" class="input" id="freight-settle-amount" value="${outstanding}" style="margin-bottom:12px;" />
      <label class="label">Notes</label>
      <input class="input" id="freight-settle-notes" />`;
    document.getElementById("freight-settle-modal")?.classList.remove("hidden");
  }

  function closeFreightSettle() {
    document.getElementById("freight-settle-modal")?.classList.add("hidden");
  }

  async function submitFreightSettle() {
    if (!freightAgentId) return;
    const ref = (document.getElementById("freight-settle-ref")?.value || "").trim();
    const amount = parseFloat(document.getElementById("freight-settle-amount")?.value || "0");
    const notes = (document.getElementById("freight-settle-notes")?.value || "").trim() || null;
    if (!ref) return ctx.toast("Transaction ID required", "error");
    if (!(amount > 0)) return ctx.toast("Enter amount", "error");
    ctx.showLoading?.();
    try {
      await ctx.api(`/freight-agents/${freightAgentId}/settle`, {
        method: "POST",
        body: JSON.stringify({ amount, transaction_ref: ref, notes }),
      });
      ctx.toast("Freight payment recorded", "success");
      closeFreightSettle();
      freightAgents = await ctx.api("/freight-agents", {}, 0);
      await openFreightAgent(freightAgentId);
      loadOverviewSilent();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function loadRouteCollections() {
    const el = document.getElementById("finance-routes-list");
    if (!el) return;
    ctx.showLoading?.();
    try {
      routeCollections = await ctx.api("/finance/route-collections", {}, 0);
      if (!routeCollections.length) {
        el.innerHTML = `<div class="empty-state"><p>No routes yet. Add routes under Setup.</p></div>`;
        return;
      }
      el.innerHTML = routeCollections.map(r => `
        <div class="rc-card" onclick="Finance.openRouteCollection(${r.route_id})">
          <div>
            <strong>${ctx.esc(r.route_name)}</strong>
            <div class="rc-meta">${r.city_count} cities · ${r.customer_count} customers · ${r.customers_with_outstanding} with dues</div>
          </div>
          <div class="rc-amt">${fmtPrice(r.total_outstanding)}</div>
        </div>`).join("");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openRouteCollection(routeId) {
    ctx.showLoading?.();
    try {
      routeDetail = await ctx.api(`/finance/route-collections/${routeId}`, {}, 0);
      routeCustomerDetail = null;
      document.getElementById("finance-hub")?.classList.add("hidden");
      document.getElementById("finance-routes-detail")?.classList.remove("hidden");
      document.getElementById("finance-routes-title").textContent = routeDetail.route_name;
      document.getElementById("finance-routes-sub").textContent =
        `Total outstanding ${fmtPrice(routeDetail.total_outstanding)} · ${(routeDetail.cities || []).map(c => c.name).join(", ") || "No cities"}`;
      renderRouteDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderRouteDetail() {
    const el = document.getElementById("finance-routes-body");
    if (!el || !routeDetail) return;
    if (routeCustomerDetail) {
      const c = routeCustomerDetail;
      el.innerHTML = `
        <button class="btn btn-secondary btn-sm" style="margin-bottom:14px;" onclick="Finance.backRouteCustomers()">← Customers</button>
        <div class="fin-card" style="margin-bottom:16px;">
          <strong style="font-size:18px;">${ctx.esc(c.business_name)}</strong>
          <div style="font-size:13px;color:var(--muted);margin-top:4px;">
            ${ctx.esc(c.person_name || "")}${c.person_name ? " · " : ""}${ctx.esc(c.city_name || "—")} · ${ctx.esc(c.phone || "")}
          </div>
          <div style="display:flex;gap:16px;margin-top:12px;flex-wrap:wrap;">
            <div><div style="font-size:12px;color:var(--muted);">Outstanding</div><strong style="font-size:20px;color:#1d4ed8;">${fmtPrice(c.outstanding)}</strong></div>
            <div><div style="font-size:12px;color:var(--muted);">Billed</div><strong>${fmtPrice(c.bill_total)}</strong></div>
            <div><div style="font-size:12px;color:var(--muted);">Paid</div><strong>${fmtPrice(c.payment_total)}</strong></div>
          </div>
        </div>
        <div class="card table-wrap">
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
            ${!(c.ledger || []).length ? `<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--muted);">No ledger entries</td></tr>` : ""}
          </tbody></table>
        </div>`;
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
      </div>`).join("") : `<div class="empty-state"><p>No outstanding on this route.</p></div>`;
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
    init, showHub, showAp, showAr, showExpenses, showRevenue, showCost, showPnl, showFreight,
    showRouteCollections, openRouteCollection, openRouteCustomer, backRouteCustomers, printRouteCollection,
    showApFromVendor, openVendorAp, openEntry, openSettle, closeSettle, submitSettle, setSettleFile,
    setApTab, toggleBill,
    openCustomerAr, openArSettle, closeArSettle, submitArSettle,
    openExpenseForm, closeExpenseForm, submitExpense,
    openLossForm, closeLossForm, submitLoss, deleteLoss,
    openFreightAgent, openFreightSettle, closeFreightSettle, submitFreightSettle,
  };
})();
