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

  function setRealEntriesOnly(on) {
    realEntriesOnly = !!on;
    renderArDetail?.();
    renderApDetail?.();
  }

  function realEntriesBar() {
    return `<label style="display:inline-flex;gap:6px;align-items:center;margin:0 0 12px;font-size:13px;">
      <input type="checkbox" ${realEntriesOnly ? "checked" : ""} onchange="Finance.setRealEntriesOnly(this.checked)" />
      Real entries only
    </label>`;
  }

  function moneyEntryIsVoid(e) {
    const status = String(e.status || "").toLowerCase();
    if (status === "voided" || status === "cancelled") return true;
    const type = String(e.entry_type || "").toLowerCase();
    if (type.includes("reversal")) return true;
    if (e.reversed) return true;
    const title = String(e.display_name || e.description || "").toLowerCase();
    if (title.startsWith("cancelled") || title.startsWith("void")) return true;
    return false;
  }

  function liveMoneyEntries(entries) {
    const list = entries || [];
    if (!realEntriesOnly) return list;
    const reversed = new Set();
    for (const e of list) {
      if (e.reverses_entry_id) reversed.add(e.reverses_entry_id);
    }
    const kept = list.filter(e => !moneyEntryIsVoid(e) && !reversed.has(e.id));
    const chrono = [...kept].sort((a, b) => {
      const da = String(a.value_date || a.created_at || "");
      const db = String(b.value_date || b.created_at || "");
      if (da !== db) return da < db ? -1 : 1;
      return (Number(a.id) || 0) - (Number(b.id) || 0);
    });
    let run = 0;
    const stamped = new Map();
    for (const e of chrono) {
      run += Number(e.signed_amount ?? e.amount ?? 0);
      stamped.set(e.id, Math.round(run * 100) / 100);
    }
    return kept.map(e => stamped.has(e.id) ? { ...e, running_balance: stamped.get(e.id) } : e);
  }

  function renderArStatement() {
    const bills = newestFirst(liveMoneyEntries(arDetail.entries).filter(e => e.entry_type === "bill" || e.entry_type === "credit_note" || e.entry_type === "opening_balance"));
    if (!bills.length) return OrdersUI.emptyState({ title: "No bills yet", sub: "Bills appear after you process customer orders." });
    return `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>When</th><th>Type</th><th>Description</th><th>Amount</th><th>Balance</th>
    </tr></thead><tbody>
      ${bills.map(e => {
        const badgeCls = e.entry_type === "credit_note" ? "badge-green" : e.entry_type === "opening_balance" ? "badge-blue" : "badge-amber";
        const typeLabel = e.entry_type === "opening_balance" ? "Opening" : e.entry_type === "credit_note" ? "Credit Note" : "Bill";
        return `<tr>
        <td style="font-size:12px;">${fmtDocDate(e.display_date || e.value_date || e.created_at)}</td>
        <td><span class="badge ${badgeCls}">${typeLabel}</span></td>
        <td>${ctx.esc(e.display_name || e.description)}${e.return_id ? ` <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();Returns.openReturn(${e.return_id})">View</button>` : ""}</td>
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
        ${newestFirst(liveMoneyEntries(arDetail.entries)).map(e => {
          const badgeCls = e.entry_type === "credit_note" ? "badge-green" : e.entry_type === "opening_balance" ? "badge-blue" : e.entry_type === "bill" ? "badge-amber" : e.entry_type === "payment_reversal" ? "badge-red" : "badge-green";
          const typeLabel = { bill: "Bill", credit_note: "Credit Note", opening_balance: "Opening", payment: "Payment", payment_reversal: "Reversal" }[e.entry_type] || e.entry_type;
          return `<tr>
          <td style="font-size:12px;">${fmtDocDate(e.display_date || e.value_date || e.created_at)}</td>
          <td><span class="badge ${badgeCls}">${typeLabel}</span></td>
          <td>${ctx.esc(e.display_name || e.description)}${e.return_id ? ` <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();Returns.openReturn(${e.return_id})">View</button>` : ""}</td>
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
    const entries = liveMoneyEntries(arDetail.entries);
    const reversed = reversedPaymentIds(arDetail.entries || []);
    const pays = newestFirst(entries.filter(e => e.entry_type === "payment" || e.entry_type === "payment_reversal"));
    if (!pays.length) return OrdersUI.emptyState({ title: "No payments yet", sub: "Collect above when cash comes in." });
    return `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>When</th><th>Reference</th><th>Comment</th><th>Amount</th><th>Balance</th><th></th>
    </tr></thead><tbody>
      ${pays.map(p => {
        const isRev = p.entry_type === "payment_reversal";
        const undone = reversed.has(p.id);
        return `<tr>
        <td style="font-size:12px;">${fmtDocDate(p.display_date || p.value_date || p.created_at)}</td>
        <td><strong>${ctx.esc(p.display_name || p.payment_ref || "—")}</strong>
          ${isRev ? ` <span class="badge badge-amber">Reversal</span>` : ""}
          ${undone ? ` <span class="badge badge-amber">Reversed</span>` : ""}
        </td>
        <td>${ctx.esc(p.payment_comment || p.description || "—")}</td>
        <td>${fmtPrice(p.signed_amount)}</td>
        <td>${fmtPrice(p.running_balance)}</td>
        <td style="white-space:nowrap;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;">
          ${!isRev && !undone && ctx.can?.("ar.write") ? `<button type="button" class="btn btn-secondary btn-sm" onclick="Finance.editArPayment(${p.id})">Edit</button>` : ""}
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
    if (!ctx.isAdmin?.() && !ctx.can?.("ar.write")) return ctx.toast?.("Not permitted", "error");
    const outstanding = Number(arDetail.outstanding) || 0;
    let paymentModesLoadFailed = false;
    try {
      paymentModes = await ctx.api("/payment-modes?active_only=true", {}, 30000) || [];
    } catch (e) {
      paymentModes = [];
      paymentModesLoadFailed = true;
      ctx.toast?.(e.message || "Could not load payment modes", "error");
    }
    const modeOpts = paymentModesLoadFailed
      ? `<p style="font-size:13px;color:var(--danger);margin:0 0 12px;">Couldn't load payment modes — <a href="#" onclick="event.preventDefault();Finance.openArSettle()">retry</a>. You can still collect; you'll be asked for a mode if one is required.</p>`
      : paymentModes.length
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
        ${ctx.reviewRow(outstanding < 0 ? "Credit" : "Due", outstanding < 0 ? fmtPrice(Math.abs(outstanding)) : fmtPrice(outstanding))}
      </div>
      ${modeOpts}
      <label class="label">Collection date</label>
      <input type="date" class="input" id="ar-settle-date" value="${ctx.esc(localToday())}" required style="margin-bottom:12px;" />
      <label class="label">Amount (₹)</label>
      <input type="number" step="0.01" class="input" id="ar-settle-amount" value="" placeholder="Enter amount" style="margin-bottom:8px;" oninput="Finance.onArSettleAmount()" />
      <p id="ar-settle-over-hint" class="hidden" style="font-size:12px;color:var(--muted);margin:0 0 12px;">Extra will sit as credit on this customer.</p>
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

  function onArSettleAmount() {
    const due = Number(arDetail?.outstanding) || 0;
    const amount = parseFloat(document.getElementById("ar-settle-amount")?.value || "0");
    const hint = document.getElementById("ar-settle-over-hint");
    if (!hint) return;
    const createsCredit = amount > 0 && (due <= 0 || amount > due);
    hint.classList.toggle("hidden", !createsCredit);
    if (!createsCredit) return;
    hint.textContent = due > 0
      ? "Extra will sit as credit on this customer."
      : "Nothing is due — this amount will sit as credit.";
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
    const valueDate = (document.getElementById("ar-settle-date")?.value || "").trim();
    if (!valueDate) return ctx.toast("Enter collection date", "error");
    const party = arDetail.customer_label;
    const cid = currentCustomer;
    ctx.showLoading?.();
    try {
      const body = { amount, comment, payment_ref: ref || null, value_date: valueDate };
      if (payment_mode_id) body.payment_mode_id = payment_mode_id;
      const saved = await ctx.api(`/accounts-receivable/customer/${currentCustomer}/settle`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      ctx.invalidateCache?.("/accounts-receivable");
      ctx.invalidateCache?.("/finance");
      closeArSettle();
      ctx.toast("Collected", "success");
      await openCustomerAr(cid);
      const modeName = paymentModes.find(m => m.id === payment_mode_id)?.name || saved?.payment_mode || "";
      settleSuccess({
        title: "Collected",
        party,
        amount,
        balanceAfter: Number(arDetail?.outstanding) || 0,
        valueDate,
        receipt: ref || (saved?.id ? `#${saved.id}` : saved?.payment_ref || ""),
        comment: comment || saved?.payment_comment || "",
        mode: modeName,
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
      <label class="fin-exp-field"><span>Head</span>
        <select class="input" id="fin-exp-cat" onchange="Finance.onExpenseFilterChange()">
          <option value="">All</option>
          ${expenseCategoryOptions().map(c =>
            `<option value="${ctx.esc(c)}" ${expenseFilters.category === c ? "selected" : ""}>${ctx.esc(c)}</option>`).join("")}
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
        <td>${fmtDocDate(e.display_date || e.expense_date)}</td>
        <td>${ctx.esc(e.display_name || e.category)}${e.is_cash === false ? ` <span class="badge">Stock</span>` : ""}</td>
        <td>${ctx.esc(e.description || "—")}</td>
        <td>${fmtPrice(e.amount)}</td>
        <td>${ctx.esc(e.reference || "—")}</td>
        <td style="white-space:nowrap;display:flex;gap:6px;justify-content:flex-end;">
          ${e.is_cash === false ? `<span class="fin-muted">Void the journal</span>` : `
          ${ctx.can?.("finance.write") ? `<button class="btn btn-secondary btn-sm" onclick="Finance.editExpense(${e.id})">Edit</button>` : ""}
          ${e.freight_agent_id
            ? `<span class="fin-muted">Freight</span>`
            : (ctx.isAdmin?.() ? `<button class="btn btn-ghost btn-sm" onclick="Finance.deleteExpense(${e.id})">Delete</button>` : "")}`}
        </td>
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

  function editExpense(id) {
    fillExpenseForm(expenses.find(x => x.id === id) || null, id);
  }

  async function saveExpenseEdit(id) {
    if (saveBusy) return;
    const payload = expensePayload();
    if (!payload) return;
    const { expense_date, description, amount, reference, subhead_id } = payload;
    saveBusy = true;
    ctx.showLoading?.();
    try {
      await ctx.api(`/expenses/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ expense_date, description, amount, reference, subhead_id }),
      });
      ctx.invalidateCache?.("/expenses");
      ctx.invalidateCache?.("/finance");
      closeExpenseForm();
      ctx.toast("Expense updated", "success");
      await loadExpenses();
      loadOverviewSilent();
    } catch (err) { ctx.toast(err.message, "error"); }
    finally { saveBusy = false; ctx.hideLoading?.(); }
  }

  function editApPayment(entryId) {
    const e = (apDetail?.payments || []).find(x => x.id === entryId)
      || (apDetail?.entries || []).find(x => x.id === entryId);
    if (!e) return;
    const amt = Math.abs(Number(e.amount || e.signed_amount || 0));
    const day = docDateIso(e.display_date || e.value_date) || localToday();
    ctx.openDetail("Edit payment", `
      <label class="label">Amount (₹)</label>
      <input type="number" step="0.01" min="0.01" class="input" id="pay-edit-amt" value="${ctx.esc(String(amt))}" style="margin-bottom:12px;" />
      <label class="label">Value date</label>
      <input type="date" class="input" id="pay-edit-date" value="${ctx.esc(day)}" style="margin-bottom:12px;" />
      <label class="label">Payment mode</label>
      <input class="input" id="pay-edit-mode" value="${ctx.esc(e.payment_mode || "")}" style="margin-bottom:12px;" />
      <label class="label">Description</label>
      <input class="input" id="pay-edit-desc" value="${ctx.esc(e.description || e.payment_comment || "")}" />
    `, `
      <button class="btn btn-secondary" onclick="App.closeDetail()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Finance.saveApPaymentEdit(${entryId})">Save</button>
    `, "sm");
  }

  async function saveApPaymentEdit(entryId) {
    if (saveBusy) return;
    const amount = parseFloat(document.getElementById("pay-edit-amt")?.value || "0");
    const value_date = document.getElementById("pay-edit-date")?.value || null;
    const payment_mode = (document.getElementById("pay-edit-mode")?.value || "").trim() || null;
    const description = (document.getElementById("pay-edit-desc")?.value || "").trim() || null;
    if (!amount || amount <= 0) return ctx.toast("Enter a valid amount", "error");
    const vid = currentVendor;
    saveBusy = true;
    ctx.showLoading?.();
    try {
      await ctx.api(`/accounts-payable/payments/${entryId}`, {
        method: "PATCH",
        body: JSON.stringify({ amount, value_date, payment_mode, description }),
      });
      ctx.invalidateCache?.("/accounts-payable");
      ctx.invalidateCache?.("/finance");
      ctx.toast("Payment updated", "success");
      App.closeDetail?.();
      if (vid) await openVendorAp(vid);
      loadOverviewSilent();
    } catch (err) { ctx.toast(err.message, "error"); }
    finally { saveBusy = false; ctx.hideLoading?.(); }
  }

  function editArPayment(entryId) {
    const e = (arDetail?.entries || []).find(x => x.id === entryId);
    if (!e || e.entry_type !== "payment") return;
    const amt = Math.abs(Number(e.amount || e.signed_amount || 0));
    const day = docDateIso(e.display_date || e.value_date) || localToday();
    ctx.openDetail("Edit payment", `
      <label class="label">Amount (₹)</label>
      <input type="number" step="0.01" min="0.01" class="input" id="pay-edit-amt" value="${ctx.esc(String(amt))}" style="margin-bottom:12px;" />
      <label class="label">Value date</label>
      <input type="date" class="input" id="pay-edit-date" value="${ctx.esc(day)}" style="margin-bottom:12px;" />
      <label class="label">Payment mode</label>
      <input class="input" id="pay-edit-mode" value="${ctx.esc(e.payment_mode || "")}" style="margin-bottom:12px;" />
      <label class="label">Description</label>
      <input class="input" id="pay-edit-desc" value="${ctx.esc(e.description || e.payment_comment || "")}" />
    `, `
      <button class="btn btn-secondary" onclick="App.closeDetail()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Finance.saveArPaymentEdit(${entryId})">Save</button>
    `, "sm");
  }

  async function saveArPaymentEdit(entryId) {
    if (saveBusy) return;
    const amount = parseFloat(document.getElementById("pay-edit-amt")?.value || "0");
    const value_date = document.getElementById("pay-edit-date")?.value || null;
    const payment_mode = (document.getElementById("pay-edit-mode")?.value || "").trim() || null;
    const description = (document.getElementById("pay-edit-desc")?.value || "").trim() || null;
    if (!amount || amount <= 0) return ctx.toast("Enter a valid amount", "error");
    const cid = currentCustomer;
    saveBusy = true;
    ctx.showLoading?.();
    try {
      await ctx.api(`/accounts-receivable/payments/${entryId}`, {
        method: "PATCH",
        body: JSON.stringify({ amount, value_date, payment_mode, description }),
      });
      ctx.invalidateCache?.("/accounts-receivable");
      ctx.invalidateCache?.("/finance");
      ctx.toast("Payment updated", "success");
      App.closeDetail?.();
      if (cid) await openCustomerAr(cid);
      loadOverviewSilent();
    } catch (err) { ctx.toast(err.message, "error"); }
    finally { saveBusy = false; ctx.hideLoading?.(); }
  }

