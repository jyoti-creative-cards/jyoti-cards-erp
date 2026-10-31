  async function submitProcess() {
    if (processBusy || !detailCustomerId) return;
    if (!processLines.some(l => Number(l.quantity_to_ship) > 0)) return ctx.toast("Enter a quantity", "error");
    if (!transportMode) return ctx.toast("Select transport", "error");
    if (transportMode === "bus") {
      if (!freightAgentId) return ctx.toast("Select the freight agent", "error");
      if (String(freightCharges || "").trim() === "") return ctx.toast("Enter freight", "error");
    }
    if (transportMode === "transport" && String(freightCharges || "").trim() === "") {
      return ctx.toast("Enter transport charges", "error");
    }
    if (!editBillId && !billSeriesId) return ctx.toast("Select a bill series", "error");
    if (editBillId) {
      const allowed = await askEditCancelKey();
      if (!allowed) return;
    } else {
      window.__jcCancelKey = "";
    }
    processBusy = true;
    showBillReady({ bill_number: "Saving…", grand_total: "", bill_id: 0, pending: true });
    try {
      let res;
      const body = buildProcessBody();
      if (editBillId) {
        res = await ctx.api(`/customer-orders/bills/${editBillId}`, {
          method: "PUT",
          headers: { "X-Cancel-Key": window.__jcCancelKey || "" },
          body: JSON.stringify(body),
        });
      } else {
        res = await ctx.api(`/customer-orders/customer/${detailCustomerId}/process`, {
          method: "POST",
          body: JSON.stringify(body),
        });
      }
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/accounts-receivable");
      ctx.invalidateCache?.("/stock");
      const edited = !!editBillId;
      if (edited) ctx.invalidateCache?.("/freight-agents");
      showBillReady(res);
      ctx.toast(`Bill ${res.bill_number} — ${fmtPrice(res.grand_total)}`, "success");
      loadList(true);
    } catch (e) {
      processBusy = false;
      const matches = e.status === 409 && e.detail && e.detail.matches;
      if (matches) {
        showBillDuplicate(e.detail);
        return;
      }
      billConfirmDuplicate = false;
      ctx.toast(e.message, "error");
      renderProcessWizard();
    } finally {
      processBusy = false;
    }
  }

  function showBillDuplicate(detail) {
    const body = document.getElementById("co-wizard-body");
    const footer = document.getElementById("co-wizard-footer");
    const rows = (detail.matches || []).map((m) => {
      const bits = [];
      if (m.same_items && m.same_items.length) bits.push(`same item ${m.same_items.join(", ")}`);
      if (m.same_amount) bits.push(`same amount ₹${m.total}`);
      return `<li>${ctx.esc(m.bill_number || "Bill")}: ${ctx.esc(bits.join(" · "))}</li>`;
    }).join("");
    if (body) {
      body.innerHTML = `<div style="border:2px solid #b45309;background:#fffbeb;border-radius:12px;padding:16px;">
        <strong style="font-size:18px;">This could be a duplicate entry.</strong>
        <p style="margin:8px 0;">Same date, same party. The following are the same:</p>
        <ul style="margin:0 0 8px 18px;">${rows}</ul>
        <p style="margin:0;">Do you want to proceed?</p>
      </div>`;
    }
    if (footer) {
      footer.innerHTML = `
        <button type="button" class="btn btn-secondary" onclick="CustomerOrders.backFromBillDuplicate()">Go back</button>
        <button type="button" class="btn btn-primary" onclick="CustomerOrders.proceedBillDuplicate()">Proceed</button>`;
    }
  }

  function backFromBillDuplicate() {
    billConfirmDuplicate = false;
    processBusy = false;
    renderProcessWizard();
  }

  function proceedBillDuplicate() {
    billConfirmDuplicate = true;
    submitProcess();
  }

  function showBillReady(res) {
    const title = document.getElementById("co-wizard-title");
    const body = document.getElementById("co-wizard-body");
    const footer = document.getElementById("co-wizard-footer");
    const steps = document.getElementById("co-wizard-steps");
    const totals = document.getElementById("co-wizard-totals");
    if (steps) steps.innerHTML = "";
    if (totals) totals.innerHTML = "";
    if (title) title.textContent = `Bill ${res.bill_number || ""}`;
    if (body) {
      body.innerHTML = `
        <p style="margin:0 0 8px;font-size:18px;"><strong>${ctx.esc(res.bill_number || "")}</strong>${res.pending ? "" : " saved"}</p>
        <p style="margin:0 0 20px;color:var(--muted);">${res.pending ? "The bill is being saved. Print and download will be ready in a moment." : fmtPrice(res.grand_total)}</p>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button type="button" class="btn btn-primary" ${res.pending ? "disabled" : ""} onclick="CustomerOrders.openBillDoc(${Number(res.bill_id) || 0}, true)">Print</button>
          <button type="button" class="btn btn-secondary" ${res.pending ? "disabled" : ""} onclick="CustomerOrders.openBillDoc(${Number(res.bill_id) || 0}, false)">Download</button>
        </div>
        <p style="margin:12px 0 0;font-size:13px;color:var(--muted);">Print is the original and the duplicate. Download is the original only.</p>`;
    }
    if (footer) {
      const backLedger = window.__jcLedgerReturn
        ? `<button type="button" class="btn btn-primary" onclick="CustomerOrders.closeProcessWizard({done:true})">Back to ledger</button>`
        : `<button type="button" class="btn btn-secondary" onclick="CustomerOrders.closeProcessWizard()">Done</button>`;
      footer.innerHTML = backLedger;
    }
    document.getElementById("co-wizard")?.classList.remove("hidden");
  }

  function setBillOnAgent(on) {
    billOnAgent = !!on;
  }

  function sayInPrintWindow(win, text) {
    try {
      win.document.open();
      win.document.write(`<!doctype html><title>Invoices</title><body style="font:16px sans-serif;padding:28px;color:#222">${text}</body>`);
      win.document.close();
    } catch (_) {}
  }

  async function printDayDuplicates() {
    const input = document.getElementById("co-print-day");
    const day = input && input.value;
    if (!day) return ctx.toast("Enter the invoice date", "error");
    const win = window.open("", "_blank");
    if (!win) return ctx.toast("Allow pop-ups to print the invoices", "error");
    sayInPrintWindow(win, "Preparing invoices…");
    try {
      const start = await ctx.api(`/share/bills/duplicates/start?day=${encodeURIComponent(day)}`, { method: "POST" });
      const jobId = start.job_id;
      let status = start;
      const started = Date.now();
      while (status.state !== "ready") {
        if (status.state === "error") throw new Error(status.error || "Could not print the invoices");
        if (Date.now() - started > 180000) throw new Error("Preparing the invoices took too long");
        sayInPrintWindow(win, `Preparing invoices… ${status.done || 0} of ${status.total || ""}`);
        await new Promise(resolve => setTimeout(resolve, 800));
        status = await ctx.api(`/share/bills/duplicates/jobs/${jobId}`);
      }
      const headers = { ...(ctx.headers?.() || {}) };
      delete headers["Content-Type"];
      const res = await fetch(`${(ctx.apiBase?.() || "").replace(/\/$/, "")}/share/bills/duplicates/jobs/${jobId}/file`, { headers });
      if (!res.ok) throw new Error("Could not open the invoices");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      win.location = url;
      setTimeout(() => {
        try { win.focus(); win.print(); } catch (_) {}
      }, 900);
      const skipped = (status.failed || []).length;
      if (skipped) ctx.toast(`Printed the invoices. ${skipped} could not be included.`, "error");
    } catch (e) {
      sayInPrintWindow(win, ctx.esc ? ctx.esc(e.message || "Could not print the invoices") : "Could not print the invoices");
      ctx.toast(e.message || "Could not print the invoices", "error");
    }
  }

  async function fetchStoredBill(billId) {
    const headers = { ...(ctx.headers?.() || {}) };
    delete headers["Content-Type"];
    const base = (ctx.apiBase?.() || "").replace(/\/$/, "");
    const res = await fetch(`${base}/customer-orders/bills/${billId}/stored-pdf`, { headers });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error("Could not open the saved bill");
    return res.blob();
  }

  async function printStoredBill(billId) {
    ctx.showLoading?.();
    try {
      const blob = await fetchStoredBill(billId);
      if (!blob) return ctx.toast("Saved bill is not ready yet", "error");
      const url = URL.createObjectURL(blob);
      const w = window.open(url, "_blank");
      if (!w) return ctx.toast("Allow pop-ups to print", "error");
      setTimeout(() => { try { w.focus(); w.print(); } catch (_) {} }, 700);
    } catch (e) {
      ctx.toast(e.message || "Could not print", "error");
    } finally { ctx.hideLoading?.(); }
  }

  async function downloadStoredBill(billId) {
    ctx.showLoading?.();
    try {
      const blob = await fetchStoredBill(billId);
      if (!blob) return ctx.toast("Saved bill is not ready yet", "error");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "bill.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (e) {
      ctx.toast(e.message || "Could not download", "error");
    } finally { ctx.hideLoading?.(); }
  }

  async function openBillDoc(billId, print) {
    ctx.showLoading?.();
    try {
      await DocShare.openPdf(`/share/bills/${billId}/pdf?layout=${print ? "print" : "file"}`, {
        print: !!print,
        filename: "bill.pdf",
      });
    } catch (e) {
      try {
        const d = await ctx.api(`/customer-orders/bills/${billId}/document`, {}, 0);
        if (!d.document_url) throw e;
        if (print) {
          const w = window.open(d.document_url, "_blank");
          if (w) w.addEventListener("load", () => w.print());
        } else {
          window.open(d.document_url, "_blank");
        }
      } catch (e2) { ctx.toast(e2.message || e.message, "error"); }
    } finally {
      ctx.hideLoading?.();
    }
  }

  async function shareBillWhatsApp(billId) {
    ctx.showLoading?.();
    try {
      const res = await DocShare.whatsapp({ kind: "bill", id: billId, caption: `Bill` });
      if (res.ok) ctx.toast("Sent on WhatsApp", "success");
      else {
        ctx.toast(res.hint || "WA failed — opening link", "error");
        if (res.wa_me) window.open(res.wa_me, "_blank");
      }
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function billApiBase() {
    const saved = localStorage.getItem("jc_api");
    if (saved) return saved;
    const host = location.hostname;
    if (host === "127.0.0.1" || host === "localhost") return "http://127.0.0.1:8003/api/v1";
    return `${location.origin}/api/v1`;
  }

  function billAuthHeaders() {
    const h = {};
    if (sessionStorage.getItem("jc_auth_mode") === "admin") h["X-Admin-Key"] = sessionStorage.getItem("jc_admin_key") || "";
    else h.Authorization = `Bearer ${sessionStorage.getItem("jc_staff_token") || ""}`;
    return h;
  }

  function uploadBillQr(billId) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/jpeg,image/png,image/webp";
    input.onchange = async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      ctx.showLoading?.();
      try {
        const res = await fetch(`${billApiBase()}/customer-orders/bills/${billId}/payment-qr`, {
          method: "POST",
          headers: billAuthHeaders(),
          body: fd,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(typeof err.detail === "string" ? err.detail : "QR upload failed");
        }
        ctx.toast("Payment QR updated", "success");
        if (detailCustomerId) openDetail(detailCustomerId, "billed");
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    };
    input.click();
  }

  async function resetBillQr(billId) {
    ctx.showLoading?.();
    try {
      const res = await fetch(`${billApiBase()}/customer-orders/bills/${billId}/payment-qr`, {
        method: "DELETE",
        headers: billAuthHeaders(),
      });
      if (!res.ok) throw new Error("Could not restore the default QR");
      ctx.toast("Default payment QR restored", "success");
      if (detailCustomerId) openDetail(detailCustomerId, "billed");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function showCreateMenuFromCustomer(customerId) {
    openOfflineWizard(customerId);
  }

  function showCreateMenu() {
    openOfflineWizard();
  }

  async function openCloseBatch(customerId) {
    ctx.showLoading?.();
    try {
      const q = customerId != null ? `?customer_id=${customerId}` : "";
      const items = await ctx.api(`/customer-orders/closeable${q}`, {}, 0);
      OrderMenus.openClose({
        title: "Close Billed Lines",
        items: items.map(it => ({
          id: it.id,
          party: it.customer_name,
          label: it.label,
          sublabel: it.sublabel,
          quantity: it.quantity,
          amount: it.amount,
        })),
        ctx,
        onSubmit: async (ids, reason) => {
          const res = await ctx.api("/customer-orders/close-batch", { method: "POST", body: JSON.stringify({ bill_line_ids: ids, reason }) });
          ctx.invalidateCache?.("/customer-orders");
          const closed = res?.closed ?? ids.length;
          ctx.toast(
            closed < ids.length ? `Closed ${closed} of ${ids.length} line(s) — some were skipped` : `Closed ${closed} line(s)`,
            closed < ids.length ? "info" : "success",
          );
          if (detailCustomerId) await openDetail(detailCustomerId, currentBucket);
          else loadList();
        },
      });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

