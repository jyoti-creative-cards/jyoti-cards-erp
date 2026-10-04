  function render() {
    const el = document.getElementById("documents-browser");
    if (!el) return;
    const caret = (typeof OrdersUI !== "undefined" && OrdersUI.captureSearchCaret)
      ? OrdersUI.captureSearchCaret("doc-search") : null;
    const write = canWrite();
    const q = searchQ.trim().toLowerCase();
    let folders = lastData.folders || [];
    let files = lastData.files || [];
    if (q) {
      folders = folders.filter(f => String(f.name || "").toLowerCase().includes(q));
      files = files.filter(f => String(f.name || "").toLowerCase().includes(q));
    }
    const empty = !folders.length && !files.length;
    el.innerHTML = `
      <div class="doc-toolbar">
        <div class="doc-crumbs">${breadcrumbs()}</div>
        <div class="doc-toolbar-actions">
          ${HubUI.searchBar({
            id: "doc-search",
            value: searchQ,
            placeholder: "Search this folder…",
            oninput: "Documents.setSearch(this.value)",
          })}
          ${write ? `<button class="btn btn-secondary btn-sm" onclick="Documents.newFolder()">+ Folder</button>
          <label class="btn btn-primary btn-sm" style="cursor:pointer;margin:0;">Upload<input type="file" class="hidden" onchange="Documents.uploadFile(this.files[0])" /></label>` : ""}
        </div>
      </div>
      ${empty
        ? HubUI.emptyState({
          title: q ? "No matches" : "Empty folder",
          sub: q ? "Try another search." : "Upload a file or create a folder.",
          ctaHtml: (!q && write)
            ? `<label class="btn btn-primary" style="cursor:pointer;margin:0;">Upload<input type="file" class="hidden" onchange="Documents.uploadFile(this.files[0])" /></label>`
            : "",
        })
        : `<div class="card table-wrap">
        <table class="data"><thead><tr><th>Name</th><th>Size</th><th>Modified</th><th></th></tr></thead><tbody>
          ${folders.map(f => `<tr class="clickable" onclick="Documents.browse('${f.prefix}')">
            <td><strong class="doc-folder-name">${esc(f.name)}</strong></td>
            <td>${fmtFolderSize(f)}</td>
            <td style="font-size:12px;color:var(--muted);">${f.last_modified ? new Date(f.last_modified).toLocaleString() : "—"}</td>
            <td></td></tr>`).join("")}
          ${files.map(f => {
            const keyEsc = f.key.replace(/'/g, "\\'");
            const nameEsc = f.name.replace(/'/g, "\\'");
            const items = [
              { label: "View", onclick: `Documents.viewFile('${nameEsc}', '${f.url}')` },
              { label: "Print", onclick: `Documents.openFile('${f.url}', true)` },
              { label: "Download", onclick: `Documents.openFile('${f.url}', false)` },
            ];
            if (write) {
              items.push({ label: "Rename", onclick: `Documents.renameFile('${keyEsc}')` });
              items.push({ label: "Delete", onclick: `Documents.deleteFile('${keyEsc}')`, danger: true });
            }
            return `<tr>
            <td>${fileNameCell(f)}</td>
            <td>${fmtSize(f.size)}</td>
            <td style="font-size:12px;color:var(--muted);">${f.last_modified ? new Date(f.last_modified).toLocaleString() : "—"}</td>
            <td>${moreMenu(items)}</td></tr>`;
          }).join("")}
        </tbody></table>
      </div>`}`;
    if (caret && typeof OrdersUI !== "undefined") OrdersUI.restoreSearchCaret("doc-search", caret);
  }

  function openFile(url, print) {
    if (!url) return ctx.toast("No URL", "error");
    const w = window.open(url, "_blank");
    if (print && w) w.addEventListener("load", () => w.print());
  }

  function viewFile(name, url) {
    if (!url) return ctx.toast("No URL", "error");
    const lower = (name || "").toLowerCase();
    let body = "";
    if (isImage(lower)) {
      body = `<div style="text-align:center;"><img src="${esc(url)}" style="max-width:100%;max-height:70vh;border-radius:8px;" alt="" /></div>`;
    } else if (lower.endsWith(".pdf")) {
      body = `<iframe src="${esc(url)}" style="width:100%;height:70vh;border:none;border-radius:8px;" title="${esc(name)}"></iframe>`;
    } else {
      body = `<p style="color:var(--muted);margin:0 0 12px;">Preview not available for this file type.</p>
        <a href="${esc(url)}" target="_blank" rel="noopener" class="btn btn-primary">Open file</a>`;
    }
    ctx.openDetail?.(name, body,
      `<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "lg");
  }

  function newFolder() {
    if (!canWrite()) return;
    const modal = document.getElementById("modal");
    if (!modal) return;
    document.getElementById("modal-title").textContent = "New folder";
    document.getElementById("modal-body").innerHTML = `
      <label class="label">Folder name</label>
      <input id="doc-folder-name" class="input" placeholder="e.g. Invoices" />`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="Documents.submitFolder()">Create</button>`;
    modal.classList.remove("hidden");
  }

  async function submitFolder() {
    const name = document.getElementById("doc-folder-name")?.value?.trim();
    if (!name) return ctx.toast("Folder name required", "error");
    try {
      await ctx.api("/documents/folder", { method: "POST", body: JSON.stringify({ prefix: currentPrefix, name }) });
      ctx.toast("Folder created", "success");
      App.closeModal?.();
      browse(currentPrefix);
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function uploadFile(file) {
    if (!file || !canWrite()) return;
    ctx.showLoading?.();
    try {
      const fd = new FormData();
      fd.append("prefix", currentPrefix);
      fd.append("file", file);
      const API = ctx.apiBase ? ctx.apiBase() : `${location.origin}/api/v1`;
      const h = {};
      if (sessionStorage.getItem("jc_auth_mode") === "admin") h["X-Admin-Key"] = sessionStorage.getItem("jc_admin_key") || "";
      else h["Authorization"] = `Bearer ${sessionStorage.getItem("jc_staff_token") || ""}`;
      const res = await fetch(`${API}/documents/upload`, { method: "POST", headers: h, body: fd });
      if (!res.ok) throw new Error("Upload failed");
      ctx.toast("Uploaded", "success");
      browse(currentPrefix);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

