  function renderApStatement() {
    const bills = newestFirst(apDetail.bills);
    if (!bills.length) return OrdersUI.emptyState({ title: "No bills yet", sub: "Bills appear after you receive/bill vendor stock." });
    return `<div class="fin-stmt">${bills.map(b => {
      const open = expandedBillId === b.receipt_id;
      const dns = newestFirst(b.debit_notes);
      return `<div class="fin-bill-card ${open ? "is-open" : ""}">
        <button type="button" class="fin-bill-head" onclick="Finance.toggleBill(${b.receipt_id})">
          <div>
            <div class="fin-bill-title">${ctx.esc(b.display_name || b.bill_number || `Bill #${b.receipt_id}`)}</div>
            <div class="fin-bill-meta">${fmtDocDate(b.display_date || b.value_date || b.created_at)} · ${dns.length} correction${dns.length === 1 ? "" : "s"}</div>
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
              // Void reverses AP ledger history — admin-only server-side (same trust
              // boundary as every other void/purge). Edit is a routine correction and
              // stays at vendor_orders.write. These used to share one flag, so a
              // vendor_orders.write-but-not-admin staffer saw a live Void button here
              // that always 403'd (debit-notes.js's own voidFromList already splits
              // these correctly — this view just never matched it).
              const canEditDn = ctx.canWrite?.("vendor_orders") || ctx.isAdmin?.();
              const canVoidDn = ctx.isAdmin?.();
              return `<div class="fin-dn-row">
                <div><strong>${title}</strong>${d.notes ? `<div class="fin-dn-note">${ctx.esc(d.notes)}</div>` : ""}
                <div class="fin-muted">${fmtDocDate(d.display_date || d.value_date || d.created_at)}</div>
                ${(canEditDn || canVoidDn) && d.id ? `<div style="margin-top:6px;">
                  ${canEditDn ? `<button type="button" class="btn btn-ghost btn-sm" onclick="Finance.editDebitNote(${b.receipt_id},${d.id})">Edit</button>` : ""}
                  ${canVoidDn ? `<button type="button" class="btn btn-ghost btn-sm" onclick="Finance.voidDebitNote(${b.receipt_id},${d.id})">Void</button>` : ""}
                </div>` : ""}
                </div>
                <strong class="${effect < 0 ? "is-pos" : "is-neg"}">${fmtPrice(effect)}</strong>
              </div>`;
            }).join("")}
          </div>` : `<p class="fin-muted">No debit notes on this bill.</p>`}
          ${(ctx.canWrite?.("vendor_orders") || ctx.isAdmin?.()) ? `<div style="margin-top:12px;">
            <button type="button" class="btn btn-secondary btn-sm" onclick="Finance.addDebitNote(${b.receipt_id})">+ Bill correction</button>
          </div>` : ""}
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

  async function editDebitNote(receiptId, noteId) {
    await addDebitNote(receiptId);
    if (typeof DebitNotes !== "undefined" && DebitNotes.editFromList) {
      DebitNotes.editFromList(noteId);
    }
  }

  async function voidDebitNote(receiptId, noteId) {
    await addDebitNote(receiptId);
    if (typeof DebitNotes !== "undefined" && DebitNotes.voidFromList) {
      await DebitNotes.voidFromList(noteId);
    }
  }

  function renderApLedgerFlat() {
    return `<div class="card table-wrap">
      <table class="data"><thead><tr>
        <th>When</th><th>Type</th><th>Description</th><th>Amount</th><th>Balance</th>
      </tr></thead><tbody>
        ${newestFirst(apDetail.entries).map(e => `<tr class="clickable" onclick="Finance.openEntry(${e.id})">
          <td style="font-size:12px;">${fmtDocDate(e.display_date || e.value_date || e.created_at)}</td>
          <td>${ctx.esc(e.entry_type)}${e.status && e.status !== "open" ? ` <span class="badge badge-amber">${ctx.esc(e.status)}</span>` : ""}</td>
          <td>${ctx.esc(e.display_name || e.description)}</td>
          <td>${fmtPrice(e.signed_amount)}</td>
          <td><strong>${fmtPrice(e.running_balance)}</strong></td>
        </tr>`).join("")}
      </tbody></table>
    </div>`;
  }

  function renderApPayments() {
    const pays = newestFirst(apDetail.payments);
    if (!pays.length) return OrdersUI.emptyState({ title: "No payments yet", sub: "Pay above to record a payment." });
    return `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>When</th><th>Reference</th><th>Comment</th><th>Amount</th><th>Balance after</th><th></th>
    </tr></thead><tbody>
      ${pays.map(p => {
        const undone = !!p.reversed;
        return `<tr>
        <td style="font-size:12px;">${fmtDocDate(p.display_date || p.created_at)}</td>
        <td><strong>${ctx.esc(p.display_name || p.payment_ref || "—")}</strong>${undone ? ` <span class="badge badge-amber">Reversed</span>` : ""}</td>
        <td>${ctx.esc(p.payment_comment || "—")}</td>
        <td>${fmtPrice(p.signed_amount)}</td>
        <td>${fmtPrice(p.running_balance_after)}</td>
        <td style="white-space:nowrap;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;">
          ${p.payment_receipt_url ? `<a href="${ctx.esc(p.payment_receipt_url)}" target="_blank" class="btn btn-secondary btn-sm">Receipt</a>` : ""}
          ${!undone && ctx.can?.("ap.write") ? `<button type="button" class="btn btn-secondary btn-sm" onclick="Finance.editApPayment(${p.id})">Edit</button>` : ""}
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
        ${ctx.reviewRow("When", fmtDocDate(e.display_date || e.value_date || e.created_at))}
        ${e.status ? ctx.reviewRow("Status", e.status) : ""}
        ${ctx.reviewRow("By", e.created_by_name)}
      </div>${extra}`,
      `${e.entry_type === "payment" && !alreadyReversed && ctx.can?.("ap.write")
        ? `<button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail();Finance.editApPayment(${e.id})">Edit</button>` : ""}
       ${undoBtns}<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`, "md");
  }

  async function openSettle() {
    if (!apDetail) return;
    if (!ctx.isAdmin?.() && !ctx.can?.("ap.write")) return ctx.toast?.("Not permitted", "error");
    const outstanding = Number(apDetail.outstanding) || 0;
    const title = document.querySelector("#settle-modal h3");
    if (title) title.textContent = "Pay";
    const footerBtn = document.querySelector("#settle-modal .btn-primary");
    if (footerBtn) footerBtn.textContent = "Pay";
    let paymentModesLoadFailed = false;
    try {
      paymentModes = await ctx.api("/payment-modes?active_only=true", {}, 30000) || [];
    } catch (e) {
      paymentModes = [];
      paymentModesLoadFailed = true;
      ctx.toast?.(e.message || "Could not load payment modes", "error");
    }
    const modeOpts = paymentModesLoadFailed
      ? `<p style="font-size:13px;color:var(--danger);margin:0 0 12px;">Couldn't load payment modes — <a href="#" onclick="event.preventDefault();Finance.openSettle()">retry</a>. You can still pay; you'll be asked for a mode if one is required.</p>`
      : paymentModes.length
      ? `<label class="label">Payment mode</label>
        <select class="input" id="settle-mode" style="margin-bottom:12px;width:100%;">
          <option value="">— Select mode —</option>
          ${paymentModes.map(m => `<option value="${m.id}">${ctx.esc(m.name)}</option>`).join("")}
        </select>
        <p style="font-size:12px;color:var(--muted);margin:-4px 0 12px;">Add modes in Setup → Payment Modes.</p>`
      : `<p style="font-size:13px;color:var(--muted);margin:0 0 12px;">No payment modes yet — <button type="button" class="btn btn-ghost btn-sm" onclick="Finance.closeSettle();App.showView('setup');App.showSetupTab('paymodes')">add in Setup</button></p>`;
    document.getElementById("settle-body").innerHTML = `
      <div class="review-block" style="margin-bottom:16px;">
        ${ctx.reviewRow("Vendor", apDetail.vendor_label)}
        ${ctx.reviewRow("Due", fmtPrice(outstanding))}
      </div>
      ${modeOpts}
      <label class="label">Payment reference / ID</label>
      <input class="input" id="settle-ref" style="margin-bottom:12px;" placeholder="UTR, cheque #, etc." />
      <label class="label">Payment date</label>
      <input type="date" class="input" id="settle-date" value="${ctx.esc(localToday())}" required style="margin-bottom:12px;" />
      <label class="label">Amount (₹)</label>
      <input type="number" step="0.01" class="input" id="settle-amount" value="" placeholder="Enter amount" style="margin-bottom:8px;" oninput="Finance.onApSettleAmount()" />
      <p id="settle-over-hint" class="hidden" style="font-size:12px;color:var(--muted);margin:0 0 12px;">Extra will sit as credit on this vendor.</p>
      <label class="label">Comment (optional)</label>
      <input class="input" id="settle-comment" style="margin-bottom:12px;" />
      <label class="label">Upload payment receipt (optional)</label>
      <input type="file" class="input" accept=".pdf,image/*" onchange="Finance.setSettleFile(this.files[0])" />
      <span id="settle-file-label" style="font-size:12px;color:var(--muted);"></span>`;
    document.getElementById("settle-modal").classList.remove("hidden");
    settleFile = null;
  }

  function onApSettleAmount() {
    const due = Number(apDetail?.outstanding) || 0;
    const amount = parseFloat(document.getElementById("settle-amount")?.value || "0");
    const hint = document.getElementById("settle-over-hint");
    if (hint) hint.classList.toggle("hidden", !(due > 0 && amount > due));
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
    const modeRaw = document.getElementById("settle-mode")?.value || "";
    const payment_mode_id = modeRaw ? parseInt(modeRaw, 10) : null;
    if (paymentModes.length && !payment_mode_id) return ctx.toast("Select payment mode", "error");
    if (!ref) return ctx.toast("Enter payment reference", "error");
    if (!amount || amount <= 0) return ctx.toast("Enter valid amount", "error");
    const valueDate = (document.getElementById("settle-date")?.value || "").trim();
    if (!valueDate) return ctx.toast("Enter payment date", "error");
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
      const body = { payment_ref: ref, amount, payment_receipt_key: key, comment, value_date: valueDate };
      if (payment_mode_id) body.payment_mode_id = payment_mode_id;
      const saved = await ctx.api(`/accounts-payable/vendor/${currentVendor}/settle`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      ctx.invalidateCache?.("/accounts-payable");
      ctx.invalidateCache?.("/finance");
      closeSettle();
      ctx.toast("Paid", "success");
      await openVendorAp(vid);
      const bal = Number(apDetail?.outstanding) || 0;
      const modeName = paymentModes.find(m => m.id === payment_mode_id)?.name || saved?.payment_mode || "";
      settleSuccess({
        title: "Paid",
        party,
        amount,
        balanceAfter: bal,
        valueDate,
        receipt: ref || (saved?.id ? `#${saved.id}` : ""),
        comment: comment || "",
        mode: modeName,
        reopenFn: `Finance.openVendorAp(${vid})`,
      });
      loadApList();
      loadOverviewSilent();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function showApFromVendor(vendorId) {
    if (!ctx.isAdmin?.() && !ctx.can?.("ap.read")) return ctx.toast?.("Not permitted", "error");
    App.closeDetail?.();
    ctx.showView?.("money");
    openVendorAp(vendorId);
  }

  function showArFromCustomer(customerId) {
    if (!ctx.isAdmin?.() && !ctx.can?.("ar.read")) return ctx.toast?.("Not permitted", "error");
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
    if (!showSettled && !hubSearch.trim()) list = list.filter(c => Number(c.outstanding) > 0);
    const dueCustomers = customers.filter(c => Number(c.outstanding) > 0);
    const barCustomers = hubSearch.trim() ? list.filter(c => Number(c.outstanding) > 0) : dueCustomers;
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
          ${barCustomers.length ? hBarList(barCustomers.slice(0, 5), "customer_label", "outstanding") : ""}
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
    if (!ctx.isAdmin?.() && !ctx.can?.("ar.read")) return ctx.toast?.("Not permitted", "error");
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
    const dueLine = outstanding > 0
      ? `${fmtPrice(outstanding)} due`
      : outstanding < 0
        ? `Credit ${fmtPrice(Math.abs(outstanding))}`
        : "Clear";
    if (hero) {
      hero.innerHTML = HubUI.pageHero({
        title: arDetail.customer_label,
        sub: `Collect · ${dueLine}`,
        actionsHtml: `
            ${(ctx.isAdmin?.() || ctx.can?.("ar.write")) ? `<button class="btn btn-primary" onclick="Finance.openArSettle()">Collect</button>` : ""}
            <button class="btn btn-secondary" onclick="Finance.shareArStatement()">Print / PDF / WA</button>
            ${ctx.isAdmin?.() ? `<button class="btn btn-secondary" onclick="Finance.setArOpeningBalance()">Set opening</button>` : ""}
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
      <p style="color:var(--muted);font-size:13px;margin:0 0 16px;">Tally start they owed. Use 0 to clear. Negative = they had a credit as of this date. Not Due (Due = opening + bills − collected).</p>
      <label class="label">Opening (₹)</label>
      <input type="number" step="0.01" class="input" id="ar-ob-amt" value="${ctx.esc(arDetail.opening_total || "0")}" style="margin-bottom:12px;" />
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
    // AR opening balance is signed (positive = customer owes us, negative = we owe
    // them a starting credit) — the backend schema/service fully support negative
    // here (unlike AP's opening balance, which is genuinely non-negative-only), so
    // don't floor it at 0.
    if (!Number.isFinite(amount)) return ctx.toast("Enter a valid amount", "error");
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

