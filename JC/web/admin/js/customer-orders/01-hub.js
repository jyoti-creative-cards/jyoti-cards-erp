  function isTodayMode() {
    return hubMode === "queue" || hubMode === "needs_action" || hubMode === "today";
  }

  function dayParam() {
    return isTodayMode() ? "today" : "all";
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
  let offlineCustomers = [];
  let offlineEditPlacementId = null;
  let offlineSelectedDetail = null; // full customer detail with outstanding/credit
  let billDate = "";

  function localToday() {
    const n = new Date();
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
  }

  function init(context) { ctx = context; }

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
      if (dispatch) {
        const sub = dispatchStatus === "picked" ? "Picked" : dispatchStatus === "all" ? "All parcels" : "Pending pick";
        title.textContent = today ? `Today · ${sub}` : sub;
        if (hint) hint.textContent = BUCKET_HINTS["dispatch"] || "";
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
              placeholder: "Search customer…",
              oninput: "CustomerOrders.setHubSearch(this.value)",
            })}
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

  function filterHubOrders(list) {
    if (!hubSearch.trim()) {
      // No search — sort by recency (toggle), not OrdersUI's default party_number
      // order. party_number ordering is right for a customer directory, but wrong
      // here: a just-created order could land anywhere in a long numeric list,
      // making it look "missing" from the queue until you scroll to find it.
      return [...(list || [])].sort((a, b) => {
        const ta = new Date(a.updated_at || 0).getTime() || 0;
        const tb = new Date(b.updated_at || 0).getTime() || 0;
        return hubSort === "oldest" ? ta - tb : tb - ta;
      });
    }
    // Hub rows only have customer_name — still token-match; rank by name starts-with
    const ranked = OrdersUI.filterAndRankParties(
      (list || []).map(o => ({
        ...o,
        business_name: o.customer_name || o.business_name || "",
      })),
      hubSearch,
    );
    return ranked;
  }

  function setHubSort(val) {
    hubSort = val === "oldest" ? "oldest" : "latest";
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

