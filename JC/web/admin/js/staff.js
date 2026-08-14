/** Staff management — admin only */
const StaffMgmt = (() => {
  let ctx = {};
  let staff = [];
  let permGroups = [];
  let editingId = null;
  let searchQ = "";

  function init(context) { ctx = context; }

  async function load() {
    [staff, permGroups] = await Promise.all([
      ctx.api("/staff"),
      ctx.api("/staff/permissions"),
    ]);
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
      keys: ["customers.read", "customers.write", "vendor_orders.read", "vendor_orders.write", "catalog.read", "addons.read"],
    },
    {
      id: "buy",
      label: "Buy",
      hint: "Vendors + buying orders + stock",
      keys: ["vendors.read", "vendors.write", "vendor_orders.read", "vendor_orders.write", "catalog.read", "catalog.write", "addons.read", "addons.write"],
    },
    {
      id: "stock",
      label: "Stock",
      hint: "Catalog + on-hand",
      keys: ["catalog.read", "catalog.write", "addons.read", "addons.write"],
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
      keys: ["setup.read", "setup.write", "recycle.read", "recycle.write"],
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
          <p style="margin:6px 0 0;font-size:12px;color:var(--muted);">Password = last 4 digits. Sent via WhatsApp.</p></div>
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
        <div><label class="label">Login ID</label><input class="input" value="${ctx.esc(s.phone)}" disabled /></div>
        <div><label class="label">Permissions</label><div class="card" style="padding:16px;max-height:240px;overflow-y:auto;">${permCheckboxes(s.permissions)}</div></div>
      </div>`;
    document.getElementById("staff-modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="StaffMgmt.closeModal()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="StaffMgmt.save()">Save Permissions</button>`;
    document.getElementById("staff-modal").classList.remove("hidden");
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
        await ctx.api(`/staff/${editingId}`, { method: "PATCH", body: JSON.stringify({ name, permissions: collectPerms() }) });
        ctx.toast("Staff updated", "success");
      } else {
        const phone = document.getElementById("sm-phone")?.value.trim();
        if (!/^\d{10}$/.test(phone.replace(/\D/g, ""))) return ctx.toast("Phone must be 10 digits", "error");
        const res = await ctx.api("/staff", { method: "POST", body: JSON.stringify({ name, phone: phone.replace(/\D/g, ""), permissions: collectPerms() }) });
        ctx.toast(res.whatsapp_sent ? "Created & WhatsApp sent!" : "Created (WA: " + (res.whatsapp_error || "failed") + ")", res.whatsapp_sent ? "success" : "error");
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

  return { init, load, openDetail, openWizard, openEdit, closeModal, save, deleteStaff, setSearch, applyRolePreset };
})();
