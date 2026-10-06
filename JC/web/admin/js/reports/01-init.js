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
      { letter: "S", tag: "Stock", title: "What’s in stock?", desc: "Stock wise · valuation · low stock", onclick: "Reports.pickQuestion('stock','stock-wise')", className: "setup-tile-catalog" },
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
        stock: "Stock wise, value on hand, movers, returns",
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
    // Low stock is a point-in-time on-hand-vs-threshold snapshot (GET /reports/
    // stock/low takes no date param at all) and can't be date-ranged; customers/
    // vendors/expenses ledger *lists* are lifetime aggregates with no date filter
    // either (only the expenses per-category *detail* screen honors a range) — all
    // four used to render a fully interactive date-preset/From-To picker that
    // silently did nothing when touched.
    const noDates = chip === "valuation" || chip === "ageing" || chip === "low"
      || (chip === "ledgers" && ["products", "staff", "routes", "freight", "customers", "vendors", "expenses"].includes(ledgerKind));
    if (noDates) {
      el.innerHTML = `<div class="rep-filters">
        ${chip === "low" ? `<label class="label">Threshold<input type="number" class="input" id="rep-threshold" min="0" value="${lowThreshold}" onchange="Reports.onThresholdChange()" style="min-width:90px" /></label>` : ""}
        ${reportActionButtons()}
      </div>`;
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
      ${reportActionButtons()}
    </div>`;
  }

  function reportActionButtons() {
    return `<div class="rep-presets" style="margin-left:auto;">
      <button type="button" class="btn btn-secondary btn-sm" onclick="Reports.printCurrent()">Print</button>
      <button type="button" class="btn btn-secondary btn-sm" onclick="Reports.exportCurrentExcel()">Excel</button>
    </div>`;
  }

  function reportPrintRoot() {
    const detail = document.getElementById("reports-ledger-detail");
    if (detail && !detail.classList.contains("hidden")) return detail;
    return document.getElementById("reports-body");
  }

  function reportTables(root) {
    const tables = [...(root?.querySelectorAll("table") || [])];
    if (tables.length) return tables;
    const rows = [...(root?.querySelectorAll(".review-row") || [])];
    if (!rows.length) return [];
    const body = rows.map(row => {
      const label = row.querySelector(".review-label")?.textContent || "";
      const value = row.querySelector(".review-value")?.textContent || "";
      return `<tr><td>${ctx.esc(label)}</td><td>${ctx.esc(value)}</td></tr>`;
    }).join("");
    const holder = document.createElement("div");
    holder.innerHTML = `<table><thead><tr><th>Item</th><th>Value</th></tr></thead><tbody>${body}</tbody></table>`;
    return [...holder.querySelectorAll("table")];
  }

  function printCurrent() {
    const root = reportPrintRoot();
    const tables = reportTables(root);
    const chunk = tables.length ? tables.map(t => t.outerHTML).join("<br>") : (root?.innerHTML || "");
    if (!chunk.trim()) return ctx.toast?.("Nothing to print", "error");
    const title = (document.querySelector("#reports-ledger-hero h1, #reports-ledger-hero .hub-title, #reports-hero h1")?.textContent || chip || "Report").trim();
    const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${ctx.esc(title)}</title>
      <style>body{font-family:sans-serif;font-size:12px;color:#111} h1{font-size:16px} table{border-collapse:collapse;width:100%;margin:0 0 16px} td,th{border:1px solid #ccc;padding:4px 6px;text-align:left;vertical-align:top} button,.btn{display:none}</style>
      </head><body><h1>${ctx.esc(title)}</h1>${chunk}</body></html>`;
    const w = window.open("", "_blank");
    if (!w) return ctx.toast?.("Allow pop-ups to print", "error");
    w.document.open();
    w.document.write(html);
    w.document.close();
    w.focus();
    setTimeout(() => { try { w.print(); } catch (_) {} }, 200);
  }

  function exportCurrentExcel() {
    const root = reportPrintRoot();
    const tables = reportTables(root);
    if (!tables.length) return ctx.toast?.("Nothing to export", "error");
    const html = `<html><head><meta charset="utf-8"></head><body>${tables.map(t => t.outerHTML).join("<br>")}</body></html>`;
    const blob = new Blob([html], { type: "application/vnd.ms-excel" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${String(chip || "report").replace(/[^a-z0-9_-]+/gi, "-")}.xls`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function renderSearch() {
    const slot = document.getElementById("reports-search-slot");
    if (!slot) return;
    const caret = (typeof OrdersUI !== "undefined" && OrdersUI.captureSearchCaret)
      ? OrdersUI.captureSearchCaret("reports-hub-search") : null;
    const searchable = ["sales", "sales-book", "receipt-book", "daybook", "purchases", "payments", "ledgers", "ageing", "customer-sales", "vendor-purchases", "item-sales", "item-purchases", "stock-wise", "valuation", "movers", "low", "returns", "debit-notes", "gst-sales", "gst-purchases", "cashbook", "expense-cat"].includes(chip);
    if (!searchable) { slot.innerHTML = ""; return; }
    const ph = chip === "ledgers"
      ? (ledgerKind === "staff" ? "Search staff…" : ledgerKind === "products" ? "Search products…" : ledgerKind === "customers" || ledgerKind === "vendors" ? "Search name, person, city…" : "Search…")
      : chip.includes("item") || chip === "stock-wise" || chip === "valuation" || chip === "movers" || chip === "low" ? "Search product…"
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
      else if (chip === "sales" || chip === "sales-book") await renderDocList(body, "sales", "Sales book");
      else if (chip === "receipt-book") await renderReceiptBook(body);
      else if (chip === "purchases") await renderDocList(body, "purchases", "Purchase bills");
      else if (chip === "payments") await renderPayments(body);
      else if (chip === "ledgers") await renderLedgers(body);
      else if (chip === "ageing") await renderAgeing(body);
      else if (chip === "customer-sales") await renderPartyAgg(body, "customer-sales", "customers");
      else if (chip === "vendor-purchases") await renderPartyAgg(body, "vendor-purchases", "vendors");
      else if (chip === "item-sales") await renderItemAgg(body, "item-sales");
      else if (chip === "item-purchases") await renderItemAgg(body, "item-purchases");
      else if (chip === "stock-wise") await renderStockWise(body);
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
    const data = await ctx.api(`/reports/daybook${rangeQs()}`, {}, 0);
    const t = data.totals || {};
    let rows = data.entries || [];
    rows = rows.filter(r => matchSearch(r.kind, r.party, r.label));
    body.innerHTML = `
      ${DocShare.toolbarHtml({
        printOnclick: "Reports.shareDaybook(true)",
        pdfOnclick: "Reports.shareDaybook(false)",
        waOnclick: "Reports.waDaybook()",
        // No Excel button here — GET /export/sales_bills.xlsx takes no date param
        // and always dumps the entire lifetime sales register, unrelated to the
        // single day this screen is scoped to (unlike Print/PDF/WhatsApp above,
        // which correctly target just this day). Silently downloading the wrong,
        // unfiltered, unlabeled file was worse than not offering Excel here at all.
      })}
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">Entries</span><strong>${t.count || 0}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Cash in</span><strong>${fmtPrice(t.cash_in)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Cash out</span><strong>${fmtPrice(t.cash_out)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Sales</span><strong>${t.sales_count || 0}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Purchases</span><strong>${t.purchase_count || 0}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Amount total</span><strong>${fmtPrice(rows.reduce((s, r) => s + (Number(r.amount) || 0), 0))}</strong></div>
      </div>
      ${simpleTable(["Time", "Type", "Party", "Particulars", "Amount"], rows.map(r => {
        const cells = [
          r.at ? new Date(r.at).toLocaleString() : "—",
          `<span class="badge badge-blue">${ctx.esc(r.kind)}</span>`,
          ctx.esc(r.party || "—"),
          ctx.esc(r.label || "—"),
          fmtPrice(r.amount),
        ];
        if (r.kind === "sales" && r.ref_id) cells._onclick = `BillSeries.openBill(${Number(r.ref_id)})`;
        else if (r.kind === "purchase" && r.ref_id) cells._onclick = `Stock.openReceiptDetail(${Number(r.ref_id)})`;
        return cells;
      }), "Quiet day", "No entries in this range. Try another range.")}`;
  }

  function daybookShareQs() {
    return rangeQs();
  }

  function daybookCaption() {
    if (fromDate && toDate && fromDate !== toDate) return `Daybook ${fromDate} to ${toDate}`;
    if (fromDate || toDate) return `Daybook ${fromDate || toDate}`;
    return "Daybook";
  }

  async function shareDaybook(print) {
    try {
      const name = fromDate && toDate && fromDate !== toDate
        ? `daybook_${fromDate}_${toDate}.pdf`
        : `daybook_${fromDate || toDate || "all"}.pdf`;
      await DocShare.openPdf(`/share/daybook/pdf${daybookShareQs()}`, {
        print: !!print,
        filename: name,
      });
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function waDaybook() {
    const phone = prompt("WhatsApp phone (10 digits / with country code):");
    if (!phone) return;
    ctx.showLoading?.();
    try {
      const res = await DocShare.whatsapp({
        kind: "daybook",
        from_date: fromDate || undefined,
        to_date: toDate || undefined,
        phone,
        caption: daybookCaption(),
      });
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

  function amountTotal(items) {
    return items.reduce((s, it) => s + (Number(it.amount) || 0), 0);
  }

  async function renderDocList(body, path, title) {
    const data = await ctx.api(`/reports/${path}${rangeQs()}`, {}, 0);
    let items = (data.items || []).filter(it => matchSearch(it.doc_number, it.party_label));
    const total = amountTotal(items);
    body.innerHTML = `
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">Bills</span><strong>${items.length}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Amount total</span><strong>${fmtPrice(total)}</strong></div>
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
        <tr><td colspan="3"><strong>Total</strong></td><td><strong>${fmtPrice(total)}</strong></td></tr>
      </tbody></table></div>` : empty("No documents", "Widen the date range or clear search.")}`;
  }

  async function renderReceiptBook(body) {
    const data = await ctx.api(`/reports/payments${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => it.direction === "in" && matchSearch(it.doc_number, it.party_label, it.description));
    const total = amountTotal(items);
    body.innerHTML = `
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">Receipts</span><strong>${items.length}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Amount total</span><strong>${fmtPrice(total)}</strong></div>
      </div>
      ${items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Date</th><th>Receipt</th><th>Party</th><th>Amount</th><th>Note</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Finance.openCustomerAr(${it.party_id})">
          <td>${ctx.esc(it.date || "—")}</td>
          <td><strong>${ctx.esc(it.doc_number || "—")}</strong></td>
          <td>${ctx.esc(it.party_label || "—")}</td>
          <td>${fmtPrice(it.amount)}</td>
          <td style="color:var(--muted);font-size:13px;">${ctx.esc(it.description || "—")}</td>
        </tr>`).join("")}
        <tr><td colspan="3"><strong>Total</strong></td><td><strong>${fmtPrice(total)}</strong></td><td></td></tr>
      </tbody></table></div>` : empty("No receipts", "Widen the dates to see money received.")}`;
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

