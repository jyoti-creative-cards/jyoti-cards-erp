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
              <div class="vo-hub-title" style="font-size:14px;">${ctx.esc(p.display_name || `Placement #${p.id}`)} · ${ctx.fmtDay(p.display_date)}</div>
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
      } else if (bucket === "open-bill" || bucket === "received") {
        const recv = await ctx.api(`/stock/vendor-order/${vendorId}/received`, {}, 0);
        hubExpandCache[key] = {
          vendor_id: vendorId,
          vendor_label: recv.vendor_label,
          receipts: recv.receipts || [],
        };
      } else if (bucket === "closed") {
        hubExpandCache[key] = { lines: await ctx.api(`/vendor-orders/vendor/${vendorId}/closed`, {}, 0) };
      } else if (bucket === "billed") {
        // VendorOrder.bucket never becomes "billed" (one-receipt-per-bill model) — this
        // sources straight from StockReceipt, matching the card's own totals.
        hubExpandCache[key] = await ctx.api(`/stock/vendor-order/${vendorId}/billed`, {}, 0);
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
      } else if (b === "billed") {
        // VendorOrder.bucket never becomes "billed" (one-receipt-per-bill model), so
        // there's no real order id to look up here — always source from StockReceipt.
        currentOrder = await ctx.api(`/stock/vendor-order/${detailVendorId}/billed`, {}, 0);
      } else if (b === "received") {
        // Same story for "received" (unbilled) — sourced from the dedicated
        // per-line detail endpoint (StockReceipt-backed) instead of a VendorOrder id
        // that will never exist for this bucket either.
        currentOrder = await ctx.api(`/stock/vendor-order/${detailVendorId}/received-detail`, {}, 0);
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
            title: p.display_name || (p.order_receipt_number ? `Receipt ${p.order_receipt_number}` : `Receive #${p.id}`),
            meta: `${lines.length} products · ${p.total_quantity || 0} qty · ${ctx.fmtDay(p.display_date)}${p.notes ? ` · ${ctx.esc(p.notes)}` : ""}`,
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
            title: p.display_name || p.bill_number || `Bill #${p.id}`,
            meta: `${placementBadge(p.color_index)} ${lines.length} products · ${totalRecv} received · ${ctx.fmtDay(p.display_date)}${p.net_payable != null ? ` · Net ${fmtPrice(p.net_payable)}` : ""}${closed && p.close_reason ? noteChip(p.close_reason, "close") : ""}`,
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
          title: `${isCancelled ? "Cancelled" : "Placement"} · ${ctx.fmtDay(p.display_date)}`,
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

