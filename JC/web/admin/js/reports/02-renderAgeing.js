  async function renderAgeing(body) {
    const side = ageingSide === "ap" ? "ap" : "ar";
    const data = await ctx.api(`/reports/ageing/${side}`, {}, 0);
    const t = data.totals || {};
    const items = (data.items || []).filter(it => matchParty(it));
    body.innerHTML = `
      ${DocShare.toolbarHtml({
        printOnclick: "Reports.shareAgeing(true)",
        pdfOnclick: "Reports.shareAgeing(false)",
        waOnclick: "Reports.waAgeing()",
        excelOnclick: `Reports.exportExcel('${side}')`,
      })}
      <p class="fin-panel-sub" style="margin:0 0 12px;">As on ${ctx.esc(data.as_of || today())}</p>
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">0–30</span><strong>${fmtPrice(t["0-30"])}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">31–60</span><strong>${fmtPrice(t["31-60"])}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">61–90</span><strong>${fmtPrice(t["61-90"])}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">90+</span><strong>${fmtPrice(t["90+"])}</strong></div>
      </div>
      ${items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Party</th><th>Total</th><th>0–30</th><th>31–60</th><th>61–90</th><th>90+</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('${side === "ar" ? "customers" : "vendors"}', ${it.id})">
          <td><strong>${ctx.esc(it.label)}</strong></td>
          <td><strong>${fmtPrice(it.outstanding)}</strong></td>
          <td>${fmtPrice(it.b0_30)}</td>
          <td>${fmtPrice(it.b31_60)}</td>
          <td>${fmtPrice(it.b61_90)}</td>
          <td>${fmtPrice(it.b90_plus)}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("All clear", "Nothing due.")}`;
  }

  async function renderStockWise(body) {
    const data = await ctx.api(`/reports/stock/summary${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.label, it.category));
    const sum = (key) => items.reduce((s, it) => s + (Number(it[key]) || 0), 0);
    const opening = sum("opening");
    const inward = sum("inward");
    const outward = sum("outward");
    const closing = sum("closing");
    body.innerHTML = `
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">Products</span><strong>${items.length}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Opening</span><strong>${opening}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">In</span><strong>${inward}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Out</span><strong>${outward}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Closing</span><strong>${closing}</strong></div>
      </div>
      ${items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Product</th><th>Opening</th><th>In</th><th>Out</th><th>Closing</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('products', ${it.id})">
          <td><strong>${ctx.esc(it.label)}</strong>${it.category ? `<div style="color:var(--muted);font-size:12px;">${ctx.esc(it.category)}</div>` : ""}</td>
          <td>${it.opening}</td>
          <td>${it.inward}</td>
          <td>${it.outward}</td>
          <td><strong>${it.closing}</strong></td>
        </tr>`).join("")}
        <tr><td><strong>Total</strong></td><td><strong>${opening}</strong></td><td><strong>${inward}</strong></td><td><strong>${outward}</strong></td><td><strong>${closing}</strong></td></tr>
      </tbody></table></div>` : empty("No stock movement", "Widen the dates to see products.")}`;
  }

  async function renderValuation(body) {
    const data = await ctx.api(`/reports/stock/valuation`, {}, 0);
    const t = data.totals || {};
    const items = (data.items || []).filter(it => matchSearch(it.label));
    body.innerHTML = `
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">SKUs</span><strong>${t.sku_count || 0}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Buy value</span><strong>${fmtPrice(t.buy_value)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Sell value</span><strong>${fmtPrice(t.sell_value)}</strong></div>
      </div>
      ${items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Product</th><th>Qty</th><th>Buy</th><th>Sell</th><th>Buy value</th><th>Sell value</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('products', ${it.id})">
          <td><strong>${ctx.esc(it.label)}</strong></td>
          <td>${it.qty}</td>
          <td>${fmtPrice(it.buying_price)}</td>
          <td>${it.selling_price != null ? fmtPrice(it.selling_price) : "—"}</td>
          <td>${fmtPrice(it.buy_value)}</td>
          <td>${it.sell_value != null ? fmtPrice(it.sell_value) : "—"}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No stock on hand", "Receive stock to see valuation.")}`;
  }

  async function renderMovers(body) {
    const data = await ctx.api(`/reports/stock/movers${rangeQs()}`, {}, 0);
    const fast = (data.fast || []).filter(it => matchSearch(it.label));
    const slow = (data.slow || []).filter(it => matchSearch(it.label));
    body.innerHTML = `
      <h3 class="fin-panel-title" style="margin:0 0 8px;">Fast movers</h3>
      ${fast.length ? `<div class="card table-wrap" style="margin-bottom:24px;"><table class="data"><thead><tr>
        <th>Product</th><th>Sold</th><th>Sales</th><th>On hand</th>
      </tr></thead><tbody>
        ${fast.map(it => `<tr><td>${ctx.esc(it.label)}</td><td>${it.qty_sold}</td><td>${fmtPrice(it.sales_value)}</td><td>${it.on_hand}</td></tr>`).join("")}
      </tbody></table></div>` : empty("No sales in range", "Widen dates to see movers.")}
      <h3 class="fin-panel-title" style="margin:0 0 8px;">Slow / idle</h3>
      ${slow.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Product</th><th>Sold</th><th>On hand</th>
      </tr></thead><tbody>
        ${slow.map(it => `<tr><td>${ctx.esc(it.label)}</td><td>${it.qty_sold}</td><td>${it.on_hand}</td></tr>`).join("")}
      </tbody></table></div>` : empty("No idle stock", "Everything is moving or empty.")}`;
  }

  async function renderLow(body) {
    const data = await ctx.api(`/reports/stock/low?threshold=${lowThreshold}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.label));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Product</th><th>On hand</th><th>Limit</th><th>Buy</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('products', ${it.id})">
        <td><strong>${ctx.esc(it.label)}</strong></td>
        <td>${it.qty}</td><td>${it.threshold}</td><td>${fmtPrice(it.buying_price)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("Stock looks fine", "Nothing at or below this threshold.");
  }

  async function renderReturns(body) {
    const data = await ctx.api(`/reports/returns-register${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.doc_number, it.party_label));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Date</th><th>Number</th><th>Customer</th><th>Qty</th><th>Credit</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr>
        <td>${ctx.esc(it.date || "—")}</td>
        <td>${ctx.esc(it.doc_number || "—")}</td>
        <td>${ctx.esc(it.party_label || "—")}</td>
        <td>${it.qty}</td>
        <td>${fmtPrice(it.credit_amount)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No returns", "Widen dates if you expect credit notes.");
  }

  async function renderDebitNotes(body) {
    const data = await ctx.api(`/reports/debit-notes-register${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.party_label, it.our_product_id, it.notes));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Date</th><th>Vendor</th><th>Type</th><th>Product</th><th>Amount</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr>
        <td>${ctx.esc(it.date || "—")}</td>
        <td>${ctx.esc(it.party_label || "—")}</td>
        <td>${ctx.esc(it.note_type)}/${ctx.esc(it.direction || "")}</td>
        <td>${ctx.esc(it.our_product_id || "—")}</td>
        <td>${fmtPrice(it.amount)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No debit notes", "Widen dates to see purchase adjustments.");
  }

  async function renderGst(body) {
    const path = chip === "gst-purchases" ? "gst/purchases" : "gst/sales";
    const data = await ctx.api(`/reports/${path}${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.doc_number, it.party_label));
    const note = chip === "gst-purchases"
      ? `<p class="fin-panel-sub" style="margin:0 0 12px;">Purchase GST not stored on receipts yet — GST shows as 0.</p>` : "";
    body.innerHTML = note + (items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Date</th><th>Number</th><th>Party</th><th>Rate</th><th>Taxable</th><th>GST</th><th>Total</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr>
        <td>${ctx.esc(it.date || "—")}</td>
        <td>${ctx.esc(it.doc_number || "—")}</td>
        <td>${ctx.esc(it.party_label || "—")}</td>
        <td>${it.gst_enabled ? `${it.gst_rate}%` : "Off"}</td>
        <td>${fmtPrice(it.taxable_value)}</td>
        <td>${fmtPrice(it.gst_amount)}</td>
        <td>${fmtPrice(it.grand_total)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No bills", "Widen dates for the GST register."));
  }

  async function renderCashbook(body) {
    const data = await ctx.api(`/reports/cashbook${rangeQs()}`, {}, 0);
    const t = data.totals || {};
    const entries = (data.entries || []).filter(r => matchSearch(r.kind, r.party, r.label));
    body.innerHTML = `
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">In</span><strong>${fmtPrice(t.cash_in)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Out</span><strong>${fmtPrice(t.cash_out)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Net</span><strong>${fmtPrice(t.net)}</strong></div>
      </div>
      ${entries.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Date</th><th>Type</th><th>Party</th><th>In</th><th>Out</th><th>Balance</th>
      </tr></thead><tbody>
        ${entries.map(r => `<tr>
          <td>${ctx.esc(r.date || "—")}</td>
          <td>${ctx.esc(r.kind)}</td>
          <td>${ctx.esc(r.party || "—")}</td>
          <td>${fmtPrice(r.in_amount)}</td>
          <td>${fmtPrice(r.out_amount)}</td>
          <td>${fmtPrice(r.balance)}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No cash moves", "Widen dates to build the cash book.")}`;
  }

  async function renderExpenseCat(body) {
    const data = await ctx.api(`/reports/expense-by-category${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.category));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Category</th><th>Count</th><th>Amount</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr class="clickable" onclick="Reports.openExpenseLedger('${ctx.esc(it.category)}')">
        <td><strong>${ctx.esc(it.category)}</strong></td>
        <td>${it.count}</td>
        <td>${fmtPrice(it.amount)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No expenses", "Add expenses in Finance, or widen dates.");
  }

  async function renderPnl(body) {
    const data = await ctx.api(`/reports/pnl${rangeQs()}`, {}, 0);
    body.innerHTML = `<div class="review-grid">
      ${ctx.reviewRow("Sales billed (incl. GST)", fmtPrice(data.sales_billed))}
      ${ctx.reviewRow("GST on sales", fmtPrice(data.gst_on_sales))}
      ${ctx.reviewRow("Sales, ex-GST", fmtPrice(data.sales_taxable))}
      ${ctx.reviewRow("Customer returns", data.customer_returns && Number(data.customer_returns) > 0 ? "−" + fmtPrice(data.customer_returns) : fmtPrice(data.customer_returns))}
      ${ctx.reviewRow("Net sales", fmtPrice(data.net_sales))}
      ${ctx.reviewRow("Purchases (COGS proxy)", fmtPrice(data.cogs_purchases))}
      ${ctx.reviewRow("Vendor debit notes", fmtPrice(data.vendor_debit_notes))}
      ${ctx.reviewRow("Net COGS", fmtPrice(data.cogs_net))}
      ${ctx.reviewRow("Gross profit", fmtPrice(data.gross_profit))}
      ${ctx.reviewRow("Expenses", fmtPrice(data.expenses))}
      ${ctx.reviewRow("Freight paid", fmtPrice(data.freight_paid))}
      ${ctx.reviewRow("Manual losses", fmtPrice(data.manual_losses))}
      ${ctx.reviewRow("Net profit", fmtPrice(data.net_profit))}
      ${ctx.reviewRow("Cash collected", fmtPrice(data.cash_collected))}
      ${ctx.reviewRow("Bill count", data.bill_count)}
    </div>
    <p class="fin-panel-sub" style="margin-top:12px;">Net profit = net sales (ex-GST, net of returns) − net COGS (purchases, net of vendor debit notes) − expenses − manual losses. Still a management approximation, not true inventory-costed accounting.${data.note ? ` ${ctx.esc(data.note)}` : ""}</p>`;
  }

  async function renderLedgers(body) {
    if (ledgerKind === "cash") {
      body.innerHTML = `<div class="fin-panel-head" style="margin-bottom:16px;">
        <div><h3 class="fin-panel-title">Cash book</h3>
        <p class="fin-panel-sub">All cash in and out with running balance</p></div>
        <button type="button" class="btn btn-primary" onclick="Reports.openCashLedger()">Open cash book</button>
      </div>`;
      return;
    }
    const data = await ctx.api(`/reports/ledgers/${ledgerKind}`, {}, 0);
    let items = data.items || [];

    if (ledgerKind === "staff") {
      items = items.filter(it => matchSearch(it.label, it.phone));
      body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Name</th><th>Phone</th><th>Activities</th>
      </tr></thead><tbody>
        ${items.map(it => {
          const onclick = it.actor_type === "admin"
            ? `Reports.openStaffLedger(0, 'admin', '${ctx.esc(it.actor_name || "")}')`
            : `Reports.openStaffLedger(${it.id})`;
          return `<tr class="clickable" onclick="${onclick}">
            <td><strong>${ctx.esc(it.label)}</strong></td>
            <td>${ctx.esc(it.phone || "—")}</td>
            <td>${it.activity_count || 0}</td>
          </tr>`;
        }).join("")}
      </tbody></table></div>` : empty("No staff activity", "Staff actions show up as they use the app.");
      return;
    }

    if (ledgerKind === "expenses") {
      items = items.filter(it => matchSearch(it.label, it.category));
      body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Category</th><th>Count</th><th>Total</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openExpenseLedger('${ctx.esc(it.category || it.label)}')">
          <td><strong>${ctx.esc(it.label)}</strong></td>
          <td>${it.count || 0}</td>
          <td>${fmtPrice(it.outstanding)}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No expense categories", "Add expenses in Finance first.");
      return;
    }

    if (ledgerKind === "products") {
      items = items.filter(it => matchSearch(it.label));
      body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Name</th><th>On hand</th><th>Buy</th><th>Sell</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('products', ${it.id})">
          <td><strong>${ctx.esc(it.label)}</strong></td>
          <td>${it.qty ?? 0}</td>
          <td>${fmtPrice(it.buying_price)}</td>
          <td>${it.selling_price != null ? fmtPrice(it.selling_price) : '<span class="prod-price-missing">Not set</span>'}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No products", "Add catalog products first.");
      return;
    }

    items = items.filter(it => matchParty(it));
    const isRoute = ledgerKind === "routes";
    const isFreight = ledgerKind === "freight";
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Name</th>
      <th>${isRoute ? "Customers" : isFreight ? "Due" : "Opening"}</th>
      ${isRoute || !isFreight ? "<th>Due</th>" : ""}
    </tr></thead><tbody>
      ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('${ledgerKind}', ${it.id})">
        <td><strong>${ctx.esc(it.label)}</strong></td>
        <td>${isRoute ? (it.customer_count ?? 0) : isFreight ? `<strong>${fmtPrice(it.outstanding)}</strong>` : fmtPrice(it.opening_total)}</td>
        ${isRoute || !isFreight ? `<td><strong>${fmtPrice(it.outstanding)}</strong></td>` : ""}
      </tr>`).join("")}
    </tbody></table></div>` : empty("No ledgers", "Nothing to show for this list.");
  }

  async function openLedger(kind, id) {
    backLabel = "Back";
    ctx.showLoading?.();
    try {
      ledgerDetail = await ctx.api(`/reports/ledgers/${kind}/${id}`, {}, 0);
      showDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openStaffLedger(id, actorType = "staff", actorName = "") {
    backLabel = "Back to staff";
    ctx.showLoading?.();
    try {
      let url = `/reports/ledgers/staff/${id || 0}`;
      if (actorType === "admin") url += `?actor_type=admin&actor_name=${encodeURIComponent(actorName)}`;
      ledgerDetail = await ctx.api(url, {}, 0);
      showDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openExpenseLedger(category) {
    backLabel = "Back";
    ctx.showLoading?.();
    try {
      ledgerDetail = await ctx.api(`/reports/ledgers/expenses/${encodeURIComponent(category)}${rangeQs()}`, {}, 0);
      showDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openCashLedger() {
    backLabel = "Back";
    ctx.showLoading?.();
    try {
      ledgerDetail = await ctx.api(`/reports/ledgers/cash/book${rangeQs()}`, {}, 0);
      showDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function showDetail() {
    document.getElementById("reports-hub")?.classList.add("hidden");
    document.getElementById("reports-ledger-detail")?.classList.remove("hidden");
    const back = document.getElementById("reports-detail-back");
    if (back) back.textContent = `← ${backLabel}`;
    renderLedgerDetail();
    App.updateGlobalBack?.();
  }

  function backFromLedger() {
    ledgerDetail = null;
    document.getElementById("reports-ledger-detail")?.classList.add("hidden");
    document.getElementById("reports-hub")?.classList.remove("hidden");
    loadChip();
    App.updateGlobalBack?.();
  }

  function renderLedgerDetail() {
    const hero = document.getElementById("reports-ledger-hero");
    const body = document.getElementById("reports-ledger-body");
    if (!ledgerDetail || !body) return;
    const d = ledgerDetail;
    if (hero) {
      const badges = [
        d.outstanding != null ? `<span class="badge badge-amber">${fmtPrice(d.outstanding)}</span>` : "",
        d.quantity_on_hand != null ? `<span class="badge badge-blue">On hand ${d.quantity_on_hand}</span>` : "",
        d.activity_count != null ? `<span class="badge badge-blue">${d.activity_count} activities</span>` : "",
      ].filter(Boolean).join(" ");
      hero.innerHTML = HubUI.pageHero({
        title: d.party_label || d.label || "Ledger",
        sub: d.party_type || "ledger",
        actionsHtml: badges,
      });
    }
    if (d.party_type === "staff") {
      const entries = d.entries || [];
      body.innerHTML = entries.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>When</th><th>Action</th><th>What</th><th>Detail</th>
      </tr></thead><tbody>
        ${entries.map(e => `<tr>
          <td style="font-size:12px;">${e.created_at ? new Date(e.created_at).toLocaleString() : "—"}</td>
          <td>${ctx.esc(e.action || "—")}</td>
          <td>${ctx.esc([e.entity_type, e.entity_label || e.entity_id].filter(Boolean).join(" · ") || "—")}</td>
          <td style="color:var(--muted);font-size:13px;">${ctx.esc(e.detail || "—")}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No activity", "This person has no logged actions yet.");
      return;
    }
    if (d.party_type === "product") {
      body.innerHTML = Stock.ledgerTableHtml
        ? `<p style="font-size:12px;color:var(--muted);margin:0 0 8px;">Click a row to open that bill.</p>${Stock.ledgerTableHtml(d.entries)}`
        : empty("No stock moves", "No ledger lines for this product.");
      return;
    }
    const entries = d.entries || [];
    body.innerHTML = `
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        ${d.opening_total != null ? `<div class="fin-stat"><span class="fin-stat-label">Opening</span><strong>${fmtPrice(d.opening_total)}</strong></div>` : ""}
        ${d.bill_total != null ? `<div class="fin-stat"><span class="fin-stat-label">In / Bills</span><strong>${fmtPrice(d.bill_total)}</strong></div>` : ""}
        ${d.payment_total != null ? `<div class="fin-stat"><span class="fin-stat-label">Out / Paid</span><strong>${fmtPrice(d.payment_total)}</strong></div>` : ""}
        ${d.credit_total != null ? `<div class="fin-stat"><span class="fin-stat-label">Credits</span><strong>${fmtPrice(d.credit_total)}</strong></div>` : ""}
        ${d.debit_note_total != null ? `<div class="fin-stat"><span class="fin-stat-label">Debit notes</span><strong>${fmtPrice(d.debit_note_total)}</strong></div>` : ""}
        ${d.outstanding != null ? `<div class="fin-stat"><span class="fin-stat-label">Net</span><strong>${fmtPrice(d.outstanding)}</strong></div>` : ""}
      </div>
      ${entries.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>When</th><th>Type</th><th>Description</th><th>Amount</th><th>Balance</th>
      </tr></thead><tbody>
        ${[...entries].reverse().map(e => `<tr>
          <td style="font-size:12px;">${e.value_date || (e.created_at ? new Date(e.created_at).toLocaleDateString() : "—")}</td>
          <td><span class="badge badge-blue">${ctx.esc(e.entry_type)}</span></td>
          <td>${ctx.esc(e.description || "—")}</td>
          <td>${fmtPrice(e.signed_amount || e.amount)}</td>
          <td>${e.running_balance != null ? fmtPrice(e.running_balance) : "—"}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("Empty ledger", "No entries yet.")}`;
  }

  function openDoc(docType, id) {
    if (docType === "sales_bill") { BillSeries?.openBill?.(id); return; }
    if (docType === "purchase_bill") { Stock?.openReceiptDetail?.(id); return; }
  }

  async function shareAgeing(print) {
    const side = ageingSide === "ap" ? "ap" : "ar";
    try {
      await DocShare.openPdf(`/share/ageing/pdf?side=${side}`, {
        print: !!print,
        filename: `ageing_${side}.pdf`,
      });
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function waAgeing() {
    const side = ageingSide === "ap" ? "ap" : "ar";
    const phone = prompt("WhatsApp phone (10 digits / with country code):");
    if (!phone) return;
    ctx.showLoading?.();
    try {
      const res = await DocShare.whatsapp({ kind: "ageing", side, phone, caption: `Ageing ${side.toUpperCase()}` });
      if (res.ok) ctx.toast("Sent on WhatsApp", "success");
      else {
        ctx.toast(res.hint || "WA failed", "error");
        if (res.wa_me) window.open(res.wa_me, "_blank");
      }
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

