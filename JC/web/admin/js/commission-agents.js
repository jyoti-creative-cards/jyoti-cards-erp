const CommissionAgents = (() => {
  function api(path, opts) {
    return App.api(path, opts || {});
  }
  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function money(value) {
    const n = Number(value) || 0;
    return "₹" + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function desk() {
    return document.getElementById("commission-desk");
  }
  function showDesk() {
    document.getElementById("finance-hub-strip")?.classList.add("hidden");
    document.getElementById("finance-action-chips")?.classList.add("hidden");
    document.getElementById("finance-search-slot")?.classList.add("hidden");
    document.getElementById("finance-needs")?.classList.add("hidden");
    document.querySelectorAll(".fin-browse-panel").forEach((el) => el.classList.add("hidden"));
    desk()?.classList.remove("hidden");
  }
  function hideDesk() {
    desk()?.classList.add("hidden");
    document.getElementById("finance-hub-strip")?.classList.remove("hidden");
    document.getElementById("finance-action-chips")?.classList.remove("hidden");
    document.getElementById("finance-search-slot")?.classList.remove("hidden");
    document.getElementById("finance-needs")?.classList.remove("hidden");
    if (window.Finance?.showHub) Finance.showHub();
  }

  async function open() {
    App.showView("money");
    showDesk();
    await renderList();
  }

  async function renderList() {
    const box = desk();
    if (!box) return;
    let rows = [];
    try { rows = await api("/commission-agents", {}, 0); }
    catch (e) { box.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
    box.innerHTML = `
      <button type="button" class="btn btn-secondary" onclick="CommissionAgents.close()">← Money</button>
      <h2 style="margin:12px 0;">Commission agents</h2>
      <p style="color:var(--muted);margin:0 0 12px;">They deliver and collect. The party keeps the order. The due sits here.</p>
      <div class="card" style="padding:12px;margin-bottom:16px;">
        <div style="display:grid;grid-template-columns:1fr 180px auto;gap:8px;align-items:end;">
          <div><label class="label">Name</label><input id="ca-new-name" class="input" placeholder="Mohd Bhai" /></div>
          <div><label class="label">Phone</label><input id="ca-new-phone" class="input" placeholder="10-digit phone" /></div>
          <button type="button" class="btn btn-primary" onclick="CommissionAgents.create()">Add agent</button>
        </div>
      </div>
      <div class="list">${(rows || []).map((row) => `
        <button type="button" class="btn btn-secondary" style="display:block;width:100%;text-align:left;margin-top:8px;" onclick="CommissionAgents.openAgent(${row.id})">
          <strong>${esc(row.name)}</strong>
          <span style="display:block;color:var(--muted);">${esc(row.phone || "")} · ${row.party_count} parties · due ${money(row.outstanding)}</span>
        </button>`).join("") || `<p style="color:var(--muted);">No agents yet.</p>`}
      </div>`;
  }

  async function create() {
    const name = document.getElementById("ca-new-name")?.value.trim();
    const phone = document.getElementById("ca-new-phone")?.value.trim();
    if (!name) return App.toast?.("Enter the agent name", "error");
    try {
      await api("/commission-agents", { method: "POST", body: JSON.stringify({ name, phone }) });
      App.toast?.("Agent added", "success");
      await renderList();
    } catch (e) { App.toast?.(e.message, "error"); }
  }

  async function openAgent(id) {
    const box = desk();
    let data;
    try { data = await api(`/commission-agents/${id}`, {}, 0); }
    catch (e) { App.toast?.(e.message, "error"); return; }
    box.innerHTML = `
      <button type="button" class="btn btn-secondary" onclick="CommissionAgents.open()">← Agents</button>
      <h2 style="margin:12px 0 4px;">${esc(data.name)}</h2>
      <p style="margin:0 0 12px;font-size:20px;font-weight:800;">Due ${money(data.outstanding)}</p>
      <div class="card" style="padding:12px;margin-bottom:12px;">
        <div style="display:grid;grid-template-columns:1fr 180px auto;gap:8px;align-items:end;">
          <div><label class="label">Name</label><input id="ca-edit-name" class="input" value="${esc(data.name)}" /></div>
          <div><label class="label">Phone</label><input id="ca-edit-phone" class="input" value="${esc(data.phone || "")}" /></div>
          <button type="button" class="btn btn-primary" onclick="CommissionAgents.save(${id})">Save</button>
        </div>
        <button type="button" class="btn btn-secondary btn-sm" style="margin-top:8px;" onclick="CommissionAgents.removeAgent(${id})">Delete agent</button>
      </div>
      <div class="card" style="padding:12px;margin-bottom:12px;">
        <h3 style="margin:0 0 8px;">Collect</h3>
        <p style="margin:0 0 8px;color:var(--muted);font-size:13px;">A lump payment. It is not tied to one party.</p>
        <div style="display:grid;grid-template-columns:160px 1fr auto;gap:8px;align-items:end;">
          <div><label class="label">Amount</label><input id="ca-pay" class="input" inputmode="decimal" placeholder="5000" /></div>
          <div><label class="label">Note</label><input id="ca-pay-note" class="input" placeholder="Optional" /></div>
          <button type="button" class="btn btn-primary" onclick="CommissionAgents.collect(${id})">Receive</button>
        </div>
      </div>
      <div class="card" style="padding:12px;margin-bottom:12px;">
        <h3 style="margin:0 0 8px;">Parties</h3>
        <input id="ca-party-q" class="input" placeholder="Search a party to add" oninput="CommissionAgents.searchParties(${id}, this.value)" />
        <div id="ca-party-hits"></div>
        <div style="margin-top:8px;">${(data.parties || []).map((p) => `
          <div style="display:flex;justify-content:space-between;gap:8px;padding:8px 0;border-bottom:1px solid var(--border);">
            <span><strong>${esc(p.business_name)}</strong> · ${esc(p.city_name || "")}</span>
            <button type="button" class="btn btn-secondary btn-sm" onclick="CommissionAgents.removeParty(${id}, ${p.id})">Remove</button>
          </div>`).join("") || `<p style="color:var(--muted);">No parties yet.</p>`}
        </div>
      </div>
      <div class="card" style="padding:12px;margin-bottom:12px;">
        <h3 style="margin:0 0 8px;">Open orders of his parties</h3>
        ${(data.open_orders || []).length ? `<table class="data"><thead><tr><th>Party</th><th>Item</th><th>Qty</th></tr></thead><tbody>
          ${data.open_orders.map((row) => `<tr><td>${esc(row.party_name)}</td><td>${esc(row.item)}</td><td>${row.qty}</td></tr>`).join("")}
        </tbody></table>` : `<p style="color:var(--muted);">Nothing waiting to bill.</p>`}
      </div>
      <div class="card" style="padding:12px;margin-bottom:12px;">
        <h3 style="margin:0 0 8px;">What his parties were billed</h3>
        ${(data.goods || []).length ? `<table class="data"><thead><tr><th>Date</th><th>Bill</th><th>Party</th><th>Item</th><th>Qty</th><th>Amount</th></tr></thead><tbody>
          ${data.goods.map((row) => `<tr><td>${esc(row.date)}</td><td>${esc(row.bill_number)}</td><td>${esc(row.party_name)}</td><td>${esc(row.item)}</td><td>${row.qty}</td><td>${money(row.amount)}</td></tr>`).join("")}
        </tbody></table>` : `<p style="color:var(--muted);">No bills yet.</p>`}
      </div>
      <div class="card" style="padding:12px;">
        <h3 style="margin:0 0 8px;">Ledger</h3>
        ${(data.ledger || []).length ? `<table class="data"><thead><tr><th>Date</th><th>Entry</th><th>Amount</th><th>Balance</th></tr></thead><tbody>
          ${data.ledger.map((row) => `<tr><td>${esc(row.date)}</td><td>${esc(row.description)}${row.party_name ? " · " + esc(row.party_name) : ""}</td><td>${money(row.amount)}</td><td>${money(row.balance)}</td></tr>`).join("")}
        </tbody></table>` : `<p style="color:var(--muted);">No entries yet.</p>`}
      </div>`;
  }

  async function save(id) {
    const name = document.getElementById("ca-edit-name")?.value.trim();
    const phone = document.getElementById("ca-edit-phone")?.value.trim();
    if (!name) return App.toast?.("Enter the agent name", "error");
    try {
      await api(`/commission-agents/${id}`, { method: "PATCH", body: JSON.stringify({ name, phone }) });
      App.toast?.("Saved", "success");
      await openAgent(id);
    } catch (e) { App.toast?.(e.message, "error"); }
  }

  async function removeAgent(id) {
    if (!confirm("Delete this agent? Parties come off him. Old bills stay on his ledger.")) return;
    try {
      await api(`/commission-agents/${id}`, { method: "DELETE" });
      App.toast?.("Deleted", "success");
      await renderList();
    } catch (e) { App.toast?.(e.message, "error"); }
  }

  async function searchParties(id, value) {
    const box = document.getElementById("ca-party-hits");
    if (!box) return;
    const q = String(value || "").trim();
    if (q.length < 2) { box.innerHTML = ""; return; }
    const rows = await api(`/commission-agents/party-search?q=${encodeURIComponent(q)}`, {}, 0);
    box.innerHTML = (rows || []).map((row) => `
      <button type="button" class="btn btn-secondary btn-sm" style="display:block;width:100%;text-align:left;margin-top:6px;" onclick="CommissionAgents.addParty(${id}, ${row.id})">
        ${esc(row.business_name)} · ${esc(row.city_name || "")}${row.agent_name ? " · now with " + esc(row.agent_name) : ""}
      </button>`).join("");
  }

  async function addParty(id, customerId) {
    try {
      await api(`/commission-agents/${id}/parties/${customerId}`, { method: "POST" });
      await openAgent(id);
    } catch (e) { App.toast?.(e.message, "error"); }
  }

  async function removeParty(id, customerId) {
    try {
      await api(`/commission-agents/${id}/parties/${customerId}`, { method: "DELETE" });
      await openAgent(id);
    } catch (e) { App.toast?.(e.message, "error"); }
  }

  async function collect(id) {
    const amount = document.getElementById("ca-pay")?.value.trim();
    const note = document.getElementById("ca-pay-note")?.value.trim();
    if (!amount || Number(amount) <= 0) return App.toast?.("Enter the amount received", "error");
    try {
      await api(`/commission-agents/${id}/payments`, { method: "POST", body: JSON.stringify({ amount, note }) });
      App.toast?.("Payment saved", "success");
      await openAgent(id);
    } catch (e) { App.toast?.(e.message, "error"); }
  }

  function close() { hideDesk(); }

  return { open, close, create, openAgent, save, removeAgent, searchParties, addParty, removeParty, collect };
})();
