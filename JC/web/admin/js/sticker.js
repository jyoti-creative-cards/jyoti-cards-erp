/** Print sticker — search a party number, print name, city, mobile, and the print time on A5. */
const Sticker = (() => {
  let timer = null;
  let picked = null;
  let lastQuery = "";

  function apiBase() {
    const saved = localStorage.getItem("jc_api");
    if (saved) return saved;
    const host = location.hostname;
    if (host === "127.0.0.1" || host === "localhost") return "http://127.0.0.1:8003/api/v1";
    return `${location.origin}/api/v1`;
  }

  function headers() {
    const h = { "Content-Type": "application/json" };
    const mode = sessionStorage.getItem("jc_auth_mode") || "";
    if (mode === "admin") {
      const key = sessionStorage.getItem("jc_admin_key") || "";
      if (key) h["X-Admin-Key"] = key;
    } else if (mode === "staff") {
      const token = sessionStorage.getItem("jc_staff_token") || "";
      if (token) h["Authorization"] = `Bearer ${token}`;
    }
    return h;
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function ensureModal() {
    if (document.getElementById("sticker-modal")) return;
    const wrap = document.createElement("div");
    wrap.id = "sticker-modal";
    wrap.className = "modal-overlay hidden";
    wrap.innerHTML = `
      <div class="modal" style="max-width:480px;" role="dialog" aria-label="Print sticker">
        <div class="modal-header">
          <h3 style="margin:0;">Print sticker</h3>
          <button type="button" class="btn-ghost" onclick="Sticker.close()">✕</button>
        </div>
        <div class="modal-body">
          <label class="label">Party number
            <input id="sticker-q" class="input" type="search" autocomplete="off" placeholder="Type the party number" oninput="Sticker.onType(this.value)" />
          </label>
          <div id="sticker-results"></div>
          <p id="sticker-picked" class="fin-panel-sub" style="margin:12px 0 0;"></p>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" onclick="Sticker.close()">Close</button>
          <button type="button" class="btn btn-primary" id="sticker-print" onclick="Sticker.print()" disabled>Print A5</button>
        </div>
      </div>`;
    wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
    document.body.appendChild(wrap);
  }

  function open() {
    ensureModal();
    picked = null;
    lastQuery = "";
    const modal = document.getElementById("sticker-modal");
    modal.classList.remove("hidden");
    const input = document.getElementById("sticker-q");
    if (input) { input.value = ""; input.focus(); }
    const box = document.getElementById("sticker-results");
    if (box) box.innerHTML = "";
    const note = document.getElementById("sticker-picked");
    if (note) note.textContent = "Type a party number. Pick the party. Then print.";
    const btn = document.getElementById("sticker-print");
    if (btn) btn.disabled = true;
  }

  function close() {
    document.getElementById("sticker-modal")?.classList.add("hidden");
  }

  function onType(value) {
    const q = String(value || "").trim();
    picked = null;
    const btn = document.getElementById("sticker-print");
    if (btn) btn.disabled = true;
    const note = document.getElementById("sticker-picked");
    if (note) note.textContent = "";
    clearTimeout(timer);
    if (!q) {
      const box = document.getElementById("sticker-results");
      if (box) box.innerHTML = "";
      return;
    }
    timer = setTimeout(() => search(q), 180);
  }

  async function search(q) {
    lastQuery = q;
    const box = document.getElementById("sticker-results");
    if (!box) return;
    try {
      const res = await fetch(`${apiBase()}/customers/quick-search?q=${encodeURIComponent(q)}`, { headers: headers() });
      if (!res.ok) throw new Error("Could not search parties");
      const rows = await res.json();
      if (lastQuery !== q) return;
      const list = Array.isArray(rows) ? rows : [];
      if (!list.length) {
        box.innerHTML = `<p class="fin-panel-sub" style="margin:8px 0 0;">No party for that number.</p>`;
        return;
      }
      box.innerHTML = `<div class="sticker-results">${list.map((r, i) => `
        <button type="button" class="sticker-hit" onclick="Sticker.pick(${i})">
          <strong>${esc(r.business_name || "Party")} · ${esc(r.party_number ?? "")}</strong>
          <span>${esc(r.city_name || "—")} · ${esc(r.phone || "—")}</span>
        </button>`).join("")}</div>`;
      box._rows = list;
    } catch (e) {
      box.innerHTML = `<p class="fin-panel-sub" style="margin:8px 0 0;">${esc(e.message || "Search failed")}</p>`;
    }
  }

  function pick(index) {
    const box = document.getElementById("sticker-results");
    const row = box && box._rows ? box._rows[index] : null;
    if (!row) return;
    picked = row;
    document.querySelectorAll(".sticker-hit").forEach((el, i) => el.classList.toggle("is-on", i === index));
    const note = document.getElementById("sticker-picked");
    if (note) {
      note.textContent = `${row.business_name || "Party"} · ${row.city_name || "—"} · ${row.phone || "—"}`;
    }
    const btn = document.getElementById("sticker-print");
    if (btn) btn.disabled = false;
  }

  function printTime() {
    return new Date().toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata",
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: true,
    });
  }

  async function hindiLabel() {
    const res = await fetch(`${apiBase()}/customers/${picked.id}/sticker`, { headers: headers() });
    if (!res.ok) throw new Error("Could not load the Hindi name");
    return res.json();
  }

  function print() {
    if (!picked) return;
    const note = document.getElementById("sticker-picked");
    hindiLabel().then((label) => {
      const when = printTime();
      const html = `<!DOCTYPE html><html lang="hi"><head><meta charset="utf-8"><title>Sticker</title>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@500;700&display=swap">
        <style>
          @page { size: A5; margin: 14mm; }
          html, body { margin: 0; padding: 0; }
          body { color: #111; }
          .time, .phone { font-family: Helvetica, Arial, sans-serif; }
          .name, .city { font-family: "Noto Sans Devanagari", "Kohinoor Devanagari", "Nirmala UI", "Mangal", sans-serif; }
          .time { font-size: 16px; margin: 0 0 28px; }
          .name { font-size: 32px; font-weight: 700; margin: 0 0 16px; line-height: 1.35; }
          .city, .phone { font-size: 24px; margin: 0 0 12px; line-height: 1.35; }
        </style></head><body>
          <p class="time">${esc(when)}</p>
          <p class="name" lang="hi">${esc(label.name_hi || "")}</p>
          <p class="city" lang="hi">${esc(label.city_hi || "")}</p>
          <p class="phone">${esc(label.phone || "")}</p>
        </body></html>`;
      const w = window.open("", "_blank");
      if (!w) {
        if (note) note.textContent = "Allow pop-ups to print.";
        return;
      }
      w.document.open();
      w.document.write(html);
      w.document.close();
      w.focus();
      const go = () => { try { w.print(); } catch (e) { /* browser print dialog */ } };
      let started = false;
      const once = () => { if (started) return; started = true; go(); };
      const fonts = w.document.fonts;
      if (fonts && fonts.ready) {
        const timer = setTimeout(once, 2000);
        fonts.ready.then(() => { clearTimeout(timer); once(); });
      } else {
        setTimeout(once, 300);
      }
    }).catch((e) => {
      if (note) note.textContent = e.message || "Could not load the Hindi name";
    });
  }

  return { open, close, onType, pick, print };
})();
