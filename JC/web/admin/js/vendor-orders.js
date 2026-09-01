/** Vendor orders — Today/Past date scope + same stage chips */
const VendorOrders = (() => {
  let ctx = {};
  let orders = [];
  let currentOrder = null;
  let openOrder = null;
  let closedLines = [];
  let currentBucket = "placed"; // same stages for Today + Past
  let hubMode = "queue"; // queue (Today) | past — date scope only
  let hubSearch = "";
  let showSummary = false;
  let orderSummary = null;
  let summaryDrill = null;
  let detailVendorId = null;
  let expandedProductId = null;
  let expandedPlacementId = null;
  let expandedClosedId = null;
  let hubExpandedVendorId = null;
  let hubExpandedPlacementId = null;
  let hubExpandCache = {};
  let wizardStep = 1;
  let wizardVendorId = null;
  let wizardProducts = [];
  let wizardLines = [];
  let wizardProductSearch = "";
  let wizardVendorSearch = "";
  let wizardVendorsCache = [];
  let wizardPlacedOn = "";
  let editingOpenLine = null;
  let vendorProductsCache = [];

  function localToday() {
    const n = new Date();
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
  }

  const STEP_LABELS = ["Vendor", "Products", "Review"];
  const PLACEMENT_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16"];
  const PAST_BUCKETS = ["placed", "received", "billed", "cancelled", "closed"];
  const BROWSE_BUCKETS = PAST_BUCKETS; // legacy alias
  const BUCKET_LABELS = {
    needs_action: "Today",
    queue: "Today",
    open: "To receive",
    placed: "To receive",
    received: "To bill",
    billed: "Billed",
    cancelled: "Cancelled",
    closed: "Closed",
  };

  function isTodayMode() {
    return hubMode === "queue" || hubMode === "needs_action" || hubMode === "today";
  }

  function dayParam() {
    return isTodayMode() ? "today" : "all";
  }

  function isQueueMode() {
    return isTodayMode();
  }

  function openKindOf(o) {
    return o.open_kind || (o.status === "to_bill" ? "to_bill" : "to_receive");
  }

  function init(context) { ctx = context; }

  function syncBucketButtons(bucket, barId) {
    OrdersUI.syncStageChips(`#${barId}`, bucket);
  }

  function updateBucketTabs(active, prefix = "vo-bucket") {
    syncBucketButtons(active, prefix === "vo-detail-bucket" ? "vo-detail-buckets" : "vo-hub-buckets");
  }

  function syncHubChrome() {
    const chips = document.getElementById("vo-hub-buckets");
    const actionHost = document.getElementById("vo-action-chips");
    const today = isTodayMode();
    chips?.classList.remove("hidden");
    OrdersUI.syncModeButtons("#vo-hub-mode", today ? "queue" : "past");
    OrdersUI.syncStageChips("#vo-hub-buckets", currentBucket);
    if (actionHost) {
      actionHost.innerHTML = "";
      actionHost.classList.add("hidden");
    }
    const title = document.getElementById("orders-list-title");
    if (title) {
      const stage = BUCKET_LABELS[currentBucket] || "Orders";
      title.textContent = today ? `Today · ${stage}` : stage;
    }
    const searchSlot = document.getElementById("vo-hub-search-slot");
    if (searchSlot) {
      searchSlot.innerHTML = HubUI.searchBar({
        id: "vo-hub-search",
        value: hubSearch,
        placeholder: "Search vendor…",
        oninput: "VendorOrders.setHubSearch(this.value)",
      });
    }
  }

  function updateDetailPrimary() {
    const btn = document.getElementById("vo-detail-primary-btn");
    if (!btn) return;
    const can = !!ctx.canWrite?.("vendor_orders");
    let label = "";
    let onclick = "";
    if (currentBucket === "placed" || currentBucket === "open") {
      label = "Receive";
      onclick = "VendorOrders.receiveOrder()";
    } else if (currentBucket === "received") {
      label = "Bill";
      onclick = "VendorOrders.billOrder()";
    } else if (currentBucket === "billed") {
      label = "Close";
      onclick = "VendorOrders.openCloseBatch(VendorOrders._detailVendorId())";
    }
    const show = can && !!label;
    btn.classList.toggle("hidden", !show);
    if (show) {
      btn.textContent = label;
      btn.setAttribute("onclick", onclick);
    }
  }

  function updateActionButtons(view) {
    if (view === "detail") updateDetailPrimary();
  }

  function setHubMode(mode) {
    if (mode === "browse" || mode === "past") hubMode = "past";
    else hubMode = "queue";
    if (!PAST_BUCKETS.includes(currentBucket)) currentBucket = "placed";
    hubExpandedVendorId = null;
    hubExpandedPlacementId = null;
    hubExpandCache = {};
    hubSearch = "";
    syncHubChrome();
    loadList();
  }

  function setQueueFilter() {
    /* removed — Today/Past share stage chips */
  }

  function setHubSearch(val) {
    hubSearch = val || "";
    hubExpandedVendorId = null;
    renderList();
  }

  function filterHubOrders(list) {
    return OrdersUI.filterAndRankParties(
      (list || []).map(o => ({
        ...o,
        business_name: o.vendor_name || String(o.vendor_label || "").split("—")[0].trim() || o.vendor_label || "",
        city_name: o.city_name || (String(o.vendor_label || "").includes("—")
          ? String(o.vendor_label).split("—").slice(1).join("—").trim()
          : ""),
        alias: o.alias || "",
      })),
      hubSearch,
    );
  }

  function vendorLabel(v) {
    if (!v) return "—";
    const name = v.business_name || v.alias || `Vendor #${v.id}`;
    const city = v.city_name || v.vendor_city;
    return city ? `${name} — ${city}` : name;
  }

  function aliasUnderTitle(o) {
    const alias = String(o?.alias || "").trim();
    return alias ? ctx.esc(alias) : "";
  }

  function hubCardMeta(o, restHtml) {
    const alias = aliasUnderTitle(o);
    return alias ? `${alias} · ${restHtml}` : restHtml;
  }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function fmtAmtOrDash(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n) || n === 0) return "—";
    return fmtPrice(n);
  }

  function thumb(url, cls = "vo-thumb") {
    if (url) return `<img src="${ctx.esc(url)}" alt="" class="${cls}" />`;
    return `<div class="${cls} vo-thumb-empty">—</div>`;
  }

  function placementBadge(idx) {
    const color = PLACEMENT_COLORS[idx % PLACEMENT_COLORS.length];
    return `<span class="vo-placement-badge" style="background:${color};">#${idx + 1}</span>`;
  }

  function stockBadge(status) {
    const map = { in_stock: ["In stock", "badge-green"], low_stock: ["Low stock", "badge-yellow"], out_of_stock: ["Out of stock", "badge-red"] };
    const [lbl, cls] = map[status] || [status, "badge-gray"];
    return `<span class="badge ${cls}">${lbl}</span>`;
  }

  function confirmDetailsTable(rows) {
    return `<table class="data" style="font-size:13px;margin:0;"><tbody>
      ${rows.map(([k, v]) => `<tr><td style="color:var(--muted);width:40%;">${ctx.esc(k)}</td><td><strong>${v}</strong></td></tr>`).join("")}
    </tbody></table>`;
  }

  function openConfirmAction({ title, message, rows, confirmLabel, danger, onConfirm, requireReason, reasonLabel }) {
    OrderMenus.openConfirm({
      title,
      message,
      detailsHtml: confirmDetailsTable(rows),
      confirmLabel,
      danger,
      onConfirm,
      requireReason,
      reasonLabel,
      ctx,
    });
  }

  function reasonBody(reason) {
    return JSON.stringify({ reason: (reason || "").trim() });
  }

  function noteChip(text, kind) {
    if (!text) return "";
    const cls = kind === "cancel" ? "vo-note vo-note-cancel" : "vo-note vo-note-close";
    return `<div class="${cls}"><span>${kind === "cancel" ? "Cancel note" : "Close note"}</span>${ctx.esc(text)}</div>`;
  }

  function setBucket(bucket) {
    // Stage only — do not flip Today/Past
    currentBucket = PAST_BUCKETS.includes(bucket) ? bucket : "placed";
    showSummary = false;
    hubExpandedVendorId = null;
    hubExpandedPlacementId = null;
    hubExpandCache = {};
    hubSearch = "";
    syncHubChrome();
    loadList();
  }

  async function loadList() {
    ctx.showLoading?.();
    try {
      if (!PAST_BUCKETS.includes(currentBucket)) currentBucket = "placed";
      const day = dayParam();
      orders = await ctx.api(`/vendor-orders?bucket=${currentBucket}&day=${day}`, {}, 0);
      if (!Array.isArray(orders)) orders = [];
      syncHubChrome();
      renderList();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function showHub() {
    document.getElementById("orders-hub")?.classList.remove("hidden");
    document.getElementById("orders-detail")?.classList.add("hidden");
    currentOrder = null;
    openOrder = null;
    closedLines = [];
    detailVendorId = null;
    expandedProductId = null;
    expandedPlacementId = null;
    expandedClosedId = null;
    hubExpandedVendorId = null;
    hubExpandedPlacementId = null;
    hubExpandCache = {};
    orderSummary = null;
    if (!PAST_BUCKETS.includes(currentBucket)) currentBucket = "placed";
    syncHubChrome();
    loadList();
    App.updateGlobalBack?.();
  }

  function filterQueueList(list) {
    return list;
  }

  function renderList() {
    const el = document.getElementById("orders-list");
    if (!el) return;
    const canWrite = !!ctx.canWrite?.("vendor_orders");
    const list = filterQueueList(filterHubOrders(orders));
    const stage = BUCKET_LABELS[currentBucket] || "orders";
    const today = isTodayMode();

    if (!list.length) {
      el.innerHTML = OrdersUI.emptyState({
        title: today ? `No ${stage} today` : `No ${stage}`,
        sub: today
          ? "Switch to Past for older dates. Same stages there."
          : "Try another stage, or create an order.",
        ctaHtml: canWrite
          ? `<button class="btn btn-primary" onclick="VendorOrders.showCreateMenu()">+ New vendor order</button>`
          : "",
      });
      return;
    }

    if (currentBucket === "placed") {
      el.innerHTML = `<div class="ord-hub-list">${list.map(o => renderPlacedHubCard(o, canWrite)).join("")}</div>`;
      return;
    }
    if (currentBucket === "received") {
      el.innerHTML = `<div class="ord-hub-list">${list.map(o => renderReceivedHubCard(o, canWrite)).join("")}</div>`;
      return;
    }
    if (currentBucket === "billed") {
      el.innerHTML = `<div class="ord-hub-list">${list.map(o => renderBilledHubCard(o, canWrite)).join("")}</div>`;
      return;
    }
    if (currentBucket === "cancelled") {
      el.innerHTML = `<div class="ord-hub-list">${list.map(o => renderNoteHubCard(o, "cancelled", canWrite)).join("")}</div>`;
      return;
    }
    if (currentBucket === "closed") {
      el.innerHTML = `<div class="ord-hub-list">${list.map(o => renderNoteHubCard(o, "closed", canWrite)).join("")}</div>`;
      return;
    }
    el.innerHTML = OrdersUI.emptyState({ title: "Unknown stage", sub: "Pick a stage above." });
  }

  function hubChevron(open) {
    return `<span class="vo-chevron ${open ? "is-open" : ""}" aria-hidden="true"></span>`;
  }

  function renderOpenHubCard(o, canWrite) {
    const kind = openKindOf(o);
    const isBill = kind === "to_bill";
    const expandKey = isBill ? `open-bill-${o.vendor_id}` : `open-${o.vendor_id}`;
    const open = hubExpandedVendorId === `${kind}-${o.vendor_id}`;
    const cache = hubExpandCache[expandKey];
    const primaryOnclick = isBill ? `VendorOrders.billVendor(${o.vendor_id})` : `VendorOrders.receiveVendor(${o.vendor_id})`;
    const more = [
      { label: open ? "Hide lines" : "Show lines", onclick: `VendorOrders.toggleHubVendor(${o.vendor_id}, '${isBill ? "open-bill" : "open"}', ${o.id || 0})` },
      { label: "Open vendor", onclick: `VendorOrders.openDetail(${o.id || 0}, '${isBill ? "received" : "placed"}', ${o.vendor_id})` },
    ];
    if (!isBill && canWrite) {
      more.push({ label: "Cancel Order", onclick: `VendorOrders.cancelVendorOpen(${o.vendor_id})`, danger: true });
    }
    const meta = isBill
      ? `${o.line_count} shipment${o.line_count === 1 ? "" : "s"} pending · <strong>${o.total_quantity}</strong> qty to bill`
      : `${o.line_count} products · <strong>${o.total_quantity}</strong> to receive`;
    return OrdersUI.partyCard({
      title: o.vendor_label,
      meta: hubCardMeta(o, meta),
      pillHtml: OrdersUI.pill(isBill ? "To bill" : "To receive", isBill ? "info" : "warn"),
      primaryLabel: isBill ? "Bill vendor" : "Receive goods",
      primaryOnclick,
      moreItems: more,
      open,
      // One click: row runs the next action; lines via More → Show lines
      rowOnclick: canWrite ? primaryOnclick : `VendorOrders.openDetail(${o.id || 0}, '${isBill ? "received" : "placed"}', ${o.vendor_id})`,
      canWrite,
      expandHtml: open
        ? `<div id="vo-hub-expand-${kind}-${o.vendor_id}">${cache ? (isBill ? renderOpenBillExpand(cache, canWrite) : renderOpenExpand(cache, canWrite)) : `<p class="vo-muted" style="margin:0;padding:8px 0;">Loading…</p>`}</div>`
        : "",
    });
  }

  function renderOpenExpand(detail, canWrite) {
    const lines = detail.lines || [];
    if (!lines.length) return `<p class="vo-muted" style="margin:0;">Nothing pending.</p>`;
    return `<table class="data vo-hub-table"><thead><tr>
      <th></th><th>Product</th><th>Qty</th><th>Price</th>
    </tr></thead><tbody>
      ${lines.map(l => {
        const img = (l.image_urls && l.image_urls[0]) || "";
        return `<tr>
          <td>${thumb(img, "vo-thumb-sm")}</td>
          <td><strong>${ctx.esc(ctx.productIdLabel(l))}</strong></td>
          <td><strong>${l.quantity}</strong></td>
          <td>${fmtPrice(l.buying_price)}</td>
        </tr>`;
      }).join("")}
    </tbody></table>
    ${canWrite ? `<div class="vo-hub-expand-actions">
      <button class="btn btn-primary" onclick="VendorOrders.receiveVendor(${detail.vendor_id})">Receive Order</button>
      <button class="btn btn-danger" onclick="VendorOrders.cancelVendorOpen(${detail.vendor_id})">Cancel Order</button>
    </div>` : ""}`;
  }

  function renderOpenBillExpand(detail, canWrite) {
    const receipts = detail.receipts || [];
    if (!receipts.length) return `<p class="vo-muted" style="margin:0;">Nothing to bill.</p>`;
    return `<table class="data vo-hub-table"><thead><tr>
      <th>Receipt</th><th>Received</th><th>Lines</th><th>Qty</th><th>Expected amount</th>
    </tr></thead><tbody>
      ${receipts.map(r => `<tr>
        <td><strong>${ctx.esc(r.order_receipt_number || `#${r.receipt_id}`)}</strong></td>
        <td class="vo-muted">${r.received_at ? new Date(r.received_at).toLocaleDateString() : "—"}</td>
        <td>${r.line_count}</td>
        <td><strong>${r.total_quantity}</strong></td>
        <td>${r.expected_bill_amount != null ? fmtPrice(r.expected_bill_amount) : "—"}${r.expected_extra_cash ? ` <span class="vo-muted">+ ${fmtPrice(r.expected_extra_cash)}</span>` : ""}</td>
      </tr>`).join("")}
    </tbody></table>
    ${canWrite ? `<div class="vo-hub-expand-actions">
      <button class="btn btn-primary" onclick="VendorOrders.billVendor(${detail.vendor_id})">Bill Order</button>
    </div>` : ""}`;
  }

  function renderPlacedHubCard(o, canWrite) {
    const open = hubExpandedVendorId === o.vendor_id;
    const cache = hubExpandCache[`placed-${o.vendor_id}`];
    return OrdersUI.partyCard({
      title: o.vendor_label,
      meta: hubCardMeta(o, `${o.placement_count} placements · ${o.line_count} lines · <strong>${o.total_quantity}</strong> placed`),
      pillHtml: OrdersUI.pill("Placed", "muted"),
      primaryLabel: "Receive",
      primaryOnclick: `VendorOrders.receiveVendor(${o.vendor_id})`,
      moreItems: [
        { label: "View vendor", onclick: `VendorOrders.openDetail(${o.id || 0}, 'placed', ${o.vendor_id})` },
      ],
      open,
      rowOnclick: `VendorOrders.toggleHubVendor(${o.vendor_id}, 'placed', ${o.id})`,
      canWrite,
      expandHtml: open
        ? `<div id="vo-hub-expand-${o.vendor_id}">${cache ? renderPlacedExpand(cache, canWrite) : `<p class="vo-muted" style="margin:0;padding:8px 0;">Loading…</p>`}</div>`
        : "",
    });
  }

  function renderReceivedHubCard(o, canWrite) {
    const open = hubExpandedVendorId === o.vendor_id;
    const cache = hubExpandCache[`received-${o.vendor_id}`];
    return OrdersUI.partyCard({
      title: o.vendor_label,
      meta: hubCardMeta(o, `${o.placement_count} receives · ${o.line_count} lines · <strong>${o.total_quantity}</strong> received`),
      pillHtml: OrdersUI.pill("Unbilled", "info"),
      primaryLabel: "Bill",
      primaryOnclick: `VendorOrders.billVendor(${o.vendor_id})`,
      moreItems: [
        { label: "View vendor", onclick: `VendorOrders.openDetail(${o.id || 0}, 'received', ${o.vendor_id})` },
      ],
      open,
      rowOnclick: `VendorOrders.toggleHubVendor(${o.vendor_id}, 'received', ${o.id})`,
      canWrite,
      expandHtml: open
        ? `<div id="vo-hub-expand-${o.vendor_id}">${cache ? renderReceivedExpand(cache, canWrite) : `<p class="vo-muted" style="margin:0;padding:8px 0;">Loading…</p>`}</div>`
        : "",
    });
  }

  function renderReceivedExpand(order, canWrite) {
    const placements = (order.placements || []).slice().sort((a, b) => new Date(b.placed_at) - new Date(a.placed_at));
    if (!placements.length) return `<p class="vo-muted" style="margin:0;">No receives yet.</p>`;
    return placements.map(p => {
      const lines = (order.aggregated_lines || [])
        .flatMap(al => (al.breakdown || []).filter(b => b.placement_id === p.id).map(b => ({ ...b, our_product_id: al.our_product_id })));
      const plines = lines.length ? lines : [];
      return `<div class="vo-nested-card" style="margin-bottom:10px;">
        <div class="vo-hub-main" style="justify-content:space-between;width:100%;">
          <div>
            <div class="vo-hub-title" style="font-size:14px;">${p.order_receipt_number ? `Receipt ${ctx.esc(p.order_receipt_number)}` : "Receive"} · ${new Date(p.placed_at).toLocaleString()}</div>
            <div class="vo-hub-meta">${p.line_count} lines · ${p.total_quantity || "—"} qty${p.notes ? ` · ${ctx.esc(p.notes)}` : ""}</div>
          </div>
          ${canWrite && p.receipt_id ? `<div class="vo-hub-actions" onclick="event.stopPropagation()">
            <button class="btn btn-secondary btn-sm" onclick="Stock.openEditReceipt(${p.receipt_id})">Edit</button>
          </div>` : ""}
        </div>
        ${plines.length ? `<table class="data vo-hub-table"><thead><tr><th>Product</th><th>Qty</th><th>Unbilled</th></tr></thead><tbody>
          ${plines.map(l => `<tr><td>${ctx.esc(ctx.productIdLabel(l))}</td><td>${l.quantity}</td><td>${l.quantity_remaining != null ? l.quantity_remaining : "—"}</td></tr>`).join("")}
        </tbody></table>` : ""}
        ${p.bill_file_url ? `<p style="margin:8px 0 0;"><a class="btn btn-secondary btn-sm" href="${ctx.esc(p.bill_file_url)}" target="_blank" rel="noopener">View receipt file</a></p>` : ""}
      </div>`;
    }).join("") + (canWrite ? `<div class="vo-hub-expand-actions">
      <button class="btn btn-primary" onclick="VendorOrders.billVendor(${order.vendor_id})">Bill Order</button>
    </div>` : "");
  }

  function renderPlacedExpand(order, canWrite) {
    const placements = (order.placements || []).slice().sort((a, b) => new Date(b.placed_at) - new Date(a.placed_at));
    if (!placements.length) return `<p class="vo-muted" style="margin:0;">No placements.</p>`;
    return `<div class="vo-nested-list">${placements.map(p => {
      const pOpen = hubExpandedPlacementId === p.id;
      const cancelled = !!p.cancel_reason || p.status === "cancelled";
      return `<div class="vo-nested-card ${pOpen ? "is-open" : ""} ${cancelled ? "is-cancelled" : ""}">
        <div class="vo-nested-row" onclick="event.stopPropagation();VendorOrders.toggleHubPlacement(${p.id}, ${order.id})">
          <div class="vo-hub-main">
            ${hubChevron(pOpen)}
            ${placementBadge(p.color_index)}
            <div>
              <div class="vo-hub-title" style="font-size:14px;">Placement · ${new Date(p.placed_at).toLocaleString()}</div>
              <div class="vo-hub-meta">${p.line_count} lines · ${p.total_quantity || "—"} qty${cancelled ? " · cancelled" : ""}</div>
              ${cancelled ? noteChip(p.cancel_reason, "cancel") : ""}
            </div>
          </div>
          <div class="vo-hub-actions" onclick="event.stopPropagation()">
            <button class="btn btn-secondary btn-sm" onclick="VendorOrders.openPlacementDoc(${p.id})">Order PDF</button>
            ${canWrite && !cancelled ? `<button class="btn btn-danger btn-sm" onclick="VendorOrders.cancelPlacement(${p.id})">Cancel Order</button>` : ""}
          </div>
        </div>
        ${pOpen ? `<div class="vo-nested-expand">${renderPlacementLines(order, p.id, canWrite && !cancelled)}</div>` : ""}
      </div>`;
    }).join("")}</div>`;
  }

  function renderPlacementLines(order, placementId, canEdit = false) {
    const lines = [];
    for (const agg of order.aggregated_lines || []) {
      for (const b of agg.breakdown || []) {
        if (b.placement_id === placementId) {
          lines.push({ ...b, our_product_id: agg.our_product_id, image_urls: agg.image_urls, buying_price: agg.buying_price });
        }
      }
    }
    if (!lines.length) return `<p class="vo-muted" style="margin:0;">No lines.</p>`;
    return `<table class="data vo-hub-table"><thead><tr><th></th><th>Product</th><th>Qty</th><th>Price</th>${canEdit ? "<th></th>" : ""}</tr></thead><tbody>
      ${lines.map(l => `<tr>
        <td>${thumb((l.image_urls && l.image_urls[0]) || "", "vo-thumb-sm")}</td>
        <td><strong>${ctx.esc(ctx.productIdLabel(l))}</strong></td>
        <td><strong>${l.quantity}</strong></td>
        <td>${fmtPrice(l.buying_price)}</td>
        ${canEdit ? `<td style="white-space:nowrap;">
          <button class="btn btn-ghost btn-sm" onclick="VendorOrders.editPlacedLine(${l.line_id}, ${l.quantity}, ${order.id})">Edit qty</button>
          <button class="btn btn-ghost btn-sm" style="color:var(--danger);" onclick="VendorOrders.deletePlacedLine(${l.line_id}, ${order.id})">Remove</button>
        </td>` : ""}
      </tr>`).join("")}
    </tbody></table>`;
  }

  function renderBilledHubCard(o, canWrite) {
    const open = hubExpandedVendorId === o.vendor_id;
    const cache = hubExpandCache[`billed-${o.vendor_id}`];
    return OrdersUI.partyCard({
      title: o.vendor_label,
      meta: hubCardMeta(o, `${o.placement_count} bills · ${o.line_count} products · <strong>${o.total_quantity}</strong> qty`),
      pillHtml: OrdersUI.pill("Billed", "ok"),
      primaryLabel: "Close",
      primaryOnclick: `VendorOrders.openCloseBatch(${o.vendor_id})`,
      moreItems: [
        { label: "View vendor", onclick: `VendorOrders.openDetail(${o.id || 0}, 'billed', ${o.vendor_id})` },
      ],
      open,
      rowOnclick: `VendorOrders.toggleHubVendor(${o.vendor_id}, 'billed', ${o.id})`,
      canWrite,
      expandHtml: open
        ? `<div id="vo-hub-expand-${o.vendor_id}">${cache ? renderBilledExpand(cache, canWrite) : `<p class="vo-muted" style="margin:0;padding:8px 0;">Loading…</p>`}</div>`
        : "",
    });
  }

  function renderBilledExpand(order, canWrite) {
    const placements = (order.placements || []).slice().sort((a, b) => new Date(b.placed_at) - new Date(a.placed_at));
    if (!placements.length) return `<p class="vo-muted" style="margin:0;">No billed shipments yet.</p>`;
    return `<div class="vo-nested-list">${placements.map(p => {
      const pOpen = hubExpandedPlacementId === p.id;
      const closed = !!p.closed_at;
      return `<div class="vo-nested-card ${pOpen ? "is-open" : ""} ${closed ? "is-closed" : ""}">
        <div class="vo-nested-row" onclick="event.stopPropagation();VendorOrders.toggleHubPlacement(${p.id}, ${order.id})">
          <div class="vo-hub-main">
            ${hubChevron(pOpen)}
            <div>
              <div class="vo-hub-title" style="font-size:14px;">${ctx.esc(p.bill_number || `Bill #${p.id}`)}${closed ? ` <span class="vo-pill-muted">Closed</span>` : ""}</div>
              <div class="vo-hub-meta">${p.line_count} lines · ${new Date(p.placed_at).toLocaleString()}
                ${p.net_payable != null ? ` · Net ${fmtPrice(p.net_payable)}` : ""}</div>
              ${closed && p.close_reason ? noteChip(p.close_reason, "close") : ""}
            </div>
          </div>
          ${canWrite && !closed ? `<div class="vo-hub-actions" onclick="event.stopPropagation()">
            <button class="btn btn-secondary btn-sm" onclick="VendorOrders.closeBilledPlacement(${p.id})">Close</button>
          </div>` : ""}
        </div>
        ${pOpen ? `<div class="vo-nested-expand" id="vo-hub-bill-${p.id}">${renderBilledPlacementBody(order, p)}</div>` : ""}
      </div>`;
    }).join("")}</div>`;
  }

  function renderBilledPlacementBody(order, p) {
    const lines = [];
    for (const agg of order.aggregated_lines || []) {
      for (const b of agg.breakdown || []) {
        if (b.placement_id === p.id) {
          lines.push({ ...b, our_product_id: agg.our_product_id, image_urls: agg.image_urls });
        }
      }
    }
    const showAmt = lines.some(l => l.billed_amount != null && Number(l.billed_amount) !== 0);
    let html = `<table class="data vo-hub-table"><thead><tr><th></th><th>Product</th><th>Recv</th><th>Billed qty</th>${showAmt ? "<th>Amount</th>" : ""}</tr></thead><tbody>
      ${lines.map(l => `<tr>
        <td>${thumb((l.image_urls && l.image_urls[0]) || "", "vo-thumb-sm")}</td>
        <td><strong>${ctx.esc(ctx.productIdLabel(l))}</strong></td>
        <td>${l.quantity}</td>
        <td>${l.quantity_billed ?? "—"}</td>
        ${showAmt ? `<td>${fmtAmtOrDash(l.billed_amount)}</td>` : ""}
      </tr>`).join("")}
    </tbody></table>
    <div class="vo-money-block">
      ${p.bill_amount != null ? `<div><span>Bill amount</span><strong>${fmtPrice(p.bill_amount)}</strong></div>` : ""}
      ${p.debit_note_total != null && Number(p.debit_note_total) ? `<div><span>Debit notes</span><strong>${fmtPrice(p.debit_note_total)}</strong></div>` : ""}
      ${p.net_payable != null ? `<div class="is-total"><span>Net payable</span><strong>${fmtPrice(p.net_payable)}</strong></div>` : ""}
    </div>
    <div class="vo-hub-expand-actions">
      ${p.receipt_id && ctx.canWrite?.("vendor_orders") && !p.closed_at ? `<button class="btn btn-primary btn-sm" onclick="Stock.openEditReceipt(${p.receipt_id})">Edit bill</button>` : ""}
      ${p.receipt_id ? `<button class="btn btn-secondary btn-sm" onclick="VendorOrders.openReceiptDoc(${p.receipt_id})">Bill Receipt</button>` : ""}
      ${p.bill_file_url ? `<button class="btn btn-secondary btn-sm" onclick="window.open('${ctx.esc(p.bill_file_url)}','_blank')">Vendor Bill</button>` : ""}
      ${p.receipt_id && ctx.canWrite?.("vendor_orders") ? `<button class="btn btn-secondary btn-sm" onclick="VendorOrders.openDebitNotes(${p.receipt_id})">Debit Note</button>` : ""}
      ${ctx.canWrite?.("vendor_orders") && !p.closed_at ? `<button class="btn btn-secondary btn-sm" onclick="VendorOrders.closeBilledPlacement(${p.id})">Close</button>` : ""}
    </div>`;
    return html;
  }

  function renderNoteHubCard(o, bucket, canWrite) {
    const open = hubExpandedVendorId === o.vendor_id;
    const cache = hubExpandCache[`${bucket}-${o.vendor_id}`];
    const meta = bucket === "cancelled"
      ? `${o.placement_count} placements · ${o.total_quantity} qty`
      : `${o.placement_count || 0} bills · ${o.line_count || 0} lines · ${o.total_quantity || 0} qty`;
    return OrdersUI.partyCard({
      title: o.vendor_label,
      meta: hubCardMeta(o, meta),
      pillHtml: OrdersUI.pill(bucket === "cancelled" ? "Cancelled" : "Closed", "muted"),
      primaryLabel: "View",
      primaryOnclick: `VendorOrders.openDetail(${o.id || 0}, '${bucket}', ${o.vendor_id})`,
      moreItems: [],
      open,
      rowOnclick: `VendorOrders.toggleHubVendor(${o.vendor_id}, '${bucket}', ${o.id || 0})`,
      canWrite: true,
      expandHtml: open
        ? `<div id="vo-hub-expand-${o.vendor_id}">${cache ? (bucket === "cancelled" ? renderCancelledExpand(cache) : renderClosedExpand(cache)) : `<p class="vo-muted" style="margin:0;padding:8px 0;">Loading…</p>`}</div>`
        : "",
    });
  }

  function renderCancelledExpand(order) {
    const placements = (order.placements || []).slice().sort((a, b) => new Date(b.placed_at) - new Date(a.placed_at));
    if (!placements.length) return `<p class="vo-muted" style="margin:0;">No cancelled placements.</p>`;
    return `<div class="vo-nested-list">${placements.map(p => {
      const pOpen = hubExpandedPlacementId === p.id;
      return `<div class="vo-nested-card ${pOpen ? "is-open" : ""} is-cancelled">
        <div class="vo-nested-row" onclick="event.stopPropagation();VendorOrders.toggleHubPlacement(${p.id}, ${order.id})">
          <div class="vo-hub-main">
            ${hubChevron(pOpen)}
            <div>
              <div class="vo-hub-title" style="font-size:14px;">${new Date(p.placed_at).toLocaleString()}</div>
              <div class="vo-hub-meta">${p.line_count} lines · ${p.total_quantity || "—"} qty</div>
              ${noteChip(p.cancel_reason, "cancel")}
            </div>
          </div>
        </div>
        ${pOpen ? `<div class="vo-nested-expand">${renderPlacementLines(order, p.id)}</div>` : ""}
      </div>`;
    }).join("")}</div>`;
  }

  function renderClosedExpand(payload) {
    const lines = payload.lines || payload || [];
    if (!lines.length) return `<p class="vo-muted" style="margin:0;">No closed items.</p>`;
    // Group: billed by bill_number/placement, open lines separately
    const bills = new Map();
    const openClosed = [];
    for (const l of lines) {
      if (l.source === "billed") {
        const key = l.placement_id || l.bill_number || `billed-${l.id}`;
        if (!bills.has(key)) {
          bills.set(key, {
            key,
            bill_number: l.bill_number,
            close_reason: l.close_reason,
            closed_at: l.closed_at,
            placement_id: l.placement_id,
            lines: [],
          });
        }
        bills.get(key).lines.push(l);
      } else {
        openClosed.push(l);
      }
    }
    let html = `<div class="vo-nested-list">`;
    for (const bill of bills.values()) {
      const qty = bill.lines.reduce((s, l) => s + (l.quantity || 0), 0);
      const open = String(hubExpandedPlacementId) === String(bill.placement_id || bill.key);
      const pid = bill.placement_id || 0;
      html += `<div class="vo-nested-card ${open ? "is-open" : ""} is-closed">
        <div class="vo-nested-row" onclick="event.stopPropagation();VendorOrders.toggleHubClosedBill('${String(bill.placement_id || bill.key).replace(/'/g, "")}')">
          <div class="vo-hub-main">
            ${hubChevron(open)}
            <div>
              <div class="vo-hub-title" style="font-size:14px;">Bill ${ctx.esc(bill.bill_number || `#${bill.placement_id || ""}`)}</div>
              <div class="vo-hub-meta">${bill.lines.length} products · ${qty} qty · ${bill.closed_at ? new Date(bill.closed_at).toLocaleString() : ""}</div>
              ${bill.close_reason ? noteChip(bill.close_reason, "close") : ""}
            </div>
          </div>
        </div>
        ${open ? `<div class="vo-nested-expand">
          <table class="data vo-hub-table"><thead><tr><th>Product</th><th>Qty</th><th>Price</th></tr></thead><tbody>
            ${bill.lines.map(l => `<tr>
              <td><strong>${ctx.esc(ctx.productIdLabel(l))}</strong></td>
              <td>${l.quantity}</td>
              <td>${fmtPrice(l.buying_price)}</td>
            </tr>`).join("")}
          </tbody></table>
        </div>` : ""}
      </div>`;
    }
    if (openClosed.length) {
      html += `<div class="vo-section-label">Closed from Open</div>`;
      html += `<table class="data vo-hub-table"><thead><tr><th>Product</th><th>Qty</th><th>Note</th><th>Closed</th></tr></thead><tbody>
        ${openClosed.map(l => `<tr>
          <td><strong>${ctx.esc(ctx.productIdLabel(l))}</strong></td>
          <td>${l.quantity}</td>
          <td>${l.close_reason ? `<span class="vo-note-inline">${ctx.esc(l.close_reason)}</span>` : "—"}</td>
          <td class="vo-muted">${l.closed_at ? new Date(l.closed_at).toLocaleString() : "—"}</td>
        </tr>`).join("")}
      </tbody></table>`;
    }
    html += `</div>`;
    return html;
  }

  function toggleHubClosedBill(key) {
    const token = String(key);
    hubExpandedPlacementId = String(hubExpandedPlacementId) === token ? null : (Number(token) || token);
    renderList();
  }

  async function toggleHubVendor(vendorId, bucket, orderId) {
    const expandId = (bucket === "open" || bucket === "open-bill")
      ? `${bucket === "open-bill" ? "to_bill" : "to_receive"}-${vendorId}`
      : vendorId;
    if (hubExpandedVendorId === expandId) {
      hubExpandedVendorId = null;
      hubExpandedPlacementId = null;
      renderList();
      return;
    }
    hubExpandedVendorId = expandId;
    hubExpandedPlacementId = null;
    renderList();
    const key = bucket === "open-bill" ? `open-bill-${vendorId}` : `${bucket}-${vendorId}`;
    try {
      if (bucket === "open") {
        hubExpandCache[key] = await ctx.api(`/vendor-orders/vendor/${vendorId}/open`, {}, 0);
      } else if (bucket === "open-bill") {
        const recv = await ctx.api(`/stock/vendor-order/${vendorId}/received`, {}, 0);
        hubExpandCache[key] = {
          vendor_id: vendorId,
          vendor_label: recv.vendor_label,
          receipts: recv.receipts || [],
        };
      } else if (bucket === "closed") {
        hubExpandCache[key] = { lines: await ctx.api(`/vendor-orders/vendor/${vendorId}/closed`, {}, 0) };
      } else {
        let id = orderId;
        if (!id || id <= 0) {
          const match = orders.find(o => o.vendor_id === vendorId && (!o.open_kind || o.bucket === bucket));
          id = match?.id || 0;
        }
        if (id > 0) hubExpandCache[key] = await ctx.api(`/vendor-orders/${id}?view=default`, {}, 0);
        else hubExpandCache[key] = { placements: [], aggregated_lines: [], vendor_id: vendorId };
      }
      if (hubExpandedVendorId === expandId) renderList();
    } catch (e) {
      ctx.toast(e.message, "error");
    }
  }

  function toggleHubPlacement(placementId, orderId) {
    hubExpandedPlacementId = hubExpandedPlacementId === placementId ? null : placementId;
    renderList();
  }

  async function openDetail(orderId, bucket, vendorId) {
    ctx.showLoading?.();
    try {
      // Map queue/legacy buckets to past stages
      let b = bucket || "placed";
      if (b === "summary" || b === "needs_action" || b === "queue") b = "placed";
      if (b === "open") b = "placed";
      if (!PAST_BUCKETS.includes(b)) b = "placed";
      currentBucket = b;
      detailVendorId = vendorId || null;
      showSummary = false;
      openOrder = null;
      closedLines = [];
      currentOrder = null;
      orderSummary = null;
      expandedProductId = null;
        expandedPlacementId = null;
      expandedClosedId = null;

      if ((!detailVendorId || detailVendorId <= 0) && orderId > 0) {
        currentOrder = await ctx.api(`/vendor-orders/${orderId}?view=default`, {}, 0);
        detailVendorId = currentOrder.vendor_id;
        if (currentOrder.bucket && BROWSE_BUCKETS.includes(currentOrder.bucket)) {
          currentBucket = currentOrder.bucket;
          b = currentBucket;
        }
      }

      if (!detailVendorId) {
        throw new Error("Vendor not found for this order");
      }

      if (b === "closed") {
        closedLines = await ctx.api(`/vendor-orders/vendor/${detailVendorId}/closed`, {}, 0);
        currentOrder = null;
      } else if (currentOrder && currentOrder.bucket === b) {
        // already loaded
      } else {
        const match = (await ctx.api(`/vendor-orders?bucket=${b}`, {}, 0)).find(o => o.vendor_id === detailVendorId);
        if (match?.id) {
          currentOrder = await ctx.api(`/vendor-orders/${match.id}?view=default`, {}, 0);
        } else if (orderId > 0) {
          currentOrder = await ctx.api(`/vendor-orders/${orderId}?view=default`, {}, 0);
          detailVendorId = currentOrder.vendor_id;
        } else {
          currentOrder = null;
        }
      }

      document.getElementById("orders-hub")?.classList.add("hidden");
      document.getElementById("orders-detail")?.classList.remove("hidden");
      syncBucketButtons(currentBucket, "vo-detail-buckets");
      updateDetailPrimary();
      renderDetail();
      App.updateGlobalBack?.();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function switchDetailBucket(bucket) {
    if (!detailVendorId) return;
    await openDetail(0, bucket, detailVendorId);
  }

  function detailVendorLabel() {
    return openOrder?.vendor_label
      || orderSummary?.vendor_label
      || currentOrder?.vendor_label
      || orders.find(o => o.vendor_id === detailVendorId)?.vendor_label
      || `Vendor #${detailVendorId || ""}`;
  }

  function setDetailHeader(titleText, subText, kicker) {
    const title = document.getElementById("orders-detail-title");
    const sub = document.getElementById("orders-detail-sub");
    const kick = document.getElementById("orders-detail-kicker");
    if (title) title.textContent = titleText || "Vendor Order";
    if (sub) sub.textContent = subText || "";
    if (kick) kick.textContent = kicker || (BUCKET_LABELS[currentBucket] || "Orders");
  }

  function detailStatPills(items) {
    return `<div class="vo-stat-pills">${items.map(([label, value]) => `
      <div class="vo-stat-pill">
        <span>${ctx.esc(label)}</span>
        <strong>${value}</strong>
      </div>`).join("")}</div>`;
  }

  function renderDetail() {
    const el = document.getElementById("orders-detail-body");
    if (!el) return;
    const canWrite = ctx.canWrite?.("vendor_orders");
    const showWho = ctx.isAdmin?.();

    if (currentBucket === "summary" && orderSummary) {
      setDetailHeader(orderSummary.vendor_label, "Live picture across placed, billed, pending, cancelled", "Summary");
      const lines = orderSummary.lines || [];
      const pendingTotal = lines.reduce((s, l) => s + (l.total_pending || 0), 0);
      el.innerHTML = `
        ${detailStatPills([
          ["Products", String(lines.length)],
          ["Pending", String(pendingTotal)],
          ["Placed", String(lines.reduce((s, l) => s + (l.total_placed || 0), 0))],
          ["Received", String(lines.reduce((s, l) => s + (l.total_received || 0), 0))],
        ])}
        <p class="vo-list-hint" style="border-radius:12px;margin-bottom:12px;">Tap a product for history. Bill or cancel only affects Open pending.</p>
        <div class="ord-hub-list">${lines.length ? lines.map(line => {
          const expanded = expandedProductId === line.catalog_product_id;
          const img = (line.image_urls && line.image_urls[0]) || "";
          return HubUI.partyCard({
            title: line.our_product_id,
            meta: `${thumb(img)} Placed ${line.total_placed} · Recv ${line.total_received} · <strong>Pending ${line.total_pending}</strong> · Cancelled ${line.total_cancelled} · Closed ${line.total_closed || 0}`,
            pillHtml: line.total_pending > 0 ? HubUI.pill("Pending", "warn") : HubUI.pill(fmtPrice(line.buying_price), "muted"),
            primaryLabel: canWrite && line.total_pending > 0 ? "Receive" : null,
            primaryOnclick: `VendorOrders.billSummaryLine(${line.catalog_product_id}, ${line.total_pending})`,
            moreItems: canWrite && line.total_pending > 0
              ? [{ label: "Cancel", onclick: `VendorOrders.cancelSummaryLine(${line.catalog_product_id})`, danger: true }]
              : [],
            open: expanded,
            rowOnclick: `VendorOrders.toggleSummaryRow(${line.catalog_product_id})`,
            canWrite: !!canWrite,
            expandHtml: expanded
              ? `<div id="vo-summary-drill-${line.catalog_product_id}"><p class="vo-muted" style="margin:0;">Loading history…</p></div>`
              : "",
          });
        }).join("") : HubUI.emptyState({ title: "No order activity", sub: "No order activity for this vendor yet." })}</div>`;
      return;
    }

    if (currentBucket === "open" && openOrder) {
      const lines = openOrder.lines || [];
      const totalPending = lines.reduce((s, l) => s + (l.quantity || 0), 0);
      setDetailHeader(openOrder.vendor_label, "Yet to receive — receive goods when they arrive, or cancel with a note", "Open");
      el.innerHTML = `
        ${detailStatPills([
          ["Products", String(lines.length)],
          ["Pending qty", String(totalPending)],
        ])}
        ${canWrite && lines.length ? `<div class="ui-toolbar vo-detail-toolbar">
          <div class="vo-detail-toolbar-copy"><strong>${lines.length}</strong> products · <strong>${totalPending}</strong> pending — use Receive above</div>
          <button class="btn btn-danger btn-sm" onclick="VendorOrders.cancelAllOpenLines()">Cancel Order</button>
        </div>` : ""}
        <div class="ord-hub-list">${lines.length ? lines.map(line => {
          const img = (line.image_urls && line.image_urls[0]) || "";
          return HubUI.partyCard({
            title: line.our_product_id,
            meta: `${thumb(img)} ${fmtPrice(line.buying_price)}${line.unit ? ` / ${ctx.esc(line.unit)}` : ""} · Pending <strong>${line.quantity}</strong>`,
            pillHtml: HubUI.pill(String(line.quantity), "warn"),
            primaryLabel: canWrite ? "Edit" : null,
            primaryOnclick: `VendorOrders.openEditOpenLine(${line.id})`,
            moreItems: canWrite ? [{ label: "Cancel", onclick: `VendorOrders.cancelOpenLine(${line.id})`, danger: true }] : [],
            canWrite: !!canWrite,
          });
        }).join("") : HubUI.emptyState({
          title: "Nothing pending",
          sub: "All billed, cancelled, or closed.",
          ctaHtml: canWrite ? `<button class="btn btn-primary" onclick="VendorOrders.showCreateMenu()">+ Create Order</button>` : "",
        })}</div>`;
      return;
    }

    if (currentBucket === "closed") {
      const label = detailVendorLabel();
      setDetailHeader(label, "Closed after payment — notes explain why each bill was closed", "Closed");
      const lines = closedLines || [];
      el.innerHTML = `
        ${detailStatPills([
          ["Items", String(lines.length)],
          ["Qty", String(lines.reduce((s, l) => s + (l.quantity || 0), 0))],
        ])}
        <div class="ord-hub-list">${lines.length ? lines.map(line => {
          const expanded = expandedClosedId === line.id;
          return HubUI.partyCard({
            title: line.our_product_id,
            meta: `${line.quantity} qty · ${ctx.esc(line.source)}${line.bill_number ? ` · Bill ${ctx.esc(line.bill_number)}` : ""} · ${line.closed_at ? new Date(line.closed_at).toLocaleString() : "—"}${line.close_reason ? noteChip(line.close_reason, "close") : ""}`,
            pillHtml: HubUI.pill(String(line.quantity), "muted"),
            open: expanded,
            rowOnclick: `VendorOrders.toggleClosedRow(${line.id})`,
            canWrite: true,
            expandHtml: expanded
              ? `<div id="vo-closed-drill-${line.id}"><p class="vo-muted" style="margin:0;">Loading…</p></div>`
              : "",
          });
        }).join("") : HubUI.emptyState({ title: "No closed items yet", sub: "Closed bills show up here." })}</div>`;
      return;
    }

    if (!currentOrder) {
      setDetailHeader(detailVendorLabel(), "Nothing in this bucket yet", BUCKET_LABELS[currentBucket] || "Orders");
      el.innerHTML = HubUI.emptyState({
        title: `No ${BUCKET_LABELS[currentBucket] || currentBucket}`,
        sub: "Nothing for this vendor in this stage.",
      });
      return;
    }

    const isPlaced = currentBucket === "placed";
    const isReceived = currentBucket === "received";
    const isBilled = currentBucket === "billed";
    const isCancelled = currentBucket === "cancelled";
    setDetailHeader(
      currentOrder.vendor_label,
      isPlaced ? "Record of what you placed — quantities stay fixed"
        : isReceived ? "Goods received — bill when vendor invoice arrives"
        : isBilled ? "Billed shipments — expand for amounts, receipt, vendor bill"
        : "Cancelled history with notes",
      isPlaced ? "Placed" : isReceived ? "Received" : isBilled ? "Billed" : "Cancelled"
    );

    if (isReceived) {
      const placements = (currentOrder.placements || []).slice().sort((a, b) => new Date(b.placed_at) - new Date(a.placed_at));
      const unbilled = (currentOrder.aggregated_lines || []).reduce((s, l) => s + (l.total_pending || 0), 0);
      const totalRecv = (currentOrder.aggregated_lines || []).reduce((s, l) => s + (l.total_quantity || 0), 0);
      el.innerHTML = `
        ${detailStatPills([
          ["Receives", String(placements.length)],
          ["Received qty", String(totalRecv)],
          ["Unbilled", String(unbilled)],
        ])}
        <div class="ord-hub-list">${placements.length ? placements.map(p => {
          const lines = linesForPlacement(p.id);
          return HubUI.partyCard({
            title: p.order_receipt_number ? `Receipt ${p.order_receipt_number}` : `Receive #${p.id}`,
            meta: `${lines.length} products · ${p.total_quantity || 0} qty · ${new Date(p.placed_at).toLocaleString()}${p.notes ? ` · ${ctx.esc(p.notes)}` : ""}`,
            primaryLabel: canWrite && p.receipt_id ? "Edit" : null,
            primaryOnclick: `Stock.openEditReceipt(${p.receipt_id})`,
            open: !!lines.length,
            canWrite: !!canWrite,
            expandHtml: lines.length ? `<table class="data vo-hub-table"><thead><tr><th>Product</th><th>Qty</th><th>Unbilled</th></tr></thead><tbody>
              ${lines.map(l => `<tr><td>${ctx.esc(ctx.productIdLabel(l))}</td><td>${l.quantity}</td><td>${l.quantity_remaining != null ? l.quantity_remaining : "—"}</td></tr>`).join("")}
            </tbody></table>` : "",
          });
        }).join("") : HubUI.emptyState({ title: "No receives yet", sub: "Receive goods from the Open or Placed stage." })}</div>`;
      return;
    }

    if (isBilled) {
      const placements = (currentOrder.placements || []).slice().sort((a, b) => new Date(b.placed_at) - new Date(a.placed_at));
      const openBills = placements.filter(p => !p.closed_at);
      const closedBills = placements.filter(p => p.closed_at);
      el.innerHTML = `
        ${detailStatPills([
          ["Bills", String(placements.length)],
          ["Open to close", String(openBills.length)],
          ["Closed", String(closedBills.length)],
          ["Received qty", String(currentOrder.aggregated_lines?.reduce((s, l) => s + (l.total_quantity || 0), 0) || 0)],
        ])}
        <p class="vo-list-hint" style="border-radius:12px;margin-bottom:12px;">Expand a bill for payable, debit notes, receipt, and vendor bill. Close after payment.</p>
        <div class="ord-hub-list">${placements.length ? placements.map(p => {
          const lines = linesForPlacement(p.id);
          const totalRecv = lines.reduce((s, l) => s + (l.quantity || 0), 0);
          const expanded = expandedPlacementId === p.id;
          const closed = !!p.closed_at;
          return HubUI.partyCard({
            title: p.bill_number || `Bill #${p.id}`,
            meta: `${placementBadge(p.color_index)} ${lines.length} products · ${totalRecv} received · ${new Date(p.placed_at).toLocaleString()}${p.net_payable != null ? ` · Net ${fmtPrice(p.net_payable)}` : ""}${closed && p.close_reason ? noteChip(p.close_reason, "close") : ""}`,
            pillHtml: closed ? HubUI.pill("Closed", "muted") : HubUI.pill("Open", "info"),
            primaryLabel: canWrite && !closed ? "Close" : null,
            primaryOnclick: `VendorOrders.closeBilledPlacement(${p.id})`,
            moreItems: canWrite && !closed && p.receipt_id
              ? [{ label: "Debit Note", onclick: `VendorOrders.openDebitNotes(${p.receipt_id})` }]
              : [],
            open: expanded,
            rowOnclick: `VendorOrders.togglePlacementRow(${p.id})`,
            canWrite: !!canWrite,
            expandHtml: expanded
              ? `<div id="vo-placement-drill-${p.id}"><p class="vo-muted" style="margin:0;">Loading bill details…</p></div>`
              : "",
          });
        }).join("") : HubUI.emptyState({ title: "No billed shipments yet", sub: "Bill received goods to see them here." })}</div>`;
      return;
    }

    // Placed / Cancelled — placement-first cards (matches hub)
    const placements = (currentOrder.placements || []).slice().sort((a, b) => new Date(b.placed_at) - new Date(a.placed_at));
    const totalQty = placements.reduce((s, p) => s + (p.total_quantity || 0), 0) ||
      (currentOrder.aggregated_lines || []).reduce((s, l) => s + (l.total_quantity || 0), 0);
    el.innerHTML = `
      ${detailStatPills([
        ["Placements", String(placements.length)],
        ["Products", String((currentOrder.aggregated_lines || []).length)],
        [isPlaced ? "Placed qty" : "Cancelled qty", String(totalQty)],
      ])}
      <p class="vo-list-hint" style="border-radius:12px;margin-bottom:12px;">${
        isPlaced
          ? "Expand a placement for line items. Cancel clears Open; placed qty stays."
          : "Cancelled placements with notes. Expand for line details."
      }</p>
      <div class="ord-hub-list">${placements.length ? placements.map(p => {
        const expanded = expandedPlacementId === p.id;
        const cancelled = !!p.cancel_reason || p.status === "cancelled" || isCancelled;
        return HubUI.partyCard({
          title: `${isCancelled ? "Cancelled" : "Placement"} · ${new Date(p.placed_at).toLocaleString()}`,
          meta: `${placementBadge(p.color_index)} ${p.line_count} lines · ${p.total_quantity || "—"} qty${showWho ? ` · ${ctx.esc(p.placed_by_name)}` : ""}${p.cancel_reason ? noteChip(p.cancel_reason, "cancel") : ""}`,
          pillHtml: cancelled ? HubUI.pill("Cancelled", "danger") : HubUI.pill("Placed", "muted"),
          primaryLabel: canWrite && isPlaced && !cancelled ? "Receive" : null,
          primaryOnclick: `VendorOrders.receiveOrder()`,
          moreItems: canWrite && isPlaced && !cancelled
            ? [{ label: "Cancel", onclick: `VendorOrders.cancelPlacement(${p.id})`, danger: true }]
            : [],
          open: expanded,
          rowOnclick: `VendorOrders.togglePlacementRow(${p.id})`,
          canWrite: !!canWrite,
          expandHtml: expanded
            ? `<div id="vo-placement-drill-${p.id}"><p class="vo-muted" style="margin:0;">Loading…</p></div>`
            : "",
        });
      }).join("") : HubUI.emptyState({ title: "No placements here", sub: "Place a vendor order to see history." })}</div>`;
  }

  function isDetailVisible() {
    return !document.getElementById("orders-detail")?.classList.contains("hidden");
  }

  async function rerenderDetailKeepExpand() {
    const keepPlacement = expandedPlacementId;
    const keepSummary = expandedProductId;
    const keepClosed = expandedClosedId;
    renderDetail();
    if (keepPlacement && document.getElementById(`vo-placement-drill-${keepPlacement}`)) {
      await loadPlacementExpand(keepPlacement);
    }
    if (keepSummary && detailVendorId && document.getElementById(`vo-summary-drill-${keepSummary}`)) {
      try {
        summaryDrill = await ctx.api(`/vendor-orders/vendor/${detailVendorId}/order-summary/${keepSummary}`, {}, 0);
        const wrap = document.getElementById(`vo-summary-drill-${keepSummary}`);
        if (wrap && summaryDrill?.events?.length) {
          wrap.innerHTML = `
            <div class="vo-section-label">History — ${ctx.esc(summaryDrill.our_product_id)}</div>
            <table class="data vo-hub-table"><thead><tr>
              <th>When</th><th>Type</th><th>Qty</th><th>Billed</th><th>Amount</th><th>Bill</th><th>By</th>
            </tr></thead><tbody>
              ${summaryDrill.events.map(e => `<tr>
                <td class="vo-muted">${new Date(e.occurred_at).toLocaleString()}</td>
                <td><span class="vo-event-pill">${ctx.esc(e.event_type)}${e.placement_index != null ? ` #${e.placement_index + 1}` : ""}</span></td>
                <td>${e.quantity}</td>
                <td>${e.quantity_billed ?? "—"}</td>
                <td>${fmtAmtOrDash(e.billed_amount)}</td>
                <td>${ctx.esc(e.bill_number || "—")}</td>
                <td>${ctx.esc(e.actor_name || "—")}</td>
              </tr>`).join("")}
            </tbody></table>`;
        } else if (wrap) {
          wrap.innerHTML = `<p class="vo-muted" style="margin:0;">No history for this product.</p>`;
        }
      } catch (e) {
        const wrap = document.getElementById(`vo-summary-drill-${keepSummary}`);
        if (wrap) wrap.innerHTML = `<p style="color:var(--danger);font-size:13px;">${ctx.esc(e.message)}</p>`;
      }
    }
    if (keepClosed && document.getElementById(`vo-closed-drill-${keepClosed}`)) {
      await loadClosedRowExpand(keepClosed);
    }
  }

  function clearHubCacheForVendor(vendorId) {
    if (!vendorId) return;
    for (const key of Object.keys(hubExpandCache)) {
      if (key.endsWith(`-${vendorId}`)) delete hubExpandCache[key];
    }
  }

  async function reloadAfterVendorChange(vendorId, preferredBucket) {
    clearHubCacheForVendor(vendorId);
    ctx.invalidateCache?.("/vendor-orders");
    if (isDetailVisible() && detailVendorId === vendorId) {
      await openDetail(currentOrder?.id || 0, preferredBucket || currentBucket, vendorId);
      return;
    }
    const keepExpanded = hubExpandedVendorId === vendorId;
    const keepPlacement = hubExpandedPlacementId;
    const hubBucket = currentBucket;
    hubExpandedVendorId = null;
    hubExpandedPlacementId = null;
    await loadList();
    if (keepExpanded && hubBucket !== "summary") {
      const match = orders.find(o => o.vendor_id === vendorId);
      if (match || hubBucket === "open" || hubBucket === "closed") {
        await toggleHubVendor(vendorId, hubBucket, match?.id || 0);
        if (keepPlacement && hubExpandCache[`${hubBucket}-${vendorId}`]) {
          hubExpandedPlacementId = keepPlacement;
          renderList();
        }
      }
    }
  }

  function linesForPlacement(placementId) {
    const out = [];
    for (const agg of currentOrder?.aggregated_lines || []) {
      for (const b of agg.breakdown || []) {
        if (b.placement_id === placementId) {
          out.push({
            our_product_id: agg.our_product_id,
            vendor_product_id: agg.vendor_product_id,
            image_urls: agg.image_urls,
            buying_price: agg.buying_price,
            quantity: b.quantity,
            quantity_billed: b.quantity_billed,
            billed_amount: b.billed_amount,
            placement_id: b.placement_id,
          });
        }
      }
    }
    return out;
  }

  async function togglePlacementRow(placementId) {
    expandedPlacementId = expandedPlacementId === placementId ? null : placementId;
    renderDetail();
    if (expandedPlacementId) await loadPlacementExpand(placementId);
  }

  async function loadPlacementExpand(placementId) {
    const wrap = document.getElementById(`vo-placement-drill-${placementId}`);
    const placement = (currentOrder?.placements || []).find(p => p.id === placementId);
    if (!wrap || !placement) return;

    if (currentBucket === "placed" || currentBucket === "cancelled") {
      const cancelled = !!placement.cancel_reason || placement.status === "cancelled" || currentBucket === "cancelled";
      const canEdit = !!ctx.canWrite?.("vendor_orders") && !cancelled && currentBucket === "placed";
      let html = renderPlacementLines(currentOrder, placementId, canEdit);
      if (currentBucket === "placed") {
        html += `<div class="vo-hub-expand-actions">
          <button class="btn btn-secondary btn-sm" onclick="VendorOrders.openPlacementDoc(${placementId})">Order PDF</button>
          ${canEdit ? `<button class="btn btn-danger btn-sm" onclick="VendorOrders.cancelPlacement(${placementId})">Cancel Order</button>` : ""}
        </div>`;
        if (cancelled) html = noteChip(placement.cancel_reason, "cancel") + html;
      } else if (placement.cancel_reason) {
        html = noteChip(placement.cancel_reason, "cancel") + html;
      }
      wrap.innerHTML = html;
      return;
    }

    const lines = linesForPlacement(placementId);
    const showAmt = lines.some(l => l.billed_amount != null && Number(l.billed_amount) !== 0);
    let html = `<table class="data vo-hub-table"><thead><tr>
        <th></th><th>Product</th><th>Received</th><th>Billed qty</th>${showAmt ? "<th>Amount</th>" : ""}
      </tr></thead><tbody>
        ${lines.map(l => {
          const img = (l.image_urls && l.image_urls[0]) || "";
          return `<tr>
            <td>${thumb(img, "vo-thumb-sm")}</td>
            <td><strong>${ctx.esc(ctx.productIdLabel(l))}</strong></td>
            <td>${l.quantity}</td>
            <td>${l.quantity_billed ?? "—"}</td>
            ${showAmt ? `<td>${fmtAmtOrDash(l.billed_amount)}</td>` : ""}
          </tr>`;
        }).join("")}
      </tbody></table>`;

    if (placement.bill_amount != null || placement.net_payable != null) {
      html += `<div class="vo-money-block">
        ${placement.bill_amount != null ? `<div><span>Bill amount</span><strong>${fmtPrice(placement.bill_amount)}</strong></div>` : ""}
        ${placement.debit_note_total != null && Number(placement.debit_note_total) ? `<div><span>Debit notes</span><strong>${fmtPrice(placement.debit_note_total)}</strong></div>` : ""}
        ${placement.net_payable != null ? `<div class="is-total"><span>Net payable</span><strong>${fmtPrice(placement.net_payable)}</strong></div>` : ""}
      </div>`;
    }

    if (placement.receipt_id) {
      try {
        const [receipt, notes] = await Promise.all([
          ctx.api(`/stock/receipts/${placement.receipt_id}`, {}, 0),
          ctx.api(`/debit-notes?receipt_id=${placement.receipt_id}`, {}, 0).catch(() => []),
        ]);
        if (!(placement.bill_amount != null || placement.net_payable != null)) {
          html += `<div class="vo-money-block">
            ${ctx.reviewRow ? "" : ""}
            <div><span>Bill amount</span><strong>${fmtPrice(receipt.bill_amount)}</strong></div>
            ${receipt.additional_charges ? `<div><span>Additional charges</span><strong>${fmtPrice(receipt.additional_charges)}</strong></div>` : ""}
            ${receipt.debit_note_total && Number(receipt.debit_note_total) ? `<div><span>Debit notes</span><strong>${fmtPrice(receipt.debit_note_total)}</strong></div>` : ""}
            <div class="is-total"><span>Net payable</span><strong>${fmtPrice(receipt.net_payable)}</strong></div>
          </div>`;
        }
        if (notes.length) {
          html += `<div class="vo-section-label">Debit notes</div>
            <table class="data vo-hub-table"><thead><tr><th>Note</th><th>Effect</th></tr></thead><tbody>
              ${notes.map(n => {
                const lbl = n.note_type === "item" ? `${ctx.esc(n.our_product_id || "")} × ${n.quantity}${n.notes ? ` — ${ctx.esc(n.notes)}` : ""}` : `Value adjustment${n.notes ? ` — ${ctx.esc(n.notes)}` : ""}`;
                const effect = n.payable_effect != null ? n.payable_effect : (n.note_type === "item" ? -Number(n.amount) : Number(n.amount));
                return `<tr><td>${lbl}</td><td>${fmtPrice(effect)}</td></tr>`;
              }).join("")}
            </tbody></table>`;
        }
        html += `<div class="vo-hub-expand-actions">
          <button class="btn btn-primary btn-sm" onclick="VendorOrders.openReceiptDoc(${placement.receipt_id})">Bill Receipt</button>
          ${placement.bill_file_url ? `<button class="btn btn-secondary btn-sm" onclick="window.open('${ctx.esc(placement.bill_file_url)}','_blank')">Vendor Bill</button>` : ""}
          ${ctx.canWrite?.("vendor_orders") ? `<button class="btn btn-secondary btn-sm" onclick="VendorOrders.openDebitNotes(${placement.receipt_id})">Debit Note</button>` : ""}
          ${!placement.closed_at && ctx.canWrite?.("vendor_orders") ? `<button class="btn btn-secondary btn-sm" onclick="VendorOrders.closeBilledPlacement(${placementId})">Close</button>` : ""}
        </div>`;
      } catch (e) {
        html += `<p style="color:var(--danger);font-size:13px;">${ctx.esc(e.message)}</p>`;
      }
    } else {
      html += `<p class="vo-muted" style="margin:12px 0 0;">No receipt linked to this bill yet.</p>`;
    }
    if (placement.closed_at && placement.close_reason) {
      html = noteChip(placement.close_reason, "close") + html;
    }
    wrap.innerHTML = html;
  }

  function closePlacedLine(catalogProductId) {
    const line = (currentOrder?.aggregated_lines || []).find(l => l.catalog_product_id === catalogProductId);
    if (!line || !(line.total_pending > 0)) return;
    openConfirmAction({
      title: "Close pending qty",
      message: "Removes from Open and records as closed.",
      rows: [
        ["Product", ctx.esc(line.our_product_id)],
        ["Pending", String(line.total_pending)],
        ["Price", fmtPrice(line.buying_price)],
      ],
      confirmLabel: "Close",
      requireReason: true,
      reasonLabel: "Close note",
      onConfirm: async (reason) => {
        await ctx.api(`/vendor-orders/vendor/${detailVendorId}/products/${catalogProductId}/close-pending`, { method: "POST", body: reasonBody(reason) });
        ctx.invalidateCache?.("/vendor-orders");
        ctx.toast("Pending closed", "success");
        await openDetail(0, "placed", detailVendorId);
      },
    });
  }

  function cancelPlacedLine(catalogProductId) {
    const line = (currentOrder?.aggregated_lines || []).find(l => l.catalog_product_id === catalogProductId);
    if (!line || !(line.total_pending > 0)) return;
    openConfirmAction({
      title: "Cancel pending qty",
      message: "Removed from Open. Recorded in Cancelled. Placed qty stays.",
      rows: [
        ["Product", ctx.esc(line.our_product_id)],
        ["Pending", String(line.total_pending)],
        ["Placed", String(line.total_placed || line.total_quantity)],
        ["Price", fmtPrice(line.buying_price)],
      ],
      confirmLabel: "Cancel pending",
      danger: true,
      requireReason: true,
      reasonLabel: "Cancel note",
      onConfirm: async (reason) => {
        await ctx.api(`/vendor-orders/vendor/${detailVendorId}/products/${catalogProductId}/cancel-pending`, { method: "POST", body: reasonBody(reason) });
        ctx.invalidateCache?.("/vendor-orders");
        ctx.toast("Pending cancelled", "success");
        await openDetail(0, "placed", detailVendorId);
      },
    });
  }

  async function refreshIfOpen(vendorId) {
    if (!vendorId) return;
    clearHubCacheForVendor(vendorId);
    ctx.invalidateCache?.("/vendor-orders");
    // After bill, Open/Placed/Summary/Billed may all change
    if (isDetailVisible() && detailVendorId === vendorId) {
      const bucket = currentBucket === "cancelled" || currentBucket === "closed" ? "billed" : currentBucket;
      await openDetail(0, bucket, vendorId);
      return;
    }
    if (["summary", "open", "placed", "received", "billed"].includes(currentBucket)) {
      const wasExpanded = hubExpandedVendorId === vendorId;
      const keepBucket = currentBucket;
      hubExpandedVendorId = null;
      hubExpandedPlacementId = null;
      await loadList();
      if (wasExpanded && keepBucket !== "summary") {
        const match = orders.find(o => o.vendor_id === vendorId);
        if (match || keepBucket === "open") await toggleHubVendor(vendorId, keepBucket, match?.id || 0);
      }
    }
  }

  async function toggleSummaryRow(id) {
    expandedProductId = expandedProductId === id ? null : id;
    renderDetail();
    if (expandedProductId && detailVendorId) {
      try {
        summaryDrill = await ctx.api(`/vendor-orders/vendor/${detailVendorId}/order-summary/${id}`, {}, 0);
        const wrap = document.getElementById(`vo-summary-drill-${id}`);
        if (wrap && summaryDrill?.events?.length) {
          wrap.innerHTML = `
            <div class="vo-section-label">History — ${ctx.esc(summaryDrill.our_product_id)}</div>
            <table class="data vo-hub-table"><thead><tr>
              <th>When</th><th>Type</th><th>Qty</th><th>Billed</th><th>Amount</th><th>Bill</th><th>By</th>
            </tr></thead><tbody>
              ${summaryDrill.events.map(e => `<tr>
                <td class="vo-muted">${new Date(e.occurred_at).toLocaleString()}</td>
                <td><span class="vo-event-pill">${ctx.esc(e.event_type)}${e.placement_index != null ? ` #${e.placement_index + 1}` : ""}</span></td>
                <td>${e.quantity}</td>
                <td>${e.quantity_billed ?? "—"}</td>
                <td>${fmtAmtOrDash(e.billed_amount)}</td>
                <td>${ctx.esc(e.bill_number || "—")}</td>
                <td>${ctx.esc(e.actor_name || "—")}</td>
              </tr>`).join("")}
            </tbody></table>`;
        } else if (wrap) {
          wrap.innerHTML = `<p style="font-size:13px;color:var(--muted);margin:0;">No history for this product.</p>`;
        }
      } catch (e) {
        const wrap = document.getElementById(`vo-summary-drill-${id}`);
        if (wrap) wrap.innerHTML = `<p style="color:var(--danger);font-size:13px;">${ctx.esc(e.message)}</p>`;
      }
    }
  }

  function openLinesConfirmRows(lines, vendorLabel) {
    const rows = [["Vendor", ctx.esc(vendorLabel || "—")]];
    (lines || []).slice(0, 8).forEach(l => {
      rows.push(["Product", `${ctx.esc(ctx.productIdLabel(l))} — ${l.quantity} @ ${fmtPrice(l.buying_price)}`]);
    });
    if ((lines || []).length > 8) rows.push(["More", `${lines.length - 8} additional lines`]);
    rows.push(["Total pending", String((lines || []).reduce((s, l) => s + (l.quantity || 0), 0))]);
    return rows;
  }

  async function runOpenLineBatch(lines, action, reason) {
    const endpoint = action === "cancel" ? "cancel" : "close";
    let ok = 0;
    const errors = [];
    for (const line of lines) {
      try {
        await ctx.api(`/vendor-orders/open-lines/${line.id}/${endpoint}`, { method: "POST", body: reasonBody(reason) });
        ok += 1;
      } catch (e) {
        errors.push(`${line.our_product_id || line.id}: ${e.message || "failed"}`);
      }
    }
    ctx.invalidateCache?.("/vendor-orders");
    return { ok, failed: errors.length, errors };
  }

  async function closeVendorOpen(vendorId, vendorLabel) {
    ctx.showLoading?.();
    try {
      const detail = await ctx.api(`/vendor-orders/vendor/${vendorId}/open`, {}, 0);
      const lines = detail.lines || [];
      if (!lines.length) return ctx.toast("No open lines", "error");
      openConfirmAction({
        title: "Close all open lines",
        message: "Removes all pending from Open and records as closed.",
        rows: openLinesConfirmRows(lines, vendorLabel || detail.vendor_label),
        confirmLabel: "Close all",
        requireReason: true,
        reasonLabel: "Close note",
        onConfirm: async (reason) => {
          const result = await runOpenLineBatch(lines, "close", reason);
          if (result.failed) ctx.toast(`Closed ${result.ok}, failed ${result.failed}`, "error");
          else ctx.toast(`Closed ${result.ok} line(s)`, "success");
          await reloadAfterVendorChange(vendorId, "open");
        },
      });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function cancelVendorOpen(vendorId, vendorLabel) {
    ctx.showLoading?.();
    try {
      const detail = await ctx.api(`/vendor-orders/vendor/${vendorId}/open`, {}, 0);
      const lines = detail.lines || [];
      if (!lines.length) return ctx.toast("No open lines", "error");
      openConfirmAction({
        title: "Cancel Order",
        message: "Removes open qty. Recorded in Cancelled. Placed record stays.",
        rows: openLinesConfirmRows(lines, vendorLabel || detail.vendor_label),
        confirmLabel: "Cancel Order",
        danger: true,
        requireReason: true,
        reasonLabel: "Cancel note",
        onConfirm: async (reason) => {
          const result = await runOpenLineBatch(lines, "cancel", reason);
          if (result.failed) ctx.toast(`Cancelled ${result.ok}, failed ${result.failed}`, "error");
          else ctx.toast(`Order cancelled (${result.ok})`, "success");
          await reloadAfterVendorChange(vendorId, "open");
        },
      });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function closeAllOpenLines() {
    const lines = openOrder?.lines || [];
    if (!lines.length) return ctx.toast("No open lines", "error");
    openConfirmAction({
      title: "Close all open lines",
      message: "Removes all pending from Open and records as closed.",
      rows: openLinesConfirmRows(lines, openOrder?.vendor_label),
      confirmLabel: "Close all",
      requireReason: true,
      reasonLabel: "Close note",
      onConfirm: async (reason) => {
        const result = await runOpenLineBatch(lines, "close", reason);
        if (result.failed) ctx.toast(`Closed ${result.ok}, failed ${result.failed}`, "error");
        else ctx.toast(`Closed ${result.ok} line(s)`, "success");
        await reloadAfterVendorChange(detailVendorId, "open");
      },
    });
  }

  function cancelAllOpenLines() {
    const lines = openOrder?.lines || [];
    if (!lines.length) return ctx.toast("No open lines", "error");
    openConfirmAction({
      title: "Cancel Order",
      message: "Removes open qty. Recorded in Cancelled. Placed record stays.",
      rows: openLinesConfirmRows(lines, openOrder?.vendor_label),
      confirmLabel: "Cancel Order",
      danger: true,
      requireReason: true,
      reasonLabel: "Cancel note",
      onConfirm: async (reason) => {
        const result = await runOpenLineBatch(lines, "cancel", reason);
        if (result.failed) ctx.toast(`Cancelled ${result.ok}, failed ${result.failed}`, "error");
        else ctx.toast(`Order cancelled (${result.ok})`, "success");
        await reloadAfterVendorChange(detailVendorId, "open");
      },
    });
  }

  async function closeOpenLine(lineId) {
    const line = (openOrder?.lines || []).find(l => l.id === lineId);
    if (!line) return;
    openConfirmAction({
      title: "Close open line",
      message: "Removes from Open and records as closed.",
      rows: [
        ["Product", ctx.esc(line.our_product_id)],
        ["Pending qty", String(line.quantity)],
        ["Price", fmtPrice(line.buying_price)],
      ],
      confirmLabel: "Close",
      requireReason: true,
      reasonLabel: "Close note",
      onConfirm: async (reason) => {
        await ctx.api(`/vendor-orders/open-lines/${lineId}/close`, { method: "POST", body: reasonBody(reason) });
        ctx.toast("Line closed", "success");
        await reloadAfterVendorChange(detailVendorId || openOrder?.vendor_id, "open");
      },
    });
  }

  async function cancelOpenLine(lineId) {
    const line = (openOrder?.lines || []).find(l => l.id === lineId);
    if (!line) return;
    openConfirmAction({
      title: "Cancel line",
      message: "Removes open qty. Recorded in Cancelled.",
      rows: [
        ["Product", ctx.esc(line.our_product_id)],
        ["Qty", String(line.quantity)],
        ["Price", fmtPrice(line.buying_price)],
      ],
      confirmLabel: "Cancel line",
      danger: true,
      requireReason: true,
      reasonLabel: "Cancel note",
      onConfirm: async (reason) => {
        await ctx.api(`/vendor-orders/open-lines/${lineId}/cancel`, { method: "POST", body: reasonBody(reason) });
        ctx.toast("Line cancelled", "success");
        await reloadAfterVendorChange(detailVendorId || openOrder?.vendor_id, "open");
      },
    });
  }


  function hubOrderForVendor(vendorId, bucket) {
    return hubExpandCache[`${bucket}-${vendorId}`] || currentOrder;
  }

  function findPlacementAnywhere(placementId) {
    if (currentOrder?.placements) {
      const p = currentOrder.placements.find(x => x.id === placementId);
      if (p) return { order: currentOrder, placement: p };
    }
    for (const [key, order] of Object.entries(hubExpandCache)) {
      if (!order?.placements) continue;
      const p = order.placements.find(x => x.id === placementId);
      if (p) return { order, placement: p, cacheKey: key };
    }
    return { order: null, placement: null };
  }

  async function closeBilledPlacement(placementId) {
    const found = findPlacementAnywhere(placementId);
    const placement = found.placement;
    const order = found.order;
    if (!placement) {
      ctx.toast("Bill not loaded — expand the vendor first", "error");
      return;
    }
    const lines = (order?.aggregated_lines || []).flatMap(l =>
      (l.breakdown || []).filter(b => b.placement_id === placementId).map(b => `${l.our_product_id} × ${b.quantity}`)
    );
    openConfirmAction({
      title: "Close billed shipment",
      message: "Marks paid / done. Moves to Closed with your note.",
      rows: [
        ["Bill", ctx.esc(placement.bill_number || `Shipment #${placementId}`)],
        ["Placed", new Date(placement.placed_at).toLocaleString()],
        ["Lines", lines.join(", ") || `${placement.line_count} items`],
      ],
      confirmLabel: "Close shipment",
      requireReason: true,
      reasonLabel: "Close note",
      onConfirm: async (reason) => {
        const result = await ctx.api(`/vendor-orders/placements/${placementId}/close`, { method: "POST", body: reasonBody(reason) });
        currentOrder = result;
        ctx.toast("Shipment closed", "success");
        await reloadAfterVendorChange(result.vendor_id, isDetailVisible() ? "billed" : currentBucket);
        if (isDetailVisible()) await rerenderDetailKeepExpand();
      },
    });
  }

  async function openDebitNotes(receiptId) {
    if (!receiptId) {
      ctx.toast?.("No bill receipt on this shipment", "error");
      return;
    }
    if (typeof DebitNotes === "undefined" || !DebitNotes.openForReceipt) {
      ctx.toast?.("Debit notes module failed to load — hard refresh", "error");
      return;
    }
    let order = currentOrder;
    let vendorId = detailVendorId || hubExpandedVendorId;
    if (!order && hubExpandedVendorId) {
      order = hubExpandCache[`billed-${hubExpandedVendorId}`] || hubExpandCache[`closed-${hubExpandedVendorId}`];
    }
    if (!vendorId && order) vendorId = order.vendor_id;
    if (!vendorId) {
      ctx.toast?.("Vendor not found for debit note", "error");
      return;
    }
    const lines = (order?.aggregated_lines || []).flatMap(l =>
      (l.breakdown || []).map(() => ({ catalog_product_id: l.catalog_product_id, our_product_id: l.our_product_id, buying_price: l.buying_price }))
    );
    const unique = [...new Map(lines.map(l => [l.catalog_product_id, l])).values()];
    try {
      await DebitNotes.openForReceipt({
        vendorId,
        receiptId,
        receivingLines: unique,
        onDone: async () => {
          await reloadAfterVendorChange(vendorId, "billed");
          if (isDetailVisible()) await rerenderDetailKeepExpand();
        },
      });
    } catch (e) {
      ctx.toast?.(e.message || "Could not open debit notes", "error");
    }
  }
  // keep alias for any leftover callers
  async function addDebitNote(receiptId) { return openDebitNotes(receiptId); }

  async function cancelPlacement(placementId) {
    const found = findPlacementAnywhere(placementId);
    const placement = found.placement;
    const order = found.order;
    if (!placement) {
      ctx.toast("Placement not loaded — expand the vendor first", "error");
      return;
    }
    const lineRows = (order?.aggregated_lines || []).flatMap(l =>
      (l.breakdown || []).filter(b => b.placement_id === placementId).map(b => [l.our_product_id, `${b.quantity} @ ${fmtPrice(b.buying_price)}`])
    );
    openConfirmAction({
      title: "Cancel Order",
      message: "Clears Open for these items. Placed record stays. History goes to Cancelled.",
      rows: [
        ["Placement", placement ? `#${placement.color_index + 1}` : String(placementId)],
        ["Placed", placement ? new Date(placement.placed_at).toLocaleString() : "—"],
        ...lineRows.map(([prod, detail]) => ["Product", `${prod} — ${detail}`]),
      ],
      confirmLabel: "Cancel Order",
      danger: true,
      requireReason: true,
      reasonLabel: "Cancel note",
      onConfirm: async (reason) => {
        const result = await ctx.api(`/vendor-orders/placements/${placementId}/cancel`, { method: "POST", body: reasonBody(reason) });
        currentOrder = result;
        ctx.toast("Order cancelled", "success");
        await reloadAfterVendorChange(result.vendor_id, isDetailVisible() ? "placed" : currentBucket);
        if (isDetailVisible()) await rerenderDetailKeepExpand();
      },
    });
  }

  function showCreateMenuFromVendor(vendorId) {
    detailVendorId = vendorId;
    showCreateMenu();
  }

  function showCreateMenu() {
    document.getElementById("order-create-new-btn")?.classList.remove("hidden");
    document.getElementById("order-create-offline-btn")?.classList.remove("hidden");
    OrderMenus.openCreate({
      onNew: () => openWizard(detailVendorId || null),
      onOffline: () => Stock.openOfflineWizard(detailVendorId || null),
    });
  }

  function runHubAction() {
    if (currentBucket === "placed") {
      Stock.openReceiveForVendor(null);
      return;
    }
    if (currentBucket === "received" || currentBucket === "open") {
      if (currentBucket === "received") Stock.openBillForVendor(null);
      else ctx.toast("Use Receive Order or Bill Order on a row", "error");
      return;
    }
    if (currentBucket === "billed") openCloseBatch(null);
  }

  function runDetailAction() {
    if (currentBucket === "placed" || currentBucket === "open") receiveOrder();
    else if (currentBucket === "received") billOrder();
    else if (currentBucket === "billed") openCloseBatch(detailVendorId);
  }

  async function openCloseBatch(vendorId) {
    ctx.showLoading?.();
    try {
      const q = vendorId != null ? `?vendor_id=${vendorId}` : "";
      const items = await ctx.api(`/vendor-orders/closeable${q}`, {}, 0);
      OrderMenus.openClose({
        title: "Close Billed Shipments",
        items: items.map(it => ({
          id: it.id,
          party: it.vendor_label,
          label: it.bill_number ? `Bill ${it.bill_number}` : `Shipment #${it.id}`,
          sublabel: `${it.line_count} lines · ${it.total_qty} qty`,
          quantity: it.total_qty,
        })),
        ctx,
        onSubmit: async (ids, reason) => {
          await ctx.api("/vendor-orders/close-batch", { method: "POST", body: JSON.stringify({ placement_ids: ids, reason }) });
          ctx.invalidateCache?.("/vendor-orders");
          ctx.toast(`Closed ${ids.length} shipment(s)`, "success");
          if (detailVendorId) await openDetail(0, currentBucket, detailVendorId);
          else loadList();
        },
      });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function openWizard(presetVendorId) {
    wizardStep = 1;
    wizardVendorId = presetVendorId || detailVendorId || null;
    wizardProducts = [];
    wizardLines = [];
    wizardProductSearch = "";
    wizardVendorSearch = "";
    wizardVendorsCache = [];
    wizardPlacedOn = localToday();
    document.getElementById("vo-wizard")?.classList.remove("hidden");
    renderWizard();
  }

  function primeVendors(list) {
    wizardVendorsCache = Array.isArray(list) ? list : [];
  }

  async function ensureWizardVendors() {
    // Always refetch when opening place-order — avoids stale cache after vendor create.
    try {
      ctx.invalidateCache?.("/vendors");
      wizardVendorsCache = (await ctx.api("/vendors", {}, 0) || []).map(v => ({ ...v, alias: v.alias || "" }));
    } catch (_) {
      if (!wizardVendorsCache.length) wizardVendorsCache = [];
    }
    // If preset vendor missing from list (race), inject from App / single fetch.
    if (wizardVendorId && !(wizardVendorsCache || []).some(v => v.id === wizardVendorId)) {
      let injected = (ctx.getVendors?.() || []).find(v => v.id === wizardVendorId);
      if (!injected) {
        try { injected = await ctx.api(`/vendors/${wizardVendorId}`, {}, 0); } catch (_) { injected = null; }
      }
      if (injected) wizardVendorsCache = [injected, ...(wizardVendorsCache || [])];
    }
    return wizardVendorsCache;
  }

  function closeWizard() { document.getElementById("vo-wizard")?.classList.add("hidden"); }

  function wizardSelectedVendor(vendors) {
    return (vendors || []).find(v => v.id === wizardVendorId) || null;
  }

  function filterWizardProducts() {
    const q = wizardProductSearch.trim().toLowerCase();
    if (!q) return wizardProducts;
    const scored = [];
    for (const p of wizardProducts) {
      const id = String(p.our_product_id || "").toLowerCase();
      const vid = String(p.vendor_product_id || "").toLowerCase();
      const cat = String(p.category || "").toLowerCase();
      const series = String(p.series || "").toLowerCase();
      let score = 0;
      if (id === q || vid === q) score = 100;
      else if (id.startsWith(q) || vid.startsWith(q)) score = 80;
      else if (id.includes(q) || vid.includes(q)) score = 40;
      else if (cat.startsWith(q) || series.startsWith(q)) score = 30;
      else if (cat.includes(q) || series.includes(q)) score = 10;
      else continue;
      scored.push({ p, score, id });
    }
    scored.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
    return scored.map(x => x.p);
  }

  function wizardCartTotal() {
    return wizardLines.reduce((sum, l) => {
      const p = wizardProducts.find(x => x.id === l.catalog_product_id);
      const price = p ? Number(p.buying_price) || 0 : 0;
      return sum + price * (Number(l.quantity) || 0);
    }, 0);
  }

  function wizardCartQty() {
    return wizardLines.reduce((sum, l) => sum + (Number(l.quantity) || 0), 0);
  }

  async function renderWizard() {
    const stepsEl = document.getElementById("vo-wizard-steps");
    const bodyEl = document.getElementById("vo-wizard-body");
    const footerEl = document.getElementById("vo-wizard-footer");
    const titleEl = document.getElementById("vo-wizard-title");
    const subEl = document.getElementById("vo-wizard-sub");
    if (!stepsEl || !bodyEl || !footerEl) return;

    stepsEl.innerHTML = STEP_LABELS.map((lbl, i) => {
      const n = i + 1;
      const cls = n === wizardStep ? "step active" : n < wizardStep ? "step done" : "step";
      return `<div class="${cls}"><span class="step-num">${n < wizardStep ? "✓" : n}</span><span class="step-label">${lbl}</span></div>`;
    }).join("");

    if (wizardStep === 1) {
      if (titleEl) titleEl.textContent = "New Vendor Order";
      if (subEl) subEl.textContent = "Step 1 — choose who you are ordering from";
      const vendors = await ensureWizardVendors();
      const active = vendors.filter(v => v.is_active && !v.deleted_at).sort((a, b) => vendorLabel(a).localeCompare(vendorLabel(b)));
      const filtered = OrdersUI.filterAndRankParties(active, wizardVendorSearch);
      const selected = wizardSelectedVendor(active);
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>Select vendor</h4>
          <p>Tap a vendor card to continue. You can search if the list is long.</p>
        </div>
        <div class="vo-wiz-search-wrap">
          <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
          <input id="vo-vendor-search" class="input vo-wiz-search" type="search" placeholder="Search vendor name, alias, city, or phone…" value="${ctx.esc(wizardVendorSearch)}" oninput="VendorOrders.onVendorSearch(this.value)" autocomplete="off" />
          ${wizardVendorSearch ? `<button type="button" class="vo-wiz-search-clear" onclick="VendorOrders.onVendorSearch('')">×</button>` : ""}
        </div>
        ${selected ? `<div class="vo-wiz-selected-banner">
          <div>
            <span class="vo-wiz-selected-label">Selected</span>
            <strong>${ctx.esc(vendorLabel(selected))}</strong>
          </div>
          <button type="button" class="btn btn-ghost btn-sm" onclick="VendorOrders.pickVendor(null)">Change</button>
        </div>` : ""}
        <div class="vo-wiz-vendor-list" id="vo-vendor-list">
          ${filtered.length ? filtered.map(v => {
            const selectedCls = wizardVendorId === v.id ? " selected" : "";
            const city = v.city_name || v.city || "";
            const alias = (v.alias || "").trim();
            return `<button type="button" class="vo-wiz-vendor-card${selectedCls}" onclick="VendorOrders.pickVendor(${v.id})">
              <span class="vo-wiz-vendor-letter">${ctx.esc((v.business_name || "?").slice(0, 1).toUpperCase())}</span>
              <span class="vo-wiz-vendor-meta">
                <strong>${ctx.esc(v.business_name || "Vendor")}</strong>
                ${alias ? `<span>${ctx.esc(alias)}</span>` : ""}
                <span>${city ? ctx.esc(city) : "No city"}${v.phone ? ` · ${ctx.esc(v.phone)}` : ""}</span>
              </span>
              <span class="vo-wiz-vendor-check">${wizardVendorId === v.id ? "✓" : ""}</span>
            </button>`;
          }).join("") : HubUI.emptyState({ title: "No matches", sub: `No vendors match “${wizardVendorSearch}”.` })}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="VendorOrders.closeWizard()">Cancel</button>
        <button class="btn btn-primary" ${wizardVendorId ? "" : "disabled"} onclick="VendorOrders.wizardNext()">Next: Products →</button>`;
      setTimeout(() => document.getElementById("vo-vendor-search")?.focus(), 30);
      return;
    }

    if (wizardStep === 2) {
      if (titleEl) titleEl.textContent = "Add Products";
      if (subEl) subEl.textContent = "Step 2 — search, tick products, set quantity";
      if (!wizardProducts.length) {
        ctx.showLoading?.();
        try { wizardProducts = await ctx.api(`/vendor-orders/vendor/${wizardVendorId}/products`, {}, 0); }
        catch (e) { ctx.toast(e.message, "error"); wizardStep = 1; return renderWizard(); }
        finally { ctx.hideLoading?.(); }
      }
      const vendors = await ensureWizardVendors();
      const vendorName = vendorLabel(wizardSelectedVendor(vendors));
      const shown = filterWizardProducts();
      // Keep selected products visible even if they don't match search
      const selectedNotShown = wizardLines
        .map(l => wizardProducts.find(p => p.id === l.catalog_product_id))
        .filter(p => p && !shown.some(s => s.id === p.id));
      const list = [...selectedNotShown, ...shown];
      const cartHtml = wizardLines.length ? `
        <div class="vo-wiz-cart">
          <div class="vo-wiz-cart-head">
            <strong>In this order</strong>
            <span>${wizardLines.length} product${wizardLines.length === 1 ? "" : "s"} · ${wizardCartQty()} qty</span>
          </div>
          <div class="vo-wiz-cart-chips">
            ${wizardLines.map(l => {
              const p = wizardProducts.find(x => x.id === l.catalog_product_id);
              return `<span class="vo-wiz-cart-chip">
                <span>${ctx.esc(p ? (p.vendor_product_id ? `${p.our_product_id} / (${p.vendor_product_id})` : p.our_product_id) : l.catalog_product_id)} × ${l.quantity}</span>
                <button type="button" title="Remove" onclick="VendorOrders.toggleWizardProduct(${l.catalog_product_id}, false)">×</button>
              </span>`;
            }).join("")}
          </div>
        </div>` : "";

      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head vo-wiz-step-head-row">
          <div>
            <h4>Products from ${ctx.esc(vendorName || "vendor")}</h4>
            <p>${wizardProducts.length} product${wizardProducts.length === 1 ? "" : "s"} available — use search to find fast.</p>
          </div>
          <div class="vo-wiz-count-pill">${wizardLines.length} selected</div>
        </div>
        ${cartHtml}
        <div class="vo-wiz-search-wrap">
          <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
          <input id="vo-product-search" class="input vo-wiz-search" type="search" placeholder="Search product ID, category, series…" value="${ctx.esc(wizardProductSearch)}" oninput="VendorOrders.onProductSearch(this.value)" autocomplete="off" />
          ${wizardProductSearch ? `<button type="button" class="vo-wiz-search-clear" onclick="VendorOrders.onProductSearch('')">×</button>` : ""}
        </div>
        <div class="vo-wiz-product-meta">
          <span>Showing ${list.length} of ${wizardProducts.length}${wizardProductSearch ? " (search + selected)" : ""}</span>
          ${wizardProductSearch && !shown.length && !selectedNotShown.length ? `<button type="button" class="btn btn-ghost btn-sm" onclick="VendorOrders.onProductSearch('')">Clear search</button>` : ""}
        </div>
        <div class="vo-wiz-products" id="vo-product-list">
          ${list.length ? list.map(p => {
            const line = wizardLines.find(l => l.catalog_product_id === p.id);
            const qty = line ? line.quantity : 1;
            const checked = !!line;
            const img = (p.image_urls && p.image_urls[0]) || "";
            const alts = (p.alternatives || []).map(a =>
              `<button type="button" class="vo-alt-chip" onclick="event.stopPropagation();VendorOrders.swapProduct(${p.id},${a.catalog_product_id})">${ctx.esc(a.our_product_id)} · ${fmtPrice(a.buying_price)}</button>`
            ).join("");
            return `<div class="vo-wiz-product ${checked ? "selected" : ""}" onclick="VendorOrders.toggleWizardProduct(${p.id}, ${checked ? "false" : "true"})">
              <div class="vo-wiz-product-main">
                <input type="checkbox" ${checked ? "checked" : ""} onclick="event.stopPropagation();VendorOrders.toggleWizardProduct(${p.id}, this.checked)" />
                ${thumb(img)}
                <div class="vo-wiz-product-info">
                  <strong>${ctx.esc(p.our_product_id)}${p.vendor_product_id ? ` / (${ctx.esc(p.vendor_product_id)})` : ""}</strong>
                  <span class="vo-wiz-product-sub">${p.category ? ctx.esc(p.category) : "Product"}${p.series ? ` · ${ctx.esc(p.series)}` : ""}</span>
                  <span class="vo-wiz-product-price">${fmtPrice(p.buying_price)}</span>
                  ${alts ? `<div class="vo-alt-row" onclick="event.stopPropagation()">${alts}</div>` : ""}
                </div>
              </div>
              <div class="vo-wiz-qty" onclick="event.stopPropagation()">
                <label>Qty</label>
                <div class="vo-wiz-qty-controls">
                  <button type="button" class="vo-wiz-qty-btn" ${checked ? "" : "disabled"} onclick="VendorOrders.bumpWizardQty(${p.id}, -1)">−</button>
                  <input type="number" min="1" class="input vo-wiz-qty-input" value="${qty}" ${checked ? "" : "disabled"} onchange="VendorOrders.setWizardQty(${p.id}, this.value)" onclick="event.stopPropagation()" />
                  <button type="button" class="vo-wiz-qty-btn" ${checked ? "" : "disabled"} onclick="VendorOrders.bumpWizardQty(${p.id}, 1)">+</button>
                </div>
              </div>
            </div>`;
          }).join("") : HubUI.emptyState({
            title: !wizardProducts.length ? "No products yet" : "No matches",
            sub: !wizardProducts.length
              ? "No products for this vendor yet."
              : `No products match “${wizardProductSearch}”.`,
            ctaHtml: wizardProductSearch
              ? `<button type="button" class="btn btn-secondary" onclick="VendorOrders.onProductSearch('')">Clear search</button>`
              : "",
          })}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="VendorOrders.wizardBack()">← Back</button>
        <div class="vo-wiz-footer-mid">${wizardLines.length ? `${wizardLines.length} item${wizardLines.length === 1 ? "" : "s"} · est. ${fmtPrice(wizardCartTotal())}` : "Select at least one product"}</div>
        <button class="btn btn-primary" ${wizardLines.length ? "" : "disabled"} onclick="VendorOrders.wizardNext()">Review →</button>`;
      return;
    }

    if (wizardStep === 3) {
      if (titleEl) titleEl.textContent = "Review & Place";
      if (subEl) subEl.textContent = "Step 3 — confirm details, then place the order";
      const vendors = await ensureWizardVendors();
      const vendor = wizardSelectedVendor(vendors);
      const total = wizardCartTotal();
      bodyEl.innerHTML = `
        <div class="vo-wiz-review">
          <div class="vo-wiz-review-hero">
            <span class="vo-wiz-review-label">Ordering from</span>
            <strong>${ctx.esc(vendorLabel(vendor))}</strong>
            <span class="vo-wiz-review-stats">${wizardLines.length} product${wizardLines.length === 1 ? "" : "s"} · ${wizardCartQty()} total qty</span>
          </div>
          <div class="vo-wiz-review-table-wrap">
            <table class="data vo-wiz-review-table"><thead><tr>
              <th></th><th>Product</th><th>Qty</th><th>Buy price</th><th>Line</th>
            </tr></thead><tbody>
              ${wizardLines.map(l => {
                const p = wizardProducts.find(x => x.id === l.catalog_product_id);
                const img = p && p.image_urls && p.image_urls[0] ? p.image_urls[0] : "";
                const lineTotal = p ? (Number(p.buying_price) || 0) * l.quantity : 0;
                return `<tr>
                  <td>${thumb(img)}</td>
                  <td><strong>${ctx.esc(p ? (p.vendor_product_id ? `${p.our_product_id} / (${p.vendor_product_id})` : p.our_product_id) : "")}</strong>${p?.category ? `<div class="vo-wiz-product-sub">${ctx.esc(p.category)}</div>` : ""}</td>
                  <td><strong>${l.quantity}</strong></td>
                  <td>${p ? fmtPrice(p.buying_price) : "—"}</td>
                  <td><strong>${fmtPrice(lineTotal)}</strong></td>
                </tr>`;
              }).join("")}
            </tbody></table>
          </div>
          <div class="vo-wiz-review-total">
            <span>Estimated buy total</span>
            <strong>${fmtPrice(total)}</strong>
          </div>
          <label class="label" style="margin-top:16px;">Order date</label>
          <input type="date" class="input" style="width:100%;max-width:220px;margin-bottom:4px;" value="${ctx.esc(wizardPlacedOn || localToday())}" onchange="VendorOrders.setWizardPlacedOn(this.value)" />
          <p class="vo-wiz-review-note">Day you placed with vendor (backdate OK). Goes to <strong>Placed</strong>. Next: Receive, then Bill.</p>
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="VendorOrders.wizardBack()">← Back</button>
        <button class="btn btn-primary btn-lg" onclick="VendorOrders.placeOrder()">Place with vendor</button>`;
    }
  }

  function setWizardPlacedOn(v) { wizardPlacedOn = v || localToday(); }

  function onVendorSearch(val) {
    const prev = document.getElementById("vo-vendor-search");
    const start = prev?.selectionStart;
    wizardVendorSearch = val || "";
    renderWizard().then(() => {
      const inp = document.getElementById("vo-vendor-search");
      if (!inp) return;
      inp.focus();
      if (typeof start === "number") {
        try { inp.setSelectionRange(start, start); } catch (_) {}
      }
    });
  }

  function onProductSearch(val) {
    const prev = document.getElementById("vo-product-search");
    const start = prev?.selectionStart;
    wizardProductSearch = val || "";
    renderWizard().then(() => {
      const inp = document.getElementById("vo-product-search");
      if (!inp) return;
      inp.focus();
      if (typeof start === "number") {
        try { inp.setSelectionRange(start, start); } catch (_) {}
      }
    });
  }

  function pickVendor(id) {
    wizardVendorId = id || null;
    wizardProducts = [];
    wizardLines = [];
    wizardProductSearch = "";
    renderWizard();
  }

  function toggleWizardProduct(productId, checked) {
    if (checked) {
      if (!wizardLines.find(l => l.catalog_product_id === productId)) {
        wizardLines.push({ catalog_product_id: productId, quantity: 1 });
      }
    } else {
      wizardLines = wizardLines.filter(l => l.catalog_product_id !== productId);
    }
    renderWizard();
  }

  function setWizardQty(productId, raw) {
    const qty = Math.max(1, parseInt(String(raw || "1"), 10) || 1);
    const line = wizardLines.find(l => l.catalog_product_id === productId);
    if (line) line.quantity = qty;
    else wizardLines.push({ catalog_product_id: productId, quantity: qty });
    // soft update footer totals without full re-render of list focus
    const mid = document.querySelector(".vo-wiz-footer-mid");
    if (mid && wizardLines.length) mid.textContent = `${wizardLines.length} item${wizardLines.length === 1 ? "" : "s"} · est. ${fmtPrice(wizardCartTotal())}`;
    const pill = document.querySelector(".vo-wiz-count-pill");
    if (pill) pill.textContent = `${wizardLines.length} selected`;
  }

  function bumpWizardQty(productId, delta) {
    const line = wizardLines.find(l => l.catalog_product_id === productId);
    if (!line) {
      if (delta > 0) {
        wizardLines.push({ catalog_product_id: productId, quantity: 1 });
        renderWizard();
      }
      return;
    }
    line.quantity = Math.max(1, (Number(line.quantity) || 1) + delta);
    renderWizard();
  }

  function swapProduct(fromId, toId) {
    const idx = wizardLines.findIndex(l => l.catalog_product_id === fromId);
    const qty = idx >= 0 ? wizardLines[idx].quantity : 1;
    wizardLines = wizardLines.filter(l => l.catalog_product_id !== fromId && l.catalog_product_id !== toId);
    wizardLines.push({ catalog_product_id: toId, quantity: qty });
    renderWizard();
  }

  function wizardBack() { if (wizardStep > 1) { wizardStep--; renderWizard(); } }

  async function wizardNext() {
    if (wizardStep === 1 && !wizardVendorId) return;
    if (wizardStep === 2 && !wizardLines.length) return;
    wizardStep++;
    await renderWizard();
  }

  function openOrderPdf(url, print) {
    if (!url) return ctx.toast("PDF not ready", "error");
    const w = window.open(url, "_blank");
    if (print && w) {
      try { w.focus(); setTimeout(() => { try { w.print(); } catch (_) {} }, 600); } catch (_) {}
    }
  }

  async function fetchPlacementPdf(placementId, print) {
    if (!placementId) return;
    ctx.showLoading?.();
    try {
      const doc = await ctx.api(`/vendor-orders/placements/${placementId}/document`, {}, 0);
      if (!doc?.document_url) throw new Error("PDF not available yet");
      openOrderPdf(doc.document_url, print);
    } catch (e) { ctx.toast(e.message || "PDF not available", "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function placeOrder() {
    ctx.showLoading?.();
    try {
      const result = await ctx.api("/vendor-orders/placements", {
        method: "POST",
        body: JSON.stringify({
          vendor_id: wizardVendorId,
          lines: wizardLines,
          placed_on: wizardPlacedOn || localToday(),
        }),
      });
      ctx.invalidateCache?.("/vendor-orders");
      closeWizard();
      ctx.toast("Order placed", "success");
      const placements = result.placements || [];
      const latest = placements[placements.length - 1];
      let docUrl = null;
      if (latest?.id) {
        try {
          const doc = await ctx.api(`/vendor-orders/placements/${latest.id}/document`, {}, 0);
          docUrl = doc.document_url || null;
        } catch (_) {}
      }
      const lineRows = wizardLines.map(l => {
        const p = wizardProducts.find(x => x.id === l.catalog_product_id);
        return `<tr><td>${ctx.esc(p ? (p.vendor_product_id ? `${p.our_product_id} / (${p.vendor_product_id})` : p.our_product_id) : l.catalog_product_id)}</td><td>${l.quantity}</td><td>${p ? fmtPrice(p.buying_price) : "—"}</td></tr>`;
      }).join("");
      const pdfBtns = latest?.id
        ? (docUrl
          ? `<div class="doc-actions">
              <button class="btn btn-primary" onclick="VendorOrders.openOrderPdf('${docUrl}', true)">Print</button>
              <button class="btn btn-secondary" onclick="VendorOrders.openOrderPdf('${docUrl}', false)">Save PDF</button>
              <button class="btn btn-secondary" onclick="VendorOrders.openOrderPdf('${docUrl}', false)">View PDF</button>
            </div>`
          : `<div class="doc-actions">
              <button class="btn btn-primary" onclick="VendorOrders.fetchPlacementPdf(${latest.id}, true)">Get PDF &amp; Print</button>
              <button class="btn btn-secondary" onclick="VendorOrders.fetchPlacementPdf(${latest.id}, false)">Get PDF</button>
            </div>`)
        : "";
      ctx.openDetail?.("Order placed", `
        <div class="doc-success-banner">
          <strong>Placed with vendor</strong>
          <span>${latest?.id ? `Placement #${latest.id}` : "Saved"} · ${wizardLines.length} product${wizardLines.length === 1 ? "" : "s"}</span>
        </div>
        <p style="margin:0 0 12px;font-size:14px;color:var(--muted);">In <strong>Placed</strong>. Next: <strong>Receive</strong> when goods arrive.</p>
        <table class="data" style="font-size:13px;margin-top:12px;"><thead><tr><th>Product</th><th>Qty</th><th>Price</th></tr></thead><tbody>
          ${lineRows}
        </tbody></table>
        ${pdfBtns}`,
        `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail();Stock.openReceiveForVendor(${wizardVendorId})">Receive</button>
         <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail();VendorOrders.billVendor(${wizardVendorId})">Bill</button>
         <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail();VendorOrders.openDetail(${result.id || 0}, 'placed', ${wizardVendorId})">View</button>`, "md");
      currentBucket = "placed";
      hubMode = "browse";
      syncHubChrome();
      loadList();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openEditOpenLine(lineId) {
    if (!openOrder) return;
    const line = (openOrder.lines || []).find(l => l.id === lineId);
    if (!line) return;
    editingOpenLine = line;
    vendorProductsCache = await ctx.api(`/vendor-orders/vendor/${openOrder.vendor_id}/products`, {}, 0);
    document.getElementById("vo-edit-body").innerHTML = `
      <label class="label">Product</label>
      <select class="input" id="vo-edit-product" style="margin-bottom:12px;">
        ${vendorProductsCache.map(p => `<option value="${p.id}" ${p.id === line.catalog_product_id ? "selected" : ""}>${ctx.esc(ctx.productIdLabel(p))}</option>`).join("")}
      </select>
      <label class="label">Quantity</label>
      <input type="number" min="1" class="input" id="vo-edit-qty" value="${line.quantity}" />`;
    document.getElementById("vo-edit-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="VendorOrders.closeEdit()">Cancel</button>
      <button class="btn btn-primary" onclick="VendorOrders.saveEdit()">Save</button>`;
    document.getElementById("vo-edit-modal").classList.remove("hidden");
  }

  function closeEdit() {
    document.getElementById("vo-edit-modal")?.classList.add("hidden");
    editingOpenLine = null;
  }

  async function saveEdit() {
    if (!editingOpenLine) return;
    const productId = parseInt(document.getElementById("vo-edit-product")?.value, 10);
    const qty = Math.max(1, parseInt(document.getElementById("vo-edit-qty")?.value || "1", 10) || 1);
    ctx.showLoading?.();
    try {
      openOrder = await ctx.api(`/vendor-orders/open-lines/${editingOpenLine.id}`, {
        method: "PATCH",
        body: JSON.stringify({ catalog_product_id: productId, quantity: qty }),
      });
      ctx.invalidateCache?.("/vendor-orders");
      closeEdit();
      ctx.toast("Line updated", "success");
      renderDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function billSummaryLine(catalogProductId, pendingQty) {
    if (!detailVendorId) return;
    Stock.openReceiveForVendor(detailVendorId, { catalog_product_id: catalogProductId, quantity: pendingQty });
  }

  function receiveSummaryLine(catalogProductId, pendingQty) {
    return billSummaryLine(catalogProductId, pendingQty);
  }

  function cancelSummaryLine(catalogProductId) {
    const line = (orderSummary?.lines || []).find(l => l.catalog_product_id === catalogProductId);
    if (!line || line.total_pending <= 0) return;
    openConfirmAction({
      title: "Cancel pending qty",
      message: "Removed from Open. Recorded in Cancelled. Placed qty stays.",
      rows: [
        ["Product", ctx.esc(line.our_product_id)],
        ["Pending", String(line.total_pending)],
        ["Placed", String(line.total_placed)],
        ["Received", String(line.total_received)],
      ],
      confirmLabel: "Cancel pending",
      danger: true,
      requireReason: true,
      reasonLabel: "Cancel note",
      onConfirm: async (reason) => {
        await ctx.api(`/vendor-orders/vendor/${detailVendorId}/products/${catalogProductId}/cancel-pending`, { method: "POST", body: reasonBody(reason) });
        ctx.toast("Pending cancelled", "success");
        await reloadAfterVendorChange(detailVendorId, "summary");
      },
    });
  }

  function closeSummaryLine(catalogProductId) {
    const line = (orderSummary?.lines || []).find(l => l.catalog_product_id === catalogProductId);
    if (!line || line.total_pending <= 0) return;
    openConfirmAction({
      title: "Close pending qty",
      message: "Removes from Open and records as closed.",
      rows: [
        ["Product", ctx.esc(line.our_product_id)],
        ["Pending", String(line.total_pending)],
        ["Price", fmtPrice(line.buying_price)],
      ],
      confirmLabel: "Close",
      requireReason: true,
      reasonLabel: "Close note",
      onConfirm: async (reason) => {
        orderSummary = await ctx.api(`/vendor-orders/vendor/${detailVendorId}/products/${catalogProductId}/close-pending`, { method: "POST", body: reasonBody(reason) });
        ctx.invalidateCache?.("/vendor-orders");
        ctx.toast("Pending closed", "success");
        renderDetail();
      },
    });
  }


  async function toggleClosedRow(lineId) {
    expandedClosedId = expandedClosedId === lineId ? null : lineId;
    renderDetail();
    if (expandedClosedId) await loadClosedRowExpand(lineId);
  }

  async function loadClosedRowExpand(lineId) {
    const wrap = document.getElementById(`vo-closed-drill-${lineId}`);
    const line = (closedLines || []).find(l => l.id === lineId);
    if (!wrap || !line) return;
    let extra = "";
    if (line.source === "billed" && line.bill_number) {
      extra = `<p style="font-size:12px;color:var(--muted);margin:8px 0 0;">Closed from billed shipment — bill ${ctx.esc(line.bill_number)}</p>`;
    }
    wrap.innerHTML = `
      ${line.close_reason ? noteChip(line.close_reason, "close") : ""}
      <div class="vo-section-label">Closed line — ${ctx.esc(line.our_product_id)}</div>
      ${confirmDetailsTable([
        ["Product", ctx.esc(line.our_product_id)],
        ["Quantity", String(line.quantity)],
        ["Price", fmtPrice(line.buying_price)],
        ["Source", ctx.esc(line.source)],
        ["Bill", ctx.esc(line.bill_number || "—")],
        ["Close note", ctx.esc(line.close_reason || "—")],
        ["Closed", line.closed_at ? new Date(line.closed_at).toLocaleString() : "—"],
      ])}
      ${extra}`;
  }

  async function openPlacementDoc(placementId) {
    try {
      const doc = await ctx.api(`/vendor-orders/placements/${placementId}/document`, {}, 0);
      if (doc.document_url) window.open(doc.document_url, "_blank");
      else ctx.toast("Document not available", "error");
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function openReceiptDoc(receiptId) {
    if (!receiptId) return;
    ctx.showLoading?.();
    try {
      const doc = await ctx.api(`/stock/receipts/${receiptId}/document`, {}, 0);
      const url = doc?.document_url;
      if (!url) throw new Error("Receipt PDF not available yet");
      const safe = ctx.esc(url);
      OrderMenus.openConfirm({
        title: "Bill receipt",
        message: "Print or download this goods receipt.",
        detailsHtml: `<div class="doc-actions">
          <button type="button" class="btn btn-primary" onclick="Stock.openReceiptPdf('${safe}', true)">Print</button>
          <button type="button" class="btn btn-secondary" onclick="Stock.openReceiptPdf('${safe}', false)">Download / View</button>
        </div>`,
        confirmLabel: "Close",
        onConfirm: async () => {},
        ctx,
      });
    } catch (e) { ctx.toast(e.message || "PDF not available", "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function _refreshAfterPlacedLineEdit(orderId) {
    ctx.invalidateCache?.("/vendor-orders");
    if (hubExpandedVendorId) {
      const vid = typeof hubExpandedVendorId === "number" ? hubExpandedVendorId : null;
      if (vid) {
        hubExpandCache[`placed-${vid}`] = await ctx.api(`/vendor-orders/${orderId}?view=default`, {}, 0);
      } else if (orderId) {
        const detail = await ctx.api(`/vendor-orders/${orderId}?view=default`, {}, 0);
        hubExpandCache[`placed-${detail.vendor_id}`] = detail;
      }
    }
    await loadList();
    if (detailVendorId) await openDetail(orderId || 0, "placed", detailVendorId);
  }

  async function editPlacedLine(lineId, currentQty, orderId) {
    const raw = prompt("Edit placed quantity:", String(currentQty ?? 1));
    if (raw == null) return;
    const qty = Math.max(1, parseInt(String(raw), 10) || 0);
    if (!qty) return ctx.toast("Enter a valid quantity", "error");
    ctx.showLoading?.();
    try {
      await ctx.api(`/vendor-orders/lines/${lineId}`, {
        method: "PATCH",
        body: JSON.stringify({ quantity: qty }),
      });
      ctx.toast("Placed line updated", "success");
      await _refreshAfterPlacedLineEdit(orderId);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function deletePlacedLine(lineId, orderId) {
    if (!confirm("Remove this product line from the placed order?")) return;
    ctx.showLoading?.();
    try {
      await ctx.api(`/vendor-orders/lines/${lineId}`, { method: "DELETE" });
      ctx.toast("Line removed", "success");
      await _refreshAfterPlacedLineEdit(orderId);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function receiveVendor(vendorId) {
    if (!vendorId) return;
    Stock.openReceiveForVendor(vendorId);
  }

  function billVendor(vendorId) {
    if (!vendorId) return;
    Stock.openBillForVendor(vendorId);
  }

  function billOpenLine(catalogProductId, qty) {
    if (!detailVendorId) return;
    Stock.openBillForVendor(detailVendorId, { catalog_product_id: catalogProductId, quantity: qty });
  }

  function receiveOrder() {
    if (!detailVendorId) return;
    Stock.openReceiveForVendor(detailVendorId);
  }

  function billOrder() {
    if (!detailVendorId) return;
    Stock.openBillForVendor(detailVendorId);
  }

  function _detailVendorId() { return detailVendorId; }

  return {
    init, showHub, setBucket, setHubMode, setQueueFilter, setHubSearch, loadList, openDetail, switchDetailBucket, refreshIfOpen,
    toggleSummaryRow, togglePlacementRow, toggleClosedRow,
    showCreateMenu, showCreateMenuFromVendor, runHubAction, runDetailAction, openCloseBatch,
    openWizard, closeWizard, primeVendors, pickVendor, toggleWizardProduct, setWizardQty, bumpWizardQty, swapProduct,
    onVendorSearch, onProductSearch,
    billOrder, receiveOrder, billVendor, receiveVendor, billOpenLine, editPlacedLine, deletePlacedLine, closePlacedLine, cancelPlacedLine,
    closeVendorOpen, cancelVendorOpen, closeAllOpenLines, cancelAllOpenLines,
    billSummaryLine, cancelSummaryLine, closeSummaryLine,
    wizardBack, wizardNext, placeOrder, setWizardPlacedOn, openOrderPdf, fetchPlacementPdf,
    openEditOpenLine, closeEdit, saveEdit,
    cancelPlacement, addDebitNote, openDebitNotes, closeOpenLine, cancelOpenLine, closeBilledPlacement,
    openPlacementDoc, openReceiptDoc,
    toggleHubVendor, toggleHubPlacement, toggleHubClosedBill,
    _detailVendorId,
  };
})();
