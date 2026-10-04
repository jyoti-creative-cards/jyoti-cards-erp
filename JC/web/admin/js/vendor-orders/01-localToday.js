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
      ctx.invalidateCache?.("/vendor-orders");
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

  function renderOpenBillExpand(detail, canWrite) {
    const receipts = detail.receipts || [];
    if (!receipts.length) return `<p class="vo-muted" style="margin:0;">Nothing to bill.</p>`;
    return `<table class="data vo-hub-table"><thead><tr>
      <th>Receipt</th><th>Received</th><th>Lines</th><th>Qty</th><th>Expected amount</th>
    </tr></thead><tbody>
      ${receipts.map(r => `<tr>
        <td><strong>${ctx.esc(r.order_receipt_number || `#${r.receipt_id}`)}</strong></td>
        <td class="vo-muted">${ctx.fmtDate(r.display_date || r.value_date || r.created_at) || "—"}</td>
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
        ? `<div id="vo-hub-expand-${o.vendor_id}">${cache ? renderOpenBillExpand(cache, canWrite) : `<p class="vo-muted" style="margin:0;padding:8px 0;">Loading…</p>`}</div>`
        : "",
    });
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
              <div class="vo-hub-title" style="font-size:14px;">${ctx.esc(p.display_name || `Placement #${p.id}`)} · ${ctx.fmtDate(p.display_date)}</div>
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
          lines.push({ ...b, our_product_id: agg.our_product_id, image_urls: agg.image_urls, buying_price: agg.buying_price, marking: agg.marking });
        }
      }
    }
    if (!lines.length) return `<p class="vo-muted" style="margin:0;">No lines.</p>`;
    return `<table class="data vo-hub-table"><thead><tr><th></th><th>Product</th><th>Qty</th><th>Price</th>${canEdit ? "<th></th>" : ""}</tr></thead><tbody>
      ${lines.map(l => `<tr>
        <td>${thumb((l.image_urls && l.image_urls[0]) || "", "vo-thumb-sm")}</td>
        <td><strong>${ctx.esc(ctx.productIdLabel(l))}</strong>${l.marking ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;">${ctx.esc(l.marking)}</span>` : ""}</td>
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
              <div class="vo-hub-title" style="font-size:14px;">${ctx.esc(p.display_name || p.bill_number || `Bill #${p.id}`)}${closed ? ` <span class="vo-pill-muted">Closed</span>` : ""}</div>
              <div class="vo-hub-meta">${p.line_count} lines · ${ctx.fmtDate(p.display_date)}
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
          lines.push({ ...b, our_product_id: agg.our_product_id, image_urls: agg.image_urls, marking: agg.marking });
        }
      }
    }
    const showAmt = lines.some(l => l.billed_amount != null && Number(l.billed_amount) !== 0);
    let html = `<table class="data vo-hub-table"><thead><tr><th></th><th>Product</th><th>Recv</th><th>Billed qty</th>${showAmt ? "<th>Amount</th>" : ""}</tr></thead><tbody>
      ${lines.map(l => `<tr>
        <td>${thumb((l.image_urls && l.image_urls[0]) || "", "vo-thumb-sm")}</td>
        <td><strong>${ctx.esc(ctx.productIdLabel(l))}</strong>${l.marking ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;">${ctx.esc(l.marking)}</span>` : ""}</td>
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

