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

