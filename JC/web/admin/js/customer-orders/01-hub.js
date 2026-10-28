  function isTodayMode() {
    return hubMode === "queue" || hubMode === "needs_action" || hubMode === "today";
  }

  function selectedListDay() {
    return document.getElementById("co-print-day")?.value || "";
  }

  function dayParam() {
    const picked = selectedListDay();
    if (picked && !(isTodayMode() && picked === localToday())) return picked;
    return isTodayMode() ? "today" : "all";
  }

  function ensurePrintDay() {
    const input = document.getElementById("co-print-day");
    if (input && !input.value && isTodayMode()) input.value = localToday();
  }

  function setPrintDay(value) {
    const input = document.getElementById("co-print-day");
    if (input) input.value = value || "";
    hubExpandedCustomerId = null;
    hubExpandCache = {};
    syncHubChrome();
    if (isDispatchBucket()) loadDispatch();
    else loadList();
  }

  function isDispatchBucket() {
    return currentBucket === "dispatch";
  }

  /** Jump to Dispatch stage (keeps Today/Past date scope). */
  function goToDispatch() {
    closeSlidePanel();
    currentBucket = "dispatch";
    dispatchStatus = "pending";
    hubSearch = "";
    hubExpandedCustomerId = null;
    hubExpandCache = {};
    syncHubChrome();
    loadDispatch();
    App.updateGlobalBack?.();
  }

  function customerActionOf(o) {
    return (o.total_quantity || 0) > 0 ? "to_bill" : "other";
  }

  let offlineStep = 1;
  let offlineCustomerId = null;
  let offlineCustomerName = "";
  let offlineCustomerSearch = "";
  let offlineLines = [];
  let offlineSearchQuery = "";
  let focusQtyProductId = null;
  let offlineSearchResults = [];
  let offlineSearchPending = false;
  let offlineProductTimer = null;
  let offlineCustomerTimer = null;
  let offlinePicked = null;
  let billEditSearchPending = false;
  let billEditTimer = null;
  let offlineNotes = "";
  let offlinePlacedOn = "";
  let offlinePreview = null;
  let offlineBusy = false;
  let offlineConfirmDuplicate = false;
  let offlineCustomers = [];
  let offlineEditPlacementId = null;
  let offlineSelectedDetail = null; // full customer detail with outstanding/credit
  let billDate = "";

  function localToday() {
    const n = new Date();
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
  }

  function init(context) {
    ctx = context;
    ensurePrintDay();
  }

  function syncHubChrome() {
    const chips = document.getElementById("co-bucket-bar");
    const actionHost = document.getElementById("co-action-chips");
    const today = isTodayMode();
    const dispatch = isDispatchBucket();
    chips?.classList.remove("hidden");
    OrdersUI.syncModeButtons("#co-hub-mode", today ? "queue" : "past");
    OrdersUI.syncStageChips("#co-bucket-bar", currentBucket);
    if (dispatch) {
      OrdersUI.actionChips({
        hostId: "co-action-chips",
        active: dispatchStatus,
        onclickFn: "CustomerOrders.setDispatchStatus",
        items: [
          { id: "pending", label: "Pending pick", count: dispatchStatus === "pending" ? dispatchParcels.length : undefined },
          { id: "picked", label: "Picked" },
          { id: "all", label: "All" },
        ],
      });
    } else if (actionHost) {
      actionHost.innerHTML = "";
      actionHost.classList.add("hidden");
    }
    const title = document.getElementById("co-list-title");
    const hint = document.getElementById("co-list-hint");
    if (title) {
      const stage = BUCKET_LABELS[currentBucket] || "Orders";
      const picked = selectedListDay();
      const specific = picked && picked !== localToday();
      if (dispatch) {
        const sub = dispatchStatus === "picked" ? "Picked" : dispatchStatus === "all" ? "All parcels" : "Pending pick";
        title.textContent = specific
          ? `${ctx.fmtDay?.(picked) || picked} · ${sub}`
          : (today ? `Today · ${sub}` : sub);
        if (hint) hint.textContent = BUCKET_HINTS["dispatch"] || "";
      } else if (specific) {
        title.textContent = `${ctx.fmtDay?.(picked) || picked} · ${stage}`;
        if (hint) hint.textContent = "";
      } else {
        const showToday = today && !NOT_DAY_SCOPED_BUCKETS.includes(currentBucket);
        title.textContent = showToday ? `Today · ${stage}` : stage;
        if (hint) hint.textContent = today ? (BUCKET_HINTS[currentBucket] || "") : "";
      }
    }
    const searchSlot = document.getElementById("co-hub-search-slot");
    if (searchSlot) {
      const agentOpts = [
        `<option value="">All agents</option>`,
        ...dispatchAgents.map(a =>
          `<option value="${a.id}" ${String(dispatchAgentId) === String(a.id) ? "selected" : ""}>${ctx.esc(a.name)}</option>`
        ),
      ].join("");
      searchSlot.innerHTML = dispatch
        ? `<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;width:100%;">
            <select class="input" style="max-width:200px;" onchange="CustomerOrders.setDispatchAgent(this.value)">
              ${agentOpts}
            </select>
            ${HubUI.searchBar({
              id: "co-hub-search",
              value: hubSearch,
              placeholder: "Search customer, bill…",
              oninput: "CustomerOrders.setHubSearch(this.value)",
            })}
          </div>`
        : `<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;width:100%;">
            ${HubUI.searchBar({
              id: "co-hub-search",
              value: hubSearch,
              placeholder: currentBucket === "open" ? "Customer, item, vendor item, category…" : currentBucket === "billed" ? "Search customer, bill no…" : "Search customer…",
              oninput: "CustomerOrders.setHubSearch(this.value)",
            })}
            ${currentBucket === "open" ? `<input class="input" style="width:110px;" inputmode="decimal" placeholder="Min price" value="${ctx.esc(hubPriceMin)}" oninput="CustomerOrders.setHubPrice('min', this.value)" />
            <input class="input" style="width:110px;" inputmode="decimal" placeholder="Max price" value="${ctx.esc(hubPriceMax)}" oninput="CustomerOrders.setHubPrice('max', this.value)" />` : ""}
            <div class="ord-mode-toggle" style="flex:0 0 auto;" role="tablist" aria-label="Sort order">
              <button type="button" class="ord-mode-btn${hubSort === "latest" ? " active" : ""}" onclick="CustomerOrders.setHubSort('latest')">Latest first</button>
              <button type="button" class="ord-mode-btn${hubSort === "oldest" ? " active" : ""}" onclick="CustomerOrders.setHubSort('oldest')">Oldest first</button>
            </div>
          </div>`;
    }
  }

  function goCollectPayment(customerId) {
    const cid = customerId || detailCustomerId;
    if (!cid) return;
    App.closeDetail?.();
    App.showView("money");
    Finance.openCustomerAr?.(cid, { settle: true });
  }

  function updateDetailPrimary() {
    // No-op: action buttons are now embedded in renderDetail() body content
  }

  function updateActionButtons(view) {
    if (view === "detail") updateDetailPrimary();
  }

  function setHubMode(mode) {
    // Legacy: setHubMode('dispatch') → Dispatch stage
    if (mode === "dispatch") {
      goToDispatch();
      return;
    }
    if (mode === "browse" || mode === "past") hubMode = "past";
    else hubMode = "queue";
    const printDay = document.getElementById("co-print-day");
    if (printDay) printDay.value = hubMode === "past" ? "" : localToday();
    if (!PAST_BUCKETS.includes(currentBucket)) currentBucket = "open";
    hubExpandedCustomerId = null;
    hubExpandCache = {};
    hubSearch = "";
    syncHubChrome();
    loadList();
  }

  function setDispatchStatus(status) {
    dispatchStatus = ["pending", "picked", "all"].includes(status) ? status : "pending";
    loadDispatch();
  }

  function setDispatchAgent(id) {
    dispatchAgentId = id ? String(id) : "";
    loadDispatch();
  }

  function setQueueFilter() {
    /* removed — Today/Past share stage chips */
  }

  function setHubSearch(val) {
    hubSearch = val || "";
    hubExpandedCustomerId = null;
    if (isDispatchBucket()) renderDispatchList();
    else renderList();
  }

  function setHubPrice(which, val) {
    if (which === "max") hubPriceMax = val || "";
    else hubPriceMin = val || "";
    renderList();
  }

  function priceInRange(prices) {
    const min = hubPriceMin === "" ? null : Number(hubPriceMin);
    const max = hubPriceMax === "" ? null : Number(hubPriceMax);
    const hasMin = min != null && Number.isFinite(min);
    const hasMax = max != null && Number.isFinite(max);
    if (!hasMin && !hasMax) return true;
    return (prices || []).some(p => {
      const n = Number(p);
      if (!Number.isFinite(n)) return false;
      if (hasMin && n < min) return false;
      if (hasMax && n > max) return false;
      return true;
    });
  }

  function hubTime(o) {
    const raw = o.sort_at || o.updated_at || o.display_date || 0;
    const t = new Date(raw).getTime();
    return Number.isFinite(t) ? t : 0;
  }

  function sortHubOrders(list) {
    const dir = hubSort === "oldest" ? 1 : -1;
    return [...(list || [])].sort((a, b) => {
      const ta = hubTime(a);
      const tb = hubTime(b);
      if (ta !== tb) return (ta - tb) * dir;
      const ia = Number(a.id) || Number(a.customer_id) || 0;
      const ib = Number(b.id) || Number(b.customer_id) || 0;
      return (ia - ib) * dir;
    });
  }

  function linePriceOk(price) {
    return priceInRange([price]);
  }

  function confirmedOrderMatches(order, tokens, hasPrice) {
    const party = `${order.customer_name || ""} ${order.city_name || ""} ${order.party_number ?? ""}`.toLowerCase();
    const partyHit = tokens.length > 0 && tokens.every(t => party.includes(String(t).toLowerCase()));
    const lines = Array.isArray(order.search_lines) && order.search_lines.length
      ? order.search_lines
      : String(order.search_text || "").split("||").filter(Boolean).map(text => ({ text, price: "" }));
    const lineHit = lines.some(ln => {
      const text = String(ln.text || "").toLowerCase();
      const textOk = !tokens.length || tokens.every(t => text.includes(String(t).toLowerCase()));
      return textOk && (!hasPrice || linePriceOk(ln.price));
    });
    if (partyHit && hasPrice) return lines.some(ln => linePriceOk(ln.price));
    if (partyHit) return true;
    return lineHit;
  }

  function filterHubOrders(list) {
    let rows = list || [];
    const tokens = hubSearch.trim() ? OrdersUI.partySearchTokens(hubSearch) : [];
    const hasPrice = currentBucket === "open" && (hubPriceMin !== "" || hubPriceMax !== "");
    if (currentBucket === "open" && (tokens.length || hasPrice)) {
      return sortHubOrders(rows.filter(o => confirmedOrderMatches(o, tokens, hasPrice)));
    }
    if (!hubSearch.trim()) {
      return sortHubOrders(rows);
    }
    // Hub rows only have customer_name — still token-match; rank by name starts-with
    const ranked = OrdersUI.filterAndRankParties(
      rows.map(o => ({
        ...o,
        business_name: o.customer_name || o.business_name || "",
      })),
      hubSearch,
    );
    if (currentBucket !== "billed") return sortHubOrders(ranked);
    const seen = new Set(ranked.map(o => o.customer_id));
    const billHits = (list || []).filter(o => {
      if (seen.has(o.customer_id)) return false;
      const bills = o.bills || [];
      return tokens.every(t => bills.some(b => billNumberMatches(b.bill_number, t))
        || (!/^\d+$/.test(t) && String(o.customer_name || "").toLowerCase().includes(t))
        || (!/^\d+$/.test(t) && String(o.city_name || "").toLowerCase().includes(t))
        || (/^\d+$/.test(t) && String(o.party_number ?? "") === t));
    });
    return sortHubOrders([...ranked, ...billHits]);
  }

  function billNumberMatches(billNumber, token) {
    const n = String(billNumber || "").toLowerCase();
    const t = String(token || "").toLowerCase();
    if (!n || !t) return false;
    if (/^\d+$/.test(t)) {
      const tail = n.match(/(\d+)$/);
      return !!(tail && tail[1] === t);
    }
    return n.includes(t);
  }

  function setHubSort(val) {
    hubSort = val === "oldest" ? "oldest" : "latest";
    syncHubChrome();
    if (isDispatchBucket()) renderDispatchList();
    else renderList();
  }

  function addonsUnderHtml(addons, qtyScale) {
    const list = Array.isArray(addons) ? addons : [];
    if (!list.length) return "";
    const scale = Number(qtyScale) > 0 ? Number(qtyScale) : 1;
    return `<div class="co-addons">${list.map(a => {
      const per = Number(a.quantity) || 1;
      const total = per * scale;
      const label = a.name || a.our_product_id || "Add-on";
      const price = Number(a.selling_price);
      const priceBit = price > 0 ? ` · ₹${price} × ${total} = ₹${price * total}` : "";
      return `<div class="co-addon-row">+ ${ctx.esc(a.our_product_id || "")} · ${ctx.esc(label)} × ${total}${priceBit}</div>`;
    }).join("")}</div>`;
  }

  function markingBanner(note) {
    const text = String(note || "").trim();
    if (!text) return "";
    const lower = text.toLowerCase();
    if (lower === "order placed by admin (phone)" || lower === "offline order") return "";
    return `<div style="margin-top:6px;padding:8px 10px;background:#fee2e2;border:1px solid #dc2626;border-radius:6px;font-weight:700;font-size:15px;color:#b91c1c;">Marking: ${ctx.esc(text)}</div>`;
  }

  function orderMarkingsBlock(orders) {
    const html = (orders || []).map(order => markingBanner(order && order.customer_notes)).join("");
    if (!html) return "";
    return `<div style="margin:0 0 12px;">${html}</div>`;
  }

  function orderMarkingForProduct(orders, productId) {
    const html = (orders || [])
      .filter(order => (order.lines || []).some(ln => Number(ln.catalog_product_id) === Number(productId)))
      .map(order => markingBanner(order.customer_notes))
      .join("");
    return html;
  }

  function calcNetFromDisc(rate, discPct) {
    const r = Number(rate);
    const d = Number(discPct);
    if (!Number.isFinite(r) || r <= 0) return "";
    if (!Number.isFinite(d) || d <= 0) return String(r);
    const net = r * (1 - Math.min(100, Math.max(0, d)) / 100);
    return (Math.round(net * 100) / 100).toString();
  }

  function calcDiscFromNet(rate, netRate) {
    const r = Number(rate);
    const n = Number(netRate);
    if (!Number.isFinite(r) || r <= 0 || !Number.isFinite(n) || n < 0) return "";
    if (n >= r) return "0";
    const pct = ((r - n) / r) * 100;
    return (Math.round(pct * 100) / 100).toString();
  }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function thumb(_url) {
    return `<div class="vo-thumb vo-thumb-empty">—</div>`;
  }

  function setBucket(bucket) {
    // Stage only — do not flip Today/Past
    currentBucket = PAST_BUCKETS.includes(bucket) ? bucket : "open";
    hubExpandedCustomerId = null;
    hubExpandCache = {};
    hubSearch = "";
    syncHubChrome();
    loadList();
  }

