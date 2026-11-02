/* Our dated markings. Not stitched. */
const Markings = (() => {
  let rows = [];

  function panel() {
    return document.getElementById("marking-panel");
  }

  function today() {
    return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  }

  function esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  async function open() {
    document.getElementById("more-hub")?.classList.add("hidden");
    document.getElementById("more-safety")?.classList.add("hidden");
    panel()?.classList.remove("hidden");
    await load();
  }

  function close() {
    panel()?.classList.add("hidden");
    document.getElementById("more-hub")?.classList.remove("hidden");
  }

  async function load() {
    const box = panel();
    if (!box) return;
    const q = document.getElementById("mk-q")?.value || "";
    try {
      const data = await App.api(`/reports/product-markings/assignments?q=${encodeURIComponent(q)}`, {}, 0);
      rows = data.items || [];
    } catch (e) {
      box.innerHTML = `<p style="color:var(--danger);">${esc(e.message)}</p>`;
      return;
    }
    const list = rows.map(r => `<tr>
      <td>${esc(r.our_product_id)}</td>
      <td><input class="input" id="mk-text-${r.id}" value="${esc(r.text)}" /></td>
      <td><input class="input" type="date" id="mk-from-${r.id}" value="${esc(r.starts_on)}" /></td>
      <td><input class="input" type="date" id="mk-until-${r.id}" value="${esc(r.ends_on)}" /></td>
      <td>${r.active ? "Showing" : "Ended"}</td>
      <td>
        <button type="button" class="btn btn-secondary btn-sm" onclick="Markings.save(${r.id})">Save</button>
        <button type="button" class="btn btn-secondary btn-sm" onclick="Markings.remove(${r.id})">Delete</button>
      </td>
    </tr>`).join("");
    box.innerHTML = `
      <button type="button" class="btn btn-secondary" style="margin:12px 0;" onclick="Markings.close()">← More</button>
      <h2 style="margin:0 0 8px;">Markings</h2>
      <p style="margin:0 0 12px;color:var(--muted);">A marking shows on the product only from its start date through its end date. After the end date it comes off by itself.</p>
      <div class="card" style="padding:12px;margin-bottom:12px;">
        <h3 style="margin:0 0 8px;">Add to products</h3>
        <input id="mk-find" class="input" placeholder="Search item number" oninput="Markings.search(this.value)" />
        <div id="mk-hits"></div>
        <div id="mk-picked" style="margin-top:8px;"></div>
        <div style="display:grid;grid-template-columns:1fr 160px 160px auto;gap:8px;align-items:end;margin-top:8px;">
          <input id="mk-new-text" class="input" maxlength="200" placeholder="Monday" />
          <input id="mk-new-from" class="input" type="date" value="${today()}" />
          <input id="mk-new-until" class="input" type="date" value="2099-12-31" />
          <button type="button" class="btn btn-primary" onclick="Markings.assign()">Add</button>
        </div>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:8px;">
        <input id="mk-q" class="input" placeholder="Search existing markings" value="${esc(q)}" />
        <button type="button" class="btn btn-secondary" onclick="Markings.load()">Search</button>
      </div>
      <table class="data"><thead><tr><th>Item</th><th>Marking</th><th>From</th><th>Until</th><th></th><th></th></tr></thead>
      <tbody>${list || `<tr><td colspan="6">None yet</td></tr>`}</tbody></table>`;
  }

  let picked = {};
  async function search(value) {
    const box = document.getElementById("mk-hits");
    if (!box) return;
    const q = String(value || "").trim();
    if (q.length < 2) { box.innerHTML = ""; return; }
    const rows = await App.api(`/stock/entry-items?q=${encodeURIComponent(q)}`, {}, 0);
    const list = Array.isArray(rows) ? rows : (rows.items || []);
    box.innerHTML = list.slice(0, 8).map(p => `
      <button type="button" class="btn btn-secondary btn-sm" style="display:block;width:100%;text-align:left;margin-top:6px;" onclick="Markings.pick(${p.catalog_product_id}, ${JSON.stringify(p.our_product_id)})">${esc(p.our_product_id)}</button>
    `).join("");
  }

  function pick(id, name) {
    picked[id] = name;
    const box = document.getElementById("mk-picked");
    if (box) box.textContent = Object.values(picked).join(", ");
  }

  async function assign() {
    const marking = document.getElementById("mk-new-text")?.value.trim() || "";
    const starts_on = document.getElementById("mk-new-from")?.value;
    const ends_on = document.getElementById("mk-new-until")?.value;
    const product_ids = Object.keys(picked).map(Number);
    if (!marking || !product_ids.length) return App.toast?.("Pick products and type the marking", "error");
    try {
      await App.api("/reports/product-markings/assign", {
        method: "POST",
        body: JSON.stringify({ marking, product_ids, starts_on, ends_on }),
      });
      picked = {};
      App.toast?.("Marking added", "success");
      await load();
    } catch (e) { App.toast?.(e.message, "error"); }
  }

  async function save(id) {
    const marking = document.getElementById(`mk-text-${id}`)?.value.trim() || "";
    const starts_on = document.getElementById(`mk-from-${id}`)?.value;
    const ends_on = document.getElementById(`mk-until-${id}`)?.value;
    try {
      await App.api(`/reports/product-markings/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ marking, starts_on, ends_on }),
      });
      App.toast?.("Saved", "success");
      await load();
    } catch (e) { App.toast?.(e.message, "error"); }
  }

  async function remove(id) {
    try {
      await App.api(`/reports/product-markings/${id}`, { method: "DELETE" });
      App.toast?.("Deleted", "success");
      await load();
    } catch (e) { App.toast?.(e.message, "error"); }
  }

  return { open, close, load, search, pick, assign, save, remove };
})();
