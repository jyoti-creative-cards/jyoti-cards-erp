/** Setup — Bill series create, list, drill-down */
const BillSeries = (() => {
  let ctx = {};
  let seriesList = [];
  let currentSeries = null;

  function init(context) { ctx = context; }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function statusBadge(s) {
    const exhausted = s.current_num >= s.end_num;
    if (exhausted) return `<span class="badge badge-amber">Exhausted</span>`;
    if (s.is_active) return `<span class="badge badge-green">Active</span>`;
    return `<span class="badge badge-gray">Inactive</span>`;
  }

  function usedCount(s) {
    if (s.current_num < s.start_num) return 0;
    return s.current_num - s.start_num + 1;
  }

  function totalCapacity(s) {
    return s.end_num - s.start_num + 1;
  }

  async function load() {
    currentSeries = null;
    ctx.showLoading?.();
    try {
      seriesList = await ctx.api("/bill-series", {}, 0);
      renderList();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderList() {
    const el = document.getElementById("bill-series-root");
    if (!el) return;
    el.innerHTML = `
      <form class="card" style="padding:20px;margin-bottom:20px;" onsubmit="BillSeries.create(event)">
        <h3 style="margin:0 0 16px;font-size:16px;">Create new bill series</h3>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;">
          <div><label class="label">Name *</label><input id="bs-name" class="input" required placeholder="e.g. FY2026" /></div>
          <div><label class="label">Prefix *</label><input id="bs-prefix" class="input" required placeholder="e.g. A" maxlength="10" /></div>
          <div><label class="label">Start #</label><input id="bs-start" class="input" type="number" min="1" value="1" /></div>
          <div><label class="label">End #</label><input id="bs-end" class="input" type="number" min="1" value="500" /></div>
        </div>
        <div style="margin-top:14px;"><button type="submit" class="btn btn-primary">Create series</button></div>
      </form>
      <div class="card table-wrap">
        <div style="display:flex;justify-content:space-between;align-items:center;padding:16px 16px 0;">
          <h3 style="margin:0;font-size:16px;">Bill series</h3>
          <button class="btn btn-secondary btn-sm" onclick="BillSeries.load()">↻ Refresh</button>
        </div>
        <table class="data" style="margin-top:12px;"><thead><tr>
          <th>Name</th><th>Prefix</th><th>Range</th><th>Used</th><th>Remaining</th><th>Status</th><th></th>
        </tr></thead><tbody>
          ${seriesList.map(s => `<tr class="clickable" onclick="BillSeries.openSeries(${s.id})">
            <td><strong>${ctx.esc(s.name)}</strong></td>
            <td style="font-family:monospace;color:var(--primary);">${ctx.esc(s.prefix)}</td>
            <td>${s.start_num}–${s.end_num}</td>
            <td>${usedCount(s)} / ${totalCapacity(s)}</td>
            <td>${totalCapacity(s) - usedCount(s)}</td>
            <td>${statusBadge(s)}</td>
            <td onclick="event.stopPropagation()">
              <button class="btn btn-danger btn-sm" onclick="BillSeries.deleteSeries(${s.id})">Delete</button>
            </td>
          </tr>`).join("")}
          ${!seriesList.length ? `<tr><td colspan="7" style="text-align:center;padding:32px;color:var(--muted);">No bill series yet.</td></tr>` : ""}
        </tbody></table>
      </div>`;
  }

  async function create(e) {
    e.preventDefault();
    const name = document.getElementById("bs-name")?.value?.trim();
    const prefix = document.getElementById("bs-prefix")?.value?.trim();
    const start_num = Number(document.getElementById("bs-start")?.value || 1);
    const end_num = Number(document.getElementById("bs-end")?.value || 0);
    if (!name || !prefix) return ctx.toast("Name and prefix required", "error");
    ctx.showLoading?.();
    try {
      await ctx.api("/bill-series", { method: "POST", body: JSON.stringify({ name, prefix, start_num, end_num }) });
      ctx.toast("Bill series created", "success");
      await load();
    } catch (err) { ctx.toast(err.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function deleteSeries(id) {
    if (!confirm("Soft-delete this bill series?")) return;
    try {
      await ctx.api(`/bill-series/${id}`, { method: "DELETE" });
      ctx.toast("Deleted", "success");
      await load();
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function openSeries(id) {
    ctx.showLoading?.();
    try {
      currentSeries = await ctx.api(`/bill-series/${id}`, {}, 0);
      renderSeriesDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderSeriesDetail() {
    const el = document.getElementById("bill-series-root");
    const s = currentSeries;
    if (!el || !s) return;
    const bills = s.bills || [];
    el.innerHTML = `
      <button type="button" class="btn btn-secondary back-btn" onclick="BillSeries.load()">← Back to list</button>
      <div style="margin:16px 0 20px;">
        <h2 style="margin:0;font-size:24px;">${ctx.esc(s.name)}</h2>
        <p style="margin:4px 0 0;color:var(--muted);font-size:14px;">Prefix <strong style="font-family:monospace;">${ctx.esc(s.prefix)}</strong> · Range ${s.start_num}–${s.end_num}</p>
      </div>
      <div class="bs-stat-grid">
        <div class="bs-stat"><div class="bs-stat-num">${s.used_count}</div><div class="bs-stat-label">Bills used</div></div>
        <div class="bs-stat"><div class="bs-stat-num">${s.remaining}</div><div class="bs-stat-label">Remaining</div></div>
        <div class="bs-stat"><div class="bs-stat-num">${s.total_capacity}</div><div class="bs-stat-label">Total capacity</div></div>
        <div class="bs-stat"><div class="bs-stat-num" style="font-size:16px;font-family:monospace;">${s.next_bill_number ? ctx.esc(s.next_bill_number) : "—"}</div><div class="bs-stat-label">Next bill #</div></div>
      </div>
      <div class="card table-wrap">
        <h3 style="margin:0 0 12px;padding:16px 16px 0;font-size:16px;">Bills in this series (${bills.length})</h3>
        <table class="data"><thead><tr>
          <th>Bill #</th><th>Customer</th><th>Amount</th><th>Created</th><th>By</th>
        </tr></thead><tbody>
          ${bills.map(b => `<tr class="clickable" onclick="BillSeries.openBill(${b.id})">
            <td><strong style="font-family:monospace;">${ctx.esc(b.bill_number)}</strong></td>
            <td>${ctx.esc(b.customer_name)}</td>
            <td>${fmtPrice(b.grand_total)}</td>
            <td style="font-size:12px;color:var(--muted);">${new Date(b.created_at).toLocaleString()}</td>
            <td style="font-size:12px;">${ctx.esc(b.created_by_name)}</td>
          </tr>`).join("")}
          ${!bills.length ? `<tr><td colspan="5" style="text-align:center;padding:32px;color:var(--muted);">No bills issued from this series yet.</td></tr>` : ""}
        </tbody></table>
      </div>`;
  }

  async function openBill(billId) {
    ctx.showLoading?.();
    try {
      const bill = await ctx.api(`/bill-series/bills/${billId}`, {}, 0);
      renderBillDetail(bill);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderBillDetail(bill) {
    const lines = (bill.lines || []).map(ln => `<tr>
      <td>${ctx.esc(ln.our_product_id)}</td>
      <td>${ln.quantity_shipped}</td>
      <td>${fmtPrice(ln.unit_price)}</td>
      <td>${fmtPrice(ln.line_total)}</td>
      <td>${ctx.esc(ln.status)}</td>
    </tr>`).join("");
    const meta = `
      <div><span class="ledger-meta-label">Customer</span> ${ctx.esc(bill.customer_name)}</div>
      <div><span class="ledger-meta-label">Series</span> ${ctx.esc(bill.bill_series_name || "—")}</div>
      <div><span class="ledger-meta-label">Grand total</span> ${fmtPrice(bill.grand_total)}</div>
      <div><span class="ledger-meta-label">Created</span> ${new Date(bill.created_at).toLocaleString()} by ${ctx.esc(bill.created_by_name)}</div>
      ${bill.placement_id ? `<div><span class="ledger-meta-label">Order placement</span> #${bill.placement_id}${bill.placement_at ? ` · ${new Date(bill.placement_at).toLocaleString()}` : ""}</div>` : ""}
      ${bill.narration ? `<div><span class="ledger-meta-label">Narration</span> ${ctx.esc(bill.narration)}</div>` : ""}`;
    const table = `<table class="data"><thead><tr><th>Product</th><th>Qty</th><th>Rate</th><th>Total</th><th>Status</th></tr></thead><tbody>${lines}</tbody></table>`;
    const docBtns = bill.document_url
      ? `<div style="display:flex;gap:8px;margin-top:12px;">
          <button class="btn btn-secondary btn-sm" onclick="BillSeries.openBillDoc(${bill.id}, true)">Print</button>
          <button class="btn btn-secondary btn-sm" onclick="BillSeries.openBillDoc(${bill.id}, false)">Download PDF</button>
          <button class="btn btn-primary btn-sm" onclick="BillSeries.viewBillDoc('${bill.bill_number.replace(/'/g, "\\'")}', '${bill.document_url}')">View PDF</button>
        </div>`
      : `<p style="font-size:13px;color:var(--muted);margin-top:12px;">PDF not generated yet.</p>`;
    const orderBtn = bill.placement_id
      ? `<button class="btn btn-primary" onclick="BillSeries.viewOrder(${bill.customer_id})">View order detail</button>`
      : "";
    ctx.openDetail?.(`Bill ${bill.bill_number}`, ctx.ledgerDetailCard("Bill details", meta, table, docBtns),
      `${ctx.detailFooterChild?.() || ""}${orderBtn}
       <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "md", { push: true });
  }

  async function openBillDoc(billId, print) {
    try {
      const doc = await ctx.api(`/customer-orders/bills/${billId}/document`, {}, 0);
      const w = window.open(doc.document_url, "_blank");
      if (print && w) w.addEventListener("load", () => w.print());
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  function viewBillDoc(name, url) {
    if (!url) return ctx.toast("No document", "error");
    ctx.openDetail?.(name,
      `<iframe src="${ctx.esc(url)}" style="width:100%;height:70vh;border:none;border-radius:8px;"></iframe>`,
      `${ctx.detailFooterChild?.() || ""}<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "lg", { push: true });
  }

  function viewOrder(customerId) {
    App.closeDetail();
    App.setOrdersType("customer");
    App.showView("orders");
    CustomerOrders.openDetail(customerId, "billed");
  }

  return { init, load, create, deleteSeries, openSeries, openBill, openBillDoc, viewBillDoc, viewOrder };
})();
