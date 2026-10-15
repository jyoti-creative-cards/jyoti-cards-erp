const WhatsAppInbox = (() => {
  let threads = [];
  let active = "";

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
    if (mode === "admin") h["X-Admin-Key"] = sessionStorage.getItem("jc_admin_key") || "";
    else h.Authorization = `Bearer ${sessionStorage.getItem("jc_staff_token") || ""}`;
    return h;
  }

  async function call(path, opts = {}) {
    const res = await fetch(`${apiBase()}${path}`, {
      ...opts,
      headers: { ...headers(), ...(opts.headers || {}) },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const detail = typeof err.detail === "string" ? err.detail : `HTTP ${res.status}`;
      throw new Error(detail);
    }
    return res.json();
  }

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function when(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  }

  function titleOf(row) {
    return row.customer_name || row.contact_name || row.phone;
  }

  function renderThreads() {
    const box = document.getElementById("wa-threads");
    if (!box) return;
    if (!threads.length) {
      box.innerHTML = '<div class="wa-empty" style="padding:16px;">No replies yet. They show up here after a customer messages this number.</div>';
      return;
    }
    box.innerHTML = threads.map(row => `
      <button type="button" class="wa-thread${row.phone === active ? " active" : ""}" onclick="WhatsAppInbox.openThread('${esc(row.phone)}')">
        <div class="wa-thread-name">${esc(titleOf(row))}</div>
        <div class="wa-thread-preview">${esc(row.phone)} · ${esc(row.body)}</div>
      </button>
    `).join("");
  }

  function renderMessages(phone, messages) {
    const head = document.getElementById("wa-chat-head");
    const box = document.getElementById("wa-bubbles");
    if (!phone) {
      if (head) head.textContent = "Select a chat";
      if (box) box.innerHTML = "";
      return;
    }
    const first = messages[0] || threads.find(row => row.phone === phone) || { phone };
    if (head) head.textContent = `${titleOf(first)} · ${phone}`;
    if (!box) return;
    if (!messages.length) {
      box.innerHTML = '<div class="wa-empty">No messages in this chat.</div>';
      return;
    }
    box.innerHTML = messages.map(row => `
      <div class="wa-bubble ${row.direction === "out" ? "out" : "in"}">
        ${esc(row.body)}
        <time>${esc(when(row.at))}</time>
      </div>
    `).join("");
    box.scrollTop = box.scrollHeight;
  }

  async function openThread(phone) {
    active = phone;
    renderThreads();
    const data = await call(`/whatsapp/inbox/${encodeURIComponent(phone)}`);
    renderMessages(phone, data.messages || []);
  }

  async function load() {
    const data = await call("/whatsapp/inbox");
    threads = data.threads || [];
    renderThreads();
    if (active) await openThread(active);
    else renderMessages("", []);
  }

  async function open() {
    App.showView("whatsapp");
    document.getElementById("nav-more")?.classList.add("active");
    try {
      await load();
    } catch (err) {
      const box = document.getElementById("wa-threads");
      if (box) box.innerHTML = `<div class="wa-empty" style="padding:16px;">${esc(err.message)}</div>`;
    }
  }

  async function send(event) {
    event.preventDefault();
    if (!active) return false;
    const input = document.getElementById("wa-reply-text");
    const text = (input?.value || "").trim();
    if (!text) return false;
    try {
      await call(`/whatsapp/inbox/${encodeURIComponent(active)}/reply`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      if (input) input.value = "";
      await openThread(active);
      await load();
    } catch (err) {
      alert(err.message);
    }
    return false;
  }

  return { open, load, openThread, send };
})();
