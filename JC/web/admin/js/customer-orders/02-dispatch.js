  const dispatchDrafts = {};
  let pickedOpenId = null;
  const pickedStories = {};

  function pullDispatchDrafts() {
    for (const id of Object.keys(dispatchDrafts)) {
      const root = document.querySelector(`[data-dispatch="${id}"]`);
      if (!root) continue;
      const d = dispatchDrafts[id];
      const read = (field) => root.querySelector(`[data-field="${field}"]`);
      const mode = read("mode");
      if (mode) d.mode = mode.value;
      const agent = read("agent");
      if (agent) d.agent = agent.value;
      const freight = read("freight");
      if (freight) d.freight = freight.value;
      const receipt = read("receipt");
      if (receipt) d.receipt = receipt.value;
      const packing = read("packing");
      if (packing) d.packing = packing.value;
      const marking = read("marking");
      if (marking) d.marking = marking.value;
      root.querySelectorAll("[data-field=cname]").forEach(el => {
        const row = d.charges[Number(el.dataset.i)];
        if (row) row.name = el.value;
      });
      root.querySelectorAll("[data-field=camt]").forEach(el => {
        const row = d.charges[Number(el.dataset.i)];
        if (row) row.amount = el.value;
      });
    }
  }

  function draftFor(p) {
    const id = String(p.bill_id);
    if (!dispatchDrafts[id]) {
      const charges = (p.additional_charges || []).map(c => ({ name: c.name || "", amount: String(c.amount || "") }));
      dispatchDrafts[id] = {
        mode: p.transport_mode || (p.freight_agent_id ? "bus" : "self_pickup"),
        agent: p.freight_agent_id || "",
        freight: p.freight_charges && Number(p.freight_charges) ? String(p.freight_charges) : "",
        receipt: p.transport_receipt_number || "",
        packing: p.packaging_charges && Number(p.packaging_charges) ? String(p.packaging_charges) : "",
        charges: charges.length ? charges : [{ name: "", amount: "" }],
        marking: p.marking || "",
      };
    }
    return dispatchDrafts[id];
  }

  function setDispatchMode(billId, value) {
    pullDispatchDrafts();
    if (dispatchDrafts[billId]) dispatchDrafts[billId].mode = value;
    renderDispatchList();
  }

  function addDispatchCharge(billId) {
    pullDispatchDrafts();
    dispatchDrafts[billId]?.charges.push({ name: "", amount: "" });
    renderDispatchList();
  }

  async function loadDispatch() {
    ctx.showLoading?.();
    try {
      const q = new URLSearchParams({ status: currentBucket === "picked" ? "picked" : "pending", day: dayParam() });
      if (dispatchAgentId) q.set("agent_id", dispatchAgentId);
      const [parcels, agents] = await Promise.all([
        ctx.api(`/freight-agents/parcels?${q}`, {}, 0),
        ctx.api("/freight-agents", {}, 0).catch(() => dispatchAgents),
      ]);
      dispatchParcels = Array.isArray(parcels) ? parcels : [];
      dispatchAgents = Array.isArray(agents) ? agents : [];
      syncHubChrome();
      renderDispatchList();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function filterDispatchParcels(list) {
    const q = hubSearch.trim().toLowerCase();
    if (!q) return list;
    return list.filter(p => {
      const hay = [
        p.customer_label, p.bill_number, p.customer_city, p.customer_phone,
        p.freight_agent_name, String(p.bill_id || ""), p.transport_mode, p.transport_receipt_number,
      ].join(" ").toLowerCase();
      return hay.includes(q);
    });
  }

  function dispatchFormHtml(p) {
    const d = draftFor(p);
    const agents = (dispatchAgents || []).map(a =>
      `<option value="${a.id}" ${String(a.id) === String(d.agent) ? "selected" : ""}>${ctx.esc(a.name)}</option>`
    ).join("");
    const modeBits = d.mode === "bus" ? `
      <label class="label">Freight agent</label>
      <select class="input" data-field="agent"><option value="">—</option>${agents}</select>
      <label class="label">Freight (₹)</label>
      <input class="input" data-field="freight" value="${ctx.esc(d.freight)}">`
      : d.mode === "transport" ? `
      <label class="label">Transport (₹)</label>
      <input class="input" data-field="freight" value="${ctx.esc(d.freight)}">
      <label class="label">Receipt number</label>
      <input class="input" data-field="receipt" value="${ctx.esc(d.receipt)}">`
      : `<p style="margin:8px 0 0;font-size:13px;color:var(--muted);">Customer picks up.</p>`;
    const charges = d.charges.map((c, i) => `
      <div style="display:flex;gap:8px;margin-bottom:6px;">
        <input class="input" data-field="cname" data-i="${i}" placeholder="Name" value="${ctx.esc(c.name)}">
        <input class="input" data-field="camt" data-i="${i}" placeholder="₹" style="width:110px;" value="${ctx.esc(c.amount)}">
      </div>`).join("");
    return `<div data-dispatch="${p.bill_id}" style="margin-top:12px;padding-top:12px;border-top:1px solid #e2e8f0;">
      <label class="label">Send by</label>
      <select class="input" data-field="mode" onchange="CustomerOrders.setDispatchMode(${p.bill_id}, this.value)">
        <option value="bus" ${d.mode === "bus" ? "selected" : ""}>Bus / freight</option>
        <option value="transport" ${d.mode === "transport" ? "selected" : ""}>Transport</option>
        <option value="self_pickup" ${d.mode === "self_pickup" ? "selected" : ""}>Self-pickup</option>
      </select>
      ${modeBits}
      <label class="label">Packing (₹)</label>
      <input class="input" data-field="packing" value="${ctx.esc(d.packing)}">
      <label class="label">Other charges</label>
      ${charges}
      <button type="button" class="btn btn-secondary btn-sm" onclick="CustomerOrders.addDispatchCharge(${p.bill_id})">+ Charge</button>
      <label class="label">Marking</label>
      <textarea class="input" data-field="marking" rows="2" style="background:#fee2e2;border:1px solid #dc2626;font-weight:800;color:#b91c1c;">${ctx.esc(d.marking)}</textarea>
      <button type="button" class="btn btn-primary" style="margin-top:12px;" onclick="CustomerOrders.markDispatchPicked(${p.bill_id})">Mark as picked</button>
    </div>`;
  }

  function storyLines(lines) {
    return (lines || []).map(l => `<tr><td>${ctx.esc(l.our_product_id)}</td><td>${l.quantity}</td><td>${fmtPrice(l.rate)}</td></tr>`).join("")
      || `<tr><td colspan="3">—</td></tr>`;
  }

  function storyBlock(title, row) {
    if (!row) return "";
    const when = row.at ? (ctx.fmtDate?.(row.at) || String(row.at).slice(0, 16).replace("T", " ")) : "";
    const bits = [];
    if (row.transport_mode) bits.push(row.transport_mode === "bus" ? "Bus / freight" : row.transport_mode === "transport" ? "Transport" : "Self-pickup");
    if (Number(row.freight_charges) > 0) bits.push(`Charges ${fmtPrice(row.freight_charges)}`);
    if (row.transport_receipt_number) bits.push(`Rcpt ${row.transport_receipt_number}`);
    if (Number(row.packaging_charges) > 0) bits.push(`Packing ${fmtPrice(row.packaging_charges)}`);
    (row.additional_charges || []).forEach(c => { if (Number(c.amount) > 0) bits.push(`${c.name} ${fmtPrice(c.amount)}`); });
    return `<div style="margin-top:10px;padding:10px 12px;border:1px solid #e2e8f0;border-radius:8px;background:#fff;">
      <div style="font-weight:800;">${ctx.esc(title)}</div>
      <div style="font-size:12px;color:var(--muted);margin:2px 0 8px;">${ctx.esc(row.by || "Staff")}${when ? " · " + ctx.esc(when) : ""}</div>
      ${row.marking ? `<div style="color:#b91c1c;font-weight:700;margin-bottom:6px;">Marking: ${ctx.esc(row.marking)}</div>` : ""}
      ${bits.length ? `<div style="font-size:13px;margin-bottom:6px;">${ctx.esc(bits.join(" · "))}</div>` : ""}
      <table class="data"><thead><tr><th>Item</th><th>Qty</th><th>Rate</th></tr></thead><tbody>${storyLines(row.lines)}</tbody></table>
    </div>`;
  }

  function renderDispatchList() {
    const el = document.getElementById("customer-orders-list");
    if (!el) return;
    const canWrite = !!ctx.canWrite?.("customer_orders");
    const list = filterDispatchParcels(dispatchParcels);
    const pickedTab = currentBucket === "picked";
    if (!list.length) {
      el.innerHTML = OrdersUI.emptyState({
        title: pickedTab ? "No picked parcels" : "Nothing waiting to be picked",
        sub: pickedTab ? "Mark a dispatch tile as picked and it lands here." : "After the bill, Dispatch brings the parcel here.",
      });
      return;
    }
    el.innerHTML = `<div class="ord-card-list">${list.map(p => {
      const lines = (p.lines || []).map(l => `${ctx.esc(l.our_product_id)} × ${l.quantity}`).join(" · ");
      const meta = [
        p.bill_number ? `Bill ${p.bill_number}` : null,
        p.customer_city || null,
        `${p.total_pcs || 0} pcs`,
      ].filter(Boolean).join(" · ");
      const noteKey = `dispatch:${p.bill_id}`;
      const open = pickedTab && String(pickedOpenId) === String(p.bill_id);
      const story = pickedStories[p.bill_id];
      const storyHtml = open && story ? [
        storyBlock("Order created", story.created),
        storyBlock("Billed", story.billed),
        storyBlock("Dispatched", story.dispatched),
        storyBlock("Marked as picked", story.picked),
      ].join("") : "";
      return `<div class="ord-card" style="padding:14px 16px;" ${pickedTab ? `onclick="CustomerOrders.togglePickedStory(${p.bill_id})"` : ""}>
        <div style="min-width:0;">
          <strong class="ord-card-title" style="font-size:16px;">${ctx.esc(p.customer_label || "Customer")}</strong>
          ${p.created_by ? `<div style="display:block;margin-top:8px;padding:8px 10px;border-radius:10px;background:#dcfce7;color:#166534;font-weight:800;font-size:16px;">Created by ${ctx.esc(p.created_by)}</div>` : ""}
          ${parcelMarkHtml(p)}
          <div data-tile-note="${noteKey}" onclick="event.stopPropagation()">
            <button type="button" class="btn btn-secondary btn-sm" style="margin-top:6px;" onclick="event.stopPropagation();App.editTileNote('${noteKey}')">Add note</button>
          </div>
          <div class="ord-card-meta" style="margin-top:4px;">${ctx.esc(meta)}</div>
          <div style="font-size:13px;margin-top:8px;">${lines || "—"}</div>
          ${pickedTab ? storyHtml : (canWrite ? dispatchFormHtml(p) : "")}
        </div>
      </div>`;
    }).join("")}</div>`;
  }

  async function togglePickedStory(billId) {
    if (String(pickedOpenId) === String(billId)) {
      pickedOpenId = null;
      renderDispatchList();
      return;
    }
    pickedOpenId = billId;
    if (!pickedStories[billId]) {
      try { pickedStories[billId] = await ctx.api(`/freight-agents/parcels/${billId}/story`, {}, 0); }
      catch (e) { ctx.toast(e.message, "error"); pickedOpenId = null; }
    }
    renderDispatchList();
  }

  async function markDispatchPicked(billId) {
    pullDispatchDrafts();
    const d = dispatchDrafts[String(billId)];
    if (!d) return;
    ctx.showLoading?.();
    try {
      await ctx.api(`/freight-agents/parcels/${billId}/mark-picked`, {
        method: "POST",
        body: JSON.stringify({
          transport_mode: d.mode,
          freight_agent_id: d.mode === "bus" ? Number(d.agent) || null : null,
          freight_charges: d.freight,
          transport_receipt_number: d.receipt,
          packaging_charges: d.packing,
          additional_charges: d.charges,
          narration: d.marking,
        }),
      }, 0);
      delete dispatchDrafts[String(billId)];
      ctx.toast("Marked as picked", "success");
      ctx.invalidateCache?.("/freight-agents");
      await loadDispatch();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function pickParcel(billId, mode) {
    const msg = mode === "bus"
      ? "Mark picked? Freight amount goes to this agent's dues in Money → Freight."
      : "Mark this parcel as dispatched?";
    if (!confirm(msg)) return;
    ctx.showLoading?.();
    try {
      await ctx.api(`/freight-agents/parcels/${billId}/pick`, { method: "POST", body: "{}" }, 0);
      ctx.toast("Picked — dues updated", "success");
      ctx.invalidateCache?.("/freight-agents");
      await loadDispatch();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function reassignParcel(billId) {
    const parcel = dispatchParcels.find(p => p.bill_id === billId);
    const currentId = parcel?.freight_agent_id || Number(dispatchAgentId) || "";
    const opts = dispatchAgents.map(a =>
      `<option value="${a.id}" ${a.id === currentId ? "selected" : ""}>${ctx.esc(a.name)}</option>`
    ).join("");
    ctx.openDetail?.("Change freight agent", `
      <p style="margin:0 0 12px;color:var(--muted);font-size:13px;">Only for unpicked parcels.</p>
      <label class="label">Agent</label>
      <select class="input" id="co-reassign-agent" style="margin-bottom:12px;">${opts}</select>
      <label class="label">Freight amount (₹) — optional</label>
      <input type="number" step="0.01" min="0" class="input" id="co-reassign-amt" placeholder="Leave blank to keep" />
    `, `
      <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="CustomerOrders.submitParcelReassign(${billId})">Save</button>
    `, "sm");
  }

  async function submitParcelReassign(billId) {
    const agentId = Number(document.getElementById("co-reassign-agent")?.value || 0);
    const amtRaw = (document.getElementById("co-reassign-amt")?.value || "").trim();
    if (!agentId) return ctx.toast("Pick agent", "error");
    const body = { freight_agent_id: agentId };
    if (amtRaw !== "") body.freight_charges = parseFloat(amtRaw);
    ctx.showLoading?.();
    try {
      await ctx.api(`/freight-agents/parcels/${billId}`, { method: "PATCH", body: JSON.stringify(body) }, 0);
      ctx.toast("Agent updated", "success");
      App.closeDetail?.();
      ctx.invalidateCache?.("/freight-agents");
      await loadDispatch();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

