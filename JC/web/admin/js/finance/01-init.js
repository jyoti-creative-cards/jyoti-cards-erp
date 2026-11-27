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

  const COLLECT_DATE_KEY = "jc_collect_date_lock";

  function collectDateState() {
    try {
      const raw = sessionStorage.getItem(COLLECT_DATE_KEY);
      if (!raw) return { locked: false, date: "" };
      const parsed = JSON.parse(raw);
      return { locked: !!parsed.locked, date: String(parsed.date || "") };
    } catch (_) {
      return { locked: false, date: "" };
    }
  }

  function saveCollectDateState(locked, date) {
    if (locked && date) sessionStorage.setItem(COLLECT_DATE_KEY, JSON.stringify({ locked: true, date }));
    else sessionStorage.removeItem(COLLECT_DATE_KEY);
  }

  function collectDateHtml(inputId) {
    const state = collectDateState();
    const locked = state.locked && !!state.date;
    const value = locked ? state.date : localToday();
    return `<div style="margin:0 0 14px;padding:10px 12px;border:2px solid #f59e0b;background:#fffbeb;border-radius:8px;">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px;">
        <label class="label" style="margin:0;">Collection date</label>
        <label style="display:flex;align-items:center;gap:6px;font-size:13px;font-weight:700;cursor:pointer;">
          <input type="checkbox" id="${inputId}-lock" ${locked ? "checked" : ""} onchange="Finance.toggleCollectDateLock('${inputId}')" />
          Lock
        </label>
      </div>
      <input type="date" class="input" id="${inputId}" value="${ctx.esc(value)}" required oninput="Finance.onCollectDateInput('${inputId}')" onchange="Finance.onCollectDateInput('${inputId}')" />
      <p id="${inputId}-hint" style="margin:6px 0 0;font-size:12px;color:#92400e;">${locked ? "Locked. Every next payment keeps this date." : "Lock it to keep this date for the next payments."}</p>
    </div>`;
  }

  function toggleCollectDateLock(inputId) {
    const lock = document.getElementById(`${inputId}-lock`);
    const date = (document.getElementById(inputId)?.value || "").trim();
    if (lock?.checked && !date) {
      lock.checked = false;
      return ctx.toast("Pick a date, then lock it", "error");
    }
    saveCollectDateState(!!lock?.checked, date);
    const hint = document.getElementById(`${inputId}-hint`);
    if (hint) hint.textContent = lock?.checked
      ? "Locked. Every next payment keeps this date."
      : "Lock it to keep this date for the next payments.";
  }

  function onCollectDateInput(inputId) {
    const lock = document.getElementById(`${inputId}-lock`);
    const date = (document.getElementById(inputId)?.value || "").trim();
    if (lock?.checked) saveCollectDateState(true, date);
  }

  function rememberCollectDate(inputId) {
    const lock = document.getElementById(`${inputId}-lock`);
    const date = (document.getElementById(inputId)?.value || "").trim();
    if (lock?.checked && date) saveCollectDateState(true, date);
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
    ["ap", "ar", "expenses", "journal", "freight", "transport", "routes", "reports"].forEach(k => {
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
      { id: "transport", label: "Transport" },
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
              : activeChip === "transport" ? "Search party or bill…"
              : activeChip === "routes" ? "Search routes…"
                : "Search…";
      const showSearch = ["due", "ap", "ar", "freight", "transport", "routes"].includes(activeChip);
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

  let keepVendorPay = false;

  function showHub() {
    if (!keepVendorPay) vendorPay = null;
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
    if (resource === "customers") {
      let agents = [];
      try {
        agents = await ctx.api(`/commission-agents/quick-search?q=${encodeURIComponent(q.trim())}`, {}, 0) || [];
      } catch (_) { agents = []; }
      const agentRows = agents.map(a => ({ id: a.id, business_name: a.name, city_name: "", kind: "agent" }));
      const partyRows = (rows || []).map(r => ({ ...r, kind: "customer" }));
      if (agentRows.length === 1) return agentRows[0];
      rows = agentRows.concat(partyRows);
    }
    if (!rows || !rows.length) { ctx.toast("No match found", "error"); return null; }
    if (rows.length === 1) return rows[0];
    const listing = rows.slice(0, 8).map((r, i) => `${i + 1}. ${r.business_name}${r.kind === "agent" ? " — Agent" : ""}${r.city_name ? " — " + r.city_name : ""}`).join("\n");
    const pick = prompt(`Multiple matches — enter the number:\n${listing}`);
    const idx = parseInt(String(pick || "").trim(), 10) - 1;
    if (!Number.isFinite(idx) || idx < 0 || idx >= rows.length) return null;
    return rows[idx];
  }

  async function postPayment(path, body) {
    try {
      return await ctx.api(path, { method: "POST", body: JSON.stringify(body) });
    } catch (e) {
      if (!(e.status === 409 && e.detail && e.detail.matches)) throw e;
      const lines = e.detail.matches.map(m => `₹${m.total} · ${m.mode || "—"} · ${m.date || ""}`).join("\n");
      if (!window.confirm(`This could be a duplicate payment.\nSame party, same amount, same date.\n\n${lines}\n\nSave it anyway?`)) {
        const cancel = new Error("Not saved");
        cancel.cancelled = true;
        throw cancel;
      }
      return ctx.api(path, { method: "POST", body: JSON.stringify({ ...body, confirm_duplicate: true }) });
    }
  }

  let vendorPay = null;
  let vendorPayHits = [];
  let vendorPayTimer = null;

  function showVendorPayScreen() {
    ctx.closeDetail?.();
    ctx.showView?.("money");
    document.getElementById("finance-hub")?.classList.remove("hidden");
    document.getElementById("finance-ap-detail")?.classList.add("hidden");
    document.getElementById("finance-ar-detail")?.classList.add("hidden");
    hideAllPanels();
  }

  function readVendorPayFields() {
    return {
      amount: document.getElementById("vp-amount")?.value || "",
      modeId: document.getElementById("vp-mode")?.value || "",
      ref: document.getElementById("vp-ref")?.value || "",
      note: document.getElementById("vp-note")?.value || "",
    };
  }

  function renderVendorPayForm() {
    const host = document.getElementById("finance-needs");
    if (!host || !vendorPay) return;
    host.classList.remove("hidden");
    const picked = vendorPay.vendor;
    const vendorBlock = picked
      ? `<div class="review-block" style="margin-bottom:12px;">${ctx.reviewRow("Vendor", partyWithCity(picked))}</div>
         <button type="button" class="btn btn-secondary" style="margin-bottom:12px;" onclick="Finance.clearVendorPay()">Change vendor</button>`
      : `<label class="label">Vendor</label>
         <input id="vp-q" class="input" placeholder="Name or phone" oninput="Finance.onVendorPaySearch(this.value)" style="margin-bottom:8px;" />
         <div id="vp-hits"></div>`;
    const modeBlock = vendorPay.modesFailed
      ? `<p style="color:var(--danger);margin:0 0 12px;">Couldn't load payment modes.</p>`
      : vendorPay.modes.length
        ? `<label class="label">Payment mode</label>
           <select class="input" id="vp-mode" style="margin-bottom:12px;width:100%;">
             <option value="">— Select mode —</option>
             ${vendorPay.modes.map(m => `<option value="${m.id}"${String(vendorPay.modeId) === String(m.id) ? " selected" : ""}>${ctx.esc(m.name)}</option>`).join("")}
           </select>`
        : "";
    host.innerHTML = `
      <div class="card" style="padding:20px;max-width:480px;">
        <h3 style="margin:0 0 12px;">Record vendor payment</h3>
        ${vendorBlock}
        <label class="label">Amount (₹)</label>
        <input type="number" step="0.01" class="input" id="vp-amount" value="${ctx.esc(vendorPay.amount)}" style="margin-bottom:12px;" />
        ${modeBlock}
        <label class="label">Reference</label>
        <input class="input" id="vp-ref" value="${ctx.esc(vendorPay.ref)}" placeholder="Cheque no. / UTR / slip no." style="margin-bottom:12px;" />
        <label class="label">Note (optional)</label>
        <input class="input" id="vp-note" value="${ctx.esc(vendorPay.note)}" style="margin-bottom:16px;" />
        <button type="button" class="btn btn-primary" onclick="Finance.reviewVendorPay()">Review</button>
      </div>`;
    host.scrollIntoView?.({ block: "start" });
  }

  async function quickVendorPayment() {
    keepVendorPay = true;
    showVendorPayScreen();
    keepVendorPay = false;
    vendorPay = { vendor: null, modes: [], modesFailed: false, amount: "", modeId: "", ref: "", note: "", modeName: "" };
    vendorPayHits = [];
    try {
      vendorPay.modes = await ctx.api("/payment-modes?active_only=true", {}, 0) || [];
    } catch (e) {
      vendorPay.modes = [];
      vendorPay.modesFailed = true;
      ctx.toast(e.message, "error");
    }
    renderVendorPayForm();
  }

  function clearVendorPay() {
    if (!vendorPay) return;
    Object.assign(vendorPay, readVendorPayFields());
    vendorPay.vendor = null;
    renderVendorPayForm();
  }

  function onVendorPaySearch(val) {
    const box = document.getElementById("vp-hits");
    if (!box) return;
    const q = String(val || "").trim();
    clearTimeout(vendorPayTimer);
    if (!q) { box.innerHTML = ""; vendorPayHits = []; return; }
    vendorPayTimer = setTimeout(async () => {
      try {
        const rows = await ctx.api(`/vendors/quick-search?q=${encodeURIComponent(q)}`, {}, 0) || [];
        if ((document.getElementById("vp-q")?.value || "").trim() !== q) return;
        vendorPayHits = rows.slice(0, 8);
        box.innerHTML = vendorPayHits.map(r =>
          `<button type="button" class="btn btn-secondary" style="display:block;width:100%;text-align:left;margin-top:6px;" onclick="Finance.pickVendorPay(${r.id})">${ctx.esc(partyWithCity(r))}</button>`
        ).join("") || `<p style="color:var(--muted);">No match</p>`;
      } catch (e) { box.innerHTML = `<p style="color:var(--danger);">${ctx.esc(e.message)}</p>`; }
    }, 250);
  }

  function pickVendorPay(id) {
    const hit = vendorPayHits.find(r => Number(r.id) === Number(id));
    if (!hit || !vendorPay) return;
    Object.assign(vendorPay, readVendorPayFields());
    vendorPay.vendor = hit;
    renderVendorPayForm();
  }

  function reviewVendorPay() {
    if (!vendorPay) return;
    if (vendorPay.modesFailed) return ctx.toast("Couldn't load payment modes", "error");
    const fields = readVendorPayFields();
    Object.assign(vendorPay, fields);
    if (!vendorPay.vendor) return ctx.toast("Select a vendor", "error");
    const amount = Number(fields.amount);
    if (!Number.isFinite(amount) || amount <= 0) return ctx.toast("Enter a valid amount", "error");
    if (vendorPay.modes.length && !fields.modeId) return ctx.toast("Select the account", "error");
    if (!String(fields.ref || "").trim()) return ctx.toast("Reference required", "error");
    const mode = vendorPay.modes.find(m => String(m.id) === String(fields.modeId));
    vendorPay.modeName = mode?.name || "";
    vendorPay.amountNumber = amount;
    const host = document.getElementById("finance-needs");
    if (!host) return;
    host.innerHTML = `
      <div class="card" style="padding:20px;max-width:480px;">
        <h3 style="margin:0 0 12px;">Check payment</h3>
        <div class="review-block">
          ${ctx.reviewRow("Vendor", partyWithCity(vendorPay.vendor))}
          ${ctx.reviewRow("Amount", fmtPrice(amount))}
          ${ctx.reviewRow("Payment mode", vendorPay.modeName || "—")}
          ${ctx.reviewRow("Reference", fields.ref.trim())}
          ${ctx.reviewRow("Note", fields.note.trim() || "—")}
        </div>
        <div style="display:flex;gap:8px;margin-top:16px;">
          <button type="button" class="btn btn-secondary" style="flex:1;" onclick="Finance.backVendorPay()">Back</button>
          <button type="button" class="btn btn-primary" style="flex:1;" onclick="Finance.submitVendorPay()">Submit</button>
        </div>
      </div>`;
  }

  function backVendorPay() {
    renderVendorPayForm();
  }

  async function submitVendorPay() {
    const pay = vendorPay;
    if (!pay?.vendor) return;
    const ref = String(pay.ref || "").trim();
    const comment = String(pay.note || "").trim();
    const paymentModeId = pay.modeId ? parseInt(pay.modeId, 10) : undefined;
    ctx.showLoading?.();
    try {
      const res = await postPayment(`/accounts-payable/vendor/${pay.vendor.id}/record-payment`, {
        payment_ref: ref,
        payment_mode_id: paymentModeId,
        amount: pay.amountNumber,
        comment: comment || undefined,
      });
      ctx.toast(res.message || "Payment recorded", "success");
      showPaymentDone({
        title: "Paid",
        party: partyWithCity(pay.vendor),
        amount: pay.amountNumber,
        receipt: ref || (res.id ? `#${res.id}` : ""),
        comment,
        mode: res.payment_mode || pay.modeName,
        againFn: "Finance.quickVendorPayment()",
      });
    } catch (e) { if (!e.cancelled) ctx.toast(e.message, "error"); }
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
        ${ctx.reviewRow(customer.kind === "agent" ? "Agent" : "Party", customer.kind === "agent" ? `${customer.business_name} · Agent` : partyWithCity(customer))}
      </div>
      ${collectDateHtml("quick-pay-date")}
      ${modeOpts}
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
    if (quickPayModes.length && !paymentModeId) return ctx.toast("Select the account", "error");
    if (!amount || amount <= 0) return ctx.toast("Enter a valid amount", "error");
    if (!valueDate) return ctx.toast("Enter collection date", "error");
    rememberCollectDate("quick-pay-date");
    ctx.showLoading?.();
    try {
      if (customer.kind === "agent") {
        const note = [ref, comment].filter(Boolean).join(" · ");
        await ctx.api(`/commission-agents/${customer.id}/payments`, {
          method: "POST",
          body: JSON.stringify({
            amount: String(amount),
            note: note || null,
            paid_on: valueDate,
            payment_mode_id: paymentModeId,
          }),
        });
        closeQuickPay();
        ctx.toast("Payment recorded on the agent", "success");
        showPaymentDone({
          title: "Collected",
          party: `${customer.business_name} · Agent`,
          amount,
          valueDate,
          receipt: ref,
          comment,
          mode: quickPayModes.find(m => m.id === paymentModeId)?.name || "Agent",
          againFn: "Finance.quickCustomerPayment()",
        });
        return;
      }
      const res = await postPayment(`/accounts-receivable/customer/${customer.id}/record-payment`, {
        payment_ref: ref || undefined,
        payment_mode_id: paymentModeId || undefined,
        amount,
        comment: comment || undefined,
        value_date: valueDate,
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
    } catch (e) { if (!e.cancelled) ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function quickAddExpense() {
    openExpenseForm();
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
    } else if (chip === "transport") {
      document.getElementById("finance-panel-transport")?.classList.remove("hidden");
      loadTransportBills();
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
    else if (activeChip === "transport") renderTransportBills();
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

