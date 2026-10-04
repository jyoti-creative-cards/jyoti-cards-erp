  async function create() {
    const btn = document.getElementById("addon-create-btn");
    if (btn) btn.disabled = true;
    const name = (document.getElementById("aw-our_product_id")?.value || wizardForm.our_product_id || "").trim();
    const qtyRaw = document.getElementById("aw-quantity")?.value ?? wizardForm.quantity ?? "0";
    const quantity = parseInt(qtyRaw, 10) || 0;
    if (!name) {
      if (btn) btn.disabled = false;
      return ctx.toast("Add-on name required", "error");
    }
    if (quantity < 0) {
      if (btn) btn.disabled = false;
      return ctx.toast("Quantity cannot be negative", "error");
    }
    try {
      const result = await ctx.api("/addons", { method: "POST", body: JSON.stringify({
        our_product_id: name,
        quantity,
      })});
      wizardForm._result = result;
      wizardForm.our_product_id = name;
      wizardStep = 2;
      renderWizard();
      await refreshAfterMutation();
      ctx.invalidateCache?.("/stats");
      if (ctx.refreshStats) await ctx.refreshStats();
      ctx.toast("Addon product created", "success");
    } catch (e) {
      ctx.toast(e.message, "error");
      if (btn) btn.disabled = false;
    }
  }

  async function openEdit(id) {
    const a = await ctx.api(`/addons/${id}`);
    editingId = id;
    document.getElementById("addon-edit-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Name</label><input id="ae-our_product_id" class="input" value="${ctx.esc(a.our_product_id)}" /></div>
        <div><label class="label">Description</label><textarea id="ae-description" class="input" rows="2">${ctx.esc(a.description || "")}</textarea></div>
      </div>`;
    document.getElementById("addon-edit-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="AddonProducts.closeEdit()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="AddonProducts.save()">Save Changes</button>`;
    document.getElementById("addon-edit-modal").classList.remove("hidden");
  }

  function closeEdit() {
    document.getElementById("addon-edit-modal").classList.add("hidden");
    editingId = null;
  }

  async function save() {
    if (!editingId) return;
    const name = document.getElementById("ae-our_product_id").value.trim();
    if (!name) return ctx.toast("Name required", "error");
    const body = {
      our_product_id: name,
      description: document.getElementById("ae-description").value.trim() || null,
    };
    try {
      await ctx.api(`/addons/${editingId}`, { method: "PATCH", body: JSON.stringify(body) });
      const id = editingId;
      closeEdit();
      App.closeDetail();
      await refreshAfterMutation();
      ctx.toast("Addon updated", "success");
      openDetail(id);
    } catch (e) {
      ctx.toast(e.message, "error");
    }
  }

  async function deleteAddon(id) {
    if (!confirm("Move this addon product to recycle bin?")) return;
    try {
      await ctx.api(`/addons/${id}`, { method: "DELETE" });
      App.closeDetail();
      await refreshAfterMutation();
      ctx.invalidateCache?.("/stats");
      if (ctx.refreshStats) await ctx.refreshStats();
      ctx.toast("Addon moved to recycle bin", "success");
    } catch (e) {
      ctx.toast(e.message, "error");
    }
  }

