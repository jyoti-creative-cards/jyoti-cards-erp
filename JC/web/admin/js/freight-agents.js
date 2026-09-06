/** Setup — Freight agents list / create / edit */
const FreightAgentsSetup = (() => {
  let ctx = {};
  let agents = [];
  let searchQ = "";
  let editingId = null;

  function init(context) { ctx = context; }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  // balance_due/advance_left come back as the literal string "—" (not a number,
  // not null) when the viewer lacks any of ap.read/ap.write/finance.write/
  // vendor_orders.write/customer_orders.write (see freight_agents.py's
  // _can_see_freight_money). `Number("—") || 0` used to silently coerce that to a
  // real 0, flipping the status pill to a reassuring "OK" for an agent who may
  // actually have a large real due.
  function moneyOrNull(raw) {
    if (raw === "—") return null;
    if (raw == null || raw === "") return 0;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }

  function canWrite() {
    // API is admin-only for create/edit
    return !!ctx.isAdmin?.();
  }

  async function load() {
    ctx.showLoading?.();
    try {
      agents = await ctx.api("/freight-agents", {}, 0);
      if (!Array.isArray(agents)) agents = [];
      const btn = document.getElementById("freight-new-btn");
      if (btn) btn.classList.toggle("hidden", !canWrite());
      render();
      const count = document.getElementById("hub-freight-count");
      if (count) count.textContent = `${agents.length} agent${agents.length === 1 ? "" : "s"}`;
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function setSearch(val) {
    searchQ = val || "";
    render();
  }

  function filtered() {
    const q = searchQ.trim().toLowerCase();
    if (!q) return agents;
    return agents.filter(a =>
      String(a.name || "").toLowerCase().includes(q)
      || String(a.notes || "").toLowerCase().includes(q)
    );
  }

  function render() {
    const el = document.getElementById("freight-agents-root");
    if (!el) return;
    const caret = (typeof OrdersUI !== "undefined" && OrdersUI.captureSearchCaret)
      ? OrdersUI.captureSearchCaret("fa-search") : null;
    const list = filtered();
    const write = canWrite();

    if (!agents.length) {
      el.innerHTML = HubUI.emptyState({
        title: "No freight agents yet",
        sub: "Create agents here, pick them on customer orders, settle in Finance.",
        ctaHtml: write ? `<button class="btn btn-primary btn-lg" onclick="FreightAgentsSetup.openWizard()">+ New agent</button>` : "",
      });
      return;
    }

    el.innerHTML = `
      <div class="setup-search-slot">
        ${HubUI.searchBar({
          id: "fa-search",
          value: searchQ,
          placeholder: "Search agents…",
          oninput: "FreightAgentsSetup.setSearch(this.value)",
        })}
      </div>
      ${!list.length
        ? HubUI.emptyState({ title: "No matches", sub: "Clear search." })
        : `<div class="ord-card-list">${list.map(a => {
          const due = moneyOrNull(a.balance_due);
          const adv = moneyOrNull(a.advance_left);
          const hidden = due == null || adv == null;
          const balBits = [];
          if (hidden) balBits.push("Balance hidden");
          else {
            if (due > 0) balBits.push(`<strong>${fmtPrice(due)}</strong> due`);
            if (adv > 0) balBits.push(`<strong>${fmtPrice(adv)}</strong> advance`);
            if (!balBits.length) balBits.push("No balance");
          }
          return HubUI.partyCard({
            title: a.name,
            meta: `${balBits.join(" · ")}${a.notes ? ` · ${ctx.esc(a.notes)}` : ""}`,
            pillHtml: hidden ? HubUI.pill("Hidden", "muted") : (due > 0 ? HubUI.pill("Due", "danger") : (adv > 0 ? HubUI.pill("Advance", "info") : HubUI.pill("OK", "muted"))),
            primaryLabel: write ? "Edit" : null,
            primaryOnclick: write ? `FreightAgentsSetup.openEdit(${a.id})` : "",
            moreItems: [
              ...(ctx.isAdmin?.() ? [{ label: "Open in Finance", onclick: `App.showView('finance');Finance.openFreightAgent(${a.id})` }] : []),
            ],
            rowOnclick: write ? `FreightAgentsSetup.openEdit(${a.id})` : (ctx.isAdmin?.() ? `App.showView('finance');Finance.openFreightAgent(${a.id})` : ""),
            canWrite: write || ctx.isAdmin?.(),
          });
        }).join("")}</div>`}`;
    if (caret && typeof OrdersUI !== "undefined") OrdersUI.restoreSearchCaret("fa-search", caret);
  }

  function openWizard() {
    editingId = null;
    openFormModal("New freight agent", "", "");
  }

  function openEdit(id) {
    const a = agents.find(x => x.id === id);
    if (!a) return;
    editingId = id;
    openFormModal("Edit freight agent", a.name, a.notes || "");
  }

  function openFormModal(title, name, notes) {
    const modal = document.getElementById("modal");
    if (!modal) return;
    document.getElementById("modal-title").textContent = title;
    document.getElementById("modal-body").innerHTML = `
      <div style="display:grid;gap:14px;">
        <div><label class="label">Name *</label><input id="fa-name" class="input" value="${ctx.esc(name)}" placeholder="e.g. Blue Dart local" /></div>
        <div><label class="label">Notes</label><input id="fa-notes" class="input" value="${ctx.esc(notes)}" placeholder="Optional" /></div>
      </div>`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="FreightAgentsSetup.save()">${editingId ? "Save" : "Create"}</button>`;
    modal.classList.remove("hidden");
  }

  async function save() {
    const name = document.getElementById("fa-name")?.value?.trim();
    const notes = document.getElementById("fa-notes")?.value?.trim() || null;
    if (!name) return ctx.toast("Name required", "error");
    ctx.showLoading?.();
    try {
      if (editingId) {
        await ctx.api(`/freight-agents/${editingId}`, { method: "PATCH", body: JSON.stringify({ name, notes }) });
        ctx.toast("Agent updated", "success");
      } else {
        await ctx.api("/freight-agents", { method: "POST", body: JSON.stringify({ name, notes }) });
        ctx.toast("Freight agent created", "success");
      }
      App.closeModal?.();
      await load();
    } catch (err) { ctx.toast(err.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  return { init, load, create: save, openWizard, openEdit, save, setSearch };
})();
