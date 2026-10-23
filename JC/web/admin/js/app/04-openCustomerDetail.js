  async function openCustomerDetail(id, opts = {}) {
    const c = await api(`/customers/${id}`);
    detailMode = "customer"; detailId = id;
    customerLedgerExpanded = null;
    customerAr = null;
    customerLedger = [];
    let tab = opts.tab || "activity";
    if (tab === "orders" || tab === "money" || tab === "returns") tab = "activity";
    const body = `
      <div class="profile-hero" style="margin:-24px -24px 16px;border-radius:0;">
        <h2>${c.party_number ? `<span style="color:var(--muted);font-size:16px;font-weight:600;margin-right:6px;">#${c.party_number}</span>` : ""}${esc(c.business_name)}${!c.is_active && !c.deleted_at ? ' <span class="badge badge-amber" style="font-size:13px;vertical-align:middle;">Inactive</span>' : ""}${c.deleted_at ? ' <span class="badge badge-red" style="font-size:13px;vertical-align:middle;">Deleted</span>' : ""}</h2>
        <p>${esc(c.person_name || "No contact person")}</p>
        <div class="profile-meta">
          <span class="badge badge-blue">${esc(c.phone)}</span>
          ${c.alias ? `<span class="badge badge-gray">${esc(c.alias)}</span>` : ""}
          ${c.city_name ? `<span class="badge badge-green">${esc(c.city_name)}</span>` : ""}
          ${c.route_name ? `<span class="badge badge-gray">${esc(c.route_name)}</span>` : ""}
          ${c.marker_1 ? `<span class="badge badge-blue">${esc(c.marker_1)}</span>` : ""}
          ${c.marker_2 ? `<span class="badge badge-amber">${esc(c.marker_2)}</span>` : ""}
          ${getOtherNotes(c) ? `<span class="badge badge-green">${esc(getOtherNotes(c))}</span>` : ""}
          ${c.payment_type === "CASH" && ![(c.marker_1||""),(c.marker_2||""),getOtherNotes(c)].join(" ").toUpperCase().includes("CASH") ? `<span class="badge badge-amber">CASH</span>` : ""}
        </div>
        ${(c.outstanding_balance !== null && c.outstanding_balance !== undefined) ? `
        <div class="credit-summary" style="margin-top:12px;display:flex;gap:16px;flex-wrap:wrap;">
          <div class="credit-stat"><span class="credit-label">Outstanding</span><span class="credit-val ${Number(c.outstanding_balance)>0?'text-danger':Number(c.outstanding_balance)<0?'text-success':''}">${fmtPersonMoney(c.outstanding_balance)}</span></div>
          <div class="credit-stat"><span class="credit-label">Credit Limit</span><span class="credit-val">${c.credit_limit !== null && c.credit_limit !== undefined ? "₹" + Number(c.credit_limit).toLocaleString("en-IN") : "₹0"}</span></div>
          <div class="credit-stat"><span class="credit-label">Available</span><span class="credit-val ${Number(c.available_credit)<0?'text-danger':'text-success'}">${fmtPersonMoney(c.available_credit)}</span></div>
        </div>` : ""}
      </div>
      <div class="ord-mode-toggle" role="tablist" style="margin-bottom:16px;">
        <button type="button" class="ord-mode-btn ${tab === "activity" ? "active" : ""}" onclick="App.openCustomerDetail(${c.id},{tab:'activity'})">Activity</button>
        <button type="button" class="ord-mode-btn ${tab === "profile" ? "active" : ""}" onclick="App.openCustomerDetail(${c.id},{tab:'profile'})">Profile</button>
      </div>
      <div id="customer-workspace">
        ${tab === "activity" ? `
          <div id="customer-summary-wrap" class="person-summary"></div>
          <div id="customer-actions-wrap" class="person-actions"></div>
          <div id="customer-ledger-wrap"><p style="color:var(--muted);font-size:13px;">Loading activity…</p></div>
        ` : ""}
        ${tab === "profile" ? `
          <div class="review-grid">
            ${reviewRow("Secondary Phone", c.secondary_phone)}
            ${reviewRow("GST Number", c.gst_number)}
            ${reviewRow("Address", c.address)}
            ${reviewRow("Additional details", c.additional_details)}
            ${reviewRow("Credit Limit", c.credit_limit !== null && c.credit_limit !== undefined ? "₹" + Number(c.credit_limit).toLocaleString("en-IN") : "₹0")}
            ${reviewRow("Available Credit", c.available_credit !== null && c.available_credit !== undefined ? fmtPersonMoney(c.available_credit) : "—")}
            ${reviewRow("Outstanding (AR)", c.outstanding_balance !== null && c.outstanding_balance !== undefined ? fmtPersonMoney(c.outstanding_balance) : "—")}
            ${reviewRow("Credit Override", c.credit_override ? "Allowed" : "Not allowed")}
            ${reviewRow("Opening", c.opening_balance_due ? fmtPersonMoney(c.opening_balance_due) : "—")}
            ${reviewRow("Opening as on", c.opening_balance_as_on || "—")}
            ${reviewRow("Status", c.deleted_at ? "Deleted" : c.is_active ? "Active" : "Inactive")}
            ${reviewRow("Password", "Unique — sent on WhatsApp")}
            ${reviewRow("Created", fmtDate(c.created_at))}
            ${reviewRow("Last Updated", fmtDate(c.updated_at))}
          </div>
          ${changeHistoryTable(c.change_history)}
        ` : ""}
      </div>`;
    const footerBtns = [];
    if (canWrite("customers")) {
      if (c.deleted_at) {
        // In recycle bin → restore only
        footerBtns.push(`<button class="btn btn-primary btn-sm" onclick="App.restoreCustomer(${c.id})">Restore</button>`);
      } else if (!c.is_active) {
        // Inactive → edit + restore to active + delete
        footerBtns.push(`<button class="btn btn-secondary btn-sm" onclick="App.openCustomerEdit(${c.id})">Edit</button>`);
        footerBtns.push(`<button class="btn btn-primary btn-sm" onclick="App.toggleCustomerActive(${c.id}, true)">Make Active</button>`);
        footerBtns.push(`<button class="btn btn-danger btn-sm" onclick="App.deleteCustomer(${c.id})">Delete</button>`);
      } else {
        // Active → mark inactive + delete + edit
        footerBtns.push(`<button class="btn btn-secondary btn-sm" onclick="App.toggleCustomerActive(${c.id}, false)">Mark Inactive</button>`);
        footerBtns.push(`<button class="btn btn-danger btn-sm" onclick="App.deleteCustomer(${c.id})">Delete</button>`);
        footerBtns.push(`<button class="btn btn-secondary btn-sm" onclick="App.openCustomerEdit(${c.id})">Edit</button>`);
        footerBtns.push(`<button class="btn btn-secondary" onclick="App.sendCredentials(${c.id})">Send login</button>`);
      }
    }
    footerBtns.push(`<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`);
    openDetail(c.business_name, body, footerBtns.join(""), "lg");
    if (tab === "activity") await refreshCustomerLedger(id);
  }

  function renderCustomerActions(id, openingDue, openingAsOn) {
    const el = document.getElementById("customer-actions-wrap");
    if (!el) return;
    const canSell = canWrite("customer_orders");
    const canSeeAr = isAdmin() || can("ar.read");
    const canCollectAr = isAdmin() || can("ar.write");
    const due = canSeeAr && customerAr && Number(customerAr.outstanding) > 0;
    const bits = [];
    // Everyday jobs: phone/offline order + bill + their order list.
    if (canSell) {
      bits.push(`<button class="btn btn-primary btn-sm" onclick="App.createCustomerOrder(${id})">Order</button>`);
      if (!orderTaker()) {
        bits.push(`<button class="btn btn-secondary btn-sm" onclick="App.billCustomer(${id})">Bill</button>`);
        bits.push(`<button class="btn btn-secondary btn-sm" onclick="App.openSelling(${id})">Orders</button>`);
      }
    }
    if (canSeeAr) {
      bits.push(`<button class="btn btn-secondary btn-sm" onclick="App.showCustomerMoneyLedger(${id})">Ledger</button>`);
    }
    if (due && canCollectAr) {
      bits.push(`<button class="btn btn-secondary btn-sm" onclick="App.collectCustomer(${id})">Collect</button>`);
    }
    const more = [];
    if (canSell && !orderTaker()) {
      more.push(`<button type="button" onclick="App.closeDetail();App.showView('returns');Returns.openCreate?.(${id})">Return</button>`);
    }
    if (canCollectAr && !due) more.push(`<button type="button" onclick="App.collectCustomer(${id})">Collect</button>`);
    if (canSeeAr) more.push(`<button type="button" onclick="App.openCustomerMoney(${id})">Money statement</button>`);
    if (isAdmin()) {
      more.push(`<button type="button" onclick="App.setCustomerOpeningBalance(${id}, '${esc(openingDue || "")}', '${esc(openingAsOn || "")}')">Opening</button>`);
    }
    if (more.length) {
      bits.push(`<details class="person-more"><summary>More</summary><div class="person-more-menu">${more.join("")}</div></details>`);
    }
    el.innerHTML = bits.join("") || "";
  }

  async function refreshCustomerLedger(id) {
    const wrap = document.getElementById("customer-ledger-wrap");
    const sumWrap = document.getElementById("customer-summary-wrap");
    try {
      const [ledgerRes, ar, cust] = await Promise.all([
        api(`/customers/${id}/ledger`, {}, 0),
        (isAdmin() || can("ar.read")) ? api(`/accounts-receivable/customer/${id}`, {}, 0).catch(() => null) : Promise.resolve(null),
        api(`/customers/${id}`, {}, 0).catch(() => null),
      ]);
      customerLedger = ledgerRes.items || [];
      customerAr = ar;
      if (sumWrap) {
        if (ar) {
          sumWrap.innerHTML = `<div class="person-summary-grid">
            <div><span class="person-summary-label">Due</span><strong>${fmtPersonMoney(ar.outstanding)}</strong></div>
            <div><span class="person-summary-label">Opening</span><strong>${fmtPersonMoney(ar.opening_total || "0")}</strong></div>
            <div><span class="person-summary-label">Bills</span><strong>${fmtPersonMoney(ar.bill_total)}</strong></div>
            <div><span class="person-summary-label">Collected</span><strong>${fmtPersonMoney(ar.payment_total)}</strong></div>
          </div>`;
        } else if (cust && cust.outstanding_balance != null && cust.outstanding_balance !== "") {
          sumWrap.innerHTML = `<div class="person-summary-grid">
            <div><span class="person-summary-label">Due</span><strong>${fmtPersonMoney(cust.outstanding_balance)}</strong></div>
          </div>`;
        } else {
          sumWrap.innerHTML = "";
        }
      }
      renderCustomerActions(id, cust?.opening_balance_due, cust?.opening_balance_as_on);
      if (wrap) wrap.innerHTML = renderCustomerStatement(id);
    } catch (e) {
      if (wrap) wrap.innerHTML = `<p style="color:var(--danger);font-size:13px;">${esc(e.message)}</p>`;
    }
  }

  async function showCustomerMoneyLedger(id) {
    const wrap = document.getElementById("customer-ledger-wrap");
    if (!wrap) return;
    wrap.innerHTML = `<p style="color:var(--muted);font-size:13px;">Loading ledger…</p>`;
    try {
      const ar = await api(`/accounts-receivable/customer/${id}`, {}, 0);
      const rows = (ar?.entries || []).slice().sort((a, b) => String(b.display_date || b.created_at || "").localeCompare(String(a.display_date || a.created_at || "")));
      if (!rows.length) {
        wrap.innerHTML = `<p style="color:var(--muted);font-size:13px;">No bills or payments yet.</p>`;
        return;
      }
      wrap.innerHTML = `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>When</th><th>What</th><th>Detail</th><th>Amount</th><th>Balance</th><th></th>
      </tr></thead><tbody>
        ${rows.map(e => {
          const kind = { bill: "Bill", credit_note: "Credit", opening_balance: "Opening", payment: "Payment", payment_reversal: "Reversal" }[e.entry_type] || e.entry_type;
          const view = e.bill_id ? `<button type="button" class="btn btn-ghost btn-sm" onclick="Finance.viewCustomerBill(${e.bill_id})">View detail</button>` : "";
          return `<tr>
            <td style="font-size:12px;">${fmtDay(e.display_date || e.value_date || e.created_at)}</td>
            <td>${esc(kind)}</td>
            <td>${esc(e.display_name || e.description || "")}</td>
            <td>${fmtPersonMoney(e.signed_amount)}</td>
            <td><strong>${fmtPersonMoney(e.running_balance)}</strong></td>
            <td>${view}</td>
          </tr>`;
        }).join("")}
      </tbody></table></div>`;
    } catch (e) {
      wrap.innerHTML = `<p style="color:var(--danger);font-size:13px;">${esc(e.message)}</p>`;
    }
  }

  function setCustomerRealOnly(on) {
    customerRealOnly = !!on;
    const wrap = document.getElementById("customer-ledger-wrap");
    if (wrap && detailId) wrap.innerHTML = renderCustomerStatement(detailId);
  }

  function customerRealBar() {
    return `<label style="display:inline-flex;gap:6px;align-items:center;margin:0 0 10px;font-size:13px;">
      <input type="checkbox" ${customerRealOnly ? "checked" : ""} onchange="App.setCustomerRealOnly(this.checked)" />
      Real entries only
    </label>`;
  }

  function renderCustomerStatement(customerId) {
    let orders = customerLedger.filter(e => e.event_type === "order_placed" || e.event_type === "order_cancelled");
    let bills = customerLedger.filter(e => e.event_type === "customer_bill");
    let payments = customerLedger.filter(e => e.event_type === "ar_payment");
    if (customerRealOnly) {
      orders = orders.filter(e => e.event_type !== "order_cancelled");
      bills = bills.filter(e => !String(e.title || "").toLowerCase().startsWith("cancelled"));
      payments = payments.filter(e => !e.details?.reversed);
    }
    const returns = customerLedger.filter(e => e.event_type === "customer_return");
    const openings = customerLedger.filter(e => e.event_type === "ar_opening");
    const sections = [];

    const group = (title, items, rowFn) => {
      if (!items.length) return;
      sections.push(`<div class="vled-group"><div class="vled-group-title">${esc(title)}</div>${items.map(rowFn).join("")}</div>`);
    };

    group("Orders", orders, (e) => {
      const d = e.details || {};
      const open = customerLedgerExpanded === e.id;
      const lines = d.lines || [];
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="App.toggleCustomerLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">${e.event_type === "order_cancelled" ? "Cancelled" : "Placed"} · #${d.placement_id || "—"}</div>
            <div class="vled-meta">${fmtDate(e.occurred_at)} · ${lines.length} lines · ${esc(e.summary || "")}</div>
          </div>
          <span class="vled-chevron">${open ? "▾" : "▸"}</span>
        </button>
        ${open ? `<div class="vled-body">
          <table class="data fin-mini"><thead><tr><th>Product</th><th>Qty</th><th>Rate</th></tr></thead><tbody>
            ${lines.map(l => `<tr><td>${esc(l.our_product_id)}</td><td>${l.quantity ?? "—"}</td><td>${fmtPersonMoney(l.unit_price ?? l.selling_price ?? l.buying_price)}</td></tr>`).join("") || "<tr><td colspan=3>—</td></tr>"}
          </tbody></table>
          <div class="vled-actions">
            <button class="btn btn-secondary btn-sm" onclick="App.openSelling(${customerId})">Open orders</button>
          </div>
        </div>` : ""}
      </div>`;
    });

    group("Bills / sold", bills, (e) => {
      const d = e.details || {};
      const open = customerLedgerExpanded === e.id;
      const lines = d.lines || [];
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="App.toggleCustomerLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">Bill ${esc(d.bill_number || "")}</div>
            <div class="vled-meta">${fmtDate(e.occurred_at)} · ${fmtPersonMoney(d.grand_total)} · ${lines.length} lines</div>
          </div>
          <span class="vled-chevron">${open ? "▾" : "▸"}</span>
        </button>
        ${open ? `<div class="vled-body">
          <table class="data fin-mini"><thead><tr><th>Product</th><th>Qty</th><th>Amount</th></tr></thead><tbody>
            ${lines.map(l => `<tr><td>${esc(l.our_product_id)}</td><td>${l.quantity ?? "—"}</td><td>${fmtPersonMoney(l.billed_amount)}</td></tr>`).join("") || "<tr><td colspan=3>—</td></tr>"}
          </tbody></table>
          <div class="vled-actions">
            ${d.bill_id ? `<button class="btn btn-primary btn-sm" onclick="CustomerOrders.openBillDoc(${d.bill_id}, false)">Bill PDF</button>` : ""}
            <button class="btn btn-secondary btn-sm" onclick="App.openSelling(${customerId}, 'billed')">Open bills</button>
          </div>
        </div>` : ""}
      </div>`;
    });

    group("Payments", payments, (e) => {
      const d = e.details || {};
      const open = customerLedgerExpanded === e.id;
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="App.toggleCustomerLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">Collected ${esc(d.payment_ref || "")}</div>
            <div class="vled-meta">${fmtDate(e.occurred_at)} · ${fmtPersonMoney(d.amount)}${d.comment ? ` · ${esc(d.comment)}` : ""}</div>
          </div>
          <span class="vled-chevron">${open ? "▾" : "▸"}</span>
        </button>
        ${open ? `<div class="vled-body">
          <div class="vled-actions">
            ${isAdmin() && d.ledger_entry_id && !d.reversed ? `
              <button class="btn btn-secondary btn-sm" onclick="Finance.undoArPayment(${d.ledger_entry_id},'reverse',${customerId})">Reverse</button>
              <button class="btn btn-ghost btn-sm" onclick="Finance.undoArPayment(${d.ledger_entry_id},'void',${customerId})">Void</button>
            ` : ""}
            ${d.reversed ? `<span class="badge badge-amber">Reversed</span>` : ""}
            ${(isAdmin() || can("ar.write")) ? `<button class="btn btn-secondary btn-sm" onclick="App.collectCustomer(${customerId})">Collect again</button>` : ""}
            ${(isAdmin() || can("ar.read")) ? `<button class="btn btn-secondary btn-sm" onclick="Finance.showArFromCustomer(${customerId})">Open AR</button>` : ""}
          </div>
        </div>` : ""}
      </div>`;
    });

    group("Returns", returns, (e) => {
      const d = e.details || {};
      const open = customerLedgerExpanded === e.id;
      const lines = d.lines || [];
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="App.toggleCustomerLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">Return ${esc(d.return_number || "")}</div>
            <div class="vled-meta">${fmtDate(e.occurred_at)} · Credit ${fmtPersonMoney(d.credit_amount)}</div>
          </div>
          <span class="vled-chevron">${open ? "▾" : "▸"}</span>
        </button>
        ${open ? `<div class="vled-body">
          <table class="data fin-mini"><thead><tr><th>Product</th><th>Qty</th><th>Amount</th></tr></thead><tbody>
            ${lines.map(l => `<tr><td>${esc(l.our_product_id)}</td><td>${l.quantity ?? "—"}</td><td>${fmtPersonMoney(l.billed_amount)}</td></tr>`).join("") || "<tr><td colspan=3>—</td></tr>"}
          </tbody></table>
        </div>` : ""}
      </div>`;
    });

    group("Opening", openings, (e) => {
      const d = e.details || {};
      return `<div class="vled-card">
        <div class="vled-head" style="cursor:default;">
          <div>
            <div class="vled-title">Opening</div>
            <div class="vled-meta">${fmtDate(e.occurred_at)} · ${fmtPersonMoney(d.amount)}${d.as_on ? ` · as on ${esc(d.as_on)}` : ""}</div>
          </div>
        </div>
      </div>`;
    });

    const emptyNote = customerLedger.length
      ? `<p style="color:var(--muted);font-size:13px;">No real entries. Uncheck Real entries only to see voids.</p>`
      : `<p style="color:var(--muted);font-size:13px;">Nothing yet. Place an order or bill this customer.</p>`;
    return `<div class="detail-section"><h4>Activity</h4>${customerRealBar()}${sections.length ? sections.join("") : emptyNote}</div>`;
  }

  function toggleCustomerLedgerRow(entryId) {
    customerLedgerExpanded = customerLedgerExpanded === entryId ? null : entryId;
    const wrap = document.getElementById("customer-ledger-wrap");
    if (wrap && detailId) wrap.innerHTML = renderCustomerStatement(detailId);
  }

  function openSelling(customerId, bucket = "open") {
    closeDetail();
    showView("selling");
    CustomerOrders.setHubMode?.("past");
    const p = CustomerOrders.openDetail?.(customerId, bucket || "open");
    if (p && typeof p.then === "function") p.then(() => updateGlobalBack());
    else updateGlobalBack();
  }

  async function billCustomer(customerId) {
    closeDetail();
    showView("selling");
    await CustomerOrders.openDetail?.(customerId, "open");
    CustomerOrders.processOrder?.();
  }

  function collectCustomer(customerId) {
    if (!isAdmin() && !can("ar.write")) return toast("Not permitted", "error");
    closeDetail();
    showView("money");
    Finance.openCustomerAr?.(customerId, { settle: true });
  }

  function openCustomerMoney(customerId) {
    if (!isAdmin() && !can("ar.read")) return toast("Not permitted", "error");
    closeDetail();
    showView("money");
    Finance.openCustomerAr?.(customerId);
  }

  async function setCustomerOpeningBalance(id, currentAmt, currentAsOn) {
    const today = new Date().toISOString().slice(0, 10);
    openDetail("Opening", `
      <p style="color:var(--muted);font-size:13px;margin:0 0 16px;">Tally start they owed. Use 0 to clear. Not Due (Due = opening + bills − collected).</p>
      <label class="label">Opening (₹)</label>
      <input type="number" step="0.01" min="0" class="input" id="ob-amt" value="${esc(currentAmt || "0")}" style="margin-bottom:12px;" />
      <label class="label">As on date</label>
      <input type="date" class="input" id="ob-as-on" value="${esc(currentAsOn || today)}" />
    `, `
      <button class="btn btn-secondary" onclick="App.closeDetail();App.openCustomerDetail(${id},{tab:'activity'})">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="App.saveCustomerOpeningBalance(${id})">Save</button>
    `, "sm");
  }

  async function saveCustomerOpeningBalance(id) {
    const amount = parseFloat(document.getElementById("ob-amt")?.value || "0");
    const asOn = (document.getElementById("ob-as-on")?.value || "").trim();
    if (!Number.isFinite(amount) || amount < 0) return toast("Enter a valid amount", "error");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(asOn)) return toast("Pick a valid date", "error");
    showLoading?.();
    try {
      await api(`/accounts-receivable/customer/${id}/opening-balance`, {
        method: "POST",
        body: JSON.stringify({ amount, as_on: asOn }),
      });
      invalidateCache("/customers");
      invalidateCache("/accounts-receivable");
      toast("Opening saved", "success");
      openCustomerDetail(id, { tab: "activity" });
    } catch (e) { toast(e.message, "error"); }
    finally { hideLoading?.(); }
  }

  function openCustomerLedgerEntry(customerId) {
    closeDetail();
    showView("selling");
    if (customerId) CustomerOrders.openCustomer?.(customerId, "open");
  }

  var otCustomer = null;
  var otLines = [];
  var otParties = null;
  var otItems = null;

  function showOrderTakerDesk() {
    document.getElementById("people-hub")?.classList.add("hidden");
    document.getElementById("people-customers")?.classList.add("hidden");
    document.getElementById("people-vendors")?.classList.add("hidden");
    document.getElementById("order-taker-desk")?.classList.remove("hidden");
    if (!otParties || !otItems) {
      Promise.all([
        api("/customers/entry-parties", {}, 0),
        api("/stock/entry-items", {}, 0),
      ]).then(([parties, items]) => {
        otParties = parties || [];
        otItems = items || [];
      }).catch(e => toast(e.message, "error"));
    }
  }

  function filterOtParties(q) {
    const needle = String(q || "").trim().toLowerCase();
    if (!needle) return [];
    const digits = needle.replace(/\D/g, "");
    const phoneNeedle = digits.length >= 4 ? digits.slice(-10) : "";
    return (otParties || []).filter(c => {
      const name = String(c.business_name || "").toLowerCase();
      const city = String(c.city_name || "").toLowerCase();
      const alias = String(c.alias || "").toLowerCase();
      const num = String(c.party_number || "");
      const phone = String(c.phone || "").replace(/\D/g, "");
      return name.includes(needle) || city.includes(needle) || alias.includes(needle)
        || (num && needle.replace(/\D/g, "") && num.includes(needle.replace(/\D/g, "")))
        || (phoneNeedle && phone.includes(phoneNeedle));
    }).slice(0, 12);
  }

  function partyLabel(c) {
    return `${c.business_name || ""}${c.city_name ? " · " + c.city_name : ""}`;
  }

  function onOrderTakerCustomer(val) {
    const box = document.getElementById("ot-customer-matches");
    if (!box) return;
    if (!otParties) {
      box.innerHTML = `<p style="font-size:14px;color:var(--muted);margin:8px 0 0;">Loading customers…</p>`;
      return;
    }
    const rows = filterOtParties(val);
    box.innerHTML = rows.map(c =>
      `<button type="button" class="btn btn-secondary ot-hit" onclick="App.pickOrderTakerCustomer(${c.id})">${esc(partyLabel(c))}${c.phone ? "<br><span style='font-weight:500;color:var(--muted);'>" + esc(c.phone) + "</span>" : ""}</button>`
    ).join("") || (String(val || "").trim() ? `<p style="font-size:14px;color:var(--muted);margin:8px 0 0;">No match</p>` : "");
  }

  function pickOrderTakerCustomer(id) {
    const c = (otParties || []).find(x => Number(x.id) === Number(id));
    if (!c) return;
    otCustomer = c;
    otLines = [];
    paintOrderTakerLines();
    const picked = document.getElementById("ot-customer-picked");
    if (picked) picked.textContent = partyLabel(c);
    const box = document.getElementById("ot-customer-matches");
    if (box) box.innerHTML = "";
    const input = document.getElementById("ot-customer");
    if (input) input.value = "";
    const item = document.getElementById("ot-item");
    if (item) item.value = "";
    const qty = document.getElementById("ot-qty");
    if (qty) qty.value = "";
    document.getElementById("ot-pick")?.classList.add("hidden");
    document.getElementById("ot-book")?.classList.remove("hidden");
    item?.focus();
  }

  function clearOrderTakerCustomer() {
    otCustomer = null;
    otLines = [];
    paintOrderTakerLines();
    const matches = document.getElementById("ot-item-matches");
    if (matches) matches.innerHTML = "";
    document.getElementById("ot-book")?.classList.add("hidden");
    document.getElementById("ot-pick")?.classList.remove("hidden");
    const input = document.getElementById("ot-customer");
    if (input) { input.value = ""; input.focus(); }
  }

  function onOrderTakerItem(val) {
    const box = document.getElementById("ot-item-matches");
    if (!box) return;
    const needle = String(val || "").trim().toLowerCase();
    if (!needle) { box.innerHTML = ""; return; }
    const rows = (otItems || []).filter(p => String(p.our_product_id || "").toLowerCase().includes(needle)).slice(0, 12);
    box.innerHTML = rows.map(p => {
      const onHand = Number(p.quantity_on_hand || 0);
      if (onHand <= 0) {
        return `<div class="ot-out">${esc(p.our_product_id)} · Out of stock</div>`;
      }
      return `<button type="button" class="btn btn-secondary ot-hit" onclick="App.addOrderTakerItem(${p.catalog_product_id})">${esc(p.our_product_id)} · ${onHand} in stock</button>`;
    }).join("") || `<p style="font-size:14px;color:var(--muted);margin:8px 0 0;">No match</p>`;
  }

  function paintOrderTakerLines() {
    const box = document.getElementById("ot-lines");
    if (!box) return;
    if (!otLines.length) { box.innerHTML = ""; return; }
    box.innerHTML = `<table class="data"><thead><tr><th>Item</th><th>Qty</th><th></th></tr></thead><tbody>
      ${otLines.map(l => `<tr><td>${esc(l.our_product_id)}</td><td>${l.quantity}</td><td><button type="button" class="btn btn-ghost btn-sm" onclick="App.removeOrderTakerLine(${l.catalog_product_id})">Remove</button></td></tr>`).join("")}
    </tbody></table>`;
  }

  function addOrderTakerItem(id) {
    const p = (otItems || []).find(x => Number(x.catalog_product_id) === Number(id));
    if (!p) return;
    const onHand = Number(p.quantity_on_hand || 0);
    if (onHand <= 0) return toast("Out of stock", "error");
    const qty = parseInt(String(document.getElementById("ot-qty")?.value || ""), 10);
    if (!qty || qty < 1) return toast("Type the quantity", "error");
    if (qty > onHand) return toast("Only " + onHand + " in stock", "error");
    const existing = otLines.find(l => l.catalog_product_id === p.catalog_product_id);
    if (existing) existing.quantity = qty;
    else otLines.push({ catalog_product_id: p.catalog_product_id, our_product_id: p.our_product_id, quantity: qty });
    const box = document.getElementById("ot-item-matches");
    if (box) box.innerHTML = "";
    const input = document.getElementById("ot-item");
    if (input) input.value = "";
    const qtyBox = document.getElementById("ot-qty");
    if (qtyBox) qtyBox.value = "";
    paintOrderTakerLines();
    input?.focus();
  }

  function removeOrderTakerLine(id) {
    otLines = otLines.filter(l => l.catalog_product_id !== id);
    paintOrderTakerLines();
  }

  async function saveOrderTakerOrder() {
    if (!otCustomer) return toast("Search the customer first", "error");
    if (!otLines.length) return toast("Add at least one item", "error");
    const today = new Date();
    const placed = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    showLoading();
    try {
      await api(`/customer-orders/customer/${otCustomer.id}/offline`, {
        method: "POST",
        body: JSON.stringify({
          lines: otLines.map(l => ({ catalog_product_id: l.catalog_product_id, quantity: l.quantity })),
          narration: null,
          placed_on: placed,
        }),
      });
      toast("Order booked", "success");
      clearOrderTakerCustomer();
    } catch (e) { toast(e.message, "error"); }
    finally { hideLoading(); }
  }

  function createCustomerOrder(customerId) {
    closeDetail();
    showView("selling");
    CustomerOrders.openOfflineWizard(customerId);
  }

  function customerCityHint(cityId) {
    const city = cities.find(c => c.id == cityId);
    if (!city) return `<p class="people-field-hint">City sets delivery route. Required for route collection.</p>`;
    return `<p class="people-field-hint">Route: <strong>${esc(city.route_name || "Unassigned")}</strong> · from city <strong>${esc(city.name)}</strong></p>`;
  }

  function normalizePhoneDigits(raw) {
    return String(raw || "").replace(/\D/g, "");
  }

  function normalizeGstin(raw) {
    return String(raw || "").replace(/\s+/g, "").toUpperCase();
  }

  function validateGstin(raw) {
    const gst = normalizeGstin(raw);
    if (!gst) return { ok: true, value: null };
    const re = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
    if (!re.test(gst)) return { ok: false, value: gst };
    return { ok: true, value: gst };
  }

  function validateOptionalPhone(raw) {
    const p = normalizePhoneDigits(raw);
    if (!p) return { ok: true, value: null };
    if (p.length !== 10) return { ok: false, value: p };
    return { ok: true, value: p };
  }

  async function openCustomerEdit(id) {
    const c = await api(`/customers/${id}`);
    editingCustomerId = id;
    document.getElementById("edit-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Business Name *</label><input id="ed-business_name" class="input" value="${esc(c.business_name)}" /></div>
        <div><label class="label">Person Name</label><input id="ed-person_name" class="input" value="${esc(c.person_name || "")}" /></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Primary Phone *</label><input id="ed-phone" class="input" type="tel" maxlength="10" value="${esc(c.phone)}" /></div>
          <div><label class="label">Secondary Phone</label><input id="ed-secondary_phone" class="input" type="tel" maxlength="10" value="${esc(c.secondary_phone || "")}" placeholder="10 digits or blank" /></div>
        </div>
        <div><label class="label">Alias</label><input id="ed-alias" class="input" value="${esc(c.alias || "")}" /></div>
        <div><label class="label">City *</label>
          <select id="ed-city_id" class="input" onchange="App.onCustomerEditCityChange(this.value)">
            <option value="">— Select city —</option>
            ${cities.map(ct => `<option value="${ct.id}" ${c.city_id == ct.id ? "selected" : ""}>${esc(ct.name)} (${esc(ct.route_name || "No route")})</option>`).join("")}
          </select>
          <div id="ed-city-hint">${customerCityHint(c.city_id)}</div>
        </div>
        <div><label class="label">GST Number</label><input id="ed-gst_number" class="input" value="${esc(c.gst_number || "")}" placeholder="22AAAAA0000A1Z5" maxlength="15" style="text-transform:uppercase;" /></div>
        <div><label class="label">Address</label><textarea id="ed-address" class="input" rows="2">${esc(c.address || "")}</textarea></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px;border:1px dashed var(--border);border-radius:10px;background:#f8fafc;">
          <div><label class="label">Marking 1</label><input id="ed-marker_1" class="input" maxlength="100" placeholder="e.g. Genuine party" value="${esc(c.marker_1 || "")}" /></div>
          <div><label class="label">Marking 2</label><input id="ed-marker_2" class="input" maxlength="100" placeholder="e.g. Only cash" value="${esc(c.marker_2 || "")}" /></div>
          <p style="grid-column:1/-1;margin:0;font-size:12px;color:var(--muted);">Internal only — shown on orders/bill screens for staff, never on the customer's bill PDF.</p>
        </div>
        <div><label class="label">Additional details</label><textarea id="ed-additional_details" class="input" rows="2">${esc(c.additional_details || "")}</textarea></div>
        <div>
          <label class="label">Payment type *</label>
          <div style="display:flex;gap:8px;margin-top:4px;">
            <label id="ed-label-cash" style="display:flex;align-items:center;gap:6px;font-size:14px;cursor:pointer;padding:8px 14px;border:1px solid var(--border);border-radius:8px;flex:1;justify-content:center;${(c.payment_type||'CREDIT')==='CASH'?'background:#fef3c7;border-color:#f59e0b;font-weight:600;':''}">
              <input type="radio" name="ed-payment_type" value="CASH" ${(c.payment_type||'CREDIT')==='CASH'?'checked':''} onchange="App.onEditPaymentTypeChange('CASH')" /> CASH
            </label>
            <label id="ed-label-credit" style="display:flex;align-items:center;gap:6px;font-size:14px;cursor:pointer;padding:8px 14px;border:1px solid var(--border);border-radius:8px;flex:1;justify-content:center;${(c.payment_type||'CREDIT')==='CREDIT'?'background:#eff6ff;border-color:#3b82f6;font-weight:600;':''}">
              <input type="radio" name="ed-payment_type" value="CREDIT" ${(c.payment_type||'CREDIT')==='CREDIT'?'checked':''} onchange="App.onEditPaymentTypeChange('CREDIT')" /> CREDIT
            </label>
          </div>
        </div>
        <div id="ed-credit-limit-wrap" style="grid-template-columns:1fr 1fr;gap:12px;display:${(c.payment_type||'CREDIT')==='CASH'?'none':'grid'};">
          <div><label class="label">Credit Limit (₹)</label><input id="ed-credit_limit" class="input" type="number" value="${esc(c.credit_limit || "")}" /></div>
          <div style="display:flex;align-items:end;"><label style="display:flex;align-items:center;gap:8px;font-size:14px;">
            <input type="checkbox" id="ed-credit_override" ${c.credit_override ? "checked" : ""} /> Allow credit override
          </label></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px;border:1px dashed var(--border);border-radius:10px;background:#fffbeb;">
          <div><label class="label">Opening (₹)</label><input id="ed-opening_due" class="input" type="number" min="0" step="0.01" value="${esc(c.opening_balance_due || "0")}" /></div>
          <div><label class="label">As on</label><input id="ed-opening_as_on" class="input" type="date" value="${esc(c.opening_balance_as_on || new Date().toISOString().slice(0, 10))}" /></div>
          <p style="grid-column:1/-1;margin:0;font-size:12px;color:var(--muted);">Tally start they owed. Not Due (Due = opening + bills − collected).</p>
        </div>
      </div>`;
    document.getElementById("edit-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeEditModal()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="App.saveCustomer()">Save Changes</button>`;
    document.getElementById("edit-modal").classList.remove("hidden");
  }

  function onCustomerEditCityChange(val) {
    const hint = document.getElementById("ed-city-hint");
    if (hint) hint.innerHTML = customerCityHint(val ? parseInt(val, 10) : null);
  }

  function onEditPaymentTypeChange(val) {
    const wrap = document.getElementById("ed-credit-limit-wrap");
    if (wrap) wrap.style.display = val === "CASH" ? "none" : "grid";
    if (val === "CASH") {
      const el = document.getElementById("ed-credit_limit");
      if (el) el.value = "";
    }
    const cashLabel = document.getElementById("ed-label-cash");
    const creditLabel = document.getElementById("ed-label-credit");
    if (cashLabel) {
      cashLabel.style.background = val === "CASH" ? "#fef3c7" : "";
      cashLabel.style.borderColor = val === "CASH" ? "#f59e0b" : "";
      cashLabel.style.fontWeight = val === "CASH" ? "600" : "";
    }
    if (creditLabel) {
      creditLabel.style.background = val === "CREDIT" ? "#eff6ff" : "";
      creditLabel.style.borderColor = val === "CREDIT" ? "#3b82f6" : "";
      creditLabel.style.fontWeight = val === "CREDIT" ? "600" : "";
    }
  }

  function closeEditModal() {
    document.getElementById("edit-modal").classList.add("hidden");
    editingCustomerId = null;
  }

  async function saveCustomer() {
    if (!editingCustomerId) return;
    const business = document.getElementById("ed-business_name").value.trim();
    const phone = normalizePhoneDigits(document.getElementById("ed-phone").value);
    const cityVal = document.getElementById("ed-city_id").value;
    const cityId = cityVal ? parseInt(cityVal, 10) : null;
    if (!business) return toast("Business name required", "error");
    if (phone.length !== 10) return toast("Phone must be 10 digits", "error");
    if (!cityId) return toast("Please select a city", "error");
    const sec = validateOptionalPhone(document.getElementById("ed-secondary_phone").value);
    if (!sec.ok) return toast("Secondary phone must be 10 digits or blank", "error");
    const gst = validateGstin(document.getElementById("ed-gst_number").value);
    if (!gst.ok) return toast("GST looks invalid — use 15-char GSTIN or leave blank", "error");
    try {
      await api(`/customers/${editingCustomerId}`, { method: "PATCH", body: JSON.stringify({
        business_name: business,
        person_name: document.getElementById("ed-person_name").value.trim() || null,
        phone,
        secondary_phone: sec.value,
        alias: document.getElementById("ed-alias").value.trim() || null,
        city_id: cityId,
        gst_number: gst.value,
        address: document.getElementById("ed-address").value.trim() || null,
        marker_1: document.getElementById("ed-marker_1")?.value.trim() || null,
        marker_2: document.getElementById("ed-marker_2")?.value.trim() || null,
        additional_details: document.getElementById("ed-additional_details")?.value.trim() || null,
        payment_type: (document.querySelector('input[name="ed-payment_type"]:checked')?.value) || "CREDIT",
        credit_limit: (() => {
          const pt = document.querySelector('input[name="ed-payment_type"]:checked')?.value;
          if (pt === "CASH") return 0;
          const v = document.getElementById("ed-credit_limit")?.value;
          return v ? parseFloat(v) : null;
        })(),
        credit_override: document.getElementById("ed-credit_override")?.checked || false,
        opening_balance_due: parseFloat(document.getElementById("ed-opening_due")?.value || "0") || 0,
        opening_balance_as_on: document.getElementById("ed-opening_as_on")?.value || null,
      })});
      const id = editingCustomerId;
      closeEditModal();
      invalidateCache("/customers");
      invalidateCache("/accounts-receivable");
      invalidateCache("/stats");
      invalidateCache("/customer-orders");
      invalidateCache("/stock");
      invalidateCache("/catalog");
      invalidateCache("/vendor-orders");
      await loadCustomers();
      toast("Customer updated", "success");
      openCustomerDetail(id);
    } catch (e) { toast(e.message, "error"); }
  }

