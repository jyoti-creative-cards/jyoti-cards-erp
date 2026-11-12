/** Orders: one list, many open forms, the same saves as a single order. */
const OrderDesk = (() => {
  const L = () => OrderDeskLogic;
  let filter = "new";
  let dateFrom = "";
  let dateTo = "";
  let raw = [];
  let selected = {};
  let forms = {};
  let saving = false;
  let shared = { ready: false, agents: [], series: [], items: [] };

  function esc(s) {
    return (typeof HubUI !== "undefined" && HubUI.esc) ? HubUI.esc(s) : String(s ?? "");
  }
  function toast(msg, kind) { App.toast?.(msg, kind || "error"); }
  function api(path, opts) { return App.api(path, opts || {}, 0); }
  function today() {
    const n = new Date();
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
  }
  function listDay() {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Kolkata",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  }
  function anyDayEdit() {
    const app = document.getElementById("app");
    if (!app) return false;
    return !(app.classList.contains("order-desk") || app.classList.contains("order-taker") || app.classList.contains("lookup-only") || app.classList.contains("sticker-only"));
  }
  function money(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "";
    return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function visibleRows() {
    return (raw || []).filter(row => L().inDateRange(L().orderDay(row), dateFrom, dateTo));
  }
  function keyOf(row) {
    if (filter === "billed" || filter === "dispatched") return "b" + row.bill_id;
    return "c" + row.customer_id;
  }
  function selectedKeys() {
    return visibleRows().map(keyOf).filter(k => selected[k]);
  }

  async function ensureShared() {
    if (shared.ready) return;
    const [agents, series, items] = await Promise.all([
      api("/freight-agents?names_only=1"),
      api("/bill-series"),
      api("/stock/entry-items"),
    ]);
    shared.agents = agents || [];
    shared.series = (series || []).filter(s => s.is_active && s.current_num < s.end_num);
    shared.items = items || [];
    shared.ready = true;
    try { await api("/bill-series/ensure-next", { method: "POST" }); } catch (_) {}
  }

  function findItem(q) {
    const needle = String(q || "").trim().toLowerCase();
    if (!needle) return [];
    const scored = [];
    for (const p of shared.items || []) {
      const id = String(p.our_product_id || "").toLowerCase();
      const alias = String(p.vendor_product_id || "").toLowerCase();
      const number = id.split(" ")[0];
      let score = 0;
      if (id === needle || number === needle) score = 300;
      else if (alias && alias === needle) score = 100;
      else if (id.startsWith(needle)) score = 80;
      else if (alias && alias.startsWith(needle)) score = 60;
      else if (id.includes(needle) || (alias && alias.includes(needle))) score = 40;
      else continue;
      scored.push({ p, score, id });
    }
    scored.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
    return scored.slice(0, 8).map(x => x.p);
  }

  function partyHtml(p) {
    if (!p) return "";
    const num = p.party_number ? "#" + p.party_number + " " : "";
    const name = p.customer_name || p.customer_label || "";
    const city = p.city_name || p.customer_city ? ` · ${esc(p.city_name || p.customer_city)}` : "";
    let badges = "";
    if (p.marker_1) badges += ` <span class="badge badge-blue" style="font-size:11px;">${esc(p.marker_1)}</span>`;
    if (p.marker_2) badges += ` <span class="badge badge-amber" style="font-size:11px;">${esc(p.marker_2)}</span>`;
    if (String(p.payment_type || "").toUpperCase() === "CASH") badges += ` <span class="badge badge-amber" style="font-size:11px;">CASH</span>`;
    return `<p style="margin:0 0 8px;"><strong>${esc(num)}${esc(name)}${city}</strong>${badges}</p>`;
  }

  function rowTitle(row) {
    if (filter === "billed" || filter === "dispatched") {
      const city = row.customer_city ? ` · ${esc(row.customer_city)}` : "";
      return `${esc(row.customer_label || "Customer")}${city}`;
    }
    const num = row.party_number ? "#" + row.party_number + " " : "";
    const city = row.city_name ? ` · ${esc(row.city_name)}` : "";
    return `${esc(num)}${esc(row.customer_name || "")}${city}`;
  }
  function rowMeta(row) {
    if (filter === "billed" || filter === "dispatched") {
      const bits = [
        row.bill_number ? `Bill ${row.bill_number}` : "",
        row.transport_mode || "",
        row.freight_agent_name || "",
        row.total_pcs ? `${row.total_pcs} pcs` : "",
        L().orderDay(row),
      ].filter(Boolean);
      const lines = (row.lines || []).slice(0, 6).map(l => `${l.our_product_id} × ${l.quantity}`).join(" · ");
      return `${esc(bits.join(" · "))}${lines ? `<div>${esc(lines)}</div>` : ""}`;
    }
    const bits = [L().orderDay(row), row.total_quantity ? `${row.total_quantity} pcs` : "", row.amount ? money(row.amount) : ""].filter(Boolean);
    let badges = "";
    if (row.marker_1) badges += ` <span class="badge badge-blue" style="font-size:11px;">${esc(row.marker_1)}</span>`;
    if (row.marker_2) badges += ` <span class="badge badge-amber" style="font-size:11px;">${esc(row.marker_2)}</span>`;
    const mark = row.marking ? `<div style="color:#b91c1c;font-weight:700;">${esc(row.marking)}</div>` : "";
    return `${esc(bits.join(" · "))}${badges}${mark}`;
  }

  function addonHtml(key, line, kind) {
    const addons = line.addons || [];
    if (!addons.length) return "";
    const skipped = new Set((line.skip_addon_ids || []).map(Number));
    return addons.map(a => {
      const id = Number(a.addon_product_id);
      const name = a.name || a.our_product_id || "Add-on";
      const off = skipped.has(id);
      const act = kind === "confirm" ? "toggleConfirmAddon" : "toggleBillAddon";
      return `<div class="co-addon-row">${off ? esc(name) + " removed" : "+ " + esc(name)} · <button type="button" class="btn btn-ghost btn-sm" onclick="OrderDesk.${act}('${key}', ${line.catalog_product_id}, ${id})">${off ? "Add" : "Remove"}</button></div>`;
    }).join("");
  }

  function confirmFormHtml(key, f) {
    const lines = (f.lines || []).map((ln, i) => `<tr>
      <td><strong>${esc(ln.our_product_id)}</strong>${addonHtml(key, ln, "confirm")}</td>
      <td>${ln.stock ?? "—"}</td>
      <td>${money(ln.unit_price)}</td>
      <td><input data-field="cqty" data-i="${i}" type="number" class="input" style="width:72px;" min="${ln.min_qty || 0}" value="${ln.quantity}"></td>
      <td><button type="button" class="btn btn-ghost btn-sm" onclick="OrderDesk.removeConfirmLine('${key}', ${i})">Remove</button></td>
    </tr>`).join("");
    const hits = findItem(f.search || "").map(p =>
      `<button type="button" class="btn btn-secondary btn-sm" style="display:block;width:100%;text-align:left;margin-top:4px;" onclick="OrderDesk.addConfirmItem('${key}', ${p.catalog_product_id})">${esc(p.our_product_id)} · stock ${p.quantity_on_hand ?? 0}</button>`
    ).join("");
    return `${partyHtml(f.party)}
      ${f.otherCount ? `<p style="margin:0 0 8px;font-size:13px;color:var(--muted);">Other new orders for this party confirm with this one.</p>` : ""}
      <table class="data"><thead><tr><th>Item</th><th>Stock</th><th>Rate</th><th>Qty</th><th></th></tr></thead>
      <tbody>${lines || `<tr><td colspan="5">No items.</td></tr>`}</tbody></table>
      <label class="label">Add item</label>
      <input class="input" data-field="csearch" value="${esc(f.search || "")}" placeholder="Item number" oninput="OrderDesk.setConfirmSearch('${key}', this.value)">
      <div>${hits}</div>
      <label class="label">Date</label>
      <input type="date" class="input" data-field="cdate" value="${esc(f.placedOn || "")}">
      <label class="label">Marking</label>
      <textarea class="input" data-field="cmark" rows="3" style="background:#fee2e2;border:1px solid #dc2626;font-weight:800;color:#b91c1c;">${esc(f.narration || "")}</textarea>
      ${f.error ? `<p style="color:#b91c1c;font-weight:700;">${esc(f.error)}</p>` : ""}
      ${f.duplicateHtml || ""}`;
  }

  function billFormHtml(key, f) {
    const ro = (!f.discountEnabled || f.useOverallDiscount) ? "readonly" : "";
    const lines = (f.lines || []).map((ln, i) => {
      const shownNet = f.useOverallDiscount && f.overallDiscount
        ? L().calcNetFromDisc(ln.unit_price, f.overallDiscount)
        : (ln.net_rate || L().calcNetFromDisc(ln.unit_price, ln.discount_percent || 0));
      const shownDisc = f.useOverallDiscount ? (f.overallDiscount || "") : (ln.discount_percent || "");
      return `<tr>
        <td><strong>${esc(ln.our_product_id)}</strong>${ln.direct ? ` <span style="font-size:12px;color:var(--muted);">direct</span>` : ""}${addonHtml(key, ln, "bill")}</td>
        <td>${ln.quantity_on_hand ?? "—"}</td>
        <td>${money(ln.unit_price)}</td>
        <td><input data-field="bqty" data-i="${i}" type="number" class="input" style="width:72px;" min="0" value="${ln.quantity_to_ship ?? ""}"></td>
        <td><input data-field="bdisc" data-i="${i}" type="number" class="input" style="width:72px;" min="0" max="100" step="0.1" ${ro} value="${esc(shownDisc)}"></td>
        <td><input data-field="bnet" data-i="${i}" type="number" class="input" style="width:88px;" min="0" step="0.01" ${ro} value="${esc(shownNet || "")}"></td>
        <td>${(f.editBillId || ln.direct) ? `<button type="button" class="btn btn-ghost btn-sm" onclick="OrderDesk.removeBillLine('${key}', ${i})">Remove</button>` : ""}</td>
      </tr>`;
    }).join("");
    const orders = (!f.editBillId && (f.billableOrders || []).length) ? `
      <label class="label">Orders still to bill</label>
      <p style="margin:0 0 8px;font-size:13px;color:var(--muted);">Already billed orders are not listed. Uncheck a hold if it should not go on this bill.</p>
      ${(f.billableOrders || []).map(order => {
        const on = (f.selectedPlacementIds || []).includes(Number(order.placement_id));
        const bits = (order.lines || []).map(ln => `${ln.our_product_id} × ${ln.quantity}`).join(", ");
        return `<label style="display:block;margin:0 0 6px;"><input type="checkbox" ${on ? "checked" : ""} onchange="OrderDesk.togglePlacement('${key}', ${order.placement_id}, this.checked)"> ${esc(bits)}</label>`;
      }).join("")}` : "";
    const agent = f.commissionAgentName && !f.editBillId ? `<div style="margin:0 0 12px;padding:12px;background:#fef3c7;border:2px solid #d97706;border-radius:12px;">
      <span style="display:block;font-size:12px;font-weight:700;">BILL THIS ON</span>
      <label style="display:block;margin-top:8px;"><input type="radio" name="agent-${key}" ${f.billOnAgent ? "checked" : ""} onchange="OrderDesk.setBillAgent('${key}', true)"> ${esc(f.commissionAgentName)} <span style="font-size:13px;">commission agent · due on the agent</span></label>
      <label style="display:block;margin-top:6px;"><input type="radio" name="agent-${key}" ${f.billOnAgent ? "" : "checked"} onchange="OrderDesk.setBillAgent('${key}', false)"> ${esc(f.party?.customer_name || "Party")} <span style="font-size:13px;">direct order · due on the party</span></label>
    </div>` : "";
    const transport = f.transportMode === "bus" ? `
      <label class="label">Freight agent</label>
      <select class="input" data-field="agent" onchange="OrderDesk.setTransportBit('${key}')">${agentOptions(f.freightAgentId)}</select>
      <label class="label">Freight (₹)</label>
      <input class="input" data-field="freight" value="${esc(f.freightCharges || "")}">`
      : f.transportMode === "transport" ? `
      <label class="label">Transport (₹)</label>
      <input class="input" data-field="freight" value="${esc(f.freightCharges || "")}">
      <label class="label">Receipt number</label>
      <input class="input" data-field="receipt" value="${esc(f.transportReceiptNumber || "")}">`
      : f.transportMode === "self_pickup" ? `<p style="margin:8px 0 0;font-size:13px;color:var(--muted);">Customer picks up.</p>` : "";
    const hits = findItem(f.search || "").map(p =>
      `<button type="button" class="btn btn-secondary btn-sm" style="display:block;width:100%;text-align:left;margin-top:4px;" onclick="OrderDesk.addBillItem('${key}', ${p.catalog_product_id})">${esc(p.our_product_id)} · stock ${p.quantity_on_hand ?? 0}</button>`
    ).join("");
    const catalogs = (!f.editBillId && (f.dueCatalogs || []).length) ? `<div style="margin:12px 0;">
      <label class="label">Add a catalogue</label>
      ${(f.dueCatalogs || []).map(c => {
        const on = Object.prototype.hasOwnProperty.call(f.pickedCatalogs || {}, String(c.id));
        const price = on ? f.pickedCatalogs[String(c.id)] : "0";
        return `<label style="display:flex;gap:8px;align-items:center;margin-top:6px;"><input type="checkbox" ${on ? "checked" : ""} onchange="OrderDesk.toggleCatalog('${key}', ${c.id}, this.checked)"> ${esc(c.name)} <input class="input" style="width:90px;" data-cat="${c.id}" value="${esc(price)}" ${on ? "" : "disabled"}></label>`;
      }).join("")}
    </div>` : "";
    const charges = (f.additionalCharges || []).map((c, i) => `
      <div style="display:flex;gap:8px;margin-bottom:6px;">
        <input class="input" data-field="cname" data-i="${i}" placeholder="Name" value="${esc(c.name)}">
        <input class="input" data-field="camt" data-i="${i}" placeholder="₹" style="width:110px;" value="${esc(c.amount)}">
      </div>`).join("");
    const series = f.editBillId ? "" : `<label class="label">Bill series</label>
      <select class="input" data-field="series" onchange="OrderDesk.pull('${key}')">${(shared.series || []).map(s => `<option value="${s.id}" ${String(s.id) === String(f.billSeriesId) ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select>
      <p style="margin:6px 0 0;font-size:13px;">Number <strong>${esc(L().nextBillNumber(shared.series, f.billSeriesId, f.numberOffset || 0) || "—")}</strong></p>`;
    const keyBox = f.editBillId ? `<label class="label">Your cancel key</label><input class="input" data-field="cancelkey" type="password" autocomplete="off" placeholder="Your cancel key">` : "";
    const cr = f.credit;
    const credit = !cr ? "" : `<p style="margin:0 0 8px;font-size:13px;">Outstanding ₹${esc(cr.used)} · limit ${cr.track_only ? "not set" : (cr.unlimited ? "Unlimited" : "₹" + esc(cr.credit_limit))}${cr.would_exceed && !cr.track_only && !cr.unlimited ? " · over the limit — you can still bill" : ""}</p>`;
    return `${partyHtml(f.party)}
      ${credit}
      ${String(f.party?.payment_type || "").toUpperCase() === "CASH" ? `<div style="padding:8px 14px;margin-bottom:10px;background:#fef3c7;border:1px solid #fde68a;border-radius:6px;font-size:13px;">⚠ <strong>CASH customer</strong> — collect payment at time of billing.</div>` : ""}
      ${agent}
      ${orders}
      <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin:8px 0 12px;font-size:14px;">
        <label><input type="radio" name="disc-${key}" ${!f.discountEnabled ? "checked" : ""} onchange="OrderDesk.setDisc('${key}', 'off')"> No discount</label>
        <label><input type="radio" name="disc-${key}" ${f.discountEnabled && !f.useOverallDiscount ? "checked" : ""} onchange="OrderDesk.setDisc('${key}', 'line')"> Per item</label>
        <label><input type="radio" name="disc-${key}" ${f.discountEnabled && f.useOverallDiscount ? "checked" : ""} onchange="OrderDesk.setDisc('${key}', 'overall')"> Overall %</label>
        ${f.discountEnabled && f.useOverallDiscount ? `<input class="input" style="width:80px;" data-field="overall" value="${esc(f.overallDiscount || "")}" placeholder="%">` : ""}
      </div>
      <table class="data"><thead><tr><th>Item</th><th>Stock</th><th>Rate</th><th>Qty</th><th>Disc %</th><th>Net</th><th></th></tr></thead>
      <tbody>${lines || `<tr><td colspan="7">No items. Add a product below.</td></tr>`}</tbody></table>
      <label class="label">Add products</label>
      <input class="input" data-field="bsearch" value="${esc(f.search || "")}" placeholder="Item number" oninput="OrderDesk.setBillSearch('${key}', this.value)">
      <div>${hits}</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px;">
        <div>
          <label class="label">Send by</label>
          <select class="input" data-field="mode" onchange="OrderDesk.setMode('${key}', this.value)">
            <option value="" ${f.transportMode ? "" : "selected"}>—</option>
            <option value="bus" ${f.transportMode === "bus" ? "selected" : ""}>Bus</option>
            <option value="transport" ${f.transportMode === "transport" ? "selected" : ""}>Transport</option>
            <option value="self_pickup" ${f.transportMode === "self_pickup" ? "selected" : ""}>Self-pickup</option>
          </select>
          ${transport}
        </div>
        <div>
          <label class="label">Packing (₹)</label>
          <input class="input" data-field="pack" value="${esc(f.packagingCharges || "")}">
          ${series}
          <label class="label">Bill date</label>
          <input type="date" class="input" data-field="bdate" value="${esc(f.billDate || today())}">
        </div>
      </div>
      <label class="label">Other charges</label>
      ${charges}
      <button type="button" class="btn btn-secondary btn-sm" onclick="OrderDesk.addCharge('${key}')">+ Charge</button>
      ${catalogs}
      <label style="display:flex;gap:8px;align-items:center;margin:12px 0;">
        <input type="checkbox" data-field="gst" ${f.gstEnabled ? "checked" : ""} onchange="OrderDesk.setGst('${key}', this.checked)"> GST
        ${f.gstEnabled ? `<input class="input" style="width:80px;" data-field="gstrate" value="${esc(f.gstRate || "18")}">` : ""}
      </label>
      <label class="label">Marking</label>
      <textarea class="input" data-field="bmark" rows="3" style="background:#fee2e2;border:1px solid #dc2626;font-weight:800;color:#b91c1c;">${esc(f.narration || "")}</textarea>
      ${keyBox}
      ${f.alsoPick ? `<p style="margin:8px 0 0;font-size:13px;color:var(--muted);">Saving also marks this dispatched.</p>` : ""}
      ${f.error ? `<p style="color:#b91c1c;font-weight:700;">${esc(f.error)}</p>` : ""}
      ${f.duplicateHtml || ""}`;
  }

  function agentOptions(current) {
    return `<option value="">—</option>` + (shared.agents || []).map(a =>
      `<option value="${a.id}" ${String(a.id) === String(current) ? "selected" : ""}>${esc(a.name)}</option>`
    ).join("");
  }

  function dispatchPlainHtml(key, f) {
    const lines = (f.parcel?.lines || []).map(l => `${esc(l.our_product_id)} × ${l.quantity}`).join(" · ");
    const bus = f.parcel?.transport_mode === "bus" ? `
      <label class="label">Freight agent</label>
      <select class="input" data-field="agent">${agentOptions(f.freightAgentId)}</select>
      <label class="label">Freight (₹)</label>
      <input class="input" data-field="freight" value="${esc(f.freightCharges || "")}">` : "";
    return `${partyHtml(f.party)}
      <p style="margin:0 0 8px;">${esc(f.parcel?.bill_number || "")} · ${esc(f.parcel?.transport_mode || "")}</p>
      <div>${lines || "—"}</div>
      ${f.parcel?.marking ? `<p style="color:#b91c1c;font-weight:700;">${esc(f.parcel.marking)}</p>` : ""}
      ${bus}
      ${f.error ? `<p style="color:#b91c1c;font-weight:700;">${esc(f.error)}</p>` : ""}`;
  }

  function formHtml(key) {
    const f = forms[key];
    if (!f || !f.ready) return f && f.error ? `<p style="color:#b91c1c;">${esc(f.error)}</p>` : "";
    if (f.mode === "confirm") return confirmFormHtml(key, f);
    if (f.mode === "bill" || (f.mode === "dispatch" && f.lines)) return billFormHtml(key, f);
    if (f.mode === "dispatch") return dispatchPlainHtml(key, f);
    return "";
  }

  function assignNumbers() {
    const used = {};
    for (const row of visibleRows()) {
      const f = forms[keyOf(row)];
      if (!f || f.editBillId || !f.lines || f.savedBillId) continue;
      const id = String(f.billSeriesId || "");
      f.numberOffset = used[id] || 0;
      used[id] = f.numberOffset + 1;
    }
  }

  function render() {
    assignNumbers();
    const root = document.getElementById("order-desk-root");
    if (!root) return;
    const rows = visibleRows();
    const buttons = L().buttonsFor(filter);
    const labels = { confirm: "Confirm all", bill: "Bill all", dispatch: "Dispatch all" };
    const hints = {
      new: "Customer orders waiting to be confirmed. Confirm all saves the edits and confirms. Bill all opens the bill. Dispatch all opens the bill and marks it sent after the bill is saved.",
      confirmed: "Confirmed orders, including orders created with New order. Bill all opens the bill form.",
      billed: "Bills not yet marked dispatched. Dispatch all uses the same dispatch edits, then marks them sent.",
      dispatched: "Already dispatched. This is a list only.",
    };
    const bar = buttons.map(b => `<button type="button" class="btn btn-primary" ${saving ? "disabled" : ""} onclick="OrderDesk.act('${b}')">${labels[b]}</button>`).join("");
    const list = rows.map(row => {
      const key = keyOf(row);
      const on = !!selected[key];
      const open = on && forms[key] && (forms[key].ready || forms[key].error);
      const tick = filter === "dispatched" ? "" : `<input type="checkbox" ${on ? "checked" : ""} onchange="OrderDesk.toggle('${key}', this.checked)">`;
      return `<div class="ord-card" style="padding:14px 16px;margin-bottom:10px;" data-desk="${key}">
        <div style="display:flex;gap:10px;align-items:flex-start;">
          ${tick}
          <div style="flex:1;min-width:0;">
            <strong>${rowTitle(row)}</strong>
            <div class="ord-card-meta">${rowMeta(row)}</div>
            ${open ? `<div style="margin-top:12px;">${formHtml(key)}</div>` : ""}
          </div>
        </div>
      </div>`;
    }).join("");
    root.innerHTML = `
      <div class="ui-toolbar" style="display:flex;gap:8px;flex-wrap:wrap;align-items:end;margin-bottom:12px;">
        <button type="button" class="btn btn-secondary" onclick="OrderDesk.newOrder()">New order</button>
        ${[["new", "New"], ["confirmed", "Confirmed"], ["billed", "Billed"], ["dispatched", "Dispatched"]].map(([id, label]) =>
          `<button type="button" class="btn ${filter === id ? "btn-primary" : "btn-secondary"}" onclick="OrderDesk.setFilter('${id}')">${label}</button>`
        ).join("")}
        <label class="label" style="margin:0;">From <input type="date" class="input" value="${esc(dateFrom)}" onchange="OrderDesk.setFrom(this.value)"></label>
        <label class="label" style="margin:0;">To <input type="date" class="input" value="${esc(dateTo)}" onchange="OrderDesk.setTo(this.value)"></label>
        ${filter === "dispatched" ? "" : `<button type="button" class="btn btn-secondary" onclick="OrderDesk.selectAll()">Select all</button>`}
        ${bar}
      </div>
      <p style="margin:0 0 12px;color:var(--muted);font-size:13px;">${hints[filter] || ""}</p>
      ${list || `<p style="color:var(--muted);">Nothing in this list.</p>`}`;
  }

  async function load() {
    const path = filter === "new" ? "/customer-orders?bucket=received&day=all"
      : filter === "confirmed" ? "/customer-orders?bucket=open&day=all"
      : filter === "billed" ? "/freight-agents/parcels?status=pending&day=all"
      : "/freight-agents/parcels?status=picked&day=all";
    raw = await api(path) || [];
    selected = {};
    forms = {};
    render();
  }

  function open() {
    const day = listDay();
    dateFrom = day;
    dateTo = day;
    load().catch(e => toast(e.message || "Could not load orders"));
  }
  function setFilter(next) {
    filter = next;
    load().catch(e => toast(e.message || "Could not load orders"));
  }
  function setFrom(v) { dateFrom = v || ""; render(); }
  function setTo(v) { dateTo = v || ""; render(); }
  function toggle(key, on) {
    if (on) selected[key] = true;
    else { delete selected[key]; delete forms[key]; }
    render();
  }
  function selectAll() {
    selected = {};
    for (const row of visibleRows()) selected[keyOf(row)] = true;
    render();
  }
  function newOrder() {
    CustomerOrders.openOfflineWizard?.();
  }

  function pull(key) {
    const root = document.querySelector(`[data-desk="${key}"]`);
    const f = forms[key];
    if (!root || !f) return;
    const val = (sel) => root.querySelector(sel);
    if (f.mode === "confirm") {
      root.querySelectorAll("[data-field=cqty]").forEach(el => {
        const line = f.lines[Number(el.dataset.i)];
        if (!line) return;
        const q = Number(el.value);
        const min = Number(line.min_qty) || 0;
        line.quantity = Number.isFinite(q) ? Math.max(min, q) : min;
      });
      const date = val("[data-field=cdate]");
      const mark = val("[data-field=cmark]");
      if (date) f.placedOn = date.value || f.placedOn;
      if (mark) f.narration = mark.value;
      return;
    }
    if (!f.lines) {
      const agent = val("[data-field=agent]");
      const freight = val("[data-field=freight]");
      if (agent) f.freightAgentId = agent.value;
      if (freight) f.freightCharges = freight.value;
      return;
    }
    root.querySelectorAll("[data-field=bqty]").forEach(el => {
      const line = f.lines[Number(el.dataset.i)];
      if (line) line.quantity_to_ship = el.value;
    });
    root.querySelectorAll("[data-field=bdisc]").forEach(el => {
      const line = f.lines[Number(el.dataset.i)];
      if (!line || el.readOnly) return;
      if (String(el.value) !== String(line.discount_percent ?? "")) line.discSource = "pct";
      line.discount_percent = el.value;
    });
    root.querySelectorAll("[data-field=bnet]").forEach(el => {
      const line = f.lines[Number(el.dataset.i)];
      if (!line || el.readOnly) return;
      if (String(el.value) !== String(line.net_rate ?? "")) line.discSource = "net";
      line.net_rate = el.value;
    });
    const overall = val("[data-field=overall]");
    if (overall) f.overallDiscount = overall.value;
    const mode = val("[data-field=mode]");
    if (mode) f.transportMode = mode.value;
    const agent = val("[data-field=agent]");
    if (agent) f.freightAgentId = agent.value;
    const freight = val("[data-field=freight]");
    if (freight) f.freightCharges = freight.value;
    const receipt = val("[data-field=receipt]");
    if (receipt) f.transportReceiptNumber = receipt.value;
    const pack = val("[data-field=pack]");
    if (pack) f.packagingCharges = pack.value;
    const series = val("[data-field=series]");
    if (series) f.billSeriesId = series.value;
    const bdate = val("[data-field=bdate]");
    if (bdate) f.billDate = bdate.value;
    const mark = val("[data-field=bmark]");
    if (mark) f.narration = mark.value;
    const gst = val("[data-field=gst]");
    if (gst) f.gstEnabled = gst.checked;
    const rate = val("[data-field=gstrate]");
    if (rate) f.gstRate = rate.value;
    const keyEl = val("[data-field=cancelkey]");
    if (keyEl) f.cancelKey = keyEl.value;
    root.querySelectorAll("[data-field=cname]").forEach(el => {
      const row = f.additionalCharges[Number(el.dataset.i)];
      if (row) row.name = el.value;
    });
    root.querySelectorAll("[data-field=camt]").forEach(el => {
      const row = f.additionalCharges[Number(el.dataset.i)];
      if (row) row.amount = el.value;
    });
    root.querySelectorAll("[data-cat]").forEach(el => {
      if (!el.disabled) f.pickedCatalogs[el.dataset.cat] = el.value;
    });
  }

  function setConfirmSearch(key, v) { if (forms[key]) { pull(key); forms[key].search = v; render(); } }
  function setBillSearch(key, v) { if (forms[key]) { pull(key); forms[key].search = v; render(); } }
  function setMode(key, v) { pull(key); if (forms[key]) forms[key].transportMode = v; render(); }
  function setTransportBit(key) { pull(key); }
  function setDisc(key, mode) {
    pull(key);
    const f = forms[key];
    if (!f) return;
    f.discountEnabled = mode !== "off";
    f.useOverallDiscount = mode === "overall";
    render();
  }
  function setGst(key, on) { pull(key); if (forms[key]) forms[key].gstEnabled = !!on; render(); }
  function setBillAgent(key, on) { pull(key); if (forms[key]) forms[key].billOnAgent = !!on; render(); }
  function addCharge(key) { pull(key); forms[key]?.additionalCharges.push({ name: "", amount: "" }); render(); }
  function toggleCatalog(key, id, on) {
    pull(key);
    const f = forms[key];
    if (!f) return;
    if (on) { if (!Object.prototype.hasOwnProperty.call(f.pickedCatalogs, String(id))) f.pickedCatalogs[String(id)] = "0"; }
    else delete f.pickedCatalogs[String(id)];
    render();
  }
  function togglePlacement(key, id, on) {
    pull(key);
    const f = forms[key];
    if (!f) return;
    const n = Number(id);
    if (on) { if (!f.selectedPlacementIds.includes(n)) f.selectedPlacementIds.push(n); }
    else f.selectedPlacementIds = f.selectedPlacementIds.filter(x => x !== n);
    f.lines = L().applySelectedOrders(f);
    render();
  }
  function toggleSkip(line, addonId) {
    const skipped = new Set((line.skip_addon_ids || []).map(Number));
    const id = Number(addonId);
    if (skipped.has(id)) skipped.delete(id);
    else skipped.add(id);
    line.skip_addon_ids = [...skipped];
  }
  function toggleConfirmAddon(key, cid, addonId) {
    pull(key);
    const line = (forms[key]?.lines || []).find(l => Number(l.catalog_product_id) === Number(cid));
    if (!line) return;
    toggleSkip(line, addonId);
    render();
  }
  function toggleBillAddon(key, cid, addonId) {
    pull(key);
    const line = (forms[key]?.lines || []).find(l => Number(l.catalog_product_id) === Number(cid));
    if (!line) return;
    toggleSkip(line, addonId);
    render();
  }
  function removeConfirmLine(key, i) {
    pull(key);
    const f = forms[key];
    if (!f) return;
    const line = f.lines[i];
    if (line && Number(line.min_qty) > 0) { toast("Billed quantity stays on the order"); return; }
    f.lines.splice(i, 1);
    render();
  }
  function removeBillLine(key, i) { pull(key); forms[key]?.lines.splice(i, 1); render(); }
  function addConfirmItem(key, cid) {
    pull(key);
    const f = forms[key];
    const p = (shared.items || []).find(x => Number(x.catalog_product_id) === Number(cid));
    if (!f || !p) return;
    const existing = f.lines.find(l => Number(l.catalog_product_id) === Number(cid));
    if (existing) existing.quantity = Number(existing.quantity || 0) + 1;
    else f.lines.push({
      catalog_product_id: p.catalog_product_id,
      our_product_id: p.our_product_id,
      quantity: 1,
      min_qty: 0,
      unit_price: p.selling_price,
      stock: p.quantity_on_hand,
      addons: (p.addons && p.addons.length) ? p.addons : (p.priced_addons || []),
      skip_addon_ids: [],
    });
    f.search = "";
    render();
  }
  function addBillItem(key, cid) {
    pull(key);
    const f = forms[key];
    const p = (shared.items || []).find(x => Number(x.catalog_product_id) === Number(cid));
    if (!f || !p) return;
    if (f.lines.some(l => Number(l.catalog_product_id) === Number(cid) && !l.direct)) {
      toast("That item is already booked — tick that order");
      return;
    }
    const existing = f.lines.find(l => Number(l.catalog_product_id) === Number(cid) && l.direct);
    if (existing) existing.quantity_to_ship = Number(existing.quantity_to_ship || 0) + 1;
    else f.lines.push({
      catalog_product_id: p.catalog_product_id,
      our_product_id: p.our_product_id,
      unit_price: p.selling_price,
      quantity_to_ship: 1,
      quantity_on_hand: p.quantity_on_hand,
      discount_percent: "",
      net_rate: L().calcNetFromDisc(p.selling_price, 0),
      discSource: "",
      addons: (p.addons && p.addons.length) ? p.addons : (p.priced_addons || []),
      skip_addon_ids: [],
      direct: true,
    });
    f.search = "";
    render();
  }

  function pickPlacement(detail) {
    const placements = (detail.placements || []).filter(p => p.status === "received");
    return placements.find(p => (p.lines || []).some(ln => ln.status === "active" && Number(ln.quantity) > Number(ln.quantity_billed || 0)))
      || placements.find(p => (p.lines || []).some(ln => ln.status === "active"))
      || placements[0]
      || null;
  }

  async function openConfirm(key, row) {
    const detail = await api(`/customer-orders/customer/${row.customer_id}?bucket=received`);
    const placement = pickPlacement(detail || {});
    if (!placement) throw new Error("No items in this order");
    const active = (placement.lines || []).filter(ln => ln.status === "active");
    if (!active.length) throw new Error("No items in this order");
    const lines = active.map(ln => {
      const hit = (shared.items || []).find(x => x.catalog_product_id === ln.catalog_product_id);
      const catalog = (hit && (hit.addons || hit.priced_addons)) || [];
      return {
        catalog_product_id: ln.catalog_product_id,
        our_product_id: ln.our_product_id,
        quantity: Number(ln.quantity) || 0,
        min_qty: Number(ln.quantity_billed) || 0,
        unit_price: ln.unit_price,
        stock: ln.stock ?? hit?.quantity_on_hand,
        addons: mergeAddons(ln.addons, catalog),
        skip_addon_ids: [],
      };
    });
    forms[key] = {
      mode: "confirm",
      ready: true,
      customerId: row.customer_id,
      placementId: placement.id,
      lines,
      narration: row.marking || placement.customer_notes || "",
      placedOn: String(placement.placed_at || row.display_date || today()).slice(0, 10),
      party: detail,
      otherCount: ((detail.placements || []).filter(p => p.status === "received").length > 1),
      search: "",
      confirmDuplicate: false,
      error: "",
    };
  }

  function mergeAddons(keptRows, catalog) {
    const byId = new Map();
    for (const a of [...(catalog || []), ...(Array.isArray(keptRows) ? keptRows : [])]) {
      if (a && a.addon_product_id != null) byId.set(Number(a.addon_product_id), a);
    }
    return [...byId.values()];
  }

  function freshBill(pctx, alsoPick) {
    const orders = pctx.orders || [];
    const state = {
      mode: alsoPick ? "dispatch" : "bill",
      ready: true,
      alsoPick: !!alsoPick,
      editBillId: null,
      customerId: pctx.customer_id,
      contextLines: pctx.lines || [],
      billableOrders: orders,
      selectedPlacementIds: orders.map(o => Number(o.placement_id)),
      lines: [],
      discountEnabled: false,
      useOverallDiscount: false,
      overallDiscount: "",
      gstEnabled: false,
      gstRate: "18",
      transportMode: "self_pickup",
      transportReceiptNumber: "",
      freightAgentId: "",
      freightCharges: "",
      packagingCharges: "",
      additionalCharges: [{ name: "", amount: "" }],
      billSeriesId: L().defaultBillSeriesId(shared.series),
      narration: pctx.default_narration || "",
      billDate: today(),
      pickedCatalogs: {},
      dueCatalogs: [],
      commissionAgentId: pctx.commission_agent_id || null,
      commissionAgentName: pctx.commission_agent_name || "",
      billOnAgent: true,
      party: pctx,
      confirmDuplicate: false,
      error: "",
      savedBillId: 0,
      search: "",
    };
    state.lines = L().applySelectedOrders(state);
    state.credit = pctx.credit || null;
    return state;
  }

  async function openBill(key, customerId, alsoPick) {
    const [pctx, catalogs] = await Promise.all([
      api(`/customer-orders/customer/${customerId}/process-context`),
      api(`/our-catalogs/for-customer/${customerId}`).catch(() => []),
    ]);
    const state = freshBill(pctx, alsoPick);
    state.dueCatalogs = catalogs || [];
    if (!state.lines.length) throw new Error("Nothing left to bill");
    forms[key] = state;
  }

  async function confirmCustomer(row, key) {
    const f = forms[key];
    if (f && f.mode === "confirm") {
      pull(key);
      const err = L().offlineError(f);
      if (err) throw new Error(err);
      await api(`/customer-orders/placements/${f.placementId}`, {
        method: "PUT",
        body: JSON.stringify(L().offlineBody(f)),
      });
    }
    const marking = (f && f.mode === "confirm" ? f.narration : row.marking) || "";
    try {
      await api(`/customer-orders/customer/${row.customer_id}/confirm`, {
        method: "POST",
        body: JSON.stringify({ marking }),
      });
    } catch (e) {
      const msg = String(e.message || "").toLowerCase();
      if (!msg.includes("no pending") && !msg.includes("nothing to confirm")) throw e;
    }
  }

  function billFromPayload(bill, party, parcel) {
    const lines = (bill.lines || []).filter(ln => ln.status === "billed").map(l => ({
      catalog_product_id: l.catalog_product_id,
      our_product_id: l.our_product_id,
      unit_price: l.unit_price,
      quantity_to_ship: l.quantity_shipped,
      quantity_on_hand: l.stock ?? "—",
      discount_percent: l.discount_percent || "",
      net_rate: l.net_rate || L().calcNetFromDisc(l.unit_price, l.discount_percent || 0),
      discSource: l.price_entry === "net" ? "net" : (l.discount_percent ? "pct" : ""),
      addons: l.addons || [],
      skip_addon_ids: [],
      bill_line_id: l.id,
    }));
    const hasOverall = bill.discount_percent != null && Number(bill.discount_percent) > 0;
    const hasLine = lines.some(l => l.discount_percent && Number(l.discount_percent) > 0);
    const state = {
      mode: "dispatch",
      ready: true,
      alsoPick: true,
      editBillId: bill.id,
      customerId: bill.customer_id,
      lines,
      discountEnabled: hasOverall || hasLine,
      useOverallDiscount: hasOverall,
      overallDiscount: hasOverall ? String(bill.discount_percent) : "",
      gstEnabled: !!bill.gst_enabled,
      gstRate: bill.gst_rate_percent != null ? String(bill.gst_rate_percent) : "18",
      transportMode: bill.transport_mode || (bill.freight_agent_id ? "bus" : (Number(bill.freight_charges) > 0 ? "transport" : "self_pickup")),
      transportReceiptNumber: bill.transport_receipt_number || "",
      freightAgentId: bill.freight_agent_id != null ? String(bill.freight_agent_id) : "",
      freightCharges: bill.freight_charges != null ? String(bill.freight_charges) : "",
      packagingCharges: bill.packaging_charges != null ? String(bill.packaging_charges) : "",
      additionalCharges: (bill.additional_charges || []).length
        ? bill.additional_charges.map(c => ({ name: c.name || "", amount: String(c.amount || "") }))
        : [{ name: "", amount: "" }],
      narration: bill.narration || "",
      billDate: bill.bill_date ? String(bill.bill_date).slice(0, 10) : today(),
      pickedCatalogs: {},
      dueCatalogs: [],
      party,
      parcel,
      confirmDuplicate: false,
      error: "",
      search: "",
      cancelKey: "",
    };
    state.snapshot = JSON.stringify(L().billBody(state));
    return state;
  }

  async function openDispatchParcel(key, row) {
    const editable = L().billEditable(row.created_at, anyDayEdit());
    let party = { customer_name: row.customer_label, city_name: row.customer_city };
    try {
      const c = await api(`/customers/${row.customer_id}`);
      party = {
        customer_name: c.business_name || row.customer_label,
        city_name: c.city_name || row.customer_city,
        party_number: c.party_number,
        marker_1: c.marker_1,
        marker_2: c.marker_2,
        payment_type: c.payment_type,
      };
    } catch (_) {}
    if (!editable) {
      forms[key] = {
        mode: "dispatch",
        ready: true,
        alsoPick: true,
        customerId: row.customer_id,
        parcel: row,
        party,
        freightAgentId: row.freight_agent_id != null ? String(row.freight_agent_id) : "",
        freightCharges: row.freight_charges != null ? String(row.freight_charges) : "",
        snapshotAgent: row.freight_agent_id != null ? String(row.freight_agent_id) : "",
        snapshotFreight: row.freight_charges != null ? String(row.freight_charges) : "",
        error: "",
      };
      return;
    }
    const bill = await api(`/customer-orders/bills/${row.bill_id}`);
    if (bill.cancelled_at) throw new Error("Cannot edit — bill cancelled");
    if ((bill.lines || []).some(ln => ln.status === "closed")) throw new Error("Cannot edit — close was done");
    forms[key] = billFromPayload(bill, party, row);
  }

  async function openForms(kind, keys) {
    await ensureShared();
    let offset = 0;
    for (const key of keys) {
      const row = visibleRows().find(r => keyOf(r) === key);
      if (!row) continue;
      try {
        if (kind === "confirm") await openConfirm(key, row);
        else if (kind === "bill" || (kind === "dispatch" && filter !== "billed")) {
          if (filter === "new") await confirmCustomer(row, key);
          await openBill(key, row.customer_id, kind === "dispatch");
          forms[key].numberOffset = offset;
          offset += 1;
        } else {
          await openDispatchParcel(key, row);
        }
      } catch (e) {
        forms[key] = { ready: false, error: e.message || "Could not open", mode: kind };
      }
    }
    render();
  }

  function duplicateNote(detail) {
    const rows = (detail && detail.matches) || [];
    if (!rows.length) return "";
    const bits = rows.map(m => {
      const same = [];
      if (m.same_items && m.same_items.length) same.push(`same item ${m.same_items.join(", ")}`);
      if (m.same_amount) same.push(`same amount ₹${m.total}`);
      return `<li>${esc(m.bill_number || ("Order #" + (m.placement_id || "")))}: ${esc(same.join(" · "))}</li>`;
    }).join("");
    return `<div style="border:2px solid #b45309;background:#fffbeb;border-radius:12px;padding:12px;margin-top:8px;">
      <strong>This could be a duplicate entry.</strong>
      <ul style="margin:8px 0;">${bits}</ul>
      <p style="margin:0;">Press the button again to proceed with this one.</p>
    </div>`;
  }

  async function saveOne(kind, key, row) {
    const f = forms[key];
    pull(key);
    if (kind === "confirm") {
      const err = L().offlineError(f);
      if (err) throw new Error(err);
      try {
        await api(`/customer-orders/placements/${f.placementId}`, { method: "PUT", body: JSON.stringify(L().offlineBody(f)) });
      } catch (e) {
        if (e.status === 409 && e.detail && e.detail.matches) {
          if (!f.confirmDuplicate) {
            f.confirmDuplicate = true;
            f.duplicateHtml = duplicateNote(e.detail);
            f.error = "";
            const again = new Error("Check the duplicate warning, then press Confirm all again");
            again.held = true;
            throw again;
          }
          f.confirmDuplicate = true;
          await api(`/customer-orders/placements/${f.placementId}`, { method: "PUT", body: JSON.stringify(L().offlineBody(f)) });
        } else throw e;
      }
      await api(`/customer-orders/customer/${f.customerId}/confirm`, {
        method: "POST",
        body: JSON.stringify({ marking: f.narration || "" }),
      });
      return;
    }
    if (f.lines) {
      if (f.savedBillId && f.alsoPick) {
        await api(`/freight-agents/parcels/${f.savedBillId}/pick`, { method: "POST", body: "{}" });
        f.picked = true;
        return;
      }
      const err = L().billError(f);
      if (err) throw new Error(err);
      const body = L().billBody(f);
      const opts = { method: f.editBillId ? "PUT" : "POST", body: JSON.stringify(body) };
      if (f.editBillId && f.cancelKey) opts.headers = { "X-Cancel-Key": f.cancelKey };
      const url = f.editBillId
        ? `/customer-orders/bills/${f.editBillId}`
        : `/customer-orders/customer/${f.customerId}/process`;
      if (f.editBillId && f.snapshot && f.snapshot === JSON.stringify(body)) {
        await api(`/freight-agents/parcels/${f.editBillId}/pick`, { method: "POST", body: "{}" });
        f.picked = true;
        return;
      }
      let res;
      try {
        res = await api(url, opts);
      } catch (e) {
        if (e.status === 409 && e.detail && e.detail.matches && !f.confirmDuplicate) {
          f.confirmDuplicate = true;
          f.duplicateHtml = duplicateNote(e.detail);
          const again = new Error("Check the duplicate warning, then press the button again");
          again.held = true;
          throw again;
        }
        throw e;
      }
      if (!f.editBillId) {
        f.savedBillId = res.bill_id;
        const series = shared.series.find(s => String(s.id) === String(f.billSeriesId));
        if (series) series.current_num = Number(series.current_num) + 1;
      }
      if (f.alsoPick) {
        const billId = f.editBillId || res.bill_id;
        await api(`/freight-agents/parcels/${billId}/pick`, { method: "POST", body: "{}" });
        f.picked = true;
      }
      return;
    }
    if (String(f.freightAgentId || "") !== String(f.snapshotAgent || "") || String(f.freightCharges || "") !== String(f.snapshotFreight || "")) {
      const body = { freight_agent_id: Number(f.freightAgentId) };
      if (String(f.freightCharges || "").trim() !== "") body.freight_charges = f.freightCharges;
      await api(`/freight-agents/parcels/${row.bill_id}`, { method: "PATCH", body: JSON.stringify(body) });
    }
    await api(`/freight-agents/parcels/${row.bill_id}/pick`, { method: "POST", body: "{}" });
    f.picked = true;
  }

  async function act(kind) {
    if (saving) return;
    const keys = selectedKeys();
    if (!keys.length) return toast("Select an order");
    const ready = keys.every(k => forms[k] && forms[k].ready && forms[k].mode === kind);
    if (ready && kind === "dispatch") {
      const msg = filter === "billed"
        ? "Mark the selected parcels dispatched? Bus freight is posted to the agent."
        : "Save these bills and mark them dispatched?";
      if (!window.confirm(msg)) return;
    }
    if (!ready) {
      saving = true;
      render();
      try { await openForms(kind, keys); }
      finally { saving = false; render(); }
      return;
    }
    saving = true;
    render();
    const done = [];
    try {
      for (const key of keys) {
        const row = visibleRows().find(r => keyOf(r) === key);
        try {
          await saveOne(kind, key, row);
          done.push(key);
        } catch (e) {
          if (forms[key]) forms[key].error = e.held ? "" : (e.message || "Could not save");
          toast(e.message || "Could not save");
          break;
        }
      }
    } finally {
      saving = false;
    }
    if (done.length === keys.length) {
      toast(kind === "confirm" ? "Orders confirmed" : kind === "bill" ? "Bills saved" : "Dispatched", "success");
      App.invalidateCache?.("/customer-orders");
      App.invalidateCache?.("/stock");
      App.invalidateCache?.("/freight-agents");
      await load().catch(() => render());
      return;
    }
    for (const key of done) {
      delete selected[key];
      delete forms[key];
      raw = raw.filter(r => keyOf(r) !== key);
    }
    render();
  }

  return {
    open, setFilter, setFrom, setTo, toggle, selectAll, newOrder, act, pull,
    setConfirmSearch, setBillSearch, setMode, setTransportBit, setDisc, setGst, setBillAgent,
    addCharge, toggleCatalog, togglePlacement, toggleConfirmAddon, toggleBillAddon,
    removeConfirmLine, removeBillLine, addConfirmItem, addBillItem,
  };
})();
