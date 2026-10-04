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
        ${(ctx.isAdmin?.() || ctx.can?.("vendor_orders.read") || ctx.can?.("vendor_orders.write")) ? `<button type="button" class="btn btn-secondary btn-sm" onclick="App.showView('buying')">Vendor orders</button>` : ""}
        ${(ctx.isAdmin?.() || ctx.can?.("ar.read") || ctx.can?.("ar.write") || ctx.can?.("ap.read") || ctx.can?.("ap.write") || ctx.can?.("finance.write")) ? `<button type="button" class="btn btn-secondary btn-sm" onclick="App.showView('money')">Money</button>` : ""}
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
          ${(ctx.isAdmin?.() || ctx.can?.("vendor_orders.read") || ctx.can?.("vendor_orders.write")) ? `<button type="button" class="btn btn-secondary btn-sm" onclick="Dashboard.goto('orders_vendor')">Receive goods</button>` : ""}
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

    /* Money focus — backend already zeroes collect/pay to [] for staff with no
       AR/AP visibility at all (see dashboard.py's can_see_ar/can_see_ap), so gating
       this on isAdmin() too hid it from exactly the staff the backend built it for
       (e.g. an accountant handed real ar.read/ap.write access) — the length check
       below is the real gate, same as the "Cash today" section above. */
    if (collect.length || pay.length) {
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

