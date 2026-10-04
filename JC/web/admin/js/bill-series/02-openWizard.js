  function openWizard() {
    if (!canWrite()) return ctx.toast("Admin only", "error");
    const modal = document.getElementById("modal");
    if (!modal) return;
    document.getElementById("modal-title").textContent = "New bill series";
    document.getElementById("modal-body").innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
        <div style="grid-column:1/-1;"><label class="label">Name *</label><input id="bs-name" class="input" placeholder="e.g. FY2026" /></div>
        <div><label class="label">Prefix *</label><input id="bs-prefix" class="input" placeholder="e.g. A" maxlength="10" /></div>
        <div><label class="label">Start #</label><input id="bs-start" class="input" type="number" min="1" value="1" /></div>
        <div><label class="label">End #</label><input id="bs-end" class="input" type="number" min="1" value="500" /></div>
      </div>`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="BillSeries.create()">Create series</button>`;
    modal.classList.remove("hidden");
  }

  async function create(e) {
    if (e?.preventDefault) e.preventDefault();
    const name = document.getElementById("bs-name")?.value?.trim();
    const prefix = document.getElementById("bs-prefix")?.value?.trim();
    const start_num = Number(document.getElementById("bs-start")?.value || 1);
    const end_num = Number(document.getElementById("bs-end")?.value || 0);
    if (!name || !prefix) return ctx.toast("Name and prefix required", "error");
    ctx.showLoading?.();
    try {
      await ctx.api("/bill-series", { method: "POST", body: JSON.stringify({ name, prefix, start_num, end_num }) });
      ctx.toast("Bill series created", "success");
      App.closeModal?.();
      await load();
    } catch (err) { ctx.toast(err.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function deleteSeries(id) {
    if (!canWrite()) return ctx.toast("Admin only", "error");
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
      setDetailBack();
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
      <div style="margin:0 0 20px;">
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
            <td style="font-size:12px;color:var(--muted);">${ctx.fmtDate(b.created_at)}${b.bill_date ? ` · Bill ${ctx.fmtDay(b.bill_date)}` : ""}</td>
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
      <div><span class="ledger-meta-label">Entered</span> ${ctx.fmtDate(bill.created_at)} by ${ctx.esc(bill.created_by_name)}</div>
      ${bill.bill_date ? `<div><span class="ledger-meta-label">Bill date</span> ${ctx.fmtDay(bill.bill_date)}</div>` : ""}
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
    ctx.showLoading?.();
    try {
      const doc = await ctx.api(`/customer-orders/bills/${billId}/document`, {}, 0);
      const w = window.open(doc.document_url, "_blank");
      if (print && w) w.addEventListener("load", () => w.print());
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

