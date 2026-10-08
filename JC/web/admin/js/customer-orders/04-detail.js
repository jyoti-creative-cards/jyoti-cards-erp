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
      const city = o.city_name ? ` <span style="color:var(--muted);font-weight:600;">· ${ctx.esc(o.city_name)}</span>` : "";
      title.innerHTML = pn + ctx.esc(o.customer_name) + city + m1 + m2 + pt;
    }
    if (sub) {
      sub.textContent = currentBucket === "received" ? "Review order, edit if needed, then Confirm →"
        : currentBucket === "open" ? "Goods being picked — Create Bill when ready"
          : currentBucket === "billed" ? "Bill created — Dispatch or Collect payment, then Close"
            : currentBucket === "closed" ? "Done"
              : "Cancelled";
    }
    const canWrite = !!ctx.canWrite?.("customer_orders");
    const canMoney = !!ctx.isAdmin?.() || !!ctx.canWrite?.("ar") || !!ctx.canWrite?.("finance");

    if (currentBucket === "open") {
      const lines = currentOrder.open_lines || [];
      el.innerHTML = `
        ${cashWarningHtml(currentOrder)}
        ${canWrite && lines.length ? `<div class="ui-toolbar" style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary btn-sm" onclick="CustomerOrders.processOrder()">Create Bill</button>
          <button class="btn btn-secondary btn-sm" onclick="CustomerOrders.openEditFromOpen()">Edit order</button>
          <button class="btn btn-danger btn-sm" onclick="CustomerOrders.cancelCustomerOpen(${detailCustomerId})">Cancel entire order</button>
        </div>` : ""}
        <div class="ord-hub-list">${lines.length ? lines.map(line => HubUI.partyCard({
          title: ctx.esc(line.our_product_id) + (line.marking ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;">${ctx.esc(line.marking)}</span>` : ""),
          titleIsHtml: true,
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
            <td>${ctx.esc(ln.our_product_id)}${ln.marking ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;">${ctx.esc(ln.marking)}</span>` : ""}${addonsUnderHtml(ln.addons, ln.quantity_shipped)}</td>
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
        if (ctx.isAdmin?.()) {
          more.push({ label: "Void (recycle bin)", onclick: `CustomerOrders.voidBill(${b.id})`, danger: true });
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
          title: b.display_name || `Bill ${b.bill_number}`,
          meta: `${fmtPrice(b.grand_total)} · ${ctx.fmtDay(b.display_date || b.bill_date)}${modeLbl ? ` · ${modeLbl}` : ""}${chargeBit}${receiptBit}${(b.additional_charges || []).filter(c => Number(c.amount) > 0).map(c => ` · ${ctx.esc(c.name)} ${fmtPrice(c.amount)}`).join("")}${b.status && b.status !== "open" ? ` · ${ctx.esc(b.status)}` : ""}${b.narration ? `<div style="margin-top:2px;">${ctx.esc(b.narration)}</div>` : ""}`,
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
          <button class="btn btn-danger btn-sm" onclick="CustomerOrders.cancelEntireReceived(${detailCustomerId})">Cancel entire order</button>
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
            <td>${ctx.esc(ln.our_product_id)}${ln.marking ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;">${ctx.esc(ln.marking)}</span>` : ""}${addonsUnderHtml(ln.addons, ln.quantity)}</td>
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
        if (ctx.isAdmin?.()) more.push({ label: "Void (recycle bin)", onclick: `CustomerOrders.voidPlacement(${p.id})`, danger: true });
        return HubUI.partyCard({
          title: p.display_name || `Order #${p.id}`,
          meta: `${ctx.fmtDay(p.display_date)}${p.customer_notes ? ` · ${ctx.esc(p.customer_notes)}` : ""}${p.cancel_reason ? `<div style="color:var(--danger);margin-top:2px;">Cancelled: ${ctx.esc(p.cancel_reason)}</div>` : ""}`,
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
        title: p.display_name || `Placement #${p.id}`,
        meta: `${ctx.fmtDay(p.display_date)}${p.customer_notes ? ` · ${ctx.esc(p.customer_notes)}` : ""}${p.cancel_reason ? `<div style="color:var(--danger);margin-top:2px;">Cancelled: ${ctx.esc(p.cancel_reason)}</div>` : ""}`,
        pillHtml: currentBucket === "cancelled" || p.cancel_reason || p.status === "cancelled"
          ? HubUI.pill("Cancelled", "danger")
          : HubUI.pill(currentBucket === "closed" || p.status === "closed" ? "Closed" : "History", "muted"),
        moreItems: ctx.isAdmin?.() ? [{ label: "Void (recycle bin)", onclick: `CustomerOrders.voidPlacement(${p.id})`, danger: true }] : [],
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
    try {
      offlineLines = active.map(ln => {
        const stock = offlineSearchResults.find(x => x.catalog_product_id === ln.catalog_product_id);
        return {
          catalog_product_id: ln.catalog_product_id,
          our_product_id: ln.our_product_id,
          quantity: ln.quantity,
          min_qty: Number(ln.quantity_billed) || 0,
          selling_price: ln.unit_price ?? stock?.selling_price,
          quantity_on_hand: stock?.quantity_on_hand,
          priced_addons: (ln.addons || []).filter(a => Number(a.selling_price) > 0).map(a => ({
            addon_product_id: a.addon_product_id,
            name: a.name || a.our_product_id,
            our_product_id: a.our_product_id,
            selling_price: a.selling_price,
            quantity: a.quantity || 1,
          })),
          skip_addon_ids: [],
        };
      });
      document.getElementById("co-offline-wizard")?.classList.remove("hidden");
      renderOfflineWizard();
    } catch (e) { ctx.toast(e.message, "error"); offlineEditPlacementId = null; }
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
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/stock");
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
        ctx.invalidateCache?.("/stock");
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
      promptReason(hasBilled ? "Cancel remaining" : "Cancel entire order", async (reason) => {
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
          ctx.invalidateCache?.("/stock");
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

  /** New (received) orders: one click cancels every unbilled placement, not line by line. */
  async function cancelEntireReceived(customerId) {
    const cid = customerId || detailCustomerId;
    if (!cid) return ctx.toast("No customer", "error");
    ctx.showLoading?.();
    try {
      const detail = await ctx.api(`/customer-orders/customer/${cid}?bucket=received`, {}, 0);
      const placements = (detail.placements || []).filter(p =>
        (p.lines || []).some(ln => ln.status === "active" && Number(ln.quantity) > Number(ln.quantity_billed || 0))
      );
      if (!placements.length) return ctx.toast("Nothing open to cancel", "error");
      const hasBilled = placements.some(p => (p.lines || []).some(ln => Number(ln.quantity_billed) > 0));
      promptReason(hasBilled ? "Cancel remaining on this order" : "Cancel entire order", async (reason) => {
        ctx.showLoading?.();
        let ok = 0;
        let failed = 0;
        try {
          for (const p of placements) {
            try {
              await ctx.api(`/customer-orders/placements/${p.id}/cancel`, {
                method: "POST",
                body: JSON.stringify({ reason }),
              });
              ok += 1;
            } catch (_) { failed += 1; }
          }
          if (failed) ctx.toast(`Cancelled ${ok}, failed ${failed}`, "error");
          else ctx.toast(hasBilled ? "Remaining cancelled — billed kept" : "Order cancelled", "success");
          ctx.invalidateCache?.("/customer-orders");
          ctx.invalidateCache?.("/stock");
          detailCustomerId = cid;
          await openDetail(cid, hasBilled ? "received" : "cancelled");
          loadList();
        } catch (e) { ctx.toast(e.message, "error"); }
        finally { ctx.hideLoading?.(); }
      });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
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
    // Same fix as voidBill below: promptReason's modal already states the
    // consequence and has its own Confirm/Cancel — a second native confirm() after
    // it was a redundant double dialog that silently swallowed the reason on Cancel.
    promptReason("Cancel bill — stock is released back to available. This qty drops off the order; place a fresh order to sell it again. Freight cleared.", async (reason) => {
      ctx.showLoading?.();
      try {
        await ctx.api(`/customer-orders/bills/${billId}/cancel`, {
          method: "POST",
          body: JSON.stringify({ reason }),
        });
        ctx.toast("Bill cancelled — stock released", "success");
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/freight-agents");
        ctx.invalidateCache?.("/stock");
        await openDetail(detailCustomerId, "open");
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
  }

  function voidBill(billId) {
    // The promptReason modal's title already states the consequence and has its own
    // Confirm/Cancel buttons — a second native confirm() after it was a redundant
    // double dialog.
    promptReason("Void bill — Admin-only, moves to recycle bin, restorable later. Cancels first if not already cancelled.", async (reason) => {
      ctx.showLoading?.();
      try {
        await ctx.api(`/customer-orders/bills/${billId}/void`, { method: "POST", body: JSON.stringify({ reason }) });
        ctx.toast("Bill voided — moved to recycle bin", "success");
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/accounts-receivable");
        ctx.invalidateCache?.("/stock");
        await openDetail(detailCustomerId, currentBucket);
        loadList();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
  }

  function voidPlacement(placementId) {
    promptReason("Void order — Admin-only, moves to recycle bin, restorable later. Only releases unbilled qty if this order hasn't been confirmed yet (New bucket) — once confirmed, voiding hides it but leaves its reserved stock/open balance untouched.", async (reason) => {
      ctx.showLoading?.();
      try {
        await ctx.api(`/customer-orders/placements/${placementId}/void`, { method: "POST", body: JSON.stringify({ reason }) });
        ctx.toast("Order voided — moved to recycle bin", "success");
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/stock");
        await openDetail(detailCustomerId, currentBucket);
        loadList();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
  }

