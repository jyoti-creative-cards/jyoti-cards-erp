/** Customer orders — Today/Past date scope + same stage chips */
const CustomerOrders = (() => {
  let ctx = {};
  let orders = [];
  let currentOrder = null;
  let currentBucket = "open"; // same stages for Today + Past
  let hubMode = "queue"; // queue (Today) | past — date scope only
  let hubSearch = "";
  let coExpandedId = null;
  let hubExpandedCustomerId = null;
  let hubExpandCache = {};
  let detailCustomerId = null;

  let dispatchParcels = [];
  let dispatchAgents = [];
  let dispatchStatus = "pending"; // pending | picked | all
  let dispatchAgentId = ""; // "" = all agents

  let processStep = 1;
  let processContext = null;
  let processLines = [];
  let discountEnabled = false;
  let useOverallDiscount = false;
  let overallDiscount = "";
  let gstEnabled = false;
  let gstRate = "18";
  let freightAgents = [];
  let billSeries = [];
  let freightAgentId = "";
  let freightCharges = "";
  let transportMode = "";
  let transportReceiptNumber = "";
  let packagingCharges = "";
  let additionalCharges = [{ name: "", amount: "" }];
  let billSeriesId = "";
  let customerNotes = "";
  let narration = "";
  let previewTotals = null;
  let processBusy = false;
  let forceCreditOverride = false;
  let editBillId = null;
  let editBillNumber = "";
  let billEditSearch = "";
  let billEditProducts = [];

  // Past stages — Dispatch is an ops stage (parcels), not a Today/Past peer.
  const PAST_BUCKETS = ["received", "open", "billed", "dispatch", "cancelled", "closed"];
  const BROWSE_BUCKETS = PAST_BUCKETS; // legacy alias
  const BUCKET_LABELS = {
    needs_action: "Today",
    queue: "Today",
    summary: "Today",
    received: "New",
    open: "Confirmed",
    billed: "Billed",
    dispatch: "Dispatch",
    cancelled: "Cancelled",
    closed: "Done",
  };

  const BUCKET_HINTS = {
    received: "Review each order, edit if needed, then confirm →",
    open: "Goods being picked — create bill when ready. Edit if quantities change.",
    billed: "Bill sent — dispatch or collect payment first, then close.",
    dispatch: "Track parcels and agent pickups.",
    closed: "All settled.",
  };

  function isTodayMode() {
    return hubMode === "queue" || hubMode === "needs_action" || hubMode === "today";
  }

  function dayParam() {
    return isTodayMode() ? "today" : "all";
  }

  function isDispatchBucket() {
    return currentBucket === "dispatch";
  }

  /** Jump to Dispatch stage (keeps Today/Past date scope). */
  function goToDispatch() {
    closeSlidePanel();
    currentBucket = "dispatch";
    dispatchStatus = "pending";
    hubSearch = "";
    hubExpandedCustomerId = null;
    hubExpandCache = {};
    syncHubChrome();
    loadDispatch();
    App.updateGlobalBack?.();
  }

  function customerActionOf(o) {
    return (o.total_quantity || 0) > 0 ? "to_bill" : "other";
  }

  let offlineStep = 1;
  let offlineCustomerId = null;
  let offlineCustomerName = "";
  let offlineCustomerSearch = "";
  let offlineLines = [];
  let offlineSearchQuery = "";
  let offlineSearchResults = [];
  let offlineNotes = "";
  let offlinePlacedOn = "";
  let offlinePreview = null;
  let offlineBusy = false;
  let offlineCustomers = [];
  let offlineEditPlacementId = null;
  let offlineSelectedDetail = null; // full customer detail with outstanding/credit
  let billDate = "";

  function localToday() {
    const n = new Date();
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
  }

  function init(context) { ctx = context; }

  function syncHubChrome() {
    const chips = document.getElementById("co-bucket-bar");
    const actionHost = document.getElementById("co-action-chips");
    const today = isTodayMode();
    const dispatch = isDispatchBucket();
    chips?.classList.remove("hidden");
    OrdersUI.syncModeButtons("#co-hub-mode", today ? "queue" : "past");
    OrdersUI.syncStageChips("#co-bucket-bar", currentBucket);
    if (dispatch) {
      OrdersUI.actionChips({
        hostId: "co-action-chips",
        active: dispatchStatus,
        onclickFn: "CustomerOrders.setDispatchStatus",
        items: [
          { id: "pending", label: "Pending pick", count: dispatchStatus === "pending" ? dispatchParcels.length : undefined },
          { id: "picked", label: "Picked" },
          { id: "all", label: "All" },
        ],
      });
    } else if (actionHost) {
      actionHost.innerHTML = "";
      actionHost.classList.add("hidden");
    }
    const title = document.getElementById("co-list-title");
    const hint = document.getElementById("co-list-hint");
    if (title) {
      const stage = BUCKET_LABELS[currentBucket] || "Orders";
      if (dispatch) {
        const sub = dispatchStatus === "picked" ? "Picked" : dispatchStatus === "all" ? "All parcels" : "Pending pick";
        title.textContent = today ? `Today · ${sub}` : sub;
        if (hint) hint.textContent = BUCKET_HINTS["dispatch"] || "";
      } else {
        title.textContent = today ? `Today · ${stage}` : stage;
        if (hint) hint.textContent = today ? (BUCKET_HINTS[currentBucket] || "") : "";
      }
    }
    const searchSlot = document.getElementById("co-hub-search-slot");
    if (searchSlot) {
      const agentOpts = [
        `<option value="">All agents</option>`,
        ...dispatchAgents.map(a =>
          `<option value="${a.id}" ${String(dispatchAgentId) === String(a.id) ? "selected" : ""}>${ctx.esc(a.name)}</option>`
        ),
      ].join("");
      searchSlot.innerHTML = dispatch
        ? `<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;width:100%;">
            <select class="input" style="max-width:200px;" onchange="CustomerOrders.setDispatchAgent(this.value)">
              ${agentOpts}
            </select>
            ${HubUI.searchBar({
              id: "co-hub-search",
              value: hubSearch,
              placeholder: "Search customer, bill…",
              oninput: "CustomerOrders.setHubSearch(this.value)",
            })}
          </div>`
        : HubUI.searchBar({
          id: "co-hub-search",
          value: hubSearch,
          placeholder: "Search customer…",
          oninput: "CustomerOrders.setHubSearch(this.value)",
        });
    }
  }

  function goCollectPayment(customerId) {
    const cid = customerId || detailCustomerId;
    if (!cid) return;
    App.closeDetail?.();
    App.showView("money");
    Finance.openCustomerAr?.(cid, { settle: true });
  }

  function updateDetailPrimary() {
    // No-op: action buttons are now embedded in renderDetail() body content
  }

  function updateActionButtons(view) {
    if (view === "detail") updateDetailPrimary();
  }

  function setHubMode(mode) {
    // Legacy: setHubMode('dispatch') → Dispatch stage
    if (mode === "dispatch") {
      goToDispatch();
      return;
    }
    if (mode === "browse" || mode === "past") hubMode = "past";
    else hubMode = "queue";
    if (!PAST_BUCKETS.includes(currentBucket)) currentBucket = "open";
    hubExpandedCustomerId = null;
    hubExpandCache = {};
    hubSearch = "";
    syncHubChrome();
    loadList();
  }

  function setDispatchStatus(status) {
    dispatchStatus = ["pending", "picked", "all"].includes(status) ? status : "pending";
    loadDispatch();
  }

  function setDispatchAgent(id) {
    dispatchAgentId = id ? String(id) : "";
    loadDispatch();
  }

  function setQueueFilter() {
    /* removed — Today/Past share stage chips */
  }

  function setHubSearch(val) {
    hubSearch = val || "";
    hubExpandedCustomerId = null;
    if (isDispatchBucket()) renderDispatchList();
    else renderList();
  }

  function filterHubOrders(list) {
    // Hub rows only have customer_name — still token-match; rank by name starts-with
    const ranked = OrdersUI.filterAndRankParties(
      (list || []).map(o => ({
        ...o,
        business_name: o.customer_name || o.business_name || "",
      })),
      hubSearch,
    );
    return ranked;
  }

  function addonsUnderHtml(addons, qtyScale) {
    const list = Array.isArray(addons) ? addons : [];
    if (!list.length) return "";
    const scale = Number(qtyScale) > 0 ? Number(qtyScale) : 1;
    return `<div class="co-addons">${list.map(a => {
      const per = Number(a.quantity) || 1;
      const total = per * scale;
      const label = a.name || a.our_product_id || "Add-on";
      return `<div class="co-addon-row">+ ${ctx.esc(a.our_product_id || "")} · ${ctx.esc(label)} × ${total}</div>`;
    }).join("")}</div>`;
  }

  function calcNetFromDisc(rate, discPct) {
    const r = Number(rate);
    const d = Number(discPct);
    if (!Number.isFinite(r) || r <= 0) return "";
    if (!Number.isFinite(d) || d <= 0) return String(r);
    const net = r * (1 - Math.min(100, Math.max(0, d)) / 100);
    return (Math.round(net * 100) / 100).toString();
  }

  function calcDiscFromNet(rate, netRate) {
    const r = Number(rate);
    const n = Number(netRate);
    if (!Number.isFinite(r) || r <= 0 || !Number.isFinite(n) || n < 0) return "";
    if (n >= r) return "0";
    const pct = ((r - n) / r) * 100;
    return (Math.round(pct * 100) / 100).toString();
  }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function thumb(url) {
    if (url) return `<img src="${ctx.esc(url)}" alt="" class="vo-thumb" />`;
    return `<div class="vo-thumb vo-thumb-empty">—</div>`;
  }

  function setBucket(bucket) {
    // Stage only — do not flip Today/Past
    currentBucket = PAST_BUCKETS.includes(bucket) ? bucket : "open";
    hubExpandedCustomerId = null;
    hubExpandCache = {};
    hubSearch = "";
    syncHubChrome();
    loadList();
  }

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
        actions.push(`<button type="button" class="btn btn-primary btn-sm" onclick="CustomerOrders.pickParcel(${p.bill_id})">${mode === "bus" ? "✓ Picked" : "Mark dispatched"}</button>`);
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

  async function pickParcel(billId) {
    if (!confirm("Mark picked? Freight amount goes to this agent's dues in Money → Freight.")) return;
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

  async function loadList() {
    if (isDispatchBucket()) {
      await loadDispatch();
      return;
    }
    ctx.showLoading?.();
    try {
      if (!PAST_BUCKETS.includes(currentBucket) || currentBucket === "dispatch") {
        currentBucket = "open";
      }
      const day = dayParam();
      orders = await ctx.api(`/customer-orders?bucket=${currentBucket}&day=${day}`, {}, 0);
      if (!Array.isArray(orders)) orders = [];
      syncHubChrome();
      renderList();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function showHub() {
    closeSlidePanel();
    hubExpandedCustomerId = null;
    hubExpandCache = {};
    if (!PAST_BUCKETS.includes(currentBucket)) currentBucket = "open";
    syncHubChrome();
    loadList();
    App.updateGlobalBack?.();
  }

  function detailBucketFor(o) {
    if (currentBucket === "dispatch" || currentBucket === "summary" || currentBucket === "queue") {
      return (o.total_quantity || 0) > 0 ? "open" : "received";
    }
    if (["received", "open", "billed", "cancelled", "closed"].includes(currentBucket)) {
      return currentBucket;
    }
    return (o.total_quantity || 0) > 0 ? "open" : "received";
  }

  function filterQueueList(list) {
    return list;
  }

  function sourceMeta(sources) {
    const list = Array.isArray(sources) ? sources : [];
    if (!list.length) return "";
    return list.map(s => {
      if (s === "phone") return "Phone";
      if (s === "portal") return "Portal";
      return String(s);
    }).filter(Boolean).join(" · ");
  }

  function renderHubExpand(detail, canWrite, customerId) {
    const lines = detail?.open_lines || [];
    if (!lines.length) return `<p class="vo-muted" style="margin:0;">Nothing to bill.</p>`;
    return `<table class="data vo-hub-table"><thead><tr>
      <th></th><th>Product</th><th>To bill</th><th>Rate</th>
    </tr></thead><tbody>
      ${lines.map(l => {
        const img = (l.image_urls || [])[0] || "";
        return `<tr>
          <td>${thumb(img)}</td>
          <td><strong>${ctx.esc(l.our_product_id)}</strong></td>
          <td><strong>${l.quantity_open}</strong></td>
          <td>${fmtPrice(l.unit_price)}</td>
        </tr>`;
      }).join("")}
    </tbody></table>
    ${canWrite ? `<div class="vo-hub-expand-actions">
      <button class="btn btn-primary" onclick="CustomerOrders.processFromHub(${customerId}, 'open')">Create Bill</button>
      <button class="btn btn-danger" onclick="CustomerOrders.cancelCustomerOpen(${customerId})">Cancel order</button>
    </div>` : ""}`;
  }

  function renderOrderCard(o, canWrite) {
    const openQty = o.total_quantity || 0;
    const bucket = detailBucketFor(o);
    const src = sourceMeta(o.sources);
    const canMoney = !!ctx.isAdmin?.() || !!ctx.canWrite?.("accounts_receivable") || !!ctx.canWrite?.("finance");
    const viewFn = `CustomerOrders.openDetail(${o.customer_id}, '${bucket}')`;

    // Primary action by bucket
    let primaryLabel = "View";
    let primaryOnclick = viewFn;
    let statText = "";
    if (currentBucket === "open") {
      primaryLabel = "Create Bill";
      primaryOnclick = `CustomerOrders.processFromHub(${o.customer_id}, 'open')`;
      statText = `${o.line_count || 0} lines · ${openQty} to bill`;
    } else if (currentBucket === "received") {
      primaryLabel = canWrite ? "Confirm →" : "View";
      primaryOnclick = canWrite ? `CustomerOrders.confirmOrder(${o.customer_id})` : viewFn;
      statText = `${o.placement_count || 0} placement${(o.placement_count || 0) !== 1 ? "s" : ""} · ${o.total_quantity || 0} pcs`;
    } else if (currentBucket === "billed") {
      primaryLabel = "Dispatch";
      primaryOnclick = "CustomerOrders.goToDispatch()";
      statText = `${o.placement_count || o.bill_count || 0} bill${(o.placement_count || 0) !== 1 ? "s" : ""}`;
    } else if (currentBucket === "cancelled" || currentBucket === "closed") {
      statText = `${o.placement_count || 0} placement${(o.placement_count || 0) !== 1 ? "s" : ""}`;
    }
    if (src) statText += (statText ? " · " : "") + src;

    // More menu
    const more = [];
    more.push({ label: "Open detail", onclick: viewFn });
    if (canWrite && (currentBucket === "received" || currentBucket === "open")) {
      more.push({ label: "Edit / place more", onclick: `CustomerOrders.openOfflineWizard(${o.customer_id})` });
    }
    if (currentBucket === "billed") {
      if (canMoney) more.push({ label: "Collect payment", onclick: `CustomerOrders.goCollectPayment(${o.customer_id})` });
      if (canWrite) more.push({ label: "Edit bill", onclick: `CustomerOrders.editLatestBill(${o.customer_id})` });
      if (canWrite) more.push({ label: "Close order", onclick: `CustomerOrders.openCloseBatch(${o.customer_id})` });
    }
    if (canWrite && openQty > 0 && (currentBucket === "open" || currentBucket === "received")) {
      more.push({ label: "Cancel order", onclick: `CustomerOrders.cancelCustomerOpen(${o.customer_id})`, danger: true });
    }

    // Party name HTML
    const _m1Upper = (o.marker_1 || "").toUpperCase();
    const nameHtml = (o.party_number ? `<span style="color:var(--muted);font-size:11px;font-weight:600;">#${o.party_number}</span> ` : "")
      + ctx.esc(o.customer_name)
      + (o.marker_1 ? ` <span class="badge badge-blue" style="font-size:9px;padding:1px 4px;">${ctx.esc(o.marker_1)}</span>` : "")
      + (o.marker_2 ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;">${ctx.esc(o.marker_2)}</span>` : "")
      + (o.payment_type === "CASH" && !_m1Upper.includes("CASH") ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;">CASH</span>` : "");

    const timeStr = o.updated_at ? (ctx.timeAgo?.(o.updated_at) || "") : "";
    const bucketCls = { received: "ord-order-card--received", open: "ord-order-card--open", billed: "ord-order-card--billed", closed: "ord-order-card--closed", cancelled: "ord-order-card--cancelled" }[currentBucket] || "";

    const avatarLetter = ctx.esc((o.customer_name || "?").slice(0, 1).toUpperCase());

    // More menu HTML (inline, no OrdersUI.moreMenu — build simple dropdown)
    const moreHtml = more.length ? `<div class="ord-more-wrap" style="position:relative;">
      <button type="button" class="btn btn-ghost btn-sm" style="padding:0 8px;" onclick="event.stopPropagation();CustomerOrders.toggleCardMore(event,${o.customer_id})">⋮</button>
      <div id="co-card-more-${o.customer_id}" class="ord-more-menu" style="display:none;position:absolute;right:0;bottom:calc(100% + 4px);z-index:20;background:#fff;border:1px solid #e2e8f0;border-radius:10px;box-shadow:0 8px 24px rgba(15,23,42,.12);min-width:160px;overflow:hidden;">
        ${more.map(m => `<button type="button" class="ord-more-item${m.danger ? " ord-more-danger" : ""}" onclick="event.stopPropagation();CustomerOrders.closeAllCardMore();${m.onclick}">${ctx.esc(m.label)}</button>`).join("")}
      </div>
    </div>` : "";

    const primaryBtn = (canWrite || currentBucket === "billed" || currentBucket === "cancelled" || currentBucket === "closed")
      ? `<button type="button" class="btn btn-primary btn-sm" onclick="event.stopPropagation();${primaryOnclick}">${ctx.esc(primaryLabel)}</button>`
      : `<button type="button" class="btn btn-secondary btn-sm" onclick="event.stopPropagation();${viewFn}">View</button>`;

    return `<div class="ord-order-card ${bucketCls}" onclick="${viewFn}">
      <div class="ord-order-card-head">
        <div class="ord-order-card-avatar">${avatarLetter}</div>
        <div class="ord-order-card-party">
          <div class="ord-order-card-name">${nameHtml}</div>
          <div class="ord-order-card-city">${o.city_name ? ctx.esc(o.city_name) : ""}${o.city_name && timeStr ? " · " : ""}${timeStr ? `<span class="ord-order-card-time">${ctx.esc(timeStr)}</span>` : ""}</div>
        </div>
      </div>
      <div class="ord-order-card-body">
        ${statText ? `<div class="ord-order-card-stat">${statText}</div>` : ""}
      </div>
      <div class="ord-order-card-foot" onclick="event.stopPropagation()">
        ${primaryBtn}
        ${moreHtml}
      </div>
    </div>`;
  }

  function toggleCardMore(e, customerId) {
    const id = `co-card-more-${customerId}`;
    const el = document.getElementById(id);
    if (!el) return;
    const isOpen = el.style.display !== "none";
    closeAllCardMore();
    if (!isOpen) el.style.display = "block";
  }

  function closeAllCardMore() {
    document.querySelectorAll('[id^="co-card-more-"]').forEach(el => { el.style.display = "none"; });
  }

  function renderList() {
    const el = document.getElementById("customer-orders-list");
    if (!el) return;
    const canWrite = !!ctx.canWrite?.("customer_orders");
    const list = filterHubOrders(orders);
    const stage = BUCKET_LABELS[currentBucket] || "orders";
    const today = isTodayMode();

    if (!list.length) {
      el.innerHTML = OrdersUI.emptyState({
        title: today ? `No ${stage} today` : `No ${stage}`,
        sub: today
          ? "Switch to Past for older dates. Same stages there."
          : "Try another stage, or place an order.",
        ctaHtml: canWrite
          ? `<button class="btn btn-primary" onclick="CustomerOrders.openOfflineWizard()">+ Place for customer</button>`
          : "",
      });
      return;
    }
    el.innerHTML = list.map(o => renderOrderCard(o, canWrite)).join("");
    // Close card more menus on outside click
    document.removeEventListener("click", closeAllCardMore);
    document.addEventListener("click", closeAllCardMore);
  }

  function openSlidePanel() {
    const panel = document.getElementById("co-slide-panel");
    const backdrop = document.getElementById("co-slide-backdrop");
    panel?.classList.add("is-open");
    backdrop?.classList.add("is-open");
    document.body.style.overflow = "hidden";
    // Escape key handler
    document._coSlideEscHandler = (e) => { if (e.key === "Escape") closeSlidePanel(); };
    document.addEventListener("keydown", document._coSlideEscHandler);
  }

  function closeSlidePanel() {
    const panel = document.getElementById("co-slide-panel");
    const backdrop = document.getElementById("co-slide-backdrop");
    panel?.classList.remove("is-open");
    backdrop?.classList.remove("is-open");
    document.body.style.overflow = "";
    if (document._coSlideEscHandler) {
      document.removeEventListener("keydown", document._coSlideEscHandler);
      document._coSlideEscHandler = null;
    }
    detailCustomerId = null;
    currentOrder = null;
    App.updateGlobalBack?.();
  }

  async function openDetail(customerId, bucket) {
    ctx.showLoading?.();
    try {
      let b = bucket || "open";
      if (b === "summary" || b === "needs_action" || b === "queue") b = "open";
      if (b === "dispatch") b = "billed"; // Dispatch is hub-only (parcels), not customer detail
      const detailBuckets = ["received", "open", "billed", "cancelled", "closed"];
      if (!detailBuckets.includes(b)) b = "open";
      currentBucket = b;
      detailCustomerId = customerId;
      coExpandedId = null;
      currentOrder = await ctx.api(`/customer-orders/customer/${customerId}?bucket=${b}`, {}, 0);
      OrdersUI.syncStageChips("#co-detail-bucket-bar", b);
      renderDetail();
      openSlidePanel();
      App.updateGlobalBack?.();
      return true;
    } catch (e) {
      ctx.toast(e.message, "error");
      return false;
    } finally { ctx.hideLoading?.(); }
  }

  async function switchBucket(bucket) {
    if (!detailCustomerId) return;
    if (bucket === "dispatch") {
      goToDispatch();
      return;
    }
    coExpandedId = null;
    await openDetail(detailCustomerId, bucket);
  }

  function renderDetail() {
    const el = document.getElementById("co-detail-body");
    const title = document.getElementById("co-detail-title");
    const sub = document.getElementById("co-detail-sub");
    if (!el || !currentOrder) return;
    if (title) {
      const o = currentOrder;
      const _m1u = (o.marker_1 || "").toUpperCase();
      const pn = o.party_number ? `<span style="color:var(--muted);font-size:14px;font-weight:600;margin-right:6px;">#${o.party_number}</span>` : "";
      const m1 = o.marker_1 ? ` <span class="badge badge-blue" style="font-size:10px;vertical-align:middle;">${ctx.esc(o.marker_1)}</span>` : "";
      const m2 = o.marker_2 ? ` <span class="badge badge-amber" style="font-size:10px;vertical-align:middle;">${ctx.esc(o.marker_2)}</span>` : "";
      const pt = (o.payment_type === "CASH" && !_m1u.includes("CASH")) ? ` <span class="badge badge-amber" style="font-size:10px;vertical-align:middle;">CASH</span>` : "";
      title.innerHTML = pn + ctx.esc(o.customer_name) + m1 + m2 + pt;
    }
    if (sub) {
      sub.textContent = currentBucket === "received" ? "Review order, edit if needed, then Confirm →"
        : currentBucket === "open" ? "Goods being picked — Create Bill when ready"
          : currentBucket === "billed" ? "Bill created — Dispatch or Collect payment, then Close"
            : currentBucket === "closed" ? "Done"
              : "Cancelled";
    }
    const canWrite = !!ctx.canWrite?.("customer_orders");
    const canMoney = !!ctx.isAdmin?.() || !!ctx.canWrite?.("accounts_receivable") || !!ctx.canWrite?.("finance");

    if (currentBucket === "open") {
      const lines = currentOrder.open_lines || [];
      el.innerHTML = `
        ${cashWarningHtml(currentOrder)}
        ${canWrite && lines.length ? `<div class="ui-toolbar" style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary btn-sm" onclick="CustomerOrders.processOrder()">Create Bill</button>
          <button class="btn btn-secondary btn-sm" onclick="CustomerOrders.openEditFromOpen()">Edit order</button>
          <button class="btn btn-danger btn-sm" onclick="CustomerOrders.cancelCustomerOpen(${detailCustomerId})">Cancel order</button>
        </div>` : ""}
        <div class="ord-hub-list">${lines.length ? lines.map(line => HubUI.partyCard({
          title: line.our_product_id,
          meta: `${thumb((line.image_urls || [])[0])} Recv ${line.quantity_received} · To bill <strong>${line.quantity_open}</strong> · Billed ${line.quantity_billed} · ${fmtPrice(line.unit_price)}${addonsUnderHtml(line.addons, line.quantity_open)}`,
          pillHtml: "",
          primaryLabel: canWrite ? "Edit qty" : null,
          primaryOnclick: `CustomerOrders.editOpenLine(${line.id}, ${line.quantity_open})`,
          moreItems: canWrite
            ? [
                { label: "Edit order (add/remove)", onclick: "CustomerOrders.openEditFromOpen()" },
                { label: "Cancel line", onclick: `CustomerOrders.cancelOpenLine(${line.id})`, danger: true },
              ]
            : [],
          canWrite,
        })).join("") : HubUI.emptyState({
          title: "Nothing to bill",
          sub: "No open qty for this customer.",
          ctaHtml: canWrite ? `<button class="btn btn-primary" onclick="CustomerOrders.openOfflineWizard()">+ Place for customer</button>` : "",
        })}</div>`;
      return;
    }

    if (currentBucket === "billed" && (currentOrder.bills || []).length) {
      el.innerHTML = `
        ${cashWarningHtml(currentOrder)}
        <div class="ui-toolbar" style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap;">
          ${canWrite ? `<button class="btn btn-primary btn-sm" onclick="CustomerOrders.goToDispatch()">Dispatch</button>` : ""}
          ${canMoney ? `<button class="btn btn-primary btn-sm" onclick="CustomerOrders.goCollectPayment(${detailCustomerId})">Collect payment</button>` : ""}
          ${canWrite ? `<button class="btn btn-secondary btn-sm" onclick="CustomerOrders.openCloseBatch(${detailCustomerId})">Close order</button>` : ""}
        </div>
        <div class="ord-hub-list">${(currentOrder.bills || []).map(b => {
        const openKey = `bill-${b.id}`;
        const expanded = coExpandedId === openKey;
        const canEditBill = canWrite && (b.lines || []).every(ln => ln.status === "billed");
        const hasFreight = b.transport_mode === "bus" || !!(b.freight_agent_id);
        const modeLbl = b.transport_mode === "bus" ? "Bus" : b.transport_mode === "transport" ? "Transport" : b.transport_mode === "self_pickup" ? "Self-pickup" : (hasFreight ? "Bus" : "");
        const linesHtml = `<table class="data vo-hub-table"><thead><tr><th>Product</th><th>Qty</th><th>Rate</th><th>Disc</th><th>Net</th><th>Total</th><th></th></tr></thead><tbody>
          ${(b.lines || []).map(ln => `<tr>
            <td>${ctx.esc(ln.our_product_id)}${addonsUnderHtml(ln.addons, ln.quantity_shipped)}</td>
            <td>${ln.quantity_shipped}</td>
            <td>${fmtPrice(ln.unit_price)}</td>
            <td>${ln.discount_percent ? ctx.esc(String(ln.discount_percent)) + "%" : "—"}</td>
            <td>${fmtPrice(ln.net_rate)}</td>
            <td>${fmtPrice(ln.line_total)}</td>
            <td>${ln.status === "billed" && canWrite
              ? `<button class="btn btn-secondary btn-sm" onclick="CustomerOrders.closeBillLine(${ln.id})">Close line</button>`
              : `<span class="vo-muted">${ctx.esc(ln.status === "billed" ? "Open" : "Closed")}</span>`}</td>
          </tr>`).join("")}
        </tbody></table>`;
        const more = [
          { label: "Download PDF", onclick: `CustomerOrders.openBillDoc(${b.id}, false)` },
          { label: "WhatsApp", onclick: `CustomerOrders.shareBillWhatsApp(${b.id})` },
        ];
        if (canWrite) {
          more.push({ label: "Edit bill number", onclick: `CustomerOrders.promptEditBillNumber(${b.id}, ${JSON.stringify(b.bill_number || "")})` });
        }
        if (canEditBill) {
          more.push({ label: "Cancel bill", onclick: `CustomerOrders.cancelBill(${b.id})`, danger: true });
        }
        if (canWrite) {
          more.unshift({ label: "Dispatch", onclick: "CustomerOrders.goToDispatch()" });
        }
        more.unshift({ label: "Print", onclick: `CustomerOrders.openBillDoc(${b.id}, true)` });
        const chargeBit = Number(b.freight_charges) > 0
          ? (b.transport_mode === "transport" ? ` · Transport ${fmtPrice(b.freight_charges)}` : ` · Freight ${fmtPrice(b.freight_charges)}`)
          : "";
        const receiptBit = b.transport_receipt_number ? ` · Rcpt ${ctx.esc(b.transport_receipt_number)}` : "";
        return HubUI.partyCard({
          title: `Bill ${b.bill_number}`,
          meta: `${fmtPrice(b.grand_total)} · ${ctx.fmtDate(b.created_at)}${b.bill_date && ctx.fmtDay(b.bill_date) !== ctx.fmtDay(b.created_at) ? ` · Bill ${ctx.fmtDay(b.bill_date)}` : ""}${modeLbl ? ` · ${modeLbl}` : ""}${chargeBit}${receiptBit}${b.narration ? `<div style="margin-top:2px;">${ctx.esc(b.narration)}</div>` : ""}`,
          pillHtml: "",
          primaryLabel: canEditBill ? "Edit" : "Print",
          primaryOnclick: canEditBill
            ? `CustomerOrders.openEditBill(${b.id})`
            : `CustomerOrders.openBillDoc(${b.id}, true)`,
          moreItems: more.filter(m => m.label !== (canEditBill ? "Edit" : "Print")),
          open: expanded,
          rowOnclick: `CustomerOrders.toggleDetailExpand('${openKey}')`,
          canWrite: true,
          expandHtml: expanded ? linesHtml : "",
        });
      }).join("")}</div>`;
      return;
    }

    if (currentBucket === "received") {
      const placements = currentOrder.placements || [];
      el.innerHTML = `
        ${cashWarningHtml(currentOrder)}
        ${canWrite && placements.length ? `<div class="ui-toolbar" style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary btn-sm" onclick="CustomerOrders.confirmOrder(${detailCustomerId})">✓ Confirm order</button>
          <button class="btn btn-secondary btn-sm" onclick="CustomerOrders.openOfflineWizard(${detailCustomerId})">Edit / add items</button>
          <button class="btn btn-danger btn-sm" onclick="CustomerOrders.cancelCustomerOpen(${detailCustomerId})">Cancel order</button>
        </div>` : ""}
        <div class="ord-hub-list">${placements.length ? placements.map(p => {
        const active = (p.lines || []).filter(ln => ln.status === "active");
        const canEdit = canWrite && p.status === "received" && active.length > 0;
        const hasUnbilled = active.some(ln => Number(ln.quantity) > Number(ln.quantity_billed || 0));
        const hasBilled = active.some(ln => Number(ln.quantity_billed) > 0);
        const canCancel = canWrite && p.status === "received" && hasUnbilled;
        const cancelLabel = hasBilled ? "Cancel remaining" : "Cancel order";
        const openKey = `recv-${p.id}`;
        const expanded = coExpandedId === openKey;
        const linesHtml = `<table class="data vo-hub-table"><thead><tr><th>Product</th><th>Qty</th><th>Billed</th><th>Rate</th><th></th></tr></thead><tbody>
          ${(p.lines || []).map(ln => `<tr>
            <td>${ctx.esc(ln.our_product_id)}${addonsUnderHtml(ln.addons, ln.quantity)}</td>
            <td>${ln.quantity}</td>
            <td>${ln.quantity_billed}</td>
            <td>${fmtPrice(ln.unit_price)}</td>
            <td style="white-space:nowrap;">
              ${ln.status === "active" && canWrite ? `
                <button class="btn btn-secondary btn-sm" onclick="CustomerOrders.editReceivedLine(${ln.id}, ${ln.quantity})">Qty</button>
                ${Number(ln.quantity) > Number(ln.quantity_billed || 0)
                  ? `<button class="btn btn-secondary btn-sm" onclick="CustomerOrders.deleteReceivedLine(${ln.id})">Remove</button>`
                  : ""}
              ` : `<span class="vo-muted">${ctx.esc(ln.status || "")}</span>`}
            </td>
          </tr>`).join("")}
        </tbody></table>`;
        const more = [];
        if (canEdit) more.push({ label: "Edit order", onclick: `CustomerOrders.openEditPlacement(${p.id})` });
        if (canCancel) more.push({ label: cancelLabel, onclick: `CustomerOrders.cancelPlacement(${p.id})`, danger: true });
        return HubUI.partyCard({
          title: `Order #${p.id}`,
          meta: `${new Date(p.placed_at).toLocaleString()}${p.customer_notes ? ` · ${ctx.esc(p.customer_notes)}` : ""}${p.cancel_reason ? `<div style="color:var(--danger);margin-top:2px;">Cancelled: ${ctx.esc(p.cancel_reason)}</div>` : ""}`,
          pillHtml: p.cancel_reason ? HubUI.pill("Cancelled", "danger") : "",
          primaryLabel: canEdit ? "Edit" : null,
          primaryOnclick: canEdit ? `CustomerOrders.openEditPlacement(${p.id})` : "",
          moreItems: more.filter(m => !(canEdit && m.label === "Edit order")),
          open: expanded,
          rowOnclick: `CustomerOrders.toggleDetailExpand('${openKey}')`,
          canWrite,
          expandHtml: expanded ? linesHtml : "",
        });
      }).join("") : HubUI.emptyState({
        title: "No orders",
        sub: "No placements for this customer yet.",
        ctaHtml: canWrite ? `<button class="btn btn-primary" onclick="CustomerOrders.openOfflineWizard()">+ Place for customer</button>` : "",
      })}</div>`;
      return;
    }

    // cancelled / closed / billed-without-bills fallback
    const placements = currentOrder.placements || [];
    el.innerHTML = `<div class="ord-hub-list">${placements.length ? placements.map(p => {
      const openKey = `hist-${p.id}`;
      const expanded = coExpandedId === openKey;
      const linesHtml = `<table class="data vo-hub-table"><thead><tr><th>Product</th><th>Qty</th><th>Billed</th><th>Rate</th></tr></thead><tbody>
        ${(p.lines || []).map(ln => `<tr>
          <td>${ctx.esc(ln.our_product_id)}${addonsUnderHtml(ln.addons, ln.quantity)}</td>
          <td>${ln.quantity}</td>
          <td>${ln.quantity_billed}</td>
          <td>${fmtPrice(ln.unit_price)}</td>
        </tr>`).join("")}
      </tbody></table>`;
      return HubUI.partyCard({
        title: `Placement #${p.id}`,
        meta: `${new Date(p.placed_at).toLocaleString()}${p.customer_notes ? ` · ${ctx.esc(p.customer_notes)}` : ""}${p.cancel_reason ? `<div style="color:var(--danger);margin-top:2px;">Cancelled: ${ctx.esc(p.cancel_reason)}</div>` : ""}`,
        pillHtml: currentBucket === "cancelled" || p.cancel_reason
          ? HubUI.pill("Cancelled", "danger")
          : HubUI.pill(currentBucket === "closed" ? "Closed" : "History", "muted"),
        open: expanded,
        rowOnclick: `CustomerOrders.toggleDetailExpand('${openKey}')`,
        canWrite: true,
        expandHtml: expanded ? linesHtml : "",
      });
    }).join("") : HubUI.emptyState({
      title: "No placements",
      sub: "Nothing in this stage for this customer.",
    })}</div>`;
  }

  function toggleDetailExpand(key) {
    coExpandedId = coExpandedId === key ? null : key;
    renderDetail();
  }

  async function editOpenLine(lineId, currentQty) {
    const raw = prompt("Edit open quantity:", String(currentQty ?? 1));
    if (raw == null) return;
    const qty = parseInt(raw, 10);
    if (!Number.isFinite(qty) || qty < 0) return ctx.toast("Invalid quantity", "error");
    ctx.showLoading?.();
    try {
      await ctx.api(`/customer-orders/open-lines/${lineId}`, {
        method: "PATCH",
        body: JSON.stringify({ quantity: qty }),
      });
      ctx.invalidateCache?.("/customer-orders");
      ctx.toast("Open qty updated", "success");
      if (currentOrder) await openDetail(currentOrder.customer_id, "open");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function editReceivedLine(lineId, currentQty) {
    const raw = prompt("Edit received quantity (0 removes):", String(currentQty ?? 1));
    if (raw == null) return;
    const qty = parseInt(raw, 10);
    if (!Number.isFinite(qty) || qty < 0) return ctx.toast("Invalid quantity", "error");
    ctx.showLoading?.();
    try {
      if (qty === 0) {
        await ctx.api(`/customer-orders/lines/${lineId}`, { method: "DELETE" });
        ctx.toast("Line removed", "success");
      } else {
        await ctx.api(`/customer-orders/lines/${lineId}`, {
          method: "PATCH",
          body: JSON.stringify({ quantity: qty }),
        });
        ctx.toast("Received qty updated", "success");
      }
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/stock");
      if (currentOrder) await openDetail(currentOrder.customer_id, "received");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function deleteReceivedLine(lineId) {
    if (!confirm("Remove unbilled qty for this product?")) return;
    ctx.showLoading?.();
    try {
      // Find billed floor — DELETE only works when billed=0; else shrink to billed.
      let billed = 0;
      for (const p of (currentOrder?.placements || [])) {
        const ln = (p.lines || []).find(x => x.id === lineId);
        if (ln) { billed = Number(ln.quantity_billed) || 0; break; }
      }
      if (billed > 0) {
        await ctx.api(`/customer-orders/lines/${lineId}`, {
          method: "PATCH",
          body: JSON.stringify({ quantity: billed }),
        });
        ctx.toast("Unbilled qty removed — billed kept", "success");
      } else {
        await ctx.api(`/customer-orders/lines/${lineId}`, { method: "DELETE" });
        ctx.toast("Line removed", "success");
      }
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/stock");
      if (currentOrder) await openDetail(currentOrder.customer_id, "received");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openEditFromOpen() {
    if (!detailCustomerId) return;
    ctx.showLoading?.();
    try {
      const detail = await ctx.api(`/customer-orders/customer/${detailCustomerId}?bucket=received`, {}, 0);
      const placements = (detail.placements || []).filter(p => p.status === "received");
      const pick = placements.find(p => (p.lines || []).some(ln => ln.status === "active"
        && Number(ln.quantity) > Number(ln.quantity_billed || 0)))
        || placements.find(p => (p.lines || []).some(ln => ln.status === "active"))
        || placements[0];
      if (!pick) return ctx.toast("No incoming order to edit — place one first", "error");
      currentOrder = detail;
      await openEditPlacement(pick.id);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openEditPlacement(placementId) {
    if (!currentOrder) return;
    const p = (currentOrder.placements || []).find(x => x.id === placementId);
    if (!p) return ctx.toast("Placement not found", "error");
    const active = (p.lines || []).filter(ln => ln.status === "active");
    if (!active.length) return ctx.toast("Nothing editable on this placement", "error");

    offlineEditPlacementId = placementId;
    offlineStep = 2;
    offlineCustomerId = currentOrder.customer_id;
    offlineCustomerName = currentOrder.customer_name || currentOrder.customer_label || "";
    offlineNotes = p.customer_notes || "";
    offlinePreview = null;
    offlineBusy = false;
    offlineSearchQuery = "";
    offlineSearchResults = [];
    ctx.showLoading?.();
    try {
      offlineCustomers = await ctx.api("/customers", {}, 30000) || [];
      await ensureOfflineProductsLoaded();
      offlineLines = active.map(ln => {
        const stock = offlineSearchResults.find(x => x.catalog_product_id === ln.catalog_product_id);
        return {
          catalog_product_id: ln.catalog_product_id,
          our_product_id: ln.our_product_id,
          quantity: ln.quantity,
          min_qty: Number(ln.quantity_billed) || 0,
          selling_price: ln.unit_price ?? stock?.selling_price,
          quantity_on_hand: stock?.quantity_on_hand,
        };
      });
      document.getElementById("co-offline-wizard")?.classList.remove("hidden");
      renderOfflineWizard();
    } catch (e) { ctx.toast(e.message, "error"); offlineEditPlacementId = null; }
    finally { ctx.hideLoading?.(); }
  }

  function promptReason(title, onOk) {
    document.getElementById("modal-title").textContent = title;
    document.getElementById("modal-body").innerHTML = `
      <label class="label">Reason (required)</label>
      <textarea class="input" id="co-reason-input" rows="3" style="width:100%;"></textarea>`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" id="co-reason-ok">Confirm</button>`;
    document.getElementById("co-reason-ok").onclick = () => {
      const reason = (document.getElementById("co-reason-input")?.value || "").trim();
      if (!reason) return ctx.toast("Enter a reason", "error");
      App.closeModal();
      onOk(reason);
    };
    document.getElementById("modal").classList.remove("hidden");
  }

  function cancelOpenLine(lineId) {
    promptReason("Cancel line", async (reason) => {
      ctx.showLoading?.();
      try {
        await ctx.api(`/customer-orders/open-lines/${lineId}/cancel`, { method: "POST", body: JSON.stringify({ reason }) });
        ctx.toast("Line cancelled — billed kept", "success");
        await openDetail(detailCustomerId, currentBucket);
        loadList();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
  }

  function cancelPlacement(placementId) {
    const p = (currentOrder?.placements || []).find(x => x.id === placementId);
    const lines = (p?.lines || []).filter(
      ln => ln.status === "active" && Number(ln.quantity) > Number(ln.quantity_billed || 0)
    );
    if (!lines.length) return ctx.toast("Nothing open to cancel — billed qty stays", "error");
    const hasBilled = (p?.lines || []).some(ln => Number(ln.quantity_billed) > 0);
    promptReason(hasBilled ? "Cancel remaining" : "Cancel Order", async (reason) => {
      ctx.showLoading?.();
      try {
        await ctx.api(`/customer-orders/placements/${placementId}/cancel`, {
          method: "POST",
          body: JSON.stringify({ reason }),
        });
        ctx.toast(hasBilled ? "Remaining cancelled — billed kept" : "Order cancelled", "success");
        ctx.invalidateCache?.("/customer-orders");
        await openDetail(detailCustomerId, hasBilled ? "received" : "cancelled");
        loadList();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
  }

  /** Re-fetch open lines by customer id — never use stale currentOrder from another party. */
  async function confirmOrder(customerId) {
    const cid = customerId || detailCustomerId;
    if (!cid) return ctx.toast("No customer", "error");
    ctx.showLoading?.();
    let detail;
    try {
      detail = await ctx.api(`/customer-orders/customer/${cid}?bucket=received`, {}, 0);
    } catch (e) {
      ctx.toast(e.message, "error");
      return;
    } finally {
      ctx.hideLoading?.();
    }

    // Build a flat list of all active lines across all received placements
    const allLines = [];
    for (const p of (detail.placements || [])) {
      for (const ln of (p.lines || [])) {
        if (ln.status === "active") {
          const existing = allLines.find(x => x.our_product_id === ln.our_product_id);
          if (existing) existing.quantity += Number(ln.quantity || 0);
          else allLines.push({ our_product_id: ln.our_product_id, quantity: Number(ln.quantity || 0), unit_price: ln.unit_price });
        }
      }
    }
    if (!allLines.length) return ctx.toast("No items in this order", "error");

    const linesHtml = allLines.map(ln =>
      `<tr>
        <td style="padding:6px 0;">${ctx.esc(ln.our_product_id)}</td>
        <td style="padding:6px 8px;text-align:right;font-weight:600;">${ln.quantity}</td>
        <td style="padding:6px 0;text-align:right;color:var(--muted);font-size:13px;">${fmtPrice(ln.unit_price)}</td>
      </tr>`
    ).join("");

    ctx.openDetail?.(
      `Confirm order — ${ctx.esc(detail.customer_name)}`,
      `<p style="margin:0 0 12px;font-size:13px;color:var(--muted);">Review the items below and confirm.</p>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr>
          <th style="text-align:left;font-size:12px;color:var(--muted);padding-bottom:6px;border-bottom:1px solid var(--border);">Item</th>
          <th style="text-align:right;font-size:12px;color:var(--muted);padding-bottom:6px;border-bottom:1px solid var(--border);">Qty</th>
          <th style="text-align:right;font-size:12px;color:var(--muted);padding-bottom:6px;border-bottom:1px solid var(--border);">Rate</th>
        </tr></thead>
        <tbody>${linesHtml}</tbody>
      </table>
      <div style="margin-top:16px;display:flex;flex-direction:column;gap:8px;">
        <button class="btn btn-primary" onclick="CustomerOrders._doConfirm(${cid});App.closeDetail?.()">✓ Confirm order</button>
        <button class="btn btn-secondary" onclick="App.closeDetail?.()">Close</button>
      </div>`,
      `<button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail?.()">Cancel</button>`,
      "sm"
    );
  }

  async function _doConfirm(cid) {
    ctx.showLoading?.();
    try {
      await ctx.api(`/customer-orders/customer/${cid}/confirm`, { method: "POST" }, 0);
      ctx.toast("Order confirmed", "success");
      currentBucket = "open";
      syncHubChrome();
      await loadList();
      await openDetail(cid, "open");
    } catch (e) {
      ctx.toast(e.message, "error");
    } finally {
      ctx.hideLoading?.();
    }
  }

  async function cancelCustomerOpen(customerId) {
    const cid = customerId || detailCustomerId;
    if (!cid) return ctx.toast("No customer", "error");
    ctx.showLoading?.();
    try {
      const detail = await ctx.api(`/customer-orders/customer/${cid}?bucket=open`, {}, 0);
      const lines = (detail.open_lines || []).filter(l => Number(l.quantity_open) > 0);
      if (!lines.length) return ctx.toast("No open lines", "error");
      const hasBilled = lines.some(l => Number(l.quantity_billed) > 0);
      promptReason(hasBilled ? "Cancel remaining" : "Cancel Order", async (reason) => {
        ctx.showLoading?.();
        let ok = 0;
        let failed = 0;
        try {
          for (const line of lines) {
            try {
              await ctx.api(`/customer-orders/open-lines/${line.id}/cancel`, {
                method: "POST",
                body: JSON.stringify({ reason }),
              });
              ok += 1;
            } catch (_) { failed += 1; }
          }
          if (failed) ctx.toast(`Cancelled ${ok}, failed ${failed}`, "error");
          else ctx.toast(hasBilled ? `Remaining cancelled ${ok} — billed kept` : `Order cancelled (${ok})`, "success");
          ctx.invalidateCache?.("/customer-orders");
          detailCustomerId = cid;
          currentOrder = detail;
          await openDetail(cid, "open");
          loadList();
        } catch (e) { ctx.toast(e.message, "error"); }
        finally { ctx.hideLoading?.(); }
      });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function cancelAllOpen() {
    return cancelCustomerOpen(detailCustomerId);
  }

  function closeBillLine(lineId) {
    promptReason("Close billed line", async (reason) => {
      ctx.showLoading?.();
      try {
        await ctx.api(`/customer-orders/bill-lines/${lineId}/close`, { method: "POST", body: JSON.stringify({ reason }) });
        ctx.toast("Line closed", "success");
        await openDetail(detailCustomerId, currentBucket);
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
  }

  function cancelBill(billId) {
    promptReason("Cancel bill — qty returns to To bill. Freight cleared.", async (reason) => {
      if (!confirm("Cancel this bill? Order stays open to bill again.")) return;
      ctx.showLoading?.();
      try {
        await ctx.api(`/customer-orders/bills/${billId}/cancel`, {
          method: "POST",
          body: JSON.stringify({ reason }),
        });
        ctx.toast("Bill cancelled — order open again", "success");
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/freight-agents");
        await openDetail(detailCustomerId, "open");
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
  }

  function buildProcessBody() {
    const discOn = discountEnabled;
    const lines = processLines
      .filter(l => Number(l.quantity_to_ship) > 0)
      .map(l => {
        const row = {
          catalog_product_id: l.catalog_product_id,
          quantity_to_ship: Number(l.quantity_to_ship),
          quantity: Number(l.quantity_to_ship),
        };
        if (discOn && !useOverallDiscount) {
          const hasPct = l.discount_percent !== "" && l.discount_percent != null && Number.isFinite(Number(l.discount_percent));
          const hasNet = l.net_rate !== "" && l.net_rate != null && Number.isFinite(Number(l.net_rate));
          if (l.discSource === "net" && hasNet) {
            row.net_rate = Number(l.net_rate);
          } else if (hasPct) {
            row.discount_percent = Number(l.discount_percent);
          } else if (hasNet) {
            row.net_rate = Number(l.net_rate);
          }
        }
        return row;
      });
    const extra = additionalCharges.filter(c => c.name.trim() && c.amount.trim() && Number(c.amount) > 0)
      .map(c => ({ name: c.name.trim(), amount: String(c.amount) }));
    const body = {
      lines,
      gst_enabled: gstEnabled,
      gst_rate_percent: Number(gstRate) || 18,
      narration: narration.trim() || null,
      additional_charges: extra,
      force_credit_override: !!forceCreditOverride,
    };
    if (!editBillId) body.bill_series_id = Number(billSeriesId);
    if ((editBillNumber || "").trim()) body.bill_number = editBillNumber.trim();
    if (discOn && useOverallDiscount && overallDiscount.trim()) {
      body.overall_discount_percent = Number(overallDiscount);
    }
    if (!transportMode) {
      /* router rejects missing mode */
    } else {
      body.transport_mode = transportMode;
    }
    if (transportMode === "transport" && transportReceiptNumber.trim()) {
      body.transport_receipt_number = transportReceiptNumber.trim();
    }
    if (transportMode === "bus" && freightAgentId) body.freight_agent_id = Number(freightAgentId);
    if (transportMode === "bus" || transportMode === "transport") {
      if (freightCharges.trim() !== "") body.freight_charges = String(freightCharges);
    }
    if (packagingCharges.trim()) body.packaging_charges = String(packagingCharges);
    if (!editBillId && billDate) body.bill_date = billDate;
    return body;
  }

  function partyMarkerBadgesHtml(pctx) {
    if (!pctx) return "";
    let h = "";
    if (pctx.marker_1) h += ` <span class="badge badge-blue" style="font-size:11px;">${ctx.esc(pctx.marker_1)}</span>`;
    if (pctx.marker_2) h += ` <span class="badge badge-amber" style="font-size:11px;">${ctx.esc(pctx.marker_2)}</span>`;
    if (pctx.payment_type === "CASH") h += ` <span class="badge badge-amber" style="font-size:11px;">CASH</span>`;
    return h;
  }

  function cashWarningHtml(o) {
    if ((o?.payment_type || "").toUpperCase() !== "CASH") return "";
    return `<div style="padding:8px 14px;margin-bottom:10px;background:#fef3c7;border:1px solid #fde68a;border-radius:6px;font-size:13px;">⚠ <strong>CASH customer</strong> — collect payment at time of billing.</div>`;
  }

  function creditBannerHtml(cr, { afterBill = false } = {}) {
    if (!cr) return "";
    const fmtMoney = v => Math.abs(Number(v)).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const colorMoney = v => {
      const n = Number(v);
      const color = n > 0 ? "#dc2626" : n < 0 ? "#16a34a" : "inherit";
      const label = n > 0 ? `₹${fmtMoney(n)} due` : n < 0 ? `₹${fmtMoney(n)} credit` : "₹0";
      return `<span style="color:${color};">${label}</span>`;
    };
    // track_only = credit_limit is 0 (informational, never enforced)
    if (cr.track_only || cr.unlimited) {
      const currentOut = Number(cr.outstanding || cr.used || 0);
      const afterOut = Number(cr.used_after_bill || currentOut);
      const showAfter = afterBill && Math.abs(afterOut - currentOut) > 0.001;
      return `<div class="card" style="padding:10px 14px;margin-bottom:12px;background:#f8fafc;border:1px solid var(--border);display:flex;gap:20px;flex-wrap:wrap;align-items:center;font-size:13px;">
        <span><strong>Outstanding:</strong> ${colorMoney(currentOut)}</span>
        ${showAfter ? `<span><strong>After this bill:</strong> ${colorMoney(afterOut)}</span>` : ""}
        <span style="color:var(--muted);">Credit limit: ${cr.track_only ? "₹0 (tracking only)" : "Unlimited"}</span>
      </div>`;
    }
    const left = afterBill ? cr.left_after_bill : cr.left;
    const used = afterBill ? cr.used_after_bill : cr.used;
    // Only show "over limit" warning when a real limit is set and it is truly exceeded
    const over = !cr.track_only && !cr.unlimited && cr.would_exceed;
    const bg = over ? "#fef2f2" : "#f0fdf4";
    const border = over ? "#fecaca" : "#bbf7d0";
    return `<div class="card" style="padding:12px 14px;margin-bottom:12px;background:${bg};border:1px solid ${border};">
      <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;">
        <div><strong>Outstanding</strong> ₹${ctx.esc(used)}</div>
        <div>Credit limit ₹${ctx.esc(cr.credit_limit)} · Available ₹${ctx.esc(left)}</div>
      </div>
      ${over ? `<p style="margin:8px 0 0;font-size:13px;color:#b91c1c;">⚠ Over limit — outstanding will exceed credit limit. Bill anyway.</p>` : ""}
    </div>`;
  }

  async function processFromHub(customerId, bucket) {
    await openDetail(customerId, bucket || "open");
    await processOrder();
  }

  async function processOrder() {
    if (!detailCustomerId) return;
    editBillId = null;
    processStep = 1;
    processBusy = false;
    previewTotals = null;
    forceCreditOverride = false;
    ctx.showLoading?.();
    try {
      const [pctx, agents, series] = await Promise.all([
        ctx.api(`/customer-orders/customer/${detailCustomerId}/process-context`, {}, 0),
        ctx.api("/freight-agents", {}, 30000),
        ctx.api("/bill-series", {}, 30000),
      ]);
      processContext = pctx;
      freightAgents = agents || [];
      billSeries = (series || []).filter(s => s.is_active && s.current_num < s.end_num);
      processLines = (pctx.lines || []).map(l => ({
        ...l,
        quantity_to_ship: l.quantity_open,
        discount_percent: "",
        net_rate: calcNetFromDisc(l.unit_price, 0),
        discSource: "",
      }));
      if (!processLines.length) {
        ctx.toast("Nothing to bill yet. Qty must be in To bill (stock reserved). If still in Orders, wait for stock.", "error");
        return;
      }
      discountEnabled = false;
      useOverallDiscount = false;
      overallDiscount = "";
      gstEnabled = false;
      gstRate = "18";
      freightAgentId = "";
      freightCharges = "";
      transportMode = "";
      transportReceiptNumber = "";
      packagingCharges = "";
      additionalCharges = [{ name: "", amount: "" }];
      billSeriesId = billSeries.length ? String(billSeries[0].id) : "";
      editBillNumber = nextBillNumberFromSeries();
      customerNotes = pctx.default_narration || "";
      narration = "";
      billDate = localToday();
      billEditSearch = "";
      document.getElementById("co-wizard")?.classList.remove("hidden");
      const title = document.getElementById("co-wizard-title");
      if (title) title.textContent = "Bill customer";
      renderProcessWizard();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function editLatestBill(customerId) {
    if (!customerId) return;
    ctx.showLoading?.();
    try {
      const detail = await ctx.api(`/customer-orders/customer/${customerId}?bucket=billed`, {}, 0);
      const bills = detail?.bills || [];
      if (!bills.length) return ctx.toast("No bills to edit", "error");
      const editable = bills.find(b => (b.lines || []).length && (b.lines || []).every(ln => ln.status === "billed"));
      const bill = editable || bills[0];
      detailCustomerId = customerId;
      currentOrder = detail;
      await openEditBill(bill.id);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openEditBill(billId) {
    if (!billId) return;
    editBillId = billId;
    processStep = 1;
    processBusy = false;
    previewTotals = null;
    forceCreditOverride = false;
    ctx.showLoading?.();
    try {
      const [bill, agents] = await Promise.all([
        ctx.api(`/customer-orders/bills/${billId}`, {}, 0),
        ctx.api("/freight-agents", {}, 30000),
      ]);
      if (bill.cancelled_at) {
        ctx.toast("Cannot edit — bill cancelled", "error");
        editBillId = null;
        return;
      }
      if ((bill.lines || []).some(ln => ln.status === "closed")) {
        ctx.toast("Cannot edit — close was done. Cancel close first or edit before Close.", "error");
        editBillId = null;
        return;
      }
      detailCustomerId = bill.customer_id || detailCustomerId;
      processContext = { customer_id: bill.customer_id, customer_name: currentOrder?.customer_name || "" };
      freightAgents = agents || [];
      billSeries = [];
      processLines = (bill.lines || []).filter(ln => ln.status === "billed").map(l => ({
        catalog_product_id: l.catalog_product_id,
        our_product_id: l.our_product_id,
        unit_price: l.unit_price,
        quantity_open: 999999,
        quantity_on_hand: "—",
        quantity_to_ship: l.quantity_shipped,
        discount_percent: l.discount_percent || "",
        net_rate: l.net_rate || (l.discount_percent
          ? calcNetFromDisc(l.unit_price, l.discount_percent)
          : calcNetFromDisc(l.unit_price, 0)),
        discSource: l.discount_percent ? "pct" : (l.net_rate ? "net" : ""),
        addons: l.addons || [],
      }));
      if (!processLines.length) {
        ctx.toast("No editable lines on this bill", "error");
        editBillId = null;
        return;
      }
      const hasOverall = bill.discount_percent != null && Number(bill.discount_percent) > 0;
      const hasLineDisc = processLines.some(l => l.discount_percent && Number(l.discount_percent) > 0);
      discountEnabled = hasOverall || hasLineDisc;
      useOverallDiscount = hasOverall;
      overallDiscount = hasOverall ? String(bill.discount_percent) : "";
      gstEnabled = !!bill.gst_enabled;
      gstRate = bill.gst_rate_percent != null ? String(bill.gst_rate_percent) : "18";
      freightAgentId = bill.freight_agent_id != null ? String(bill.freight_agent_id) : "";
      freightCharges = bill.freight_charges != null ? String(bill.freight_charges) : "";
      transportMode = bill.transport_mode || (bill.freight_agent_id ? "bus" : (Number(bill.freight_charges) > 0 ? "transport" : "self_pickup"));
      transportReceiptNumber = bill.transport_receipt_number || "";
      packagingCharges = bill.packaging_charges != null ? String(bill.packaging_charges) : "";
      additionalCharges = (bill.additional_charges || []).length
        ? bill.additional_charges.map(c => ({ name: c.name || "", amount: String(c.amount || "") }))
        : [{ name: "", amount: "" }];
      billSeriesId = bill.bill_series_id != null ? String(bill.bill_series_id) : "";
      editBillNumber = bill.bill_number || "";
      customerNotes = "";
      narration = bill.narration || "";
      billEditSearch = "";
      if (!billEditProducts.length) {
        try { billEditProducts = await ctx.api("/stock/products?lite=1", {}, 120000) || []; }
        catch (_) { billEditProducts = []; }
      }
      document.getElementById("co-wizard")?.classList.remove("hidden");
      const title = document.getElementById("co-wizard-title");
      if (title) title.textContent = `Edit bill ${bill.bill_number}`;
      renderProcessWizard();
    } catch (e) { ctx.toast(e.message, "error"); editBillId = null; }
    finally { ctx.hideLoading?.(); }
  }

  function closeProcessWizard() {
    document.getElementById("co-wizard")?.classList.add("hidden");
    editBillId = null;
    editBillNumber = "";
  }

  function promptEditBillNumber(billId, current) {
    ctx.openDetail?.("Edit bill number", `
      <p style="margin:0 0 12px;color:var(--muted);font-size:13px;">Temporary correction. Must be unique among open bills.</p>
      <label class="label">Bill number</label>
      <input class="input" id="co-edit-bill-num" value="${ctx.esc(current || "")}" />
    `, `
      <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="CustomerOrders.saveBillNumber(${billId})">Save</button>
    `, "sm");
  }

  async function saveBillNumber(billId) {
    const num = (document.getElementById("co-edit-bill-num")?.value || "").trim();
    if (!num) return ctx.toast("Bill number required", "error");
    ctx.showLoading?.();
    try {
      const res = await ctx.api(`/customer-orders/bills/${billId}/number`, {
        method: "PATCH",
        body: JSON.stringify({ bill_number: num }),
      }, 0);
      ctx.toast(`Bill number → ${res.bill_number}`, "success");
      App.closeDetail?.();
      ctx.invalidateCache?.("/customer-orders");
      if (detailCustomerId) await openDetail(detailCustomerId, "billed");
      else await loadList();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function enableDiscount() {
    discountEnabled = true;
    useOverallDiscount = false;
    overallDiscount = "";
    renderProcessWizard();
  }

  function clearDiscount() {
    discountEnabled = false;
    useOverallDiscount = false;
    overallDiscount = "";
    processLines.forEach(l => { l.discount_percent = ""; l.net_rate = ""; l.discSource = ""; });
    renderProcessWizard();
  }

  function addBillEditProduct(catalogProductId) {
    const p = billEditProducts.find(x => x.catalog_product_id === catalogProductId);
    if (!p) return;
    if (processLines.some(l => l.catalog_product_id === catalogProductId)) {
      return ctx.toast("Already on bill", "error");
    }
    processLines.push({
      catalog_product_id: p.catalog_product_id,
      our_product_id: p.our_product_id,
      unit_price: p.selling_price,
      quantity_open: 999999,
      quantity_on_hand: p.quantity_on_hand ?? 0,
      quantity_to_ship: 50,
      discount_percent: "",
      net_rate: "",
      discSource: "",
      addons: p.addons || [],
    });
    billEditSearch = "";
    renderProcessWizard();
  }

  function removeProcessLine(idx) {
    if (!editBillId) return;
    if (processLines.length <= 1) return ctx.toast("Bill needs at least one product", "error");
    processLines.splice(idx, 1);
    renderProcessWizard();
  }

  function setShipQty(idx, val) {
    const ln = processLines[idx];
    if (!ln) return;
    let q = Math.max(0, parseInt(val, 10) || 0);
    if (!editBillId) q = Math.min(ln.quantity_open, q);
    ln.quantity_to_ship = q;
  }

  function setLineDisc(idx, val) {
    const ln = processLines[idx];
    if (!ln) return;
    ln.discount_percent = val;
    ln.discSource = val === "" || val == null ? "" : "pct";
    ln.net_rate = val === "" || val == null ? "" : calcNetFromDisc(ln.unit_price, val);
  }

  function setLineNetRate(idx, val) {
    const ln = processLines[idx];
    if (!ln) return;
    ln.net_rate = val;
    ln.discSource = val === "" || val == null ? "" : "net";
    if (val === "" || val == null) {
      ln.discount_percent = "";
      return;
    }
    ln.discount_percent = calcDiscFromNet(ln.unit_price, val);
    discountEnabled = true;
    useOverallDiscount = false;
  }

  function renderProcessWizard() {
    const stepsEl = document.getElementById("co-wizard-steps");
    const bodyEl = document.getElementById("co-wizard-body");
    const footerEl = document.getElementById("co-wizard-footer");
    if (!stepsEl || !bodyEl || !footerEl) return;

    const labels = ["Lines", "Transport", "Charges", "Narration", "Review"];
    stepsEl.innerHTML = labels.map((l, i) => {
      const n = i + 1;
      const cls = n === processStep ? "step active" : n < processStep ? "step done" : "step";
      return `<div class="${cls}"><span class="step-num">${n}</span><span class="step-label">${l}</span></div>`;
    }).join("");

    if (processStep === 1) {
      const lineDiscLocked = !discountEnabled || useOverallDiscount;
      const discPanel = `<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:12px;border:1px solid var(--border);border-radius:10px;background:#fafafa;">
            <strong style="font-size:13px;">Discount</strong>
            <label style="display:flex;align-items:center;gap:6px;font-size:14px;">
              <input type="radio" name="co-disc-mode" ${!discountEnabled ? "checked" : ""} onchange="CustomerOrders.setDiscToggle('off')" /> Off
            </label>
            <label style="display:flex;align-items:center;gap:6px;font-size:14px;">
              <input type="radio" name="co-disc-mode" ${discountEnabled && !useOverallDiscount ? "checked" : ""} onchange="CustomerOrders.setDiscToggle('line')" /> Per item
            </label>
            <label style="display:flex;align-items:center;gap:6px;font-size:14px;">
              <input type="radio" name="co-disc-mode" ${discountEnabled && useOverallDiscount ? "checked" : ""} onchange="CustomerOrders.setDiscToggle('overall')" /> Overall
            </label>
            ${discountEnabled && useOverallDiscount ? `<input class="input" style="width:100px;" placeholder="%" value="${ctx.esc(overallDiscount)}" oninput="CustomerOrders.setOverallDisc(this.value)" />` : ""}
          </div>`;
      const addProd = editBillId ? (() => {
        const q = billEditSearch.trim().toLowerCase();
        const matches = q
          ? billEditProducts.filter(p => String(p.our_product_id || "").toLowerCase().includes(q)).slice(0, 8)
          : [];
        return `<div style="margin-top:14px;">
          <label class="label">Add product</label>
          <input class="input" style="width:100%;margin-bottom:8px;" placeholder="Search product ID…" value="${ctx.esc(billEditSearch)}" oninput="CustomerOrders.setBillEditSearch(this.value)" />
          ${matches.length ? `<div style="display:flex;flex-direction:column;gap:4px;">${matches.map(p => `
            <button type="button" class="btn btn-secondary btn-sm" style="justify-content:flex-start;" onclick="CustomerOrders.addBillEditProduct(${p.catalog_product_id})">
              ${ctx.esc(p.our_product_id)} · ${fmtPrice(p.selling_price)} · stock ${p.quantity_on_hand ?? 0}
            </button>`).join("")}</div>` : (q ? `<p style="font-size:12px;color:var(--muted);">No matches</p>` : "")}
        </div>`;
      })() : "";
      bodyEl.innerHTML = `
        ${!editBillId ? creditBannerHtml(processContext?.credit) : ""}
        <p style="margin:0 0 12px;color:var(--muted);font-size:14px;">Customer: <strong>${processContext?.party_number ? `#${processContext.party_number} ` : ""}${ctx.esc(processContext?.customer_name || "")}</strong>${partyMarkerBadgesHtml(processContext)}${editBillId ? " · editing bill (order syncs on save)" : ""}</p>
        <div style="margin-bottom:12px;">${discPanel}</div>
        <table class="data"><thead><tr>
          <th></th><th>Product</th>${editBillId ? "" : "<th>Stock</th><th>To bill</th>"}<th>Rate</th><th>${editBillId ? "Qty" : "Ship"}</th><th>Disc %</th><th>Net rate</th>${editBillId ? "<th></th>" : ""}
        </tr></thead><tbody>
          ${processLines.map((ln, i) => {
            const shownNet = useOverallDiscount && overallDiscount
              ? calcNetFromDisc(ln.unit_price, overallDiscount)
              : (ln.net_rate || calcNetFromDisc(ln.unit_price, ln.discount_percent || 0));
            const shownDisc = useOverallDiscount ? (overallDiscount || "") : (ln.discount_percent || "");
            const ro = lineDiscLocked ? "readonly" : "";
            return `<tr>
            <td>${thumb((ln.image_urls || [])[0])}</td>
            <td><strong>${ctx.esc(ln.our_product_id)}</strong>${addonsUnderHtml(ln.addons, ln.quantity_to_ship || 1)}</td>
            ${editBillId ? "" : `<td>${ln.quantity_on_hand}</td><td>${ln.quantity_open}</td>`}
            <td>${fmtPrice(ln.unit_price)}</td>
            <td><input type="number" class="input" style="width:72px;" min="0" ${editBillId ? "" : `max="${ln.quantity_open}"`} value="${ln.quantity_to_ship}" onchange="CustomerOrders.setShipQty(${i}, this.value)" /></td>
            <td><input type="number" class="input" style="width:64px;" min="0" max="100" step="0.1" ${ro} value="${ctx.esc(shownDisc)}" oninput="CustomerOrders.setLineDisc(${i}, this.value)" /></td>
            <td><input type="number" class="input" style="width:80px;" min="0" step="0.01" placeholder="₹" ${ro} value="${ctx.esc(shownNet || "")}" oninput="CustomerOrders.setLineNetRate(${i}, this.value)" /></td>
            ${editBillId ? `<td><button type="button" class="btn btn-ghost btn-sm" style="color:var(--danger);" onclick="CustomerOrders.removeProcessLine(${i})">Remove</button></td>` : ""}
          </tr>`;
          }).join("")}
        </tbody></table>
        ${addProd}`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="CustomerOrders.closeProcessWizard()">Cancel</button>
        <button class="btn btn-primary" onclick="CustomerOrders.processNext()">Next →</button>`;
      return;
    }

    if (processStep === 2) {
      const modeBtn = (id, label) => `<button type="button" class="btn ${transportMode === id ? "btn-primary" : "btn-secondary"}" style="flex:1;min-width:120px;" onclick="CustomerOrders.setTransportMode('${id}')">${label}</button>`;
      let extra = "";
      if (transportMode === "bus") {
        extra = `
          <label class="label">Freight agent</label>
          <select class="input" style="margin-bottom:12px;width:100%;" onchange="CustomerOrders.setFreightAgent(this.value)">
            <option value="">— Select agent —</option>
            ${freightAgents.map(a => `<option value="${a.id}" ${String(a.id) === freightAgentId ? "selected" : ""}>${ctx.esc(a.name)} (due ${fmtPrice(a.balance_due)})</option>`).join("")}
          </select>
          <label class="label">Freight charges (₹)</label>
          <input class="input" style="width:100%;max-width:220px;" value="${ctx.esc(freightCharges)}" oninput="CustomerOrders.setFreightCharges(this.value)" />`;
      } else if (transportMode === "transport") {
        extra = `
          <label class="label">Transport charges (₹)</label>
          <input class="input" style="width:100%;max-width:220px;margin-bottom:12px;" value="${ctx.esc(freightCharges)}" oninput="CustomerOrders.setFreightCharges(this.value)" />
          <label class="label">Receipt number <span style="font-weight:400;color:var(--muted);">(optional)</span></label>
          <input class="input" style="width:100%;max-width:280px;" placeholder="If you have it" value="${ctx.esc(transportReceiptNumber)}" oninput="CustomerOrders.setTransportReceipt(this.value)" />`;
      } else if (transportMode === "self_pickup") {
        extra = `<p style="font-size:13px;color:var(--muted);margin:0;">Customer picks up. No agent or charges.</p>`;
      }
      bodyEl.innerHTML = `
        <p style="margin:0 0 12px;color:var(--muted);font-size:14px;">Mode of transport</p>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;">
          ${modeBtn("bus", "Bus")}
          ${modeBtn("transport", "Transport")}
          ${modeBtn("self_pickup", "Self-pickup")}
        </div>
        ${extra}`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="CustomerOrders.processBack()">← Back</button>
        <button class="btn btn-primary" onclick="CustomerOrders.processNext()">Next →</button>`;
      return;
    }

    if (processStep === 3) {
      bodyEl.innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
          <div><label class="label">Packaging (₹)</label><input class="input" value="${ctx.esc(packagingCharges)}" oninput="CustomerOrders.setPackagingCharges(this.value)" /></div>
        </div>
        <label class="label">Additional charges</label>
        ${additionalCharges.map((c, i) => `
          <div style="display:flex;gap:8px;margin-bottom:8px;">
            <input class="input" placeholder="Name" value="${ctx.esc(c.name)}" oninput="CustomerOrders.setAddCharge(${i}, 'name', this.value)" />
            <input class="input" placeholder="₹" style="width:100px;" value="${ctx.esc(c.amount)}" oninput="CustomerOrders.setAddCharge(${i}, 'amount', this.value)" />
          </div>`).join("")}
        <button type="button" class="btn btn-secondary btn-sm" onclick="CustomerOrders.addChargeRow()">+ Add charge</button>
        <div style="margin-top:16px;padding-top:16px;border-top:1px solid var(--border);">
          <label style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
            <input type="checkbox" ${gstEnabled ? "checked" : ""} onchange="CustomerOrders.setGst(this.checked)" /> GST inclusive split
          </label>
          ${gstEnabled ? `<label class="label">GST rate %</label><input class="input" style="width:100px;margin-bottom:12px;" value="${ctx.esc(gstRate)}" oninput="CustomerOrders.setGstRate(this.value)" />` : ""}
          ${editBillId ? "" : `<label class="label">Bill series</label>
          <select class="input" style="width:100%;" onchange="CustomerOrders.setBillSeries(this.value)">
            ${billSeries.map(s => `<option value="${s.id}" ${String(s.id) === billSeriesId ? "selected" : ""}>${ctx.esc(s.name)} (${s.prefix}${s.current_num + 1 >= s.start_num ? s.current_num + 1 : s.start_num}…${s.prefix}${s.end_num})</option>`).join("")}
            ${!billSeries.length ? `<option value="">No series — create one in Setup</option>` : ""}
          </select>`}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="CustomerOrders.processBack()">← Back</button>
        <button class="btn btn-primary" ${(!editBillId && !billSeriesId) ? "disabled" : ""} onclick="CustomerOrders.processNext()">Next →</button>`;
      return;
    }

    if (processStep === 4) {
      bodyEl.innerHTML = `
        ${customerNotes ? `
          <label class="label">Customer note</label>
          <div class="card" style="padding:12px 14px;margin-bottom:16px;background:#f8fafc;white-space:pre-wrap;font-size:14px;">${ctx.esc(customerNotes)}</div>
          <p style="font-size:12px;color:var(--muted);margin:-8px 0 16px;">From the customer — not editable here.</p>
        ` : (editBillId ? "" : `<p style="font-size:13px;color:var(--muted);margin:0 0 16px;">No customer note on this order.</p>`)}
        ${`
          <label class="label">Bill number — temp</label>
          <input class="input" style="width:100%;max-width:220px;margin-bottom:4px;" value="${ctx.esc(editBillNumber)}" oninput="CustomerOrders.setEditBillNumber(this.value)" />
          <p style="font-size:12px;color:var(--muted);margin:0 0 16px;">${editBillId ? "Temporary. Fix typo / wrong number." : "Next from series. Change if you need a different number."} Must be unique among open bills.</p>
        `}
        ${editBillId ? "" : `
          <label class="label">Bill date</label>
          <input type="date" class="input" style="width:100%;max-width:220px;margin-bottom:4px;" value="${ctx.esc(billDate || localToday())}" onchange="CustomerOrders.setBillDate(this.value)" />
          <p style="font-size:12px;color:var(--muted);margin:0 0 16px;">Use the day the bill actually happened (backdate OK).</p>
        `}
        <label class="label">Your narration</label>
        <textarea class="input" rows="4" style="width:100%;" placeholder="Staff note for the bill…" oninput="CustomerOrders.setNarration(this.value)">${ctx.esc(narration)}</textarea>
        <p style="font-size:12px;color:var(--muted);margin-top:8px;">This goes on the bill. Separate from the customer note above.</p>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="CustomerOrders.processBack()">← Back</button>
        <button class="btn btn-primary" onclick="CustomerOrders.processNext()">Review →</button>`;
      return;
    }

    const shipCount = processLines.filter(l => Number(l.quantity_to_ship) > 0).length;
    const tot = previewTotals || {};
    const cr = tot.credit || processContext?.credit;
    const discAmt = Number(tot.discount_amount || 0);
    const lineRows = (tot.lines || []).map(ln => {
      const disc = Number(ln.line_discount || 0);
      const discPct = ln.item_discount_percent ? ` (${ln.item_discount_percent}%)` : "";
      return `<tr>
        <td><strong>${ctx.esc(ln.our_product_id)}</strong></td>
        <td>${ln.quantity}</td>
        <td>${fmtPrice(ln.rate_inclusive || ln.unit_price)}</td>
        <td>${disc > 0 ? `${discPct.trim() || "—"}` : "—"}</td>
        <td>${fmtPrice(ln.net_rate || ln.effective_price)}</td>
        <td>${fmtPrice(ln.line_total)}</td>
      </tr>`;
    }).join("");
    const modeLabel = transportMode === "bus" ? "Bus" : transportMode === "transport" ? "Transport" : transportMode === "self_pickup" ? "Self-pickup" : "—";
    const chargeLabel = transportMode === "transport" ? "Transport charges" : "Freight";
    const agentName = (freightAgents.find(a => String(a.id) === String(freightAgentId)) || {}).name;
    bodyEl.innerHTML = `
      ${creditBannerHtml(cr, { afterBill: true })}
      <div class="card table-wrap" style="margin-bottom:16px;">
        <table class="data"><thead><tr>
          <th>Item</th><th>Qty</th><th>Rate</th><th>Disc</th><th>Net</th><th>Total</th>
        </tr></thead><tbody>
          ${lineRows || `<tr><td colspan="6" style="text-align:center;color:var(--muted);">No lines</td></tr>`}
        </tbody></table>
      </div>
      <div class="review-grid" style="margin-bottom:16px;">
        ${ctx.reviewRow("Customer", processContext?.customer_name)}
        ${ctx.reviewRow("Bill number", editBillNumber || "—")}
        ${!editBillId ? ctx.reviewRow("Bill date", billDate || localToday()) : ""}
        ${ctx.reviewRow("Lines shipping", shipCount)}
        ${ctx.reviewRow("Transport", modeLabel)}
        ${transportMode === "bus" && agentName ? ctx.reviewRow("Freight agent", agentName) : ""}
        ${transportMode === "transport" && transportReceiptNumber.trim() ? ctx.reviewRow("Receipt", transportReceiptNumber.trim()) : ""}
        ${ctx.reviewRow("Subtotal", fmtPrice(tot.subtotal_inclusive))}
        ${discAmt > 0 ? ctx.reviewRow(tot.discount_percent ? `Discount (${tot.discount_percent}%)` : "Discount", "−" + fmtPrice(tot.discount_amount)) : ""}
        ${Number(tot.taxable_value) > 0 && tot.gst_enabled ? ctx.reviewRow("Taxable", fmtPrice(tot.taxable_value)) : ""}
        ${Number(tot.gst_amount) > 0 ? ctx.reviewRow(`GST (${tot.gst_rate_label || ""})`, fmtPrice(tot.gst_amount)) : ""}
        ${tot.freight_charges && transportMode !== "self_pickup" ? ctx.reviewRow(chargeLabel, fmtPrice(tot.freight_charges)) : ""}
        ${tot.packaging_charges ? ctx.reviewRow("Packaging", fmtPrice(tot.packaging_charges)) : ""}
        ${(tot.additional_charges || []).map(c => ctx.reviewRow(c.name, fmtPrice(c.amount))).join("")}
        ${ctx.reviewRow("Grand total", fmtPrice(tot.rounded_grand_total || tot.grand_total))}
      </div>
      ${customerNotes ? `<p style="font-size:13px;margin:0 0 6px;"><span class="vo-muted">Customer note:</span> ${ctx.esc(customerNotes)}</p>` : ""}
      <p style="font-size:13px;color:var(--muted);margin:0;"><span class="vo-muted">Narration:</span> ${ctx.esc(narration || "—")}</p>
      ${editBillId ? `<p style="font-size:12px;color:var(--muted);margin:10px 0 0;">Saving updates the bill and syncs the customer order quantities.</p>` : ""}`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="CustomerOrders.processBack()">← Back</button>
      <button class="btn btn-primary" ${processBusy ? "disabled" : ""} onclick="CustomerOrders.submitProcess()">${processBusy ? "Saving…" : (editBillId ? "Save bill" : "Submit Bill")}</button>`;
  }

  function setForceCredit(v) { forceCreditOverride = !!v; renderProcessWizard(); }

  function setDiscToggle(mode) {
    if (mode === "off") {
      discountEnabled = false;
      useOverallDiscount = false;
      overallDiscount = "";
      processLines.forEach(l => { l.discount_percent = ""; l.net_rate = calcNetFromDisc(l.unit_price, 0); l.discSource = ""; });
    } else if (mode === "overall") {
      discountEnabled = true;
      useOverallDiscount = true;
      processLines.forEach(l => { l.discount_percent = overallDiscount; l.net_rate = calcNetFromDisc(l.unit_price, overallDiscount); l.discSource = ""; });
    } else {
      discountEnabled = true;
      useOverallDiscount = false;
      overallDiscount = "";
    }
    renderProcessWizard();
  }
  function setDiscMode(overall) {
    setDiscToggle(overall ? "overall" : "line");
  }
  function setOverallDisc(v) { overallDiscount = v; }
  function setBillEditSearch(v) { billEditSearch = v || ""; renderProcessWizard(); }
  function setFreightAgent(v) { freightAgentId = v; }
  function setFreightCharges(v) { freightCharges = v; }
  function setTransportMode(v) {
    transportMode = v;
    if (v === "self_pickup") {
      freightAgentId = "";
      freightCharges = "";
      transportReceiptNumber = "";
    } else if (v === "transport") {
      freightAgentId = "";
    } else if (v === "bus") {
      transportReceiptNumber = "";
    }
    renderProcessWizard();
  }
  function setTransportReceipt(v) { transportReceiptNumber = v; }
  function setPackagingCharges(v) { packagingCharges = v; }
  function setGst(v) { gstEnabled = v; renderProcessWizard(); }
  function setGstRate(v) { gstRate = v; }
  function setBillSeries(v) {
    billSeriesId = v;
    if (!editBillId) editBillNumber = nextBillNumberFromSeries();
  }
  function nextBillNumberFromSeries() {
    const s = billSeries.find(x => String(x.id) === String(billSeriesId));
    if (!s) return "";
    const n = s.current_num + 1 >= s.start_num ? s.current_num + 1 : s.start_num;
    return `${s.prefix}${n}`;
  }
  function setNarration(v) { narration = v; }
  function setEditBillNumber(v) { editBillNumber = v || ""; }
  function setBillDate(v) { billDate = v || localToday(); }
  function setAddCharge(i, field, val) { if (additionalCharges[i]) additionalCharges[i][field] = val; }
  function addChargeRow() { additionalCharges.push({ name: "", amount: "" }); renderProcessWizard(); }

  async function processNext() {
    if (processStep === 1) {
      if (!processLines.some(l => Number(l.quantity_to_ship) > 0)) return ctx.toast("Enter qty to ship", "error");
      processStep = 2;
      renderProcessWizard();
      return;
    }
    if (processStep === 2) {
      if (!transportMode) return ctx.toast("Select mode of transport", "error");
      if (transportMode === "bus") {
        if (!freightAgentId) return ctx.toast("Select freight agent", "error");
        if (freightCharges.trim() === "") return ctx.toast("Enter freight charges", "error");
      }
      if (transportMode === "transport" && freightCharges.trim() === "") {
        return ctx.toast("Enter transport charges", "error");
      }
      processStep = 3;
      renderProcessWizard();
      return;
    }
    if (processStep === 3) {
      if (!editBillId && !billSeriesId) return ctx.toast("Select bill series", "error");
      processStep = 4;
      renderProcessWizard();
      return;
    }
    if (processStep === 4) {
      if (editBillId) {
        const lines = processLines.filter(l => Number(l.quantity_to_ship) > 0);
        previewTotals = {
          lines: lines.map(l => {
            const rate = Number(l.unit_price) || 0;
            const qty = Number(l.quantity_to_ship) || 0;
            const discPct = discountEnabled && useOverallDiscount
              ? Number(overallDiscount) || 0
              : (discountEnabled ? Number(l.discount_percent) || 0 : 0);
            const net = discPct > 0 ? rate * (1 - Math.min(100, discPct) / 100) : (Number(l.net_rate) || rate);
            const lineTotal = net * qty;
            const lineDisc = (rate * qty) - lineTotal;
            return {
              our_product_id: l.our_product_id,
              quantity: qty,
              unit_price: l.unit_price,
              rate_inclusive: l.unit_price,
              item_discount_percent: discPct || null,
              net_rate: (Math.round(net * 100) / 100).toString(),
              line_discount: lineDisc > 0 ? lineDisc : 0,
              line_total: lineTotal,
            };
          }),
          subtotal_inclusive: lines.reduce((s, l) => s + (Number(l.unit_price) || 0) * Number(l.quantity_to_ship || 0), 0),
          discount_amount: 0,
          freight_charges: transportMode === "self_pickup" ? null : freightCharges,
          transport_mode: transportMode,
          transport_receipt_number: transportReceiptNumber,
          packaging_charges: packagingCharges,
          grand_total: 0,
        };
        previewTotals.discount_amount = previewTotals.lines.reduce((s, l) => s + Number(l.line_discount || 0), 0);
        previewTotals.grand_total = previewTotals.lines.reduce((s, l) => s + Number(l.line_total || 0), 0)
          + Number(previewTotals.freight_charges || 0) + Number(packagingCharges || 0);
        processStep = 5;
        renderProcessWizard();
        return;
      }
      ctx.showLoading?.();
      try {
        previewTotals = await ctx.api(`/customer-orders/customer/${detailCustomerId}/process/preview`, {
          method: "POST",
          body: JSON.stringify(buildProcessBody()),
        });
        processStep = 5;
        renderProcessWizard();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    }
  }

  function processBack() {
    if (processStep > 1) { processStep -= 1; renderProcessWizard(); }
  }

  async function submitProcess() {
    if (processBusy || !detailCustomerId) return;
    processBusy = true;
    renderProcessWizard();
    ctx.showLoading?.();
    try {
      let res;
      const body = buildProcessBody();
      if (editBillId) {
        res = await ctx.api(`/customer-orders/bills/${editBillId}`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
      } else {
        res = await ctx.api(`/customer-orders/customer/${detailCustomerId}/process`, {
          method: "POST",
          body: JSON.stringify(body),
        });
      }
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/accounts-receivable");
      ctx.invalidateCache?.("/stock");
      const edited = !!editBillId;
      closeProcessWizard();
      const cid = detailCustomerId;
      if (edited) {
        ctx.toast(`Bill ${res.bill_number} updated — order + dispatch synced`, "success");
        ctx.invalidateCache?.("/freight-agents");
        if (isDispatchBucket()) await loadDispatch();
      } else {
        const hasFreight = transportMode === "bus" || !!(res.freight_agent_id || freightAgentId);
        const nextHint = transportMode === "bus" || hasFreight
          ? "Next: Dispatch (agent pick) or Collect."
          : "Next: Dispatch or Collect — then Close.";
        ctx.openDetail?.(`Bill ${res.bill_number}`, `
            <p style="margin:0 0 16px;color:var(--muted);">Bill created — ${fmtPrice(res.grand_total)}. AR posted. ${nextHint}</p>
            <div style="display:flex;flex-direction:column;gap:8px;">
              <button class="btn btn-primary" onclick="App.closeDetail();CustomerOrders.goToDispatch()">Dispatch</button>
              ${(ctx.isAdmin?.() || ctx.canWrite?.("accounts_receivable") || ctx.canWrite?.("finance")) ? `<button class="btn btn-secondary" onclick="App.closeDetail();CustomerOrders.goCollectPayment(${cid})">Collect payment</button>` : ""}
              <button class="btn btn-secondary" onclick="CustomerOrders.openBillDoc(${res.bill_id}, false)">Download PDF</button>
              <button class="btn btn-secondary" onclick="CustomerOrders.openBillDoc(${res.bill_id}, true)">Print</button>
              <button class="btn btn-secondary" onclick="CustomerOrders.shareBillWhatsApp(${res.bill_id})">WhatsApp</button>
              <button class="btn btn-secondary" onclick="App.closeDetail();CustomerOrders.openCloseBatch(${cid})">Close order</button>
            </div>`,
          `<button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail()">Done</button>`, "sm");
        ctx.toast(`Bill ${res.bill_number} — ${fmtPrice(res.grand_total)}`, "success");
      }
      await openDetail(detailCustomerId, "billed");
      loadList();
    } catch (e) {
      ctx.toast(e.message, "error");
      renderProcessWizard();
    } finally {
      processBusy = false;
      ctx.hideLoading?.();
    }
  }

  async function openBillDoc(billId, print) {
    try {
      await DocShare.openPdf(`/share/bills/${billId}/pdf`, {
        print: !!print,
        filename: `bill_${billId}.pdf`,
      });
    } catch (e) {
      try {
        const d = await ctx.api(`/customer-orders/bills/${billId}/document`, {}, 0);
        if (!d.document_url) throw e;
        if (print) {
          const w = window.open(d.document_url, "_blank");
          if (w) w.addEventListener("load", () => w.print());
        } else {
          window.open(d.document_url, "_blank");
        }
      } catch (e2) { ctx.toast(e2.message || e.message, "error"); }
    }
  }

  async function shareBillWhatsApp(billId) {
    ctx.showLoading?.();
    try {
      const res = await DocShare.whatsapp({ kind: "bill", id: billId, caption: `Bill` });
      if (res.ok) ctx.toast("Sent on WhatsApp", "success");
      else {
        ctx.toast(res.hint || "WA failed — opening link", "error");
        if (res.wa_me) window.open(res.wa_me, "_blank");
      }
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function showCreateMenuFromCustomer(customerId) {
    openOfflineWizard(customerId);
  }

  function showCreateMenu() {
    openOfflineWizard(detailCustomerId || null);
  }

  function runHubAction() {
    if (currentBucket === "open" || currentBucket === "received") ctx.toast("Open a customer to process", "error");
    else if (currentBucket === "billed") openCloseBatch(null);
  }

  function runDetailAction() {
    if (currentBucket === "open") processOrder();
    else if (currentBucket === "billed") openCloseBatch(detailCustomerId);
  }

  async function openCloseBatch(customerId) {
    ctx.showLoading?.();
    try {
      const q = customerId != null ? `?customer_id=${customerId}` : "";
      const items = await ctx.api(`/customer-orders/closeable${q}`, {}, 0);
      OrderMenus.openClose({
        title: "Close Billed Lines",
        items: items.map(it => ({
          id: it.id,
          party: it.customer_name,
          label: it.label,
          sublabel: it.sublabel,
          quantity: it.quantity,
          amount: it.amount,
        })),
        ctx,
        onSubmit: async (ids, reason) => {
          await ctx.api("/customer-orders/close-batch", { method: "POST", body: JSON.stringify({ bill_line_ids: ids, reason }) });
          ctx.invalidateCache?.("/customer-orders");
          ctx.toast(`Closed ${ids.length} line(s)`, "success");
          if (detailCustomerId) await openDetail(detailCustomerId, currentBucket);
          else loadList();
        },
      });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openOfflineWizard(presetCustomerId) {
    const cid = presetCustomerId != null ? presetCustomerId : detailCustomerId;
    offlineEditPlacementId = null;
    offlineStep = 1;
    offlineCustomerId = cid || null;
    offlineCustomerName = "";
    offlineCustomerSearch = "";
    offlineSelectedDetail = null;
    offlineLines = [];
    offlineSearchQuery = "";
    offlineSearchResults = [];
    offlineNotes = "";
    offlinePlacedOn = localToday();
    offlinePreview = null;
    offlineBusy = false;
    ctx.showLoading?.();
    try {
      offlineCustomers = await ctx.api("/customers", {}, 30000) || [];
      document.getElementById("co-offline-wizard")?.classList.remove("hidden");
      renderOfflineWizard();
      // preset customer: fetch detail for credit summary (same path as manual pick)
      if (cid) await pickOfflineCustomer(cid);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function matchOfflineCustomer(c, tokens) {
    if (!tokens.length) return true;
    return OrdersUI.partySearchRank(c, tokens) != null;
  }

  function onOfflineCustomerSearch(val) {
    offlineCustomerSearch = val || "";
    renderOfflineWizard();
    setTimeout(() => {
      const el = document.getElementById("co-offline-cust-search");
      if (!el) return;
      el.focus();
      try { el.setSelectionRange(el.value.length, el.value.length); } catch (_) {}
    }, 0);
  }

  async function pickOfflineCustomer(id) {
    if (!id) {
      offlineCustomerId = null;
      offlineCustomerName = "";
      offlineSelectedDetail = null;
      renderOfflineWizard();
      return;
    }
    const c = (offlineCustomers || []).find(x => x.id === id);
    offlineCustomerId = id;
    offlineCustomerName = c?.business_name || "";
    offlineSelectedDetail = c || null;
    renderOfflineWizard();
    // fetch full detail (has outstanding_balance + available_credit)
    try {
      offlineSelectedDetail = await ctx.api(`/customers/${id}`, {}, 0);
      renderOfflineWizard();
    } catch (_) {}
  }

  function closeOfflineWizard() {
    document.getElementById("co-offline-wizard")?.classList.add("hidden");
    offlineEditPlacementId = null;
  }

  function buildOfflineBody() {
    return {
      lines: offlineLines.filter(l => Number(l.quantity) > 0).map(l => ({
        catalog_product_id: l.catalog_product_id,
        quantity: Number(l.quantity),
      })),
      narration: (offlineNotes || "").trim() || null,
      placed_on: offlinePlacedOn || localToday(),
    };
  }

  function filterOfflineProducts() {
    const q = offlineSearchQuery.trim().toLowerCase();
    const all = offlineSearchResults || [];
    if (!q) return all.slice(0, 40);
    const scored = [];
    for (const p of all) {
      const id = String(p.our_product_id || "").toLowerCase();
      const cat = String(p.category || "").toLowerCase();
      const series = String(p.series || "").toLowerCase();
      const vendor = String(p.vendor_name || "").toLowerCase();
      let score = 0;
      if (id === q) score = 100;
      else if (id.startsWith(q)) score = 80;
      else if (id.includes(q)) score = 40;
      else if (cat.startsWith(q) || series.startsWith(q)) score = 30;
      else if (cat.includes(q) || series.includes(q) || vendor.includes(q)) score = 10;
      else continue;
      scored.push({ p, score, id });
    }
    scored.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
    return scored.map(x => x.p).slice(0, 40);
  }

  function offlineCartQty() {
    return offlineLines.reduce((s, l) => s + (Number(l.quantity) || 0), 0);
  }

  function offlineCartTotal() {
    return offlineLines.reduce((s, l) => s + (Number(l.selling_price) || 0) * (Number(l.quantity) || 0), 0);
  }

  function renderOfflineWizard() {
    const stepsEl = document.getElementById("co-offline-steps");
    const bodyEl = document.getElementById("co-offline-body");
    const footerEl = document.getElementById("co-offline-footer");
    if (!stepsEl || !bodyEl || !footerEl) return;

    const editing = !!offlineEditPlacementId;
    const labels = editing ? ["Products", "Review"] : ["Customer", "Products", "Review"];
    const stepNum = editing ? offlineStep - 1 : offlineStep;
    stepsEl.innerHTML = labels.map((lbl, i) => {
      const n = i + 1;
      const cls = n === stepNum ? "step active" : n < stepNum ? "step done" : "step";
      return `<div class="${cls}"><span class="step-num">${n < stepNum ? "✓" : n}</span><span class="step-label">${lbl}</span></div>`;
    }).join("");

    if (offlineStep === 1 && !editing) {
      const tokens = OrdersUI.partySearchTokens(offlineCustomerSearch);
      const customers = OrdersUI.filterAndRankParties(
        (offlineCustomers || []).filter(c => c.is_active !== false),
        offlineCustomerSearch,
      ).slice(0, tokens.length ? 40 : 60);
      const selected = offlineCustomerId
        ? (offlineCustomers || []).find(c => c.id === offlineCustomerId)
        : null;
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>Select customer</h4>
          <p>Search any part of name, city, or phone — e.g. <em>natraj</em> or <em>anjad</em>.</p>
        </div>
        <div class="vo-wiz-search-wrap">
          <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
          <input id="co-offline-cust-search" class="input vo-wiz-search" type="search" placeholder="Search customer, city, phone…" value="${ctx.esc(offlineCustomerSearch)}" oninput="CustomerOrders.onOfflineCustomerSearch(this.value)" autocomplete="off" />
          ${offlineCustomerSearch ? `<button type="button" class="vo-wiz-search-clear" onclick="CustomerOrders.onOfflineCustomerSearch('')">×</button>` : ""}
        </div>
        ${selected ? `<div class="vo-wiz-selected-banner">
          <div>
            <span class="vo-wiz-selected-label">Selected</span>
            ${selected.party_number ? `<span style="font-size:11px;color:var(--muted);font-weight:600;margin-right:4px;">#${selected.party_number}</span>` : ""}<strong>${ctx.esc(selected.business_name || offlineCustomerName)}</strong>${selected.marker_1 ? ` <span class="badge badge-blue" style="font-size:10px;padding:2px 4px;vertical-align:middle;">${ctx.esc(selected.marker_1)}</span>` : ""}${selected.marker_2 ? ` <span class="badge badge-amber" style="font-size:10px;padding:2px 4px;vertical-align:middle;">${ctx.esc(selected.marker_2)}</span>` : ""}${(selected.payment_type === "CASH" && !(selected.marker_1 || "").toUpperCase().includes("CASH")) ? ` <span class="badge badge-amber" style="font-size:10px;padding:2px 4px;vertical-align:middle;">CASH</span>` : ""}
            ${selected.city_name ? `<span class="vo-muted"> · ${ctx.esc(selected.city_name)}</span>` : ""}
          </div>
          <button type="button" class="btn btn-ghost btn-sm" onclick="CustomerOrders.pickOfflineCustomer(null)">Change</button>
        </div>
        ${cashWarningHtml(selected)}
        ${offlineSelectedDetail ? (() => {
          const d = offlineSelectedDetail;
          const outstanding = d.outstanding_balance;
          const avail = d.available_credit;
          const limit = d.credit_limit;
          if (outstanding == null && avail == null) return "";
          const outN = Number(outstanding || 0);
          const availN = Number(avail || 0);
          const overLimit = availN < 0;
          const bg = overLimit ? "#fef2f2" : "#f0fdf4";
          const border = overLimit ? "#fecaca" : "#bbf7d0";
          return `<div style="margin:8px 0;padding:10px 14px;border-radius:8px;background:${bg};border:1px solid ${border};display:flex;gap:16px;flex-wrap:wrap;font-size:13px;">
            <span><strong>Outstanding:</strong> ${outN < 0 ? "<span style='color:#16a34a'>Credit ₹" + Math.abs(outN).toLocaleString("en-IN", {maximumFractionDigits:2}) + "</span>" : outN > 0 ? "<span style='color:#dc2626'>₹" + outN.toLocaleString("en-IN", {maximumFractionDigits:2}) + "</span>" : "₹0"}</span>
            <span><strong>Credit Limit:</strong> ₹${Number(limit || 0).toLocaleString("en-IN", {maximumFractionDigits:2})}</span>
            <span><strong>Available:</strong> ${availN < 0 ? "<span style='color:#dc2626'>-₹" + Math.abs(availN).toLocaleString("en-IN", {maximumFractionDigits:2}) + "</span>" : "<span style='color:#16a34a'>₹" + availN.toLocaleString("en-IN", {maximumFractionDigits:2}) + "</span>"}</span>
          </div>`;
        })() : (offlineCustomerId ? `<p style="font-size:12px;color:var(--muted);margin:4px 0;">Loading credit info…</p>` : "")}` : ""}
        <div class="vo-wiz-vendor-list">
          ${customers.length ? customers.map(c => {
            const selectedCls = offlineCustomerId === c.id ? " selected" : "";
            const _cm1u = (c.marker_1 || "").toUpperCase();
            return `<button type="button" class="vo-wiz-vendor-card${selectedCls}" onclick="CustomerOrders.pickOfflineCustomer(${c.id})">
              <span class="vo-wiz-vendor-letter">${ctx.esc((c.business_name || "?").slice(0, 1).toUpperCase())}</span>
              <span class="vo-wiz-vendor-meta">
                <strong>${c.party_number ? `<span style="font-size:10px;color:var(--muted);font-weight:600;margin-right:3px;">#${c.party_number}</span>` : ""}${ctx.esc(c.business_name || "Customer")}${c.marker_1 ? ` <span class="badge badge-blue" style="font-size:9px;padding:1px 4px;vertical-align:middle;">${ctx.esc(c.marker_1)}</span>` : ""}${c.marker_2 ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;vertical-align:middle;">${ctx.esc(c.marker_2)}</span>` : ""}${(c.payment_type === "CASH" && !_cm1u.includes("CASH")) ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;vertical-align:middle;">CASH</span>` : ""}</strong>
                <span>${c.city_name ? ctx.esc(c.city_name) : "No city"}${c.phone ? ` · ${ctx.esc(c.phone)}` : ""}</span>
              </span>
              <span class="vo-wiz-vendor-check">${offlineCustomerId === c.id ? "✓" : ""}</span>
            </button>`;
          }).join("") : HubUI.emptyState({
            title: "No matches",
            sub: tokens.length ? `No customer matches “${ctx.esc(offlineCustomerSearch)}”.` : "No customers loaded.",
          })}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="CustomerOrders.closeOfflineWizard()">Cancel</button>
        <button class="btn btn-primary" ${offlineCustomerId ? "" : "disabled"} onclick="CustomerOrders.offlineNext()">Next →</button>`;
      setTimeout(() => document.getElementById("co-offline-cust-search")?.focus(), 30);
      return;
    }

    if (offlineStep === 2) {
      const shown = filterOfflineProducts();
      const selectedNotShown = offlineLines
        .map(l => offlineSearchResults.find(p => p.catalog_product_id === l.catalog_product_id))
        .filter(p => p && !shown.some(s => s.catalog_product_id === p.catalog_product_id));
      const list = [...selectedNotShown, ...shown];
      const cartHtml = offlineLines.length ? `
        <div class="vo-wiz-cart">
          <div class="vo-wiz-cart-head">
            <strong>In this order</strong>
            <span>${offlineLines.length} product${offlineLines.length === 1 ? "" : "s"} · ${offlineCartQty()} qty</span>
          </div>
          <div class="vo-wiz-cart-chips">
            ${offlineLines.map(l => `<span class="vo-wiz-cart-chip">
              <span>${ctx.esc(l.our_product_id)} × ${l.quantity}</span>
              <button type="button" title="Remove" onclick="CustomerOrders.toggleOfflineProduct(${l.catalog_product_id}, false)">×</button>
            </span>`).join("")}
          </div>
        </div>` : "";

      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head vo-wiz-step-head-row">
          <div>
            <h4 style="margin:0;">${editing ? `Edit placement #${offlineEditPlacementId}` : `Products for ${ctx.esc(offlineCustomerName)}`}</h4>
            <p style="margin:4px 0 0;font-size:13px;color:var(--muted);">${editing ? "Add, change qty, or remove products. Stock updates on save." : "Search product ID — tick rows, set qty. Enter adds exact / best match."}</p>
          </div>
          <div class="vo-wiz-count-pill">${offlineLines.length} selected</div>
        </div>
        ${cartHtml}
        <div class="vo-wiz-search-wrap">
          <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
          <input id="co-offline-search" class="input vo-wiz-search" type="search" placeholder="Search product ID, category, series…" value="${ctx.esc(offlineSearchQuery)}" oninput="CustomerOrders.onOfflineSearchInput(this.value)" onkeydown="CustomerOrders.onOfflineSearchKey(event)" autocomplete="off" />
          ${offlineSearchQuery ? `<button type="button" class="vo-wiz-search-clear" onclick="CustomerOrders.onOfflineSearchInput('')">×</button>` : ""}
        </div>
        <div class="vo-wiz-product-meta">
          <span>Showing ${list.length}${offlineSearchQuery ? " match" : " (type to search)"}${offlineSearchResults.length ? ` · ${offlineSearchResults.length} loaded` : ""}</span>
        </div>
        <div class="vo-wiz-products" id="co-offline-product-list">
          ${!offlineSearchResults.length ? HubUI.emptyState({ title: "Loading…", sub: "Loading products…" })
            : list.length ? list.map(p => {
              const line = offlineLines.find(l => l.catalog_product_id === p.catalog_product_id);
              const qty = line ? line.quantity : 1;
              const checked = !!line;
              const img = (p.image_urls && p.image_urls[0]) || "";
              return `<div class="vo-wiz-product ${checked ? "selected" : ""}" onclick="CustomerOrders.toggleOfflineProduct(${p.catalog_product_id}, ${checked ? "false" : "true"})">
                <div class="vo-wiz-product-main">
                  <input type="checkbox" ${checked ? "checked" : ""} onclick="event.stopPropagation();CustomerOrders.toggleOfflineProduct(${p.catalog_product_id}, this.checked)" />
                  ${thumb(img)}
                  <div class="vo-wiz-product-info">
                    <strong>${ctx.esc(p.our_product_id)}${p.year_group ? ` <span class="prod-year-pill">${ctx.esc(p.year_group)}</span>` : ""}</strong>
                    <span class="vo-wiz-product-sub">${p.category ? ctx.esc(p.category) : "Product"}${p.series ? ` · ${ctx.esc(p.series)}` : ""}${p.year_group ? ` · ${ctx.esc(p.year_group)}` : ""}${p.vendor_name ? ` · ${ctx.esc(p.vendor_name)}` : ""}</span>
                    <span class="vo-wiz-product-price">${fmtPrice(p.selling_price)} · Stock ${p.quantity_on_hand ?? 0}</span>
                  </div>
                </div>
                <div class="vo-wiz-qty" onclick="event.stopPropagation()">
                  <label>Qty</label>
                  <div class="vo-wiz-qty-controls">
                    <button type="button" class="vo-wiz-qty-btn" ${checked ? "" : "disabled"} onclick="CustomerOrders.bumpOfflineQty(${p.catalog_product_id}, -1)">−</button>
                    <input type="number" min="1" class="input vo-wiz-qty-input" value="${qty}" ${checked ? "" : "disabled"} onchange="CustomerOrders.setOfflineQty(${p.catalog_product_id}, this.value)" onclick="event.stopPropagation()" />
                    <button type="button" class="vo-wiz-qty-btn" ${checked ? "" : "disabled"} onclick="CustomerOrders.bumpOfflineQty(${p.catalog_product_id}, 1)">+</button>
                  </div>
                </div>
              </div>`;
            }).join("") : HubUI.emptyState({
              title: "No matches",
              sub: `No products match “${offlineSearchQuery}”.`,
              ctaHtml: `<button type="button" class="btn btn-secondary" onclick="CustomerOrders.onOfflineSearchInput('')">Clear search</button>`,
            })}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="${editing ? "CustomerOrders.closeOfflineWizard()" : "CustomerOrders.offlineBack()"}">${editing ? "Cancel" : "← Back"}</button>
        <div class="vo-wiz-footer-mid">${offlineLines.length ? `${offlineLines.length} item(s) · est. ${fmtPrice(offlineCartTotal())}` : "Select at least one product"}</div>
        <button class="btn btn-primary" ${offlineLines.length ? "" : "disabled"} onclick="CustomerOrders.offlineNext()">Review →</button>`;
      setTimeout(() => {
        const inp = document.getElementById("co-offline-search");
        if (!inp) return;
        inp.focus();
        try { const n = (offlineSearchQuery || "").length; inp.setSelectionRange(n, n); } catch (_) {}
      }, 30);
      return;
    }

    const tot = offlinePreview || {};
    const lines = tot.lines || offlineLines.map(l => ({
      our_product_id: l.our_product_id,
      quantity: l.quantity,
      unit_price: l.selling_price,
      line_total: (Number(l.selling_price) || 0) * (Number(l.quantity) || 0),
      out_of_stock: Number(l.quantity_on_hand) < Number(l.quantity),
      on_hand: l.quantity_on_hand,
    }));
    const warnings = tot.stock_warnings || lines.filter(l => l.out_of_stock).map(l => ({
      message: `${l.our_product_id}: need ${l.quantity}, have ${l.on_hand ?? 0} — will go negative`,
    }));
    const warnHtml = warnings.length
      ? `<div style="margin:0 0 14px;padding:12px 14px;background:#fffbeb;border:1px solid #fcd34d;border-radius:10px;">
          <strong style="color:#b45309;">Out of stock — order still allowed (offline)</strong>
          <ul style="margin:8px 0 0;padding-left:18px;font-size:13px;color:#92400e;">
            ${warnings.map(w => `<li>${ctx.esc(w.message || w.our_product_id)}</li>`).join("")}
          </ul>
          <p style="margin:8px 0 0;font-size:12px;color:#92400e;">Stock on hand will go negative after place. Portal customers still cannot oversell.</p>
        </div>`
      : "";
    bodyEl.innerHTML = `
      ${warnHtml}
      <div class="review-grid" style="margin-bottom:16px;">
        ${ctx.reviewRow("Customer", offlineCustomerName)}
        ${editing ? ctx.reviewRow("Placement", `#${offlineEditPlacementId}`) : ""}
        ${ctx.reviewRow("Items", String(lines.length))}
        ${ctx.reviewRow("Est. total", fmtPrice(tot.subtotal || offlineCartTotal()))}
      </div>
      ${editing ? "" : `
        <label class="label">Order date</label>
        <input type="date" class="input" style="width:100%;max-width:220px;margin-bottom:4px;" value="${ctx.esc(offlinePlacedOn || localToday())}" onchange="CustomerOrders.setOfflinePlacedOn(this.value)" />
        <p style="font-size:12px;color:var(--muted);margin:0 0 12px;">Day the call / order actually happened (backdate OK).</p>
      `}
      <label class="label">Notes (optional — shown on order)</label>
      <textarea class="input" id="co-offline-notes" rows="2" style="width:100%;margin-bottom:12px;" oninput="CustomerOrders.setOfflineNotes(this.value)">${ctx.esc(offlineNotes || "")}</textarea>
      <div class="card table-wrap">
        <table class="data"><thead><tr><th>Product</th><th>Stock</th><th>Qty</th><th>Rate</th><th>Line</th></tr></thead>
        <tbody>${lines.map(ln => `<tr>
          <td><strong>${ctx.esc(ln.our_product_id)}</strong>${ln.out_of_stock ? ` <span style="color:#b45309;font-size:11px;font-weight:700;">out of stock</span>` : ""}</td>
          <td>${ln.on_hand != null ? ln.on_hand : "—"}</td>
          <td>${ln.quantity}</td>
          <td>${fmtPrice(ln.unit_price || ln.rate_inclusive)}</td>
          <td>${fmtPrice(ln.line_total)}</td>
        </tr>`).join("")}</tbody></table>
      </div>
      <p style="margin:12px 0 0;font-size:13px;color:var(--muted);">${editing
        ? "Saves changes to this incoming order. Stock reserve adjusts automatically."
        : "Goes to <strong>To bill</strong>. Next: Bill when packed."}</p>`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="CustomerOrders.offlineBack()">← Back</button>
      <button class="btn btn-primary" ${offlineBusy ? "disabled" : ""} onclick="CustomerOrders.submitOffline()">${offlineBusy ? "Saving…" : (editing ? "Save changes" : (warnings.length ? "Place anyway" : "Place for customer"))}</button>`;
  }

  function setOfflineCustomer(id, name) {
    offlineCustomerId = id || null;
    if (!id) {
      offlineCustomerName = "";
    } else if (name && name !== "— Select customer —") {
      offlineCustomerName = name.split(" · ")[0];
    } else {
      const c = (offlineCustomers || []).find(x => x.id === id);
      offlineCustomerName = c?.business_name || offlineCustomerName;
    }
    renderOfflineWizard();
  }

  function setOfflineNotes(v) { offlineNotes = v || ""; }
  function setOfflinePlacedOn(v) { offlinePlacedOn = v || localToday(); }

  function onOfflineSearchInput(val) {
    const prev = document.getElementById("co-offline-search");
    const start = prev?.selectionStart;
    offlineSearchQuery = val || "";
    renderOfflineWizard();
    const inp = document.getElementById("co-offline-search");
    if (inp && typeof start === "number") {
      try { inp.setSelectionRange(start, start); } catch (_) {}
    }
  }

  function onOfflineSearchKey(e) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const q = offlineSearchQuery.trim().toLowerCase();
    if (!q) return;
    const exact = offlineSearchResults.find(p => String(p.our_product_id || "").toLowerCase() === q);
    const best = exact || filterOfflineProducts()[0];
    if (!best) return ctx.toast("No product match", "error");
    toggleOfflineProduct(best.catalog_product_id, true);
    offlineSearchQuery = "";
    renderOfflineWizard();
  }

  async function ensureOfflineProductsLoaded() {
    if (offlineSearchResults.length) return;
    try {
      offlineSearchResults = await ctx.api("/stock/products?lite=1", {}, 120000) || [];
    } catch (e) {
      offlineSearchResults = [];
      ctx.toast(e.message, "error");
    }
  }

  function toggleOfflineProduct(catalogProductId, checked) {
    const p = offlineSearchResults.find(x => x.catalog_product_id === catalogProductId);
    if (!p) return;
    if (checked) {
      if (!offlineLines.find(l => l.catalog_product_id === catalogProductId)) {
        offlineLines.push({
          catalog_product_id: p.catalog_product_id,
          our_product_id: p.our_product_id,
          quantity: 1,
          min_qty: 0,
          selling_price: p.selling_price,
          quantity_on_hand: p.quantity_on_hand,
        });
      }
    } else {
      const existing = offlineLines.find(l => l.catalog_product_id === catalogProductId);
      if (existing && Number(existing.min_qty) > 0) {
        existing.quantity = Number(existing.min_qty);
        return ctx.toast(`Keep billed qty (${existing.min_qty}) — cannot remove billed product`, "error");
      }
      offlineLines = offlineLines.filter(l => l.catalog_product_id !== catalogProductId);
    }
    renderOfflineWizard();
  }

  function addOfflineProduct(catalogProductId) {
    toggleOfflineProduct(catalogProductId, true);
  }

  function removeOfflineLine(catalogProductId) {
    toggleOfflineProduct(catalogProductId, false);
  }

  function setOfflineQty(cid, raw) {
    const line = offlineLines.find(l => l.catalog_product_id === cid);
    const minQ = line ? (Number(line.min_qty) || 0) : 0;
    const qty = Math.max(minQ || 1, parseInt(String(raw || "1"), 10) || 1);
    if (line) line.quantity = qty;
    else {
      const p = offlineSearchResults.find(x => x.catalog_product_id === cid);
      if (p) offlineLines.push({
        catalog_product_id: p.catalog_product_id,
        our_product_id: p.our_product_id,
        quantity: qty,
        min_qty: 0,
        selling_price: p.selling_price,
        quantity_on_hand: p.quantity_on_hand,
      });
    }
    const mid = document.querySelector("#co-offline-footer .vo-wiz-footer-mid");
    if (mid && offlineLines.length) mid.textContent = `${offlineLines.length} item(s) · est. ${fmtPrice(offlineCartTotal())}`;
  }

  function bumpOfflineQty(cid, delta) {
    const line = offlineLines.find(l => l.catalog_product_id === cid);
    if (!line) {
      if (delta > 0) toggleOfflineProduct(cid, true);
      return;
    }
    const minQ = Number(line.min_qty) || 0;
    line.quantity = Math.max(minQ || 1, (Number(line.quantity) || 1) + delta);
    renderOfflineWizard();
  }

  async function offlineNext() {
    if (offlineStep === 1) {
      if (!offlineCustomerId) return ctx.toast("Select a customer", "error");
      offlineStep = 2;
      renderOfflineWizard();
      await ensureOfflineProductsLoaded();
      renderOfflineWizard();
      return;
    }
    if (offlineStep === 2) {
      if (!offlineLines.length) return ctx.toast("Add at least one product", "error");
      ctx.showLoading?.();
      try {
        offlinePreview = await ctx.api(`/customer-orders/customer/${offlineCustomerId}/offline/preview`, {
          method: "POST",
          body: JSON.stringify(buildOfflineBody()),
        });
        offlineStep = 3;
        renderOfflineWizard();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    }
  }

  function offlineBack() {
    if (offlineEditPlacementId) {
      if (offlineStep > 2) { offlineStep -= 1; renderOfflineWizard(); }
      return;
    }
    if (offlineStep > 1) { offlineStep -= 1; renderOfflineWizard(); }
  }

  async function submitOffline() {
    if (offlineBusy || !offlineCustomerId) return;
    const notesEl = document.getElementById("co-offline-notes");
    if (notesEl) offlineNotes = notesEl.value || "";
    offlineBusy = true;
    renderOfflineWizard();
    ctx.showLoading?.();
    try {
      const body = buildOfflineBody();
      if (offlineEditPlacementId) {
        const pid = offlineEditPlacementId;
        const cid = offlineCustomerId;
        await ctx.api(`/customer-orders/placements/${pid}`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/stock");
        closeOfflineWizard();
        ctx.toast("Order updated", "success");
        await openDetail(cid, "received");
        loadList();
        return;
      }
      const res = await ctx.api(`/customer-orders/customer/${offlineCustomerId}/offline`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/stock");
      closeOfflineWizard();
      const cid = offlineCustomerId;
      ctx.openDetail?.(`Order #${res.placement_id}`, `
        <div class="doc-success-banner">
          <strong>Placed for customer</strong>
          <span>Same as portal · stock reserved</span>
        </div>
        <p style="margin:12px 0;font-size:14px;color:var(--muted);">Order in <strong>To bill</strong>. Bill now, or view order.</p>`,
        `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail();CustomerOrders.processFromHub(${cid}, 'open')">Bill now</button>
         <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail();CustomerOrders.openDetail(${cid}, 'received')">View order</button>`, "sm");
      ctx.toast("Order placed for customer", "success");
      hubMode = "needs_action";
      currentBucket = "open";
      syncHubChrome();
      loadList();
    } catch (e) { ctx.toast(e.message || "Could not place order", "error"); }
    finally {
      offlineBusy = false;
      ctx.hideLoading?.();
      // Re-draw so Save button unlocks after error (was stuck on “Saving…”)
      if (!document.getElementById("co-offline-wizard")?.classList.contains("hidden")) {
        renderOfflineWizard();
      }
    }
  }

  function _detailCustomerId() { return detailCustomerId; }

  function openCustomer(customerId, bucket) {
    return openDetail(customerId, bucket || "open");
  }

  return {
    init, loadList, setBucket, setHubMode, setQueueFilter, setHubSearch, showHub, openDetail, openCustomer, switchBucket, toggleDetailExpand,
    openSlidePanel, closeSlidePanel, toggleCardMore, closeAllCardMore,
    goToDispatch, goCollectPayment, setDispatchStatus, setDispatchAgent, pickParcel, reassignParcel, submitParcelReassign,
    showCreateMenu, showCreateMenuFromCustomer, runHubAction, runDetailAction, openCloseBatch,
    processOrder, processFromHub, closeProcessWizard, renderProcessWizard,
    openEditBill, editLatestBill, promptEditBillNumber, saveBillNumber, enableDiscount, clearDiscount, setBillEditSearch, addBillEditProduct, removeProcessLine,
    openEditFromOpen,
    _detailCustomerId,
    setShipQty, setLineDisc, setLineNetRate, setDiscMode, setDiscToggle, setOverallDisc,
    setFreightAgent, setFreightCharges, setTransportMode, setTransportReceipt, setPackagingCharges,
    setGst, setGstRate, setBillSeries, setNarration, setEditBillNumber, setBillDate, setAddCharge, addChargeRow,
    setOfflinePlacedOn,
    setForceCredit,
    processNext, processBack, submitProcess,
    confirmOrder, _doConfirm, cancelOpenLine, cancelPlacement, cancelCustomerOpen, cancelAllOpen, editOpenLine, editReceivedLine, deleteReceivedLine, openEditPlacement, closeBillLine, cancelBill, openBillDoc, shareBillWhatsApp,
    openOfflineWizard, closeOfflineWizard, renderOfflineWizard,
    setOfflineCustomer, pickOfflineCustomer, onOfflineCustomerSearch, setOfflineNotes,
    onOfflineSearchInput, onOfflineSearchKey, toggleOfflineProduct, addOfflineProduct, removeOfflineLine,
    setOfflineQty, bumpOfflineQty, offlineNext, offlineBack, submitOffline,
  };
})();
