/** Today — do now · money · stock · recent (merged Home + work queues) */
const Dashboard = (() => {
  let ctx = {};
  let data = null;

  function init(context) { ctx = context; }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc?.(String(val)) || String(val);
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function fmtPriceExact(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc?.(String(val)) || String(val);
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function greeting() {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  }

  function showHub() {
    load();
  }

  async function load() {
    const body = document.getElementById("dashboard-body");
    if (!body) return;
    ctx.showLoading?.();
    try {
      data = await ctx.api("/dashboard", {}, 0);
      render();
    } catch (e) {
      body.innerHTML = OrdersUI.emptyState({ title: "Could not load Today", sub: e.message });
    } finally {
      ctx.hideLoading?.();
    }
  }

  function goto(target) {
    if (target === "orders_customer") {
      App.showView("selling");
      CustomerOrders?.setHubMode?.("queue");
      CustomerOrders?.setBucket?.("open");
      return;
    }
    if (target === "orders_vendor") {
      App.showView("buying");
      VendorOrders?.setHubMode?.("queue");
      VendorOrders?.setBucket?.("placed");
      return;
    }
    if (target === "finance_ar") {
      App.showView("money");
      Finance?.showAr?.();
      return;
    }
    if (target === "finance_ap") {
      App.showView("money");
      Finance?.showAp?.();
      return;
    }
    if (target === "finance_freight") {
      App.showView("money");
      Finance?.showFreight?.();
      return;
    }
    if (target === "reports_low_stock") {
      App.showView("products");
      Products?.setMainTab?.("stock");
      Products?.setAttentionFilter?.("low_stock");
      return;
    }
    if (target === "reports_today") {
      App.showView("reports");
      Reports?.setMode?.("today");
      Reports?.setChip?.("daybook");
      return;
    }
    if (target === "returns") {
      App.showView("returns");
      return;
    }
    if (target === "people_customers") {
      App.showView("people");
      App.showPeopleTab?.("customers");
      return;
    }
    if (target === "people_vendors") {
      App.showView("people");
      App.showPeopleTab?.("vendors");
      return;
    }
    if (target === "products") {
      App.showView("products");
      return;
    }
    if (target === "setup") {
      App.showView("setup");
      return;
    }
    if (target === "reports_books") {
      App.showView("reports");
      Reports?.setMode?.("books");
      Reports?.setChip?.("ledgers");
      return;
    }
  }

  const ACTION_COPY = {
    customer_orders: { label: "Bill customers", hint: "Qty ready to bill", cta: "Bill" },
    vendor_orders: { label: "Vendor orders", hint: "Receive goods or bill vendors", cta: "Open" },
    collect: { label: "Collect cash", hint: "Customer dues", cta: "Collect" },
    pay_vendors: { label: "Pay vendors", hint: "Vendor dues", cta: "Pay" },
    freight: { label: "Freight dues", hint: "Agent dues after pick", cta: "Settle" },
    low_stock: { label: "Low stock", hint: "Needs reorder attention", cta: "View" },
    returns: { label: "Returns", hint: "Last 7 days", cta: "Open" },
  };

  function barPct(part, whole) {
    const a = Math.max(0, Number(part) || 0);
    const b = Math.max(a, Number(whole) || 0);
    if (b <= 0) return 0;
    return Math.min(100, Math.round((a / b) * 100));
  }

  function pulseBars(pulse) {
    const sales = Number(pulse.sales_billed) || 0;
    const cashIn = Number(pulse.cash_in) || 0;
    const cashOut = Number(pulse.cash_out) || 0;
    const moneyMax = Math.max(sales, cashIn, cashOut, 1);
    const rows = [
      { label: "Sales", value: fmtPrice(sales), pct: barPct(sales, moneyMax), tone: "sales", sub: `${pulse.sales_count || 0} bill${(pulse.sales_count || 0) === 1 ? "" : "s"}` },
      { label: "Cash in", value: fmtPrice(cashIn), pct: barPct(cashIn, moneyMax), tone: "in", sub: "Collected" },
      { label: "Cash out", value: fmtPrice(cashOut), pct: barPct(cashOut, moneyMax), tone: "out", sub: "Vendor payments" },
    ];
    return `<div class="home-pulse-bars">
      ${rows.map(r => `
        <div class="home-pulse-row">
          <div class="home-pulse-meta">
            <span class="home-pulse-label">${r.label}</span>
            <strong class="home-pulse-val">${r.value}</strong>
          </div>
          <div class="home-pulse-track" aria-hidden="true"><span class="home-pulse-fill is-${r.tone}" style="width:${r.pct}%"></span></div>
          <span class="home-pulse-sub">${ctx.esc(r.sub)}</span>
        </div>
      `).join("")}
    </div>
    <div class="home-pulse-foot">
      <span>${pulse.purchase_count || 0} purchase${(pulse.purchase_count || 0) === 1 ? "" : "s"} today</span>
      ${(pulse.returns_today || 0) > 0 ? `<span>· ${pulse.returns_today} return${pulse.returns_today === 1 ? "" : "s"}</span>` : ""}
    </div>`;
  }

  function dueRow(item, side) {
    const settle = side === "ar"
      ? `App.showView('money');Finance.openCustomerAr(${item.id},{settle:true})`
      : `App.showView('money');Finance.openVendorAp(${item.id},{settle:true})`;
    const open = side === "ar"
      ? `App.showView('money');Finance.openCustomerAr(${item.id})`
      : `App.showView('money');Finance.openVendorAp(${item.id})`;
    return `<button type="button" class="home-due-row" onclick="${open}">
      <span class="home-due-name">${ctx.esc(item.label)}</span>
      <span class="home-due-amt">${fmtPriceExact(item.outstanding)}</span>
      <span class="home-due-go" onclick="event.stopPropagation();${settle}">${side === "ar" ? "Collect" : "Pay"}</span>
    </button>`;
  }

  function relativeTime(iso) {
    if (!iso) return "";
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return "";
    const mins = Math.round((Date.now() - t) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  }

  function render() {
    const body = document.getElementById("dashboard-body");
    if (!body || !data) return;

    const day = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "short" });
    const actions = (data.actions || []).filter(a => a.count > 0);
    const pulse = data.pulse;
    const activity = (data.activity || []).slice(0, 6);
    const collect = (data.top_collect || []).slice(0, 4);
    const pay = (data.top_pay || []).slice(0, 4);

    let html = `<div class="home-page">`;

    html += `<header class="home-top">
      <div>
        <p class="home-kicker">${ctx.esc(day)}</p>
        <h2 class="home-title">${greeting()}</h2>
        <p class="home-sub">${actions.length
          ? `${actions.length} thing${actions.length === 1 ? "" : "s"} need you`
          : "You’re all clear for now"}</p>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button type="button" class="btn btn-secondary btn-sm" onclick="App.showView('selling')">Customer orders</button>
        <button type="button" class="btn btn-secondary btn-sm" onclick="App.showView('buying')">Vendor orders</button>
        ${ctx.isAdmin?.() ? `<button type="button" class="btn btn-secondary btn-sm" onclick="App.showView('money')">Money</button>` : ""}
        <button type="button" class="btn btn-ghost btn-sm" onclick="Dashboard.load()">Refresh</button>
      </div>
    </header>`;

    /* Do now */
    html += `<section class="home-card">
      <div class="home-card-head">
        <h3>Do now</h3>
        ${actions.length ? `<span class="home-count">${actions.length}</span>` : ""}
      </div>`;
    if (!actions.length) {
      html += `<div class="home-clear">
        <p class="home-clear-title">All clear</p>
        <p class="home-clear-sub">When orders or dues pile up, they show here.</p>
        <div class="home-clear-actions">
          <button type="button" class="btn btn-secondary btn-sm" onclick="Dashboard.goto('orders_customer')">Bill customer</button>
          <button type="button" class="btn btn-secondary btn-sm" onclick="Dashboard.goto('orders_vendor')">Receive goods</button>
        </div>
      </div>`;
    } else {
      html += `<div class="home-action-list">
        ${actions.map(a => {
          const copy = ACTION_COPY[a.id] || { label: a.label, hint: "", cta: a.cta || "Open" };
          const meta = a.amount != null
            ? `${fmtPriceExact(a.amount)} · ${a.count} part${a.count === 1 ? "y" : "ies"}`
            : `${a.count} item${a.count === 1 ? "" : "s"}`;
          return `<button type="button" class="home-action is-${a.tone || "muted"}" onclick="Dashboard.goto('${a.goto}')">
            <span class="home-action-count">${a.count > 99 ? "99+" : a.count}</span>
            <span class="home-action-text">
              <strong>${ctx.esc(copy.label)}</strong>
              <span>${ctx.esc(copy.hint || meta)}</span>
            </span>
            <span class="home-action-meta">${ctx.esc(meta)}</span>
            <span class="home-action-cta">${ctx.esc(copy.cta)}</span>
          </button>`;
        }).join("")}
      </div>`;
    }
    html += `</section>`;

    /* Cash today */
    if (pulse) {
      html += `<section class="home-card">
        <div class="home-card-head">
          <h3>Cash today</h3>
          <button type="button" class="btn btn-ghost btn-sm" onclick="Dashboard.goto('reports_today')">Daybook →</button>
        </div>
        ${pulseBars(pulse)}
      </section>`;
    }

    /* Money focus (admin) */
    if (ctx.isAdmin?.() && (collect.length || pay.length)) {
      html += `<section class="home-money">
        <div class="home-card">
          <div class="home-card-head">
            <h3>Collect next</h3>
            <button type="button" class="btn btn-ghost btn-sm" onclick="Dashboard.goto('finance_ar')">All →</button>
          </div>
          ${collect.length
            ? `<div class="home-due-list">${collect.map(c => dueRow(c, "ar")).join("")}</div>`
            : `<p class="home-empty-line">No customer dues</p>`}
        </div>
        <div class="home-card">
          <div class="home-card-head">
            <h3>Pay next</h3>
            <button type="button" class="btn btn-ghost btn-sm" onclick="Dashboard.goto('finance_ap')">All →</button>
          </div>
          ${pay.length
            ? `<div class="home-due-list">${pay.map(v => dueRow(v, "ap")).join("")}</div>`
            : `<p class="home-empty-line">No vendor dues</p>`}
        </div>
      </section>`;
    }

    /* Recent */
    html += `<section class="home-card">
      <div class="home-card-head">
        <h3>Just now</h3>
      </div>`;
    if (!activity.length) {
      html += `<p class="home-empty-line">No recent activity yet.</p>`;
    } else {
      html += `<ul class="home-timeline">
        ${activity.map(e => {
          const what = [e.entity_label || e.entity_type, e.action].filter(Boolean).join(" · ");
          return `<li>
            <span class="home-tl-dot" aria-hidden="true"></span>
            <div class="home-tl-body">
              <strong>${ctx.esc(what || e.detail || "Update")}</strong>
              <span>${ctx.esc(e.actor_name || "—")} · ${relativeTime(e.created_at)}</span>
            </div>
          </li>`;
        }).join("")}
      </ul>`;
    }
    html += `</section>`;

    html += `</div>`;
    body.innerHTML = html;
  }

  return { init, showHub, load, goto };
})();
