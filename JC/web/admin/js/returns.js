/** Customer returns — one return per customer, multi-bill lines, restock + AR credit */
const Returns = (() => {
  let ctx = null;
  let hubRows = [];
  let hubSearch = "";
  let detailCustomerId = null;
  let detailRows = [];
  let wizard = null;

  function init(appCtx) { ctx = appCtx; }

  function fmtPrice(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  async function showHub() {
    document.getElementById("returns-hub")?.classList.remove("hidden");
    document.getElementById("returns-detail")?.classList.add("hidden");
    detailCustomerId = null;
    ctx.showLoading?.();
    try {
      hubRows = await ctx.api("/customer-returns", {}, 0);
      renderHub();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally {
      ctx.hideLoading?.();
      App.updateGlobalBack?.();
    }
  }

  function setHubSearch(val) {
    hubSearch = val || "";
    renderHub();
  }

  function filteredHub() {
    return OrdersUI.filterAndRankParties(
      (hubRows || []).map(r => ({
        ...r,
        business_name: r.business_name || r.customer_label || "",
      })),
      hubSearch,
    );
  }

  function renderHub() {
    const el = document.getElementById("returns-list");
    if (!el) return;
    const caret = (typeof OrdersUI !== "undefined" && OrdersUI.captureSearchCaret)
      ? OrdersUI.captureSearchCaret("returns-hub-search") : null;
    const canWrite = !!ctx.canWrite?.("returns");
    const slot = document.getElementById("returns-search-slot");
    if (slot) {
      slot.innerHTML = hubRows.length
        ? HubUI.searchBar({
          id: "returns-hub-search",
          value: hubSearch,
          placeholder: "Search name, person, city…",
          oninput: "Returns.setHubSearch(this.value)",
        })
        : "";
      if (caret && typeof OrdersUI !== "undefined") OrdersUI.restoreSearchCaret("returns-hub-search", caret);
    }
    if (!hubRows.length) {
      el.innerHTML = HubUI.emptyState({
        title: "No returns yet",
        sub: "Create a return to restock and credit the customer.",
        ctaHtml: canWrite
          ? `<button class="btn btn-primary" data-require-write="returns" onclick="Returns.openCreate()">+ Create return</button>`
          : "",
      });
      return;
    }
    const rows = filteredHub();
    if (!rows.length) {
      el.innerHTML = HubUI.emptyState({ title: "No matches", sub: "Clear search." });
      return;
    }
    el.innerHTML = `<div class="ord-hub-list">${rows.map(r => HubUI.partyCard({
      title: r.customer_label,
      meta: `${r.return_count} return${r.return_count === 1 ? "" : "s"} · Credit <strong>${fmtPrice(r.credit_total)}</strong>${r.last_return_at ? ` · ${new Date(r.last_return_at).toLocaleString()}` : ""}`,
      pillHtml: HubUI.pill("Returns", "muted"),
      primaryLabel: "Open",
      primaryOnclick: `Returns.openDetail(${r.customer_id})`,
      rowOnclick: `Returns.openDetail(${r.customer_id})`,
      canWrite: true,
    })).join("")}</div>`;
  }

  async function openDetail(customerId) {
    detailCustomerId = customerId;
    document.getElementById("returns-hub")?.classList.add("hidden");
    document.getElementById("returns-detail")?.classList.remove("hidden");
    ctx.showLoading?.();
    try {
      detailRows = await ctx.api(`/customer-returns/customer/${customerId}`, {}, 0);
      const label = hubRows.find(r => r.customer_id === customerId)?.customer_label
        || detailRows[0]?.return_number && `Customer #${customerId}`
        || `Customer #${customerId}`;
      const title = document.getElementById("returns-detail-title");
      if (title) title.textContent = label;
      renderDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally {
      ctx.hideLoading?.();
      App.updateGlobalBack?.();
    }
  }

  function renderDetail() {
    const el = document.getElementById("returns-detail-body");
    if (!el) return;
    if (!detailRows.length) {
      const canWrite = !!ctx.canWrite?.("returns");
      el.innerHTML = HubUI.emptyState({
        title: "No returns for this customer",
        sub: "Create a return to credit AR and restock.",
        ctaHtml: canWrite
          ? `<button class="btn btn-primary" onclick="Returns.openCreate(${detailCustomerId})">+ Create return</button>`
          : "",
      });
      return;
    }
    el.innerHTML = `<div class="ord-hub-list">${detailRows.map(r => HubUI.partyCard({
      title: r.return_number,
      meta: `${r.total_quantity} qty · ${r.line_count} lines · Credit <strong>${fmtPrice(r.credit_amount)}</strong> · ${new Date(r.created_at).toLocaleString()}${r.notes ? `<div style="margin-top:2px;">${ctx.esc(r.notes)}</div>` : ""}`,
      pillHtml: HubUI.pill(fmtPrice(r.calculated_amount), "muted"),
      primaryLabel: "View",
      primaryOnclick: `Returns.openReturn(${r.id})`,
      moreItems: [
        { label: "Print", onclick: `Returns.openDoc(${r.id}, true)` },
      ],
      canWrite: true,
    })).join("")}</div>`;
  }

  async function openReturn(returnId) {
    ctx.showLoading?.();
    try {
      const d = await ctx.api(`/customer-returns/${returnId}`, {}, 0);
      const lines = (d.lines || []).map(ln => `
        <tr>
          <td>${ctx.esc(ln.our_product_id)}</td>
          <td>${ctx.esc(ln.bill_number)}</td>
          <td>${ln.quantity_returned}</td>
          <td>${fmtPrice(ln.sold_unit_price)}</td>
          <td>${fmtPrice(ln.line_calculated)}</td>
        </tr>`).join("");
      ctx.openDetail?.(d.return_number, `
        <div class="review-grid" style="margin-bottom:16px;">
          ${ctx.reviewRow("Customer", d.customer_label)}
          ${ctx.reviewRow("Calculated", fmtPrice(d.calculated_amount))}
          ${ctx.reviewRow("Credit (AR)", fmtPrice(d.credit_amount))}
          ${d.notes ? ctx.reviewRow("Notes", d.notes) : ""}
        </div>
        <table class="data"><thead><tr><th>Product</th><th>Bill</th><th>Qty</th><th>Sold</th><th>Amount</th></tr></thead>
        <tbody>${lines}</tbody></table>`,
        `<button class="btn btn-secondary" style="flex:1;" onclick="Returns.openDoc(${d.id}, true)">Print</button>
         <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Done</button>`, "md");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openDoc(returnId, print) {
    ctx.showLoading?.();
    try {
      const res = await ctx.api(`/customer-returns/${returnId}/document`, {}, 0);
      if (!res.document_url) throw new Error("document not available");
      const w = window.open(res.document_url, "_blank");
      if (print) setTimeout(() => { try { w?.print?.(); } catch (_) {} }, 800);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openCreate(preselectCustomerId) {
    if (!ctx.canWrite?.("returns")) return ctx.toast("No write access", "error");
    let customers = [];
    try { customers = await ctx.api("/customers", {}, 30000); } catch (_) {}
    wizard = {
      step: 1,
      customer_id: preselectCustomerId || null,
      customers,
      search: "",
      returnable: [],
      qtys: {},
      credit_amount: "",
      notes: "",
    };
    if (wizard.customer_id) await loadReturnable();
    else renderWizard();
  }

  function closeWizard() {
    wizard = null;
    document.getElementById("returns-wizard-modal")?.classList.add("hidden");
  }

  async function loadReturnable() {
    const cid = wizard?.customer_id;
    wizard.returnable = [];
    wizard.qtys = {};
    if (!cid) { renderWizard(); return; }
    ctx.showLoading?.();
    try {
      wizard.returnable = await ctx.api(`/customer-returns/customer/${cid}/returnable`, {}, 0);
      wizard.qtys = {};
      renderWizard();
    } catch (e) { ctx.toast(e.message, "error"); renderWizard(); }
    finally { ctx.hideLoading?.(); }
  }

  function pickCustomer(id) {
    wizard.customer_id = id || null;
    wizard.search = "";
    if (!id) { wizard.returnable = []; wizard.qtys = {}; renderWizard(); return; }
    loadReturnable();
  }

  function setWizardSearch(val) {
    if (!wizard) return;
    wizard.search = val || "";
    renderWizard();
  }

  async function onCustomerPick() {
    const sel = document.getElementById("ret-customer");
    const cid = parseInt(sel?.value || "0", 10);
    pickCustomer(cid || null);
  }

  function setQty(billLineId, val) {
    const n = Math.max(0, parseInt(val || "0", 10) || 0);
    const line = wizard.returnable.find(l => l.bill_line_id === billLineId);
    if (!line) return;
    wizard.qtys[billLineId] = Math.min(n, line.quantity_returnable);
    const calcEl = document.getElementById("ret-calc-hint");
    if (calcEl) calcEl.textContent = `Calculated: ${fmtPrice(calcTotal())}`;
  }

  function calcTotal() {
    let t = 0;
    for (const ln of wizard.returnable) {
      const q = wizard.qtys[ln.bill_line_id] || 0;
      if (q > 0) t += q * Number(ln.sold_unit_price);
    }
    return Math.round(t * 100) / 100;
  }

  function selectedLines() {
    return wizard.returnable
      .filter(ln => (wizard.qtys[ln.bill_line_id] || 0) > 0)
      .map(ln => ({
        bill_line_id: ln.bill_line_id,
        quantity: wizard.qtys[ln.bill_line_id],
        our_product_id: ln.our_product_id,
        bill_number: ln.bill_number,
        sold_unit_price: ln.sold_unit_price,
        line_calc: Math.round((wizard.qtys[ln.bill_line_id] * Number(ln.sold_unit_price)) * 100) / 100,
      }));
  }

  function next() {
    if (wizard.step === 1) {
      if (!wizard.customer_id) return ctx.toast("Pick customer", "error");
      if (!selectedLines().length) return ctx.toast("Enter return qty", "error");
      const calc = calcTotal();
      if (!wizard.credit_amount) wizard.credit_amount = String(calc);
      wizard.step = 2;
    } else if (wizard.step === 2) {
      const el = document.getElementById("ret-credit");
      const notesEl = document.getElementById("ret-notes");
      if (el) wizard.credit_amount = el.value;
      if (notesEl) wizard.notes = notesEl.value;
      const credit = parseFloat(wizard.credit_amount);
      if (!Number.isFinite(credit) || credit < 0) return ctx.toast("Enter credit amount", "error");
      wizard.step = 3;
    }
    renderWizard();
  }

  function back() {
    if (wizard.step > 1) wizard.step -= 1;
    renderWizard();
  }

  function renderWizard() {
    const modal = document.getElementById("returns-wizard-modal");
    const body = document.getElementById("returns-wizard-body");
    const footer = document.getElementById("returns-wizard-footer");
    const title = document.getElementById("returns-wizard-title");
    if (!modal || !body || !wizard) return;
    modal.classList.remove("hidden");

    if (wizard.step === 1) {
      if (title) title.textContent = "Create return — items";
      const caret = (typeof OrdersUI !== "undefined" && OrdersUI.captureSearchCaret)
        ? OrdersUI.captureSearchCaret("ret-cust-search") : null;
      const tokens = OrdersUI.partySearchTokens(wizard.search);
      const selected = wizard.customer_id
        ? (wizard.customers || []).find(c => c.id === wizard.customer_id)
        : null;
      const customers = OrdersUI.filterAndRankParties(
        (wizard.customers || []).filter(c => c.is_active !== false),
        wizard.search,
      ).slice(0, tokens.length ? 40 : 60);
      body.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>Select customer</h4>
          <p>Search business, person, city, or phone — middle / last name too.</p>
        </div>
        <div class="vo-wiz-search-wrap">
          <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
          <input id="ret-cust-search" class="input vo-wiz-search" type="search" placeholder="Search name, person, city…" value="${ctx.esc(wizard.search || "")}" oninput="Returns.setWizardSearch(this.value)" autocomplete="off" />
          ${wizard.search ? `<button type="button" class="vo-wiz-search-clear" onclick="Returns.setWizardSearch('')">×</button>` : ""}
        </div>
        ${selected ? `<div class="vo-wiz-selected-banner">
          <div>
            <span class="vo-wiz-selected-label">Selected</span>
            <strong>${ctx.esc(selected.business_name || ("#" + selected.id))}</strong>
            ${selected.person_name ? `<span class="vo-muted"> · ${ctx.esc(selected.person_name)}</span>` : ""}
            ${selected.city_name ? `<span class="vo-muted"> · ${ctx.esc(selected.city_name)}</span>` : ""}
          </div>
          <button type="button" class="btn btn-ghost btn-sm" onclick="Returns.pickCustomer(null)">Change</button>
        </div>` : ""}
        ${!wizard.customer_id ? `<div class="vo-wiz-vendor-list">
          ${customers.length ? customers.map(c => `
            <button type="button" class="vo-wiz-vendor-card" onclick="Returns.pickCustomer(${c.id})">
              <span class="vo-wiz-vendor-letter">${ctx.esc((c.business_name || "?").slice(0, 1).toUpperCase())}</span>
              <span class="vo-wiz-vendor-meta">
                <strong>${ctx.esc(c.business_name || "Customer")}</strong>
                <span>${c.person_name ? ctx.esc(c.person_name) + " · " : ""}${c.city_name ? ctx.esc(c.city_name) : "No city"}${c.phone ? ` · ${ctx.esc(c.phone)}` : ""}</span>
              </span>
              <span class="vo-wiz-vendor-check"></span>
            </button>`).join("") : HubUI.emptyState({
            title: "No matches",
            sub: tokens.length ? `No customer matches “${ctx.esc(wizard.search)}”.` : "No customers loaded.",
          })}
        </div>` : `
          ${!wizard.returnable.length ? `<p style="color:var(--muted);">No returnable billed items.</p>` : `
            <p style="font-size:13px;color:var(--muted);margin:0 0 10px;">Against billed qty only. Sold price includes discount.</p>
            <div class="card table-wrap">
              <table class="data"><thead><tr>
                <th>Product</th><th>Bill</th><th>Returnable</th><th>Sold</th><th>Return qty</th>
              </tr></thead><tbody>
                ${wizard.returnable.map(ln => `<tr>
                  <td><strong>${ctx.esc(ln.our_product_id)}</strong></td>
                  <td>${ctx.esc(ln.bill_number)}</td>
                  <td>${ln.quantity_returnable}</td>
                  <td>${fmtPrice(ln.sold_unit_price)}</td>
                  <td><input type="number" min="0" max="${ln.quantity_returnable}" class="input" style="width:80px;"
                    value="${wizard.qtys[ln.bill_line_id] || 0}"
                    onchange="Returns.setQty(${ln.bill_line_id}, this.value)"
                    oninput="Returns.setQty(${ln.bill_line_id}, this.value)" /></td>
                </tr>`).join("")}
              </tbody></table>
            </div>
            <p id="ret-calc-hint" style="margin-top:12px;font-weight:600;">Calculated: ${fmtPrice(calcTotal())}</p>
          `}
        `}`;
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="Returns.closeWizard()">Cancel</button>
        <button class="btn btn-primary" onclick="Returns.next()">Next</button>`;
      if (caret && typeof OrdersUI !== "undefined") OrdersUI.restoreSearchCaret("ret-cust-search", caret);
      else if (!wizard.customer_id) setTimeout(() => document.getElementById("ret-cust-search")?.focus(), 30);
    } else if (wizard.step === 2) {
      if (title) title.textContent = "Create return — credit";
      const calc = calcTotal();
      body.innerHTML = `
        <div class="review-block" style="margin-bottom:16px;">
          ${ctx.reviewRow("Calculated (qty × sold)", fmtPrice(calc))}
        </div>
        <label class="label">Credit amount (final AR) ₹</label>
        <input type="number" step="0.01" min="0" class="input" id="ret-credit" style="margin-bottom:12px;"
          value="${ctx.esc(String(wizard.credit_amount))}"
          onchange="Returns.wizard.credit_amount=this.value" oninput="Returns.wizard.credit_amount=this.value" />
        <p style="font-size:12px;color:var(--muted);margin:0 0 12px;">Edited amount becomes final AR credit, even if different from calculated.</p>
        <label class="label">Note (optional)</label>
        <textarea class="input" id="ret-notes" rows="3" onchange="Returns.wizard.notes=this.value" oninput="Returns.wizard.notes=this.value">${ctx.esc(wizard.notes || "")}</textarea>`;
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="Returns.back()">Back</button>
        <button class="btn btn-primary" onclick="Returns.next()">Review</button>`;
    } else {
      if (title) title.textContent = "Create return — review";
      const lines = selectedLines();
      const credit = parseFloat(wizard.credit_amount) || 0;
      body.innerHTML = `
        <div class="review-grid" style="margin-bottom:16px;">
          ${ctx.reviewRow("Calculated", fmtPrice(calcTotal()))}
          ${ctx.reviewRow("Credit (AR)", fmtPrice(credit))}
          ${wizard.notes ? ctx.reviewRow("Notes", wizard.notes) : ""}
        </div>
        <table class="data"><thead><tr><th>Product</th><th>Bill</th><th>Qty</th><th>Sold</th><th>Amount</th></tr></thead>
        <tbody>${lines.map(ln => `<tr>
          <td>${ctx.esc(ln.our_product_id)}</td>
          <td>${ctx.esc(ln.bill_number)}</td>
          <td>${ln.quantity}</td>
          <td>${fmtPrice(ln.sold_unit_price)}</td>
          <td>${fmtPrice(ln.line_calc)}</td>
        </tr>`).join("")}</tbody></table>
        <p style="margin-top:12px;font-size:13px;color:var(--muted);">Stock will restock. Credit note posts to AR.</p>`;
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="Returns.back()">Back</button>
        <button class="btn btn-primary" onclick="Returns.submit()">Submit return</button>`;
    }
  }

  async function submit() {
    if (!wizard?.customer_id) return;
    const credit = parseFloat(wizard.credit_amount);
    if (!Number.isFinite(credit) || credit < 0) return ctx.toast("Enter credit amount", "error");
    const lines = selectedLines().map(ln => ({ bill_line_id: ln.bill_line_id, quantity: ln.quantity }));
    ctx.showLoading?.();
    try {
      const res = await ctx.api("/customer-returns", {
        method: "POST",
        body: JSON.stringify({
          customer_id: wizard.customer_id,
          lines,
          credit_amount: credit,
          notes: (wizard.notes || "").trim() || null,
        }),
      });
      ctx.invalidateCache?.("/customer-returns");
      ctx.invalidateCache?.("/accounts-receivable");
      ctx.invalidateCache?.("/stock");
      closeWizard();
      ctx.toast(`Return ${res.return_number} created`, "success");
      const docBtns = [
        `<button class="btn btn-primary" style="flex:1;" onclick="Returns.openDoc(${res.id}, true)">Print</button>`,
        `<button class="btn btn-secondary" style="flex:1;" onclick="Returns.openDoc(${res.id}, false)">PDF</button>`,
      ];
      ctx.openDetail?.(res.return_number, `
        <p style="margin:0 0 12px;">Credit ${fmtPrice(res.credit_amount)} posted to AR. Stock restocked.</p>
        <div style="display:flex;gap:8px;">${docBtns.join("")}</div>`,
        `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Done</button>`, "sm");
      await showHub();
      if (detailCustomerId) await openDetail(detailCustomerId);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function openCreateFromDetail() {
    openCreate(detailCustomerId || undefined);
  }

  return {
    init, showHub, setHubSearch, openDetail, openCreate, openCreateFromDetail, closeWizard, onCustomerPick, pickCustomer, setWizardSearch, setQty, next, back, submit,
    openReturn, openDoc,
    get wizard() { return wizard; },
  };
})();
