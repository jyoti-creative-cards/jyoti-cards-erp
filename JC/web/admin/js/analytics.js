/** Admin analytics. Staff never see this screen. */
const Analytics = (() => {
  let screen = "hub";
  let choices = null;
  let stockPick = { from: "", year: "", categories: [] };
  let salePick = { from: "", to: "" };
  let partyPick = { from: "", to: "" };
  let stockRows = [];
  let saleRows = [];
  let partyRows = [];
  let alertRows = [];
  let alertQuery = "";
  let openItem = null;

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  function root() {
    return document.getElementById("analytics-root");
  }

  function qs(params) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (Array.isArray(value)) value.forEach((item) => { if (item) query.append(key, item); });
      else if (value) query.set(key, value);
    });
    const text = query.toString();
    return text ? `?${text}` : "";
  }

  function open() {
    screen = "hub";
    openItem = null;
    render();
  }

  function render() {
    const host = root();
    if (!host) return;
    if (screen === "hub") host.innerHTML = hubHtml();
    else if (screen === "stock") host.innerHTML = stockHtml();
    else if (screen === "sales") host.innerHTML = saleHtml();
    else if (screen === "parties") host.innerHTML = partyHtml();
    else if (screen === "threshold") host.innerHTML = openItem ? detailHtml() : thresholdHtml();
  }

  function hubHtml() {
    return `<div class="ui-hub-intro">
      <h2 class="ui-hub-title">Analytics</h2>
      <p class="ui-hub-sub">Stock, collections, and parties. Admin only.</p>
    </div>
    <div class="setup-grid">
      ${tile("stock", "S", "Stock management", "Inward, outward, and today's stock")}
      ${tile("sales", "C", "Sale to balance", "How much is already collected")}
      ${tile("parties", "P", "Parties", "Every party we still do business with")}
      ${tile("threshold", "%", "Item threshold", "Stock under the alert percent")}
    </div>`;
  }

  function tile(name, letter, title, desc) {
    return `<button type="button" class="big-tile ui-tile setup-tile" onclick="Analytics.show('${name}')">
      <span class="big-tile-letter">${letter}</span>
      <span class="big-tile-title">${title}</span>
      <span class="big-tile-desc">${desc}</span>
    </button>`;
  }

  function show(name) {
    screen = name;
    openItem = null;
    render();
    if (name === "stock") loadStock();
    else if (name === "sales") loadSales();
    else if (name === "parties") loadParties();
    else if (name === "threshold") loadThreshold();
  }

  function back() {
    if (openItem) {
      openItem = null;
      render();
      return;
    }
    screen = "hub";
    render();
  }

  function tools(kind) {
    return `<div class="ui-toolbar" style="display:flex;gap:8px;flex-wrap:wrap;margin:12px 0;">
      <button type="button" class="btn btn-secondary btn-sm" onclick="Analytics.back()">← Back</button>
      <button type="button" class="btn btn-primary btn-sm" onclick="Analytics.printReport('${kind}')">Print</button>
      <button type="button" class="btn btn-secondary btn-sm" onclick="Analytics.downloadPdf('${kind}')">PDF</button>
      <button type="button" class="btn btn-secondary btn-sm" onclick="Analytics.excel('${kind}')">Excel</button>
    </div>`;
  }

  function stockHtml() {
    const years = (choices?.year_groups || []).map((year) =>
      `<option value="${esc(year)}" ${year === stockPick.year ? "selected" : ""}>${esc(year)}</option>`).join("");
    const cats = (choices?.categories || []).map((cat) =>
      `<label style="display:flex;gap:6px;align-items:center;margin:4px 0;">
        <input type="checkbox" value="${esc(cat)}" ${stockPick.categories.includes(cat) ? "checked" : ""} onchange="Analytics.toggleCategory(this)">
        ${esc(cat)}
      </label>`).join("") || `<div style="color:var(--muted);">No categories yet.</div>`;
    return `<h2 class="ui-hub-title">Stock management</h2>
      <p class="ui-hub-sub">From the start date through today. Closing stock is what is in the godown today. Closing value uses the purchase rate.</p>
      ${tools("stock")}
      <div class="card" style="padding:12px;margin-bottom:12px;display:flex;gap:16px;flex-wrap:wrap;align-items:flex-end;">
        <label>Start date<br><input type="date" id="an-stock-from" value="${esc(stockPick.from)}" onchange="Analytics.pickStock()"></label>
        <label>Year group<br><select id="an-stock-year" onchange="Analytics.pickStock()"><option value="">All</option>${years}</select></label>
        <details><summary>Categories</summary><div style="max-height:220px;overflow:auto;padding-top:6px;">${cats}</div></details>
      </div>
      <div class="card table-wrap"><table class="data"><thead><tr>
        <th>Item</th><th>Alias</th><th>Party</th><th>Category 1</th><th>Category 2</th><th>Category 3</th>
        <th>Bills</th><th>Inward</th><th>Outward</th><th>Closing stock</th><th>Closing value</th><th>%</th><th>Last received</th>
      </tr></thead><tbody id="an-stock-body"><tr><td colspan="13">Loading…</td></tr></tbody></table></div>`;
  }

  function saleHtml() {
    return `<h2 class="ui-hub-title">Sale to balance</h2>
      <p class="ui-hub-sub">Collected % is money already received, divided by the sale. Sold 100 and received 20 is 20%.</p>
      ${tools("sales")}
      ${rangeHtml("sale", salePick)}
      <div class="card table-wrap"><table class="data"><thead><tr>
        <th>Party</th><th>City</th><th>Sale</th><th>Balance</th><th>Collected %</th><th>Last payment</th><th>Receipts</th>
      </tr></thead><tbody id="an-sale-body"><tr><td colspan="7">Loading…</td></tr></tbody></table></div>`;
  }

  function partyHtml() {
    return `<h2 class="ui-hub-title">Parties</h2>
      <p class="ui-hub-sub">Every party we still do business with. Switched-off parties stay out. Last payment is the latest receipt.</p>
      ${tools("parties")}
      ${rangeHtml("party", partyPick)}
      <div class="card table-wrap"><table class="data"><thead><tr>
        <th>Party</th><th>City</th><th>Bills</th><th>Sale</th><th>Albums sent</th><th>Balance</th><th>Last payment</th>
      </tr></thead><tbody id="an-party-body"><tr><td colspan="7">Loading…</td></tr></tbody></table></div>`;
  }

  function rangeHtml(kind, pick) {
    return `<div class="card" style="padding:12px;margin-bottom:12px;display:flex;gap:16px;flex-wrap:wrap;">
      <label>From<br><input type="date" id="an-${kind}-from" value="${esc(pick.from)}" onchange="Analytics.pickRange('${kind}')"></label>
      <label>To<br><input type="date" id="an-${kind}-to" value="${esc(pick.to)}" onchange="Analytics.pickRange('${kind}')"></label>
    </div>`;
  }

  function thresholdHtml() {
    const rows = alertRows.map((row) => `<tr class="clickable" onclick="Analytics.openProduct(${row.id})">
      <td>${esc(row.item)}</td><td>${esc(row.alias)}</td><td>${esc(row.party)}</td>
      <td>${esc(row.inward)}</td><td>${esc(row.closing_stock)}</td>
      <td onclick="event.stopPropagation()"><input type="number" min="0" max="10000" step="0.01" value="${esc(row.percent)}" style="width:80px;" id="an-pct-${row.id}">
        <button type="button" class="btn btn-secondary btn-sm" onclick="Analytics.savePercent(${row.id})">Save</button></td>
      <td>${row.below ? "Yes" : ""}</td>
    </tr>`).join("");
    return `<h2 class="ui-hub-title">Item threshold</h2>
      <p class="ui-hub-sub">Shown when today's stock is under the percent of everything received so far. A blank saved percent means 20.</p>
      ${tools("threshold")}
      <div class="card" style="padding:12px;margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
        <input id="an-alert-q" placeholder="Search an item" value="${esc(alertQuery)}" oninput="Analytics.searchAlert()" style="min-width:220px;">
        <button type="button" class="btn btn-secondary btn-sm" onclick="Analytics.applyDefault()">Set 20% on every item</button>
      </div>
      <div class="card table-wrap"><table class="data"><thead><tr>
        <th>Item</th><th>Alias</th><th>Party</th><th>Received</th><th>Closing stock</th><th>Alert %</th><th>Below</th>
      </tr></thead><tbody id="an-alert-body">${rows || `<tr><td colspan="7">Nothing is under its alert.</td></tr>`}</tbody></table></div>`;
  }

  function detailHtml() {
    const item = openItem;
    const bills = (item.bills || []).map((bill) => `<tr class="clickable" onclick="Analytics.openBill(${bill.bill_id})">
      <td>${esc(bill.bill_number)}</td><td>${esc(bill.bill_date)}</td><td>${esc(bill.party)}</td><td>${esc(bill.city)}</td>
      <td>${esc(bill.quantity)}</td><td>${esc(bill.rate)}</td><td>${esc(bill.amount)}</td>
    </tr>`).join("");
    return `<h2 class="ui-hub-title">${esc(item.item)}</h2>
      <p class="ui-hub-sub">${esc(item.party)} ${item.alias ? "· " + esc(item.alias) : ""} · received ${esc(item.inward)} · closing ${esc(item.closing_stock)}</p>
      <div class="ui-toolbar" style="display:flex;gap:8px;flex-wrap:wrap;margin:12px 0;align-items:center;">
        <button type="button" class="btn btn-secondary btn-sm" onclick="Analytics.back()">← Back</button>
        <label>Alert % <input type="number" min="0" max="10000" step="0.01" id="an-detail-pct" value="${esc(item.percent)}" style="width:90px;"></label>
        <button type="button" class="btn btn-primary btn-sm" onclick="Analytics.savePercent(${item.id}, true)">Save</button>
      </div>
      <div class="card" style="padding:12px;margin-bottom:12px;">${esc(item.category_1)} ${esc(item.category_2)} ${esc(item.category_3)}</div>
      <div class="card table-wrap"><table class="data"><thead><tr>
        <th>Bill</th><th>Date</th><th>Who bought</th><th>City</th><th>Qty</th><th>Rate</th><th>Amount</th>
      </tr></thead><tbody>${bills || `<tr><td colspan="7">No bills for this item.</td></tr>`}</tbody></table></div>`;
  }

  async function loadChoices() {
    if (choices) return;
    choices = await App.api("/analytics/filters");
  }

  function toggleCategory(input) {
    const value = input.value;
    const set = new Set(stockPick.categories);
    if (input.checked) set.add(value);
    else set.delete(value);
    stockPick.categories = [...set];
    loadStock();
  }

  function pickStock() {
    stockPick.from = document.getElementById("an-stock-from")?.value || "";
    stockPick.year = document.getElementById("an-stock-year")?.value || "";
    loadStock();
  }

  function pickRange(kind) {
    const pick = kind === "sale" ? salePick : partyPick;
    pick.from = document.getElementById(`an-${kind}-from`)?.value || "";
    pick.to = document.getElementById(`an-${kind}-to`)?.value || "";
    if (kind === "sale") loadSales();
    else loadParties();
  }

  function stockQuery() {
    return qs({ from_date: stockPick.from, year_group: stockPick.year, categories: stockPick.categories });
  }

  async function loadStock() {
    try {
      if (!choices) {
        await loadChoices();
        if (screen === "stock") render();
      }
      const data = await App.api(`/analytics/stock${stockQuery()}`);
      stockRows = data.items || [];
      const body = document.getElementById("an-stock-body");
      if (!body) return;
      body.innerHTML = stockRows.map((row) => `<tr>
        <td>${esc(row.item)}</td><td>${esc(row.alias)}</td><td>${esc(row.party)}</td>
        <td>${esc(row.category_1)}</td><td>${esc(row.category_2)}</td><td>${esc(row.category_3)}</td>
        <td>${esc(row.bills)}</td><td>${esc(row.inward)}</td><td>${esc(row.outward)}</td>
        <td>${esc(row.closing_stock)}</td><td>${esc(row.closing_value)}</td><td>${esc(row.percent)}</td><td>${esc(row.last_received)}</td>
      </tr>`).join("") || `<tr><td colspan="13">Nothing in this range.</td></tr>`;
    } catch (err) { App.toast(err.message || "Could not load stock", "error"); }
  }

  async function loadSales() {
    try {
      const data = await App.api(`/analytics/sales${qs({ from_date: salePick.from, to_date: salePick.to })}`);
      saleRows = data.items || [];
      const body = document.getElementById("an-sale-body");
      if (!body) return;
      body.innerHTML = saleRows.map((row) => `<tr>
        <td>${esc(row.party)}</td><td>${esc(row.city)}</td><td>${esc(row.sale)}</td><td>${esc(row.balance)}</td>
        <td>${esc(row.collected_percent)}</td><td>${esc(row.last_payment)}</td><td>${esc(row.receipts)}</td>
      </tr>`).join("") || `<tr><td colspan="7">Nothing in this range.</td></tr>`;
    } catch (err) { App.toast(err.message || "Could not load sales", "error"); }
  }

  async function loadParties() {
    try {
      const data = await App.api(`/analytics/parties${qs({ from_date: partyPick.from, to_date: partyPick.to })}`);
      partyRows = data.items || [];
      const body = document.getElementById("an-party-body");
      if (!body) return;
      body.innerHTML = partyRows.map((row) => `<tr>
        <td>${esc(row.party)}</td><td>${esc(row.city)}</td><td>${esc(row.bills)}</td><td>${esc(row.sale)}</td>
        <td>${esc(row.albums)}</td><td>${esc(row.balance)}</td><td>${esc(row.last_payment)}</td>
      </tr>`).join("") || `<tr><td colspan="7">No active parties.</td></tr>`;
    } catch (err) { App.toast(err.message || "Could not load parties", "error"); }
  }

  let searchTimer = null;
  function searchAlert() {
    alertQuery = document.getElementById("an-alert-q")?.value || "";
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadThreshold, 250);
  }

  async function loadThreshold() {
    try {
      const data = await App.api(`/analytics/threshold${qs({ q: alertQuery })}`);
      alertRows = data.items || [];
      const body = document.getElementById("an-alert-body");
      if (!body) {
        if (screen === "threshold" && !openItem) render();
        return;
      }
      const rows = alertRows.map((row) => `<tr class="clickable" onclick="Analytics.openProduct(${row.id})">
        <td>${esc(row.item)}</td><td>${esc(row.alias)}</td><td>${esc(row.party)}</td>
        <td>${esc(row.inward)}</td><td>${esc(row.closing_stock)}</td>
        <td onclick="event.stopPropagation()"><input type="number" min="0" max="10000" step="0.01" value="${esc(row.percent)}" style="width:80px;" id="an-pct-${row.id}">
          <button type="button" class="btn btn-secondary btn-sm" onclick="Analytics.savePercent(${row.id})">Save</button></td>
        <td>${row.below ? "Yes" : ""}</td>
      </tr>`).join("");
      body.innerHTML = rows || `<tr><td colspan="7">Nothing is under its alert.</td></tr>`;
    } catch (err) { App.toast(err.message || "Could not load the threshold", "error"); }
  }

  async function openProduct(id) {
    try {
      openItem = await App.api(`/analytics/threshold/${id}`);
      render();
    } catch (err) { App.toast(err.message || "Could not open the item", "error"); }
  }

  async function savePercent(id, fromDetail) {
    const input = document.getElementById(fromDetail ? "an-detail-pct" : `an-pct-${id}`);
    const percent = Number(input?.value);
    if (!Number.isFinite(percent) || percent < 0) {
      App.toast("Enter a percent", "error");
      return;
    }
    try {
      const saved = await App.api(`/analytics/threshold/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ percent }),
      });
      if (fromDetail) openItem = saved;
      App.toast("Alert percent saved");
      await loadThreshold();
      if (fromDetail) render();
    } catch (err) { App.toast(err.message || "Could not save", "error"); }
  }

  async function applyDefault() {
    try {
      await App.api("/analytics/threshold/defaults", { method: "POST", body: JSON.stringify({ percent: 20 }) });
      App.toast("Every item is set to 20%");
      await loadThreshold();
    } catch (err) { App.toast(err.message || "Could not set 20%", "error"); }
  }

  function openBill(id) {
    if (window.Finance?.viewCustomerBill) Finance.viewCustomerBill(id);
  }

  function reportPath(kind) {
    if (kind === "stock") return `/analytics/stock/pdf${stockQuery()}`;
    if (kind === "sales") return `/analytics/sales/pdf${qs({ from_date: salePick.from, to_date: salePick.to })}`;
    if (kind === "parties") return `/analytics/parties/pdf${qs({ from_date: partyPick.from, to_date: partyPick.to })}`;
    return `/analytics/threshold/pdf${qs({ q: alertQuery })}`;
  }

  async function printReport(kind) {
    try { await DocShare.openPdf(reportPath(kind), { print: true, filename: `${kind}.pdf` }); }
    catch (err) { App.toast(err.message || "Could not print", "error"); }
  }

  async function downloadPdf(kind) {
    try { await DocShare.openPdf(reportPath(kind), { print: false, filename: `${kind}.pdf` }); }
    catch (err) { App.toast(err.message || "Could not download", "error"); }
  }

  function excel(kind) {
    const sheets = {
      stock: [["Item", "Alias", "Party", "Category 1", "Category 2", "Category 3", "Bills", "Inward", "Outward", "Closing stock", "Closing value", "%", "Last received"],
        ...stockRows.map((row) => [row.item, row.alias, row.party, row.category_1, row.category_2, row.category_3, row.bills, row.inward, row.outward, row.closing_stock, row.closing_value, row.percent, row.last_received])],
      sales: [["Party", "City", "Sale", "Balance", "Collected %", "Last payment", "Receipts"],
        ...saleRows.map((row) => [row.party, row.city, row.sale, row.balance, row.collected_percent, row.last_payment, row.receipts])],
      parties: [["Party", "City", "Bills", "Sale", "Albums sent", "Balance", "Last payment"],
        ...partyRows.map((row) => [row.party, row.city, row.bills, row.sale, row.albums, row.balance, row.last_payment])],
      threshold: [["Item", "Alias", "Party", "Received", "Closing stock", "Alert %", "Below"],
        ...alertRows.map((row) => [row.item, row.alias, row.party, row.inward, row.closing_stock, row.percent, row.below ? "Yes" : ""])],
    };
    Xlsx.download(kind, sheets[kind] || [[]]);
  }

  return {
    open, show, back, toggleCategory, pickStock, pickRange, searchAlert,
    openProduct, savePercent, applyDefault, openBill, printReport, downloadPdf, excel,
  };
})();
