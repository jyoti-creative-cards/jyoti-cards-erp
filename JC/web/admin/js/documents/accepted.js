/** Setup — S3 Documents browser */
const Documents = (() => {
  let ctx = {};
  let currentPrefix = "JCC/";
  let lastData = { folders: [], files: [] };
  let searchQ = "";
  let renameKey = null;

  function init(context) { ctx = context; }

  function esc(s) { return ctx.esc ? ctx.esc(s) : String(s); }

  function canWrite() {
    return !!ctx.isAdmin?.();
  }

  function fmtSize(n) {
    if (n == null || n === "") return "—";
    const num = Number(n);
    if (!Number.isFinite(num) || num < 0) return "—";
    if (num === 0) return "0 B";
    if (num < 1024) return num + " B";
    if (num < 1024 * 1024) return (num / 1024).toFixed(1) + " KB";
    return (num / (1024 * 1024)).toFixed(1) + " MB";
  }

  function fmtFolderSize(f) {
    const count = Number(f.file_count) || 0;
    if (!count && !(Number(f.size) > 0)) return "—";
    const sizeBit = fmtSize(f.size || 0);
    return count ? `${sizeBit} · ${count} file${count === 1 ? "" : "s"}` : sizeBit;
  }

  function isImage(name) {
    return /\.(jpe?g|png|gif|webp|bmp|svg)$/i.test(name || "");
  }

  function fileNameCell(f) {
    const thumb = isImage(f.name) && f.url
      ? `<img src="${esc(f.url)}" class="doc-thumb" alt="" loading="lazy" />`
      : "";
    return `<div class="doc-name-cell">${thumb}<span>${esc(f.name)}</span></div>`;
  }

  function breadcrumbs() {
    const parts = currentPrefix.replace(/\/$/, "").split("/").filter(Boolean);
    let path = "";
    const crumbs = [`<button class="btn-ghost" style="font-size:13px;padding:4px 8px;" onclick="Documents.browse('JCC/')">JCC</button>`];
    parts.forEach((p, i) => {
      if (i === 0 && p === "JCC") return;
      path += p + "/";
      const pref = "JCC/" + path;
      crumbs.push(`<span style="color:var(--muted);">/</span><button class="btn-ghost" style="font-size:13px;padding:4px 8px;" onclick="Documents.browse('${pref}')">${esc(p)}</button>`);
    });
    return crumbs.join(" ");
  }

  function moreMenu(items) {
    if (!items?.length) return "";
    const id = `doc-more-${Math.random().toString(36).slice(2, 9)}`;
    return `<div class="ord-more" onclick="event.stopPropagation()">
      <button type="button" class="btn btn-ghost btn-sm ord-more-btn" onclick="OrdersUI.toggleMore('${id}')">More ▾</button>
      <div class="ord-more-menu hidden" id="${id}">
        ${items.map(it => `<button type="button" class="ord-more-item${it.danger ? " is-danger" : ""}" onclick="${it.onclick}">${esc(it.label)}</button>`).join("")}
      </div>
    </div>`;
  }

  async function browse(prefix) {
    currentPrefix = prefix || "JCC/";
    ctx.showLoading?.();
    try {
      const data = await ctx.api(`/documents?prefix=${encodeURIComponent(currentPrefix)}`, {}, 0);
      lastData = data || { folders: [], files: [] };
      render();
      const count = document.getElementById("hub-documents-count");
      if (count) {
        const n = (lastData.folders || []).length + (lastData.files || []).length;
        count.textContent = currentPrefix === "JCC/" ? "Files" : `${n} item${n === 1 ? "" : "s"}`;
      }
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function setSearch(val) {
    searchQ = val || "";
    render();
  }

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

  return {
    init, load, browse, viewFile, openFile, newFolder, uploadFile, renameFile, deleteFile,
    setSearch, submitFolder, submitRename,
  };
})();
