/** Setup — S3 Documents browser */
const Documents = (() => {
  let ctx = {};
  let currentPrefix = "JCC/";

  function init(context) { ctx = context; }

  function esc(s) { return ctx.esc ? ctx.esc(s) : String(s); }

  function fmtSize(n) {
    if (!n) return "—";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / (1024 * 1024)).toFixed(1) + " MB";
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

  async function browse(prefix) {
    currentPrefix = prefix || "JCC/";
    ctx.showLoading?.();
    try {
      const data = await ctx.api(`/documents?prefix=${encodeURIComponent(currentPrefix)}`, {}, 0);
      render(data);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function render(data) {
    const el = document.getElementById("documents-browser");
    if (!el) return;
    const folders = data.folders || [];
    const files = data.files || [];
    el.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:12px;">
        <div style="display:flex;align-items:center;gap:4px;flex-wrap:wrap;">${breadcrumbs()}</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-secondary btn-sm" onclick="Documents.newFolder()">+ Folder</button>
          <label class="btn btn-primary btn-sm" style="cursor:pointer;margin:0;">Upload<input type="file" class="hidden" onchange="Documents.uploadFile(this.files[0])" /></label>
        </div>
      </div>
      <div class="card table-wrap">
        <table class="data"><thead><tr><th>Name</th><th>Size</th><th>Modified</th><th></th></tr></thead><tbody>
          ${folders.map(f => `<tr class="clickable" onclick="Documents.browse('${f.prefix}')">
            <td><strong>📁 ${esc(f.name)}</strong></td><td>—</td><td>—</td><td></td></tr>`).join("")}
          ${files.map(f => `<tr>
            <td>${fileNameCell(f)}</td>
            <td>${fmtSize(f.size)}</td>
            <td style="font-size:12px;color:var(--muted);">${f.last_modified ? new Date(f.last_modified).toLocaleString() : "—"}</td>
            <td style="white-space:nowrap;">
              <button class="btn btn-primary btn-sm" onclick="Documents.viewFile('${f.name.replace(/'/g, "\\'")}', '${f.url}')">View</button>
              <button class="btn btn-secondary btn-sm" onclick="Documents.openFile('${f.url}', true)">Print</button>
              <button class="btn btn-secondary btn-sm" onclick="Documents.openFile('${f.url}', false)">Download</button>
              <button class="btn btn-secondary btn-sm" onclick="Documents.renameFile('${f.key.replace(/'/g, "\\'")}')">Rename</button>
              <button class="btn btn-danger btn-sm" onclick="Documents.deleteFile('${f.key.replace(/'/g, "\\'")}')">Delete</button>
            </td></tr>`).join("")}
          ${!folders.length && !files.length ? `<tr><td colspan="4" style="text-align:center;padding:32px;color:var(--muted);">Empty folder</td></tr>` : ""}
        </tbody></table>
      </div>`;
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

  async function newFolder() {
    const name = prompt("Folder name:");
    if (!name?.trim()) return;
    try {
      await ctx.api("/documents/folder", { method: "POST", body: JSON.stringify({ prefix: currentPrefix, name: name.trim() }) });
      ctx.toast("Folder created", "success");
      browse(currentPrefix);
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function uploadFile(file) {
    if (!file) return;
    ctx.showLoading?.();
    try {
      const fd = new FormData();
      fd.append("prefix", currentPrefix);
      fd.append("file", file);
      const API = ctx.apiBase ? ctx.apiBase() : "http://127.0.0.1:8003/api/v1";
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

  async function renameFile(key) {
    const newName = prompt("New file name (full path from JCC/):", key);
    if (!newName || newName === key) return;
    try {
      await ctx.api("/documents/rename", { method: "PATCH", body: JSON.stringify({ src_key: key, dest_key: newName }) });
      ctx.toast("Renamed", "success");
      browse(currentPrefix);
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function deleteFile(key) {
    if (!confirm("Delete this file from S3?")) return;
    try {
      await ctx.api(`/documents?key=${encodeURIComponent(key)}`, { method: "DELETE" });
      ctx.toast("Deleted", "success");
      browse(currentPrefix);
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  function load() { browse(currentPrefix); }

  return { init, load, browse, viewFile, openFile, newFolder, uploadFile, renameFile, deleteFile };
})();
