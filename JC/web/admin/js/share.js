/** Print / PDF / WhatsApp share helpers */
const DocShare = (() => {
  let ctx = null;

  function init(c) { ctx = c; }

  function authHeaders() {
    const h = ctx?.headers?.() || {};
    // blob downloads must not force JSON content-type
    const out = { ...h };
    delete out["Content-Type"];
    return out;
  }

  function apiBase() {
    return (ctx?.apiBase?.() || "").replace(/\/$/, "");
  }

  async function openPdf(path, { print = false, filename = "document.pdf" } = {}) {
    const res = await fetch(`${apiBase()}${path}`, { headers: authHeaders() });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const msg = typeof err.detail === "string" ? err.detail : `HTTP ${res.status}`;
      throw new Error(msg);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    if (print) {
      const w = window.open(url, "_blank");
      if (w) {
        w.addEventListener("load", () => { try { w.print(); } catch (_) {} });
        setTimeout(() => { try { w.print(); } catch (_) {} }, 800);
      }
    } else {
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
    }
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  async function whatsapp(body) {
    return ctx.api("/share/whatsapp", { method: "POST", body: JSON.stringify(body) }, 0);
  }

  async function shareFlow({ kind, id, day, side, phone, caption, filename }) {
    const actions = [
      { label: "Print", run: async () => openPdf(pdfPath({ kind, id, day, side }), { print: true, filename }) },
      { label: "Download PDF", run: async () => openPdf(pdfPath({ kind, id, day, side }), { print: false, filename }) },
      {
        label: "WhatsApp",
        run: async () => {
          const res = await whatsapp({ kind, id, day, side, phone: phone || undefined, caption: caption || "" });
          if (res.ok) ctx.toast("Sent on WhatsApp", "success");
          else {
            ctx.toast(res.hint || res.whatsapp?.error || "WA send failed — try link", "error");
            if (res.wa_me) window.open(res.wa_me, "_blank");
          }
        },
      },
    ];
    ctx.openDetail?.(
      "Share",
      `<p style="margin:0 0 12px;color:var(--muted);font-size:14px;">Print, download PDF, or send on WhatsApp.</p>
       <div style="display:flex;flex-direction:column;gap:8px;">
         ${actions.map((a, i) => `<button class="btn ${i === 0 ? "btn-primary" : "btn-secondary"}" style="width:100%;" data-share-i="${i}">${a.label}</button>`).join("")}
       </div>`,
      `<button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "sm",
    );
    setTimeout(() => {
      document.querySelectorAll("[data-share-i]").forEach(btn => {
        btn.addEventListener("click", async () => {
          const i = Number(btn.getAttribute("data-share-i"));
          ctx.showLoading?.();
          try { await actions[i].run(); } catch (e) { ctx.toast(e.message, "error"); }
          finally { ctx.hideLoading?.(); }
        });
      });
    }, 0);
  }

  function pdfPath({ kind, id, day, side }) {
    if (kind === "bill") return `/share/bills/${id}/pdf`;
    if (kind === "ar_statement") return `/share/statements/ar/${id}/pdf`;
    if (kind === "ap_statement") return `/share/statements/ap/${id}/pdf`;
    if (kind === "freight_statement") return `/share/statements/freight/${id}/pdf`;
    if (kind === "freight_payment") return `/share/freight-payments/${id}/pdf`;
    if (kind === "daybook") return `/share/daybook/pdf?day=${encodeURIComponent(day)}`;
    if (kind === "ageing") return `/share/ageing/pdf?side=${encodeURIComponent(side || "ar")}`;
    throw new Error("unknown share kind");
  }

  async function downloadExport(kindOrBackup) {
    const path = kindOrBackup === "backup"
      ? "/export/backup.zip"
      : `/export/${kindOrBackup}.xlsx`;
    const res = await fetch(`${apiBase()}${path}`, { headers: authHeaders() });
    if (!res.ok) {
      let msg = `Export failed (${res.status})`;
      try {
        const err = await res.json();
        if (err.detail) msg = typeof err.detail === "string" ? err.detail : msg;
      } catch (_) { /* ignore */ }
      throw new Error(msg);
    }
    const blob = await res.blob();
    const stamp = new Date().toISOString().slice(0, 10);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = kindOrBackup === "backup" ? `jc_full_backup_${stamp}.zip` : `${kindOrBackup}.xlsx`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  }

  function toolbarHtml({ printOnclick, pdfOnclick, waOnclick, excelOnclick }) {
    const btns = [];
    if (printOnclick) btns.push(`<button type="button" class="btn btn-secondary btn-sm" onclick="${printOnclick}">Print</button>`);
    if (pdfOnclick) btns.push(`<button type="button" class="btn btn-secondary btn-sm" onclick="${pdfOnclick}">PDF</button>`);
    if (waOnclick) btns.push(`<button type="button" class="btn btn-secondary btn-sm" onclick="${waOnclick}">WhatsApp</button>`);
    if (excelOnclick) btns.push(`<button type="button" class="btn btn-secondary btn-sm" onclick="${excelOnclick}">Excel</button>`);
    return btns.length ? `<div class="rep-share-bar" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">${btns.join("")}</div>` : "";
  }

  return { init, openPdf, whatsapp, shareFlow, pdfPath, downloadExport, toolbarHtml };
})();
