/** Shared create-order menu + batch close modal */
const OrderMenus = (() => {
  let createHandler = null;
  let closeHandler = null;
  let closeItems = [];
  let closeSelected = new Set();
  let confirmHandler = null;

  function openCreate(handler) {
    createHandler = handler;
    document.getElementById("order-create-menu")?.classList.remove("hidden");
  }

  function closeCreate() {
    document.getElementById("order-create-menu")?.classList.add("hidden");
    createHandler = null;
  }

  function pickNew() {
    const h = createHandler;
    closeCreate();
    if (h?.onNew) h.onNew();
  }

  function pickOffline() {
    const h = createHandler;
    closeCreate();
    if (h?.onOffline) h.onOffline();
  }

  function openClose({ title, items, onSubmit, ctx }) {
    closeHandler = { onSubmit, ctx };
    closeItems = items || [];
    closeSelected = new Set();
    document.getElementById("close-order-title").textContent = title || "Close Order";
    renderCloseBody(ctx);
    document.getElementById("close-order-modal")?.classList.remove("hidden");
  }

  function renderCloseBody(ctx) {
    const body = document.getElementById("close-order-body");
    const footer = document.getElementById("close-order-footer");
    if (!body || !footer) return;
    if (!closeItems.length) {
      body.innerHTML = `<div class="empty-state"><p>Nothing to close in this view.</p></div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="OrderMenus.closeBatch()">Close</button>`;
      return;
    }
    body.innerHTML = `
      <p style="margin:0 0 12px;font-size:13px;color:var(--muted);">Select rows to close. You can pick across vendors/customers.</p>
      <table class="data"><thead><tr>
        <th style="width:36px;"><input type="checkbox" onchange="OrderMenus.toggleAll(this.checked)" /></th>
        <th>Party</th><th>Item</th><th>Detail</th><th>Qty</th><th>Amount</th>
      </tr></thead><tbody>
        ${closeItems.map(it => `<tr>
          <td><input type="checkbox" ${closeSelected.has(it.id) ? "checked" : ""} onchange="OrderMenus.toggleItem(${it.id}, this.checked)" /></td>
          <td>${ctx.esc(it.party || "—")}</td>
          <td><strong>${ctx.esc(it.label || "")}</strong></td>
          <td style="font-size:12px;color:var(--muted);">${ctx.esc(it.sublabel || "—")}</td>
          <td>${it.quantity != null ? it.quantity : "—"}</td>
          <td>${it.amount ? "₹" + Number(it.amount).toLocaleString("en-IN") : "—"}</td>
        </tr>`).join("")}
      </tbody></table>
      <label class="label" style="margin-top:16px;">Reason (required)</label>
      <textarea class="input" id="close-order-reason" rows="2" style="width:100%;"></textarea>`;
    footer.innerHTML = `
      <button class="btn btn-secondary" onclick="OrderMenus.closeBatch()">Cancel</button>
      <button class="btn btn-primary" onclick="OrderMenus.submitClose()">Close Selected</button>`;
  }

  function toggleItem(id, checked) {
    if (checked) closeSelected.add(id);
    else closeSelected.delete(id);
  }

  function toggleAll(checked) {
    closeSelected = checked ? new Set(closeItems.map(i => i.id)) : new Set();
    renderCloseBody(closeHandler?.ctx || {});
  }

  function closeBatch() {
    document.getElementById("close-order-modal")?.classList.add("hidden");
    closeHandler = null;
    closeItems = [];
    closeSelected = new Set();
  }

  async function submitClose() {
    const reason = (document.getElementById("close-order-reason")?.value || "").trim();
    if (!reason) return closeHandler?.ctx?.toast?.("Enter a reason", "error");
    if (!closeSelected.size) return closeHandler?.ctx?.toast?.("Select at least one row", "error");
    const ids = [...closeSelected];
    const h = closeHandler;
    closeHandler?.ctx?.showLoading?.();
    try {
      await h.onSubmit(ids, reason);
      closeBatch();
    } catch (e) {
      closeHandler?.ctx?.toast?.(e.message, "error");
    } finally {
      closeHandler?.ctx?.hideLoading?.();
    }
  }

  function openConfirm({ title, message, detailsHtml, confirmLabel, danger, onConfirm, ctx, requireReason, reasonLabel }) {
    confirmHandler = { onConfirm, ctx, requireReason: !!requireReason };
    document.getElementById("vo-confirm-title").textContent = title || "Confirm";
    const body = document.getElementById("vo-confirm-body");
    const footer = document.getElementById("vo-confirm-footer");
    if (body) {
      body.innerHTML = `
        ${message ? `<p style="margin:0 0 12px;font-size:13px;color:var(--muted);">${ctx.esc(message)}</p>` : ""}
        ${detailsHtml || ""}
        ${requireReason ? `<label class="label" style="margin-top:14px;">${ctx.esc(reasonLabel || "Note (required)")}</label>
          <textarea class="input" id="vo-confirm-reason" rows="3" style="width:100%;" placeholder="Why?"></textarea>` : ""}`;
    }
    const btnClass = danger ? "btn btn-danger" : "btn btn-primary";
    if (footer) {
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="OrderMenus.closeConfirm()">Cancel</button>
        <button class="${btnClass}" onclick="OrderMenus.submitConfirm()">${ctx.esc(confirmLabel || "Confirm")}</button>`;
    }
    document.getElementById("vo-confirm-modal")?.classList.remove("hidden");
    if (requireReason) setTimeout(() => document.getElementById("vo-confirm-reason")?.focus(), 50);
  }

  function closeConfirm() {
    document.getElementById("vo-confirm-modal")?.classList.add("hidden");
    confirmHandler = null;
  }

  async function submitConfirm() {
    const h = confirmHandler;
    if (!h?.onConfirm) return closeConfirm();
    let reason = "";
    if (h.requireReason) {
      reason = (document.getElementById("vo-confirm-reason")?.value || "").trim();
      if (!reason) return h.ctx?.toast?.("Enter a note", "error");
    }
    h.ctx?.showLoading?.();
    try {
      await h.onConfirm(reason);
      closeConfirm();
    } catch (e) {
      h.ctx?.toast?.(e.message, "error");
    } finally {
      h.ctx?.hideLoading?.();
    }
  }

  return { openCreate, closeCreate, pickNew, pickOffline, openClose, closeBatch, toggleItem, toggleAll, submitClose, openConfirm, closeConfirm, submitConfirm };
})();
