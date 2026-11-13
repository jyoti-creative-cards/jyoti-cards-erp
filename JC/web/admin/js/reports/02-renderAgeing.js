  async function renderAgeing(body) {
    const side = ageingSide === "ap" ? "ap" : "ar";
    const data = await ctx.api(`/reports/ageing/${side}`, {}, 0);
    const t = data.totals || {};
    const items = (data.items || []).filter(it => matchParty(it));
    body.innerHTML = `
      ${DocShare.toolbarHtml({
        printOnclick: "Reports.shareAgeing(true)",
        pdfOnclick: "Reports.shareAgeing(false)",
        waOnclick: "Reports.waAgeing()",
        excelOnclick: `Reports.exportExcel('${side}')`,
      })}
      <p class="fin-panel-sub" style="margin:0 0 12px;">As on ${ctx.esc(data.as_of || today())}</p>
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">0–30</span><strong>${fmtPrice(t["0-30"])}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">31–60</span><strong>${fmtPrice(t["31-60"])}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">61–90</span><strong>${fmtPrice(t["61-90"])}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">90+</span><strong>${fmtPrice(t["90+"])}</strong></div>
      </div>
      ${items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Party</th><th>Total</th><th>0–30</th><th>31–60</th><th>61–90</th><th>90+</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('${side === "ar" ? "customers" : "vendors"}', ${it.id})">
          <td><strong>${ctx.esc(it.label)}</strong></td>
          <td><strong>${fmtPrice(it.outstanding)}</strong></td>
          <td>${fmtPrice(it.b0_30)}</td>
          <td>${fmtPrice(it.b31_60)}</td>
          <td>${fmtPrice(it.b61_90)}</td>
          <td>${fmtPrice(it.b90_plus)}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("All clear", "Nothing due.")}`;
  }

  function toggleStockAlbum(name) {
    const has = stockAlbums.includes(name);
    stockAlbums = has ? stockAlbums.filter(a => a !== name) : stockAlbums.concat(name);
    loadChip();
  }

  async function renderStockWise(body) {
    const params = new URLSearchParams();
    if (fromDate) params.set("from_date", fromDate);
    if (toDate) params.set("to_date", toDate);
    stockAlbums.forEach(name => params.append("albums", name));
    const qs = params.toString();
    const data = await ctx.api(`/reports/stock/summary${qs ? `?${qs}` : ""}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.label, it.category, ...(it.albums || [])));
    const sum = (key) => items.reduce((s, it) => s + (Number(it[key]) || 0), 0);
    const opening = sum("opening");
    const inward = sum("inward");
    const outward = sum("outward");
    const closing = sum("closing");
    const albumBar = (data.albums || []).map(name =>
      `<label style="display:inline-flex;align-items:center;gap:4px;margin:0 10px 6px 0;font-size:13px;">
        <input type="checkbox" ${stockAlbums.includes(name) ? "checked" : ""} onchange="Reports.toggleStockAlbum(this.value)" value="${ctx.esc(name)}" />
        ${ctx.esc(name)}
      </label>`
    ).join("");
    body.innerHTML = `
      <div style="margin:0 0 12px;">${albumBar}</div>
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">Products</span><strong>${items.length}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Opening</span><strong>${opening}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">In</span><strong>${inward}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Out</span><strong>${outward}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Closing</span><strong>${closing}</strong></div>
      </div>
      ${items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Product</th><th>Opening</th><th>In</th><th>Out</th><th>Closing</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('products', ${it.id})">
          <td><strong>${ctx.esc(it.label)}</strong>${it.category ? `<div style="color:var(--muted);font-size:12px;">${ctx.esc(it.category)}</div>` : ""}</td>
          <td>${it.opening}</td>
          <td>${it.inward}</td>
          <td>${it.outward}</td>
          <td><strong>${it.closing}</strong></td>
        </tr>`).join("")}
        <tr><td><strong>Total</strong></td><td><strong>${opening}</strong></td><td><strong>${inward}</strong></td><td><strong>${outward}</strong></td><td><strong>${closing}</strong></td></tr>
      </tbody></table></div>` : empty("No stock movement", "Widen the dates to see products.")}`;
  }

  function fmtReportDay(iso) {
    const m = String(iso || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? `${m[3]}/${m[2]}/${m[1]}` : (iso || "");
  }

  function outwardPeriodLabel() {
    if (fromDate && toDate && fromDate !== toDate) return `${fmtReportDay(fromDate)} to ${fmtReportDay(toDate)}`;
    if (fromDate || toDate) return fmtReportDay(fromDate || toDate);
    return "All dates";
  }

  function setJournalReportKind(kind) {
    journalReportKind = ["all", "transfer", "consumption", "direct_out"].includes(kind) ? kind : "all";
    loadChip();
  }

  async function renderStockJournal(body) {
    const data = await ctx.api(`/reports/stock/journals${rangeQs({ kind: journalReportKind })}`, {}, 0);
    const q = hubSearch.trim().toLowerCase();
    const items = (data.items || []).filter(it => {
      if (!q) return true;
      return [it.item, it.kind_label, it.reason, it.by].join(" ").toLowerCase().includes(q);
    });
    const kinds = [
      ["all", "All"],
      ["transfer", "Move to new item"],
      ["consumption", "Sampling"],
      ["direct_out", "Direct out"],
    ];
    const kindBar = kinds.map(([id, label]) =>
      `<button type="button" class="btn btn-sm ${journalReportKind === id ? "btn-primary" : "btn-secondary"}" onclick="Reports.setJournalReportKind('${id}')">${label}</button>`
    ).join(" ");
    const period = outwardPeriodLabel();
    const qty = items.reduce((s, it) => s + (Number(it.qty) || 0), 0);
    const amount = items.reduce((s, it) => s + (Number(it.amount) || 0), 0);
    body.innerHTML = `
      <h2 class="report-print-title" style="position:absolute;left:-9999px;">Stock journal · ${ctx.esc(period)}</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px;">${kindBar}</div>
      <p class="fin-panel-sub" style="margin:0 0 12px;">${ctx.esc(period)} · ${items.length} line${items.length === 1 ? "" : "s"} · Qty ${qty} · ${fmtPrice(amount)}</p>
      ${items.length ? `<div class="card table-wrap"><table class="data"><caption style="caption-side:top;text-align:left;font-weight:600;padding:8px 0;">Stock journal · ${ctx.esc(period)}</caption><thead><tr>
        <th>Date</th><th>Type</th><th>Item</th><th>Qty</th><th>Rate</th><th>Amount</th><th>Reason</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr>
          <td>${ctx.esc(fmtReportDay(it.date))}</td>
          <td>${ctx.esc(it.kind_label || it.kind)}</td>
          <td><strong>${ctx.esc(it.item)}</strong></td>
          <td>${it.signed_qty < 0 ? "−" : ""}${it.qty}</td>
          <td>${fmtPrice(it.rate)}</td>
          <td>${fmtPrice(it.amount)}</td>
          <td>${ctx.esc(it.reason || "")}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No journal lines", "Widen the dates, or pick another type.")}`;
  }

  function tallyCell(raw, pcs) {
    if (raw == null || raw === "" || Number(raw) === 0) return "";
    const n = Number(raw);
    const abs = Math.abs(n).toLocaleString("en-IN", pcs
      ? { maximumFractionDigits: 0 }
      : { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const body = pcs ? `${abs} pcs` : abs;
    return n < 0 ? `(-)${body}` : body;
  }

  function tallyTotal(raw, pcs) {
    const n = Number(raw) || 0;
    const abs = Math.abs(n).toLocaleString("en-IN", pcs
      ? { maximumFractionDigits: 0 }
      : { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const body = pcs ? `${abs} pcs` : abs;
    return n < 0 ? `(-)${body}` : body;
  }

  function setStockYear(value) {
    stockYear = value || "";
    loadChip();
  }

  function stockQs() {
    return rangeQs(stockYear ? { year_group: stockYear } : {});
  }

  async function shareStockSummary(print) {
    try {
      const yearBit = stockYear ? `_${stockYear}` : "";
      const name = fromDate && toDate && fromDate !== toDate
        ? `stock_summary_${fromDate}_${toDate}${yearBit}.pdf`
        : `stock_summary_${fromDate || toDate || "all"}${yearBit}.pdf`;
      await DocShare.openPdf(`/share/stock-summary/pdf${stockQs()}`, { print: !!print, filename: name });
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function shareNoAlbum(print) {
    try {
      const name = fromDate && toDate && fromDate !== toDate
        ? `items-without-album_${fromDate}_${toDate}.pdf`
        : `items-without-album_${fromDate || toDate || "all"}.pdf`;
      await DocShare.openPdf(`/reports/items-without-album/pdf${rangeQs()}`, { print: !!print, filename: name });
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function renderNoAlbum(body) {
    const data = await ctx.api(`/reports/items-without-album${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.item));
    const period = data.period || "";
    const num = "text-align:right;white-space:nowrap;";
    const sum = (key) => items.reduce((s, it) => s + (Number(it[key]) || 0), 0);
    body.innerHTML = `
      ${DocShare.toolbarHtml({
        printOnclick: "Reports.shareNoAlbum(true)",
        pdfOnclick: "Reports.shareNoAlbum(false)",
        excelOnclick: "Reports.exportCurrentExcel()",
      })}
      <h2 class="report-print-title" style="position:absolute;left:-9999px;">Items without album · ${ctx.esc(period)}</h2>
      <p class="fin-panel-sub" style="margin:0 0 12px;">${ctx.esc(period)}. Items with no album in category 1, 2, or 3. Total amount is stock × price.</p>
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">Items</span><strong>${items.length}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Stock</span><strong>${sum("stock")}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Total sales</span><strong>${sum("total_sales")}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Total amount</span><strong>${sum("total_amount").toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong></div>
      </div>
      ${items.length ? `<div class="card table-wrap"><table class="data"><caption style="caption-side:top;text-align:left;font-weight:700;padding:8px 12px;">Items without album · ${ctx.esc(period)}</caption><thead><tr>
          <th>Item</th><th style="${num}">Stock</th><th style="${num}">Price</th><th style="${num}">Inward</th><th style="${num}">Outward</th><th>Last sale</th><th style="${num}">Total bills</th><th style="${num}">Total sales</th><th style="${num}">Total amount</th>
        </tr></thead><tbody>
        ${items.map(it => `<tr>
          <td><strong>${ctx.esc(it.item)}</strong></td>
          <td style="${num}">${it.stock}</td>
          <td style="${num}">${ctx.esc(it.price)}</td>
          <td style="${num}">${it.inward}</td>
          <td style="${num}">${it.outward}</td>
          <td>${ctx.esc(it.last_sale || "—")}</td>
          <td style="${num}">${it.total_bills}</td>
          <td style="${num}">${it.total_sales}</td>
          <td style="${num}">${ctx.esc(it.total_amount)}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No items", "Every active item is in an album.")}`;
  }

  async function renderItemOutward(body) {
    if (!stockYears) {
      try { stockYears = await ctx.api("/catalog/year-groups", {}, 60000) || []; }
      catch (_) { stockYears = []; }
    }
    const data = await ctx.api(`/reports/stock/group-summary${stockQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.particular, it.vendor_name));
    const sum = (key) => items.reduce((s, it) => s + (Number(it[key]) || 0), 0);
    const period = data.period || outwardPeriodLabel();
    const num = "text-align:right;white-space:nowrap;";
    body.innerHTML = `
      ${DocShare.toolbarHtml({
        printOnclick: "Reports.shareStockSummary(true)",
        pdfOnclick: "Reports.shareStockSummary(false)",
        excelOnclick: "Reports.exportCurrentExcel()",
      })}
      <div class="rep-filters" style="margin-bottom:12px;">
        <label class="label">Year group
          <select class="input" onchange="Reports.setStockYear(this.value)">
            <option value="">All years</option>
            ${(stockYears || []).map(y => `<option value="${ctx.esc(y)}" ${stockYear === y ? "selected" : ""}>${ctx.esc(y)}</option>`).join("")}
          </select>
        </label>
      </div>
      <h2 class="report-print-title" style="position:absolute;left:-9999px;">Stock Summary · ${ctx.esc(period)}${stockYear ? ` · ${ctx.esc(stockYear)}` : ""}</h2>
      <p class="fin-panel-sub" style="margin:0 0 12px;">${ctx.esc(period)}. Same start and end date is one day. Total sales is a bill, or a confirmed order that is not billed yet. Closing rate is the purchase rate.</p>
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">Items</span><strong>${items.length}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Total sales</span><strong>${sum("sales_count")}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Inward</span><strong>${tallyTotal(sum("in_qty"), true)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Outward</span><strong>${tallyTotal(sum("out_qty"), true)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Closing value</span><strong>${tallyTotal(sum("close_value"), false)}</strong></div>
      </div>
      ${items.length ? `<div class="card table-wrap"><table class="data"><caption style="caption-side:top;text-align:left;font-weight:700;padding:8px 12px;">Stock Summary · ${ctx.esc(period)}</caption><thead>
        <tr>
          <th rowspan="2">Particulars</th>
          <th rowspan="2">Vendor</th>
          <th rowspan="2" style="${num}">Total sales</th>
          <th colspan="3" style="text-align:center;">Inwards</th>
          <th colspan="3" style="text-align:center;">Outwards</th>
          <th colspan="3" style="text-align:center;">Closing balance</th>
        </tr>
        <tr>
          <th style="${num}">Quantity</th><th style="${num}">Rate</th><th style="${num}">Value</th>
          <th style="${num}">Quantity</th><th style="${num}">Rate</th><th style="${num}">Value</th>
          <th style="${num}">Quantity</th><th style="${num}">Rate</th><th style="${num}">Value</th>
        </tr>
      </thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('products', ${it.id})">
          <td><strong>${ctx.esc(it.particular)}</strong></td>
          <td>${ctx.esc(it.vendor_name || "")}</td>
          <td style="${num}">${it.sales_count ? it.sales_count : ""}</td>
          <td style="${num}">${tallyCell(it.in_qty, true)}</td>
          <td style="${num}">${tallyCell(it.in_rate, false)}</td>
          <td style="${num}">${tallyCell(it.in_value, false)}</td>
          <td style="${num}">${tallyCell(it.out_qty, true)}</td>
          <td style="${num}">${tallyCell(it.out_rate, false)}</td>
          <td style="${num}">${tallyCell(it.out_value, false)}</td>
          <td style="${num}">${tallyCell(it.close_qty, true)}</td>
          <td style="${num}">${tallyCell(it.close_rate, false)}</td>
          <td style="${num}">${tallyCell(it.close_value, false)}</td>
        </tr>`).join("")}
        <tr>
          <td colspan="3"><strong>Grand total</strong></td>
          <td style="${num}"><strong>${tallyTotal(sum("in_qty"), true)}</strong></td>
          <td></td>
          <td style="${num}"><strong>${tallyTotal(sum("in_value"), false)}</strong></td>
          <td style="${num}"><strong>${tallyTotal(sum("out_qty"), true)}</strong></td>
          <td></td>
          <td style="${num}"><strong>${tallyTotal(sum("out_value"), false)}</strong></td>
          <td style="${num}"><strong>${tallyTotal(sum("close_qty"), true)}</strong></td>
          <td></td>
          <td style="${num}"><strong>${tallyTotal(sum("close_value"), false)}</strong></td>
        </tr>
      </tbody></table></div>` : empty("No movement", "Nothing was billed, confirmed, or received in these dates.")}`;
  }

  async function renderValuation(body) {
    const data = await ctx.api(`/reports/stock/valuation`, {}, 0);
    const t = data.totals || {};
    const items = (data.items || []).filter(it => matchSearch(it.label));
    body.innerHTML = `
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">SKUs</span><strong>${t.sku_count || 0}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Buy value</span><strong>${fmtPrice(t.buy_value)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Sell value</span><strong>${fmtPrice(t.sell_value)}</strong></div>
      </div>
      ${items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Product</th><th>Qty</th><th>Buy</th><th>Sell</th><th>Buy value</th><th>Sell value</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('products', ${it.id})">
          <td><strong>${ctx.esc(it.label)}</strong></td>
          <td>${it.qty}</td>
          <td>${fmtPrice(it.buying_price)}</td>
          <td>${it.selling_price != null ? fmtPrice(it.selling_price) : "—"}</td>
          <td>${fmtPrice(it.buy_value)}</td>
          <td>${it.sell_value != null ? fmtPrice(it.sell_value) : "—"}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No stock on hand", "Receive stock to see valuation.")}`;
  }

  async function renderMovers(body) {
    const data = await ctx.api(`/reports/stock/movers${rangeQs()}`, {}, 0);
    const fast = (data.fast || []).filter(it => matchSearch(it.label));
    const slow = (data.slow || []).filter(it => matchSearch(it.label));
    body.innerHTML = `
      <h3 class="fin-panel-title" style="margin:0 0 8px;">Fast movers</h3>
      ${fast.length ? `<div class="card table-wrap" style="margin-bottom:24px;"><table class="data"><thead><tr>
        <th>Product</th><th>Sold</th><th>Sales</th><th>On hand</th>
      </tr></thead><tbody>
        ${fast.map(it => `<tr><td>${ctx.esc(it.label)}</td><td>${it.qty_sold}</td><td>${fmtPrice(it.sales_value)}</td><td>${it.on_hand}</td></tr>`).join("")}
      </tbody></table></div>` : empty("No sales in range", "Widen dates to see movers.")}
      <h3 class="fin-panel-title" style="margin:0 0 8px;">Slow / idle</h3>
      ${slow.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Product</th><th>Sold</th><th>On hand</th>
      </tr></thead><tbody>
        ${slow.map(it => `<tr><td>${ctx.esc(it.label)}</td><td>${it.qty_sold}</td><td>${it.on_hand}</td></tr>`).join("")}
      </tbody></table></div>` : empty("No idle stock", "Everything is moving or empty.")}`;
  }

  async function renderLow(body) {
    const data = await ctx.api(`/reports/stock/low?threshold=${lowThreshold}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.label));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Product</th><th>On hand</th><th>Limit</th><th>Buy</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('products', ${it.id})">
        <td><strong>${ctx.esc(it.label)}</strong></td>
        <td>${it.qty}</td><td>${it.threshold}</td><td>${fmtPrice(it.buying_price)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("Stock looks fine", "Nothing at or below this threshold.");
  }

  async function renderReturns(body) {
    const data = await ctx.api(`/reports/returns-register${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.doc_number, it.party_label));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Date</th><th>Number</th><th>Customer</th><th>Qty</th><th>Credit</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr>
        <td>${ctx.esc(it.date || "—")}</td>
        <td>${ctx.esc(it.doc_number || "—")}</td>
        <td>${ctx.esc(it.party_label || "—")}</td>
        <td>${it.qty}</td>
        <td>${fmtPrice(it.credit_amount)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No returns", "Widen dates if you expect credit notes.");
  }

  async function renderDebitNotes(body) {
    const data = await ctx.api(`/reports/debit-notes-register${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.party_label, it.our_product_id, it.notes));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Date</th><th>Vendor</th><th>Type</th><th>Product</th><th>Amount</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr>
        <td>${ctx.esc(it.date || "—")}</td>
        <td>${ctx.esc(it.party_label || "—")}</td>
        <td>${ctx.esc(it.note_type)}/${ctx.esc(it.direction || "")}</td>
        <td>${ctx.esc(it.our_product_id || "—")}</td>
        <td>${fmtPrice(it.amount)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No debit notes", "Widen dates to see purchase adjustments.");
  }

  async function renderGst(body) {
    const path = chip === "gst-purchases" ? "gst/purchases" : "gst/sales";
    const data = await ctx.api(`/reports/${path}${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.doc_number, it.party_label));
    const note = chip === "gst-purchases"
      ? `<p class="fin-panel-sub" style="margin:0 0 12px;">Purchase GST not stored on receipts yet — GST shows as 0.</p>` : "";
    body.innerHTML = note + (items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Date</th><th>Number</th><th>Party</th><th>Rate</th><th>Taxable</th><th>GST</th><th>Total</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr>
        <td>${ctx.esc(it.date || "—")}</td>
        <td>${ctx.esc(it.doc_number || "—")}${it.status === "cancelled" ? " cancel" : ""}</td>
        <td>${ctx.esc(it.party_label || "—")}</td>
        <td>${it.gst_enabled ? `${it.gst_rate}%` : "Off"}</td>
        <td>${fmtPrice(it.taxable_value)}</td>
        <td>${fmtPrice(it.gst_amount)}</td>
        <td>${fmtPrice(it.grand_total)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No bills", "Widen dates for the GST register."));
  }

  async function renderCashbook(body) {
    const data = await ctx.api(`/reports/cashbook${rangeQs()}`, {}, 0);
    const t = data.totals || {};
    const entries = (data.entries || []).filter(r => matchSearch(r.kind, r.party, r.label));
    body.innerHTML = `
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        <div class="fin-stat"><span class="fin-stat-label">In</span><strong>${fmtPrice(t.cash_in)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Out</span><strong>${fmtPrice(t.cash_out)}</strong></div>
        <div class="fin-stat"><span class="fin-stat-label">Net</span><strong>${fmtPrice(t.net)}</strong></div>
      </div>
      ${entries.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Date</th><th>Type</th><th>Party</th><th>In</th><th>Out</th><th>Balance</th>
      </tr></thead><tbody>
        ${entries.map(r => `<tr>
          <td>${ctx.esc(r.date || "—")}</td>
          <td>${ctx.esc(r.kind)}</td>
          <td>${ctx.esc(r.party || "—")}</td>
          <td>${fmtPrice(r.in_amount)}</td>
          <td>${fmtPrice(r.out_amount)}</td>
          <td>${fmtPrice(r.balance)}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No cash moves", "Widen dates to build the cash book.")}`;
  }

  async function renderExpenseCat(body) {
    const data = await ctx.api(`/reports/expense-by-category${rangeQs()}`, {}, 0);
    const items = (data.items || []).filter(it => matchSearch(it.category));
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Category</th><th>Count</th><th>Amount</th>
    </tr></thead><tbody>
      ${items.map(it => `<tr class="clickable" onclick="Reports.openExpenseLedger('${ctx.esc(it.category)}')">
        <td><strong>${ctx.esc(it.category)}</strong></td>
        <td>${it.count}</td>
        <td>${fmtPrice(it.amount)}</td>
      </tr>`).join("")}
    </tbody></table></div>` : empty("No expenses", "Add expenses in Finance, or widen dates.");
  }

  async function renderPnl(body) {
    const data = await ctx.api(`/reports/pnl${rangeQs()}`, {}, 0);
    body.innerHTML = `<div class="review-grid">
      ${ctx.reviewRow("Sales billed (incl. GST)", fmtPrice(data.sales_billed))}
      ${ctx.reviewRow("GST on sales", fmtPrice(data.gst_on_sales))}
      ${ctx.reviewRow("Sales, ex-GST", fmtPrice(data.sales_taxable))}
      ${ctx.reviewRow("Customer returns", data.customer_returns && Number(data.customer_returns) > 0 ? "−" + fmtPrice(data.customer_returns) : fmtPrice(data.customer_returns))}
      ${ctx.reviewRow("Net sales", fmtPrice(data.net_sales))}
      ${ctx.reviewRow("Purchases (COGS proxy)", fmtPrice(data.cogs_purchases))}
      ${ctx.reviewRow("Vendor debit notes", fmtPrice(data.vendor_debit_notes))}
      ${ctx.reviewRow("Net COGS", fmtPrice(data.cogs_net))}
      ${ctx.reviewRow("Gross profit", fmtPrice(data.gross_profit))}
      ${ctx.reviewRow("Expenses", fmtPrice(data.expenses))}
      ${ctx.reviewRow("Freight paid", fmtPrice(data.freight_paid))}
      ${ctx.reviewRow("Manual losses", fmtPrice(data.manual_losses))}
      ${ctx.reviewRow("Net profit", fmtPrice(data.net_profit))}
      ${ctx.reviewRow("Cash collected", fmtPrice(data.cash_collected))}
      ${ctx.reviewRow("Bill count", data.bill_count)}
    </div>
    <p class="fin-panel-sub" style="margin-top:12px;">Net profit = net sales (ex-GST, net of returns) − net COGS (purchases, net of vendor debit notes) − expenses − manual losses. Still a management approximation, not true inventory-costed accounting.${data.note ? ` ${ctx.esc(data.note)}` : ""}</p>`;
  }

  async function renderLedgers(body) {
    if (ledgerKind === "agents") {
      let rows = [];
      try { rows = await ctx.api("/commission-agents", {}, 0) || []; }
      catch (e) { body.innerHTML = empty("Could not load agents", e.message); return; }
      const q = foldReportName(hubSearch);
      rows = rows.filter(r => !q || q.split(/\s+/).every(t => foldReportName(r.name).includes(t) || String(r.phone || "").includes(t)));
      body.innerHTML = rows.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Agent</th><th>Phone</th><th>Parties</th><th>Due</th>
      </tr></thead><tbody>
        ${rows.map(r => `<tr class="clickable" onclick="Reports.openAgentLedger(${r.id})">
          <td><strong>${ctx.esc(r.name)}</strong></td>
          <td>${ctx.esc(r.phone || "—")}</td>
          <td>${r.party_count || 0}</td>
          <td><strong>${fmtPrice(r.outstanding)}</strong></td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No agent", "No commission agent matches that search.");
      return;
    }
    if (ledgerKind === "cash") {
      body.innerHTML = `<div class="fin-panel-head" style="margin-bottom:16px;">
        <div><h3 class="fin-panel-title">Cash book</h3>
        <p class="fin-panel-sub">All cash in and out with running balance</p></div>
        <button type="button" class="btn btn-primary" onclick="Reports.openCashLedger()">Open cash book</button>
      </div>`;
      return;
    }
    const data = await ctx.api(`/reports/ledgers/${ledgerKind}`, {}, 0);
    let items = data.items || [];

    if (ledgerKind === "staff") {
      items = items.filter(it => matchSearch(it.label, it.phone));
      body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Name</th><th>Phone</th><th>Activities</th>
      </tr></thead><tbody>
        ${items.map(it => {
          const onclick = it.actor_type === "admin"
            ? `Reports.openStaffLedger(0, 'admin', '${ctx.esc(it.actor_name || "")}')`
            : `Reports.openStaffLedger(${it.id})`;
          return `<tr class="clickable" onclick="${onclick}">
            <td><strong>${ctx.esc(it.label)}</strong></td>
            <td>${ctx.esc(it.phone || "—")}</td>
            <td>${it.activity_count || 0}</td>
          </tr>`;
        }).join("")}
      </tbody></table></div>` : empty("No staff activity", "Staff actions show up as they use the app.");
      return;
    }

    if (ledgerKind === "expenses") {
      let heads = [];
      try { heads = await ctx.api("/expenses/heads", {}, 0) || []; } catch (err) { heads = []; }
      const covered = new Set();
      heads.forEach(h => {
        covered.add((h.name || "").toLowerCase());
        (h.subheads || []).forEach(s => covered.add((s.category || "").toLowerCase()));
      });
      const shownHeads = heads.filter(h => matchSearch(h.name) || (h.subheads || []).some(s => matchSearch(h.name, s.name)));
      const earlier = items.filter(it => !covered.has(String(it.category || it.label || "").toLowerCase()) && matchSearch(it.label, it.category));
      const headRows = shownHeads.map(h => `
        <tr class="clickable" onclick="Reports.openExpenseLedger('${ctx.esc(h.name)}')">
          <td><strong>${ctx.esc(h.name)}</strong></td>
          <td>All</td>
          <td>${h.count || 0}</td>
          <td>${fmtPrice(h.total)}</td>
          <td><button type="button" class="btn btn-ghost btn-sm" onclick="event.stopPropagation(); Reports.addExpenseSubhead(${h.id})">Sub-head</button></td>
        </tr>
        ${(h.subheads || []).filter(s => matchSearch(h.name, s.name)).map(s => `
          <tr class="clickable" onclick="Reports.openExpenseLedger('${ctx.esc(s.category)}')">
            <td></td>
            <td>${ctx.esc(s.name)}</td>
            <td>${s.count || 0}</td>
            <td>${fmtPrice(s.total)}</td>
            <td></td>
          </tr>`).join("")}`).join("");
      const oldRows = earlier.map(it => `<tr class="clickable" onclick="Reports.openExpenseLedger('${ctx.esc(it.category || it.label)}')">
          <td><strong>${ctx.esc(it.label)}</strong></td>
          <td>—</td>
          <td>${it.count || 0}</td>
          <td>${fmtPrice(it.outstanding)}</td>
          <td></td>
        </tr>`).join("");
      let sources = [];
      try { sources = await ctx.api("/expenses/sources", {}, 0) || []; } catch (err) { sources = []; }
      const sourceRows = sources.map(s => `<div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
        <span style="flex:1;">${ctx.esc(s.name)}</span>
        <button type="button" class="btn btn-ghost btn-sm" onclick="Reports.renameExpenseSource(${s.id})">Rename</button>
        <button type="button" class="btn btn-ghost btn-sm" onclick="Reports.deleteExpenseSource(${s.id})">Delete</button>
      </div>`).join("");
      body.innerHTML = `<div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
          <button type="button" class="btn btn-primary btn-sm" onclick="Reports.addExpenseHead()">New head</button>
        </div>
        <div class="card" style="padding:12px;margin-bottom:12px;">
          <strong>Paid from</strong>
          <p style="margin:4px 0 8px;font-size:12px;color:var(--muted);">ICICI, cash, and any other account the money leaves from.</p>
          ${sourceRows}
          <div style="display:flex;gap:8px;margin-top:8px;">
            <input id="rep-source-new" class="input" placeholder="New source" />
            <button type="button" class="btn btn-secondary btn-sm" onclick="Reports.addExpenseSource()">Add</button>
          </div>
        </div>` + ((headRows || oldRows) ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Head</th><th>Sub-head</th><th>Count</th><th>Total</th><th></th>
      </tr></thead><tbody>${headRows}${oldRows}</tbody></table></div>` : empty("No expense heads", "Create a head, then a sub-head, then enter the expense in Finance."));
      return;
    }

    if (ledgerKind === "products") {
      items = items.filter(it => matchSearch(it.label));
      body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Name</th><th>On hand</th><th>Buy</th><th>Sell</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('products', ${it.id})">
          <td><strong>${ctx.esc(it.label)}</strong></td>
          <td>${it.qty ?? 0}</td>
          <td>${fmtPrice(it.buying_price)}</td>
          <td>${it.selling_price != null ? fmtPrice(it.selling_price) : '<span class="prod-price-missing">Not set</span>'}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No products", "Add catalog products first.");
      return;
    }

    items = items.filter(it => matchParty(it));
    const isRoute = ledgerKind === "routes";
    const isFreight = ledgerKind === "freight";
    body.innerHTML = items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
      <th>Name</th>
      <th>${isRoute ? "Customers" : isFreight ? "Due" : "Opening"}</th>
      ${isRoute || !isFreight ? "<th>Due</th>" : ""}
    </tr></thead><tbody>
      ${items.map(it => `<tr class="clickable" onclick="Reports.openLedger('${ledgerKind}', ${it.id})">
        <td><strong>${ctx.esc(it.label)}</strong></td>
        <td>${isRoute ? (it.customer_count ?? 0) : isFreight ? `<strong>${fmtPrice(it.outstanding)}</strong>` : fmtPrice(it.opening_total)}</td>
        ${isRoute || !isFreight ? `<td><strong>${fmtPrice(it.outstanding)}</strong></td>` : ""}
      </tr>`).join("")}
    </tbody></table></div>` : empty("No ledgers", "Nothing to show for this list.");
  }

  async function openLedger(kind, id) {
    backLabel = "Back";
    ctx.showLoading?.();
    try {
      ledgerDetail = await ctx.api(`/reports/ledgers/${kind}/${id}`, {}, 0);
      showDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openStaffLedger(id, actorType = "staff", actorName = "") {
    backLabel = "Back to staff";
    ctx.showLoading?.();
    try {
      let url = `/reports/ledgers/staff/${id || 0}`;
      if (actorType === "admin") url += `?actor_type=admin&actor_name=${encodeURIComponent(actorName)}`;
      ledgerDetail = await ctx.api(url, {}, 0);
      showDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function addExpenseSource() {
    const name = (document.getElementById("rep-source-new")?.value || "").trim();
    if (!name) return ctx.toast("Type a source name", "error");
    try {
      await ctx.api("/expenses/sources", { method: "POST", body: JSON.stringify({ name }) });
      ctx.toast("Source saved", "success");
      setLedgerKind("expenses");
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function renameExpenseSource(id) {
    const name = prompt("Source name:");
    if (name == null || !name.trim()) return;
    try {
      await ctx.api(`/expenses/sources/${id}`, { method: "PATCH", body: JSON.stringify({ name: name.trim() }) });
      ctx.toast("Source renamed", "success");
      setLedgerKind("expenses");
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function deleteExpenseSource(id) {
    if (!confirm("Delete this source?")) return;
    try {
      await ctx.api(`/expenses/sources/${id}`, { method: "DELETE" });
      ctx.toast("Source deleted", "success");
      setLedgerKind("expenses");
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function addExpenseHead() {
    const name = prompt("Expense head name:");
    if (name == null || !name.trim()) return;
    try {
      await ctx.api("/expenses/heads", { method: "POST", body: JSON.stringify({ name: name.trim() }) });
      ctx.toast("Head saved", "success");
      setLedgerKind("expenses");
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function addExpenseSubhead(headId) {
    const name = prompt("Sub-head name:");
    if (name == null || !name.trim()) return;
    try {
      await ctx.api(`/expenses/heads/${headId}/subheads`, { method: "POST", body: JSON.stringify({ name: name.trim() }) });
      ctx.toast("Sub-head saved", "success");
      setLedgerKind("expenses");
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function openExpenseLedger(category) {
    backLabel = "Back";
    ctx.showLoading?.();
    try {
      const qs = new URLSearchParams({ category });
      ledgerDetail = await ctx.api(`/reports/ledgers/expense-book?${qs}`, {}, 0);
      showDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openCashLedger() {
    backLabel = "Back";
    ctx.showLoading?.();
    try {
      ledgerDetail = await ctx.api(`/reports/ledgers/cash/book${rangeQs()}`, {}, 0);
      showDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function showDetail() {
    document.getElementById("reports-hub")?.classList.add("hidden");
    document.getElementById("reports-ledger-detail")?.classList.remove("hidden");
    const back = document.getElementById("reports-detail-back");
    if (back) back.textContent = `← ${backLabel}`;
    renderLedgerDetail();
    App.updateGlobalBack?.();
  }

  function backFromLedger() {
    ledgerDetail = null;
    document.getElementById("reports-ledger-detail")?.classList.add("hidden");
    document.getElementById("reports-hub")?.classList.remove("hidden");
    loadChip();
    App.updateGlobalBack?.();
  }

  function setHideVoids(on) {
    hideVoids = !!on;
    if (ledgerDetail) renderLedgerDetail();
  }

  function ledgerRowIsVoid(e) {
    const status = String(e.status || e.details?.status || "").toLowerCase();
    if (status === "voided" || status === "cancelled") return true;
    const type = String(e.entry_type || e.event_type || e.action || "").toLowerCase();
    if (type.includes("reversal") || type === "order_cancelled" || type.includes("void")) return true;
    if (e.reversed || e.voided_at || e.details?.reversed) return true;
    const title = String(e.title || e.description || e.detail || e.notes || "").toLowerCase();
    if (title.startsWith("cancelled") || title.startsWith("void")) return true;
    return false;
  }

  function realLedgerEntries(entries) {
    const list = entries || [];
    if (!hideVoids) return list;
    const reversed = new Set();
    for (const e of list) {
      if (e.reverses_entry_id) reversed.add(e.reverses_entry_id);
    }
    const kept = list.filter(e => !ledgerRowIsVoid(e) && !reversed.has(e.id));
    const chrono = [...kept].sort((a, b) => {
      const da = String(a.value_date || a.created_at || "");
      const db = String(b.value_date || b.created_at || "");
      if (da !== db) return da < db ? -1 : 1;
      return (Number(a.id) || 0) - (Number(b.id) || 0);
    });
    let run = 0;
    const stamped = new Map();
    for (const e of chrono) {
      run += Number(e.signed_amount ?? e.amount ?? 0);
      stamped.set(e.id, Math.round(run * 100) / 100);
    }
    return kept.map(e => (e.signed_amount != null || e.amount != null) && stamped.has(e.id)
      ? { ...e, running_balance: stamped.get(e.id) }
      : e);
  }

  function voidFilterBar() {
    return `<label style="display:inline-flex;gap:6px;align-items:center;margin:0 0 12px;font-size:13px;">
      <input type="checkbox" ${hideVoids ? "checked" : ""} onchange="Reports.setHideVoids(this.checked)" />
      Real entries only
    </label>`;
  }

  function foldReportName(text) {
    return String(text || "").toLowerCase().replace(/mohammad|mohammed|mohd/g, "mohm");
  }

  async function openAgentLedger(id) {
    backLabel = "Back";
    ctx.showLoading?.();
    try {
      const data = await ctx.api(`/commission-agents/${id}`, {}, 0);
      const goods = data.goods || [];
      const entries = [];
      for (const entry of data.ledger || []) {
        const lines = entry.bill_number
          ? goods.filter(g => g.bill_number === entry.bill_number && g.party_name === entry.party_name)
          : [];
        if (!lines.length) {
          entries.push(entry);
          continue;
        }
        lines.forEach((g, i) => entries.push({
          ...entry,
          date: i ? "" : entry.date,
          bill_number: i ? "" : entry.bill_number,
          party_name: i ? "" : entry.party_name,
          item: g.item,
          qty: g.qty,
          line_amount: g.amount,
          balance: i ? "" : entry.balance,
        }));
      }
      ledgerDetail = {
        party_type: "agent",
        party_label: data.name,
        outstanding: data.outstanding,
        entries,
      };
      showDetail();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function renderLedgerDetail() {
    const hero = document.getElementById("reports-ledger-hero");
    const body = document.getElementById("reports-ledger-body");
    if (!ledgerDetail || !body) return;
    const d = ledgerDetail;
    if (hero) {
      const badges = [
        d.outstanding != null ? `<span class="badge badge-amber">${fmtPrice(d.outstanding)}</span>` : "",
        d.quantity_on_hand != null ? `<span class="badge badge-blue">On hand ${d.quantity_on_hand}</span>` : "",
        d.activity_count != null ? `<span class="badge badge-blue">${d.activity_count} activities</span>` : "",
      ].filter(Boolean).join(" ");
      hero.innerHTML = HubUI.pageHero({
        title: d.party_label || d.label || "Ledger",
        sub: d.party_type || "ledger",
        actionsHtml: `${badges}
          <button type="button" class="btn btn-secondary btn-sm" onclick="Reports.printCurrent()">Print</button>
          <button type="button" class="btn btn-secondary btn-sm" onclick="Reports.exportCurrentExcel()">Excel</button>`,
      });
    }
    if (d.party_type === "agent") {
      const entries = d.entries || [];
      body.innerHTML = entries.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Date</th><th>Bill</th><th>Party</th><th>Item</th><th>Qty</th><th>Amount</th><th>Balance</th>
      </tr></thead><tbody>
        ${entries.map(e => `<tr>
          <td>${ctx.esc(e.date || "")}</td>
          <td>${ctx.esc(e.bill_number || e.entry_type || "")}</td>
          <td>${ctx.esc(e.party_name || "")}</td>
          <td>${ctx.esc(e.item || e.description || "")}</td>
          <td>${e.qty ?? ""}</td>
          <td>${ctx.esc(e.line_amount || e.amount || "")}</td>
          <td>${ctx.esc(e.balance || "")}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("Empty ledger", "No entries yet.");
      return;
    }
    if (d.party_type === "staff") {
      const entries = realLedgerEntries(d.entries || []);
      body.innerHTML = voidFilterBar() + (entries.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>When</th><th>Action</th><th>What</th><th>Detail</th>
      </tr></thead><tbody>
        ${entries.map(e => `<tr>
          <td style="font-size:12px;">${e.created_at ? new Date(e.created_at).toLocaleString() : "—"}</td>
          <td>${ctx.esc(e.action || "—")}</td>
          <td>${ctx.esc([e.entity_type, e.entity_label || e.entity_id].filter(Boolean).join(" · ") || "—")}</td>
          <td style="color:var(--muted);font-size:13px;">${ctx.esc(e.detail || "—")}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No activity", "This person has no logged actions yet."));
      return;
    }
    if (d.party_type === "product") {
      const rows = d.entries || [];
      body.innerHTML = Stock.ledgerTableHtml
        ? `<p style="font-size:12px;color:var(--muted);margin:0 0 8px;">Click a row to open that bill.</p>${Stock.ledgerTableHtml(rows)}`
        : empty("No stock moves", "No ledger lines for this product.");
      return;
    }
    const entries = d.party_type === "expense" ? (d.entries || []) : realLedgerEntries(d.entries || []);
    body.innerHTML = `
      <div class="fin-hub-strip" style="margin-bottom:16px;">
        ${d.opening_total != null ? `<div class="fin-stat"><span class="fin-stat-label">Opening</span><strong>${fmtPrice(d.opening_total)}</strong></div>` : ""}
        ${d.bill_total != null ? `<div class="fin-stat"><span class="fin-stat-label">In / Bills</span><strong>${fmtPrice(d.bill_total)}</strong></div>` : ""}
        ${d.payment_total != null ? `<div class="fin-stat"><span class="fin-stat-label">Out / Paid</span><strong>${fmtPrice(d.payment_total)}</strong></div>` : ""}
        ${d.credit_total != null ? `<div class="fin-stat"><span class="fin-stat-label">Credits</span><strong>${fmtPrice(d.credit_total)}</strong></div>` : ""}
        ${d.debit_note_total != null ? `<div class="fin-stat"><span class="fin-stat-label">Debit notes</span><strong>${fmtPrice(d.debit_note_total)}</strong></div>` : ""}
        ${d.outstanding != null ? `<div class="fin-stat"><span class="fin-stat-label">Net</span><strong>${fmtPrice(d.outstanding)}</strong></div>` : ""}
      </div>
      ${voidFilterBar()}
      ${entries.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Date</th><th>Type</th><th>Description</th><th>Amount</th><th>Balance</th>
      </tr></thead><tbody>
        ${[...entries].reverse().map(e => `<tr>
          <td style="font-size:12px;">${ctx.esc(e.value_date || e.display_date || "—")}</td>
          <td><span class="badge badge-blue">${ctx.esc(e.entry_type)}</span></td>
          <td>${ctx.esc(e.description || "—")}</td>
          <td>${fmtPrice(e.signed_amount || e.amount)}</td>
          <td>${e.running_balance != null ? fmtPrice(e.running_balance) : "—"}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("Empty ledger", "No entries yet.")}`;
  }

  function openDoc(docType, id) {
    if (docType === "sales_bill") { BillSeries?.openBill?.(id); return; }
    if (docType === "purchase_bill") { Stock?.openReceiptDetail?.(id); return; }
  }

  async function shareAgeing(print) {
    const side = ageingSide === "ap" ? "ap" : "ar";
    try {
      await DocShare.openPdf(`/share/ageing/pdf?side=${side}`, {
        print: !!print,
        filename: `ageing_${side}.pdf`,
      });
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function waAgeing() {
    const side = ageingSide === "ap" ? "ap" : "ar";
    const phone = prompt("WhatsApp phone (10 digits / with country code):");
    if (!phone) return;
    ctx.showLoading?.();
    try {
      const res = await DocShare.whatsapp({ kind: "ageing", side, phone, caption: `Ageing ${side.toUpperCase()}` });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function toggleVendorDcu(on) {
    includeDcu = !!on;
    loadChip();
  }

  function downloadVendorOrderCsv() {
    const rows = vendorOrderRows || [];
    if (!rows.length) return ctx.toast?.("Nothing to download", "error");
    const header = ["Item no.", "Company no.", "Company name", "Category", "No. of invoices", "Inward qty", "Outward qty", "Closing qty", "Purchase rate", "Closing value", "Last inward date", "Closing / inward %"];
    const lines = [header.join(",")];
    for (const row of rows) {
      const cells = [row.item_no, row.company_no, row.company_name, row.category, row.invoices, row.inward_qty, row.outward_qty, row.closing_qty, row.purchase_rate, row.closing_value, row.last_inward_date || "", row.stock_ratio || ""];
      lines.push(cells.map(value => `"${String(value ?? "").replace(/"/g, '""')}"`).join(","));
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `vendor-order-report-${fromDate || "all"}-${toDate || "all"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function confirmedQuery() {
    const params = new URLSearchParams();
    if (datePreset !== "all") {
      if (fromDate) params.set("from_date", fromDate);
      if (toDate) params.set("to_date", toDate);
    }
    return params.toString();
  }

  async function downloadConfirmedPdf() {
    const q = confirmedQuery();
    const label = datePreset === "all" ? "all" : (fromDate || toDate || "today");
    try {
      await DocShare.openPdf(`/reports/confirmed-orders/pdf${q ? "?" + q : ""}`, { filename: `confirmed-orders-${label}.pdf` });
    } catch (e) { ctx.toast(e.message, "error"); }
  }

  async function renderConfirmedOrders(body) {
    const qstr = confirmedQuery();
    const data = await ctx.api(`/reports/confirmed-orders${qstr ? "?" + qstr : ""}`, {}, 0);
    const q = hubSearch.trim().toLowerCase();
    const orders = (data.orders || []).filter(order => {
      if (!q) return true;
      const items = (order.lines || []).map(l => l.item_no).join(" ");
      return [order.party, order.party_number, order.city, order.marking, order.placement_id, items].join(" ").toLowerCase().includes(q);
    });
    const period = data.on || (datePreset === "all" ? "All dates" : "");
    const bands = ["#ffffff", "#f8fafc"];
    const html = orders.map((order, i) => {
      const bg = bands[i % 2];
      const city = order.city ? ` · ${ctx.esc(order.city)}` : "";
      const head = `<tr style="background:${bg};">
        <td style="font-weight:800;">${order.party_number ?? ""}</td>
        <td style="font-weight:800;">${ctx.esc(order.party || "")}${city}</td>
        <td style="color:#b91c1c;font-weight:700;">${ctx.esc(order.marking || "")}</td>
        <td style="font-weight:800;">#${order.placement_id}</td>
        <td></td><td></td><td></td>
      </tr>`;
      const lines = (order.lines || []).map(line => `<tr style="background:${bg};">
        <td></td>
        <td style="padding-left:28px;color:#334155;">${ctx.esc(line.item_no)}</td>
        <td></td><td></td>
        <td>${line.qty}</td>
        <td>${ctx.esc(line.rate)}</td>
        <td></td>
      </tr>`).join("");
      return head + lines;
    }).join("");
    body.innerHTML = `
      <h2 class="report-print-title" style="position:absolute;left:-9999px;">Confirmed orders · ${ctx.esc(period)}</h2>
      <div style="display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin:0 0 12px;">
        <button type="button" class="btn btn-secondary btn-sm" onclick="Reports.downloadConfirmedPdf()">PDF</button>
        <button type="button" class="btn btn-secondary btn-sm" onclick="Reports.printCurrent()">Print</button>
        <button type="button" class="btn btn-secondary btn-sm" onclick="Reports.exportCurrentExcel()">Excel</button>
        <span style="color:var(--muted);font-size:13px;">${orders.length} order${orders.length === 1 ? "" : "s"} · ${ctx.esc(period)}</span>
      </div>
      ${orders.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Party no.</th><th>Party</th><th>Marking</th><th>Order</th><th>Qty</th><th>Rate</th><th></th>
      </tr></thead><tbody>${html}</tbody></table></div>` : empty("No confirmed orders", "Choose another date, or All.")}`;
  }

  async function renderVendorOrderReport(body) {
    const year = stockYear || "2026-27";
    const params = new URLSearchParams();
    if (fromDate) params.set("from_date", fromDate);
    if (toDate) params.set("to_date", toDate);
    params.set("year_group", year);
    if (includeDcu) params.set("include_dcu", "true");
    const data = await ctx.api(`/reports/vendor-orders?${params.toString()}`, {}, 0);
    const q = hubSearch.trim().toLowerCase();
    const items = (data.items || []).filter(it => {
      if (!q) return true;
      return [it.item_no, it.company_no, it.company_name, it.category].join(" ").toLowerCase().includes(q);
    });
    vendorOrderRows = items;
    const period = data.period || "";
    body.innerHTML = `
      <h2 class="report-print-title" style="position:absolute;left:-9999px;">Vendor order report · ${ctx.esc(year)} · ${ctx.esc(period)}</h2>
      <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:0 0 12px;">
        <label style="display:inline-flex;align-items:center;gap:6px;font-size:13px;">
          <input type="checkbox" ${includeDcu ? "checked" : ""} onchange="Reports.toggleVendorDcu(this.checked)" />
          Include DCU
        </label>
        <button type="button" class="btn btn-secondary btn-sm" onclick="Reports.downloadVendorOrderCsv()">Download CSV</button>
        <span style="color:var(--muted);font-size:13px;">${ctx.esc(year)} · ${ctx.esc(period)} · DCU is left out unless you tick it</span>
      </div>
      ${items.length ? `<div class="card table-wrap"><table class="data"><thead><tr>
        <th>Item no.</th><th>Company no.</th><th>Company name</th><th>Category</th><th>Invoices</th>
        <th>Inward</th><th>Outward</th><th>Closing</th><th>Purchase rate</th><th>Closing value</th><th>Last inward</th><th>Closing / inward %</th>
      </tr></thead><tbody>
        ${items.map(it => `<tr>
          <td><strong>${ctx.esc(it.item_no)}</strong></td>
          <td>${ctx.esc(it.company_no)}</td>
          <td>${ctx.esc(it.company_name)}</td>
          <td>${ctx.esc(it.category)}</td>
          <td>${it.invoices}</td>
          <td>${ctx.esc(it.inward_qty)}</td>
          <td>${ctx.esc(it.outward_qty)}</td>
          <td>${ctx.esc(it.closing_qty)}</td>
          <td>${ctx.esc(it.purchase_rate)}</td>
          <td>${ctx.esc(it.closing_value)}</td>
          <td>${ctx.esc(it.last_inward_date || "")}</td>
          <td>${ctx.esc(it.stock_ratio || "")}</td>
        </tr>`).join("")}
      </tbody></table></div>` : empty("No items", "Change the dates or include DCU.")}`;
  }

