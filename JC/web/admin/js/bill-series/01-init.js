  function init(context) { ctx = context; }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function canWrite() {
    return !!ctx.isAdmin?.();
  }

  function statusPill(s) {
    const exhausted = s.current_num >= s.end_num;
    if (exhausted) return HubUI.pill("Exhausted", "warn");
    if (s.is_active) return HubUI.pill("Active", "ok");
    return HubUI.pill("Inactive", "muted");
  }

  function usedCount(s) {
    if (s.current_num < s.start_num) return 0;
    return s.current_num - s.start_num + 1;
  }

  function totalCapacity(s) {
    return s.end_num - s.start_num + 1;
  }

  function setListBack() {
    const back = document.getElementById("setup-billseries-back");
    if (back) {
      back.textContent = "← Back to Setup";
      back.onclick = () => App.showSetupHub();
    }
    document.getElementById("setup-billseries-hero")?.classList.remove("hidden");
  }

  function setDetailBack() {
    const back = document.getElementById("setup-billseries-back");
    if (back) {
      back.textContent = "← Bill series";
      back.onclick = () => load();
    }
    document.getElementById("setup-billseries-hero")?.classList.add("hidden");
  }

  async function load() {
    currentSeries = null;
    setListBack();
    ctx.showLoading?.();
    try {
      seriesList = await ctx.api("/bill-series", {}, 0);
      if (!Array.isArray(seriesList)) seriesList = [];
      const btn = document.getElementById("billseries-new-btn");
      if (btn) btn.classList.toggle("hidden", !canWrite());
      renderList();
      const count = document.getElementById("hub-billseries-count");
      if (count) count.textContent = `${seriesList.length} series`;
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function setSearch(val) {
    searchQ = val || "";
    renderList();
  }

  function filtered() {
    const q = searchQ.trim().toLowerCase();
    if (!q) return seriesList;
    return seriesList.filter(s =>
      String(s.name || "").toLowerCase().includes(q)
      || String(s.prefix || "").toLowerCase().includes(q)
    );
  }

  function renderList() {
    const el = document.getElementById("bill-series-root");
    if (!el) return;
    const prev = document.getElementById("bs-search");
    const caret = prev && document.activeElement === prev
      ? { start: prev.selectionStart, end: prev.selectionEnd }
      : null;
    const write = canWrite();
    const list = filtered();

    if (!seriesList.length) {
      el.innerHTML = HubUI.emptyState({
        title: "No bill series yet",
        sub: "Create a number range before issuing customer bills.",
        ctaHtml: write ? `<button class="btn btn-primary btn-lg" onclick="BillSeries.openWizard()">+ New series</button>` : "",
      });
      return;
    }

    el.innerHTML = `
      <div class="setup-search-slot">
        ${HubUI.searchBar({
          id: "bs-search",
          value: searchQ,
          placeholder: "Search series…",
          oninput: "BillSeries.setSearch(this.value)",
        })}
      </div>
      ${!list.length
        ? HubUI.emptyState({ title: "No matches", sub: "Clear search." })
        : `<div class="ord-card-list">${list.map(s => {
          const used = usedCount(s);
          const cap = totalCapacity(s);
          const left = cap - used;
          const pct = cap ? Math.round((used / cap) * 100) : 0;
          return HubUI.partyCard({
            title: s.name,
            meta: `Prefix <code>${ctx.esc(s.prefix)}</code> · ${s.start_num}–${s.end_num} · ${left} left
              <div class="setup-series-bar" style="margin-top:8px;"><div class="setup-series-fill" style="width:${pct}%"></div></div>`,
            pillHtml: statusPill(s),
            primaryLabel: "Open",
            primaryOnclick: `BillSeries.openSeries(${s.id})`,
            moreItems: write ? [{ label: "Delete", onclick: `BillSeries.deleteSeries(${s.id})`, danger: true }] : [],
            rowOnclick: `BillSeries.openSeries(${s.id})`,
            canWrite: true,
          });
        }).join("")}</div>`}`;
    if (caret) {
      const el = document.getElementById("bs-search");
      if (el) {
        el.focus();
        try { el.setSelectionRange(caret.start, caret.end); } catch (_) {}
      }
    }
  }

