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

  function localToday() {
    const n = new Date();
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
  }

  let saveBusy = false; // guard expense/payment PATCH double-click

  function fmtDocDate(d) {
    if (!d) return "—";
    if (typeof d === "string" && /^\d{4}-\d{2}-\d{2}$/.test(d)) return ctx.fmtDay?.(d) || d;
    return ctx.fmtDate?.(d) || new Date(d).toLocaleString();
  }

  function docDateIso(d) {
    if (!d) return "";
    if (typeof d === "string" && /^\d{4}-\d{2}-\d{2}/.test(d)) return d.slice(0, 10);
    const dt = new Date(d);
    if (Number.isNaN(dt.getTime())) return "";
    return dt.toISOString().slice(0, 10);
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
    ["ap", "ar", "expenses", "journal", "freight", "routes", "reports"].forEach(k => {
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

    const scopedArAp = !ctx.isAdmin?.() && (ctx.can?.("ar.read") || ctx.can?.("ap.read"));
    const allChips = [
      { id: "due", label: "To do", count: chipCounts.due || undefined },
      { id: "ar", label: "To collect", count: chipCounts.ar || undefined },
      { id: "ap", label: "To pay", count: chipCounts.ap || undefined },
      { id: "freight", label: "Freight", count: chipCounts.freight || undefined },
      { id: "expenses", label: "Other spend" },
      { id: "journal", label: "Journal" },
      { id: "routes", label: "Routes" },
      { id: "reports", label: "Cash snapshot" },
    ];
    const items = scopedArAp
      ? allChips.filter(i =>
        (i.id === "ar" && ctx.can?.("ar.read")) || (i.id === "ap" && ctx.can?.("ap.read")))
      : allChips.filter(i => i.id !== "journal" || ctx.isAdmin?.());
    OrdersUI.actionChips({
      hostId: "finance-action-chips",
      active: activeChip,
      onclickFn: "Finance.setChip",
      items,
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
      if (ctx.can?.("ar.read") || ctx.can?.("ap.read")) { showArApHub(); return; }
      if (ctx.can?.("finance.write")) { showQuickEntry(); return; }
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

  /** Entry-only view for accountant-role staff — no totals, no reports, no ledgers. */
  function showQuickEntry() {
    document.getElementById("finance-hub")?.classList.remove("hidden");
    document.getElementById("finance-ap-detail")?.classList.add("hidden");
    document.getElementById("finance-ar-detail")?.classList.add("hidden");
    document.getElementById("finance-freight-detail")?.classList.add("hidden");
    document.getElementById("finance-routes-detail")?.classList.add("hidden");
    hideAllPanels();
    const sub = document.getElementById("finance-hub-sub");
    if (sub) sub.textContent = "Record entries — figures & reports are owner-only";
    const strip = document.getElementById("finance-hub-strip");
    if (strip) strip.innerHTML = "";
    const chips = document.getElementById("finance-action-chips");
    if (chips) chips.innerHTML = "";
    const search = document.getElementById("finance-search-slot");
    if (search) search.innerHTML = "";
    const needs = document.getElementById("finance-needs");
    if (needs) needs.innerHTML = `
      <div class="card" style="padding:20px;max-width:440px;display:grid;gap:10px;">
        <h3 style="margin:0 0 4px;">Quick entry</h3>
        <p style="margin:0 0 10px;font-size:13px;color:var(--muted);">Record a transaction below. Running balances, dues, and reports aren't shown here — check with the owner if unsure of an amount.</p>
        <button class="btn btn-primary" onclick="Finance.quickVendorPayment()">Record vendor payment</button>
        <button class="btn btn-primary" onclick="Finance.quickCustomerPayment()">Record customer payment</button>
        <button class="btn btn-primary" onclick="Finance.quickAddExpense()">+ Add expense</button>
      </div>`;
    App.updateGlobalBack?.();
  }

  /** AR/AP-scoped view — full ledgers, outstanding & payments for AR/AP only. No P&L, revenue, freight or reports. */
  function showArApHub() {
    document.getElementById("finance-hub")?.classList.remove("hidden");
    document.getElementById("finance-ap-detail")?.classList.add("hidden");
    document.getElementById("finance-ar-detail")?.classList.add("hidden");
    document.getElementById("finance-freight-detail")?.classList.add("hidden");
    document.getElementById("finance-routes-detail")?.classList.add("hidden");
    currentVendor = null;
    currentCustomer = null;
    apDetail = null;
    arDetail = null;
    const strip = document.getElementById("finance-hub-strip");
    if (strip) strip.innerHTML = "";
    const startChip = ctx.can?.("ar.read") ? "ar" : "ap";
    setChip(startChip, true);
    App.updateGlobalBack?.();
  }

  function partyWithCity(row) {
    if (!row) return "—";
    const name = row.business_name || "";
    const city = row.city_name || "";
    if (name && city && !String(name).includes(city)) return `${name} — ${city}`;
    return name || "—";
  }

  function openQuickEntry() {
    ctx.openDetail?.("Quick entry", `
      <div style="display:grid;gap:10px;">
        <p style="margin:0 0 4px;font-size:13px;color:var(--muted);">Record a payment or an expense without opening the party first.</p>
        <button class="btn btn-primary" onclick="App.closeDetail();Finance.quickVendorPayment()">Record vendor payment</button>
        <button class="btn btn-primary" onclick="App.closeDetail();Finance.quickCustomerPayment()">Record customer payment</button>
        <button class="btn btn-primary" onclick="App.closeDetail();Finance.quickAddExpense()">+ Add expense</button>
      </div>`,
      `<button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "sm");
  }

  async function _pickQuickParty(resource, noun) {
    const q = prompt(`Search ${noun} by name or phone:`);
    if (q == null || !q.trim()) return null;
    let rows;
    try {
      // /quick-search (not the full /vendors or /customers list) — the documented
      // finance.write-only "entry-only accountant" role has no vendors.read/
      // customers.read, and the full list endpoints both leak outstanding-balance/
      // cost fields that role is explicitly meant not to see. quick-search accepts
      // finance.write alone and returns only id/business_name/city_name.
      rows = await ctx.api(`/${resource}/quick-search?q=${encodeURIComponent(q.trim())}`, {}, 0);
    } catch (e) { ctx.toast(e.message, "error"); return null; }
    if (!rows || !rows.length) { ctx.toast("No match found", "error"); return null; }
    if (rows.length === 1) return rows[0];
    const listing = rows.slice(0, 8).map((r, i) => `${i + 1}. ${r.business_name}${r.city_name ? " — " + r.city_name : ""}`).join("\n");
    const pick = prompt(`Multiple matches — enter the number:\n${listing}`);
    const idx = parseInt(String(pick || "").trim(), 10) - 1;
    if (!Number.isFinite(idx) || idx < 0 || idx >= rows.length) return null;
    return rows[idx];
  }

  async function quickVendorPayment() {
    const vendor = await _pickQuickParty("vendors", "vendor");
    if (!vendor) return;
    if (!confirm(`Record a payment for "${partyWithCity(vendor)}"?`)) return;
    const amtRaw = prompt("Amount paid (₹):");
    if (amtRaw == null) return;
    const amount = Number(amtRaw);
    if (!Number.isFinite(amount) || amount <= 0) return ctx.toast("Enter a valid amount", "error");

    let paymentModeId;
    let modeName = "";
    try {
      const modes = await ctx.api("/payment-modes?active_only=true", {}, 0);
      if (modes && modes.length) {
        const listing = modes.map((m, i) => `${i + 1}. ${m.name}`).join("\n");
        const pick = prompt(`Payment mode (Cash / Bank) — enter the number:\n${listing}`);
        const idx = parseInt(String(pick || "").trim(), 10) - 1;
        if (!Number.isFinite(idx) || idx < 0 || idx >= modes.length) return ctx.toast("Payment mode required", "error");
        paymentModeId = modes[idx].id;
        modeName = modes[idx].name || "";
      }
    } catch (e) { ctx.toast(e.message, "error"); return; }

    const ref = prompt("Payment reference (cheque no. / UTR / slip no.) *:");
    if (ref == null || !ref.trim()) return ctx.toast("Reference required", "error");
    const comment = prompt("Note (optional):") || "";
    ctx.showLoading?.();
    try {
      const res = await ctx.api(`/accounts-payable/vendor/${vendor.id}/record-payment`, {
        method: "POST",
        body: JSON.stringify({ payment_ref: ref.trim(), payment_mode_id: paymentModeId, amount, comment: comment.trim() || undefined }),
      });
      ctx.toast(res.message || "Payment recorded", "success");
      showPaymentDone({
        title: "Paid",
        party: partyWithCity(vendor),
        amount,
        receipt: ref.trim() || (res.id ? `#${res.id}` : ""),
        comment: comment.trim(),
        mode: res.payment_mode || modeName,
        againFn: "Finance.quickVendorPayment()",
      });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  let quickPayCustomer = null;
  let quickPayModes = [];

  async function quickCustomerPayment() {
    const customer = await _pickQuickParty("customers", "customer");
    if (!customer) return;
    quickPayCustomer = customer;
    let paymentModesLoadFailed = false;
    try {
      quickPayModes = await ctx.api("/payment-modes?active_only=true", {}, 0) || [];
    } catch (e) {
      quickPayModes = [];
      paymentModesLoadFailed = true;
      ctx.toast(e.message, "error");
    }
    const modeOpts = paymentModesLoadFailed
      ? `<p style="font-size:13px;color:var(--danger);margin:0 0 12px;">Couldn't load payment modes. You can still collect; you'll be asked for a mode if one is required.</p>`
      : quickPayModes.length
      ? `<label class="label">Payment mode</label>
        <select class="input" id="quick-pay-mode" style="margin-bottom:12px;width:100%;">
          <option value="">— Select mode —</option>
          ${quickPayModes.map(m => `<option value="${m.id}">${ctx.esc(m.name)}</option>`).join("")}
        </select>`
      : "";
    document.getElementById("quick-pay-body").innerHTML = `
      <div class="review-block" style="margin-bottom:16px;">
        ${ctx.reviewRow("Party", partyWithCity(customer))}
      </div>
      ${modeOpts}
      <label class="label">Collection date</label>
      <input type="date" class="input" id="quick-pay-date" value="${ctx.esc(localToday())}" required style="margin-bottom:12px;" />
      <label class="label">Amount (₹)</label>
      <input type="number" step="0.01" class="input" id="quick-pay-amount" placeholder="Enter amount" style="margin-bottom:8px;" />
      <p style="font-size:12px;color:var(--muted);margin:0 0 12px;">More than they owe, or a payment when nothing is due, is saved as credit.</p>
      <label class="label">Payment reference (optional)</label>
      <input class="input" id="quick-pay-ref" style="margin-bottom:12px;" placeholder="UTR, cheque #…" />
      <label class="label">Comment (optional)</label>
      <input class="input" id="quick-pay-comment" />`;
    document.getElementById("quick-pay-modal")?.classList.remove("hidden");
  }

  function closeQuickPay() {
    document.getElementById("quick-pay-modal")?.classList.add("hidden");
    quickPayCustomer = null;
  }

  async function submitQuickPay() {
    const customer = quickPayCustomer;
    if (!customer) return;
    const amount = parseFloat(document.getElementById("quick-pay-amount")?.value || "0");
    const valueDate = (document.getElementById("quick-pay-date")?.value || "").trim();
    const ref = (document.getElementById("quick-pay-ref")?.value || "").trim();
    const comment = (document.getElementById("quick-pay-comment")?.value || "").trim();
    const modeRaw = document.getElementById("quick-pay-mode")?.value || "";
    const paymentModeId = modeRaw ? parseInt(modeRaw, 10) : null;
    if (quickPayModes.length && !paymentModeId) return ctx.toast("Select payment mode", "error");
    if (!amount || amount <= 0) return ctx.toast("Enter a valid amount", "error");
    if (!valueDate) return ctx.toast("Enter collection date", "error");
    ctx.showLoading?.();
    try {
      const res = await ctx.api(`/accounts-receivable/customer/${customer.id}/record-payment`, {
        method: "POST",
        body: JSON.stringify({
          payment_ref: ref || undefined,
          payment_mode_id: paymentModeId || undefined,
          amount,
          comment: comment || undefined,
          value_date: valueDate,
        }),
      });
      closeQuickPay();
      ctx.toast(res.message || "Payment recorded", "success");
      const modeName = quickPayModes.find(m => m.id === paymentModeId)?.name || res.payment_mode || "";
      showPaymentDone({
        title: "Collected",
        party: partyWithCity(customer),
        amount,
        valueDate,
        receipt: ref || (res.id ? `#${res.id}` : res.payment_ref || ""),
        comment,
        mode: modeName,
        againFn: "Finance.quickCustomerPayment()",
      });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function quickAddExpense() {
    const category = prompt("Category (e.g. rent, salary, transport, misc):");
    if (category == null || !category.trim()) return;
    const amtRaw = prompt("Amount (₹):");
    if (amtRaw == null) return;
    const amount = Number(amtRaw);
    if (!Number.isFinite(amount) || amount <= 0) return ctx.toast("Enter a valid amount", "error");
    // description/date are genuinely optional (fall back to "" / today) — but that
    // exact `|| fallback` pattern can't tell "user cleared the field and hit OK"
    // apart from "user hit Cancel", so a Cancel here used to silently continue and
    // record the expense anyway with today's date, instead of aborting like the
    // category/amount prompts above correctly do.
    const descriptionRaw = prompt("Description (optional):");
    if (descriptionRaw === null) return;
    const description = descriptionRaw || "";
    const today = new Date().toISOString().slice(0, 10);
    const dateInput = prompt("Date (YYYY-MM-DD):", today);
    if (dateInput === null) return;
    const dateRaw = dateInput || today;
    ctx.showLoading?.();
    try {
      await ctx.api("/expenses", {
        method: "POST",
        body: JSON.stringify({
          expense_date: dateRaw.trim(),
          category: category.trim(),
          description: description.trim() || undefined,
          amount,
        }),
      });
      ctx.toast("Expense recorded", "success");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
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
    } else if (chip === "journal") {
      document.getElementById("finance-panel-journal")?.classList.remove("hidden");
      loadJournals();
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

