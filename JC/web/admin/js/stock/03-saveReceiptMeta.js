  function saveReceiptMeta() {
    // Only overwrite fields when their inputs exist — review step has none,
    // so a blanket read was wiping total bill amount before submit.
    const billEl = document.getElementById("stock-bill-number");
    if (billEl) receiptMeta.billNumber = (billEl.value || "").trim();
    const totalEl = document.getElementById("stock-total-billed");
    if (totalEl && totalEl.tagName === "INPUT") receiptMeta.totalBilledAmount = totalEl.value || "";
    const pctEl = document.getElementById("stock-billing-pct");
    if (pctEl) receiptMeta.billingPct = pctEl.value || "";
    const gstPctEl = document.getElementById("stock-gst-pct");
    if (gstPctEl) receiptMeta.gstPct = gstPctEl.value || "";
    const ornEl = document.getElementById("stock-order-receipt-number");
    if (ornEl) receiptMeta.orderReceiptNumber = (ornEl.value || "").trim();
    const notesEl = document.getElementById("stock-receive-notes");
    if (notesEl) receiptMeta.notes = (notesEl.value || "").trim();
    const dateEl = document.getElementById("stock-event-date");
    if (dateEl) receiptMeta.eventDate = (dateEl.value || "").trim() || localToday();
  }
  function calcReviewTotals(active) {
    const billAmount = parseFloat(receiptMeta.totalBilledAmount) || 0;
    const dnAdj = pendingDebitNotes.reduce((s, dn) => s + dnPayableEffect(dn), 0);
    const netPayable = billAmount + dnAdj;
    return { billAmount, charges: 0, dnAdj, netPayable };
  }
  function renderDebitNoteStep(bodyEl, footerEl) {
    const billable = billableLines();
    const dnRows = pendingDebitNotes.map((dn, i) => {
      const amt = dnPayableEffect(dn);
      const payLess = amt < 0;
      const comment = dn.notes ? `<div class="dn-row-note">${ctx.esc(dn.notes)}</div>` : "";
      const autoTag = dn._auto_suggested
        ? `<span class="badge badge-blue" style="font-size:10px;margin-left:6px;">auto</span>`
        : "";
      return `<tr>
        <td>
          <strong>${ctx.esc(dnDisplayLabel(dn))}</strong>${autoTag}
          ${comment}
        </td>
        <td><span class="dn-effect-pill ${payLess ? "is-less" : "is-more"}">${payLess ? "Pay less" : "Pay more"} ${fmtPrice(Math.abs(amt))}</span></td>
        <td style="white-space:nowrap;">
          <button class="btn btn-ghost btn-sm" onclick="Stock.editPendingDebitNote(${i})">Edit</button>
          <button class="btn btn-ghost btn-sm" onclick="Stock.removeDebitNote(${i})">✕</button>
        </td>
      </tr>`;
    }).join("");
    const billDisplayAmt = parseFloat(receiptMeta.totalBilledAmount) || 0;
    bodyEl.innerHTML = `
      <div class="vo-wiz-step-head vo-wiz-step-head-row">
        <div>
          <h4>Debit notes</h4>
          <p>Auto-suggested when billed qty ≠ received qty. Edit or remove, or add more.</p>
        </div>
        <button class="btn btn-primary btn-sm" onclick="Stock.openDebitNote()" ${billable.length ? "" : "disabled"}>+ Add</button>
      </div>
      ${!billable.length ? HubUI.emptyState({ title: "No lines yet", sub: "Go back and enter quantities first." }) : ""}
      ${pendingDebitNotes.length
        ? `<div class="stock-dn-table-wrap"><table class="data"><thead><tr><th>Note</th><th>Payable effect</th><th></th></tr></thead><tbody>${dnRows}</tbody></table></div>`
        : HubUI.emptyState({ title: "No debit notes", sub: "All billed quantities match received." })}
      <div class="stock-dn-summary">
        ${ctx.reviewRow("Lines on bill", String(billable.length))}
        ${ctx.reviewRow("Bill document total", fmtPrice(billDisplayAmt))}
      </div>`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
      <button class="btn btn-primary" onclick="Stock.wizardNext()">Review →</button>`;
  }
  function renderReviewStep(bodyEl, footerEl) {
    const active = billableLines();
    const dnAdj = pendingDebitNotes.reduce((s, dn) => s + dnPayableEffect(dn), 0);
    const dnRows = pendingDebitNotes.map((dn) => {
      const amt = dnPayableEffect(dn);
      const payLess = amt < 0;
      const comment = dn.notes ? ` — ${ctx.esc(dn.notes)}` : "";
      const autoTag = dn._auto_suggested ? ` <span class="badge badge-blue" style="font-size:10px;">auto</span>` : "";
      return `<tr>
        <td>${ctx.esc(dnDisplayLabel(dn))}${autoTag}${comment}</td>
        <td><span class="dn-effect-pill ${payLess ? "is-less" : "is-more"}">${payLess ? "Pay less" : "Pay more"} ${fmtPrice(Math.abs(amt))}</span></td>
      </tr>`;
    }).join("");
    const billAmt = parseFloat(receiptMeta.totalBilledAmount) || 0;
    const extraCash = billPreview?.expected_extra_cash ? Number(billPreview.expected_extra_cash) : 0;
    const billNum = receiptMeta.billNumber || "—";
    const apSection = `
      <h4 style="margin:0 0 8px;font-size:15px;">AP entries (accounts payable)</h4>
      <div class="stock-dn-table-wrap" style="margin-bottom:16px;">
        <table class="data" style="font-size:13px;"><thead><tr><th>Entry</th><th>Amount</th></tr></thead><tbody>
          <tr>
            <td>Entry 1 — bill ${ctx.esc(billNum)} document total</td>
            <td style="font-weight:600;">${fmtPrice(billAmt)}</td>
          </tr>
          ${extraCash > 0 ? `<tr>
            <td>Entry 2 — extra cash (half-price balance, no GST${billingTerms?.cash_discount_equals_gst ? " — less GST discount" : ""})</td>
            <td style="font-weight:600;">${fmtPrice(extraCash)}</td>
          </tr>
          <tr style="border-top:2px solid var(--border);">
            <td style="font-weight:700;color:var(--primary);">Total AP (before debit notes)</td>
            <td style="font-weight:700;color:var(--primary);">${fmtPrice(billAmt + extraCash)}</td>
          </tr>` : ""}
          ${dnAdj ? `<tr>
            <td>Debit note adjustment</td>
            <td style="font-weight:600;">${fmtPrice(dnAdj)}</td>
          </tr>
          <tr style="border-top:2px solid var(--border);">
            <td style="font-weight:700;color:var(--primary);">Net payable</td>
            <td style="font-weight:700;color:var(--primary);">${fmtPrice(billAmt + extraCash + dnAdj)}</td>
          </tr>` : ""}
        </tbody></table>
      </div>`;
    bodyEl.innerHTML = `
      <div class="vo-wiz-review-hero">
        <span class="vo-wiz-review-label">Billing from</span>
        <strong>${ctx.esc(placedOrder?.vendor_label || "—")}</strong>
        <span class="vo-wiz-review-stats">${active.length} line${active.length === 1 ? "" : "s"}</span>
      </div>
      <div class="review-block" style="margin-bottom:16px;">
        ${ctx.reviewRow("Bill number", receiptMeta.billNumber || "—")}
        ${ctx.reviewRow("Bill date", receiptMeta.eventDate || localToday())}
      </div>
      <div class="stock-dn-table-wrap" style="margin-bottom:16px;">
        <table class="data"><thead><tr>
          <th>Product</th><th style="text-align:right;">Received</th><th style="text-align:right;">Billed</th><th style="text-align:right;">Diff</th>
        </tr></thead><tbody>
          ${active.map(l => {
            const diff = (l.quantity_billed || 0) - (l.quantity_received || 0);
            const diffCell = diff !== 0
              ? `<span class="badge ${diff > 0 ? "badge-amber" : "badge-blue"}" style="font-size:10px;">${diff > 0 ? "+" : ""}${diff}</span>`
              : `<span style="color:var(--muted);">—</span>`;
            return `<tr>
              <td><strong>${ctx.esc(productIdLabel(l))}</strong>${!(l.quantity_received || 0) && (l.quantity_billed || 0) ? ` <span class="badge badge-amber" style="font-size:10px;">Billed only</span>` : ""}</td>
              <td style="text-align:right;">${l.quantity_received || 0}</td>
              <td style="text-align:right;">${l.quantity_billed || 0}</td>
              <td style="text-align:right;">${diffCell}</td>
            </tr>`;
          }).join("")}
        </tbody><tfoot><tr class="stock-qty-tfoot">
          <td>Total quantity</td>
          <td style="text-align:right;">${lineQtySum(active, "quantity_received")}</td>
          <td style="text-align:right;">${lineQtySum(active, "quantity_billed")}</td>
          <td></td>
        </tr></tfoot></table>
      </div>
      ${apSection}
      ${pendingDebitNotes.length
        ? `<h4 style="margin:0 0 8px;font-size:15px;">Debit notes</h4>
           <div class="stock-dn-table-wrap"><table class="data"><thead><tr><th>Note</th><th>Effect</th></tr></thead><tbody>${dnRows}</tbody></table></div>`
        : ""}`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
      <button class="btn btn-primary btn-lg" onclick="Stock.submitReceipt()">Submit Bill</button>`;
  }
  function openDebitNote() {
    const active = billableLines();
    if (!active.length) return ctx.toast("Enter received or billed quantities first", "error");
    DebitNotes.openCreate({
      vendorId: wizardVendorId,
      receiptId: null,
      receivingLines: active.map(l => ({
        catalog_product_id: l.catalog_product_id,
        our_product_id: l.our_product_id,
        vendor_product_id: l.vendor_product_id,
        buying_price: l.buying_price || placedOrder?.lines?.find(x => x.catalog_product_id === l.catalog_product_id)?.buying_price,
        quantity_received: l.quantity_received || 0,
        quantity_billed: l.quantity_billed || 0,
      })),
      onDone: (payload) => {
        if (!payload) return;
        const line = active.find(l => l.catalog_product_id === payload.catalog_product_id);
        const price = Number(line?.buying_price || 0);
        const amt = payload.note_type === "item" ? price * payload.quantity : Number(payload.amount) || 0;
        pendingDebitNotes.push({
          ...payload,
          direction: payload.direction,
          _direction: payload.direction,
          _direction_label: payload._direction_label,
          _label: productIdLabel(line),
          _amount: Math.abs(amt),
          _payable_effect: payload.note_type === "item" ? -amt : amt,
        });
        renderWizard();
      },
    });
  }
  function removeDebitNote(idx) {
    pendingDebitNotes.splice(idx, 1);
    renderWizard();
  }
  function editPendingDebitNote(idx) {
    const active = billableLines();
    const existing = pendingDebitNotes[idx];
    if (!existing) return;
    DebitNotes.openCreate({
      vendorId: wizardVendorId,
      receiptId: null,
      receivingLines: active.map(l => ({
        catalog_product_id: l.catalog_product_id,
        our_product_id: l.our_product_id,
        vendor_product_id: l.vendor_product_id,
        buying_price: l.buying_price || placedOrder?.lines?.find(x => x.catalog_product_id === l.catalog_product_id)?.buying_price,
        quantity_received: l.quantity_received || 0,
        quantity_billed: l.quantity_billed || 0,
      })),
      prefill: existing,
      editIndex: idx,
      onDone: (payload, i) => {
        if (!payload) return;
        const line = active.find(l => l.catalog_product_id === payload.catalog_product_id);
        const price = Number(line?.buying_price || 0);
        const amt = payload.note_type === "item" ? price * payload.quantity : Number(payload.amount) || 0;
        // Full replace (not merge) — drops _auto_suggested/source:"auto" so a hand-edited
        // suggestion survives the next bill-preview refresh instead of being wiped and re-added.
        pendingDebitNotes[i] = {
          ...payload,
          direction: payload.direction,
          _direction: payload.direction,
          _direction_label: payload._direction_label,
          _label: (line ? productIdLabel(line) : null) || existing._label,
          _amount: Math.abs(amt),
          _payable_effect: payload.note_type === "item" ? -amt : amt,
        };
        renderWizard();
      },
    });
  }
  function openOfflineQtyPopup(productId) {
    offlineQtyPopupId = productId;
    renderWizard();
  }
  function closeOfflineQtyPopup() {
    offlineQtyPopupId = null;
    renderWizard();
  }
  function confirmOfflineQty() {
    const productId = offlineQtyPopupId;
    if (productId == null) return;
    const raw = document.getElementById("stock-offline-qty-input")?.value;
    const qty = Math.max(1, parseInt(String(raw || "1"), 10) || 1);
    const prod = wizardProducts.find(p => p.id === productId);
    let line = wizardLines.find(l => l.catalog_product_id === productId);
    if (!line) {
      line = {
        catalog_product_id: productId,
        our_product_id: prod?.our_product_id || "",
        vendor_product_id: prod?.vendor_product_id || "",
        buying_price: prod?.buying_price,
        image_urls: prod?.image_urls,
        quantity_received: qty,
        quantity_billed: 0,
      };
      wizardLines.push(line);
    } else {
      line.quantity_received = qty;
    }
    offlineQtyPopupId = null;
    renderWizard();
  }
  function removeOfflineLine(productId) {
    wizardLines = wizardLines.filter(l => l.catalog_product_id !== productId);
    if (offlineQtyPopupId === productId) offlineQtyPopupId = null;
    renderWizard();
  }
  function bumpOfflineQty(productId, delta) {
    const line = wizardLines.find(l => l.catalog_product_id === productId);
    if (!line) return;
    line.quantity_received = Math.max(1, (parseInt(String(line.quantity_received || 1), 10) || 1) + delta);
    renderWizard();
  }
  function toggleOfflineProduct(productId, checked) {
    if (!checked) {
      removeOfflineLine(productId);
      return;
    }
    const prod = wizardProducts.find(p => p.id === productId);
    if (!prod) return;
    let line = wizardLines.find(l => l.catalog_product_id === productId);
    if (!line) {
      wizardLines.push({
        catalog_product_id: productId,
        our_product_id: prod.our_product_id || "",
        vendor_product_id: prod.vendor_product_id || "",
        buying_price: prod.buying_price,
        image_urls: prod.image_urls,
        quantity_received: 1,
        quantity_billed: 0,
      });
    }
    focusQtyProductId = productId;
    renderWizard();
  }
  function pickOfflineProduct(productId) {
    if (wizardLines.some(l => l.catalog_product_id === productId)) {
      const el = document.querySelector(`#stock-wizard [data-qty-for="${productId}"]`);
      if (el) { el.disabled = false; el.focus(); el.select(); }
      return;
    }
    toggleOfflineProduct(productId, true);
  }
  function onOfflineSearchKey(e) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const list = filterOfflineProducts();
    if (!list.length) return;
    pickOfflineProduct(list[0].id);
  }
  function onOfflineQtyKey(e) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    offlineProductSearch = "";
    focusQtyProductId = null;
    renderWizard();
  }
  function focusPendingQty(searchId) {
    if (focusQtyProductId != null) {
      const id = focusQtyProductId;
      focusQtyProductId = null;
      const el = document.querySelector(`[data-qty-for="${id}"]`);
      if (el) { el.disabled = false; el.focus(); el.select(); return; }
    }
    const inp = document.getElementById(searchId);
    if (inp && document.activeElement !== inp) inp.focus();
  }
  function onOfflineVendorSearch(val) {
    const prev = document.getElementById("stock-offline-vendor-search")
      || document.getElementById("stock-receive-vendor-search");
    const start = prev?.selectionStart;
    offlineVendorSearch = val || "";
    Promise.resolve(renderWizard()).then(() => {
      const inp = document.getElementById("stock-offline-vendor-search")
        || document.getElementById("stock-receive-vendor-search");
      if (!inp) return;
      inp.focus();
      const pos = typeof start === "number" ? start : (offlineVendorSearch || "").length;
      try { inp.setSelectionRange(pos, pos); } catch (_) {}
    });
  }
  function setOfflineLine(productId, field, raw) {
    const line = wizardLines.find(l => l.catalog_product_id === productId);
    if (!line) return;
    const n = Math.max(1, parseInt(String(raw || "1"), 10) || 1);
    line[field] = n;
  }
  function pickVendor(id) {
    wizardVendorId = id || null;
    placedOrder = null;
    wizardLines = [];
    wizardProducts = [];
    if (wizardMode === "bill_received") {
      wizardReceiptId = null;
      wizardPendingBillList = null;
      billingTerms = null;
      billPreview = null;
    }
    if (wizardMode === "offline_vendor" && wizardVendorId) {
      const v = offlineVendorsCache.find(x => x.id === wizardVendorId);
      const lbl = v
        ? (v.city_name ? `${v.business_name} — ${v.city_name}` : v.business_name)
        : "Receive without order";
      placedOrder = { vendor_id: wizardVendorId, vendor_label: lbl };
    }
    if (document.querySelector(".vo-wiz-vendor-list")) {
      renderWizard();
      return;
    }
    const nextBtn = document.querySelector("#stock-wizard-footer .btn-primary");
    if (nextBtn) nextBtn.disabled = !wizardVendorId;
  }
  function setLine(idx, field, raw) {
    if (!wizardLines[idx]) return;
    wizardLines[idx][field] = Math.max(0, parseInt(String(raw || "0"), 10) || 0);
    if (field === "quantity_received" && wizardMode !== "receive_goods" && wizardMode !== "offline_vendor") {
      wizardLines[idx].quantity_billed = wizardLines[idx].quantity_received;
      const row = document.querySelectorAll(".stock-receive-table tbody tr")[idx];
      const billedEl = row?.querySelector(".stock-billed-input");
      if (billedEl) billedEl.value = wizardLines[idx].quantity_billed || "";
    }
    if (field === "quantity_billed" && !wizardLines[idx]._amountDirty) {
      // If neither a manual rate nor the underlying buying_price is known (hidden
      // cost), leave billed_amount as null instead of coercing to a submittable 0 —
      // the biller must type the vendor's paper rate/amount manually.
      if (wizardLines[idx]._priceHidden && wizardLines[idx].billed_rate == null) {
        wizardLines[idx].billed_amount = null;
      } else {
        const rate = Number(wizardLines[idx].billed_rate ?? wizardLines[idx].buying_price) || 0;
        const amt = (Number(wizardLines[idx].quantity_billed) || 0) * rate;
        wizardLines[idx].billed_amount = amt;
        const row = document.querySelectorAll(".stock-receive-table tbody tr")[idx];
        const amtEl = row?.querySelector(".stock-amount-input");
        if (amtEl) amtEl.value = amt ? amt.toFixed(2) : "";
      }
    }
    refreshQtyFooter();
  }
  // Rate billed — defaults to our catalog rate but the vendor's paper bill can
  // state a different rate; editing it recomputes amount = qty x rate. Amount
  // stays independently editable (setLineAmount) for whole-total mismatches.
  function setLineRate(idx, raw) {
    if (!wizardLines[idx]) return;
    const v = parseFloat(raw);
    const rate = Number.isFinite(v) && v >= 0 ? v : (Number(wizardLines[idx].buying_price) || 0);
    wizardLines[idx].billed_rate = rate;
    wizardLines[idx]._amountDirty = false;
    const amt = (Number(wizardLines[idx].quantity_billed) || 0) * rate;
    wizardLines[idx].billed_amount = amt;
    const row = document.querySelectorAll(".stock-receive-table tbody tr")[idx];
    const amtEl = row?.querySelector(".stock-amount-input");
    if (amtEl) amtEl.value = amt ? amt.toFixed(2) : "";
    refreshQtyFooter();
  }
  function setLineAmount(idx, raw) {
    if (!wizardLines[idx]) return;
    const v = parseFloat(raw);
    wizardLines[idx].billed_amount = Number.isFinite(v) && v >= 0 ? v : 0;
    wizardLines[idx]._amountDirty = true;
    // Keep the rate field in sync so it doesn't show a stale, inconsistent value.
    const qty = Number(wizardLines[idx].quantity_billed) || 0;
    if (qty > 0) {
      wizardLines[idx].billed_rate = wizardLines[idx].billed_amount / qty;
      const row = document.querySelectorAll(".stock-receive-table tbody tr")[idx];
      const rateEl = row?.querySelector(".stock-rate-input");
      if (rateEl) rateEl.value = wizardLines[idx].billed_rate ? wizardLines[idx].billed_rate.toFixed(2) : "";
    }
    refreshQtyFooter();
  }
  function removeEditLine(idx) {
    if (!wizardLines[idx]) return;
    if ((wizardLines[idx].quantity_billed || 0) > 0) {
      return ctx.toast("Already billed on this line — reduce billed qty on the bill first", "error");
    }
    wizardLines.splice(idx, 1);
    renderWizard();
  }
  function toggleEditAddPicker(open) {
    editAddPickerOpen = !!open;
    if (!open) editAddSearch = "";
    renderWizard();
  }
  function onEditAddSearch(val) {
    editAddSearch = val || "";
    renderWizard();
  }
  function addEditLine(catalogProductId) {
    const p = wizardProducts.find(x => x.id === catalogProductId);
    if (!p) return;
    if (wizardLines.some(l => l.catalog_product_id === catalogProductId)) return;
    wizardLines.push({
      catalog_product_id: p.id,
      our_product_id: p.our_product_id,
      vendor_product_id: p.vendor_product_id || "",
      buying_price: p.buying_price,
      quantity_received: 1,
      quantity_billed: 0,
      image_urls: p.image_urls || [],
    });
    editAddPickerOpen = false;
    editAddSearch = "";
    renderWizard();
  }
  function setBillFile(file) { billFile = file || null; billFileKey = null; }
  function wizardBack() {
    if (wizardStep > 1) {
      wizardStep--;
      offlineQtyPopupId = null;
      // Keep entered lines/qtys when going back — only drop product cache on vendor step
      if (wizardMode === "offline_vendor" && wizardStep === 1) {
        wizardProducts = [];
        document.querySelector("#stock-wizard .stock-wiz-modal")?.classList.remove("stock-wiz-wide");
      }
      renderWizard();
    } else if ((wizardMode === "receive_goods" || wizardMode === "bill_received") && enteredFromAddStock) {
      wizardMode = null; wizardStep = 1;
      renderWizard();
    } else if (wizardMode === "receive_goods" || wizardMode === "bill_received") {
      closeWizard();
    } else if (wizardMode !== "offline_vendor") {
      wizardStep = 1; wizardMode = null; renderWizard();
    }
  }
