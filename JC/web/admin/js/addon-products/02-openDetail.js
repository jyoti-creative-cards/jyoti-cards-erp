  async function openDetail(id) {
    const a = await ctx.api(`/addons/${id}`);
    const heroImg = a.image_urls && a.image_urls[0]
      ? `<img src="${ctx.esc(a.image_urls[0])}" alt="" style="width:72px;height:72px;object-fit:cover;border-radius:12px;border:1px solid var(--border);" />`
      : `<div style="width:72px;height:72px;border-radius:12px;background:#e2e8f0;display:flex;align-items:center;justify-content:center;font-weight:700;color:var(--muted);">${ctx.esc((a.our_product_id || "").slice(0, 3))}</div>`;

    const changeHist = ctx.changeHistoryTable
      ? ctx.changeHistoryTable(a.change_history)
      : '<p style="color:var(--muted);font-size:14px;margin:0;">No field changes recorded yet.</p>';

    const moveRows = (a.stock_movements || []).length
      ? `<table class="data"><thead><tr><th>When</th><th>Type</th><th>Δ</th><th>Balance</th><th>Note</th></tr></thead><tbody>
          ${a.stock_movements.map(m => `<tr>
            <td style="font-size:13px;color:var(--muted);">${ctx.fmtDate(m.created_at)}</td>
            <td>${ctx.esc((m.entry_type || "").replace(/_/g, " "))}</td>
            <td><strong style="color:${m.quantity_delta < 0 ? "var(--danger, #dc2626)" : "var(--brand-green, #16a34a)"};">${m.quantity_delta > 0 ? "+" : ""}${m.quantity_delta}</strong></td>
            <td>${m.balance_after}</td>
            <td style="font-size:13px;color:var(--muted);">${ctx.esc(m.notes || m.party || "")}</td>
          </tr>`).join("")}
        </tbody></table>`
      : '<p style="color:var(--muted);font-size:14px;margin:0;">No stock movements recorded yet.</p>';

    ctx.openDetail("Addon Product", `
      <div class="profile-hero" style="margin:-24px -24px 24px;border-radius:0;">
        <div style="display:flex;align-items:center;gap:16px;">
          ${heroImg}
          <div>
            <h2 style="margin:0 0 4px;">${ctx.esc(a.our_product_id)}</h2>
            <p style="margin:0;">${ctx.esc(a.description || "")}</p>
            <div class="profile-meta">
              ${stockBadge(a)}
            </div>
          </div>
        </div>
      </div>
      <div class="review-grid" style="margin-bottom:24px;">
        ${ctx.reviewRow("Created", ctx.fmtDate(a.created_at))}
        ${ctx.reviewRow("Last Updated", ctx.fmtDate(a.updated_at))}
      </div>
      <div class="detail-section">
        <h4>Stock Movements</h4>
        ${moveRows}
      </div>
      ${changeHist}`,
      `${ctx.canWrite?.("addons") ? `<button class="btn btn-danger btn-sm" onclick="AddonProducts.deleteAddon(${a.id})">Delete</button>
       <button class="btn btn-secondary btn-sm" onclick="AddonProducts.openAdjustStock(${a.id})">Adjust Stock</button>
       <button class="btn btn-secondary btn-sm" onclick="AddonProducts.openReceiveStock(${a.id})">Receive Stock</button>
       <button class="btn btn-secondary btn-sm" onclick="AddonProducts.openEdit(${a.id})">Edit</button>` : ""}
       <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "lg"
    );
  }

  function openReceiveStock(id) {
    // Single modal with all 3 fields — was a 3-prompt() chain (qty, cost, note).
    document.getElementById("modal-title").textContent = "Receive addon stock";
    document.getElementById("modal-body").innerHTML = `
      <label class="label">Quantity received</label>
      <input class="input" id="addon-rs-qty" type="number" step="1" min="1" style="width:100%;margin-bottom:10px;" />
      <label class="label">Note (optional)</label>
      <textarea class="input" id="addon-rs-note" rows="2" style="width:100%;"></textarea>`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" id="addon-rs-ok">Save</button>`;
    document.getElementById("addon-rs-ok").onclick = async () => {
      const q = parseInt(document.getElementById("addon-rs-qty").value, 10);
      if (!Number.isFinite(q) || q <= 0) return ctx.toast("Enter a valid quantity", "error");
      const note = (document.getElementById("addon-rs-note").value || "").trim() || null;
      try {
        // Close only after a successful save — this used to close first, so a
        // failure (e.g. no finance.write when a cost is entered) silently dropped
        // every typed field with nothing left on screen to retry from.
        await ctx.api(`/addons/${id}/receive-stock`, { method: "POST", body: JSON.stringify({ quantity: q, note }) });
        App.closeModal();
        App.closeDetail();
        await refreshAfterMutation();
        ctx.toast("Stock received", "success");
        openDetail(id);
      } catch (e) {
        ctx.toast(e.message, "error");
      }
    };
    document.getElementById("modal").classList.remove("hidden");
  }

  function openAdjustStock(id) {
    // Single modal with both fields — was a 2-prompt() chain (delta, then reason).
    document.getElementById("modal-title").textContent = "Adjust addon stock";
    document.getElementById("modal-body").innerHTML = `
      <label class="label">Adjustment (e.g. -3 or 10)</label>
      <input class="input" id="addon-as-delta" type="number" step="1" style="width:100%;margin-bottom:10px;" />
      <label class="label">Reason (required)</label>
      <textarea class="input" id="addon-as-reason" rows="2" style="width:100%;"></textarea>`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" id="addon-as-ok">Save</button>`;
    document.getElementById("addon-as-ok").onclick = async () => {
      const d = parseInt(document.getElementById("addon-as-delta").value, 10);
      if (!Number.isFinite(d) || d === 0) return ctx.toast("Enter a non-zero number", "error");
      const reason = (document.getElementById("addon-as-reason").value || "").trim();
      if (!reason) return ctx.toast("Reason required", "error");
      try {
        await ctx.api(`/addons/${id}/adjust-stock`, { method: "POST", body: JSON.stringify({ delta: d, reason }) });
        App.closeModal();
        App.closeDetail();
        await refreshAfterMutation();
        ctx.toast("Stock adjusted", "success");
        openDetail(id);
      } catch (e) {
        ctx.toast(e.message, "error");
      }
    };
    document.getElementById("modal").classList.remove("hidden");
  }

  async function openWizard() {
    wizardStep = 1;
    wizardForm = { image_keys: [], quantity: "" };
    document.getElementById("addon-wizard").classList.remove("hidden");
    renderWizard();
  }

  function closeWizard() {
    document.getElementById("addon-wizard").classList.add("hidden");
    wizardForm = {};
    wizardStep = 1;
  }

