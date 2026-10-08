  async function loadRouteCollections() {
    const el = document.getElementById("finance-routes-list");
    if (!el) return;
    ctx.showLoading?.();
    try {
      routeCollections = await ctx.api("/finance/route-collections", {}, 0);
      renderRouteListFiltered();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderRouteListFiltered() {
    const el = document.getElementById("finance-routes-list");
    if (!el) return;
    const list = (routeCollections || []).filter(r => matchSearch(r.route_name));
    if (!routeCollections.length) {
      el.innerHTML = OrdersUI.emptyState({
        title: "No routes yet",
        sub: "Add routes under Setup.",
        ctaHtml: `<button class="btn btn-secondary" onclick="App.showView('setup');App.showSetupTab('routes')">Open Setup → Routes</button>`,
      });
      return;
    }
    if (!list.length) {
      el.innerHTML = OrdersUI.emptyState({ title: "No matches", sub: "Clear search." });
      return;
    }
    el.innerHTML = list.map(r => `
      <div class="rc-card" onclick="Finance.openRouteCollection(${r.route_id})">
        <div>
          <strong>${ctx.esc(r.route_name)}</strong>
          <div class="rc-meta">${r.city_count} cities · ${r.customer_count} customers · ${r.customers_with_outstanding} with dues</div>
        </div>
        <div class="rc-amt">${fmtPrice(r.total_outstanding)}</div>
      </div>`).join("");
  }

  async function openRouteCollection(routeId) {
    ctx.showLoading?.();
    try {
      routeDetail = await ctx.api(`/finance/route-collections/${routeId}`, {}, 0);
      routeCustomerDetail = null;
      document.getElementById("finance-hub")?.classList.add("hidden");
      document.getElementById("finance-routes-detail")?.classList.remove("hidden");
      const routesHero = document.getElementById("finance-routes-hero");
      if (routesHero) {
        routesHero.innerHTML = HubUI.pageHero({
          title: routeDetail.route_name,
          sub: `Total outstanding ${fmtPrice(routeDetail.total_outstanding)} · ${(routeDetail.cities || []).map(c => c.name).join(", ") || "No cities"}`,
          actionsHtml: `<button class="btn btn-secondary" onclick="Finance.printRouteCollection()">Print / PDF</button>`,
        });
      }
      renderRouteDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderRouteDetail() {
    const el = document.getElementById("finance-routes-body");
    if (!el || !routeDetail) return;
    if (routeCustomerDetail) {
      const c = routeCustomerDetail;
      const due = Number(c.outstanding) || 0;
      el.innerHTML = `
        <button class="btn btn-secondary btn-sm" style="margin-bottom:14px;" onclick="Finance.backRouteCustomers()">← Customers</button>
        ${HubUI.pageHero({
          title: c.business_name,
          sub: `${c.person_name || ""}${c.person_name ? " · " : ""}${c.city_name || "—"} · ${c.phone || ""} · Due ${fmtPrice(c.outstanding)}`,
          actionsHtml: due > 0 ? `<button class="btn btn-primary" onclick="Finance.openCustomerAr(${c.customer_id}, {settle:true})">Collect</button>` : "",
        })}
        <div class="review-grid" style="margin-bottom:12px;">
          ${ctx.reviewRow("Due", fmtPrice(c.outstanding))}
          ${ctx.reviewRow("Bills", fmtPrice(c.bill_total))}
          ${ctx.reviewRow("Collected", fmtPrice(c.payment_total))}
        </div>
        ${!(c.ledger || []).length
          ? HubUI.emptyState({ title: "No ledger entries", sub: "Bills and payments for this customer show here." })
          : `<div class="card table-wrap">
          <table class="data"><thead><tr>
            <th>When</th><th>Type</th><th>Detail</th><th>Amount</th><th>Balance</th>
          </tr></thead><tbody>
            ${(c.ledger || []).map(e => `<tr>
              <td style="font-size:12px;">${fmtDocDate(e.display_date || e.value_date || e.created_at)}</td>
              <td><span class="badge ${e.entry_type === "bill" ? "badge-amber" : "badge-green"}">${ctx.esc(e.entry_type)}</span></td>
              <td>${ctx.esc(e.description || "—")}</td>
              <td>${fmtPrice(e.signed_amount || e.amount)}</td>
              <td><strong>${fmtPrice(e.running_balance)}</strong></td>
            </tr>`).join("")}
          </tbody></table>
        </div>`}`;
      return;
    }

    const rows = routeDetail.customers || [];
    el.innerHTML = rows.length ? rows.map(c => `
      <div class="rc-card" onclick="Finance.openRouteCustomer(${routeDetail.route_id}, ${c.customer_id})">
        <div>
          <strong>${ctx.esc(c.business_name)}</strong>
          <div class="rc-meta">${ctx.esc(c.city_name || "—")} · ${ctx.esc(c.phone || "")}${c.person_name ? ` · ${ctx.esc(c.person_name)}` : ""}</div>
        </div>
        <div class="rc-amt">${fmtPrice(c.outstanding)}</div>
      </div>`).join("") : OrdersUI.emptyState({ title: "No outstanding on this route", sub: "" });
  }

  function backRouteCustomers() {
    routeCustomerDetail = null;
    renderRouteDetail();
  }

  async function openRouteCustomer(routeId, customerId) {
    ctx.showLoading?.();
    try {
      routeCustomerDetail = await ctx.api(`/finance/route-collections/${routeId}/customer/${customerId}`, {}, 0);
      renderRouteDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function printRouteCollection() {
    if (!routeDetail?.route_id) return;
    ctx.showLoading?.();
    try {
      const key = sessionStorage.getItem("jc_admin_key") || "";
      const saved = localStorage.getItem("jc_api");
      const base = saved || `${location.origin}/api/v1`;
      const res = await fetch(`${base}/finance/route-collections/${routeDetail.route_id}/pdf`, {
        headers: { "X-Admin-Key": key },
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "PDF failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      ctx.toast("PDF ready — print or share", "success");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function todayIstInput() {
    try {
      return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    } catch (_) {
      return new Date().toISOString().slice(0, 10);
    }
  }

  function blankJournalForm() {
    return {
      kind: "transfer",
      journal_date: todayIstInput(),
      narration: "",
      expense_category: "Sample catalogues",
      from_id: null,
      to_id: null,
      from_label: "",
      to_label: "",
      from_q: "",
      to_q: "",
      quantity: "",
      consume_mode: "items",
      album: "",
      copies: "",
      lines: [],
      line_q: "",
      preview: null,
      busy: false,
    };
  }

  function syncJournalFields() {
    const root = document.getElementById("finance-journal-body");
    if (!root || !journalForm) return;
    const date = root.querySelector("input[type='date']");
    if (date?.value) journalForm.journal_date = date.value;
    const note = root.querySelector("input[placeholder='Why this journal']");
    if (note) journalForm.narration = note.value;
  }

  function journalBody() {
    syncJournalFields();
    const f = journalForm;
    const body = {
      journal_date: f.journal_date,
      kind: f.kind,
      narration: (f.narration || "").trim() || null,
    };
    if (f.kind === "transfer") {
      body.from_product_id = f.from_id;
      body.to_product_id = f.to_id;
      body.quantity = Number(f.quantity) || null;
    } else {
      body.expense_category = (f.expense_category || "Sample catalogues").trim();
      if (f.consume_mode === "album") {
        body.album = (f.album || "").trim();
        body.copies = Number(f.copies) || null;
      } else {
        body.lines = (f.lines || []).map(l => ({
          catalog_product_id: l.catalog_product_id,
          quantity: Number(l.quantity) || 0,
          rate: l.rate !== "" && l.rate != null ? l.rate : null,
        }));
      }
    }
    return body;
  }

  let journalCategories = [];

  async function loadJournals() {
    if (!journalForm) journalForm = blankJournalForm();
    const el = document.getElementById("finance-journal-body");
    if (!el) return;
    renderJournal();
    try {
      journalCategories = await ctx.api("/catalog/categories", {}, 0) || [];
    } catch (_) {
      journalCategories = [];
    }
    try {
      journals = await ctx.api("/stock-journals", {}, 0) || [];
    } catch (e) {
      journals = [];
      ctx.toast(e.message, "error");
    }
    renderJournal();
  }

  function renderJournal() {
    const el = document.getElementById("finance-journal-body");
    if (!el || !journalForm) return;
    const f = journalForm;
    const hitList = (hits, which) => hitButtons(hits, which);
    const transfer = f.kind === "transfer";
    const preview = f.preview;
    el.innerHTML = `
      <div class="card" style="padding:16px;display:grid;gap:12px;margin-bottom:16px;">
        <div style="display:flex;gap:16px;flex-wrap:wrap;">
          <label style="display:flex;gap:6px;align-items:center;"><input type="radio" name="fj-kind" ${transfer ? "checked" : ""} onchange="Finance.setJournalKind('transfer')" /> Move to new item</label>
          <label style="display:flex;gap:6px;align-items:center;"><input type="radio" name="fj-kind" ${!transfer ? "checked" : ""} onchange="Finance.setJournalKind('consumption')" /> Sample catalogues</label>
        </div>
        <div style="display:flex;gap:12px;flex-wrap:wrap;">
          <label>Date <input class="input" type="date" value="${ctx.esc(f.journal_date)}" onchange="Finance.setJournalField('journal_date', this.value)" /></label>
          <label style="flex:1;min-width:220px;">Note <input class="input" style="width:100%;" value="${ctx.esc(f.narration)}" oninput="Finance.setJournalField('narration', this.value)" placeholder="Why this journal" /></label>
        </div>
        ${transfer ? `
          <div style="display:grid;gap:8px;">
            <label>Old item <input class="input" id="fj-from" value="${ctx.esc(f.from_q)}" placeholder="Item number" oninput="Finance.searchJournalProduct('from', this.value)" /></label>
            ${f.from_label ? `<p style="margin:0;font-size:13px;">Selected ${ctx.esc(f.from_label)}</p>` : ""}
            <div id="fj-hits-from" style="display:flex;flex-direction:column;gap:4px;">${hitList(journalHits.from, "from")}</div>
            <label>New item <input class="input" id="fj-to" value="${ctx.esc(f.to_q)}" placeholder="Item number" oninput="Finance.searchJournalProduct('to', this.value)" /></label>
            ${f.to_label ? `<p style="margin:0;font-size:13px;">Selected ${ctx.esc(f.to_label)}</p>` : ""}
            <div id="fj-hits-to" style="display:flex;flex-direction:column;gap:4px;">${hitList(journalHits.to, "to")}</div>
            <label>Quantity <input class="input" type="number" min="1" value="${ctx.esc(f.quantity)}" oninput="Finance.setJournalField('quantity', this.value)" /></label>
          </div>
        ` : `
          <label>Expense category <input class="input" value="${ctx.esc(f.expense_category)}" oninput="Finance.setJournalField('expense_category', this.value)" /></label>
          <div style="display:flex;gap:16px;">
            <label style="display:flex;gap:6px;align-items:center;"><input type="radio" name="fj-mode" ${f.consume_mode === "items" ? "checked" : ""} onchange="Finance.setJournalMode('items')" /> Item wise</label>
            <label style="display:flex;gap:6px;align-items:center;"><input type="radio" name="fj-mode" ${f.consume_mode === "album" ? "checked" : ""} onchange="Finance.setJournalMode('album')" /> Album wise</label>
          </div>
          ${f.consume_mode === "album" ? `
            <label>Category
              <select class="input" onchange="Finance.setJournalField('album', this.value)">
                <option value="">— Select category —</option>
                ${(journalCategories || []).map(c => `<option value="${ctx.esc(c)}" ${f.album === c ? "selected" : ""}>${ctx.esc(c)}</option>`).join("")}
              </select>
            </label>
            <label>Quantity <input class="input" type="number" min="1" value="${ctx.esc(f.copies)}" oninput="Finance.setJournalField('copies', this.value)" /></label>
            <p style="margin:0;font-size:12px;color:var(--muted);">Every item in this category loses this quantity. The expense is each item's buying price times that quantity, added up.</p>
          ` : `
            <label>Search item <input class="input" id="fj-line" value="${ctx.esc(f.line_q)}" placeholder="Item number or name" oninput="Finance.searchJournalProduct('line', this.value)" /></label>
            <p style="margin:0;font-size:12px;color:var(--muted);">Tap a result to add it. Add as many items as you need, then set each quantity. One expense covers all of them.</p>
            <div id="fj-hits-line" style="display:flex;flex-direction:column;gap:4px;">${hitList(journalHits.line, "line")}</div>
            ${(f.lines || []).map((l, i) => `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              <strong>${ctx.esc(l.our_product_id)}</strong>
              <span style="color:var(--muted);font-size:12px;">stock ${l.on_hand ?? 0}</span>
              <input class="input" style="width:90px;" type="number" min="1" value="${ctx.esc(l.quantity)}" oninput="Finance.setJournalLine(${i}, 'quantity', this.value)" />
              <input class="input" style="width:110px;" placeholder="Rate" value="${ctx.esc(l.rate ?? "")}" oninput="Finance.setJournalLine(${i}, 'rate', this.value)" />
              <button type="button" class="btn btn-ghost btn-sm" onclick="Finance.removeJournalLine(${i})">Remove</button>
            </div>`).join("")}
          `}
        `}
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button type="button" class="btn btn-secondary" ${f.busy ? "disabled" : ""} onclick="Finance.previewJournal()">Preview</button>
          <button type="button" class="btn btn-primary" ${f.busy ? "disabled" : ""} onclick="Finance.saveJournal()">Save journal</button>
        </div>
        ${preview ? `
          ${(preview.warnings || []).map(w => `<p style="margin:0;color:#b45309;font-size:13px;">${ctx.esc(w)}</p>`).join("")}
          <p style="margin:0;font-size:13px;">Cost ${fmtPrice(preview.total_cost)} · ${preview.lines.length} item(s) · ${journalPieces(preview)} total pieces</p>
          ${(preview.warnings || []).map(w => `<p style="margin:0;font-size:13px;color:#92400e;">${ctx.esc(w)}</p>`).join("")}
          <div style="display:flex;gap:8px;">
            <button type="button" class="btn btn-secondary btn-sm" onclick="Finance.printJournalPreview()">Print</button>
            <button type="button" class="btn btn-secondary btn-sm" onclick="Finance.exportJournalExcel()">Excel</button>
          </div>
          <table class="data"><thead><tr><th>Item</th><th>Qty</th><th>Rate</th><th>Amount</th><th>On hand</th></tr></thead><tbody>
            ${(preview.lines || []).map(l => `<tr>
              <td>${ctx.esc(l.our_product_id)}</td>
              <td>${l.quantity_delta}</td>
              <td>${fmtPrice(l.rate)}</td>
              <td>${fmtPrice(l.amount)}</td>
              <td>${l.on_hand}</td>
            </tr>`).join("")}
          </tbody></table>
        ` : ""}
      </div>
      <div class="card table-wrap">
        ${journals.length ? `<table class="data"><thead><tr><th>Date</th><th>Kind</th><th>Note</th><th>Cost</th><th></th></tr></thead><tbody>
          ${journals.map(j => `<tr>
            <td>${ctx.esc(j.journal_date)}</td>
            <td>${j.kind === "transfer" ? "Move" : "Samples"}${j.voided_at ? " · voided" : ""}</td>
            <td>${ctx.esc(j.narration || "—")}</td>
            <td>${fmtPrice(j.total_cost)}</td>
            <td>${j.voided_at ? "" : `<button class="btn btn-ghost btn-sm" onclick="Finance.voidJournal(${j.id})">Void</button>`}</td>
          </tr>`).join("")}
        </tbody></table>` : `<p style="padding:16px;margin:0;color:var(--muted);">No journals yet.</p>`}
      </div>`;
  }

  function journalPieces(preview) {
    return (preview?.lines || []).reduce((sum, line) => sum + Math.abs(Number(line.quantity_delta) || 0), 0);
  }

  function printJournalPreview() {
    const preview = journalForm?.preview;
    if (!preview) return;
    const pieces = journalPieces(preview);
    const rows = (preview.lines || []).map(l => `<tr>
      <td>${ctx.esc(l.our_product_id)}</td>
      <td>${ctx.esc(String(l.quantity_delta))}</td>
      <td>${ctx.esc(String(l.rate ?? ""))}</td>
      <td>${ctx.esc(String(l.amount ?? ""))}</td>
      <td>${ctx.esc(String(l.on_hand ?? ""))}</td>
    </tr>`).join("");
    const title = journalForm?.kind === "transfer" ? "Move to new item" : "Sample catalogue";
    const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${ctx.esc(title)}</title>
      <style>body{font-family:sans-serif;font-size:12px;color:#111}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:4px 6px;text-align:left}h1{font-size:16px}</style>
      </head><body>
      <h1>${ctx.esc(title)}</h1>
      <p>Cost ${ctx.esc(String(preview.total_cost))} · ${(preview.lines || []).length} items · ${pieces} total pieces</p>
      <table><thead><tr><th>Item</th><th>Qty</th><th>Rate</th><th>Amount</th><th>On hand</th></tr></thead><tbody>${rows}</tbody></table>
      </body></html>`;
    const w = window.open("", "_blank");
    if (!w) return ctx.toast("Allow pop-ups to print", "error");
    w.document.open();
    w.document.write(html);
    w.document.close();
    w.focus();
    w.print();
  }

  function exportJournalExcel() {
    const preview = journalForm?.preview;
    if (!preview) return;
    const pieces = journalPieces(preview);
    const cell = (v) => ctx.esc(v == null ? "" : String(v));
    const rows = (preview.lines || []).map(l => `<tr>
      <td>${cell(l.our_product_id)}</td><td>${cell(l.quantity_delta)}</td><td>${cell(l.rate)}</td>
      <td>${cell(l.amount)}</td><td>${cell(l.on_hand)}</td></tr>`).join("");
    const html = `<html><head><meta charset="utf-8"></head><body>
      <table>
        <tr><td>Items</td><td>${(preview.lines || []).length}</td></tr>
        <tr><td>Total pieces</td><td>${pieces}</td></tr>
        <tr><td>Total cost</td><td>${cell(preview.total_cost)}</td></tr>
        <tr></tr>
        <tr><th>Item</th><th>Qty</th><th>Rate</th><th>Amount</th><th>On hand</th></tr>
        ${rows}
      </table></body></html>`;
    const blob = new Blob([html], { type: "application/vnd.ms-excel" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = journalForm?.kind === "transfer" ? "move-to-new-item.xls" : "sample-catalogue.xls";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function setJournalKind(kind) {
    if (!journalForm) journalForm = blankJournalForm();
    journalForm.kind = kind;
    journalForm.preview = null;
    renderJournal();
  }

  function setJournalMode(mode) {
    if (!journalForm) journalForm = blankJournalForm();
    journalForm.consume_mode = mode;
    journalForm.preview = null;
    renderJournal();
  }

  function setJournalField(key, value) {
    if (!journalForm) journalForm = blankJournalForm();
    journalForm[key] = value;
    journalForm.preview = null;
  }

  function setJournalLine(i, key, value) {
    if (!journalForm?.lines[i]) return;
    journalForm.lines[i][key] = value;
    journalForm.preview = null;
  }

  function removeJournalLine(i) {
    journalForm.lines.splice(i, 1);
    journalForm.preview = null;
    renderJournal();
  }

  function searchJournalProduct(which, value) {
    if (!journalForm) journalForm = blankJournalForm();
    if (which === "from") journalForm.from_q = value;
    else if (which === "to") journalForm.to_q = value;
    else journalForm.line_q = value;
    clearTimeout(journalTimer);
    const q = (value || "").trim();
    const paintHits = () => {
      const host = document.getElementById(`fj-hits-${which}`);
      if (!host) return;
      host.innerHTML = hitButtons(journalHits[which], which);
    };
    if (q.length < 1) {
      journalHits[which] = [];
      paintHits();
      return;
    }
    journalTimer = setTimeout(async () => {
      try {
        const rows = await ctx.api(`/stock-journals/products?q=${encodeURIComponent(q)}`, {}, 0) || [];
        if ((which === "from" ? journalForm.from_q : which === "to" ? journalForm.to_q : journalForm.line_q).trim() !== q) return;
        journalHits[which] = rows;
      } catch (e) {
        journalHits[which] = [];
        ctx.toast(e.message, "error");
      }
      paintHits();
    }, 200);
  }

  function hitButtons(hits, which) {
    return (hits || []).map(p => `
      <button type="button" class="btn btn-secondary btn-sm" style="justify-content:flex-start;" onclick="Finance.pickJournalProduct('${which}', ${p.catalog_product_id})">
        ${ctx.esc(p.our_product_id)}${p.category ? ` · ${ctx.esc(p.category)}` : ""} · stock ${p.quantity_on_hand ?? 0}${p.buying_price ? ` · buy ${ctx.esc(p.buying_price)}` : ""}
      </button>`).join("");
  }

  function pickJournalProduct(which, id) {
    const p = (journalHits[which] || []).find(x => x.catalog_product_id === id);
    if (!p || !journalForm) return;
    if (which === "from") {
      journalForm.from_id = id;
      journalForm.from_label = p.our_product_id;
      journalForm.from_q = p.our_product_id;
    } else if (which === "to") {
      journalForm.to_id = id;
      journalForm.to_label = p.our_product_id;
      journalForm.to_q = p.our_product_id;
    } else if (!journalForm.lines.some(l => l.catalog_product_id === id)) {
      journalForm.lines.push({
        catalog_product_id: id,
        our_product_id: p.our_product_id,
        quantity: 1,
        rate: p.buying_price || "",
        on_hand: p.quantity_on_hand,
      });
      journalForm.line_q = "";
    }
    journalHits[which] = [];
    journalForm.preview = null;
    renderJournal();
  }

  async function previewJournal() {
    syncJournalFields();
    journalForm.busy = true;
    renderJournal();
    try {
      journalForm.preview = await ctx.api("/stock-journals/preview", { method: "POST", body: JSON.stringify(journalBody()) }, 0);
    } catch (e) {
      journalForm.preview = null;
      ctx.toast(e.message, "error");
    } finally {
      journalForm.busy = false;
      renderJournal();
    }
  }

  async function saveJournal() {
    syncJournalFields();
    journalForm.busy = true;
    renderJournal();
    ctx.showLoading?.();
    try {
      const saved = await ctx.api("/stock-journals", { method: "POST", body: JSON.stringify(journalBody()) }, 0);
      ctx.toast(saved.kind === "consumption" ? "Sample cost recorded" : "Stock moved", "success");
      journalForm = blankJournalForm();
      journalHits = { from: [], to: [], line: [] };
      ctx.invalidateCache?.("/stock");
      ctx.invalidateCache?.("/expenses");
      await loadJournals();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally {
      if (journalForm) journalForm.busy = false;
      ctx.hideLoading?.();
      renderJournal();
    }
  }

  async function voidJournal(id) {
    const reason = window.prompt("Reason to void this journal");
    if (!reason || !reason.trim()) return;
    ctx.showLoading?.();
    try {
      await ctx.api(`/stock-journals/${id}/void`, { method: "POST", body: JSON.stringify({ reason: reason.trim() }) }, 0);
      ctx.toast("Journal voided. Stock put back.", "success");
      ctx.invalidateCache?.("/stock");
      ctx.invalidateCache?.("/expenses");
      await loadJournals();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

