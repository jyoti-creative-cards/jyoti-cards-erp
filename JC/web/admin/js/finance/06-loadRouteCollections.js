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
    } else if (f.kind === "direct_out" || f.kind === "direct_in") {
      body.expense_category = f.kind === "direct_in" ? "stock in" : "direct out";
      body.lines = (f.lines || []).filter(l => Number(l.quantity) > 0).map(l => ({
        catalog_product_id: l.catalog_product_id,
        quantity: Number(l.quantity) || 0,
        rate: l.rate !== "" && l.rate != null ? l.rate : null,
      }));
    } else {
      body.expense_category = (f.expense_category || "Sample catalogues").trim();
      const readyLines = (f.lines || []).filter(l => Number(l.quantity) > 0);
      if (f.consume_mode === "album" && !readyLines.length) {
        body.album = (f.album || "").trim();
        body.copies = Number(f.copies) || null;
      } else {
        body.lines = readyLines.map(l => ({
          catalog_product_id: l.catalog_product_id,
          quantity: Number(l.quantity) || 0,
          rate: l.rate !== "" && l.rate != null ? l.rate : null,
        }));
      }
    }
    return body;
  }

  function journalCategoryText(l) {
    const bits = [];
    if (l?.category) bits.push(`1 ${l.category}`);
    if (l?.second_category) bits.push(`2 ${l.second_category}`);
    if (l?.category_3) bits.push(`3 ${l.category_3}`);
    return bits.length ? bits.map(ctx.esc).join(" · ") : "no category";
  }

  let journalCategories = [];
  let journalLedger = "all";

  function journalKindLabel(kind) {
    if (kind === "transfer") return "Move";
    if (kind === "direct_out") return "Stock out";
    if (kind === "direct_in") return "Stock in";
    return "Samples";
  }

  function setJournalLedger(mode) {
    journalLedger = mode || "all";
    renderJournal();
  }

  function journalsForLedger() {
    const rows = journals || [];
    if (journalLedger === "in") return rows.filter(j => j.kind === "direct_in");
    if (journalLedger === "out") return rows.filter(j => j.kind === "direct_out");
    if (journalLedger === "stock") return rows.filter(j => j.kind === "direct_in" || j.kind === "direct_out");
    return rows;
  }

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
    const direct = f.kind === "direct_out";
    const inward = f.kind === "direct_in";
    const stockMove = direct || inward;
    const preview = f.preview;
    el.innerHTML = `
      <div class="card" style="padding:16px;display:grid;gap:12px;margin-bottom:16px;">
        <div style="display:flex;gap:16px;flex-wrap:wrap;">
          <label style="display:flex;gap:6px;align-items:center;"><input type="radio" name="fj-kind" ${transfer ? "checked" : ""} onchange="Finance.setJournalKind('transfer')" /> Move to new item</label>
          <label style="display:flex;gap:6px;align-items:center;"><input type="radio" name="fj-kind" ${f.kind === "consumption" ? "checked" : ""} onchange="Finance.setJournalKind('consumption')" /> Sample catalogues</label>
          <label style="display:flex;gap:6px;align-items:center;"><input type="radio" name="fj-kind" ${direct ? "checked" : ""} onchange="Finance.setJournalKind('direct_out')" /> Stock out</label>
          <label style="display:flex;gap:6px;align-items:center;"><input type="radio" name="fj-kind" ${inward ? "checked" : ""} onchange="Finance.setJournalKind('direct_in')" /> Stock in</label>
        </div>
        <div style="display:flex;gap:12px;flex-wrap:wrap;">
          <label>Date <input class="input" type="date" value="${ctx.esc(f.journal_date)}" onchange="Finance.setJournalField('journal_date', this.value)" /></label>
          <label style="flex:1;min-width:220px;">${stockMove ? "Reason (optional)" : "Note"} <input class="input" style="width:100%;" value="${ctx.esc(f.narration)}" oninput="Finance.setJournalField('narration', this.value)" placeholder="Why this journal" /></label>
        </div>
        ${stockMove ? `
          <p style="margin:0;font-size:13px;color:var(--muted);">${inward ? "Quantity comes into stock. This is not a vendor bill." : "Quantity leaves stock. Use this for damaged goods. Reason is optional."}</p>
          <label>Search item <input class="input" id="fj-line" value="${ctx.esc(f.line_q)}" placeholder="Item number or name" oninput="Finance.searchJournalProduct('line', this.value)" /></label>
          <div id="fj-hits-line" style="display:flex;flex-direction:column;gap:4px;">${hitList(journalHits.line, "line")}</div>
          ${(f.lines || []).map((l, i) => `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <strong>${ctx.esc(l.our_product_id)}</strong>
            <span style="color:var(--muted);font-size:12px;">${journalCategoryText(l)} · stock ${l.on_hand ?? 0}</span>
            <input class="input" style="width:90px;" type="number" min="1" value="${ctx.esc(l.quantity)}" oninput="Finance.setJournalLine(${i}, 'quantity', this.value)" />
            <input class="input" style="width:110px;" placeholder="Rate" value="${ctx.esc(l.rate ?? "")}" oninput="Finance.setJournalLine(${i}, 'rate', this.value)" />
            <button type="button" class="btn btn-ghost btn-sm" onclick="Finance.removeJournalLine(${i})">Remove</button>
          </div>`).join("")}
          ${(f.lines || []).length ? `<p style="margin:0;font-size:13px;"><strong>${journalTotalLine(draftLineTotals(f.lines))}</strong></p>` : ""}
        ` : transfer ? `
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
              <select class="input" onchange="Finance.loadAlbumLines(this.value)">
                <option value="">— Select category —</option>
                ${(journalCategories || []).map(c => `<option value="${ctx.esc(c)}" ${f.album === c ? "selected" : ""}>${ctx.esc(c)}</option>`).join("")}
              </select>
            </label>
            <div style="display:flex;gap:8px;align-items:end;flex-wrap:wrap;">
              <label>Default qty <input class="input" type="number" min="1" value="${ctx.esc(f.copies)}" oninput="Finance.setJournalField('copies', this.value)" /></label>
              <button type="button" class="btn btn-secondary btn-sm" onclick="Finance.applyJournalQtyAll()">Apply to all</button>
            </div>
            <p style="margin:0;font-size:12px;color:var(--muted);">Every item in this album is listed. Change any quantity (some can be 250). Add the same item again if it should be doubled. Apply to all fills every row with the default qty.</p>
            ${(f.lines || []).map((l, i) => `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              <strong>${ctx.esc(l.our_product_id)}</strong>
              <span style="color:var(--muted);font-size:12px;">${journalCategoryText(l)} · stock ${l.on_hand ?? 0}</span>
              <input class="input" style="width:90px;" type="number" min="1" value="${ctx.esc(l.quantity)}" oninput="Finance.setJournalLine(${i}, 'quantity', this.value)" />
              <input class="input" style="width:110px;" placeholder="Rate" value="${ctx.esc(l.rate ?? "")}" oninput="Finance.setJournalLine(${i}, 'rate', this.value)" />
              <button type="button" class="btn btn-ghost btn-sm" onclick="Finance.removeJournalLine(${i})">Remove</button>
            </div>`).join("")}
            ${(f.lines || []).length ? `<p style="margin:0;font-size:13px;"><strong>${journalTotalLine(draftLineTotals(f.lines))}</strong></p>` : ""}
            <label>Add extra item <input class="input" id="fj-line" value="${ctx.esc(f.line_q)}" placeholder="Item number or name — same item can be added again" oninput="Finance.searchJournalProduct('line', this.value)" /></label>
            <div id="fj-hits-line" style="display:flex;flex-direction:column;gap:4px;">${hitList(journalHits.line, "line")}</div>
          ` : `
            <label>Search item <input class="input" id="fj-line" value="${ctx.esc(f.line_q)}" placeholder="Item number or name" oninput="Finance.searchJournalProduct('line', this.value)" /></label>
            <p style="margin:0;font-size:12px;color:var(--muted);">Tap a result to add it. Add as many items as you need, then set each quantity. One expense covers all of them.</p>
            <div id="fj-hits-line" style="display:flex;flex-direction:column;gap:4px;">${hitList(journalHits.line, "line")}</div>
            ${(f.lines || []).map((l, i) => `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              <strong>${ctx.esc(l.our_product_id)}</strong>
              <span style="color:var(--muted);font-size:12px;">${journalCategoryText(l)} · stock ${l.on_hand ?? 0}</span>
              <input class="input" style="width:90px;" type="number" min="1" value="${ctx.esc(l.quantity)}" oninput="Finance.setJournalLine(${i}, 'quantity', this.value)" />
              <input class="input" style="width:110px;" placeholder="Rate" value="${ctx.esc(l.rate ?? "")}" oninput="Finance.setJournalLine(${i}, 'rate', this.value)" />
              <button type="button" class="btn btn-ghost btn-sm" onclick="Finance.removeJournalLine(${i})">Remove</button>
            </div>`).join("")}
            ${(f.lines || []).length ? `<p style="margin:0;font-size:13px;"><strong>${journalTotalLine(draftLineTotals(f.lines))}</strong></p>` : ""}
          `}
        `}
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button type="button" class="btn btn-secondary" ${f.busy ? "disabled" : ""} onclick="Finance.previewJournal()">Preview</button>
          <button type="button" class="btn btn-primary" ${f.busy ? "disabled" : ""} onclick="Finance.saveJournal()">Save journal</button>
        </div>
        ${preview ? `
          ${(preview.warnings || []).map(w => `<p style="margin:0;color:#b45309;font-size:13px;">${ctx.esc(w)}</p>`).join("")}
          <p style="margin:0;font-size:13px;">${journalTotalLine(journalTotals(preview))}</p>
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
            ${journalTotalRow(journalTotals(preview))}
          </tbody></table>
        ` : ""}
      </div>
      <div class="card table-wrap">
        <div style="display:flex;gap:8px;flex-wrap:wrap;padding:12px 12px 0;">
          <button type="button" class="btn btn-sm ${journalLedger === "all" ? "btn-primary" : "btn-secondary"}" onclick="Finance.setJournalLedger('all')">All journals</button>
          <button type="button" class="btn btn-sm ${journalLedger === "in" ? "btn-primary" : "btn-secondary"}" onclick="Finance.setJournalLedger('in')">Stock in</button>
          <button type="button" class="btn btn-sm ${journalLedger === "out" ? "btn-primary" : "btn-secondary"}" onclick="Finance.setJournalLedger('out')">Stock out</button>
          <button type="button" class="btn btn-sm ${journalLedger === "stock" ? "btn-primary" : "btn-secondary"}" onclick="Finance.setJournalLedger('stock')">Stock ledger</button>
        </div>
        ${journalListHtml()}
      </div>`;
  }

  function journalListHtml() {
    if (journalLedger === "stock") return stockLedgerTable();
    const rows = journalsForLedger();
    if (!rows.length) return `<p style="padding:16px;margin:0;color:var(--muted);">No journals yet.</p>`;
    return `<table class="data"><thead><tr><th>Date</th><th>Kind</th><th>Note</th><th>Cost</th><th></th></tr></thead><tbody>
      ${rows.map(j => `<tr>
        <td>${ctx.esc(j.journal_date)}</td>
        <td>${journalKindLabel(j.kind)}${j.voided_at ? " · voided" : ""}</td>
        <td>${ctx.esc(j.narration || "—")}</td>
        <td>${fmtPrice(j.total_cost)}</td>
        <td>${j.voided_at ? "" : `<button class="btn btn-ghost btn-sm" onclick="Finance.voidJournal(${j.id})">Void</button>`}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  function stockLedgerTable() {
    const rows = [];
    for (const j of journalsForLedger()) {
      if (j.voided_at) continue;
      for (const ln of j.lines || []) {
        rows.push(`<tr>
          <td>${ctx.esc(j.journal_date)}</td>
          <td>${journalKindLabel(j.kind)}</td>
          <td>${ctx.esc(ln.our_product_id)}</td>
          <td>${ln.quantity_delta}</td>
          <td>${ctx.esc(j.narration || "—")}</td>
          <td><button class="btn btn-ghost btn-sm" onclick="Finance.voidJournal(${j.id})">Void</button></td>
        </tr>`);
      }
    }
    if (!rows.length) return `<p style="padding:16px;margin:0;color:var(--muted);">No stock in or stock out yet.</p>`;
    return `<table class="data"><thead><tr><th>Date</th><th>Kind</th><th>Item</th><th>Qty</th><th>Note</th><th></th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
  }

  function journalPieces(preview) {
    return journalTotals(preview).qty;
  }

  function journalTotals(preview) {
    const lines = preview?.lines || [];
    const qty = lines.reduce((sum, line) => sum + Math.abs(Number(line.quantity_delta) || 0), 0);
    const amount = lines.reduce((sum, line) => sum + (Number(line.amount) || 0), 0);
    return { items: lines.length, qty, amount: amount || Number(preview?.total_cost) || 0 };
  }

  function draftLineTotals(lines) {
    const rows = lines || [];
    const qty = rows.reduce((sum, line) => sum + Math.abs(Number(line.quantity) || 0), 0);
    const amount = rows.reduce((sum, line) => {
      const q = Number(line.quantity) || 0;
      const rate = Number(line.rate);
      return sum + (Number.isFinite(rate) ? q * rate : 0);
    }, 0);
    return { items: rows.length, qty, amount };
  }

  function journalTotalLine(t) {
    return `Total · ${t.items} item(s) · Qty ${t.qty} · Amount ${fmtPrice(t.amount)}`;
  }

  function journalTotalRow(t) {
    return `<tr>
      <td><strong>Total · ${t.items} item(s)</strong></td>
      <td><strong>${t.qty}</strong></td>
      <td></td>
      <td><strong>${fmtPrice(t.amount)}</strong></td>
      <td></td>
    </tr>`;
  }

  function printJournalPreview() {
    const preview = journalForm?.preview;
    if (!preview) return;
    const totals = journalTotals(preview);
    const rows = (preview.lines || []).map(l => `<tr>
      <td>${ctx.esc(l.our_product_id)}</td>
      <td>${ctx.esc(String(l.quantity_delta))}</td>
      <td>${ctx.esc(String(l.rate ?? ""))}</td>
      <td>${ctx.esc(String(l.amount ?? ""))}</td>
      <td>${ctx.esc(String(l.on_hand ?? ""))}</td>
    </tr>`).join("");
    const title = journalKindLabel(journalForm?.kind);
    const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${ctx.esc(title)}</title>
      <style>body{font-family:sans-serif;font-size:12px;color:#111}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:4px 6px;text-align:left}h1{font-size:16px}</style>
      </head><body>
      <h1>${ctx.esc(title)}</h1>
      <p>${ctx.esc(journalTotalLine(totals))}</p>
      <table><thead><tr><th>Item</th><th>Qty</th><th>Rate</th><th>Amount</th><th>On hand</th></tr></thead>
      <tbody>${rows}${journalTotalRow(totals)}</tbody></table>
      </body></html>`;
    const w = window.open("", "_blank");
    if (!w) return ctx.toast("Allow pop-ups to print", "error");
    w.document.open();
    w.document.write(html);
    w.document.close();
    w.focus();
    let started = false;
    const go = () => {
      if (started) return;
      started = true;
      try { w.print(); } catch (_) {}
    };
    w.addEventListener("load", go);
    setTimeout(go, 200);
  }

  function exportJournalExcel() {
    const preview = journalForm?.preview;
    if (!preview) return;
    const totals = journalTotals(preview);
    const sheet = [
      ["Items", totals.items],
      ["Total qty", totals.qty],
      ["Total amount", totals.amount],
      [],
      ["Item", "Qty", "Rate", "Amount", "On hand"],
      ...(preview.lines || []).map(l => [l.our_product_id, l.quantity_delta, l.rate, l.amount, l.on_hand]),
      [`Total · ${totals.items} item(s)`, totals.qty, "", totals.amount, ""],
    ];
    Xlsx.download(`${journalKindLabel(journalForm?.kind).replace(/\s+/g, "-").toLowerCase()}.xlsx`, sheet);
  }

  function setJournalKind(kind) {
    if (!journalForm) journalForm = blankJournalForm();
    journalForm.kind = kind;
    journalForm.preview = null;
    if (kind === "direct_in") journalLedger = "in";
    else if (kind === "direct_out") journalLedger = "out";
    renderJournal();
  }

  function setJournalMode(mode) {
    if (!journalForm) journalForm = blankJournalForm();
    journalForm.consume_mode = mode;
    journalForm.preview = null;
    if (mode === "album") journalForm.lines = [];
    renderJournal();
  }

  function setJournalField(key, value) {
    if (!journalForm) journalForm = blankJournalForm();
    journalForm[key] = value;
    journalForm.preview = null;
  }

  function applyJournalQtyAll() {
    if (!journalForm) return;
    const qty = Math.max(1, parseInt(journalForm.copies, 10) || 1);
    journalForm.copies = String(qty);
    for (const line of journalForm.lines || []) line.quantity = qty;
    journalForm.preview = null;
    renderJournal();
  }

  async function loadAlbumLines(name) {
    if (!journalForm) journalForm = blankJournalForm();
    const album = (name || "").trim();
    journalForm.album = album;
    journalForm.preview = null;
    journalForm.lines = [];
    journalHits.line = [];
    if (!album) {
      renderJournal();
      return;
    }
    journalForm.busy = true;
    renderJournal();
    try {
      const rows = await ctx.api(`/stock-journals/products?q=${encodeURIComponent(album)}`, {}, 0) || [];
      const qty = Math.max(1, parseInt(journalForm.copies, 10) || 1);
      journalForm.lines = rows.map(p => ({
        catalog_product_id: p.catalog_product_id,
        our_product_id: p.our_product_id,
        category: p.category,
        second_category: p.second_category,
        category_3: p.category_3,
        quantity: qty,
        rate: p.buying_price || "",
        on_hand: p.quantity_on_hand,
      }));
      if (!rows.length) ctx.toast("No items in this album", "error");
    } catch (e) {
      journalForm.lines = [];
      ctx.toast(e.message, "error");
    } finally {
      journalForm.busy = false;
      renderJournal();
    }
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
    } else {
      const qty = journalForm.consume_mode === "album"
        ? Math.max(1, parseInt(journalForm.copies, 10) || 1)
        : 1;
      journalForm.lines.push({
        catalog_product_id: id,
        our_product_id: p.our_product_id,
        category: p.category,
        second_category: p.second_category,
        category_3: p.category_3,
        quantity: qty,
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
      ctx.toast(saved.kind === "consumption" ? "Sample cost recorded" : saved.kind === "direct_out" ? "Stock out recorded" : saved.kind === "direct_in" ? "Stock in recorded" : "Stock moved", "success");
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
    if (!ctx.isAdmin?.()) {
      const passKey = window.prompt("Your cancel key");
      if (!passKey || !passKey.trim()) return ctx.toast("Enter your cancel key", "error");
      window.__jcCancelKey = passKey.trim();
    } else {
      window.__jcCancelKey = "";
    }
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

