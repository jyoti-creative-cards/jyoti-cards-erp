  function pulseBars(pulse) {
    const sales = Number(pulse.sales_billed) || 0;
    const cashIn = Number(pulse.cash_in) || 0;
    const cashOut = Number(pulse.cash_out) || 0;
    const moneyMax = Math.max(sales, cashIn, cashOut, 1);
    const rows = [
      { label: "Sales", value: fmtPrice(sales), pct: barPct(sales, moneyMax), tone: "sales", sub: `${pulse.sales_count || 0} bill${(pulse.sales_count || 0) === 1 ? "" : "s"}` },
      { label: "Cash in", value: fmtPrice(cashIn), pct: barPct(cashIn, moneyMax), tone: "in", sub: "Collected" },
      { label: "Cash out", value: fmtPrice(cashOut), pct: barPct(cashOut, moneyMax), tone: "out", sub: "Vendor payments" },
    ];
    return `<div class="home-pulse-bars">
      ${rows.map(r => `
        <div class="home-pulse-row">
          <div class="home-pulse-meta">
            <span class="home-pulse-label">${r.label}</span>
            <strong class="home-pulse-val">${r.value}</strong>
          </div>
          <div class="home-pulse-track" aria-hidden="true"><span class="home-pulse-fill is-${r.tone}" style="width:${r.pct}%"></span></div>
          <span class="home-pulse-sub">${ctx.esc(r.sub)}</span>
        </div>
      `).join("")}
    </div>
    <div class="home-pulse-foot">
      <span>${pulse.purchase_count || 0} purchase${(pulse.purchase_count || 0) === 1 ? "" : "s"} today</span>
      ${(pulse.returns_today || 0) > 0 ? `<span>· ${pulse.returns_today} return${pulse.returns_today === 1 ? "" : "s"}</span>` : ""}
    </div>`;
  }

  function dueRow(item, side) {
    const settle = side === "ar"
      ? `App.showView('money');Finance.openCustomerAr(${item.id},{settle:true})`
      : `App.showView('money');Finance.openVendorAp(${item.id},{settle:true})`;
    const open = side === "ar"
      ? `App.showView('money');Finance.openCustomerAr(${item.id})`
      : `App.showView('money');Finance.openVendorAp(${item.id})`;
    return `<button type="button" class="home-due-row" onclick="${open}">
      <span class="home-due-name">${ctx.esc(item.label)}</span>
      <span class="home-due-amt">${fmtPriceExact(item.outstanding)}</span>
      <span class="home-due-go" onclick="event.stopPropagation();${settle}">${side === "ar" ? "Collect" : "Pay"}</span>
    </button>`;
  }

  function relativeTime(iso) {
    if (!iso) return "";
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return "";
    const mins = Math.round((Date.now() - t) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  }

