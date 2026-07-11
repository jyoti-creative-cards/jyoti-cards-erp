/** Customer orders — received / open / billed / cancelled / closed */
const CustomerOrders = (() => {
  let ctx = {};
  let orders = [];
  let currentOrder = null;
  let currentBucket = "summary";
  let detailCustomerId = null;

  let processStep = 1;
  let processContext = null;
  let processLines = [];
  let useOverallDiscount = false;
  let overallDiscount = "";
  let gstEnabled = false;
  let gstRate = "18";
  let freightAgents = [];
  let billSeries = [];
  let freightAgentId = "";
  let freightCharges = "";
  let packagingCharges = "";
  let additionalCharges = [{ name: "", amount: "" }];
  let billSeriesId = "";
  let narration = "";
  let previewTotals = null;
  let processBusy = false;

  const BUCKETS = ["summary", "received", "open", "billed", "cancelled", "closed"];
  const BUCKET_LABELS = {
    summary: "Order Summary",
    received: "Received",
    open: "Open",
    billed: "Billed",
    cancelled: "Cancelled",
    closed: "Closed",
  };
  const ACTION_LABELS = { received: "Process Order", open: "Process Order", billed: "Close Order" };

  let offlineStep = 1;
  let offlineCustomerId = null;
  let offlineCustomerName = "";
  let offlineLines = [];
  let offlineSearchQuery = "";
  let offlineSearchResults = [];
  let offlineSearchTimer = null;
  let offlineUseOverallDiscount = false;
  let offlineOverallDiscount = "";
  let offlineGstEnabled = false;
  let offlineGstRate = "18";
  let offlineAdditionalCharges = [{ name: "", amount: "" }];
  let offlineBillSeries = [];
  let offlineBillSeriesId = "";
  let offlinePreview = null;
  let offlineBusy = false;

  function init(context) { ctx = context; }

  function syncBucketSelect(bucket, prefix) {
    // legacy no-op — tabs replaced selects
  }

  function updateActionButtons(view) {
    const hubBtn = document.getElementById("co-hub-action-btn");
    const detailBtn = document.getElementById("co-detail-action-btn");
    const label = ACTION_LABELS[currentBucket];
    [hubBtn, detailBtn].forEach(btn => {
      if (!btn) return;
      const show = !!label && ctx.canWrite?.("vendor_orders");
      const isDetail = view === "detail";
      btn.classList.toggle("hidden", !show || (isDetail ? btn !== detailBtn : btn !== hubBtn));
      if (show && ((isDetail && btn === detailBtn) || (!isDetail && btn === hubBtn))) btn.textContent = label;
    });
    if (view === "detail") hubBtn?.classList.add("hidden");
    else detailBtn?.classList.add("hidden");
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

  function updateTabs(active, barId) {
    const bar = document.getElementById(barId || "co-bucket-bar");
    bar?.querySelectorAll(".prod-tab").forEach(btn => {
      btn.classList.toggle("active", btn.getAttribute("data-bucket") === active);
    });
  }

  function setBucket(bucket) {
    currentBucket = bucket;
    updateTabs(bucket, "co-bucket-bar");
    updateActionButtons("hub");
    loadList();
  }

  async function loadList() {
    ctx.showLoading?.();
    try {
      orders = await ctx.api(`/customer-orders?bucket=${currentBucket}`, {}, 0);
      renderList();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function showHub() {
    document.getElementById("co-hub")?.classList.remove("hidden");
    document.getElementById("co-detail")?.classList.add("hidden");
    currentOrder = null;
    detailCustomerId = null;
    setBucket(currentBucket);
  }

  function renderList() {
    const el = document.getElementById("customer-orders-list");
    if (!el) return;
    if (!orders.length) {
      el.innerHTML = `<div class="empty-state"><p>No ${BUCKET_LABELS[currentBucket] || currentBucket} customer orders.</p></div>`;
      return;
    }
    const qtyLabel = currentBucket === "open" || currentBucket === "summary" ? "Open qty" : "Qty";
    el.innerHTML = orders.map(o => `
      <div class="co-hub-card">
        <div class="co-hub-row" onclick="CustomerOrders.openDetail(${o.customer_id}, '${currentBucket === "summary" ? "received" : currentBucket}')">
          <div>
            <div class="co-hub-title">${ctx.esc(o.customer_name)}</div>
            <div class="co-hub-meta">${o.placement_count} placements · ${o.line_count} lines · <strong>${o.total_quantity}</strong> ${qtyLabel.toLowerCase()}</div>
          </div>
          <div style="text-align:right;">
            <div style="font-size:12px;color:var(--muted);">${new Date(o.updated_at).toLocaleString()}</div>
            <button class="btn btn-secondary btn-sm" style="margin-top:6px;" onclick="event.stopPropagation();CustomerOrders.openDetail(${o.customer_id}, '${currentBucket === "summary" ? "received" : currentBucket}')">Open</button>
          </div>
        </div>
      </div>`).join("");
  }

  async function openDetail(customerId, bucket) {
    ctx.showLoading?.();
    try {
      currentBucket = bucket;
      detailCustomerId = customerId;
      currentOrder = await ctx.api(`/customer-orders/customer/${customerId}?bucket=${bucket}`, {}, 0);
      document.getElementById("co-hub")?.classList.add("hidden");
      document.getElementById("co-detail")?.classList.remove("hidden");
      updateTabs(bucket === "received" ? "received" : bucket, "co-detail-bucket-bar");
      updateActionButtons("detail");
      renderDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function switchBucket(bucket) {
    if (!detailCustomerId) return;
    updateTabs(bucket, "co-detail-bucket-bar");
    const effective = bucket === "summary" ? "received" : bucket;
    await openDetail(detailCustomerId, effective);
    if (bucket === "summary") updateTabs("summary", "co-detail-bucket-bar");
  }

  function renderDetail() {
    const el = document.getElementById("co-detail-body");
    const title = document.getElementById("co-detail-title");
    const sub = document.getElementById("co-detail-sub");
    if (!el || !currentOrder) return;
    if (title) title.textContent = currentOrder.customer_name;
    if (sub) {
      sub.textContent = currentBucket === "received" ? "All customer placements"
        : currentBucket === "open" ? "Pending to ship — click Process to bill"
          : currentBucket === "billed" ? "Shipped and billed"
            : currentBucket === "closed" ? "Manually closed"
              : "Cancelled orders";
    }

    const processBtn = document.getElementById("co-process-btn");
    if (processBtn) processBtn.classList.add("hidden");

    if (currentBucket === "open") {
      el.innerHTML = `
        <div class="card table-wrap">
          <table class="data"><thead><tr>
            <th></th><th>Product</th><th>Received</th><th>Open</th><th>Billed</th><th>Rate</th><th></th>
          </tr></thead><tbody>
            ${(currentOrder.open_lines || []).map(line => `
              <tr>
                <td>${thumb((line.image_urls || [])[0])}</td>
                <td><strong>${ctx.esc(line.our_product_id)}</strong></td>
                <td>${line.quantity_received}</td>
                <td><strong>${line.quantity_open}</strong></td>
                <td>${line.quantity_billed}</td>
                <td>${fmtPrice(line.unit_price)}</td>
                <td><button class="btn btn-secondary btn-sm" onclick="CustomerOrders.cancelOpenLine(${line.id})">Cancel</button></td>
              </tr>`).join("")}
            ${!(currentOrder.open_lines || []).length ? `<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--muted);">Nothing open.</td></tr>` : ""}
          </tbody></table>
        </div>`;
      return;
    }

    if (currentBucket === "billed" && (currentOrder.bills || []).length) {
      el.innerHTML = (currentOrder.bills || []).map(b => `
        <div class="card" style="margin-bottom:16px;padding:16px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <strong>Bill ${ctx.esc(b.bill_number)}</strong>
            <span>${fmtPrice(b.grand_total)} · ${new Date(b.created_at).toLocaleString()}</span>
          </div>
          <div style="display:flex;gap:8px;margin-bottom:8px;">
            <button class="btn btn-secondary btn-sm" onclick="CustomerOrders.openBillDoc(${b.id}, true)">Print</button>
            <button class="btn btn-secondary btn-sm" onclick="CustomerOrders.openBillDoc(${b.id}, false)">Download PDF</button>
          </div>
          ${b.narration ? `<p style="font-size:13px;color:var(--muted);margin:0 0 8px;">${ctx.esc(b.narration)}</p>` : ""}
          <table class="data" style="margin:0;"><thead><tr><th>Product</th><th>Qty</th><th>Rate</th><th>Total</th><th></th></tr></thead><tbody>
            ${(b.lines || []).map(ln => `<tr>
              <td>${ctx.esc(ln.our_product_id)}</td>
              <td>${ln.quantity_shipped}</td>
              <td>${fmtPrice(ln.unit_price)}</td>
              <td>${fmtPrice(ln.line_total)}</td>
              <td>${ln.status === "billed" ? `<button class="btn btn-secondary btn-sm" onclick="CustomerOrders.closeBillLine(${ln.id})">Close</button>` : `<span style="font-size:12px;color:var(--muted);">Closed</span>`}</td>
            </tr>`).join("")}
          </tbody></table>
        </div>`).join("");
      return;
    }

    if (currentBucket === "received") {
      const hasPlacements = (currentOrder.placements || []).length > 0;
      el.innerHTML = `
        ${hasPlacements && ctx.canWrite?.("vendor_orders") ? `
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding:14px 16px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;">
            <div>
              <div style="font-weight:600;font-size:15px;">Ready to bill?</div>
              <div style="font-size:13px;color:var(--muted);margin-top:2px;">Process received placements into a customer bill.</div>
            </div>
            <button class="btn btn-primary" onclick="CustomerOrders.processOrder()">Process Order</button>
          </div>` : ""}
        <div class="card table-wrap">
        ${(currentOrder.placements || []).map(p => `
          <div style="padding:16px;border-bottom:1px solid var(--border);">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
              <strong>Placement #${p.id}</strong>
              <span style="font-size:12px;color:var(--muted);">${new Date(p.placed_at).toLocaleString()}</span>
            </div>
            ${p.customer_notes ? `<p style="font-size:13px;color:var(--muted);margin:0 0 8px;">${ctx.esc(p.customer_notes)}</p>` : ""}
            ${p.cancel_reason ? `<p style="font-size:12px;color:var(--danger);margin:0 0 8px;">Cancelled: ${ctx.esc(p.cancel_reason)}</p>` : ""}
            <table class="data" style="margin:0;"><thead><tr><th>Product</th><th>Qty</th><th>Billed</th><th>Rate</th></tr></thead><tbody>
              ${(p.lines || []).map(ln => `<tr>
                <td>${ctx.esc(ln.our_product_id)}</td>
                <td>${ln.quantity}</td>
                <td>${ln.quantity_billed}</td>
                <td>${fmtPrice(ln.unit_price)}</td>
              </tr>`).join("")}
            </tbody></table>
          </div>`).join("")}
        ${!(currentOrder.placements || []).length ? `<p style="padding:24px;text-align:center;color:var(--muted);margin:0;">No placements.</p>` : ""}
      </div>`;
      return;
    }

    el.innerHTML = `
      <div class="card table-wrap">
        ${(currentOrder.placements || []).map(p => `
          <div style="padding:16px;border-bottom:1px solid var(--border);">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
              <strong>Placement #${p.id}</strong>
              <span style="font-size:12px;color:var(--muted);">${new Date(p.placed_at).toLocaleString()}</span>
            </div>
            ${p.customer_notes ? `<p style="font-size:13px;color:var(--muted);margin:0 0 8px;">${ctx.esc(p.customer_notes)}</p>` : ""}
            ${p.cancel_reason ? `<p style="font-size:12px;color:var(--danger);margin:0 0 8px;">Cancelled: ${ctx.esc(p.cancel_reason)}</p>` : ""}
            <table class="data" style="margin:0;"><thead><tr><th>Product</th><th>Qty</th><th>Billed</th><th>Rate</th></tr></thead><tbody>
              ${(p.lines || []).map(ln => `<tr>
                <td>${ctx.esc(ln.our_product_id)}</td>
                <td>${ln.quantity}</td>
                <td>${ln.quantity_billed}</td>
                <td>${fmtPrice(ln.unit_price)}</td>
              </tr>`).join("")}
            </tbody></table>
          </div>`).join("")}
        ${!(currentOrder.placements || []).length ? `<p style="padding:24px;text-align:center;color:var(--muted);margin:0;">No placements.</p>` : ""}
      </div>`;
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
    promptReason("Cancel open line", async (reason) => {
      ctx.showLoading?.();
      try {
        await ctx.api(`/customer-orders/open-lines/${lineId}/cancel`, { method: "POST", body: JSON.stringify({ reason }) });
        ctx.toast("Line cancelled", "success");
        await openDetail(detailCustomerId, currentBucket);
        loadList();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
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

  function buildProcessBody() {
    const lines = processLines
      .filter(l => Number(l.quantity_to_ship) > 0)
      .map(l => ({
        catalog_product_id: l.catalog_product_id,
        quantity_to_ship: Number(l.quantity_to_ship),
        discount_percent: useOverallDiscount ? undefined : (l.discount_percent ? Number(l.discount_percent) : undefined),
      }));
    const extra = additionalCharges.filter(c => c.name.trim() && c.amount.trim() && Number(c.amount) > 0)
      .map(c => ({ name: c.name.trim(), amount: String(c.amount) }));
    const body = {
      lines,
      gst_enabled: gstEnabled,
      gst_rate_percent: Number(gstRate) || 18,
      bill_series_id: Number(billSeriesId),
      narration: narration.trim() || null,
      additional_charges: extra,
    };
    if (useOverallDiscount && overallDiscount.trim()) body.overall_discount_percent = Number(overallDiscount);
    if (freightAgentId) body.freight_agent_id = Number(freightAgentId);
    if (freightCharges.trim()) body.freight_charges = String(freightCharges);
    if (packagingCharges.trim()) body.packaging_charges = String(packagingCharges);
    return body;
  }

  async function processOrder() {
    if (!detailCustomerId) return;
    processStep = 1;
    processBusy = false;
    previewTotals = null;
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
      }));
      if (!processLines.length) {
        ctx.toast("No open lines to bill. Switch to Open bucket or wait for stock.", "error");
        return;
      }
      useOverallDiscount = false;
      overallDiscount = "";
      gstEnabled = false;
      gstRate = "18";
      freightAgentId = "";
      freightCharges = "";
      packagingCharges = "";
      additionalCharges = [{ name: "", amount: "" }];
      billSeriesId = billSeries.length ? String(billSeries[0].id) : "";
      narration = pctx.default_narration || "";
      document.getElementById("co-wizard")?.classList.remove("hidden");
      renderProcessWizard();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function closeProcessWizard() {
    document.getElementById("co-wizard")?.classList.add("hidden");
  }

  function setShipQty(idx, val) {
    const ln = processLines[idx];
    if (!ln) return;
    const max = ln.quantity_open;
    let q = Math.max(0, Math.min(max, parseInt(val, 10) || 0));
    ln.quantity_to_ship = q;
    renderProcessWizard();
  }

  function setLineDisc(idx, val) {
    if (processLines[idx]) processLines[idx].discount_percent = val;
  }

  function renderProcessWizard() {
    const stepsEl = document.getElementById("co-wizard-steps");
    const bodyEl = document.getElementById("co-wizard-body");
    const footerEl = document.getElementById("co-wizard-footer");
    if (!stepsEl || !bodyEl || !footerEl) return;

    const labels = ["Lines", "Charges", "Narration", "Review"];
    stepsEl.innerHTML = labels.map((l, i) => {
      const n = i + 1;
      const cls = n === processStep ? "step active" : n < processStep ? "step done" : "step";
      return `<div class="${cls}"><span class="step-num">${n}</span><span class="step-label">${l}</span></div>`;
    }).join("");

    if (processStep === 1) {
      bodyEl.innerHTML = `
        <p style="margin:0 0 12px;color:var(--muted);font-size:14px;">Customer: <strong>${ctx.esc(processContext?.customer_name || "")}</strong></p>
        <div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;flex-wrap:wrap;">
          <label style="display:flex;align-items:center;gap:6px;font-size:14px;">
            <input type="radio" name="co-disc-mode" ${!useOverallDiscount ? "checked" : ""} onchange="CustomerOrders.setDiscMode(false)" /> Per-line discount
          </label>
          <label style="display:flex;align-items:center;gap:6px;font-size:14px;">
            <input type="radio" name="co-disc-mode" ${useOverallDiscount ? "checked" : ""} onchange="CustomerOrders.setDiscMode(true)" /> Overall discount
          </label>
          ${useOverallDiscount ? `<input class="input" style="width:100px;" placeholder="%" value="${ctx.esc(overallDiscount)}" oninput="CustomerOrders.setOverallDisc(this.value)" />` : ""}
        </div>
        <table class="data"><thead><tr>
          <th></th><th>Product</th><th>Stock</th><th>Open</th><th>Rate</th><th>Ship</th>${!useOverallDiscount ? "<th>Disc %</th>" : ""}
        </tr></thead><tbody>
          ${processLines.map((ln, i) => `<tr>
            <td>${thumb((ln.image_urls || [])[0])}</td>
            <td><strong>${ctx.esc(ln.our_product_id)}</strong></td>
            <td>${ln.quantity_on_hand}</td>
            <td>${ln.quantity_open}</td>
            <td>${fmtPrice(ln.unit_price)}</td>
            <td><input type="number" class="input" style="width:72px;" min="0" max="${ln.quantity_open}" value="${ln.quantity_to_ship}" onchange="CustomerOrders.setShipQty(${i}, this.value)" /></td>
            ${!useOverallDiscount ? `<td><input type="number" class="input" style="width:64px;" min="0" max="100" step="0.1" value="${ctx.esc(ln.discount_percent)}" oninput="CustomerOrders.setLineDisc(${i}, this.value)" /></td>` : ""}
          </tr>`).join("")}
        </tbody></table>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="CustomerOrders.closeProcessWizard()">Cancel</button>
        <button class="btn btn-primary" onclick="CustomerOrders.processNext()">Next →</button>`;
      return;
    }

    if (processStep === 2) {
      bodyEl.innerHTML = `
        <label class="label">Freight agent</label>
        <select class="input" style="margin-bottom:12px;width:100%;" onchange="CustomerOrders.setFreightAgent(this.value)">
          <option value="">— None —</option>
          ${freightAgents.map(a => `<option value="${a.id}" ${String(a.id) === freightAgentId ? "selected" : ""}>${ctx.esc(a.name)} (due ${fmtPrice(a.balance_due)})</option>`).join("")}
        </select>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
          <div><label class="label">Freight (₹)</label><input class="input" value="${ctx.esc(freightCharges)}" oninput="CustomerOrders.setFreightCharges(this.value)" /></div>
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
          <label class="label">Bill series</label>
          <select class="input" style="width:100%;" onchange="CustomerOrders.setBillSeries(this.value)">
            ${billSeries.map(s => `<option value="${s.id}" ${String(s.id) === billSeriesId ? "selected" : ""}>${ctx.esc(s.name)} (${s.prefix}${s.current_num + 1 >= s.start_num ? s.current_num + 1 : s.start_num}…${s.prefix}${s.end_num})</option>`).join("")}
            ${!billSeries.length ? `<option value="">No series — create one in Setup</option>` : ""}
          </select>
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="CustomerOrders.processBack()">← Back</button>
        <button class="btn btn-primary" ${billSeriesId ? "" : "disabled"} onclick="CustomerOrders.processNext()">Next →</button>`;
      return;
    }

    if (processStep === 3) {
      bodyEl.innerHTML = `
        <label class="label">Bill narration</label>
        <textarea class="input" rows="5" style="width:100%;" oninput="CustomerOrders.setNarration(this.value)">${ctx.esc(narration)}</textarea>
        <p style="font-size:12px;color:var(--muted);margin-top:8px;">Prefilled from customer notes. Edit as needed.</p>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="CustomerOrders.processBack()">← Back</button>
        <button class="btn btn-primary" onclick="CustomerOrders.processNext()">Review →</button>`;
      return;
    }

    const shipCount = processLines.filter(l => Number(l.quantity_to_ship) > 0).length;
    const tot = previewTotals || {};
    const discAmt = Number(tot.discount_amount || 0);
    const lineRows = (tot.lines || []).map(ln => {
      const disc = Number(ln.line_discount || 0);
      const discPct = ln.item_discount_percent ? ` (${ln.item_discount_percent}%)` : "";
      return `<tr>
        <td><strong>${ctx.esc(ln.our_product_id)}</strong></td>
        <td>${ln.quantity}</td>
        <td>${fmtPrice(ln.rate_inclusive || ln.unit_price)}</td>
        <td>${disc > 0 ? `−${fmtPrice(disc)}${discPct}` : "—"}</td>
        <td>${fmtPrice(ln.line_total)}</td>
      </tr>`;
    }).join("");
    bodyEl.innerHTML = `
      <div class="card table-wrap" style="margin-bottom:16px;">
        <table class="data"><thead><tr>
          <th>Item</th><th>Qty</th><th>Price</th><th>Discount</th><th>Total</th>
        </tr></thead><tbody>
          ${lineRows || `<tr><td colspan="5" style="text-align:center;color:var(--muted);">No lines</td></tr>`}
        </tbody></table>
      </div>
      <div class="review-grid" style="margin-bottom:16px;">
        ${ctx.reviewRow("Customer", processContext?.customer_name)}
        ${ctx.reviewRow("Lines shipping", shipCount)}
        ${ctx.reviewRow("Subtotal", fmtPrice(tot.subtotal_inclusive))}
        ${discAmt > 0 ? ctx.reviewRow(tot.discount_percent ? `Discount (${tot.discount_percent}%)` : "Discount", "−" + fmtPrice(tot.discount_amount)) : ""}
        ${Number(tot.taxable_value) > 0 && tot.gst_enabled ? ctx.reviewRow("Taxable", fmtPrice(tot.taxable_value)) : ""}
        ${Number(tot.gst_amount) > 0 ? ctx.reviewRow(`GST (${tot.gst_rate_label || ""})`, fmtPrice(tot.gst_amount)) : ""}
        ${tot.freight_charges ? ctx.reviewRow("Freight", fmtPrice(tot.freight_charges)) : ""}
        ${tot.packaging_charges ? ctx.reviewRow("Packaging", fmtPrice(tot.packaging_charges)) : ""}
        ${(tot.additional_charges || []).map(c => ctx.reviewRow(c.name, fmtPrice(c.amount))).join("")}
        ${ctx.reviewRow("Grand total", fmtPrice(tot.rounded_grand_total || tot.grand_total))}
      </div>
      <p style="font-size:13px;color:var(--muted);margin:0;">${ctx.esc(narration || "—")}</p>`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="CustomerOrders.processBack()">← Back</button>
      <button class="btn btn-primary" ${processBusy ? "disabled" : ""} onclick="CustomerOrders.submitProcess()">${processBusy ? "Submitting…" : "Submit Bill"}</button>`;
  }

  function setDiscMode(overall) { useOverallDiscount = overall; renderProcessWizard(); }
  function setOverallDisc(v) { overallDiscount = v; }
  function setFreightAgent(v) { freightAgentId = v; }
  function setFreightCharges(v) { freightCharges = v; }
  function setPackagingCharges(v) { packagingCharges = v; }
  function setGst(v) { gstEnabled = v; renderProcessWizard(); }
  function setGstRate(v) { gstRate = v; }
  function setBillSeries(v) { billSeriesId = v; }
  function setNarration(v) { narration = v; }
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
      if (!billSeriesId) return ctx.toast("Select bill series", "error");
      processStep = 3;
      renderProcessWizard();
      return;
    }
    if (processStep === 3) {
      ctx.showLoading?.();
      try {
        previewTotals = await ctx.api(`/customer-orders/customer/${detailCustomerId}/process/preview`, {
          method: "POST",
          body: JSON.stringify(buildProcessBody()),
        });
        processStep = 4;
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
      const res = await ctx.api(`/customer-orders/customer/${detailCustomerId}/process`, {
        method: "POST",
        body: JSON.stringify(buildProcessBody()),
      });
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/accounts-receivable");
      closeProcessWizard();
      if (res.document_url) {
        ctx.openDetail?.(`Bill ${res.bill_number}`, `
          <p style="margin:0 0 16px;color:var(--muted);">Bill created — ${fmtPrice(res.grand_total)}</p>
          <div style="display:flex;gap:8px;">
            <button class="btn btn-primary" style="flex:1;" onclick="CustomerOrders.openBillDoc(${res.bill_id}, true);App.closeDetail();">Print</button>
            <button class="btn btn-secondary" style="flex:1;" onclick="CustomerOrders.openBillDoc(${res.bill_id}, false);App.closeDetail();">Download PDF</button>
          </div>`,
          `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Done</button>`, "sm");
      }
      ctx.toast(`Bill ${res.bill_number} — ${fmtPrice(res.grand_total)}`, "success");
      await openDetail(detailCustomerId, "billed");
      loadList();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { processBusy = false; ctx.hideLoading?.(); }
  }

  async function openBillDoc(billId, print) {
    try {
      const d = await ctx.api(`/customer-orders/bills/${billId}/document`, {}, 0);
      if (!d.document_url) return ctx.toast("PDF not available", "error");
      if (print) {
        const w = window.open(d.document_url, "_blank");
        if (w) w.addEventListener("load", () => w.print());
      } else {
        const a = document.createElement("a");
        a.href = d.document_url;
        a.download = `${d.bill_number || "bill"}.pdf`;
        a.target = "_blank";
        a.click();
      }
    } catch (e) { ctx.toast(e.message, "error"); }
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
    if (currentBucket === "received" || currentBucket === "open") processOrder();
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
    offlineStep = 1;
    offlineCustomerId = cid || null;
    offlineCustomerName = "";
    offlineLines = [];
    offlineSearchQuery = "";
    offlineSearchResults = [];
    offlineUseOverallDiscount = false;
    offlineOverallDiscount = "";
    offlineGstEnabled = false;
    offlineGstRate = "18";
    offlineAdditionalCharges = [{ name: "", amount: "" }];
    offlinePreview = null;
    offlineBusy = false;
    ctx.showLoading?.();
    try {
      if (presetCustomerId || cid) {
        const c = await ctx.api(`/customers/${cid}`, {}, 30000);
        offlineCustomerName = c.business_name || "";
      }
      offlineBillSeries = (await ctx.api("/bill-series", {}, 30000) || []).filter(s => s.is_active && s.current_num < s.end_num);
      offlineBillSeriesId = offlineBillSeries.length ? String(offlineBillSeries[0].id) : "";
      document.getElementById("co-offline-wizard")?.classList.remove("hidden");
      renderOfflineWizard();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function closeOfflineWizard() {
    document.getElementById("co-offline-wizard")?.classList.add("hidden");
  }

  function buildOfflineBody() {
    const lines = offlineLines.filter(l => Number(l.quantity) > 0).map(l => ({
      catalog_product_id: l.catalog_product_id,
      quantity: Number(l.quantity),
      discount_percent: offlineUseOverallDiscount ? undefined : (l.discount_percent ? Number(l.discount_percent) : undefined),
    }));
    const extra = offlineAdditionalCharges.filter(c => c.name.trim() && c.amount.trim() && Number(c.amount) > 0)
      .map(c => ({ name: c.name.trim(), amount: String(c.amount) }));
    const body = {
      lines,
      gst_enabled: offlineGstEnabled,
      gst_rate_percent: Number(offlineGstRate) || 18,
      bill_series_id: Number(offlineBillSeriesId),
      additional_charges: extra,
    };
    if (offlineUseOverallDiscount && offlineOverallDiscount.trim()) body.overall_discount_percent = Number(offlineOverallDiscount);
    return body;
  }

  async function renderOfflineWizard() {
    const stepsEl = document.getElementById("co-offline-steps");
    const bodyEl = document.getElementById("co-offline-body");
    const footerEl = document.getElementById("co-offline-footer");
    if (!stepsEl || !bodyEl || !footerEl) return;
    const labels = ["Customer", "Products", "Charges", "Review"];
    stepsEl.innerHTML = labels.map((l, i) => {
      const n = i + 1;
      const cls = n === offlineStep ? "step active" : n < offlineStep ? "step done" : "step";
      return `<div class="${cls}"><span class="step-num">${n}</span><span class="step-label">${l}</span></div>`;
    }).join("");

    if (offlineStep === 1) {
      let customers = [];
      try { customers = await ctx.api("/customers", {}, 30000); } catch (_) {}
      bodyEl.innerHTML = `
        <p style="margin:0 0 16px;color:var(--muted);font-size:14px;">Who is this order for?</p>
        <label class="label">Customer</label>
        <select class="input" style="font-size:15px;padding:12px;" onchange="CustomerOrders.setOfflineCustomer(parseInt(this.value,10)||null, this.options[this.selectedIndex].text)">
          <option value="">— Select customer —</option>
          ${customers.filter(c => c.is_active).map(c => `<option value="${c.id}" ${offlineCustomerId === c.id ? "selected" : ""}>${ctx.esc(c.business_name)}${c.city_name ? ` · ${ctx.esc(c.city_name)}` : ""}</option>`).join("")}
        </select>
        ${offlineCustomerId ? `<div style="margin-top:16px;padding:12px 14px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;font-size:14px;">
          <strong>${ctx.esc(offlineCustomerName)}</strong> selected — next, add products.
        </div>` : ""}`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="CustomerOrders.closeOfflineWizard()">Cancel</button>
        <button class="btn btn-primary" ${offlineCustomerId ? "" : "disabled"} onclick="CustomerOrders.offlineNext()">Next →</button>`;
      return;
    }

    if (offlineStep === 2) {
      const cartRows = offlineLines.length ? offlineLines.map((line, i) => `
        <tr>
          <td><strong>${ctx.esc(line.our_product_id)}</strong></td>
          <td><span class="badge ${line.quantity_on_hand > 0 ? "badge-green" : "badge-red"}">${line.quantity_on_hand ?? 0}</span></td>
          <td>${fmtPrice(line.selling_price)}</td>
          <td><input type="number" min="1" class="input" style="width:72px;" value="${line.quantity}" onchange="CustomerOrders.setOfflineQty(${line.catalog_product_id}, this.value)" /></td>
          ${!offlineUseOverallDiscount ? `<td><input type="number" min="0" max="100" step="0.1" class="input" style="width:64px;" value="${ctx.esc(line.discount_percent || "")}" oninput="CustomerOrders.setOfflineLineDisc(${line.catalog_product_id}, this.value)" /></td>` : ""}
          <td><button class="btn btn-ghost btn-sm" onclick="CustomerOrders.removeOfflineLine(${line.catalog_product_id})">✕</button></td>
        </tr>`).join("") : `<tr><td colspan="${offlineUseOverallDiscount ? 5 : 6}" style="text-align:center;padding:20px;color:var(--muted);">Add products from the list below</td></tr>`;

      const q = offlineSearchQuery.trim().toLowerCase();
      const filtered = (offlineSearchResults || []).filter(p => {
        if (!q) return true;
        return String(p.our_product_id || "").toLowerCase().includes(q)
          || String(p.vendor_name || "").toLowerCase().includes(q);
      }).slice(0, 50);

      const searchRows = filtered.map(p => {
        const inCart = offlineLines.some(l => l.catalog_product_id === p.catalog_product_id);
        const img = (p.image_urls && p.image_urls[0]) || "";
        return `<button type="button" class="co-search-hit ${inCart ? "in-cart" : ""}" onclick="CustomerOrders.addOfflineProduct(${p.catalog_product_id})" ${inCart ? "disabled" : ""}>
          ${thumb(img)}
          <div class="co-search-hit-body">
            <strong>${ctx.esc(p.our_product_id)}</strong>
            <span>${fmtPrice(p.selling_price)} · Stock ${p.quantity_on_hand ?? 0}${p.vendor_name ? ` · ${ctx.esc(p.vendor_name)}` : ""}</span>
          </div>
          <span class="co-search-hit-add">${inCart ? "Added" : "+ Add"}</span>
        </button>`;
      }).join("");

      bodyEl.innerHTML = `
        <div style="margin-bottom:12px;font-size:14px;color:var(--muted);">Customer: <strong style="color:var(--text);">${ctx.esc(offlineCustomerName)}</strong></div>
        <label class="label">Find product</label>
        <input class="input search-big" id="co-offline-search" placeholder="Filter by product ID or vendor…" value="${ctx.esc(offlineSearchQuery)}" oninput="CustomerOrders.onOfflineSearchInput(this.value)" autocomplete="off" />
        <div class="co-offline-products co-search-results">
          ${searchRows || `<p style="padding:16px;text-align:center;color:var(--muted);font-size:13px;margin:0;">${offlineSearchResults.length ? "No match" : "Loading products…"}</p>`}
        </div>
        <div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;flex-wrap:wrap;">
          <span style="font-size:13px;font-weight:600;">Discount</span>
          <label style="display:flex;align-items:center;gap:6px;font-size:13px;">
            <input type="radio" name="co-off-disc" ${!offlineUseOverallDiscount ? "checked" : ""} onchange="CustomerOrders.setOfflineDiscMode(false)" /> Per line
          </label>
          <label style="display:flex;align-items:center;gap:6px;font-size:13px;">
            <input type="radio" name="co-off-disc" ${offlineUseOverallDiscount ? "checked" : ""} onchange="CustomerOrders.setOfflineDiscMode(true)" /> Overall
          </label>
          ${offlineUseOverallDiscount ? `<input class="input" style="width:80px;" placeholder="%" value="${ctx.esc(offlineOverallDiscount)}" oninput="CustomerOrders.setOfflineOverallDisc(this.value)" />` : ""}
        </div>
        <div class="card table-wrap" style="margin:0;">
          <table class="data" style="margin:0;font-size:13px;"><thead><tr>
            <th>Product</th><th>Stock</th><th>Rate</th><th>Qty</th>${!offlineUseOverallDiscount ? "<th>Disc %</th>" : ""}<th></th>
          </tr></thead><tbody>${cartRows}</tbody></table>
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="CustomerOrders.offlineBack()">← Back</button>
        <button class="btn btn-primary" ${offlineLines.some(l => Number(l.quantity) > 0) ? "" : "disabled"} onclick="CustomerOrders.offlineNext()">Next →</button>`;
      return;
    }

    if (offlineStep === 3) {
      bodyEl.innerHTML = `
        <p style="margin:0 0 12px;font-size:14px;color:var(--muted);">${offlineLines.length} product(s) for <strong>${ctx.esc(offlineCustomerName)}</strong></p>
        <label class="label">Additional charges</label>
        ${offlineAdditionalCharges.map((c, i) => `
          <div style="display:flex;gap:8px;margin-bottom:8px;">
            <input class="input" placeholder="Name / note" value="${ctx.esc(c.name)}" oninput="CustomerOrders.setOfflineAddCharge(${i}, 'name', this.value)" />
            <input class="input" placeholder="₹" style="width:100px;" value="${ctx.esc(c.amount)}" oninput="CustomerOrders.setOfflineAddCharge(${i}, 'amount', this.value)" />
          </div>`).join("")}
        <button type="button" class="btn btn-secondary btn-sm" onclick="CustomerOrders.addOfflineChargeRow()">+ Add charge</button>
        <div style="margin-top:16px;padding-top:16px;border-top:1px solid var(--border);">
          <label style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
            <input type="checkbox" ${offlineGstEnabled ? "checked" : ""} onchange="CustomerOrders.setOfflineGst(this.checked)" /> GST inclusive split
          </label>
          ${offlineGstEnabled ? `<label class="label">GST rate %</label><input class="input" style="width:100px;margin-bottom:12px;" value="${ctx.esc(offlineGstRate)}" oninput="CustomerOrders.setOfflineGstRate(this.value)" />` : ""}
          <label class="label">Bill series</label>
          <select class="input" style="width:100%;" onchange="CustomerOrders.setOfflineBillSeries(this.value)">
            ${offlineBillSeries.map(s => `<option value="${s.id}" ${String(s.id) === offlineBillSeriesId ? "selected" : ""}>${ctx.esc(s.name)}</option>`).join("")}
          </select>
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="CustomerOrders.offlineBack()">← Back</button>
        <button class="btn btn-primary" ${offlineBillSeriesId ? "" : "disabled"} onclick="CustomerOrders.offlineNext()">Review →</button>`;
      return;
    }

    const tot = offlinePreview || {};
    const discAmt = Number(tot.discount_amount || 0);
    const lineRows = (tot.lines || []).map(ln => {
      const disc = Number(ln.line_discount || 0);
      const discPct = ln.item_discount_percent ? ` (${ln.item_discount_percent}%)` : "";
      return `<tr>
        <td><strong>${ctx.esc(ln.our_product_id)}</strong></td>
        <td>${ln.quantity}</td>
        <td>${fmtPrice(ln.rate_inclusive || ln.unit_price)}</td>
        <td>${disc > 0 ? `−${fmtPrice(disc)}${discPct}` : "—"}</td>
        <td>${fmtPrice(ln.line_total)}</td>
      </tr>`;
    }).join("");
    bodyEl.innerHTML = `
      <div class="card table-wrap" style="margin-bottom:16px;">
        <table class="data"><thead><tr>
          <th>Item</th><th>Qty</th><th>Price</th><th>Discount</th><th>Total</th>
        </tr></thead><tbody>${lineRows}</tbody></table>
      </div>
      <div class="review-grid" style="margin-bottom:16px;">
        ${ctx.reviewRow("Customer", offlineCustomerName)}
        ${ctx.reviewRow("Subtotal", fmtPrice(tot.subtotal_inclusive))}
        ${discAmt > 0 ? ctx.reviewRow(tot.discount_percent ? `Discount (${tot.discount_percent}%)` : "Discount", "−" + fmtPrice(tot.discount_amount)) : ""}
        ${Number(tot.gst_amount) > 0 ? ctx.reviewRow("GST", fmtPrice(tot.gst_amount)) : ""}
        ${ctx.reviewRow("Grand total", fmtPrice(tot.rounded_grand_total || tot.grand_total))}
      </div>`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="CustomerOrders.offlineBack()">← Back</button>
      <button class="btn btn-primary" ${offlineBusy ? "disabled" : ""} onclick="CustomerOrders.submitOffline()">${offlineBusy ? "Creating…" : "Confirm Order"}</button>`;
  }

  function setOfflineCustomer(id, name) {
    offlineCustomerId = id || null;
    offlineCustomerName = name && name !== "— Select customer —" ? name.split(" · ")[0] : offlineCustomerName;
    if (!id) offlineCustomerName = "";
    renderOfflineWizard();
  }

  function onOfflineSearchInput(val) {
    offlineSearchQuery = val;
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

  async function searchOfflineProducts(q) {
    await ensureOfflineProductsLoaded();
    renderOfflineWizard();
  }

  function addOfflineProduct(catalogProductId) {
    const p = offlineSearchResults.find(x => x.catalog_product_id === catalogProductId);
    if (!p || offlineLines.some(l => l.catalog_product_id === catalogProductId)) return;
    offlineLines.push({
      catalog_product_id: p.catalog_product_id,
      our_product_id: p.our_product_id,
      quantity: 1,
      discount_percent: "",
      selling_price: p.selling_price,
      quantity_on_hand: p.quantity_on_hand,
    });
    renderOfflineWizard();
  }

  function removeOfflineLine(catalogProductId) {
    offlineLines = offlineLines.filter(l => l.catalog_product_id !== catalogProductId);
    renderOfflineWizard();
  }
  function setOfflineDiscMode(v) { offlineUseOverallDiscount = v; renderOfflineWizard(); }
  function setOfflineOverallDisc(v) { offlineOverallDiscount = v; }
  function setOfflineGst(v) { offlineGstEnabled = v; renderOfflineWizard(); }
  function setOfflineGstRate(v) { offlineGstRate = v; }
  function setOfflineBillSeries(v) { offlineBillSeriesId = v; }
  function setOfflineAddCharge(i, field, val) { if (offlineAdditionalCharges[i]) offlineAdditionalCharges[i][field] = val; }
  function addOfflineChargeRow() { offlineAdditionalCharges.push({ name: "", amount: "" }); renderOfflineWizard(); }

  function setOfflineQty(cid, raw) {
    const line = offlineLines.find(l => l.catalog_product_id === cid);
    if (line) line.quantity = Math.max(1, parseInt(raw, 10) || 1);
    renderOfflineWizard();
  }

  function setOfflineLineDisc(cid, val) {
    const line = offlineLines.find(l => l.catalog_product_id === cid);
    if (line) line.discount_percent = val;
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
      if (!offlineLines.some(l => Number(l.quantity) > 0)) return ctx.toast("Add at least one product", "error");
      offlineStep = 3;
      renderOfflineWizard();
      return;
    }
    if (offlineStep === 3) {
      if (!offlineBillSeriesId) return ctx.toast("Select bill series", "error");
      ctx.showLoading?.();
      try {
        offlinePreview = await ctx.api(`/customer-orders/customer/${offlineCustomerId}/offline/preview`, {
          method: "POST",
          body: JSON.stringify(buildOfflineBody()),
        });
        offlineStep = 4;
        renderOfflineWizard();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    }
  }

  function offlineBack() {
    if (offlineStep > 1) { offlineStep -= 1; renderOfflineWizard(); }
  }

  async function submitOffline() {
    if (offlineBusy || !offlineCustomerId) return;
    offlineBusy = true;
    renderOfflineWizard();
    ctx.showLoading?.();
    try {
      const res = await ctx.api(`/customer-orders/customer/${offlineCustomerId}/offline`, {
        method: "POST",
        body: JSON.stringify(buildOfflineBody()),
      });
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/stock");
      closeOfflineWizard();
      const docBtns = [];
      if (res.order_document_url) docBtns.push(`<button class="btn btn-primary" style="flex:1;" onclick="window.open('${res.order_document_url}','_blank')?.print?.()">Print Receipt</button>`);
      if (res.order_document_url) docBtns.push(`<button class="btn btn-secondary" style="flex:1;" onclick="window.open('${res.order_document_url}','_blank')">Download Receipt</button>`);
      if (res.bill_document_url) docBtns.push(`<button class="btn btn-secondary" style="flex:1;" onclick="window.open('${res.bill_document_url}','_blank')">Bill PDF</button>`);
      ctx.openDetail?.(`Offline order — ${res.bill_number}`, `
        <p style="margin:0 0 12px;color:var(--muted);">Bill ${ctx.esc(res.bill_number)} · ${fmtPrice(res.grand_total)}</p>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">${docBtns.join("")}</div>`,
        `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Done</button>`, "sm");
      ctx.toast("Offline order created", "success");
      setBucket("billed");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { offlineBusy = false; ctx.hideLoading?.(); }
  }

  return {
    init, loadList, setBucket, showHub, openDetail, switchBucket,
    showCreateMenu, showCreateMenuFromCustomer, runHubAction, runDetailAction, openCloseBatch,
    processOrder, closeProcessWizard, renderProcessWizard,
    setShipQty, setLineDisc, setDiscMode, setOverallDisc,
    setFreightAgent, setFreightCharges, setPackagingCharges,
    setGst, setGstRate, setBillSeries, setNarration, setAddCharge, addChargeRow,
    processNext, processBack, submitProcess,
    cancelOpenLine, closeBillLine, openBillDoc,
    openOfflineWizard, closeOfflineWizard, renderOfflineWizard,
    setOfflineCustomer, setOfflineDiscMode, setOfflineOverallDisc, setOfflineGst, setOfflineGstRate,
    setOfflineBillSeries, setOfflineAddCharge, addOfflineChargeRow,
    onOfflineSearchInput, addOfflineProduct, removeOfflineLine,
    setOfflineQty, setOfflineLineDisc, offlineNext, offlineBack, submitOffline,
  };
})();
