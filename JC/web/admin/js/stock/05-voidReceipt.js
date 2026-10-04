  function voidReceipt(receiptId, vendorId) {
    // Styled confirm (details table + optional-reason textarea) instead of a bare
    // native prompt() — matches every other void/cancel/close action in the buying
    // flow (VendorOrders.cancelPlacement/closeBilledPlacement/etc.) while keeping the
    // reason genuinely optional, matching the backend's void contract.
    const rows = [["Receipt", `#${receiptId}`]];
    OrderMenus.openConfirm({
      title: "Void receipt",
      message: "Stock and AP will be reversed — moves to recycle bin, can be restored.",
      detailsHtml: `<table class="data" style="font-size:13px;margin:0;"><tbody>
        ${rows.map(([k, v]) => `<tr><td style="color:var(--muted);width:40%;">${ctx.esc(k)}</td><td><strong>${v}</strong></td></tr>`).join("")}
      </tbody></table>`,
      confirmLabel: "Void",
      danger: true,
      optionalReason: true,
      reasonLabel: "Void reason (optional)",
      ctx,
      onConfirm: async (reason) => {
        await ctx.api(`/stock/receipts/${receiptId}/void`, { method: "POST", body: JSON.stringify({ reason: reason || null }) });
        ctx.invalidateCache?.("/stock");
        ctx.invalidateCache?.("/vendor-orders");
        ctx.invalidateCache?.("/accounts-payable");
        ctx.closeDetail?.();
        ctx.toast("Voided — moved to recycle bin", "success");
        if (typeof VendorOrders !== "undefined" && VendorOrders.refreshIfOpen) VendorOrders.refreshIfOpen(vendorId);
        await load();
      },
    });
  }
  async function editThreshold(catalogProductId, current) {
    const raw = prompt("Low stock threshold (qty below this = low stock):", String(current ?? 5));
    if (raw == null) return;
    const val = Math.max(0, parseInt(raw, 10) || 0);
    ctx.showLoading?.();
    try {
      await ctx.api(`/stock/products/${catalogProductId}/threshold`, {
        method: "PATCH",
        body: JSON.stringify({ low_stock_threshold: val }),
      });
      ctx.invalidateCache?.("/stock");
      ctx.toast("Threshold updated", "success");
      if (typeof Products !== "undefined" && Products.openProductDetail) {
        await Products.openProductDetail(catalogProductId, "stock");
        Products.refreshHub?.();
      } else {
        openDetail(catalogProductId);
      }
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
  function adjustStock(catalogProductId, currentQty) {
    // Single modal with both fields — was a 2-prompt() chain (qty, then reason),
    // which felt disjointed and lost the qty context on the second popup.
    document.getElementById("modal-title").textContent = "Adjust stock";
    document.getElementById("modal-body").innerHTML = `
      <p class="vo-muted" style="margin:0 0 10px;">Current on hand: <strong>${currentQty ?? 0}</strong></p>
      <label class="label">Quantity change (e.g. 5 to add, -3 to remove)</label>
      <input class="input" id="stock-adj-delta" type="number" step="1" style="width:100%;margin-bottom:10px;" />
      <label class="label">Reason (required)</label>
      <textarea class="input" id="stock-adj-reason" rows="3" style="width:100%;"></textarea>`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" id="stock-adj-ok">Save</button>`;
    document.getElementById("stock-adj-ok").onclick = async () => {
      const delta = parseInt(String(document.getElementById("stock-adj-delta").value || "").trim(), 10);
      if (!Number.isFinite(delta) || delta === 0) return ctx.toast("Enter a non-zero whole number", "error");
      const reasonTrimmed = (document.getElementById("stock-adj-reason").value || "").trim();
      if (!reasonTrimmed) return ctx.toast("Reason is required", "error");
      App.closeModal();
      ctx.showLoading?.();
      try {
        await ctx.api(`/stock/products/${catalogProductId}/adjust`, {
          method: "POST",
          body: JSON.stringify({ quantity_delta: delta, reason: reasonTrimmed }),
        });
        ctx.invalidateCache?.("/stock");
        ctx.toast(`Stock ${delta > 0 ? "increased" : "decreased"} by ${Math.abs(delta)}`, "success");
        if (typeof Products !== "undefined" && Products.openProductDetail) {
          await Products.openProductDetail(catalogProductId, "stock");
          Products.refreshHub?.();
        } else {
          openDetail(catalogProductId);
        }
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    };
    document.getElementById("modal").classList.remove("hidden");
  }
  async function setSellingPrice(catalogProductId, current) {
    const raw = prompt("Selling price (₹). Leave blank to clear:", current == null ? "" : String(current));
    if (raw == null) return;
    const trimmed = String(raw).trim();
    let selling_price = null;
    if (trimmed !== "") {
      const n = parseFloat(trimmed);
      if (Number.isNaN(n) || n < 0) return ctx.toast("Enter a valid price", "error");
      selling_price = n;
    }
    ctx.showLoading?.();
    try {
      await ctx.api(`/stock/products/${catalogProductId}/selling-price`, {
        method: "PATCH",
        body: JSON.stringify({ selling_price }),
      });
      ctx.invalidateCache?.("/stock");
      ctx.invalidateCache?.("/catalog");
      ctx.toast("Sell price updated", "success");
      if (typeof Products !== "undefined" && Products.openProductDetail) {
        await Products.openProductDetail(catalogProductId, "stock");
        Products.refreshHub?.();
      } else {
        openDetail(catalogProductId);
      }
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }
