const state = {
  mode: "party",
  from: monthStart(),
  to: today(),
  screen: "home",
  metric: "sales",
  group: "party",
  rateMin: "",
  rateMax: "",
  query: "",
  searchSeq: 0,
  holdCaret: false,
  caret: 0,
  tab: "summary",
  productId: 0,
  billId: 0,
  receiptId: 0,
  error: "",
  stack: [],
};

const titles = {
  sales: "Sales",
  purchase: "Purchase",
  receipt: "Receipt",
  payment: "Payment",
  payable: "Outstanding payable",
  receivable: "Outstanding receivable",
  cash: "Cash / bank",
  expenses: "Expenses",
};

function today() {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}
function monthStart() {
  return today().slice(0, 8) + "01";
}
function inr(value) {
  const n = Number(value) || 0;
  const text = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (n < 0 ? "−₹" : "₹") + text;
}
function qty(value) {
  if (value == null || value === "") return "";
  const n = Number(value) || 0;
  return n.toLocaleString("en-IN", { maximumFractionDigits: 2 }) + " pcs";
}
function qs(extra) {
  const p = new URLSearchParams();
  if (state.from) p.set("from_date", state.from);
  if (state.to) p.set("to_date", state.to);
  Object.entries(extra || {}).forEach(([k, v]) => { if (v != null && v !== "") p.set(k, v); });
  const s = p.toString();
  return s ? `?${s}` : "";
}
async function api(path, opts) {
  const res = await fetch(path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...((opts && opts.headers) || {}),
    },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not load");
  return data;
}
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function dates() {
  return `<div class="dates">
    <label>From<input type="date" id="from" value="${esc(state.from)}" /></label>
    <label>To<input type="date" id="to" value="${esc(state.to)}" /></label>
  </div>`;
}
function readDates() {
  state.from = document.getElementById("from")?.value || state.from;
  state.to = document.getElementById("to")?.value || state.to;
}

function modeSwitch() {
  const party = state.mode === "party" ? "on" : "";
  const items = state.mode === "items" ? "on" : "";
  const more = state.mode === "more" ? "on" : "";
  return `<div class="switch">
      <button type="button" class="${party}" data-mode="party">Party</button>
      <button type="button" class="${items}" data-mode="items">Items</button>
      <button type="button" class="${more}" data-mode="more">More</button>
    </div>`;
}

function homeView(data) {
  const tiles = [
    ["sales", "Sales", data.sales],
    ["purchase", "Purchase", data.purchase],
    ["receipt", "Receipt", data.receipt],
    ["payment", "Payment", data.payment],
    ["payable", "Outstanding payable", data.payable],
    ["receivable", "Outstanding receivable", data.receivable],
    ["cash", "Cash / bank", data.cash],
    ["expenses", "Expenses", data.expenses],
  ];
  const heads = (data.expense_heads || []).map((row) =>
    `<div class="bar-meta"><span>${esc(row.name)}</span><b>${inr(row.amount)}</b></div>`
  ).join("");
  return `<h1>Books</h1>
    ${modeSwitch()}
    ${dates()}
    <div class="tiles">
      ${tiles.map(([id, label, amount]) => `<button class="tile" data-metric="${id}"><span>${label}</span><b>${inr(amount)}</b></button>`).join("")}
    </div>
    ${heads ? `<div class="card" style="margin-top:12px;"><div class="muted">Expenses by head</div>${heads}</div>` : ""}`;
}

function bars(rows) {
  const max = Math.max(...rows.map((row) => Math.abs(Number(row.amount) || 0)), 1);
  return rows.map((row) => {
    const width = Math.max(2, (Math.abs(Number(row.amount) || 0) / max) * 100);
    const click = row.kind === "item" && row.id ? ` data-item="${row.id}"` : "";
    return `<button class="bar-row" ${click} style="display:block;width:100%;border:0;background:transparent;padding:0;text-align:left;">
      <div class="bar-meta"><span>${esc(row.label)}<br><small>${esc(row.sub || "")} ${row.qty ? esc(qty(row.qty)) : ""}</small></span><b>${inr(row.amount)}</b></div>
      <div class="track"><div class="bar" style="width:${width}%"></div></div>
    </button>`;
  }).join("");
}

function drillView(data) {
  const grouped = state.metric === "sales" || state.metric === "purchase";
  return `<button class="back" id="back">Back</button>
    <h2>${esc(titles[state.metric] || state.metric)}</h2>
    <p><b>${inr(data.total)}</b></p>
    ${dates()}
    ${grouped ? `<div class="chips">
      ${[["party", "Party"], ["item", "Item"], ["category", "Album"]].map(([id, label]) =>
        `<button type="button" class="${state.group === id ? "on" : ""}" data-group="${id}">${label}</button>`).join("")}
    </div>
    <div class="dates">
      <label>Rate from<input id="rate-min" inputmode="decimal" value="${esc(state.rateMin)}" placeholder="3" /></label>
      <label>Rate to<input id="rate-max" inputmode="decimal" value="${esc(state.rateMax)}" placeholder="5" /></label>
    </div>` : ""}
    <div class="list">${bars(data.rows || []) || `<p class="muted">Nothing in these dates.</p>`}</div>`;
}

function searchHits(items, query) {
  const rows = items || [];
  if (!rows.length) return `<p class="muted">${String(query || "").trim() ? "No match." : "Type an item number."}</p>`;
  return rows.map((item) => `<button class="hit" data-item="${item.id}">
        <strong>${esc(item.name)}</strong>
        <span class="muted">${esc(item.category || "")} ${esc(item.year_group || "")} · stock ${item.stock}</span>
      </button>`).join("");
}

function searchView(items) {
  return `<h1>Items</h1>
    ${modeSwitch()}
    <label class="search">Item number<input id="q" value="${esc(state.query)}" placeholder="9443" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" inputmode="numeric" /></label>
    <div id="item-hits" class="search-results">${searchHits(items, state.query)}</div>`;
}

function summaryStats(title, block) {
  return `<div class="card"><strong>${title}</strong>
    <div class="stats" style="margin-top:8px;">
      <div class="stat"><span>Net</span><b>${inr(block.value)}</b></div>
      <div class="stat"><span>Qty</span><b>${esc(qty(block.qty))}</b></div>
      <div class="stat"><span>Last date</span><b>${esc(block.last_date || "—")}</b></div>
      <div class="stat"><span>Last rate</span><b>${inr(block.last_rate)}</b></div>
      <div class="stat"><span>${title === "Sales" ? "Invoices" : "Receipts"}</span><b>${block.invoices ?? block.receipts ?? 0}</b></div>
    </div></div>`;
}

function itemView(data, rows) {
  const tabs = ["summary", "customer", "supplier"].map((id) =>
    `<button type="button" class="${state.tab === id ? "on" : ""}" data-tab="${id}">${id[0].toUpperCase()}${id.slice(1)}</button>`
  ).join("");
  let body = "";
  if (state.tab === "summary") {
    body = `${summaryStats("Sales", data.sales)}<div style="height:8px"></div>${summaryStats("Purchase", data.purchase)}`;
  } else {
    body = `<div class="list">${(rows || []).map((row) => {
      const idAttr = state.tab === "customer" ? `data-bill="${row.bill_id}"` : `data-receipt="${row.receipt_id}"`;
      const city = state.tab === "customer" && row.city ? ` · ${esc(row.city)}` : "";
      return `<button class="hit" ${idAttr}>
        <strong>${esc(row.party)}${city}</strong>
        <span class="muted">${esc(row.date)} · ${esc(row.bill_number || row.receipt_number || "")} · ${esc(qty(row.qty))} · ${inr(row.rate)}</span>
        <b>${inr(row.amount)}</b>
      </button>`;
    }).join("") || `<p class="muted">Nothing in these dates.</p>`}</div>`;
  }
  return `<button class="back" id="back">Back</button>
    <h2>${esc(data.name)}</h2>
    <p class="muted">Stock ${data.stock} · ${esc(data.category || "No album")} ${esc(data.vendor_item || "")}</p>
    ${dates()}
    <div class="tabs">${tabs}</div>
    ${body}`;
}

function docView(data, kind) {
  return `<button class="back" id="back">Back</button>
    <h2>${esc(data.number)}${data.cancelled ? " cancel" : ""}</h2>
    <p class="muted">${esc(data.party)} · ${esc(data.date)}</p>
    <p><b>${inr(data.total)}</b></p>
    <div class="list">${(data.lines || []).map((line) => `<button class="line" data-item="${line.product_id}">
      <strong>${esc(line.name)}</strong>
      <span class="muted">${esc(qty(line.qty))} · ${inr(line.rate)}</span>
      <b>${inr(line.amount)}</b>
    </button>`).join("")}</div>`;
}

function renderShell(html) {
  document.getElementById("app").innerHTML = html;
  bind();
}

function snapshot() {
  return {
    screen: state.screen, productId: state.productId, billId: state.billId,
    receiptId: state.receiptId, tab: state.tab, metric: state.metric, mode: state.mode,
  };
}
function restore(prev) {
  state.screen = prev.screen;
  state.productId = prev.productId;
  state.billId = prev.billId;
  state.receiptId = prev.receiptId;
  state.tab = prev.tab;
  state.metric = prev.metric;
  state.mode = prev.mode;
}
function bindOrder() {
  document.getElementById("go-order")?.addEventListener("click", () => {
    order.customer = null;
    order.lines = [];
    order.product = null;
    order.partyQ = "";
    order.itemQ = "";
    state.screen = "order";
    state.mode = "more";
    render();
  });
  document.getElementById("go-stock")?.addEventListener("click", () => {
    stockQ = "";
    state.screen = "stock";
    state.mode = "more";
    render();
  });
  document.getElementById("order-back")?.addEventListener("click", () => {
    if (order.product) {
      order.product = null;
      render();
      return;
    }
    if (order.customer) {
      order.customer = null;
      order.lines = [];
      order.product = null;
      render();
      return;
    }
    state.screen = "more";
    render();
  });
  document.getElementById("stock-back")?.addEventListener("click", () => {
    state.screen = "more";
    render();
  });
  document.getElementById("change-item")?.addEventListener("click", () => {
    order.product = null;
    render();
  });
  document.getElementById("party-q")?.addEventListener("input", (event) => {
    order.partyQ = event.target.value;
    clearTimeout(state._party);
    state._party = setTimeout(async () => {
      const q = order.partyQ.trim();
      const box = document.getElementById("party-hits");
      if (!box) return;
      if (!q) { box.innerHTML = ""; return; }
      try {
        const data = await api(`/api/v1/biz/parties?q=${encodeURIComponent(q)}`);
        if (order.partyQ.trim() !== q) return;
        box.innerHTML = (data.parties || []).map((party) =>
          `<button type="button" class="hit" data-party="${party.id}" data-label="${esc(party.label)}"><strong>${esc(party.label)}</strong></button>`
        ).join("") || `<p class="muted">No party</p>`;
        box.querySelectorAll("[data-party]").forEach((btn) => btn.addEventListener("click", () => {
          order.customer = { id: Number(btn.getAttribute("data-party")), label: btn.getAttribute("data-label") };
          order.product = null;
          render();
        }));
      } catch (e) {
        box.innerHTML = `<p class="err">${esc(e.message)}</p>`;
      }
    }, 250);
  });
  document.getElementById("order-item")?.addEventListener("input", (event) => {
    order.itemQ = event.target.value;
    clearTimeout(state._item);
    state._item = setTimeout(async () => {
      const q = order.itemQ.trim();
      const box = document.getElementById("order-hits");
      if (!box) return;
      if (!q) { box.innerHTML = ""; return; }
      try {
        const data = await api(`/api/v1/biz/items?q=${encodeURIComponent(q)}`);
        if (order.itemQ.trim() !== q) return;
        box.innerHTML = (data.items || []).slice(0, 8).map((item) =>
          `<button type="button" class="hit" data-product="${item.id}" data-name="${esc(item.name)}"><strong>${esc(item.name)}</strong></button>`
        ).join("") || `<p class="muted">No item</p>`;
        box.querySelectorAll("[data-product]").forEach((btn) => btn.addEventListener("click", () => {
          order.product = { id: Number(btn.getAttribute("data-product")), name: btn.getAttribute("data-name") };
          render();
        }));
      } catch (e) {
        box.innerHTML = `<p class="err">${esc(e.message)}</p>`;
      }
    }, 250);
  });
  document.getElementById("stock-q")?.addEventListener("input", (event) => {
    stockQ = event.target.value;
    clearTimeout(state._stock);
    state._stock = setTimeout(async () => {
      const q = stockQ.trim();
      const box = document.getElementById("stock-hits");
      if (!box) return;
      if (!q) { box.innerHTML = ""; return; }
      try {
        const data = await api(`/api/v1/biz/items?q=${encodeURIComponent(q)}`);
        if (stockQ.trim() !== q) return;
        box.innerHTML = (data.items || []).slice(0, 8).map((item) =>
          `<div class="hit"><strong>${esc(item.name)}</strong><div style="font-size:40px;font-weight:800;">${item.stock}</div></div>`
        ).join("") || `<p class="muted">No item</p>`;
      } catch (e) {
        box.innerHTML = `<p class="err">${esc(e.message)}</p>`;
      }
    }, 250);
  });
  document.querySelectorAll("[data-remove]").forEach((btn) => btn.addEventListener("click", () => {
    order.lines.splice(Number(btn.getAttribute("data-remove")), 1);
    render();
  }));
  document.getElementById("add-more")?.addEventListener("click", () => {
    const qty = Math.floor(Number(document.getElementById("order-qty")?.value || "0"));
    if (!order.product || qty < 1) return;
    const hit = order.lines.find((line) => line.id === order.product.id);
    if (hit) hit.quantity += qty;
    else order.lines.push({ id: order.product.id, name: order.product.name, quantity: qty });
    order.product = null;
    order.itemQ = "";
    render();
  });
  document.getElementById("place-order")?.addEventListener("click", async () => {
    const lines = order.lines.map((line) => ({ catalog_product_id: line.id, quantity: line.quantity }));
    const qty = Math.floor(Number(document.getElementById("order-qty")?.value || "0"));
    if (order.product) {
      if (qty < 1) return;
      const hit = lines.find((line) => line.catalog_product_id === order.product.id);
      if (hit) hit.quantity += qty;
      else lines.push({ catalog_product_id: order.product.id, quantity: qty });
    }
    if (!order.customer || !lines.length) return;
    try {
      await api("/api/v1/biz/orders", {
        method: "POST",
        body: JSON.stringify({ customer_id: order.customer.id, lines }),
      });
      order.customer = null;
      order.lines = [];
      order.product = null;
      state.screen = "more";
      render();
    } catch (e) {
      const box = document.getElementById("app");
      const note = document.createElement("p");
      note.className = "err";
      note.textContent = e.message;
      box.prepend(note);
    }
  });
}

function bind() {
  document.querySelectorAll("[data-mode]").forEach((btn) => btn.addEventListener("pointerdown", () => {
    state.holdCaret = false;
  }));
  document.querySelectorAll("[data-mode]").forEach((btn) => btn.addEventListener("click", () => {
    state.mode = btn.getAttribute("data-mode");
    state.screen = state.mode === "items" ? "search" : state.mode === "more" ? "more" : "home";
    render();
  }));
  document.querySelectorAll("[data-metric]").forEach((btn) => btn.addEventListener("click", () => {
    readDates();
    state.stack.push(snapshot());
    state.metric = btn.getAttribute("data-metric");
    state.group = "party";
    state.screen = "drill";
    render();
  }));
  document.querySelectorAll("[data-group]").forEach((btn) => btn.addEventListener("click", () => {
    state.group = btn.getAttribute("data-group");
    state.rateMin = document.getElementById("rate-min")?.value || "";
    state.rateMax = document.getElementById("rate-max")?.value || "";
    readDates();
    render();
  }));
  document.getElementById("back")?.addEventListener("click", () => {
    const prev = state.stack.pop();
    if (prev) restore(prev);
    else state.screen = state.mode === "items" ? "search" : "home";
    render();
  });
  document.querySelectorAll("[data-item]").forEach((btn) => btn.addEventListener("click", () => {
    readDates();
    state.stack.push(snapshot());
    state.productId = Number(btn.getAttribute("data-item"));
    state.tab = "summary";
    state.screen = "item";
    state.mode = "items";
    render();
  }));
  document.querySelectorAll("[data-tab]").forEach((btn) => btn.addEventListener("click", () => {
    readDates();
    state.tab = btn.getAttribute("data-tab");
    render();
  }));
  document.querySelectorAll("[data-bill]").forEach((btn) => btn.addEventListener("click", () => {
    state.stack.push(snapshot());
    state.billId = Number(btn.getAttribute("data-bill"));
    state.screen = "bill";
    render();
  }));
  document.querySelectorAll("[data-receipt]").forEach((btn) => btn.addEventListener("click", () => {
    state.stack.push(snapshot());
    state.receiptId = Number(btn.getAttribute("data-receipt"));
    state.screen = "receipt";
    render();
  }));
  const q = document.getElementById("q");
  q?.addEventListener("input", () => {
    state.holdCaret = true;
    state.query = q.value;
    state.caret = q.selectionStart ?? q.value.length;
    clearTimeout(state._t);
    state._t = setTimeout(refreshItemSearch, 200);
  });
  q?.addEventListener("keyup", () => { state.caret = q.selectionStart ?? q.value.length; });
  q?.addEventListener("blur", () => {
    if (!state.holdCaret || state.screen !== "search") return;
    placeSearchCaret(q);
  });
  ["from", "to", "rate-min", "rate-max"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", () => {
      readDates();
      state.rateMin = document.getElementById("rate-min")?.value || state.rateMin;
      state.rateMax = document.getElementById("rate-max")?.value || state.rateMax;
      render();
    });
  });
  bindOrder();
}

function placeSearchCaret(box) {
  if (!box || !box.isConnected || !state.holdCaret || state.screen !== "search" || state._placing) return;
  const pos = Number.isInteger(state.caret) ? state.caret : box.value.length;
  state._placing = true;
  try {
    if (document.activeElement !== box) box.focus({ preventScroll: true });
    box.setSelectionRange(pos, pos);
  } catch (e) { /* phone keyboard stays if focus is refused */ }
  state._placing = false;
}

function bindSearchHits() {
  document.querySelectorAll("#item-hits [data-item]").forEach((btn) => {
    btn.addEventListener("pointerdown", () => { state.holdCaret = false; });
    btn.addEventListener("click", () => {
    readDates();
    state.stack.push(snapshot());
    state.productId = Number(btn.getAttribute("data-item"));
    state.tab = "summary";
    state.screen = "item";
    state.mode = "items";
    state.holdCaret = false;
    render();
    });
  });
}

async function refreshItemSearch() {
  const seq = ++state.searchSeq;
  const query = state.query.trim();
  const list = document.getElementById("item-hits");
  const box = document.getElementById("q");
  if (!list || !box || state.screen !== "search") {
    if (state.holdCaret) return;
    return render();
  }
  try {
    const data = query ? await api(`/api/v1/biz/items?q=${encodeURIComponent(query)}`) : { items: [] };
    if (seq !== state.searchSeq || state.screen !== "search") return;
    const live = document.getElementById("q");
    const hits = document.getElementById("item-hits");
    if (!live || !hits || live !== box) return;
    hits.innerHTML = searchHits(data.items, query);
    bindSearchHits();
    placeSearchCaret(live);
  } catch (e) {
    if (seq !== state.searchSeq) return;
    const hits = document.getElementById("item-hits");
    if (hits) hits.innerHTML = `<p class="err">${esc(e.message)}</p>`;
    placeSearchCaret(document.getElementById("q"));
  }
}

const order = { customer: null, lines: [], product: null, partyQ: "", itemQ: "" };
let stockQ = "";

function moreView() {
  return `<h1>More</h1>
    ${modeSwitch()}
    <button type="button" class="big" id="go-order">Create order</button>
    <button type="button" class="big alt" id="go-stock">View stock</button>`;
}

function orderLinesHtml() {
  if (!order.lines.length) return "";
  return order.lines.map((line, i) => `<div class="hit">
    <strong>${esc(line.name)}</strong>
    <span class="muted">Qty ${line.quantity}</span>
    <button type="button" class="back" data-remove="${i}">Remove</button>
  </div>`).join("");
}

function orderView() {
  const back = `<button class="back" id="order-back">← Back</button>`;
  if (!order.customer) {
    return `${back}<h2>Party</h2>
      <label class="search">Name or number<input id="party-q" value="${esc(order.partyQ)}" placeholder="Party" /></label>
      <div id="party-hits" class="search-results"></div>`;
  }
  const lines = orderLinesHtml();
  if (!order.product) {
    return `${back}<h2>${esc(order.customer.label)}</h2>
      ${lines}
      <label class="search">Item number<input id="order-item" value="${esc(order.itemQ)}" placeholder="Item number" inputmode="numeric" /></label>
      <div id="order-hits" class="search-results"></div>
      ${order.lines.length ? `<button type="button" class="big" id="place-order">Place order</button>` : ""}`;
  }
  return `${back}<h2>${esc(order.customer.label)}</h2>
    ${lines}
    <p><b>${esc(order.product.name)}</b></p>
    <button type="button" class="back" id="change-item">Change item</button>
    <label class="search">Quantity<input id="order-qty" inputmode="numeric" placeholder="How many" /></label>
    <button type="button" class="big alt" id="add-more">Add more</button>
    <button type="button" class="big" id="place-order">Place order</button>`;
}

function stockView() {
  return `<button class="back" id="stock-back">← Back</button>
    <h2>View stock</h2>
    <label class="search">Item number<input id="stock-q" value="${esc(stockQ)}" placeholder="Item number" inputmode="numeric" /></label>
    <div id="stock-hits" class="search-results"></div>`;
}

async function render() {
  try {
    if (state.screen === "home") {
      const data = await api(`/api/v1/biz/home${qs()}`);
      return renderShell(homeView(data));
    }
    if (state.screen === "drill") {
      const data = await api(`/api/v1/biz/drill${qs({
        metric: state.metric,
        group: state.group,
        rate_min: state.rateMin,
        rate_max: state.rateMax,
      })}`);
      return renderShell(drillView(data));
    }
    if (state.screen === "search") {
      if (document.getElementById("q")) return refreshItemSearch();
      const data = state.query.trim() ? await api(`/api/v1/biz/items?q=${encodeURIComponent(state.query.trim())}`) : { items: [] };
      return renderShell(searchView(data.items));
    }
    if (state.screen === "item") {
      const data = await api(`/api/v1/biz/items/${state.productId}${qs()}`);
      let rows = [];
      if (state.tab === "customer") rows = (await api(`/api/v1/biz/items/${state.productId}/customers${qs()}`)).rows;
      if (state.tab === "supplier") rows = (await api(`/api/v1/biz/items/${state.productId}/suppliers${qs()}`)).rows;
      return renderShell(itemView(data, rows));
    }
    if (state.screen === "more") return renderShell(moreView());
    if (state.screen === "order") return renderShell(orderView());
    if (state.screen === "stock") return renderShell(stockView());
    if (state.screen === "bill") return renderShell(docView(await api(`/api/v1/biz/bills/${state.billId}`), "bill"));
    if (state.screen === "receipt") return renderShell(docView(await api(`/api/v1/biz/receipts/${state.receiptId}`), "receipt"));
  } catch (e) {
    renderShell(`<button class="back" id="back">Back</button><p class="err">${esc(e.message)}</p>`);
  }
}

function showHome() {
  state.screen = "home";
  state.mode = "party";
  return render();
}

render();
