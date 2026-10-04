/** Setup — Payment modes for customer collect */
const PaymentModes = (() => {
  let ctx = {};
  let modes = [];
  let searchQ = "";
  let editingId = null;

  function init(context) { ctx = context; }

  function canWrite() { return !!ctx.isAdmin?.(); }

  async function load() {
    ctx.showLoading?.();
    try {
      modes = await ctx.api("/payment-modes", {}, 0) || [];
      const btn = document.getElementById("paymodes-new-btn");
      if (btn) btn.classList.toggle("hidden", !canWrite());
      const count = document.getElementById("hub-paymodes-count");
      if (count) count.textContent = `${modes.filter(m => m.is_active).length} active`;
      render();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function setSearch(val) {
    searchQ = val || "";
    render();
  }

  function filtered() {
    const q = searchQ.trim().toLowerCase();
    if (!q) return modes;
    return modes.filter(m => String(m.name || "").toLowerCase().includes(q));
  }

  function render() {
    const el = document.getElementById("payment-modes-root");
    if (!el) return;
    const caret = (typeof OrdersUI !== "undefined" && OrdersUI.captureSearchCaret)
      ? OrdersUI.captureSearchCaret("pm-search") : null;
    const write = canWrite();
    const list = filtered();

    if (!modes.length) {
      el.innerHTML = HubUI.emptyState({
        title: "No payment modes yet",
        sub: "Add Cash, UPI, Cheque, NEFT… then pick one when collecting.",
        ctaHtml: write ? `<button class="btn btn-primary btn-lg" onclick="PaymentModes.openWizard()">+ Add mode</button>` : "",
      });
      return;
    }

    el.innerHTML = `
      <div class="setup-search-slot">
        ${HubUI.searchBar({
          id: "pm-search",
          value: searchQ,
          placeholder: "Search modes…",
          oninput: "PaymentModes.setSearch(this.value)",
        })}
      </div>
      ${!list.length
        ? HubUI.emptyState({ title: "No matches", sub: "Clear search." })
        : `<div class="ord-card-list">${list.map(m => HubUI.partyCard({
          title: m.name,
          meta: `Sort ${m.sort_order}`,
          pillHtml: m.is_active ? HubUI.pill("Active", "ok") : HubUI.pill("Off", "muted"),
          primaryLabel: write ? "Edit" : null,
          primaryOnclick: write ? `PaymentModes.openEdit(${m.id})` : "",
          moreItems: write ? [{ label: "Delete", onclick: `PaymentModes.deleteMode(${m.id})`, danger: true }] : [],
          rowOnclick: write ? `PaymentModes.openEdit(${m.id})` : "",
          canWrite: write,
        })).join("")}</div>`}`;
    if (caret && typeof OrdersUI !== "undefined") OrdersUI.restoreSearchCaret("pm-search", caret);
  }

  function openWizard() {
    editingId = null;
    openForm("New payment mode", "", true, 0);
  }

  function openEdit(id) {
    const m = modes.find(x => x.id === id);
    if (!m) return;
    editingId = id;
    openForm("Edit payment mode", m.name, !!m.is_active, m.sort_order || 0);
  }

  function openForm(title, name, active, sort) {
    document.getElementById("modal-title").textContent = title;
    document.getElementById("modal-body").innerHTML = `
      <label class="label">Name</label>
      <input class="input" id="pm-name" value="${ctx.esc(name)}" placeholder="Cash, UPI, Cheque…" style="margin-bottom:12px;" />
      <label class="label">Sort order</label>
      <input type="number" class="input" id="pm-sort" value="${sort}" style="margin-bottom:12px;" />
      <label style="display:flex;align-items:center;gap:8px;font-size:14px;">
        <input type="checkbox" id="pm-active" ${active ? "checked" : ""} /> Active
      </label>`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="PaymentModes.save()">${editingId ? "Save" : "Create"}</button>`;
    document.getElementById("modal").classList.remove("hidden");
  }

  async function save() {
    const name = (document.getElementById("pm-name")?.value || "").trim();
    const sort_order = parseInt(document.getElementById("pm-sort")?.value || "0", 10) || 0;
    const is_active = !!document.getElementById("pm-active")?.checked;
    if (!name) return ctx.toast("Enter mode name", "error");
    ctx.showLoading?.();
    try {
      const body = JSON.stringify({ name, is_active, sort_order });
      if (editingId) {
        await ctx.api(`/payment-modes/${editingId}`, { method: "PATCH", body });
        ctx.toast("Mode updated", "success");
      } else {
        await ctx.api("/payment-modes", { method: "POST", body });
        ctx.toast("Mode created", "success");
      }
      App.closeModal();
      await load();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function deleteMode(id) {
    const m = modes.find(x => x.id === id);
    if (!confirm(`Delete mode “${m?.name || id}”?`)) return;
    ctx.showLoading?.();
    try {
      await ctx.api(`/payment-modes/${id}`, { method: "DELETE" });
      ctx.toast("Deleted", "success");
      await load();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  return { init, load, setSearch, openWizard, openEdit, save, deleteMode };
})();
