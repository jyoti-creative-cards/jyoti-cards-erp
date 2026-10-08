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
        <span style="color:var(--muted);">Credit limit: ${cr.track_only ? "not set — outstanding tracked only, never blocks billing" : "Unlimited"}</span>
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
      ${over ? `<p style="margin:8px 0 0;font-size:13px;color:#b91c1c;">⚠ This bill will push the customer over their credit limit — you can still proceed.</p>` : ""}
    </div>`;
  }

  async function processFromHub(customerId, bucket) {
    detailCustomerId = customerId;
    currentBucket = bucket || "open";
    await processOrder();
  }

  /** Confirm received order (if any), then open bill wizard. Used by post-place "Bill now". */
  async function billNow(customerId) {
    if (!customerId) return;
    App.closeDetail?.();
    ctx.showLoading?.();
    try {
      try {
        await ctx.api(`/customer-orders/customer/${customerId}/confirm`, { method: "POST" }, 0);
        ctx.invalidateCache?.("/customer-orders");
      } catch (e) {
        const msg = String(e.message || "").toLowerCase();
        if (!msg.includes("no pending") && !msg.includes("nothing to confirm")) throw e;
      }
      detailCustomerId = customerId;
      currentBucket = "open";
      await processOrder();
    } catch (e) {
      ctx.toast(e.message || "Could not bill", "error");
    } finally {
      ctx.hideLoading?.();
    }
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
      freightAgentId = defaultFreightAgentId();
      freightCharges = "";
      transportMode = freightAgentId ? "bus" : "";
      transportReceiptNumber = "";
      packagingCharges = "";
      additionalCharges = [{ name: "", amount: "" }];
      billSeriesId = billSeries.length ? String(billSeries[0].id) : "";
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
      // City wasn't already on hand here (bill/detail payloads don't carry it) — fetch
      // it separately for the review screen's "Customer / City" line. Best-effort only.
      ctx.api(`/customers/${bill.customer_id}`, {}, 30000).then(c => {
        if (processContext && processContext.customer_id === bill.customer_id) {
          processContext.city_name = c?.city_name || null;
          renderProcessWizard();
        }
      }).catch(() => {});
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
      editBillOriginalQty = {};
      for (const l of processLines) editBillOriginalQty[l.catalog_product_id] = Number(l.quantity_to_ship) || 0;
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
      if ((bill.transport_mode || (bill.freight_agent_id ? "bus" : "")) === "bus" && !freightAgentId) {
        freightAgentId = defaultFreightAgentId();
      }
      freightCharges = bill.freight_charges != null ? String(bill.freight_charges) : "";
      transportMode = bill.transport_mode || (bill.freight_agent_id ? "bus" : (Number(bill.freight_charges) > 0 ? "transport" : "self_pickup"));
      transportReceiptNumber = bill.transport_receipt_number || "";
      packagingCharges = bill.packaging_charges != null ? String(bill.packaging_charges) : "";
      additionalCharges = (bill.additional_charges || []).filter(c => String(c.name || "").trim().toLowerCase() !== "name plate").length
        ? bill.additional_charges.filter(c => String(c.name || "").trim().toLowerCase() !== "name plate").map(c => ({ name: c.name || "", amount: String(c.amount || "") }))
        : [{ name: "", amount: "" }];
      billSeriesId = bill.bill_series_id != null ? String(bill.bill_series_id) : "";
      editBillNumber = bill.bill_number || "";
      customerNotes = "";
      narration = bill.narration || "";
      billEditSearch = "";
      billEditProducts = [];
      billEditSearchPending = false;
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
    editBillOriginalQty = {};
  }

  /** Lines whose qty on this bill edit dropped below what was originally billed —
   * saving will restore stock and shrink the customer's order for that qty. */
  function _billEditShrinkLines() {
    if (!editBillId) return [];
    const currentByCid = {};
    for (const l of processLines) currentByCid[l.catalog_product_id] = Number(l.quantity_to_ship) || 0;
    const out = [];
    for (const [cidStr, origQty] of Object.entries(editBillOriginalQty)) {
      const cid = Number(cidStr);
      const newQty = currentByCid[cid] || 0; // 0 if the line was removed entirely
      if (newQty < origQty) {
        const line = processLines.find(l => l.catalog_product_id === cid);
        out.push({ our_product_id: line ? line.our_product_id : cid, from: origQty, to: newQty });
      }
    }
    return out;
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
    renderWizardTotalsBar();
  }

  function setLineDisc(idx, val) {
    const ln = processLines[idx];
    if (!ln) return;
    ln.discount_percent = val;
    ln.discSource = val === "" || val == null ? "" : "pct";
    ln.net_rate = val === "" || val == null ? "" : calcNetFromDisc(ln.unit_price, val);
    renderWizardTotalsBar();
  }

  function setLineNetRate(idx, val) {
    const ln = processLines[idx];
    if (!ln) return;
    ln.net_rate = val;
    ln.discSource = val === "" || val == null ? "" : "net";
    if (val === "" || val == null) {
      ln.discount_percent = "";
      renderWizardTotalsBar();
      return;
    }
    ln.discount_percent = calcDiscFromNet(ln.unit_price, val);
    discountEnabled = true;
    useOverallDiscount = false;
    renderWizardTotalsBar();
  }

  /** Running qty/amount from the line items alone (pre-GST/pre-freight/pre-charges) —
   * kept visible on every wizard step (not just Review) since staff use it to judge
   * additional charges while still on the Transport/Charges steps. */
  function wizardLinesTotals() {
    let qty = 0, amount = 0;
    for (const ln of processLines) {
      const q = Number(ln.quantity_to_ship) || 0;
      if (q <= 0) continue;
      qty += q;
      // Mirror the "shownNet" logic used in the Step-1 table so this bar always matches
      // what's on screen there (overall-discount mode ignores the per-line net_rate).
      const rate = useOverallDiscount && overallDiscount
        ? Number(calcNetFromDisc(ln.unit_price, overallDiscount)) || 0
        : (Number(ln.net_rate) || Number(calcNetFromDisc(ln.unit_price, ln.discount_percent || 0)) || 0);
      amount += q * rate;
    }
    return { qty, amount };
  }

  function renderWizardTotalsBar() {
    const bar = document.getElementById("co-wizard-totals");
    if (!bar) return;
    const { qty, amount } = wizardLinesTotals();
    bar.innerHTML = qty > 0
      ? `<span><span class="wtb-muted">Total qty</span>${qty}</span><span><span class="wtb-muted">Total amount</span>${fmtPrice(amount)}</span>`
      : "";
  }

  function renderProcessWizard() {
    const stepsEl = document.getElementById("co-wizard-steps");
    const bodyEl = document.getElementById("co-wizard-body");
    const footerEl = document.getElementById("co-wizard-footer");
    if (!stepsEl || !bodyEl || !footerEl) return;
    renderWizardTotalsBar();

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
            </button>`).join("")}</div>` : (q ? `<p style="font-size:12px;color:var(--muted);">${billEditSearchPending ? "Searching…" : "No matches"}</p>` : `<p style="font-size:12px;color:var(--muted);">Type a product number</p>`)}
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
            <td><strong>${ctx.esc(ln.our_product_id)}</strong>${ln.marking ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;">${ctx.esc(ln.marking)}</span>` : ""}${addonsUnderHtml(ln.addons, ln.quantity_to_ship || 1)}</td>
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
          <input id="co-freight-amount" class="input" style="width:100%;max-width:220px;" value="${ctx.esc(freightCharges)}" oninput="CustomerOrders.setFreightCharges(this.value)" />`;
      } else if (transportMode === "transport") {
        extra = `
          <label class="label">Transport charges (₹)</label>
          <input id="co-freight-amount" class="input" style="width:100%;max-width:220px;margin-bottom:12px;" value="${ctx.esc(freightCharges)}" oninput="CustomerOrders.setFreightCharges(this.value)" />
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
        ${editBillId ? "" : `
          <div style="margin-bottom:16px;">
            <label class="label">Bill number</label>
            <div style="font-size:15px;font-weight:600;color:var(--text);">${ctx.esc(nextBillNumberFromSeries() || "—")}</div>
            <p style="font-size:12px;color:var(--muted);margin:4px 0 0;">Auto-assigned from series when bill is created.</p>
          </div>
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
    const totalQty = (tot.lines || []).reduce((s, ln) => s + (Number(ln.quantity) || 0), 0);
    const totalLineAmount = (tot.lines || []).reduce((s, ln) => s + (Number(ln.line_total) || 0), 0);
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
        </tbody>${lineRows ? `<tfoot><tr style="font-weight:600;border-top:2px solid var(--border);">
          <td>Total</td><td>${totalQty}</td><td></td><td></td><td></td><td>${fmtPrice(totalLineAmount)}</td>
        </tr></tfoot>` : ""}</table>
      </div>
      <div class="review-grid" style="margin-bottom:16px;">
        ${ctx.reviewRow("Customer", processContext?.customer_name)}
        ${processContext?.city_name ? ctx.reviewRow("City", processContext.city_name) : ""}
        ${!editBillId ? ctx.reviewRow("Bill number", nextBillNumberFromSeries() || "auto") : ""}
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
      ${editBillId ? `<p style="font-size:12px;color:var(--muted);margin:10px 0 0;">Saving updates the bill and syncs the customer order quantities.</p>` : ""}
      ${editBillId && _billEditShrinkLines().length ? `<div style="margin-top:10px;padding:10px 12px;background:#fef3c7;border:1px solid #fde68a;border-radius:8px;font-size:13px;color:#92400e;">
        <strong>Reducing quantity below what was billed:</strong>
        <ul style="margin:6px 0 0;padding-left:18px;">
          ${_billEditShrinkLines().map(l => `<li>${ctx.esc(l.our_product_id)}: ${l.from} → ${l.to}</li>`).join("")}
        </ul>
        <div style="margin-top:6px;">Stock will be restored and the customer's order for these qty will shrink — this can't be told apart later from "never ordered".</div>
      </div>` : ""}`;
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
  function setOverallDisc(v) { overallDiscount = v; renderWizardTotalsBar(); }
  function setBillEditSearch(v) {
    billEditSearch = v || "";
    renderProcessWizard();
    clearTimeout(billEditTimer);
    const q = billEditSearch.trim();
    if (q.length < 1) {
      billEditProducts = [];
      billEditSearchPending = false;
      renderProcessWizard();
      return;
    }
    billEditSearchPending = true;
    billEditTimer = setTimeout(async () => {
      try {
        billEditProducts = await ctx.api(`/stock/products?lite=1&limit=8&search=${encodeURIComponent(q)}`, {}, 0) || [];
      } catch (_) {
        billEditProducts = [];
      }
      if (billEditSearch.trim() !== q) return;
      billEditSearchPending = false;
      renderProcessWizard();
    }, 200);
  }
  function defaultFreightAgentId() {
    const hit = freightAgents.find(a => String(a.name || "").trim().toLowerCase() === "vishnu parcel");
    return hit ? String(hit.id) : "";
  }
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
      if (!freightAgentId) freightAgentId = defaultFreightAgentId();
    }
    renderProcessWizard();
    if (v === "bus" || v === "transport") {
      requestAnimationFrame(() => {
        const el = document.getElementById("co-freight-amount");
        if (el) { el.focus(); el.select(); }
      });
    }
  }
  function setTransportReceipt(v) { transportReceiptNumber = v; }
  function setPackagingCharges(v) { packagingCharges = v; }
  function setGst(v) { gstEnabled = v; renderProcessWizard(); }
  function setGstRate(v) { gstRate = v; }
  function setBillSeries(v) {
    billSeriesId = v;
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
      ctx.showLoading?.();
      try {
        // Real server-side totals (GST + additional charges included) for both create
        // and edit — the edit path used to hand-roll a client estimate that silently
        // dropped GST/additional charges, so what staff approved here didn't match what
        // PUT .../bills/{id} actually saved.
        const url = editBillId
          ? `/customer-orders/bills/${editBillId}/edit-preview`
          : `/customer-orders/customer/${detailCustomerId}/process/preview`;
        previewTotals = await ctx.api(url, {
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

