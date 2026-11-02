/** Our physical catalogues — made from stock, assigned to parties, sent on a bill or recorded by hand. */
const OurCatalogs = (() => {
  let rows = [];
  let openId = null;
  let detail = null;
  let partyHits = [];

  function esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function money(n) { return App.fmtPrice ? App.fmtPrice(n) : n; }
  function panel() { return document.getElementById("our-catalog-panel"); }

  async function load() {
    const box = panel();
    if (!box) return;
    box.innerHTML = `<p style="color:var(--muted);">Loading…</p>`;
    try {
      rows = await App.api("/our-catalogs", {}, 0) || [];
    } catch (e) {
      box.innerHTML = `<p style="color:var(--danger);">${esc(e.message)}</p>`;
      return;
    }
    if (openId) return openDetail(openId);
    renderList();
  }

  function renderList() {
    const box = panel();
    if (!box) return;
    const cards = rows.map(r => `
      <button type="button" class="big-tile ui-tile" style="text-align:left;" onclick="OurCatalogs.openDetail(${r.id})">
        <span class="big-tile-title">${esc(r.name)}</span>
        <span class="big-tile-desc">Made ${r.copies_made} · Sent ${r.copies_sent} · Left ${r.copies_left}</span>
        <span class="big-tile-count">${r.assigned} parties to send</span>
      </button>`).join("");
    box.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin:12px 0;">
        <p style="margin:0;color:var(--muted);">Create a catalogue, assign the parties who should get it, and record who already has it.</p>
        <button type="button" class="btn btn-primary" onclick="OurCatalogs.openCreate()">+ New catalog</button>
      </div>
      <div class="ui-tile-grid">${cards || `<p style="color:var(--muted);">No catalogues yet.</p>`}</div>`;
  }

  async function openDetail(id) {
    openId = id;
    const box = panel();
    if (box) box.innerHTML = `<p style="color:var(--muted);">Loading…</p>`;
    try { detail = await App.api(`/our-catalogs/${id}`, {}, 0); }
    catch (e) { if (box) box.innerHTML = `<p style="color:var(--danger);">${esc(e.message)}</p>`; return; }
    renderDetail();
  }

  function renderDetail() {
    const box = panel();
    const d = detail;
    if (!box || !d) return;
    const lines = (d.lines || []).map(l => `<tr><td>${esc(l.our_product_id)}</td><td>${l.quantity}</td></tr>`).join("");
    const assigned = (d.assignments || []).map(a => `<tr>
      <td>${esc(a.business_name)}${a.party_number ? " · #" + a.party_number : ""}</td>
      <td>${a.received ? a.received : "Not yet"}</td>
    </tr>`).join("");
    const issues = (d.issues || []).map(i => `<tr>
      <td>${esc(i.issued_on)}</td><td>${esc(i.business_name)}</td><td>${i.copies}</td><td>${money(i.price)}</td><td>${i.bill_id ? "Bill" : esc(i.note || "Recorded")}</td>
    </tr>`).join("");
    box.innerHTML = `
      <button type="button" class="btn btn-secondary" style="margin:12px 0;" onclick="OurCatalogs.back()">← Catalogs</button>
      <h2 style="margin:0 0 4px;">${esc(d.name)}</h2>
      <p style="margin:0 0 12px;">Made <strong>${d.copies_made}</strong> · Sent <strong>${d.copies_sent}</strong> · Left <strong>${d.copies_left}</strong></p>
      <div class="card" style="padding:12px;margin-bottom:12px;">
        <h3 style="margin:0 0 8px;">Items in one copy</h3>
        <table class="data"><thead><tr><th>Item</th><th>Qty</th></tr></thead><tbody>${lines}</tbody></table>
      </div>
      <div class="card" style="padding:12px;margin-bottom:12px;">
        <h3 style="margin:0 0 8px;">Should go to</h3>
        <input id="oc-party-q" class="input" placeholder="Search a party to assign" oninput="OurCatalogs.searchParties(this.value)" />
        <div id="oc-party-hits"></div>
        <table class="data" style="margin-top:8px;"><thead><tr><th>Party</th><th>Received</th></tr></thead><tbody>${assigned || `<tr><td colspan="2">None yet</td></tr>`}</tbody></table>
      </div>
      <div class="card" style="padding:12px;margin-bottom:12px;">
        <h3 style="margin:0 0 8px;">Already received</h3>
        <div style="display:grid;grid-template-columns:1fr 90px 140px auto;gap:8px;align-items:end;margin-bottom:8px;">
          <input id="oc-got-q" class="input" placeholder="Party who already has it" oninput="OurCatalogs.searchGot(this.value)" />
          <input id="oc-got-copies" class="input" inputmode="numeric" value="1" />
          <input id="oc-got-date" class="input" type="date" />
          <span></span>
        </div>
        <div id="oc-got-hits"></div>
        <table class="data" style="margin-top:8px;"><thead><tr><th>Date</th><th>Party</th><th>Copies</th><th>Charged</th><th></th></tr></thead><tbody>${issues || `<tr><td colspan="5">None recorded yet</td></tr>`}</tbody></table>
      </div>`;
  }

  function back() { openId = null; detail = null; renderList(); }

  async function searchParties(value) {
    const box = document.getElementById("oc-party-hits");
    if (!box) return;
    const q = String(value || "").trim();
    if (q.length < 2) { box.innerHTML = ""; return; }
    const rows = await App.api(`/customers?search=${encodeURIComponent(q)}`, {}, 0);
    const list = Array.isArray(rows) ? rows : (rows.items || rows.customers || []);
    box.innerHTML = list.slice(0, 8).map(c => `
      <button type="button" class="btn btn-secondary btn-sm" style="display:block;width:100%;text-align:left;margin-top:6px;" onclick="OurCatalogs.assign(${c.id})">
        ${esc(c.business_name || "")}${c.city_name ? " · " + esc(c.city_name) : ""}
      </button>`).join("");
  }

  async function assign(customerId) {
    try {
      await App.api(`/our-catalogs/${openId}/assign`, { method: "POST", body: JSON.stringify({ customer_ids: [customerId] }) });
      App.toast?.("Assigned", "success");
      await openDetail(openId);
    } catch (e) { App.toast?.(e.message, "error"); }
  }

  async function searchGot(value) {
    const box = document.getElementById("oc-got-hits");
    if (!box) return;
    const q = String(value || "").trim();
    if (q.length < 2) { box.innerHTML = ""; return; }
    const rows = await App.api(`/customers?search=${encodeURIComponent(q)}`, {}, 0);
    const list = Array.isArray(rows) ? rows : (rows.items || rows.customers || []);
    box.innerHTML = list.slice(0, 8).map(c => `
      <button type="button" class="btn btn-secondary btn-sm" style="display:block;width:100%;text-align:left;margin-top:6px;" onclick="OurCatalogs.recordGot(${c.id})">
        Record for ${esc(c.business_name || "")}
      </button>`).join("");
  }

  async function recordGot(customerId) {
    const copies = Number(document.getElementById("oc-got-copies")?.value || 1);
    const issued_on = document.getElementById("oc-got-date")?.value || null;
    try {
      await App.api(`/our-catalogs/${openId}/issues`, {
        method: "POST",
        body: JSON.stringify({ customer_id: customerId, copies, issued_on, price: "0", note: "Already sent" }),
      });
      App.toast?.("Recorded", "success");
      await openDetail(openId);
    } catch (e) { App.toast?.(e.message, "error"); }
  }

  function openCreate() {
    const box = panel();
    if (!box) return;
    box.innerHTML = `
      <button type="button" class="btn btn-secondary" style="margin:12px 0;" onclick="OurCatalogs.back()">← Catalogs</button>
      <h2>New catalog</h2>
      <label class="label">Name</label>
      <input id="oc-name" class="input" placeholder="ALBUM NO. 01" />
      <label class="label">How many copies</label>
      <input id="oc-copies" class="input" inputmode="numeric" value="1" />
      <label class="label">Item in one copy</label>
      <input id="oc-item-q" class="input" placeholder="Item number" oninput="OurCatalogs.searchItems(this.value)" />
      <div id="oc-item-hits"></div>
      <div id="oc-item-lines"></div>
      <button type="button" class="btn btn-primary" style="margin-top:12px;" onclick="OurCatalogs.saveCreate()">Create and post the expense</button>`;
    window.__ocLines = [];
  }

  async function searchItems(value) {
    const box = document.getElementById("oc-item-hits");
    if (!box) return;
    const q = String(value || "").trim();
    if (q.length < 1) { box.innerHTML = ""; return; }
    const rows = await App.api(`/stock/entry-items?q=${encodeURIComponent(q)}`, {}, 0) || [];
    box.innerHTML = rows.slice(0, 8).map(p => `
      <button type="button" class="btn btn-secondary btn-sm" style="display:block;width:100%;text-align:left;margin-top:6px;" onclick='OurCatalogs.addItem(${p.catalog_product_id}, ${JSON.stringify(p.our_product_id)})'>
        ${esc(p.our_product_id)}
      </button>`).join("");
  }

  function addItem(id, name) {
    window.__ocLines = window.__ocLines || [];
    if (!window.__ocLines.some(l => l.catalog_product_id === id)) window.__ocLines.push({ catalog_product_id: id, name, quantity: 1 });
    const box = document.getElementById("oc-item-lines");
    if (!box) return;
    box.innerHTML = window.__ocLines.map((l, i) => `
      <div style="display:flex;gap:8px;margin-top:6px;align-items:center;">
        <span style="flex:1;">${esc(l.name)}</span>
        <input class="input" style="width:80px;" value="${l.quantity}" oninput="OurCatalogs.setItemQty(${i}, this.value)" />
      </div>`).join("");
  }

  function setItemQty(i, value) {
    if (window.__ocLines[i]) window.__ocLines[i].quantity = Number(value) || 1;
  }

  async function saveCreate() {
    const name = document.getElementById("oc-name")?.value.trim();
    const copies = Number(document.getElementById("oc-copies")?.value || 0);
    const lines = (window.__ocLines || []).filter(l => l.quantity > 0).map(l => ({ catalog_product_id: l.catalog_product_id, quantity: l.quantity }));
    if (!name) return App.toast?.("Enter the name", "error");
    if (!copies) return App.toast?.("Enter how many copies", "error");
    if (!lines.length) return App.toast?.("Add the items", "error");
    try {
      const created = await App.api("/our-catalogs", { method: "POST", body: JSON.stringify({ name, copies, lines }) });
      App.toast?.("Catalog created", "success");
      await openDetail(created.id);
    } catch (e) { App.toast?.(e.message, "error"); }
  }

  return { load, openDetail, back, openCreate, searchParties, assign, searchGot, recordGot, searchItems, addItem, setItemQty, saveCreate };
})();
