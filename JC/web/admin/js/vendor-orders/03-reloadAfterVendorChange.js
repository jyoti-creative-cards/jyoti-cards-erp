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
            quantity_remaining: b.quantity_remaining,
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
    try {
      await _loadPlacementExpandInner(wrap, placement, placementId);
    } catch (e) {
      // Anything unexpected here previously left the row stuck on "Loading…" forever.
      wrap.innerHTML = `<p style="color:var(--danger);font-size:13px;">Failed to load — ${ctx.esc(e.message || "unknown error")}
        <a href="#" onclick="event.preventDefault();VendorOrders.loadPlacementExpand(${placementId})">retry</a></p>`;
    }
  }

  async function _loadPlacementExpandInner(wrap, placement, placementId) {
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
        const receipt = await ctx.api(`/stock/receipts/${placement.receipt_id}`, {}, 0);
        let notes = [];
        let notesFailed = false;
        try {
          notes = await ctx.api(`/debit-notes?receipt_id=${placement.receipt_id}`, {}, 0);
        } catch (_) {
          notesFailed = true; // don't conflate a failed fetch with "confirmed no debit notes"
        }
        if (!(placement.bill_amount != null || placement.net_payable != null)) {
          html += `<div class="vo-money-block">
            ${ctx.reviewRow ? "" : ""}
            <div><span>Bill amount</span><strong>${fmtPrice(receipt.bill_amount)}</strong></div>
            ${receipt.additional_charges ? `<div><span>Additional charges</span><strong>${fmtPrice(receipt.additional_charges)}</strong></div>` : ""}
            ${receipt.debit_note_total && Number(receipt.debit_note_total) ? `<div><span>Debit notes</span><strong>${fmtPrice(receipt.debit_note_total)}</strong></div>` : ""}
            <div class="is-total"><span>Net payable</span><strong>${fmtPrice(receipt.net_payable)}</strong></div>
          </div>`;
        }
        if (notesFailed) {
          html += `<p style="color:var(--danger);font-size:13px;margin:12px 0 0;">Couldn't load debit notes —
            <a href="#" onclick="event.preventDefault();VendorOrders.loadPlacementExpand(${placementId})">retry</a></p>`;
        } else if (notes.length) {
          const canDn = ctx.canWrite?.("vendor_orders");
          html += `<div class="vo-section-label">Debit notes</div>
            <table class="data vo-hub-table"><thead><tr><th>Note</th><th>Effect</th>${canDn ? "<th></th>" : ""}</tr></thead><tbody>
              ${notes.map(n => {
                const lbl = n.note_type === "item" ? `${ctx.esc(n.our_product_id || "")} × ${n.quantity}${n.notes ? ` — ${ctx.esc(n.notes)}` : ""}` : `Value adjustment${n.notes ? ` — ${ctx.esc(n.notes)}` : ""}`;
                const effect = n.payable_effect != null ? n.payable_effect : (n.note_type === "item" ? -Number(n.amount) : Number(n.amount));
                const actions = canDn
                  ? `<td style="white-space:nowrap;">
                      <button type="button" class="btn btn-ghost btn-sm" onclick="event.stopPropagation();VendorOrders.editDebitNote(${placement.receipt_id},${n.id})">Edit</button>
                      <button type="button" class="btn btn-ghost btn-sm" onclick="event.stopPropagation();VendorOrders.voidDebitNote(${placement.receipt_id},${n.id})">Void</button>
                    </td>`
                  : "";
                return `<tr><td>${lbl}</td><td>${fmtPrice(effect)}</td>${actions}</tr>`;
              }).join("")}
            </tbody></table>`;
        } else if (ctx.canWrite?.("vendor_orders") && placement.receipt_id) {
          html += `<p class="vo-muted" style="margin:12px 0 0;">No debit notes yet.</p>`;
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
    ctx.invalidateCache?.("/stock");
    if (isDetailVisible() && detailVendorId === vendorId) {
      await openDetail(0, currentBucket === "received" ? "billed" : currentBucket, vendorId);
    }
    const hubEl = document.getElementById("orders-hub");
    const hubVisible = hubEl && !hubEl.classList.contains("hidden");
    if (hubVisible) {
      hubExpandedVendorId = null;
      hubExpandedPlacementId = null;
      await loadList();
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
        ["Bill", ctx.esc(placement.display_name || placement.bill_number || `Shipment #${placementId}`)],
        ["Placed", ctx.fmtDay(placement.display_date || placement.value_date || placement.created_at)],
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

  async function editDebitNote(receiptId, noteId) {
    if (!receiptId || !noteId) return;
    await openDebitNotes(receiptId);
    if (typeof DebitNotes !== "undefined" && DebitNotes.editFromList) {
      DebitNotes.editFromList(noteId);
    }
  }

  async function voidDebitNote(receiptId, noteId) {
    if (!receiptId || !noteId) return;
    await openDebitNotes(receiptId);
    if (typeof DebitNotes !== "undefined" && DebitNotes.voidFromList) {
      await DebitNotes.voidFromList(noteId);
    }
  }

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
        ["Placed", placement ? ctx.fmtDay(placement.display_date || placement.value_date || placement.created_at) : "—"],
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
      let score = 0;
      if (id === q || vid === q) score = 100;
      else if (id.startsWith(q) || vid.startsWith(q)) score = 80;
      else if (id.includes(q) || vid.includes(q)) score = 40;
      else if (cat.startsWith(q)) score = 30;
      else if (cat.includes(q)) score = 10;
      else continue;
      scored.push({ p, score, id });
    }
    scored.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
    return scored.map(x => x.p);
  }

  // buying_price comes back as the literal string "—" (not a number, not null) when the
  // viewer lacks costs.read (see cost_visibility.hide_cost). `Number("—") || 0` silently
  // coerces that to a real 0, so a redacted price used to render as a plausible-looking
  // "est. ₹0" total instead of an honest "unknown" — actively misleading, not just blank.
  function priceOrNull(raw) {
    if (raw == null || raw === "") return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }

