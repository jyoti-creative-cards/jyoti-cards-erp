  async function loadDispatch() {
    ctx.showLoading?.();
    try {
      const q = new URLSearchParams({ status: dispatchStatus, day: dayParam() });
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

  function renderDispatchList() {
    const el = document.getElementById("customer-orders-list");
    if (!el) return;
    const canWrite = !!ctx.canWrite?.("customer_orders");
    const list = filterDispatchParcels(dispatchParcels);
    if (!list.length) {
      el.innerHTML = OrdersUI.emptyState({
        title: dispatchStatus === "pending" ? "No pending parcels" : "No parcels",
        sub: "After bill, parcels land here. Bus: tick Picked when agent takes goods. Transport / self-pickup: mark dispatched.",
      });
      return;
    }
    el.innerHTML = `<div class="ord-card-list">${list.map(p => {
      const pending = p.status === "pending";
      const mode = p.transport_mode || (p.freight_agent_id ? "bus" : "self_pickup");
      const modeLbl = mode === "bus" ? "Bus" : mode === "transport" ? "Transport" : "Self-pickup";
      const chargeLbl = mode === "transport" ? "transport" : mode === "bus" ? "freight" : "";
      const lines = (p.lines || []).slice(0, 6).map(l =>
        `${ctx.esc(l.our_product_id)} × ${l.quantity}`
      ).join(" · ");
      const more = (p.lines || []).length > 6 ? ` · +${p.lines.length - 6} more` : "";
      const meta = [
        p.bill_number ? `Bill ${p.bill_number}` : null,
        modeLbl,
        p.freight_agent_name || null,
        p.transport_receipt_number ? `Rcpt ${p.transport_receipt_number}` : null,
        p.customer_city || null,
        `${p.line_count || 0} lines · ${p.total_pcs || 0} pcs`,
        p.customer_phone || null,
      ].filter(Boolean).join(" · ");
      const actions = [];
      if (canWrite) {
        actions.push(`<button type="button" class="btn btn-secondary btn-sm" onclick="CustomerOrders.openEditBill(${p.bill_id})">Edit</button>`);
      }
      if (pending && canWrite) {
        actions.push(`<button type="button" class="btn btn-primary btn-sm" onclick="CustomerOrders.pickParcel(${p.bill_id}, '${mode}')">${mode === "bus" ? "✓ Picked" : "Mark dispatched"}</button>`);
        if (mode === "bus") {
          actions.push(`<button type="button" class="btn btn-secondary btn-sm" onclick="CustomerOrders.reassignParcel(${p.bill_id})">Change agent</button>`);
        }
      } else if (!pending) {
        actions.push(`<span class="badge badge-green">${mode === "bus" ? "Picked" : "Dispatched"}</span>`);
        if (p.picked_at) actions.push(`<span style="font-size:12px;color:var(--muted);">${ctx.fmtDate?.(p.picked_at) || p.picked_at.slice(0, 10)}</span>`);
      }
      return `<div class="ord-card" style="padding:14px 16px;">
        <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap;">
          <div style="min-width:0;flex:1;">
            <strong class="ord-card-title" style="font-size:16px;">${ctx.esc(p.customer_label || "Customer")}</strong>
            <div class="ord-card-meta" style="margin-top:4px;">${ctx.esc(meta)}</div>
            <div style="font-size:13px;margin-top:8px;">${lines || "—"}${more}</div>
          </div>
          <div style="text-align:right;">
            ${chargeLbl ? `<div style="font-weight:700;font-size:18px;">${fmtPrice(p.freight_charges)}</div>
            <div style="font-size:12px;color:var(--muted);">${chargeLbl}</div>` : `<div style="font-size:12px;color:var(--muted);">No charges</div>`}
            <div class="ord-card-actions" style="margin-top:10px;justify-content:flex-end;">${actions.join("")}</div>
          </div>
        </div>
      </div>`;
    }).join("")}</div>`;
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

