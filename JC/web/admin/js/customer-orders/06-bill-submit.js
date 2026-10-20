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
    processBusy = true;
    const saveBtn = document.querySelector("#co-wizard-footer .btn-primary");
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = "Saving…"; }
    ctx.showLoading?.();
    try {
      let res;
      const body = buildProcessBody();
      if (editBillId) {
        res = await ctx.api(`/customer-orders/bills/${editBillId}`, {
          method: "PUT",
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
      closeProcessWizard();
      if (edited) {
        ctx.toast(`Bill ${res.bill_number} updated`, "success");
        ctx.invalidateCache?.("/freight-agents");
        if (isDispatchBucket()) await loadDispatch();
        if (detailCustomerId) await openDetail(detailCustomerId, "billed");
      } else {
        ctx.toast(`Bill ${res.bill_number} — ${fmtPrice(res.grand_total)}`, "success");
      }
      entryItems = null;
      loadList();
    } catch (e) {
      processBusy = false;
      ctx.toast(e.message, "error");
      renderProcessWizard();
    } finally {
      processBusy = false;
      ctx.hideLoading?.();
    }
  }

  async function openBillDoc(billId, print) {
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

