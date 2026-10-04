  async function openReceiptDoc(receiptId) {
    if (!receiptId) return;
    ctx.showLoading?.();
    try {
      const doc = await ctx.api(`/stock/receipts/${receiptId}/document`, {}, 0);
      const url = doc?.document_url;
      if (!url) throw new Error("Receipt PDF not available yet");
      const safe = ctx.esc(url);
      OrderMenus.openConfirm({
        title: "Bill receipt",
        message: "Print or download this goods receipt.",
        detailsHtml: `<div class="doc-actions">
          <button type="button" class="btn btn-primary" onclick="Stock.openReceiptPdf('${safe}', true)">Print</button>
          <button type="button" class="btn btn-secondary" onclick="Stock.openReceiptPdf('${safe}', false)">Download / View</button>
        </div>`,
        confirmLabel: "Close",
        onConfirm: async () => {},
        ctx,
      });
    } catch (e) { ctx.toast(e.message || "PDF not available", "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function _refreshAfterPlacedLineEdit(orderId) {
    ctx.invalidateCache?.("/vendor-orders");
    if (hubExpandedVendorId) {
      const vid = typeof hubExpandedVendorId === "number" ? hubExpandedVendorId : null;
      if (vid) {
        hubExpandCache[`placed-${vid}`] = await ctx.api(`/vendor-orders/${orderId}?view=default`, {}, 0);
      } else if (orderId) {
        const detail = await ctx.api(`/vendor-orders/${orderId}?view=default`, {}, 0);
        hubExpandCache[`placed-${detail.vendor_id}`] = detail;
      }
    }
    await loadList();
    if (detailVendorId) await openDetail(orderId || 0, "placed", detailVendorId);
  }

  async function editPlacedLine(lineId, currentQty, orderId) {
    const raw = prompt("Edit placed quantity:", String(currentQty ?? 1));
    if (raw == null) return;
    const qty = Math.max(1, parseInt(String(raw), 10) || 0);
    if (!qty) return ctx.toast("Enter a valid quantity", "error");
    ctx.showLoading?.();
    try {
      await ctx.api(`/vendor-orders/lines/${lineId}`, {
        method: "PATCH",
        body: JSON.stringify({ quantity: qty }),
      });
      ctx.toast("Placed line updated", "success");
      await _refreshAfterPlacedLineEdit(orderId);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function deletePlacedLine(lineId, orderId) {
    if (!confirm("Remove this product line from the placed order?")) return;
    ctx.showLoading?.();
    try {
      await ctx.api(`/vendor-orders/lines/${lineId}`, { method: "DELETE" });
      ctx.toast("Line removed", "success");
      await _refreshAfterPlacedLineEdit(orderId);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function receiveVendor(vendorId) {
    if (!vendorId) return;
    Stock.openReceiveForVendor(vendorId);
  }

  function billVendor(vendorId) {
    if (!vendorId) return;
    Stock.openBillForVendor(vendorId);
  }

  function billOpenLine(catalogProductId, qty) {
    if (!detailVendorId) return;
    Stock.openBillForVendor(detailVendorId, { catalog_product_id: catalogProductId, quantity: qty });
  }

  function receiveOrder() {
    if (!detailVendorId) return;
    Stock.openReceiveForVendor(detailVendorId);
  }

  function billOrder() {
    if (!detailVendorId) return;
    Stock.openBillForVendor(detailVendorId);
  }

  function _detailVendorId() { return detailVendorId; }

