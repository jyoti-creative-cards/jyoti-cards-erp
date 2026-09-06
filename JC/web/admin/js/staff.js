/** Staff management — admin only */
const StaffMgmt = (() => {
  let ctx = {};
  let staff = [];
  let permGroups = [];
  let editingId = null;
  let searchQ = "";

  function init(context) { ctx = context; }

  async function load() {
    // Called unguarded on tab switch (app.js) — an API failure previously threw
    // an unhandled rejection and left the page stuck on whatever it last showed
    // with no explanation.
    try {
      [staff, permGroups] = await Promise.all([
        ctx.api("/staff"),
        ctx.api("/staff/permissions"),
      ]);
    } catch (e) {
      ctx.toast?.(e.message || "Could not load staff", "error");
      return;
    }
    if (!Array.isArray(staff)) staff = [];
    const count = document.getElementById("hub-staff-count");
    if (count) count.textContent = `${staff.length} staff`;
    renderSearch();
    render();
  }

  function setSearch(val) {
    searchQ = val || "";
    render();
  }

  function renderSearch() {
    const slot = document.getElementById("staff-search-slot");
    if (!slot) return;
    slot.innerHTML = HubUI.searchBar({
      id: "staff-search",
      value: searchQ,
      placeholder: "Search name or phone…",
      oninput: "StaffMgmt.setSearch(this.value)",
    });
  }

  function filtered() {
    const q = searchQ.trim().toLowerCase();
    if (!q) return staff;
    return staff.filter(s =>
      String(s.name || "").toLowerCase().includes(q)
      || String(s.phone || "").includes(q)
    );
  }

  function render() {
    const el = document.getElementById("staff-table");
    if (!el) return;
    const list = filtered();
    if (!staff.length) {
      el.innerHTML = HubUI.emptyState({
        title: "No staff yet",
        sub: "Add a team member to share logins.",
        ctaHtml: `<button class="btn btn-primary btn-lg" onclick="StaffMgmt.openWizard()">+ Add Staff</button>`,
      });
      return;
    }
    if (!list.length) {
      el.innerHTML = HubUI.emptyState({ title: "No matches", sub: "Clear search." });
      return;
    }
    el.innerHTML = `<div class="ord-card-list">${list.map(s => HubUI.partyCard({
      title: s.name,
      meta: `${ctx.esc(s.phone)}${s.permissions.length ? ` · ${s.permissions.length} permission${s.permissions.length === 1 ? "" : "s"}` : " · No permissions"}`,
      pillHtml: s.is_active === false ? HubUI.pill("Inactive", "muted") : HubUI.pill("Active", "ok"),
      primaryLabel: "Edit",
      primaryOnclick: `StaffMgmt.openEdit(${s.id})`,
      moreItems: [
        { label: "Open", onclick: `StaffMgmt.openDetail(${s.id})` },
        { label: "Remove", onclick: `StaffMgmt.deleteStaff(${s.id},${JSON.stringify(s.name)})`, danger: true },
      ],
      rowOnclick: `StaffMgmt.openDetail(${s.id})`,
      canWrite: true,
    })).join("")}</div>`;
  }

  async function openDetail(id) {
    ctx.showLoading?.();
    try {
      const s = staff.find(x => x.id === id) || await ctx.api(`/staff/${id}`);
      ctx.openDetail("Staff — " + s.name, `
        <div class="review-grid" style="margin-bottom:20px;">
          ${ctx.reviewRow("Name", s.name)}
          ${ctx.reviewRow("Login ID", s.phone)}
          ${ctx.reviewRow("Permissions", s.permissions.length ? s.permissions.join(", ") : "None")}
          ${ctx.reviewRow("Status", s.is_active ? "Active" : "Inactive")}
          ${ctx.reviewRow("Created", ctx.fmtDate(s.created_at))}
        </div>
        <div class="detail-section">
          <h4>Activity</h4>
          <div id="staff-activity-wrap">Loading…</div>
        </div>`,
        `<button class="btn btn-secondary btn-sm" onclick="StaffMgmt.openEdit(${s.id})">Edit</button>
         <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
        "md"
      );
      await ctx.loadActivity?.({ tableId: "staff-activity-wrap", actorId: s.id, limit: 50, clickable: true });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  const ROLE_PRESETS = [
    {
      id: "sell",
      label: "Sell",
      hint: "Customers + selling orders",
      keys: ["customers.read", "customers.write", "customer_orders.read", "customer_orders.write", "returns.read", "returns.write", "catalog.read", "addons.read"],
    },
    {
      id: "buy",
      label: "Buy",
      hint: "Vendors + buying orders + stock",
      // Hint promises "stock" but stock.read/write (on-hand qty + ledger, gated
      // separately from catalog.*/vendor_orders.* server-side) was missing — the
      // buying flow itself worked without it, but the standalone Stock screen the
      // hint calls out always 403'd.
      keys: ["vendors.read", "vendors.write", "vendor_orders.read", "vendor_orders.write", "catalog.read", "catalog.write", "addons.read", "addons.write", "stock.read", "stock.write"],
    },
    {
      id: "stock",
      label: "Stock",
      hint: "Catalog + on-hand",
      // Named "Stock" and promises "on-hand" but stock.read/write (the actual
      // permission gating GET /stock/products, /stock/products/{id}, and
      // /stock/ledger/{id}) was entirely missing — the one thing this preset's own
      // label promises was the one thing it didn't grant.
      keys: ["catalog.read", "catalog.write", "addons.read", "addons.write", "stock.read", "stock.write"],
    },
    {
      id: "people",
      label: "People",
      hint: "Customers + vendors only",
      keys: ["customers.read", "customers.write", "vendors.read", "vendors.write"],
    },
    {
      id: "setup",
      label: "Setup",
      hint: "Routes, cities, lookups",
      // Deliberately no recycle.* here — recycle bin is unrelated to setup data
      // and least-privilege says don't bundle it in by default.
      keys: ["setup.read", "setup.write"],
    },
    {
      id: "accountant",
      label: "Accountant",
      hint: "Runs day-to-day ops — no buying price, no finance figures, entry-only money",
      keys: [
        // Deliberately no customers.write / vendors.write / catalog.write / addons.write / setup.write / recycle.*:
        // those permissions also gate "Delete" buttons in this app — read-only master data keeps this role delete-free.
        "customers.read", "vendors.read",
        "catalog.read", "addons.read", "setup.read",
        "vendor_orders.read", "vendor_orders.write",
        "customer_orders.read", "customer_orders.write",
        "returns.read", "returns.write",
        "stock.read", "stock.write",
        "finance.write",
      ],
    },
  ];

  function applyRolePreset(roleId) {
    const role = ROLE_PRESETS.find(r => r.id === roleId);
    if (!role) return;
    const want = new Set(role.keys);
    document.querySelectorAll(".staff-perm-cb").forEach(cb => {
      cb.checked = want.has(cb.value);
    });
  }

  function permCheckboxes(selected) {
    const sel = new Set(selected || []);
    const presets = `<div style="margin-bottom:14px;">
      <div style="font-size:12px;font-weight:700;color:var(--muted);margin-bottom:8px;">Quick roles</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px;">
        ${ROLE_PRESETS.map(r => `<button type="button" class="btn btn-secondary btn-sm" title="${ctx.esc(r.hint)}" onclick="StaffMgmt.applyRolePreset('${r.id}')">${ctx.esc(r.label)}</button>`).join("")}
      </div>
      <p style="margin:8px 0 0;font-size:12px;color:var(--muted);">Tap a role to tick the common permissions, then fine-tune below.</p>
    </div>`;
    const groups = permGroups.map(g => `
      <div style="margin-bottom:12px;">
        <div style="font-size:12px;font-weight:700;color:var(--muted);margin-bottom:6px;">${ctx.esc(g.label)}</div>
        ${g.permissions.map(p => `<label style="display:flex;align-items:center;gap:8px;margin-bottom:4px;font-size:13px;">
          <input type="checkbox" class="staff-perm-cb" value="${ctx.esc(p.key)}" ${sel.has(p.key) ? "checked" : ""} />
          ${ctx.esc(p.label)}
        </label>`).join("")}
      </div>`).join("");
    return presets + groups;
  }

  function collectPerms() {
    return Array.from(document.querySelectorAll(".staff-perm-cb:checked")).map(cb => cb.value);
  }

  function openWizard() {
    editingId = null;
    document.getElementById("staff-modal-title").textContent = "New Staff Member";
    document.getElementById("staff-modal-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Full Name *</label><input id="sm-name" class="input" placeholder="e.g. Rahul Sharma" /></div>
        <div><label class="label">Mobile Number (Login ID) *</label><input id="sm-phone" class="input" type="tel" maxlength="10" placeholder="10-digit mobile" />
          <p style="margin:6px 0 0;font-size:12px;color:var(--muted);">Password = last 4 digits by default. Sent via WhatsApp.</p></div>
        <div><label class="label">Custom Password (optional)</label><input id="sm-password" class="input" placeholder="Leave blank to use last 4 digits of phone" />
          <p style="margin:6px 0 0;font-size:12px;color:var(--muted);">Set this if the phone number isn't real (e.g. no WhatsApp) — you'll need to share it yourself.</p></div>
        <div><label class="label">Permissions</label><div class="card" style="padding:16px;max-height:240px;overflow-y:auto;">${permCheckboxes([])}</div></div>
      </div>`;
    document.getElementById("staff-modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="StaffMgmt.closeModal()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="StaffMgmt.save()">Create & Send WhatsApp</button>`;
    document.getElementById("staff-modal").classList.remove("hidden");
  }

  async function openEdit(id) {
    const s = staff.find(x => x.id === id) || await ctx.api(`/staff/${id}`);
    editingId = id;
    document.getElementById("staff-modal-title").textContent = "Edit Staff — " + s.name;
    document.getElementById("staff-modal-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Full Name *</label><input id="sm-name" class="input" value="${ctx.esc(s.name)}" /></div>
        <div><label class="label">Login ID (mobile)</label><input id="sm-phone" class="input" type="tel" maxlength="10" value="${ctx.esc(s.phone)}" />
          <p style="margin:6px 0 0;font-size:12px;color:var(--muted);">Changing this changes their login number too.</p></div>
        <div><label class="label">Permissions</label><div class="card" style="padding:16px;max-height:240px;overflow-y:auto;">${permCheckboxes(s.permissions)}</div></div>
        <div><button type="button" class="btn btn-secondary btn-sm" onclick="StaffMgmt.resetPassword(${s.id})">Reset Password</button></div>
      </div>`;
    document.getElementById("staff-modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="StaffMgmt.closeModal()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="StaffMgmt.save()">Save</button>`;
    document.getElementById("staff-modal").classList.remove("hidden");
  }

  async function resetPassword(id) {
    if (!confirm("Reset this staff member's password? A new one will be generated and sent via WhatsApp.")) return;
    try {
      const res = await ctx.api(`/staff/${id}/reset-password`, { method: "POST", body: "{}" });
      if (res.whatsapp_sent) {
        ctx.toast("Password reset & WhatsApp sent!", "success");
      } else {
        alert(`Password reset.\nNew password: ${res.temp_password}\n\n(WhatsApp not sent: ${res.whatsapp_error || "unknown reason"} — share this yourself.)`);
      }
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  function closeModal() {
    document.getElementById("staff-modal").classList.add("hidden");
    editingId = null;
  }

  async function save() {
    const name = document.getElementById("sm-name")?.value.trim();
    if (!name) return ctx.toast("Name required", "error");
    try {
      if (editingId) {
        const phone = document.getElementById("sm-phone")?.value.trim();
        const body = { name, permissions: collectPerms() };
        if (phone) body.phone = phone.replace(/\D/g, "");
        const res = await ctx.api(`/staff/${editingId}`, { method: "PATCH", body: JSON.stringify(body) });
        if (res.whatsapp_sent === true) {
          ctx.toast("Staff updated — login number change sent via WhatsApp", "success");
        } else if (res.whatsapp_sent === false) {
          alert(`Staff updated.\nCould not WhatsApp the new login number (${res.whatsapp_error || "unknown reason"}) — tell them yourself: ${res.phone}`);
        } else {
          ctx.toast("Staff updated", "success");
        }
      } else {
        const phone = document.getElementById("sm-phone")?.value.trim();
        if (!/^\d{10}$/.test(phone.replace(/\D/g, ""))) return ctx.toast("Phone must be 10 digits", "error");
        const password = document.getElementById("sm-password")?.value.trim();
        const res = await ctx.api("/staff", { method: "POST", body: JSON.stringify({ name, phone: phone.replace(/\D/g, ""), permissions: collectPerms(), password: password || undefined }) });
        if (res.whatsapp_sent) {
          ctx.toast("Created & WhatsApp sent!", "success");
        } else {
          alert(`Staff created.\nLogin ID: ${res.phone}\nPassword: ${res.temp_password}\n\n(WhatsApp not sent: ${res.whatsapp_error || "unknown reason"} — share these credentials yourself.)`);
        }
      }
      closeModal();
      await load();
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function deleteStaff(id, name) {
    if (!confirm(`Remove staff "${name}"?`)) return;
    try {
      await ctx.api(`/staff/${id}`, { method: "DELETE" });
      ctx.toast("Staff removed", "success");
      await load();
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  return { init, load, openDetail, openWizard, openEdit, closeModal, save, deleteStaff, setSearch, applyRolePreset, resetPassword };
})();
