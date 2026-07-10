/** Staff management — admin only */
const StaffMgmt = (() => {
  let ctx = {};
  let staff = [];
  let permGroups = [];
  let editingId = null;

  function init(context) { ctx = context; }

  async function load() {
    [staff, permGroups] = await Promise.all([
      ctx.api("/staff"),
      ctx.api("/staff/permissions"),
    ]);
    render();
  }

  function render() {
    const el = document.getElementById("staff-table");
    if (!el) return;
    if (!staff.length) {
      el.innerHTML = '<div class="empty-state"><p>No staff yet.</p><button class="btn btn-primary btn-lg" style="margin-top:16px;" onclick="StaffMgmt.openWizard()">+ Add Staff</button></div>';
      return;
    }
    el.innerHTML = `<table class="data"><thead><tr><th>Name</th><th>Phone (Login ID)</th><th>Permissions</th><th></th></tr></thead><tbody>
      ${staff.map(s => `<tr class="clickable" onclick="StaffMgmt.openDetail(${s.id})">
        <td><strong>${ctx.esc(s.name)}</strong></td>
        <td>${ctx.esc(s.phone)}</td>
        <td style="font-size:12px;color:var(--muted);">${s.permissions.length ? s.permissions.map(p => `<span class="badge badge-gray" style="margin:2px;">${ctx.esc(p.replace('.', ' '))}</span>`).join("") : "—"}</td>
        <td onclick="event.stopPropagation()"><div class="actions">
          <button class="btn btn-ghost btn-sm" onclick="StaffMgmt.openEdit(${s.id})">Edit</button>
          <button class="btn btn-danger btn-sm" onclick="StaffMgmt.deleteStaff(${s.id},${JSON.stringify(s.name)})">Remove</button>
        </div></td>
      </tr>`).join("")}
    </tbody></table>`;
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

  function permCheckboxes(selected) {
    const sel = new Set(selected || []);
    return permGroups.map(g => `
      <div style="margin-bottom:12px;">
        <div style="font-size:12px;font-weight:700;color:var(--muted);margin-bottom:6px;">${ctx.esc(g.label)}</div>
        ${g.permissions.map(p => `<label style="display:flex;align-items:center;gap:8px;margin-bottom:4px;font-size:13px;">
          <input type="checkbox" class="staff-perm-cb" value="${ctx.esc(p.key)}" ${sel.has(p.key) ? "checked" : ""} />
          ${ctx.esc(p.label)}
        </label>`).join("")}
      </div>`).join("");
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

  return { init, load, openDetail, openWizard, openEdit, closeModal, save, deleteStaff };
})();
