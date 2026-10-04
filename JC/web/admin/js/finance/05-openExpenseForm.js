  function openExpenseForm() {
    const today = localToday();
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
    const modal = document.getElementById("expense-modal");
    modal?.classList.remove("hidden");
    const saveBtn = modal?.querySelector(".btn-primary");
    if (saveBtn) {
      saveBtn.textContent = "Save expense";
      saveBtn.setAttribute("onclick", "Finance.submitExpense()");
    }
  }

  function closeExpenseForm() { document.getElementById("expense-modal")?.classList.add("hidden"); }

  async function submitExpense() {
    if (saveBusy) return;
    const expense_date = document.getElementById("exp-date")?.value;
    const category = document.getElementById("exp-cat")?.value || "misc";
    const description = (document.getElementById("exp-desc")?.value || "").trim() || null;
    const amount = parseFloat(document.getElementById("exp-amount")?.value || "0");
    const reference = (document.getElementById("exp-ref")?.value || "").trim() || null;
    if (!expense_date || !amount || amount <= 0) return ctx.toast("Enter date and amount", "error");
    saveBusy = true;
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
    finally { saveBusy = false; ctx.hideLoading?.(); }
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
          ${newestFirst(freightLedger).map(r => {
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
              <td>${fmtDocDate(r.display_date || r.value_date || r.created_at)}</td>
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
