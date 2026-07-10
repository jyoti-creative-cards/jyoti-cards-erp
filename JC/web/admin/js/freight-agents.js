/** Setup — Freight agents create / list */
const FreightAgentsSetup = (() => {
  let ctx = {};
  let agents = [];

  function init(context) { ctx = context; }

  function fmtPrice(val) {
    if (val == null || val === "") return "₹0";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  async function load() {
    ctx.showLoading?.();
    try {
      agents = await ctx.api("/freight-agents", {}, 0);
      render();
      const count = document.getElementById("hub-freight-count");
      if (count) count.textContent = `${agents.length} agent${agents.length === 1 ? "" : "s"}`;
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function render() {
    const el = document.getElementById("freight-agents-root");
    if (!el) return;
    const canWrite = ctx.isAdmin?.();
    el.innerHTML = `
      ${canWrite ? `<form class="card" style="padding:20px;margin-bottom:20px;" onsubmit="FreightAgentsSetup.create(event)">
        <h3 style="margin:0 0 16px;font-size:16px;">Create freight agent</h3>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Name *</label><input id="fa-name" class="input" required placeholder="e.g. Blue Dart local" /></div>
          <div><label class="label">Notes</label><input id="fa-notes" class="input" placeholder="Optional" /></div>
        </div>
        <div style="margin-top:14px;"><button type="submit" class="btn btn-primary">Create agent</button></div>
      </form>` : ""}
      <div class="card table-wrap">
        <div style="display:flex;justify-content:space-between;align-items:center;padding:16px 16px 0;">
          <h3 style="margin:0;font-size:16px;">Freight agents</h3>
          <button class="btn btn-secondary btn-sm" onclick="FreightAgentsSetup.load()">↻ Refresh</button>
        </div>
        <table class="data" style="margin-top:12px;"><thead><tr>
          <th>Name</th><th>Outstanding</th><th>Notes</th>
        </tr></thead><tbody>
          ${agents.map(a => `<tr>
            <td><strong>${ctx.esc(a.name)}</strong></td>
            <td>${fmtPrice(a.balance_due)}</td>
            <td style="color:var(--muted);">${ctx.esc(a.notes || "—")}</td>
          </tr>`).join("")}
          ${!agents.length ? `<tr><td colspan="3" style="text-align:center;padding:32px;color:var(--muted);">No freight agents yet.</td></tr>` : ""}
        </tbody></table>
      </div>`;
  }

  async function create(e) {
    e.preventDefault();
    const name = document.getElementById("fa-name")?.value?.trim();
    const notes = document.getElementById("fa-notes")?.value?.trim() || null;
    if (!name) return ctx.toast("Name required", "error");
    ctx.showLoading?.();
    try {
      await ctx.api("/freight-agents", { method: "POST", body: JSON.stringify({ name, notes }) });
      ctx.toast("Freight agent created", "success");
      await load();
    } catch (err) { ctx.toast(err.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  return { init, load, create };
})();
