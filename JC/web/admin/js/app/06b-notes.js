  const tileNoteCache = {};
  let tileNoteTimer = null;
  let stickyNotes = [];
  let stickyOpen = false;
  let stickyMin = false;
  let stickyDrag = null;

  function tileNoteHtml(key) {
    const note = tileNoteCache[key] || "";
    const banner = note
      ? `<div style="display:block;margin:0;padding:8px 14px;background:#fef9c3;color:#854d0e;font-weight:800;font-size:15px;">Note: ${esc(note)}</div>`
      : "";
    return `${banner}<button type="button" class="btn btn-ghost btn-sm" style="margin:4px 14px 6px;" onclick="event.stopPropagation();App.editTileNote('${key}')">Add note</button>`;
  }

  function paintTileNotes(root) {
    (root || document).querySelectorAll("[data-tile-note]").forEach(el => {
      const key = el.getAttribute("data-tile-note");
      if (!key) return;
      el.innerHTML = tileNoteHtml(key);
    });
  }

  async function loadTileNotes(keys) {
    const wanted = [...new Set(keys.filter(Boolean))];
    if (!wanted.length) return;
    const data = await api(`/tile-notes?keys=${encodeURIComponent(wanted.join(","))}`, {}, 0);
    wanted.forEach(key => { tileNoteCache[key] = (data && data[key]) || ""; });
  }

  function scheduleTileNotes() {
    clearTimeout(tileNoteTimer);
    tileNoteTimer = setTimeout(async () => {
      const nodes = [...document.querySelectorAll("[data-tile-note]")];
      const keys = nodes.map(el => el.getAttribute("data-tile-note")).filter(Boolean);
      try { await loadTileNotes(keys); } catch (e) { return; }
      paintTileNotes(document);
    }, 60);
  }

  function installBoard() {
    if (window.__jcBoard) return;
    window.__jcBoard = true;
    const obs = new MutationObserver(() => scheduleTileNotes());
    obs.observe(document.body, { childList: true, subtree: true });
    scheduleTileNotes();
    ensureSticky();
  }

  async function editTileNote(key) {
    const next = prompt("Note for this tile", tileNoteCache[key] || "");
    if (next === null) return;
    const saved = await api(`/tile-notes/${encodeURIComponent(key)}`, {
      method: "PUT",
      body: JSON.stringify({ body: next }),
    });
    tileNoteCache[key] = (saved && saved.body) || "";
    paintTileNotes(document);
  }

  function stickyPos() {
    try { return JSON.parse(localStorage.getItem("jc_sticky_pos") || ""); }
    catch (e) { return null; }
  }

  function ensureSticky() {
    if (document.getElementById("jc-sticky")) return;
    const box = document.createElement("div");
    box.id = "jc-sticky";
    box.className = "jc-sticky";
    document.body.appendChild(box);
    const pos = stickyPos();
    if (pos && Number.isFinite(pos.x) && Number.isFinite(pos.y)) {
      box.style.left = pos.x + "px";
      box.style.top = pos.y + "px";
      box.style.right = "auto";
    }
    box.addEventListener("pointerdown", (e) => {
      if (!e.target.closest(".jc-sticky-bar")) return;
      const rect = box.getBoundingClientRect();
      stickyDrag = { dx: e.clientX - rect.left, dy: e.clientY - rect.top };
      box.setPointerCapture(e.pointerId);
    });
    box.addEventListener("pointermove", (e) => {
      if (!stickyDrag) return;
      const x = Math.max(8, e.clientX - stickyDrag.dx);
      const y = Math.max(8, e.clientY - stickyDrag.dy);
      box.style.left = x + "px";
      box.style.top = y + "px";
      box.style.right = "auto";
    });
    box.addEventListener("pointerup", () => {
      if (!stickyDrag) return;
      stickyDrag = null;
      const rect = box.getBoundingClientRect();
      localStorage.setItem("jc_sticky_pos", JSON.stringify({ x: rect.left, y: rect.top }));
    });
    renderSticky();
  }

  function toggleSticky() {
    ensureSticky();
    stickyOpen = !stickyOpen;
    if (stickyOpen) loadSticky();
    else renderSticky();
  }

  async function loadSticky() {
    try { stickyNotes = await api("/sticky-notes", {}, 0) || []; }
    catch (e) { toast(e.message, "error"); }
    renderSticky();
  }

  function renderSticky() {
    const box = document.getElementById("jc-sticky");
    if (!box) return;
    if (!stickyOpen) {
      box.innerHTML = `<button type="button" class="jc-sticky-fab" onclick="App.toggleSticky()">Notes</button>`;
      return;
    }
    const rows = stickyMin ? "" : (stickyNotes || []).map(note => `
      <div class="jc-sticky-item">
        <div>${esc(note.body)}</div>
        <div class="jc-sticky-meta">${esc(note.author_name || "")}
          <button type="button" onclick="App.deleteSticky(${note.id})">Delete</button>
        </div>
      </div>`).join("") || `<p class="jc-sticky-meta">Nothing here yet.</p>`;
    box.innerHTML = `
      <div class="jc-sticky-bar">
        <strong>Sticky notes</strong>
        <span>
          <button type="button" onclick="App.minimizeSticky()">${stickyMin ? "Open" : "Minimize"}</button>
          <button type="button" onclick="App.toggleSticky()">Close</button>
        </span>
      </div>
      ${rows}
      ${stickyMin ? "" : `<div class="jc-sticky-add">
        <textarea id="jc-sticky-text" placeholder="Write a note for everyone"></textarea>
        <button type="button" class="btn btn-primary btn-sm" onclick="App.addSticky()">Add</button>
      </div>`}`;
  }

  function minimizeSticky() {
    stickyMin = !stickyMin;
    renderSticky();
  }

  async function addSticky() {
    const text = document.getElementById("jc-sticky-text")?.value || "";
    if (!text.trim()) return;
    await api("/sticky-notes", { method: "POST", body: JSON.stringify({ body: text }) });
    await loadSticky();
  }

  async function deleteSticky(id) {
    await api(`/sticky-notes/${id}`, { method: "DELETE" });
    await loadSticky();
  }
