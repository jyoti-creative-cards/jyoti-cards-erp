  async function submitProcess() {
    if (processBusy || !detailCustomerId) return;
    processBusy = true;
    renderProcessWizard();
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
      const cid = detailCustomerId;
      if (edited) {
        ctx.toast(`Bill ${res.bill_number} updated — order + dispatch synced`, "success");
        ctx.invalidateCache?.("/freight-agents");
        if (isDispatchBucket()) await loadDispatch();
      } else {
        const hasFreight = transportMode === "bus" || !!(res.freight_agent_id || freightAgentId);
        const nextHint = transportMode === "bus" || hasFreight
          ? "Next: Dispatch (agent pick) or Collect."
          : "Next: Dispatch or Collect — then Close.";
        ctx.openDetail?.(`Bill ${res.bill_number}`, `
            <p style="margin:0 0 16px;color:var(--muted);">Bill created — ${fmtPrice(res.grand_total)}. AR posted. ${nextHint}</p>
            <div style="display:flex;flex-direction:column;gap:8px;">
              <button class="btn btn-primary" onclick="App.closeDetail();CustomerOrders.goToDispatch()">Dispatch</button>
              ${(ctx.isAdmin?.() || ctx.canWrite?.("ar") || ctx.canWrite?.("finance")) ? `<button class="btn btn-secondary" onclick="App.closeDetail();CustomerOrders.goCollectPayment(${cid})">Collect payment</button>` : ""}
              <button class="btn btn-secondary" onclick="CustomerOrders.openBillDoc(${res.bill_id}, false)">Download PDF</button>
              <button class="btn btn-secondary" onclick="CustomerOrders.openBillDoc(${res.bill_id}, true)">Print</button>
              <button class="btn btn-secondary" onclick="CustomerOrders.shareBillWhatsApp(${res.bill_id})">WhatsApp</button>
              <button class="btn btn-secondary" onclick="App.closeDetail();CustomerOrders.openCloseBatch(${cid})">Close order</button>
            </div>`,
          `<button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail()">Done</button>`, "sm");
        ctx.toast(`Bill ${res.bill_number} — ${fmtPrice(res.grand_total)}`, "success");
      }
      loadList();
      if (edited) await openDetail(detailCustomerId, "billed");
    } catch (e) {
      ctx.toast(e.message, "error");
      renderProcessWizard();
    } finally {
      processBusy = false;
      ctx.hideLoading?.();
    }
  }

  async function openBillDoc(billId, print) {
    try {
      await DocShare.openPdf(`/share/bills/${billId}/pdf`, {
        print: !!print,
        filename: `bill_${billId}.pdf`,
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

  function showCreateMenuFromCustomer(customerId) {
    openOfflineWizard(customerId);
  }

  function showCreateMenu() {
    openOfflineWizard(detailCustomerId || null);
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

