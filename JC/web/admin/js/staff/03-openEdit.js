  async function openEdit(id) {
    const s = staff.find(x => x.id === id) || await ctx.api(`/staff/${id}`);
    editingId = id;
    document.getElementById("staff-modal-title").textContent = "Edit Staff — " + s.name;
    document.getElementById("staff-modal-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Full Name *</label><input id="sm-name" class="input" value="${ctx.esc(s.name)}" /></div>
        <div><label class="label">Login ID (mobile)</label><input id="sm-phone" class="input" type="tel" maxlength="10" value="${ctx.esc(s.phone)}" />
          <p style="margin:6px 0 0;font-size:12px;color:var(--muted);">Changing this changes their login number too.</p></div>
        <div><label class="label">Permissions</label><div class="card" style="padding:16px;max-height:420px;overflow-y:auto;">${permCheckboxes(s.permissions)}</div></div>
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

