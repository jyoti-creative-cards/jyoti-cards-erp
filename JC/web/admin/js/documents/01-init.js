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

