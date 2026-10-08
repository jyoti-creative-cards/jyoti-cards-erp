  async function wizardNext() {
    if (wizardMode === "offline_vendor") {
      if (wizardStep === 1 && !wizardVendorId) return;
      if (wizardStep === 2) {
        offlineQtyPopupId = null;
        if (!wizardLines.some(l => (l.quantity_received || 0) > 0)) {
          return ctx.toast("Add at least one product with quantity", "error");
        }
      }
      if (wizardStep === 3) {
        saveReceiptMeta();
        if (!receiptMeta.orderReceiptNumber) {
          return ctx.toast("Enter order receipt number", "error");
        }
      }
      wizardStep++;
      await renderWizard();
      return;
    }
    if (wizardMode === "receive_goods") {
      if (wizardStep === 1 && !wizardVendorId) return;
      if (wizardStep === 2) {
        saveReceiptMeta();
        if (!wizardLines.some(l => (l.quantity_received || 0) > 0)) {
          return ctx.toast("Enter quantity received on at least one row", "error");
        }
        if (!receiptMeta.orderReceiptNumber) {
          return ctx.toast("Enter order receipt number", "error");
        }
      }
      wizardStep++;
      await renderWizard();
      return;
    }
    if (wizardMode === "bill_received") {
      if (wizardStep === 1 && !wizardVendorId) return;
      if (wizardStep === 2) {
        if (!wizardReceiptId) return; // still picking a receipt
        if (!wizardLines.some(l => (l.quantity_billed || 0) > 0)) {
          return ctx.toast("Enter billed quantity on at least one row", "error");
        }
        saveReceiptMeta();
        const total = parseFloat(receiptMeta.totalBilledAmount);
        if (!receiptMeta.totalBilledAmount || Number.isNaN(total) || total < 0) {
          return ctx.toast("Enter total bill amount", "error");
        }
        ctx.showLoading?.();
        try { await refreshBillPreview(); } finally { ctx.hideLoading?.(); }
      }
      wizardStep++;
      await renderWizard();
      return;
    }
    if (wizardStep === 2 && !wizardVendorId) return;
    wizardStep++;
    await renderWizard();
  }
  async function uploadBill() {
    const billNum = receiptMeta.billNumber || (document.getElementById("stock-bill-number")?.value || "").trim() || "receive";
    if (!billFile) return null;
    const fd = new FormData();
    fd.append("vendor_id", String(wizardVendorId));
    fd.append("bill_number", billNum);
    fd.append("file", billFile);
    const API = ctx.apiBase ? ctx.apiBase() : "http://127.0.0.1:8003/api/v1";
    const h = {};
    if (sessionStorage.getItem("jc_auth_mode") === "admin") {
      h["X-Admin-Key"] = sessionStorage.getItem("jc_admin_key") || "";
    } else {
      h["Authorization"] = `Bearer ${sessionStorage.getItem("jc_staff_token") || ""}`;
    }
    const res = await fetch(`${API}/stock/upload-bill`, { method: "POST", headers: h, body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : "Bill upload failed");
    }
    const data = await res.json();
    return data.key;
  }
  async function submitReceipt() {
    if (receiptSubmitBusy) return; // double-click/double-submit guard — was creating duplicate receipts
    receiptSubmitBusy = true;
    try {
      await _submitReceiptInner();
    } finally {
      receiptSubmitBusy = false;
    }
  }
  async function _submitReceiptInner() {
    saveReceiptMeta();
    const isEdit = wizardMode === "edit_receipt" && editReceiptId;
    const isOffline = wizardMode === "offline_vendor";
    const isReceive = wizardMode === "receive_goods" || isOffline
      || (isEdit && (editReceiptType === "vendor_receive" || editReceiptType === "offline_vendor" || editReceiptType === "vendor_order"));
    const isBill = wizardMode === "bill_received" || (isEdit && editReceiptType === "vendor_bill");
    const isNewBill = isBill && !isEdit;
    const active = isReceive
      ? receivedLines()
      : (isBill ? wizardLines.filter(l => (l.quantity_billed || 0) > 0) : billableLines());
    if (!active.length) return ctx.toast(isReceive ? "Enter received quantities" : "Enter received or billed quantities", "error");
    if (isBill && active.some(l => l._priceHidden && l.billed_amount == null)) {
      return ctx.toast("Cost is hidden for you on some lines — enter Rate billed / Amount billed manually before saving", "error");
    }
    const endpoint = isEdit
      ? `/stock/receipts/${editReceiptId}`
      : isOffline
        ? "/stock/receipts/offline-vendor"
        : isReceive
          ? "/stock/receipts/vendor-receive"
          : `/stock/receipts/${wizardReceiptId}/bill`;
    const savedVendorId = wizardVendorId;
    const savedLabel = placedOrder?.vendor_label || "";
    const savedMode = wizardMode;
    const savedNotes = receiptMeta.notes || "";
    const savedBillNum = receiptMeta.billNumber || "";
    const savedOrderReceipt = receiptMeta.orderReceiptNumber || "";
    const savedDns = [...pendingDebitNotes];
    const savedExtraCash = billPreview?.expected_extra_cash ? Number(billPreview.expected_extra_cash) : 0;
    ctx.showLoading?.();
    try {
      let key = billFileKey;
      if (billFile) key = await uploadBill();
      const billNum = receiptMeta.billNumber || null;
      const totalBilled = receiptMeta.totalBilledAmount ? parseFloat(receiptMeta.totalBilledAmount) : null;
      if (!isReceive && (totalBilled == null || totalBilled < 0)) return ctx.toast("Enter total bill amount", "error");
      if (isReceive && !receiptMeta.orderReceiptNumber) {
        return ctx.toast("Enter order receipt number", "error");
      }
      const eventDate = receiptMeta.eventDate || localToday();
      const debitNotesPayload = pendingDebitNotes.map(dn => ({
        note_type: dn.note_type,
        direction: dn.direction || dn._direction || null,
        catalog_product_id: dn.catalog_product_id,
        quantity: dn.quantity,
        amount: dn.amount,
        notes: dn.notes || null,
      }));
      const payload = isReceive
        ? {
            vendor_id: wizardVendorId,
            order_receipt_number: receiptMeta.orderReceiptNumber,
            bill_file_key: key,
            notes: receiptMeta.notes || null,
            received_on: eventDate,
            lines: active.map(l => ({
              catalog_product_id: l.catalog_product_id,
              quantity_received: l.quantity_received || 0,
              quantity_billed: 0,
              billed_amount: 0,
            })),
          }
        : isNewBill
        ? {
            total_billed_amount: totalBilled,
            lines: active.map(l => ({
              catalog_product_id: l.catalog_product_id,
              quantity_billed: l.quantity_billed || 0,
              billed_amount: l.billed_amount != null ? l.billed_amount : null,
            })),
            bill_number: billNum,
            bill_file_key: key,
            bill_date: eventDate,
            notes: receiptMeta.notes || null,
            debit_notes: debitNotesPayload,
            ...billingPctOverridePayload(),
            ...gstPctOverridePayload(),
          }
        : {
            vendor_id: wizardVendorId,
            bill_number: billNum,
            bill_file_key: key,
            notes: receiptMeta.notes || null,
            additional_charges: null,
            total_billed_amount: totalBilled,
            bill_date: eventDate,
            lines: active.map(l => ({
              catalog_product_id: l.catalog_product_id,
              quantity_received: l.quantity_received || l.quantity_billed || 0,
              quantity_billed: l.quantity_billed || 0,
              billed_amount: l.billed_amount != null ? l.billed_amount : null,
            })),
            debit_notes: debitNotesPayload,
            ...(isBill ? billingPctOverridePayload() : {}),
            ...(isBill ? gstPctOverridePayload() : {}),
          };
      const res = await ctx.api(endpoint, {
        method: isEdit ? "PATCH" : "POST",
        body: JSON.stringify(payload),
      });
      ctx.invalidateCache?.("/stock");
      ctx.invalidateCache?.("/vendor-orders");
      ctx.invalidateCache?.("/accounts-payable");
      const rid = res.receipt_id || editReceiptId;
      closeWizard();
      if (isEdit) {
        ctx.toast(isReceive ? "Receive updated" : "Bill updated", "success");
        if (rid) await openReceiptDetail(rid);
        if (typeof VendorOrders !== "undefined" && VendorOrders.refreshIfOpen) VendorOrders.refreshIfOpen(savedVendorId);
        await load();
        return;
      }
      if (isReceive) {
        const lineHtml = `<table class="data" style="font-size:13px;margin-top:12px;"><thead><tr><th>Product</th><th>Received</th></tr></thead><tbody>
          ${active.map(l => `<tr><td>${ctx.esc(productIdLabel(l))}</td><td>${l.quantity_received || 0}</td></tr>`).join("")}
        </tbody><tfoot><tr class="stock-qty-tfoot"><td>Total quantity</td><td>${lineQtySum(active, "quantity_received")}</td></tr></tfoot></table>`;
        const nextHint = savedMode === "offline_vendor"
          ? "In <strong>Received</strong> (unbilled). Next: Bill when vendor invoice arrives."
          : "Stock updated. Next: Bill when vendor invoice arrives.";
        ctx.openDetail?.("Goods received", `
          <div class="doc-success-banner">
            <strong>Goods in stock</strong>
            <span>Receipt #${rid} · no AP yet</span>
          </div>
          <p style="margin:0 0 12px;font-size:14px;color:var(--muted);">${nextHint}</p>
          <div class="review-block" style="margin-bottom:12px;">
            ${ctx.reviewRow("Vendor", savedLabel || "—")}
            ${ctx.reviewRow("Order receipt #", savedOrderReceipt || "—")}
            ${savedNotes ? ctx.reviewRow("Note", savedNotes) : ""}
          </div>
          ${lineHtml}`,
          `${ctx.canWrite?.("vendor_orders") !== false ? `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail(); Stock.openBillForVendor(${savedVendorId})">Bill next →</button>` : ""}
           <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail(); if(typeof VendorOrders!=='undefined'){App.showView('buying');VendorOrders.setHubMode('past');VendorOrders.setBucket('received');VendorOrders.openDetail(0,'received',${savedVendorId});}">View Received</button>`, "md");
        ctx.toast("Goods received", "success");
        if (typeof VendorOrders !== "undefined" && VendorOrders.refreshIfOpen) VendorOrders.refreshIfOpen(savedVendorId);
        await load();
        return;
      }
      const totals = calcReviewTotals(active);
      if (savedExtraCash > 0) totals.netPayable += savedExtraCash;
      let docUrl = res.document_url;
      if (!docUrl && rid) {
        try {
          const doc = await ctx.api(`/stock/receipts/${rid}/document`, {}, 0);
          docUrl = doc.document_url;
        } catch (_) {}
      }
      const dnHtml = savedDns.length
        ? `<table class="data" style="font-size:13px;margin-top:12px;"><thead><tr><th>Debit Note</th><th>Effect</th></tr></thead><tbody>
            ${savedDns.map(dn => {
              const effect = dnPayableEffect(dn);
              const payLess = effect < 0;
              const cmt = dn.notes ? ` — ${ctx.esc(dn.notes)}` : "";
              return `<tr><td>${ctx.esc(dnDisplayLabel(dn))}${cmt}</td><td>${payLess ? "Pay less" : "Pay more"} ${fmtPrice(Math.abs(effect))}</td></tr>`;
            }).join("")}
          </tbody></table>` : "";
      const lineHtml = `<table class="data" style="font-size:13px;margin-top:12px;"><thead><tr><th>Product</th><th>Received</th><th>Billed</th></tr></thead><tbody>
        ${active.map(l => `<tr><td>${ctx.esc(productIdLabel(l))}</td><td>${l.quantity_received || 0}</td><td>${l.quantity_billed || 0}</td></tr>`).join("")}
      </tbody><tfoot><tr class="stock-qty-tfoot"><td>Total quantity</td><td>${lineQtySum(active, "quantity_received")}</td><td>${lineQtySum(active, "quantity_billed")}</td></tr></tfoot></table>`;
      const pdfBtns = docUrl
        ? `<div class="doc-actions">
            <button class="btn btn-primary" onclick="Stock.openReceiptPdf('${docUrl}', true)">Print</button>
            <button class="btn btn-secondary" onclick="Stock.openReceiptPdf('${docUrl}', false)">Save PDF</button>
            <button class="btn btn-secondary" onclick="Stock.openReceiptPdf('${docUrl}', false)">View PDF</button>
          </div>`
        : `<div class="doc-actions">
            <button class="btn btn-primary" onclick="Stock.fetchReceiptPdf(${rid}, true)">Get PDF &amp; Print</button>
            <button class="btn btn-secondary" onclick="Stock.fetchReceiptPdf(${rid}, false)">Get PDF</button>
          </div>
          <p class="doc-actions-hint">Receipt #${rid} is saved. Tap Get PDF if the file was still generating.</p>`;
      ctx.openDetail?.("Bill saved", `
        <div class="doc-success-banner">
          <strong>Bill saved</strong>
          <span>Receipt #${rid}${savedBillNum ? ` · Bill ${ctx.esc(savedBillNum)}` : ""}</span>
        </div>
        <div class="review-block" style="margin-bottom:12px;">
          ${ctx.reviewRow("Vendor", savedLabel || "—")}
          ${ctx.reviewRow("Bill number", savedBillNum || "—")}
          ${ctx.reviewRow("Bill amount", fmtPrice(totals.billAmount))}
          ${savedExtraCash > 0 ? ctx.reviewRow("Extra cash", fmtPrice(savedExtraCash)) : ""}
          ${totals.dnAdj ? ctx.reviewRow("Debit note adj.", fmtPrice(totals.dnAdj)) : ""}
          ${ctx.reviewRow("Net payable", fmtPrice(totals.netPayable))}
        </div>
        ${lineHtml}
        ${dnHtml}
        ${pdfBtns}`,
        `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail(); if(typeof VendorOrders!=='undefined'){ App.showView('buying'); VendorOrders.setBucket('received'); }">Done</button>`, "md");
      ctx.toast(savedMode === "offline_vendor" ? "Offline order created" : "Bill created", "success");
      if (typeof VendorOrders !== "undefined" && VendorOrders.refreshIfOpen) {
        await VendorOrders.refreshIfOpen(savedVendorId);
      }
      await load();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  function openReceiptPdf(url, print) {
    if (!url) return ctx.toast("PDF not ready", "error");
    const w = window.open(url, "_blank");
    if (print && w) {
      try { w.focus(); setTimeout(() => { try { w.print(); } catch (_) {} }, 600); } catch (_) {}
    }
  }
  async function fetchReceiptPdf(receiptId, print) {
    if (!receiptId) return;
    ctx.showLoading?.();
    try {
      const doc = await ctx.api(`/stock/receipts/${receiptId}/document`, {}, 0);
      if (!doc?.document_url) throw new Error("PDF not available yet");
      openReceiptPdf(doc.document_url, print);
    } catch (e) { ctx.toast(e.message || "PDF not available", "error"); }
    finally { ctx.hideLoading?.(); }
  }
  let stockLedgerKind = "all";
  let stockHideVoids = true;
  let stockLedgerRows = [];

  function stockMoveBucket(e) {
    const t = String(e.entry_type || "").toLowerCase();
    const ref = String(e.reference_type || "").toLowerCase();
    const notes = String(e.notes || "").toLowerCase();
    if (t.includes("void") || t.includes("restore") || notes.includes("cancelled") || notes.includes("voided")) return "void";
    if (ref === "stock_receipt" || t === "received") return "purchase";
    if (ref === "customer_placement" || ref === "customer_bill" || t === "reserved" || t === "sold") return "sales";
    return "other";
  }

  function visibleStockRows(rows) {
    let list = rows || [];
    if (stockHideVoids) {
      const voided = new Set();
      for (const e of list) {
        if (stockMoveBucket(e) === "void" && e.reference_id) voided.add(`${e.reference_type}:${e.reference_id}`);
      }
      list = list.filter(e => {
        if (stockMoveBucket(e) === "void") return false;
        if (e.reference_id && voided.has(`${e.reference_type}:${e.reference_id}`)) return false;
        return true;
      });
    }
    if (stockLedgerKind === "purchase" || stockLedgerKind === "sales" || stockLedgerKind === "other") {
      list = list.filter(e => stockMoveBucket(e) === stockLedgerKind);
    }
    return list;
  }

  function setLedgerKind(kind) {
    stockLedgerKind = kind || "all";
    repaintStockLedger();
  }

  function setHideStockVoids(on) {
    stockHideVoids = !!on;
    repaintStockLedger();
  }

  function repaintStockLedger() {
    const host = document.getElementById("stock-ledger-block");
    if (!host) return;
    host.outerHTML = ledgerTableHtml(stockLedgerRows);
  }

  function ledgerTableHtml(rows) {
    stockLedgerRows = rows || [];
    const shown = visibleStockRows(stockLedgerRows);
    const chip = (id, label) => `<button type="button" class="btn btn-sm ${stockLedgerKind === id ? "btn-primary" : "btn-secondary"}" onclick="Stock.setLedgerKind('${id}')">${label}</button>`;
    const body = shown.length ? shown.map(e => {
      const when = ctx.fmtDay?.(e.display_date || e.created_at) || "—";
      const qty = `${e.quantity_delta > 0 ? "+" : ""}${e.quantity_delta}`;
      const kind = e.voucher_kind || "";
      const vid = Number(e.voucher_id) || 0;
      const click = kind && vid
        ? `Stock.openVoucher('${kind}', ${vid})`
        : (e.reference_type === "customer_placement"
          ? `Stock.toastNoBill()`
          : `Stock.openLedgerDetail(${e.id})`);
      return `<tr class="clickable" onclick="${click}">
        <td style="font-size:12px;">${when}</td>
        <td>${ctx.esc(e.party || "—")}</td>
        <td>${qty}</td>
        <td><strong>${ctx.esc(e.bill_number || "—")}</strong></td>
        <td>${e.balance_after}</td>
        <td><span class="badge badge-blue">${ctx.esc(e.entry_type || "")}</span></td>
      </tr>`;
    }).join("") : `<tr><td colspan="6" style="color:var(--muted);">No movements for this filter</td></tr>`;
    return `<div id="stock-ledger-block">
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 10px;">
        ${chip("all", "All")}
        ${chip("purchase", "Purchase")}
        ${chip("sales", "Sales")}
        ${chip("other", "Other")}
        <label style="display:inline-flex;gap:6px;align-items:center;margin-left:4px;font-size:13px;">
          <input type="checkbox" ${stockHideVoids ? "checked" : ""} onchange="Stock.setHideStockVoids(this.checked)" />
          Hide void entries
        </label>
      </div>
      <div class="table-wrap"><table class="data history-table"><thead><tr>
        <th>Date</th><th>Party</th><th>Qty</th><th>Bill</th><th>Balance</th><th>Type</th>
      </tr></thead><tbody>${body}</tbody></table></div>
    </div>`;
  }
  function toastNoBill() {
    ctx.toast("No bill yet for this item and party", "error");
  }
  function openVoucher(kind, id) {
    if (!id) return;
    if (kind === "customer_bill") { BillSeries?.openBill?.(id); return; }
    if (kind === "stock_receipt") { openReceiptDetail(id); return; }
    if (kind === "customer_return") { Returns?.openReturn?.(id); return; }
    openLedgerDetail(id);
  }
  async function openLedgerDetail(ledgerId) {
    ctx.showLoading?.();
    try {
      const d = await ctx.api(`/stock/ledger/${ledgerId}`, {}, 0);
      renderReceiptDetail("Stock movement", d.entry_type, d.quantity_delta, d.balance_after, d.display_date || d.created_at, d.notes, d.receipt);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  async function openReceiptDetail(receiptId) {
    ctx.showLoading?.();
    try {
      const receipt = await ctx.api(`/stock/receipts/${receiptId}`, {}, 0);
      renderReceiptDetail("Stock receipt", "receipt", null, null, receipt.display_date || receipt.value_date || receipt.created_at, null, receipt);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  async function openEditReceipt(receiptId) {
    ctx.showLoading?.();
    try {
      const receipt = await ctx.api(`/stock/receipts/${receiptId}`, {}, 0);
      editReceiptId = receipt.id;
      // One-to-one model: receipt_type stays "vendor_receive" for life; bill_status
      // (not receipt_type) tells us whether this is now a bill to edit.
      editReceiptType = receipt.bill_status === "billed" ? "vendor_bill" : (receipt.receipt_type || "vendor_order");
      wizardMode = "edit_receipt";
      wizardStep = 1;
      wizardVendorId = receipt.vendor_id;
      wizardProducts = [];
      editAddPickerOpen = false;
      editAddSearch = "";
      wizardLines = (receipt.lines || []).map(l => {
        // buying_price is masked ("—") for staff without costs.read, but
        // billed_amount (a historical fact, not a "cost") never is — re-deriving
        // billed_amount from qty*buying_price used to overwrite an already-correct
        // recorded amount with 0 the moment a masked-price line was re-edited.
        // Prefer the already-recorded real billed_amount; only fall back to null
        // (forcing manual entry) when there's neither a visible price nor an
        // existing recorded amount to preserve (e.g. a brand-new masked-price line
        // added during this edit).
        const priceKnown = Number.isFinite(Number(l.buying_price));
        const existingAmt = Number(l.billed_amount);
        const hasExistingAmt = Number.isFinite(existingAmt) && existingAmt > 0;
        const qty = Number(l.quantity_billed) || 0;
        return {
          catalog_product_id: l.catalog_product_id,
          our_product_id: l.our_product_id,
          vendor_product_id: l.vendor_product_id || "",
          year_group: l.year_group || "",
          buying_price: l.buying_price,
          quantity_received: l.quantity_received || 0,
          quantity_billed: qty,
          billed_amount: priceKnown ? qty * Number(l.buying_price) : (hasExistingAmt ? existingAmt : null),
          billed_rate: priceKnown ? l.buying_price : (hasExistingAmt && qty > 0 ? existingAmt / qty : null),
          _priceHidden: !priceKnown && !hasExistingAmt,
        };
      });
      billFile = null;
      billFileKey = receipt.bill_file_key || null;
      pendingDebitNotes = (receipt.debit_notes || []).map(dn => ({
        note_type: dn.note_type,
        direction: dn.direction,
        catalog_product_id: dn.catalog_product_id,
        our_product_id: dn.our_product_id,
        vendor_product_id: dn.vendor_product_id,
        quantity: dn.quantity,
        amount: dn.amount,
        notes: dn.notes,
        _payable_effect: dn.payable_effect,
      }));
      receiptMeta = {
        billNumber: receipt.bill_number || "",
        orderReceiptNumber: receipt.order_receipt_number || "",
        additionalCharges: receipt.additional_charges || "",
        totalBilledAmount: receipt.total_billed_amount || receipt.bill_amount || "",
        billingPct: receipt.billing_pct_applied || "",
        gstPct: receipt.gst_rate_pct_applied || "",
        notes: receipt.notes || "",
      };
      try {
        const v = await ctx.api(`/vendors/${receipt.vendor_id}`, {}, 60000);
        placedOrder = {
          vendor_id: receipt.vendor_id,
          vendor_label: v.city_name ? `${v.business_name} — ${v.city_name}` : v.business_name,
        };
        billingTerms = {
          billing_pct: v.billing_pct, additional_charge: v.additional_charge,
          additional_charge_label: v.additional_charge_label, discount_pct: v.discount_pct,
          gst_included: v.gst_included, gst_rate_pct: v.gst_rate_pct, billing_notes: v.billing_notes,
        };
        if (!receiptMeta.billingPct) receiptMeta.billingPct = String(Number(v.billing_pct));
        if (!receiptMeta.gstPct) receiptMeta.gstPct = String(Number(v.gst_rate_pct));
      } catch (_) {
        placedOrder = { vendor_id: receipt.vendor_id, vendor_label: `Vendor #${receipt.vendor_id}` };
      }
      document.getElementById("stock-wizard")?.classList.remove("hidden");
      document.querySelector("#stock-wizard .modal-header h3").textContent =
        (editReceiptType === "vendor_receive" || editReceiptType === "offline_vendor" || editReceiptType === "vendor_order") ? "Edit Receive" : "Edit Vendor Bill";
      await renderWizard();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  function renderReceiptDetail(title, entryType, qtyDelta, balanceAfter, when, notes, receipt) {
    const voidedBanner = receipt?.deleted_at
      ? `<div style="background:var(--danger-bg,#fee2e2);color:var(--danger);border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:13px;">
          <strong>Voided</strong>${receipt.deleted_reason ? ` — ${ctx.esc(receipt.deleted_reason)}` : ""}. Restore it from the recycle bin to edit or bill again.
        </div>`
      : "";
    const meta = [
      entryType ? ctx.reviewRow("Type", entryType) : "",
      qtyDelta != null ? ctx.reviewRow("Quantity", (qtyDelta > 0 ? "+" : "") + qtyDelta) : "",
      balanceAfter != null ? ctx.reviewRow("Balance after", balanceAfter) : "",
      ctx.reviewRow("Date", ctx.fmtDay(entryType === "receipt" ? (receipt?.display_date || when) : when)),
      notes ? ctx.reviewRow("Notes", notes) : "",
      receipt?.display_name ? ctx.reviewRow("Label", receipt.display_name) : "",
      receipt?.order_receipt_number ? ctx.reviewRow("Order receipt #", receipt.order_receipt_number) : "",
      receipt?.bill_number ? ctx.reviewRow("Bill number", receipt.bill_number) : "",
      receipt?.bill_amount ? ctx.reviewRow("Bill amount", fmtPrice(receipt.bill_amount)) : "",
      receipt?.debit_note_total ? ctx.reviewRow("Debit note adj.", fmtPrice(receipt.debit_note_total)) : "",
      receipt?.net_payable ? ctx.reviewRow("Net payable", fmtPrice(receipt.net_payable)) : "",
      receipt?.received_by_name && ctx.isAdmin?.() ? ctx.reviewRow("Received by", receipt.received_by_name) : "",
    ].join("");
    let table = "";
    let extra = "";
    if (receipt?.lines?.length) {
      const showAmt = receipt.lines.some(l => l.billed_amount && Number(l.billed_amount) !== 0);
      const lineRows = receipt.lines.map(l =>
        `<tr><td>${ctx.esc(productIdLabel(l))}</td><td>${l.quantity_received}</td><td>${l.quantity_billed || 0}</td>${showAmt ? `<td>${l.billed_amount ? fmtPrice(l.billed_amount) : "—"}</td>` : ""}</tr>`
      ).join("");
      table = `<table class="data" style="font-size:13px;"><thead><tr><th>Product</th><th>Received</th><th>Billed Qty</th>${showAmt ? "<th>Billed Amt</th>" : ""}</tr></thead><tbody>${lineRows}</tbody></table>`;
    }
    if (receipt?.debit_notes?.length) {
      extra += `<div style="margin-top:12px;"><strong style="font-size:13px;">Debit notes</strong>
        <table class="data" style="font-size:13px;margin-top:6px;"><thead><tr><th>Note</th><th>Effect</th></tr></thead><tbody>
        ${receipt.debit_notes.map(dn => {
          const item = dn.our_product_id || dn.catalog_product_id ? ctx.esc(productIdLabel(dn)) : "";
          const label = dn.note_type === "item"
            ? `${item} × ${dn.quantity} (${ctx.esc(dn.direction || "")})`
            : item
              ? `${item} — ₹${ctx.esc(dn.amount)} (${ctx.esc(dn.direction || "")})`
              : `Value ₹${ctx.esc(dn.amount)} (${ctx.esc(dn.direction || "")})`;
          return `<tr><td>${label}${dn.notes ? ` — ${ctx.esc(dn.notes)}` : ""}</td><td>${fmtPrice(dn.payable_effect)}</td></tr>`;
        }).join("")}
        </tbody></table></div>`;
    }
    if (receipt?.bill_file_url) {
      extra += `<p style="margin-top:8px;"><a href="${ctx.esc(receipt.bill_file_url)}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm">View bill file</a></p>`;
    }
    if (receipt?.change_history?.length && ctx.changeHistoryTable) {
      extra += `<div style="margin-top:16px;">${ctx.changeHistoryTable(receipt.change_history)}</div>`;
    }
    const canWrite = ctx.canWrite?.("stock") !== false;
    const isVoided = !!receipt?.deleted_at;
    const editLabel = receipt?.receipt_type === "vendor_receive" ? "Edit receive" : "Edit bill";
    const footer = `
      ${canWrite && receipt?.id && !isVoided ? `<button class="btn btn-primary" onclick="Stock.openEditReceipt(${receipt.id})">${editLabel}</button>` : ""}
      ${ctx.isAdmin?.() && receipt?.id && !isVoided ? `<button class="btn btn-danger" onclick="Stock.voidReceipt(${receipt.id}, ${receipt.vendor_id || "null"})">Void</button>` : ""}
      ${ctx.detailFooterChild()}`;
    ctx.openDetail(title, voidedBanner + ctx.ledgerDetailCard("Receipt details", meta, table, extra), footer, "md", { push: true });
  }
