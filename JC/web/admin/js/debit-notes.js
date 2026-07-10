/** Debit notes — create / edit modal with plain-language direction choices */
const DebitNotes = (() => {
  let ctx = {};
  let state = {
    vendorId: null,
    receiptId: null,
    lines: [],
    editing: null,
    onDone: null,
    noteType: "item",
    itemDirection: "short", // short = billed more / received less → pay less
    valueDirection: "over", // over = bill too high → pay less
  };

  function init(context) { ctx = context; }

  function fmtPrice(val) {
    const n = Number(val);
    if (Number.isNaN(n)) return "—";
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function directionFromNote(note) {
    if (!note) return { itemDirection: "short", valueDirection: "over" };
    if (note.note_type === "item") {
      const d = note.direction || (Number(note.quantity) < 0 ? "extra" : "short");
      return { itemDirection: d === "extra" ? "extra" : "short", valueDirection: "over" };
    }
    const d = note.direction || (Number(note.amount) < 0 ? "over" : "under");
    return { itemDirection: "short", valueDirection: d === "under" ? "under" : "over" };
  }

  function openCreate({ vendorId, receiptId, receivingLines, onDone }) {
    state = {
      vendorId,
      receiptId,
      lines: receivingLines || [],
      editing: null,
      onDone: onDone || null,
      noteType: "item",
      itemDirection: "short",
      valueDirection: "over",
    };
    document.getElementById("dn-modal-title").textContent = "Add Debit Note";
    renderForm();
    document.getElementById("debit-note-modal").classList.remove("hidden");
  }

  async function openEdit(noteId, onDone) {
    ctx.showLoading?.();
    try {
      const note = await ctx.api(`/debit-notes/${noteId}`, {}, 0);
      const lines = await ctx.api(`/stock/receipts/${note.receipt_id}/lines`, {}, 0).catch(() => []);
      const dirs = directionFromNote(note);
      state = {
        vendorId: note.vendor_id,
        receiptId: note.receipt_id,
        lines,
        editing: note,
        onDone: onDone || null,
        noteType: note.note_type || "item",
        itemDirection: dirs.itemDirection,
        valueDirection: dirs.valueDirection,
      };
      document.getElementById("dn-modal-title").textContent = "Edit Debit Note";
      renderForm(note);
      document.getElementById("debit-note-modal").classList.remove("hidden");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function close() {
    document.getElementById("debit-note-modal")?.classList.add("hidden");
    state = {
      vendorId: null, receiptId: null, lines: [], editing: null, onDone: null,
      noteType: "item", itemDirection: "short", valueDirection: "over",
    };
  }

  function setType(type) {
    state.noteType = type === "value" ? "value" : "item";
    renderForm(state.editing);
  }

  function setItemDirection(dir) {
    state.itemDirection = dir === "extra" ? "extra" : "short";
    updatePreview();
  }

  function setValueDirection(dir) {
    state.valueDirection = dir === "under" ? "under" : "over";
    updatePreview();
  }

  function absQty(note) {
    if (!note || note.quantity == null) return "";
    return Math.abs(Number(note.quantity) || 0) || "";
  }

  function absAmount(note) {
    if (!note || note.amount == null || note.amount === "") return "";
    return Math.abs(Number(note.amount) || 0) || "";
  }

  function renderForm(note) {
    const body = document.getElementById("debit-note-body");
    const footer = document.getElementById("debit-note-footer");
    if (!body) return;
    const type = state.noteType || "item";
    const productOpts = state.lines.map(l => {
      const recv = l.quantity_received != null ? Number(l.quantity_received) : null;
      const billed = l.quantity_billed != null ? Number(l.quantity_billed) : null;
      let hint = fmtPrice(l.buying_price);
      if (recv != null || billed != null) {
        hint += ` · recv ${recv ?? 0} / bill ${billed ?? 0}`;
      }
      return `<option value="${l.catalog_product_id}" ${note?.catalog_product_id === l.catalog_product_id ? "selected" : ""}>${ctx.esc(l.our_product_id)} · ${hint}</option>`;
    }).join("");

    body.innerHTML = `
      <div class="dn-form">
        <p class="dn-lead">Adjust what you owe the vendor when the bill and goods don’t match.</p>

        <div class="dn-type-seg" role="group" aria-label="Debit note type">
          <button type="button" class="dn-type-btn ${type === "item" ? "active" : ""}" onclick="DebitNotes.setType('item')">Quantity</button>
          <button type="button" class="dn-type-btn ${type === "value" ? "active" : ""}" onclick="DebitNotes.setType('value')">Amount</button>
        </div>

        ${type === "item" ? `
          <label class="label">Product</label>
          <select class="input" id="dn-product" onchange="DebitNotes.updatePreview()">
            <option value="">— Select product —</option>${productOpts}
          </select>

          <p class="dn-section-label">What happened?</p>
          <div class="dn-choice-list">
            <label class="dn-choice ${state.itemDirection === "short" ? "selected" : ""}">
              <input type="radio" name="dn-item-dir" value="short" ${state.itemDirection === "short" ? "checked" : ""} onchange="DebitNotes.setItemDirection('short')" />
              <span class="dn-choice-body">
                <strong>Short delivery</strong>
                <span>Received less than billed — you pay less</span>
              </span>
            </label>
            <label class="dn-choice ${state.itemDirection === "extra" ? "selected" : ""}">
              <input type="radio" name="dn-item-dir" value="extra" ${state.itemDirection === "extra" ? "checked" : ""} onchange="DebitNotes.setItemDirection('extra')" />
              <span class="dn-choice-body">
                <strong>Extra goods</strong>
                <span>Received more than billed — you pay more</span>
              </span>
            </label>
          </div>

          <label class="label">Quantity difference</label>
          <input type="number" min="1" step="1" class="input" id="dn-qty" value="${absQty(note) || 1}" oninput="DebitNotes.updatePreview()" placeholder="e.g. 5" />
          <div id="dn-preview" class="dn-preview"></div>
        ` : `
          <p class="dn-section-label">What happened on the bill?</p>
          <div class="dn-choice-list">
            <label class="dn-choice ${state.valueDirection === "over" ? "selected" : ""}">
              <input type="radio" name="dn-value-dir" value="over" ${state.valueDirection === "over" ? "checked" : ""} onchange="DebitNotes.setValueDirection('over')" />
              <span class="dn-choice-body">
                <strong>Bill overcharged</strong>
                <span>Vendor billed too much — you pay less</span>
              </span>
            </label>
            <label class="dn-choice ${state.valueDirection === "under" ? "selected" : ""}">
              <input type="radio" name="dn-value-dir" value="under" ${state.valueDirection === "under" ? "checked" : ""} onchange="DebitNotes.setValueDirection('under')" />
              <span class="dn-choice-body">
                <strong>Bill undercharged</strong>
                <span>Vendor billed too little — you pay more</span>
              </span>
            </label>
          </div>

          <label class="label">Amount (₹)</label>
          <input type="number" min="0.01" step="0.01" class="input" id="dn-value" value="${absAmount(note)}" oninput="DebitNotes.updatePreview()" placeholder="e.g. 250" />
          <div id="dn-preview" class="dn-preview"></div>
        `}

        <label class="label" style="margin-top:14px;">Note (optional)</label>
        <input class="input" id="dn-notes" value="${ctx.esc(note?.notes || "")}" placeholder="Short reason for your records" />
      </div>`;

    footer.innerHTML = state.editing
      ? `<button class="btn btn-secondary" onclick="DebitNotes.close()">Cancel</button>
         <button class="btn btn-primary" onclick="DebitNotes.saveEdit()">Save</button>`
      : `<button class="btn btn-secondary" onclick="DebitNotes.close()">Cancel</button>
         <button class="btn btn-primary" onclick="DebitNotes.review()">Add Note</button>`;

    updatePreview();
  }

  function calcEffect() {
    const type = state.noteType || "item";
    if (type === "item") {
      const catId = parseInt(document.getElementById("dn-product")?.value, 10);
      const qtyAbs = Math.abs(parseInt(document.getElementById("dn-qty")?.value || "0", 10) || 0);
      const line = state.lines.find(l => l.catalog_product_id === catId);
      if (!line || !qtyAbs) return null;
      const price = Number(line.buying_price) || 0;
      const signedQty = state.itemDirection === "extra" ? -qtyAbs : qtyAbs;
      const amt = price * signedQty;
      const effect = -amt; // item: positive qty → pay less
      return {
        type, line, qtyAbs, signedQty, price, amt, effect,
        label: state.itemDirection === "short" ? "Short delivery" : "Extra goods",
      };
    }
    const valAbs = Math.abs(parseFloat(document.getElementById("dn-value")?.value || "0") || 0);
    if (!valAbs) return null;
    const signedAmt = state.valueDirection === "over" ? -valAbs : valAbs;
    const effect = signedAmt; // value: negative → pay less
    return {
      type, valAbs, signedAmt, effect,
      label: state.valueDirection === "over" ? "Bill overcharged" : "Bill undercharged",
    };
  }

  function updatePreview() {
    const el = document.getElementById("dn-preview");
    if (!el) return;
    const info = calcEffect();
    if (!info) {
      el.className = "dn-preview";
      el.textContent = state.noteType === "item" ? "Select a product and enter quantity." : "Enter the amount to adjust.";
      return;
    }
    const payLess = info.effect < 0;
    el.className = `dn-preview ${payLess ? "is-less" : "is-more"}`;
    if (info.type === "item") {
      el.innerHTML = `<strong>${info.label}</strong> · ${info.qtyAbs} × ${fmtPrice(info.price)}
        <span>AP ${payLess ? "reduces" : "increases"} by <b>${fmtPrice(Math.abs(info.effect))}</b> — you ${payLess ? "pay less" : "pay more"}</span>`;
    } else {
      el.innerHTML = `<strong>${info.label}</strong>
        <span>AP ${payLess ? "reduces" : "increases"} by <b>${fmtPrice(Math.abs(info.effect))}</b> — you ${payLess ? "pay less" : "pay more"}</span>`;
    }
  }

  async function review() {
    const payload = buildPayload();
    if (!payload) return;
    const info = calcEffect();
    if (!info) return;
    const summary = info.type === "item"
      ? `${info.label}: ${info.line.our_product_id} × ${info.qtyAbs}`
      : `${info.label}: ${fmtPrice(info.valAbs)}`;
    if (!confirm(`${summary}\nYou ${info.effect < 0 ? "pay less" : "pay more"} by ${fmtPrice(Math.abs(info.effect))}.\n\nAdd this debit note?`)) return;
    // Wizard queue (no receipt yet): hand payload to parent
    if (state.onDone && !state.receiptId) {
      state.onDone(payload);
      close();
      return;
    }
    // Existing receipt: persist then notify parent
    await submitNew();
  }

  function buildPayload() {
    const notes = document.getElementById("dn-notes")?.value?.trim() || null;
    const info = calcEffect();
    if (!info) {
      ctx.toast(state.noteType === "item" ? "Select product and quantity" : "Enter amount", "error");
      return null;
    }
    if (info.type === "item") {
      return {
        note_type: "item",
        direction: state.itemDirection,
        catalog_product_id: info.line.catalog_product_id,
        quantity: info.signedQty,
        notes,
        _direction: state.itemDirection,
        _direction_label: info.label,
      };
    }
    return {
      note_type: "value",
      direction: state.valueDirection,
      amount: info.signedAmt,
      notes,
      _direction: state.valueDirection,
      _direction_label: info.label,
    };
  }

  async function submitNew() {
    const payload = buildPayload();
    if (!payload) return;
    if (!state.receiptId) {
      ctx.toast("No receipt linked for this debit note", "error");
      return;
    }
    const done = state.onDone;
    ctx.showLoading?.();
    try {
      await ctx.api(`/debit-notes?vendor_id=${state.vendorId}&receipt_id=${state.receiptId}`, {
        method: "POST",
        body: JSON.stringify({
          note_type: payload.note_type,
          direction: payload.direction,
          catalog_product_id: payload.catalog_product_id,
          quantity: payload.quantity,
          amount: payload.amount,
          notes: payload.notes,
        }),
      });
      ctx.invalidateCache?.("/debit-notes");
      ctx.invalidateCache?.("/accounts-payable");
      ctx.toast("Debit note created", "success");
      close();
      if (done) await done(null);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function saveEdit() {
    if (!state.editing) return;
    const payload = buildPayload();
    if (!payload) return;
    const body = {
      notes: payload.notes,
      note_type: payload.note_type,
      direction: payload.direction,
    };
    if (payload.note_type === "item") {
      body.catalog_product_id = payload.catalog_product_id;
      body.quantity = payload.quantity;
    } else {
      body.amount = payload.amount;
    }
    ctx.showLoading?.();
    try {
      await ctx.api(`/debit-notes/${state.editing.id}`, { method: "PATCH", body: JSON.stringify(body) });
      ctx.invalidateCache?.("/debit-notes");
      ctx.invalidateCache?.("/accounts-payable");
      ctx.toast("Debit note updated", "success");
      close();
      if (state.onDone) state.onDone(null);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  let listCtx = null;

  async function openForReceipt({ vendorId, receiptId, receivingLines, onDone }) {
    if (!receiptId) return openCreate({ vendorId, receiptId, receivingLines, onDone });
    listCtx = { vendorId, receiptId, receivingLines: receivingLines || [], onDone: onDone || null };
    ctx.showLoading?.();
    try {
      const notes = await ctx.api(`/debit-notes?receipt_id=${receiptId}`, {}, 0);
      if (!listCtx.receivingLines.length) {
        listCtx.receivingLines = await ctx.api(`/stock/receipts/${receiptId}/lines`, {}, 0).catch(() => []);
      }
      document.getElementById("dn-modal-title").textContent = "Debit Notes";
      const body = document.getElementById("debit-note-body");
      const footer = document.getElementById("debit-note-footer");
      const rows = (notes || []).map(n => {
        const effect = n.payable_effect != null ? n.payable_effect : (n.note_type === "item" ? -Number(n.amount) : Number(n.amount));
        const payLess = Number(effect) < 0;
        const title = n.note_type === "item"
          ? `${ctx.esc(n.our_product_id || "Item")} × ${n.quantity}${n.direction ? ` (${ctx.esc(n.direction)})` : ""}`
          : `Value ${ctx.esc(n.direction || "adj.")}`;
        return `<div class="dn-list-card">
          <div class="dn-list-main">
            <strong>${title}</strong>
            <span class="dn-effect-pill ${payLess ? "is-less" : "is-more"}">${payLess ? "Pay less" : "Pay more"} ${fmtPrice(Math.abs(effect))}</span>
          </div>
          ${n.notes ? `<div class="dn-row-note">${ctx.esc(n.notes)}</div>` : ""}
          <div class="vo-muted" style="margin-top:4px;">${new Date(n.created_at).toLocaleString()}</div>
        </div>`;
      }).join("");
      body.innerHTML = `
        <p class="dn-lead">Adjustments on this bill. Add another if needed.</p>
        ${rows || `<div class="vo-wiz-empty"><p>No debit notes on this bill yet.</p></div>`}`;
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="DebitNotes.close()">Close</button>
        <button class="btn btn-primary" onclick="DebitNotes.addFromList()">+ Add Debit Note</button>`;
      document.getElementById("debit-note-modal").classList.remove("hidden");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function addFromList() {
    if (!listCtx) return;
    const { vendorId, receiptId, receivingLines, onDone } = listCtx;
    openCreate({
      vendorId,
      receiptId,
      receivingLines,
      onDone: async () => {
        if (onDone) await onDone();
        await openForReceipt({ vendorId, receiptId, receivingLines, onDone });
      },
    });
  }

  return {
    init, openCreate, openEdit, openForReceipt, addFromList, close, setType, setItemDirection, setValueDirection,
    updatePreview, review, saveEdit, buildPayload,
  };
})();
