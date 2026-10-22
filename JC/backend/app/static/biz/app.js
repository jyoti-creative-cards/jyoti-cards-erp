const tokenKey = "jc_biz_token";
const state = {
  token: localStorage.getItem(tokenKey) || "",
  mode: "party",
  from: monthStart(),
  to: today(),
  screen: "home",
  metric: "sales",
  group: "party",
  rateMin: "",
  rateMax: "",
  query: "",
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
      ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
      ...((opts && opts.headers) || {}),
    },
  });
  if (res.status === 401 && !path.includes("/auth/staff/login")) {
    state.token = "";
    localStorage.removeItem(tokenKey);
    state.screen = "login";
    render();
    throw new Error("Sign in again");
  }
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

async function login(phone, password) {
  const data = await api("/api/v1/auth/staff/login", {
    method: "POST",
    body: JSON.stringify({ phone, password }),
  });
  state.token = data.access_token;
  localStorage.setItem(tokenKey, state.token);
  state.screen = "home";
  state.error = "";
}

function loginView() {
  return `<h1>JC Books</h1>
    <p class="muted">Staff login. Same mobile and password as the admin app.</p>
    <label>Mobile or name<input id="phone" autocomplete="username" /></label>
    <label>Password<input id="password" type="password" autocomplete="current-password" /></label>
    ${state.error ? `<p class="err">${esc(state.error)}</p>` : ""}
    <button class="primary" id="go">Sign in</button>`;
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
    <div class="switch">
      <button type="button" class="${state.mode === "party" ? "on" : ""}" data-mode="party">Party</button>
      <button type="button" class="${state.mode === "items" ? "on" : ""}" data-mode="items">Items</button>
    </div>
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

function searchView(items) {
  return `<h1>Items</h1>
    <div class="switch">
      <button type="button" data-mode="party">Party</button>
      <button type="button" class="on" data-mode="items">Items</button>
    </div>
    <label class="search">Item number<input id="q" value="${esc(state.query)}" placeholder="9443" /></label>
    <div class="list">
      ${(items || []).map((item) => `<button class="hit" data-item="${item.id}">
        <strong>${esc(item.name)}</strong>
        <span class="muted">${esc(item.category || "")} ${esc(item.year_group || "")} · stock ${item.stock}</span>
      </button>`).join("") || `<p class="muted">Type an item number.</p>`}
    </div>`;
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
      return `<button class="hit" ${idAttr}>
        <strong>${esc(row.party)}</strong>
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
function bind() {
  document.getElementById("go")?.addEventListener("click", async () => {
    try {
      await login(document.getElementById("phone").value.trim(), document.getElementById("password").value);
      await showHome();
    } catch (e) { state.error = e.message; render(); }
  });
  document.querySelectorAll("[data-mode]").forEach((btn) => btn.addEventListener("click", () => {
    state.mode = btn.getAttribute("data-mode");
    state.screen = state.mode === "items" ? "search" : "home";
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
    state.query = q.value;
    clearTimeout(state._t);
    state._t = setTimeout(render, 250);
  });
  ["from", "to", "rate-min", "rate-max"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", () => {
      readDates();
      state.rateMin = document.getElementById("rate-min")?.value || state.rateMin;
      state.rateMax = document.getElementById("rate-max")?.value || state.rateMax;
      render();
    });
  });
}

async function render() {
  if (!state.token) return renderShell(loginView());
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
    if (state.screen === "bill") return renderShell(docView(await api(`/api/v1/biz/bills/${state.billId}`), "bill"));
    if (state.screen === "receipt") return renderShell(docView(await api(`/api/v1/biz/receipts/${state.receiptId}`), "receipt"));
  } catch (e) {
    if (!state.token) return;
    renderShell(`<button class="back" id="back">Back</button><p class="err">${esc(e.message)}</p>`);
  }
}

function showHome() {
  state.screen = "home";
  state.mode = "party";
  return render();
}

render();
