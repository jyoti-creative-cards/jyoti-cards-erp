  async function renderWizard() {
    const stepsEl = document.getElementById("stock-wizard-steps");
    const bodyEl = document.getElementById("stock-wizard-body");
    const footerEl = document.getElementById("stock-wizard-footer");
    if (!stepsEl || !bodyEl || !footerEl) return;
    const labels = wizardMode === "edit_receipt"
      ? ["Edit bill"]
      : wizardMode === "offline_vendor"
      ? ["Vendor", "Products", "Receipt", "Review"]
      : wizardMode === "receive_goods"
      ? ["Vendor", "Receive", "Review"]
      : wizardMode === "bill_received"
      ? ["Vendor", "Bill", "Debit Note", "Review"]
      : ["Source"];
    stepsEl.innerHTML = labels.map((lbl, i) => {
      const n = i + 1;
      const cls = n === wizardStep ? "step active" : n < wizardStep ? "step done" : "step";
      return `<div class="${cls}"><span class="step-num">${n < wizardStep ? "✓" : n}</span><span class="step-label">${lbl}</span></div>`;
    }).join("");
    if (wizardMode === "edit_receipt") {
      // "offline_vendor" (received w/o a placed order) is unbilled, same as
      // "vendor_receive" — submitReceipt() below already treats them the same
      // way; this used to fall through to the bill-editing form/labels instead
      // of the plain receive-quantities one, demanding a bill number/amount for
      // a receipt that was never billed.
      const isRecvEdit = editReceiptType === "vendor_receive" || editReceiptType === "offline_vendor";
      const isBillEdit = editReceiptType === "vendor_bill";
      setStockWizardChrome(
        isRecvEdit ? "Edit Receive" : "Edit Vendor Bill",
        `${ctx.esc(placedOrder?.display_name || (receiptMeta.orderReceiptNumber ? `Receipt ${receiptMeta.orderReceiptNumber}` : `Receipt #${editReceiptId}`))} — ${ctx.esc(placedOrder?.vendor_label || "")}`
      );
      const totals = calcReviewTotals(isBillEdit ? wizardLines.filter(l => (l.quantity_billed || 0) > 0) : billableLines());
      if (isRecvEdit) {
        if (editAddPickerOpen && !wizardProducts.length) {
          try { wizardProducts = await ctx.api(`/vendor-orders/vendor/${wizardVendorId}/products`, {}, 60000); }
          catch (e) { ctx.toast(e.message, "error"); }
        }
        const pickedIds = new Set(wizardLines.map(l => l.catalog_product_id));
        const q = editAddSearch.trim().toLowerCase();
        const pickerList = wizardProducts.filter(p => {
          if (pickedIds.has(p.id)) return false;
          if (!q) return true;
          return String(p.our_product_id || "").toLowerCase().includes(q)
            || String(p.vendor_product_id || "").toLowerCase().includes(q);
        }).slice(0, 30);
        bodyEl.innerHTML = `
          <div class="vo-wiz-step-head">
            <h4>Edit received quantities</h4>
            <p>Stock and open pending update on save. Cannot go below already-billed qty. Add, remove or edit any line. Old PDF removed; history kept.</p>
          </div>
          <div class="stock-receive-table-wrap">
            <table class="data stock-receive-table"><thead><tr>
              <th>Product</th><th>Received</th><th></th>
            </tr></thead><tbody>
              ${wizardLines.map((l, i) => `<tr>
                <td><strong>${ctx.esc(productIdLabel(l))}</strong></td>
                <td><input type="number" min="0" class="input stock-qty-input" value="${l.quantity_received || ""}" onchange="Stock.setLine(${i},'quantity_received',this.value)" /></td>
                <td><button type="button" class="btn btn-secondary btn-sm" title="Remove item" onclick="Stock.removeEditLine(${i})">✕</button></td>
              </tr>`).join("")}
              ${!wizardLines.length ? `<tr><td colspan="3" style="color:var(--muted);">No items — add one below.</td></tr>` : ""}
            </tbody></table>
          </div>
          ${editAddPickerOpen ? `
            <div class="stock-bill-card" style="margin-top:12px;">
              <h4>Add product</h4>
              <input class="input" placeholder="Search product ID, vendor ID…" value="${ctx.esc(editAddSearch)}" oninput="Stock.onEditAddSearch(this.value)" autofocus />
              <div class="vo-wiz-products" style="max-height:220px;overflow-y:auto;margin-top:10px;">
                ${pickerList.length ? pickerList.map(p => {
                  const img = (p.image_urls && p.image_urls[0]) || "";
                  return `<div class="vo-wiz-product" onclick="Stock.addEditLine(${p.id})">
                    <div class="vo-wiz-product-main">
                      ${thumb(img)}
                      <div class="vo-wiz-product-info">
                        <strong>${ctx.esc(productIdLabel(p))}</strong>
                        <span class="vo-wiz-product-sub">${fmtPrice(p.buying_price)}</span>
                      </div>
                    </div>
                    <button type="button" class="btn btn-secondary btn-sm">+ Add</button>
                  </div>`;
                }).join("") : `<p style="color:var(--muted);font-size:13px;">${wizardProducts.length ? "No matches." : "Loading…"}</p>`}
              </div>
              <button type="button" class="btn btn-secondary btn-sm" style="margin-top:10px;" onclick="Stock.toggleEditAddPicker(false)">Close</button>
            </div>
          ` : `<button type="button" class="btn btn-secondary" style="margin-top:12px;" onclick="Stock.toggleEditAddPicker(true)">+ Add product</button>`}
          <div class="stock-bill-card" style="margin-top:16px;">
            <h4>Order receipt</h4>
            <div class="stock-bill-grid">
              <div><label class="label">Order receipt number *</label>
                <input class="input" id="stock-order-receipt-number" value="${ctx.esc(receiptMeta.orderReceiptNumber || "")}" required /></div>
              <div><label class="label">Replace file</label>
                <input type="file" class="input" accept=".pdf,image/*" onchange="Stock.setBillFile(this.files[0])" />
                ${billFile ? `<span class="stock-file-name">${ctx.esc(billFile.name)}</span>` : (billFileKey ? `<span class="stock-file-name">Current file kept</span>` : "")}
              </div>
              <div style="grid-column:1/-1;"><label class="label">Note</label>
                <input class="input" id="stock-receive-notes" value="${ctx.esc(receiptMeta.notes || "")}" /></div>
            </div>
          </div>`;
        footerEl.innerHTML = `
          <button class="btn btn-secondary" onclick="Stock.closeWizard()">Cancel</button>
          <button class="btn btn-primary btn-lg" onclick="Stock.submitReceipt()">Save changes</button>`;
        return;
      }
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>Edit ${isBillEdit ? "billed qty & bill" : "quantities & bill"}</h4>
          <p>${isBillEdit ? "AP, debit notes and unbilled received update on save." : "Stock, AP and debit notes update when you save."} Old PDF removed; history kept.</p>
        </div>
        <div class="stock-receive-table-wrap">
          <table class="data stock-receive-table"><thead><tr>
            <th>Product</th>${isBillEdit ? "" : "<th>Received</th>"}<th>Billed</th>${isBillEdit ? "<th>Rate billed</th><th>Amount billed</th>" : ""}
          </tr></thead><tbody>
            ${wizardLines.map((l, i) => `<tr>
              <td><strong>${ctx.esc(productIdLabel(l))}</strong></td>
              ${isBillEdit ? "" : `<td><input type="number" min="0" class="input stock-qty-input" value="${l.quantity_received || ""}" onchange="Stock.setLine(${i},'quantity_received',this.value)" /></td>`}
              <td><input type="number" min="0" class="input stock-qty-input stock-billed-input" value="${l.quantity_billed || ""}" onchange="Stock.setLine(${i},'quantity_billed',this.value)" /></td>
              ${isBillEdit ? `<td><input type="number" min="0" step="0.01" class="input stock-qty-input stock-rate-input" value="${billedRateInputValue(l)}" placeholder="${l._priceHidden ? "Enter rate" : ""}" onchange="Stock.setLineRate(${i},this.value)" title="${l._priceHidden ? "Cost hidden — type the vendor's paper rate" : "Defaults to our catalog rate — edit if the vendor's paper bill states a different rate"}" /></td>` : ""}
              ${isBillEdit ? `<td><input type="number" min="0" step="0.01" class="input stock-qty-input stock-amount-input" value="${billedAmountInputValue(l)}" placeholder="${l._priceHidden ? "Enter amount" : ""}" onchange="Stock.setLineAmount(${i},this.value)" title="${l._priceHidden ? "Cost hidden — type the vendor's paper amount" : "Defaults to qty x our rate — edit if the vendor's paper bill states a different rate/amount"}" /></td>` : ""}
            </tr>`).join("")}
          </tbody>
          ${isBillEdit ? `<tfoot><tr class="stock-qty-tfoot">
            <td>Total</td>
            <td style="text-align:right;" id="stock-tfoot-billed">${wizardQtySum("quantity_billed")}</td>
            <td></td>
            <td style="text-align:right;" id="stock-tfoot-amount">${fmtPrice(wizardQtySum("billed_amount"))}</td>
          </tr></tfoot>` : ""}
          </table>
        </div>
        ${isBillEdit ? renderVendorBillingTermsCard() : ""}
        <div class="stock-bill-card" style="margin-top:16px;">
          <h4>Vendor bill</h4>
          <div class="stock-bill-grid">
            <div><label class="label">Bill number</label><input class="input" id="stock-bill-number" value="${ctx.esc(receiptMeta.billNumber)}" /></div>
            <div class="stock-bill-total"><label class="label">Total bill amount *</label>
              <input type="number" min="0" step="0.01" class="input" id="stock-total-billed" value="${ctx.esc(receiptMeta.totalBilledAmount)}" required /></div>
            ${isBillEdit ? `<div><label class="label">Billing % (this bill only)</label>
              <input type="number" min="0.01" max="100" step="0.01" class="input" id="stock-billing-pct" value="${ctx.esc(receiptMeta.billingPct)}" title="Override the vendor's usual billing % for this bill only — vendor profile stays unchanged" /></div>` : ""}
            ${isBillEdit && billingTerms?.gst_included ? `<div><label class="label">GST % (this bill only)</label>
              <input type="number" min="0" max="100" step="0.01" class="input" id="stock-gst-pct" value="${ctx.esc(receiptMeta.gstPct)}" title="Override the vendor's usual GST % for this bill only — vendor profile stays unchanged" /></div>` : ""}
            <div><label class="label">Replace bill file</label>
              <input type="file" class="input" accept=".pdf,image/*" onchange="Stock.setBillFile(this.files[0])" />
              ${billFile ? `<span class="stock-file-name">${ctx.esc(billFile.name)}</span>` : (billFileKey ? `<span class="stock-file-name">Current file kept</span>` : "")}
            </div>
          </div>
        </div>
        <div style="margin-top:16px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <strong>Debit notes</strong>
            <button type="button" class="btn btn-secondary btn-sm" onclick="Stock.openDebitNote()">+ Add / replace set</button>
          </div>
          ${pendingDebitNotes.length
            ? `<table class="data" style="font-size:13px;"><thead><tr><th>Note</th><th>Effect</th><th></th></tr></thead><tbody>
                ${pendingDebitNotes.map((dn, i) => `<tr>
                  <td>${ctx.esc(dnDisplayLabel(dn))}${dn.notes ? ` — ${ctx.esc(dn.notes)}` : ""}</td>
                  <td>${fmtPrice(dnPayableEffect(dn))}</td>
                  <td style="white-space:nowrap;">
                    <button type="button" class="btn btn-ghost btn-sm" onclick="Stock.editPendingDebitNote(${i})">Edit</button>
                    <button type="button" class="btn btn-ghost btn-sm" onclick="Stock.removeDebitNote(${i})">Remove</button>
                  </td>
                </tr>`).join("")}
              </tbody></table>`
            : `<p class="vo-muted" style="margin:0;">No debit notes on this bill.</p>`}
          <p class="vo-muted" style="margin:8px 0 0;font-size:12px;">Saving replaces all debit notes with the list above (AP updates automatically).</p>
        </div>
        <div class="review-block" style="margin-top:16px;">
          ${ctx.reviewRow("Bill amount", fmtPrice(totals.billAmount))}
          ${totals.dnAdj ? ctx.reviewRow("Debit note adj.", fmtPrice(totals.dnAdj)) : ""}
          ${ctx.reviewRow("Net payable", fmtPrice(totals.netPayable))}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.closeWizard()">Cancel</button>
        <button class="btn btn-primary btn-lg" onclick="Stock.submitReceipt()">Save changes</button>`;
      return;
    }
    if (wizardStep === 1 && (wizardMode === "receive_goods" || wizardMode === "bill_received")) {
      const isRecv = wizardMode === "receive_goods";
      setStockWizardChrome(isRecv ? "Receive Goods" : "Bill Order", "Step 1 — select vendor");
      if (!offlineVendorsCache.length) {
        try { offlineVendorsCache = (await ctx.api("/catalog/vendors", {}, 0) || []).map(v => ({ ...v, alias: v.alias || "" })); } catch (_) {
          try { offlineVendorsCache = (await ctx.api("/vendors", {}, 0) || []).map(v => ({ ...v, alias: v.alias || "" })); } catch (e2) {
            offlineVendorsCache = [];
            ctx.toast(e2.message, "error");
          }
        }
      }
      const active = offlineVendorsCache.filter(v => v.is_active !== false && !v.deleted_at);
      const q = offlineVendorSearch.trim();
      const filtered = OrdersUI.filterAndRankParties(active, offlineVendorSearch);
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>Select vendor</h4>
          <p>${isRecv ? "We’ll load placed lines yet to receive." : "We’ll load received lines yet to bill."}</p>
        </div>
        <div class="vo-wiz-search-wrap">
          <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
          <input id="stock-receive-vendor-search" class="input vo-wiz-search" type="search" placeholder="Search vendor name, alias, city, or phone…" value="${ctx.esc(offlineVendorSearch)}" oninput="Stock.onOfflineVendorSearch(this.value)" autocomplete="off" />
        </div>
        <div class="vo-wiz-vendor-list">
          ${filtered.length ? filtered.map(v => {
            const selected = wizardVendorId === v.id;
            const alias = (v.alias || "").trim();
            return `<button type="button" class="vo-wiz-vendor-card${selected ? " selected" : ""}" onclick="Stock.pickVendor(${v.id})">
              <span class="vo-wiz-vendor-letter">${ctx.esc((v.business_name || "?").slice(0, 1).toUpperCase())}</span>
              <span class="vo-wiz-vendor-meta">
                <strong>${v.vendor_number ? `<span style="color:var(--muted);font-weight:600;margin-right:4px;">#${v.vendor_number}</span>` : ""}${ctx.esc(v.business_name || "Vendor")}</strong>
                ${alias ? `<span>${ctx.esc(alias)}</span>` : ""}
                <span>${ctx.esc(v.city_name || "No city")}</span>
              </span>
              <span class="vo-wiz-vendor-check">${selected ? "✓" : ""}</span>
            </button>`;
          }).join("") : HubUI.emptyState({ title: q ? "No matches" : "No vendors found", sub: q ? `No vendors match “${offlineVendorSearch}”.` : "Add vendors under People first." })}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.closeWizard()">Cancel</button>
        <button class="btn btn-primary" ${wizardVendorId ? "" : "disabled"} onclick="Stock.wizardNext()">${isRecv ? "Next: Receive →" : "Next: Bill →"}</button>`;
      setTimeout(() => {
        const inp = document.getElementById("stock-receive-vendor-search");
        if (!inp || document.activeElement === inp) return;
        inp.focus();
        const n = (offlineVendorSearch || "").length;
        try { inp.setSelectionRange(n, n); } catch (_) {}
      }, 30);
      return;
    }
    if (wizardStep === 1) {
      if (wizardMode === "offline_vendor") {
        setStockWizardChrome("Receive without order", "Step 1 — choose the vendor");
        if (!offlineVendorsCache.length) {
          try { offlineVendorsCache = (await ctx.api("/vendors", {}, 0) || []).map(v => ({ ...v, alias: v.alias || "" })); } catch (_) { offlineVendorsCache = []; }
        }
        const q = offlineVendorSearch.trim();
        const active = offlineVendorsCache.filter(v => v.is_active !== false && !v.deleted_at);
        const filtered = OrdersUI.filterAndRankParties(active, offlineVendorSearch);
        bodyEl.innerHTML = `
          <div class="vo-wiz-step-head">
            <h4>Select vendor</h4>
            <p>Goods already in godown — no prior place order. Stock now, bill later from Received.</p>
          </div>
          <div class="vo-wiz-search-wrap">
            <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
            <input id="stock-offline-vendor-search" class="input vo-wiz-search" type="search" placeholder="Search vendor name, alias, city, or phone…" value="${ctx.esc(offlineVendorSearch)}" oninput="Stock.onOfflineVendorSearch(this.value)" autocomplete="off" />
          </div>
          <div class="vo-wiz-vendor-list">
            ${filtered.length ? filtered.map(v => {
              const selected = wizardVendorId === v.id;
              const lbl = v.city_name ? `${v.business_name} — ${v.city_name}` : v.business_name;
              const alias = (v.alias || "").trim();
              return `<button type="button" class="vo-wiz-vendor-card${selected ? " selected" : ""}" onclick="Stock.pickVendor(${v.id})">
                <span class="vo-wiz-vendor-letter">${ctx.esc((v.business_name || "?").slice(0, 1).toUpperCase())}</span>
                <span class="vo-wiz-vendor-meta">
                  <strong>${v.vendor_number ? `<span style="color:var(--muted);font-weight:600;margin-right:4px;">#${v.vendor_number}</span>` : ""}${ctx.esc(v.business_name || "Vendor")}</strong>
                  ${alias ? `<span>${ctx.esc(alias)}</span>` : ""}
                  <span>${ctx.esc(v.city_name || "No city")}</span>
                </span>
                <span class="vo-wiz-vendor-check">${selected ? "✓" : ""}</span>
              </button>`;
            }).join("") : HubUI.emptyState({ title: q ? "No matches" : "No vendors found", sub: q ? `No vendors match “${offlineVendorSearch}”.` : "Add vendors under People first." })}
          </div>`;
        footerEl.innerHTML = `
          <button class="btn btn-secondary" onclick="Stock.closeWizard()">Cancel</button>
          <button class="btn btn-primary" ${wizardVendorId ? "" : "disabled"} onclick="Stock.wizardNext()">Next: Products →</button>`;
        setTimeout(() => {
          const inp = document.getElementById("stock-offline-vendor-search");
          if (!inp || document.activeElement === inp) return;
          inp.focus();
          const n = (offlineVendorSearch || "").length;
          try { inp.setSelectionRange(n, n); } catch (_) {}
        }, 30);
        return;
      }
      setStockWizardChrome("Add Stock", "How did these goods arrive?");
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>Choose source</h4>
          <p>Pick the path that matches how you got the stock.</p>
        </div>
        <div class="stock-source-grid">
          <button type="button" class="create-order-card" onclick="Stock.pickMode('vendor_order')">
            <span class="create-order-letter">P</span>
            <span class="create-order-card-body">
              <strong>Against placed order</strong>
              <span>Receive goods for an order you already placed with a vendor</span>
            </span>
            <span class="create-order-arrow">→</span>
          </button>
          <button type="button" class="create-order-card create-order-card-alt" onclick="Stock.pickMode('manual')">
            <span class="create-order-letter alt">R</span>
            <span class="create-order-card-body">
              <strong>Receive without order</strong>
              <span>Ad-hoc goods in godown — stock now, bill later from Received</span>
            </span>
            <span class="create-order-arrow">→</span>
          </button>
        </div>`;
      footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.closeWizard()">Cancel</button>`;
      return;
    }
    if (wizardStep === 2 && wizardMode === "offline_vendor") {
      if (!wizardProducts.length) {
        ctx.showLoading?.();
        try { wizardProducts = await ctx.api(`/vendor-orders/vendor/${wizardVendorId}/products`, {}, 0); }
        catch (e) { ctx.toast(e.message, "error"); wizardStep = 1; return renderWizard(); }
        finally { ctx.hideLoading?.(); }
      }
      document.querySelector("#stock-wizard .stock-wiz-modal")?.classList.remove("stock-wiz-wide");
      offlineQtyPopupId = null;
      const shown = filterOfflineProducts();
      const list = shown;
      const cartHtml = wizardLines.length ? `
        <div class="vo-wiz-cart">
          <div class="vo-wiz-cart-head">
            <strong>Receiving now</strong>
            <span>${wizardLines.length} product${wizardLines.length === 1 ? "" : "s"} · ${wizardLines.reduce((s, l) => s + (l.quantity_received || 0), 0)} qty</span>
          </div>
          <div class="vo-wiz-cart-chips">
            ${wizardLines.map(l => {
              const p = wizardProducts.find(x => x.id === l.catalog_product_id);
              return `<span class="vo-wiz-cart-chip">
                <span>${ctx.esc(p ? productIdLabel(p) : l.our_product_id)} × ${l.quantity_received || 0}</span>
                <button type="button" title="Remove" onclick="Stock.toggleOfflineProduct(${l.catalog_product_id}, false)">×</button>
              </span>`;
            }).join("")}
          </div>
        </div>` : "";
      setStockWizardChrome("Receive without order", "Step 2 — search, tick products, set qty");
      const emptyCatalog = !wizardProducts.length;
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head vo-wiz-step-head-row">
          <div>
            <h4>Products from ${ctx.esc(placedOrder?.vendor_label || "vendor")}</h4>
            <p>${emptyCatalog ? "This vendor has no products in catalog." : `${wizardProducts.length} product${wizardProducts.length === 1 ? "" : "s"} available — same picker as place order.`}</p>
          </div>
          <div class="vo-wiz-count-pill">${wizardLines.length} selected</div>
        </div>
        ${cartHtml}
        <div class="vo-wiz-search-wrap">
          <span class="vo-wiz-search-icon" aria-hidden="true">⌕</span>
          <input id="stock-offline-product-search" class="input vo-wiz-search" type="search" placeholder="Search product ID, vendor ID, category…" value="${ctx.esc(offlineProductSearch)}" oninput="Stock.onOfflineProductSearch(this.value)" onkeydown="Stock.onOfflineSearchKey(event)" onfocus="this.select()" autocomplete="off" />
          ${offlineProductSearch ? `<button type="button" class="vo-wiz-search-clear" onclick="Stock.onOfflineProductSearch('')">×</button>` : ""}
        </div>
        <div class="vo-wiz-product-meta">
          <span>Showing ${list.length} of ${wizardProducts.length}${offlineProductSearch ? " (search + selected)" : ""}</span>
        </div>
        <div class="vo-wiz-products">
          ${emptyCatalog ? HubUI.emptyState({ title: "No products yet", sub: "Add catalog products for this vendor first." })
            : list.length ? list.map(p => {
              const line = wizardLines.find(l => l.catalog_product_id === p.id);
              const qty = line ? (line.quantity_received || 1) : 1;
              const checked = !!line;
              const img = (p.image_urls && p.image_urls[0]) || "";
              return `<div class="vo-wiz-product ${checked ? "selected" : ""}" onclick="Stock.pickOfflineProduct(${p.id})">
                <div class="vo-wiz-product-main">
                  <input type="checkbox" ${checked ? "checked" : ""} onclick="event.stopPropagation();Stock.toggleOfflineProduct(${p.id}, this.checked)" />
                  ${thumb(img)}
                  <div class="vo-wiz-product-info">
                    <strong>${ctx.esc(productIdLabel(p))}</strong>
                    <span class="vo-wiz-product-sub">${p.category ? ctx.esc(p.category) : "Product"}</span>
                    <span class="vo-wiz-product-price">${fmtPrice(p.buying_price)}</span>
                  </div>
                </div>
                <div class="vo-wiz-qty" onclick="event.stopPropagation()">
                  <label>Qty</label>
                  <div class="vo-wiz-qty-controls">
                    <button type="button" class="vo-wiz-qty-btn" ${checked ? "" : "disabled"} onclick="Stock.bumpOfflineQty(${p.id}, -1)">−</button>
                    <input type="number" min="1" class="input vo-wiz-qty-input" data-qty-for="${p.id}" value="${qty}" ${checked ? "" : "disabled"} onchange="Stock.setOfflineLine(${p.id},'quantity_received',this.value)" onkeydown="Stock.onOfflineQtyKey(event)" onclick="event.stopPropagation()" />
                    <button type="button" class="vo-wiz-qty-btn" ${checked ? "" : "disabled"} onclick="Stock.bumpOfflineQty(${p.id}, 1)">+</button>
                  </div>
                </div>
              </div>`;
            }).join("") : HubUI.emptyState({
              title: "No matches",
              sub: `No products match “${offlineProductSearch}”.`,
              ctaHtml: `<button type="button" class="btn btn-secondary" onclick="Stock.onOfflineProductSearch('')">Clear search</button>`,
            })}
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
        <div class="vo-wiz-footer-mid">${wizardLines.length ? `${wizardLines.length} item${wizardLines.length === 1 ? "" : "s"} selected` : "Select at least one product"}</div>
        <button class="btn btn-primary" ${wizardLines.some(l => (l.quantity_received || 0) > 0) ? "" : "disabled"} onclick="Stock.wizardNext()">Next: Receipt →</button>`;
      setTimeout(() => focusPendingQty("stock-offline-product-search"), 30);
      return;
    }
    if (wizardStep === 3 && wizardMode === "offline_vendor") {
      document.querySelector("#stock-wizard .stock-wiz-modal")?.classList.remove("stock-wiz-wide");
      offlineQtyPopupId = null;
      setStockWizardChrome("Receive without order", "Step 3 — order receipt details");
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>${ctx.esc(placedOrder?.vendor_label || "Receive without order")}</h4>
          <p>${wizardLines.length} product${wizardLines.length === 1 ? "" : "s"} selected · enter receipt details next.</p>
        </div>
        <div class="table-wrap" style="max-height:28vh;overflow-y:auto;margin-bottom:16px;">
          <table class="data" style="font-size:13px;"><thead><tr><th>Product</th><th>Received</th></tr></thead><tbody>
            ${wizardLines.map(l => {
              const p = wizardProducts.find(x => x.id === l.catalog_product_id);
              return `<tr><td>${ctx.esc(p ? productIdLabel(p) : l.our_product_id)}</td><td>${l.quantity_received || 0}</td></tr>`;
            }).join("")}
          </tbody><tfoot><tr class="stock-qty-tfoot"><td>Total quantity</td><td>${lineQtySum(wizardLines, "quantity_received")}</td></tr></tfoot></table>
        </div>
        <div class="stock-bill-card">
          <h4>Order receipt</h4>
          <div class="stock-bill-grid">
            <div><label class="label">Order receipt number *</label>
              <input class="input" id="stock-order-receipt-number" value="${ctx.esc(receiptMeta.orderReceiptNumber || "")}" placeholder="Challan / delivery note #" required /></div>
            <div><label class="label">Receive date</label>
              <input type="date" class="input" id="stock-event-date" value="${ctx.esc(receiptMeta.eventDate || localToday())}" /></div>
            <div><label class="label">Upload receipt (optional)</label>
              <input type="file" class="input" accept=".pdf,image/*" onchange="Stock.setBillFile(this.files[0])" />
              ${billFile ? `<span class="stock-file-name">${ctx.esc(billFile.name)}</span>` : ""}
            </div>
            <div style="grid-column:1/-1;"><label class="label">Note</label>
              <input class="input" id="stock-receive-notes" value="${ctx.esc(receiptMeta.notes || "")}" placeholder="Optional note" /></div>
          </div>
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
        <button class="btn btn-primary" onclick="Stock.wizardNext()">Review →</button>`;
      setTimeout(() => document.getElementById("stock-order-receipt-number")?.focus(), 30);
      return;
    }
    if (wizardStep === 2 && wizardMode === "receive_goods") {
      if (!placedOrder) {
        bodyEl.innerHTML = HubUI.emptyState({ title: "Loading…", sub: "Loading placed order…" });
        footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>`;
        ctx.showLoading?.();
        try {
          placedOrder = await ctx.api(`/stock/vendor-order/${wizardVendorId}/placed`, {}, 0);
          wizardLines = (placedOrder.lines || []).map(l => ({
            catalog_product_id: l.catalog_product_id,
            our_product_id: l.our_product_id,
            vendor_product_id: l.vendor_product_id || "",
            category: l.category || "",
            quantity_ordered: l.quantity_remaining,
            buying_price: l.buying_price != null && l.buying_price !== ""
              ? l.buying_price
              : null,
            unit: l.unit,
            image_urls: l.image_urls,
            quantity_received: 0,
            quantity_billed: 0,
          }));
          if (receivePrefill?.catalog_product_id) {
            const qty = Math.max(1, parseInt(String(receivePrefill.quantity || receivePrefill.pending_qty || 1), 10) || 1);
            const match = wizardLines.find(l => l.catalog_product_id === receivePrefill.catalog_product_id);
            if (match) {
              match.quantity_received = Math.min(qty, match.quantity_ordered || qty);
              wizardLines = [match];
            }
            receivePrefill = null;
          }
        } catch (e) { ctx.toast(e.message, "error"); wizardStep = 1; return renderWizard(); }
        finally { ctx.hideLoading?.(); }
      }
      if (!wizardLines.length) {
        setStockWizardChrome("Receive Goods", "Nothing pending");
        bodyEl.innerHTML = HubUI.emptyState({ title: "Nothing to receive", sub: "No placed lines yet to receive for this vendor." });
        footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>`;
        return;
      }
      setStockWizardChrome("Receive Goods", "Step 2 — enter received quantities");
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>${ctx.esc(placedOrder.vendor_label)}</h4>
          <p>Enter qty received. Order receipt number is required. File/note optional. Bill later from Received.</p>
        </div>
        <div class="stock-receive-table-wrap">
          <table class="data stock-receive-table"><thead><tr>
            <th></th><th>Product</th><th>Category</th><th>Pending</th><th>Price</th><th>Received</th>
          </tr></thead><tbody>
            ${wizardLines.map((l, i) => {
              const img = (l.image_urls && l.image_urls[0]) || "";
              return `<tr>
                <td>${thumb(img)}</td>
                <td><strong>${ctx.esc(productIdLabel(l))}</strong></td>
                <td>${ctx.esc(l.category || "—")}</td>
                <td>${l.quantity_ordered}</td>
                <td>${fmtPrice(l.buying_price)}</td>
                <td><input type="number" min="0" class="input stock-qty-input" value="${l.quantity_received || ""}" onchange="Stock.setLine(${i},'quantity_received',this.value)" /></td>
              </tr>`;
            }).join("")}
          </tbody>
          <tfoot><tr class="stock-qty-tfoot">
            <td colspan="3">Total qty</td>
            <td>${wizardQtySum("quantity_ordered")}</td>
            <td></td>
            <td id="stock-tfoot-received">${wizardQtySum("quantity_received")}</td>
          </tr></tfoot></table>
        </div>
        <div class="stock-bill-card" style="margin-top:16px;">
          <h4>Order receipt</h4>
          <div class="stock-bill-grid">
            <div><label class="label">Order receipt number *</label>
              <input class="input" id="stock-order-receipt-number" value="${ctx.esc(receiptMeta.orderReceiptNumber || "")}" placeholder="Challan / delivery note #" required /></div>
            <div><label class="label">Receive date</label>
              <input type="date" class="input" id="stock-event-date" value="${ctx.esc(receiptMeta.eventDate || localToday())}" /></div>
            <div><label class="label">Upload receipt (optional)</label>
              <input type="file" class="input" accept=".pdf,image/*" onchange="Stock.setBillFile(this.files[0])" />
              ${billFile ? `<span class="stock-file-name">${ctx.esc(billFile.name)}</span>` : ""}
            </div>
            <div style="grid-column:1/-1;"><label class="label">Note</label>
              <input class="input" id="stock-receive-notes" value="${ctx.esc(receiptMeta.notes || "")}" placeholder="Optional note" /></div>
          </div>
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
        <button class="btn btn-primary" onclick="Stock.wizardNext()">Review →</button>`;
      return;
    }
    if (wizardStep === 2 && wizardMode === "bill_received" && !wizardReceiptId) {
      if (!wizardPendingBillList) {
        bodyEl.innerHTML = HubUI.emptyState({ title: "Loading…", sub: "Loading pending receipts…" });
        footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>`;
        ctx.showLoading?.();
        try { wizardPendingBillList = await ctx.api(`/stock/vendor-order/${wizardVendorId}/received`, {}, 0); }
        catch (e) { ctx.toast(e.message, "error"); wizardStep = 1; return renderWizard(); }
        finally { ctx.hideLoading?.(); }
      }
      const receipts = wizardPendingBillList.receipts || [];
      setStockWizardChrome("Bill Order", "Step 2 — pick a receipt to bill");
      if (!receipts.length) {
        bodyEl.innerHTML = HubUI.emptyState({ title: "Nothing to bill", sub: "No pending receipts for this vendor." });
        footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>`;
        return;
      }
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>${ctx.esc(wizardPendingBillList.vendor_label)}${wizardPendingBillList.vendor_alias ? ` <span style="color:var(--muted);font-weight:500;">(${ctx.esc(wizardPendingBillList.vendor_alias)})</span>` : ""}</h4>
          <p>${receipts.length} receipt${receipts.length === 1 ? "" : "s"} pending bill. One bill per receipt.</p>
        </div>
        <div class="vo-wiz-vendor-list">
          ${receipts.map(r => `
            <button type="button" class="vo-wiz-vendor-card" onclick="Stock.selectPendingReceipt(${r.receipt_id})">
              <span class="vo-wiz-vendor-letter">#${r.receipt_id}</span>
              <span class="vo-wiz-vendor-meta">
                <strong>${ctx.esc(r.display_name || r.order_receipt_number || `Receipt #${r.receipt_id}`)}</strong>
                <span>${ctx.fmtDate?.(r.display_date || r.value_date || r.created_at) || "—"} · ${r.line_count} line${r.line_count === 1 ? "" : "s"} · ${r.total_quantity} qty</span>
              </span>
              <span class="vo-wiz-vendor-meta" style="text-align:right;">
                <strong>${r.expected_bill_amount != null ? fmtPrice(r.expected_bill_amount) : "—"}</strong>
                ${r.expected_extra_cash ? `<span>+ ${fmtPrice(r.expected_extra_cash)} extra cash</span>` : ""}
              </span>
            </button>`).join("")}
        </div>`;
      footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>`;
      return;
    }
    if (wizardStep === 2 && wizardMode === "bill_received" && wizardReceiptId) {
      if (!wizardLines.length) {
        setStockWizardChrome("Bill Order", "Nothing to bill");
        bodyEl.innerHTML = HubUI.emptyState({ title: "Nothing to bill", sub: "This receipt has no lines." });
        footerEl.innerHTML = `<button class="btn btn-secondary" onclick="Stock.changePendingReceipt()">← Choose different receipt</button>`;
        return;
      }
      setStockWizardChrome("Bill Order", "Step 2 — enter billed quantities & bill total");
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>${ctx.esc(placedOrder.vendor_label)}${placedOrder.vendor_alias ? ` <span style="color:var(--muted);font-weight:500;">(${ctx.esc(placedOrder.vendor_alias)})</span>` : ""} — receipt #${placedOrder.receipt_id}${placedOrder.order_receipt_number ? ` (${ctx.esc(placedOrder.order_receipt_number)})` : ""}</h4>
          <p>Billed qty defaults to received — edit if the vendor's bill differs. Total bill amount defaults to the calculated expectation — edit to match the paper invoice.</p>
        </div>
        <div class="stock-receive-table-wrap">
          <table class="data stock-receive-table"><thead><tr>
            <th></th><th>Product</th><th style="text-align:right;">Received</th><th style="text-align:right;">Price</th><th style="text-align:right;">Billed qty</th><th style="text-align:right;">Rate billed</th><th style="text-align:right;">Amount billed</th>
          </tr></thead><tbody>
            ${wizardLines.map((l, i) => {
              const img = (l.image_urls && l.image_urls[0]) || "";
              const diff = (l.quantity_billed || 0) - (l.quantity_received || 0);
              const diffBadge = diff !== 0
                ? `<span class="badge ${diff > 0 ? "badge-amber" : "badge-blue"}" style="font-size:10px;margin-left:4px;">${diff > 0 ? "+" : ""}${diff}</span>`
                : "";
              return `<tr>
                <td>${thumb(img)}</td>
                <td><strong>${ctx.esc(productIdLabel(l))}</strong>${diffBadge}</td>
                <td style="text-align:right;color:var(--muted);">${l.quantity_received || 0}</td>
                <td style="text-align:right;">${fmtPrice(l.buying_price)}</td>
                <td style="text-align:right;"><input type="number" min="0" class="input stock-qty-input stock-billed-input" value="${l.quantity_billed ?? ""}" onchange="Stock.setLine(${i},'quantity_billed',this.value)" /></td>
                <td style="text-align:right;"><input type="number" min="0" step="0.01" class="input stock-qty-input stock-rate-input" value="${billedRateInputValue(l)}" placeholder="${l._priceHidden ? "Enter rate" : ""}" onchange="Stock.setLineRate(${i},this.value)" title="${l._priceHidden ? "Cost hidden — type the vendor's paper rate" : "Defaults to our catalog rate — edit if the vendor's paper bill states a different rate"}" /></td>
                <td style="text-align:right;"><input type="number" min="0" step="0.01" class="input stock-qty-input stock-amount-input" value="${billedAmountInputValue(l)}" placeholder="${l._priceHidden ? "Enter amount" : ""}" onchange="Stock.setLineAmount(${i},this.value)" title="${l._priceHidden ? "Cost hidden — type the vendor's paper amount" : "Defaults to qty x our rate — edit if the vendor's paper bill states a different rate/amount for this line"}" /></td>
              </tr>`;
            }).join("")}
          </tbody>
          <tfoot><tr class="stock-qty-tfoot">
            <td></td>
            <td>Total qty / amount</td>
            <td style="text-align:right;" id="stock-tfoot-received">${wizardQtySum("quantity_received")}</td>
            <td></td>
            <td style="text-align:right;" id="stock-tfoot-billed">${wizardQtySum("quantity_billed")}</td>
            <td></td>
            <td style="text-align:right;" id="stock-tfoot-amount">${fmtPrice(wizardQtySum("billed_amount"))}</td>
          </tr></tfoot></table>
        </div>
        ${renderVendorBillingTermsCard()}
        <div class="stock-bill-card">
          <h4>Vendor bill</h4>
          <div class="stock-bill-grid">
            <div><label class="label">Bill number</label><input class="input" id="stock-bill-number" value="${ctx.esc(receiptMeta.billNumber)}" placeholder="Vendor bill #" /></div>
            <div><label class="label">Bill date</label>
              <input type="date" class="input" id="stock-event-date" value="${ctx.esc(receiptMeta.eventDate || localToday())}" /></div>
            <div class="stock-bill-total"><label class="label">Total bill amount *</label>
              <input type="number" min="0" step="0.01" class="input" id="stock-total-billed" value="${ctx.esc(receiptMeta.totalBilledAmount)}" placeholder="₹ total on vendor bill" required /></div>
            <div><label class="label">Billing % (this bill only)</label>
              <input type="number" min="0.01" max="100" step="0.01" class="input" id="stock-billing-pct" value="${ctx.esc(receiptMeta.billingPct)}" title="Override the vendor's usual billing % for this bill only — vendor profile stays unchanged" /></div>
            ${billingTerms?.gst_included ? `<div><label class="label">GST % (this bill only)</label>
              <input type="number" min="0" max="100" step="0.01" class="input" id="stock-gst-pct" value="${ctx.esc(receiptMeta.gstPct)}" title="Override the vendor's usual GST % for this bill only — vendor profile stays unchanged" /></div>` : ""}
            <div><label class="label">Upload bill</label>
              <input type="file" class="input" accept=".pdf,image/*" onchange="Stock.setBillFile(this.files[0])" />
              ${billFile ? `<span class="stock-file-name">${ctx.esc(billFile.name)}</span>` : ""}
            </div>
            <div style="grid-column:1/-1;"><label class="label">Note</label>
              <input class="input" id="stock-receive-notes" value="${ctx.esc(receiptMeta.notes || "")}" placeholder="Optional note" /></div>
          </div>
        </div>`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.changePendingReceipt()">← Choose different receipt</button>
        <button class="btn btn-primary" onclick="Stock.wizardNext()">Debit Notes →</button>`;
      return;
    }
    if ((wizardStep === 3 && wizardMode === "receive_goods")
      || (wizardStep === 4 && wizardMode === "offline_vendor")) {
      document.querySelector("#stock-wizard .stock-wiz-modal")?.classList.remove("stock-wiz-wide");
      saveReceiptMeta();
      const active = receivedLines();
      const vendorLabel = placedOrder?.vendor_label
        || (wizardMode === "offline_vendor" ? "Receive without order" : "");
      setStockWizardChrome("Review & Submit", wizardMode === "offline_vendor"
        ? "Confirm receive — stock now, bill later"
        : "Confirm goods received");
      bodyEl.innerHTML = `
        <div class="vo-wiz-step-head">
          <h4>${ctx.esc(vendorLabel)}</h4>
          <p>Stock will increase. No AP yet — bill from Received when ready.</p>
        </div>
        <div class="review-block" style="margin-bottom:12px;">
          ${ctx.reviewRow("Order receipt #", receiptMeta.orderReceiptNumber || "—")}
          ${ctx.reviewRow("Receive date", receiptMeta.eventDate || localToday())}
          ${receiptMeta.notes ? ctx.reviewRow("Note", receiptMeta.notes) : ""}
        </div>
        <table class="data" style="font-size:13px;"><thead><tr><th>Product</th><th>Received</th></tr></thead><tbody>
          ${active.map(l => {
            const p = wizardProducts.find(x => x.id === l.catalog_product_id);
            const id = p ? productIdLabel(p) : (l.our_product_id || l.catalog_product_id);
            return `<tr><td>${ctx.esc(id)}</td><td>${l.quantity_received || 0}</td></tr>`;
          }).join("")}
        </tbody><tfoot><tr class="stock-qty-tfoot"><td>Total quantity</td><td>${lineQtySum(active, "quantity_received")}</td></tr></tfoot></table>
        ${billFile ? `<p class="vo-muted">Receipt file: ${ctx.esc(billFile.name)}</p>` : ""}`;
      footerEl.innerHTML = `
        <button class="btn btn-secondary" onclick="Stock.wizardBack()">← Back</button>
        <button class="btn btn-primary btn-lg" onclick="Stock.submitReceipt()">Confirm receive</button>`;
      return;
    }
    if (wizardStep === 3 && wizardMode === "bill_received") {
      setStockWizardChrome("Debit Notes", "Auto-suggested based on billed vs received");
      if (!billPreview) await refreshBillPreview();
      renderDebitNoteStep(bodyEl, footerEl);
      return;
    }
    if (wizardStep === 4 && wizardMode === "bill_received") {
      setStockWizardChrome("Review & Submit", "Confirm bill");
      renderReviewStep(bodyEl, footerEl);
      return;
    }
  }
