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
          <td><strong>${ctx.esc(l.our_product_id)}</strong>${l.marking ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;">${ctx.esc(l.marking)}</span>` : ""}</td>
          <td><strong>${l.quantity_open}</strong></td>
          <td>${fmtPrice(l.unit_price)}</td>
        </tr>`;
      }).join("")}
    </tbody></table>
    ${canWrite ? `<div class="vo-hub-expand-actions">
      <button class="btn btn-primary" onclick="CustomerOrders.processFromHub(${customerId}, 'open')">Create Bill</button>
      <button class="btn btn-danger" onclick="CustomerOrders.cancelCustomerOpen(${customerId})">Cancel entire order</button>
    </div>` : ""}`;
  }

  function renderOrderCard(o, canWrite) {
    const openQty = o.total_quantity || 0;
    const bucket = detailBucketFor(o);
    const src = sourceMeta(o.sources);
    const canMoney = !!ctx.isAdmin?.() || !!ctx.canWrite?.("ar") || !!ctx.canWrite?.("finance");
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
    if (canWrite && openQty > 0 && currentBucket === "open") {
      more.push({ label: "Cancel entire order", onclick: `CustomerOrders.cancelCustomerOpen(${o.customer_id})`, danger: true });
    }
    if (canWrite && currentBucket === "received") {
      more.push({ label: "Cancel entire order", onclick: `CustomerOrders.cancelEntireReceived(${o.customer_id})`, danger: true });
    }

    // Party name HTML
    const _m1Upper = (o.marker_1 || "").toUpperCase();
    const nameHtml = (o.party_number ? `<span style="color:var(--muted);font-size:11px;font-weight:600;">#${o.party_number}</span> ` : "")
      + ctx.esc(o.customer_name)
      + (o.marker_1 ? ` <span class="badge badge-blue" style="font-size:9px;padding:1px 4px;">${ctx.esc(o.marker_1)}</span>` : "")
      + (o.marker_2 ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;">${ctx.esc(o.marker_2)}</span>` : "")
      + (o.payment_type === "CASH" && !_m1Upper.includes("CASH") ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;">CASH</span>` : "");

    const when = o.display_date || o.updated_at;
    const timeStr = when ? (ctx.fmtDay?.(when) || "") : "";
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

