  function renameFile(key) {
    if (!canWrite()) return;
    renameKey = key;
    const base = key.split("/").pop() || key;
    const modal = document.getElementById("modal");
    if (!modal) return;
    document.getElementById("modal-title").textContent = "Rename file";
    document.getElementById("modal-body").innerHTML = `
      <label class="label">New file name</label>
      <input id="doc-rename-name" class="input" value="${esc(base)}" />
      <p style="margin:8px 0 0;font-size:12px;color:var(--muted);">Stays in the same folder.</p>`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Documents.submitRename()">Rename</button>`;
    modal.classList.remove("hidden");
  }

  async function submitRename() {
    if (!renameKey) return;
    const newBase = document.getElementById("doc-rename-name")?.value?.trim();
    if (!newBase) return ctx.toast("Name required", "error");
    const parts = renameKey.split("/");
    parts[parts.length - 1] = newBase;
    const dest = parts.join("/");
    if (dest === renameKey) { App.closeModal?.(); return; }
    try {
      await ctx.api("/documents/rename", { method: "PATCH", body: JSON.stringify({ src_key: renameKey, dest_key: dest }) });
      ctx.toast("Renamed", "success");
      App.closeModal?.();
      renameKey = null;
      browse(currentPrefix);
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function deleteFile(key) {
    if (!canWrite()) return;
    if (!confirm("Delete this file from storage?")) return;
    try {
      await ctx.api(`/documents?key=${encodeURIComponent(key)}`, { method: "DELETE" });
      ctx.toast("Deleted", "success");
      browse(currentPrefix);
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  function load() { browse(currentPrefix); }

