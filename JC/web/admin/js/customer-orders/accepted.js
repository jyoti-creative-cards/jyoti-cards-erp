/** Customer orders — Today/Past date scope + same stage chips */
const CustomerOrders = (() => {
  let ctx = {};
  let orders = [];
  let currentOrder = null;
  let currentBucket = "open"; // same stages for Today + Past
  let hubMode = "queue"; // queue (Today) | past — date scope only
  let hubSearch = "";
  let hubPriceMin = "";
  let hubPriceMax = "";
  let hubSort = "latest"; // latest | oldest — unfiltered hub-list order
  let createdByPick = [];
  let coExpandedId = null;
  let hubExpandedCustomerId = null;
  let hubExpandCache = {};
  let detailCustomerId = null;
  let dueCatalogs = [];
  let pickedCatalogs = {};

  let dispatchParcels = [];
  let dispatchAgents = [];
  let dispatchStatus = "pending"; // pending | picked | all
  let dispatchAgentId = ""; // "" = all agents

  let processStep = 1;
  let processContext = null;
  let billOnAgent = true;
  let processLines = [];
  let billableOrders = [];
  let selectedPlacementIds = [];
  let discountEnabled = false;
  let useOverallDiscount = false;
  let overallDiscount = "";
  let gstEnabled = false;
  let gstRate = "18";
  let freightAgents = [];
  let billSeries = [];
  let freightAgentId = "";
  let freightHandler = "";
  let freightCharges = "";
  let transportMode = "";
  let transportReceiptNumber = "";
  let packagingCharges = "";
  let additionalCharges = [{ name: "", amount: "" }];
  let billSeriesId = "";
  let customerNotes = "";
  let narration = "";
  let markEdit = null;
  let previewTotals = null;
  let processBusy = false;
  let forceCreditOverride = false;
  let editBillId = null;
  let editBillNumber = "";
  let billEditSearch = "";
  // catalog_product_id -> quantity_shipped as it stood when the edit wizard opened.
  // Used only to warn the user before a qty decrease restores stock + shrinks the order.
  let editBillOriginalQty = {};
  let billEditProducts = [];

  // Past stages — Dispatch is an ops stage (parcels), not a Today/Past peer.
  const PAST_BUCKETS = ["received", "open", "billed", "dispatch", "picked", "cancelled", "closed"];
  const BROWSE_BUCKETS = PAST_BUCKETS; // legacy alias
  // All backlog buckets (New/Confirmed/Billed) now day-scope consistently: day=today
  // shows only entries touched today, day=all shows full history — nothing is ever
  // lost, it just moves from Today to Past (see list_customer_orders on the backend).
  const NOT_DAY_SCOPED_BUCKETS = [];
  const BUCKET_LABELS = {
    needs_action: "Today",
    queue: "Today",
    summary: "Today",
    received: "New",
    open: "Confirmed",
    billed: "Billed",
    dispatch: "Dispatch",
    picked: "Picked",
    cancelled: "Cancelled",
    closed: "Done",
  };

  const BUCKET_HINTS = {
    received: "Review each order, edit if needed, then confirm →",
    open: "Goods being picked — create bill when ready. Edit if quantities change.",
    billed: "Bill sent — dispatch or collect payment first, then close.",
    dispatch: "Check the send-by details, then mark as picked.",
    picked: "Parcels already marked picked.",
    closed: "All settled.",
  };

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
    return currentBucket === "dispatch" || currentBucket === "picked";
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

  function billEditableToday(createdAt) {
    if (ctx.isAdmin?.()) return true;
    if (!createdAt) return false;
    const created = new Date(createdAt);
    if (Number.isNaN(created.getTime())) return false;
    const day = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Kolkata",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    return day.format(created) === day.format(new Date());
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
    if (actionHost) {
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
        title.textContent = specific
          ? `${ctx.fmtDay?.(picked) || picked} · ${stage}`
          : (today ? `Today · ${stage}` : stage);
        if (hint) hint.textContent = BUCKET_HINTS[currentBucket] || "";
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
            ${createdByFilterHtml(dispatchParcels)}
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
            ${createdByFilterHtml(orders)}
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

  function creatorNames(row) {
    const raw = row && row.created_by;
    const list = Array.isArray(raw) ? raw : (raw ? [raw] : []);
    return list.map(x => String(x || "").trim()).filter(Boolean);
  }

  function rowMatchesCreators(row) {
    if (!createdByPick.length) return true;
    const names = creatorNames(row).map(n => n.toLowerCase());
    return createdByPick.some(picked => names.includes(picked.toLowerCase()));
  }

  function toggleCreatedBy(name, on) {
    const key = String(name || "").trim();
    if (!key) return;
    if (on) {
      if (!createdByPick.some(n => n.toLowerCase() === key.toLowerCase())) createdByPick.push(key);
    } else {
      createdByPick = createdByPick.filter(n => n.toLowerCase() !== key.toLowerCase());
    }
    if (isDispatchBucket()) renderDispatchList();
    else renderList();
  }

  function createdByFilterHtml(rows) {
    const names = [];
    const seen = new Set();
    for (const row of rows || []) {
      for (const name of creatorNames(row)) {
        const key = name.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        names.push(name);
      }
    }
    for (const name of createdByPick) {
      if (!seen.has(name.toLowerCase())) names.push(name);
    }
    names.sort((a, b) => a.localeCompare(b));
    if (!names.length && !createdByPick.length) return "";
    const summary = createdByPick.length ? createdByPick.join(", ") : "Created by";
    const boxes = names.map(name => {
      const on = createdByPick.some(n => n.toLowerCase() === name.toLowerCase());
      return `<label style="display:flex;gap:8px;align-items:center;padding:4px 0;"><input type="checkbox" ${on ? "checked" : ""} onchange="CustomerOrders.toggleCreatedBy(this.value, this.checked)" value="${ctx.esc(name)}" /> ${ctx.esc(name)}</label>`;
    }).join("");
    return `<details style="position:relative;">
      <summary class="btn btn-secondary btn-sm" style="list-style:none;cursor:pointer;">${ctx.esc(summary)}</summary>
      <div style="position:absolute;z-index:20;background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:8px 12px;min-width:180px;box-shadow:0 8px 24px rgba(15,23,42,.12);">${boxes}</div>
    </details>`;
  }

  function filterHubOrders(list) {
    let rows = (list || []).filter(rowMatchesCreators);
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
    const billHits = rows.filter(o => {
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

  function tileMarkings(o) {
    const fromApi = Array.isArray(o && o.markings) ? o.markings : [];
    const fromBills = (Array.isArray(o && o.bills) ? o.bills : []).map(b => b && b.narration).filter(Boolean);
    const extra = o && o.narration ? [o.narration] : [];
    const all = [];
    const seen = new Set();
    for (const raw of [...fromApi, ...fromBills, ...extra]) {
      String(raw || "").split(" · ").forEach(part => {
        const text = part.trim();
        if (!text) return;
        const key = text.toLowerCase();
        if (seen.has(key)) return;
        seen.add(key);
        all.push(text);
      });
    }
    return all.map(text => markingBanner(text)).join("");
  }

  function markHistoryHtml(rows) {
    if (!rows || !rows.length) return `<p style="margin:12px 0 0;font-size:13px;color:var(--muted);">No history yet.</p>`;
    return `<div style="margin-top:14px;">${rows.map(r => {
      const when = r.created_at ? new Date(r.created_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" }) : "";
      return `<div style="padding:8px 0;border-top:1px solid #e2e8f0;"><div style="font-size:12px;color:var(--muted);">${ctx.esc(r.actor_name || "Staff")}${when ? " · " + ctx.esc(when) : ""}</div><div>${ctx.esc(r.body || "(cleared)")}</div></div>`;
    }).join("")}</div>`;
  }

  async function openTileMark(_kind, customerId, billIds) {
    const cid = Number(customerId);
    const bills = String(billIds || "");
    const billList = bills.split(",").filter(Boolean).map(Number);
    let text = "";
    if (currentBucket === "dispatch" || billList.length === 1) {
      const parcel = (dispatchParcels || []).find(p => String(p.bill_id) === String(billList[0] || bills));
      if (parcel) text = parcel.marking || "";
      if (!text && billList.length === 1) {
        const row = (orders || []).find(o => Number(o.customer_id) === cid);
        const chip = ((row && row.bills) || []).find(b => Number(b.bill_id) === billList[0]);
        text = (chip && chip.narration) || "";
      }
    } else {
      const row = (orders || []).find(o => Number(o.customer_id) === cid);
      text = (row && row.marking) || "";
    }
    const kind = billList.length === 1 ? "bill" : "order";
    const subject = billList.length === 1 ? String(billList[0]) : String(cid);
    let rows = [];
    try { rows = await ctx.api(`/text-events?kind=${kind}&subject=${encodeURIComponent(subject)}`, {}, 0) || []; }
    catch (e) { rows = []; }
    markEdit = {
      kind: "marking",
      customerId: cid,
      billIds: billList.length === 1 ? billList : [],
      text: text || "",
      key: "marking:" + cid + ":" + bills,
    };
    ctx.openDetail?.(
      "Marking",
      `<textarea id="co-mark-box" class="input" rows="5" style="width:100%;background:#fee2e2;border:1px solid #dc2626;font-weight:800;color:#b91c1c;">${ctx.esc(text || "")}</textarea>
      <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;">
        <button type="button" class="btn btn-primary" onclick="CustomerOrders.saveTileMark(false)">Save</button>
        <button type="button" class="btn btn-danger" onclick="CustomerOrders.saveTileMark(true)">Delete</button>
        <button type="button" class="btn btn-secondary" onclick="App.closeDetail?.()">Cancel</button>
      </div>
      ${markHistoryHtml(rows)}`,
      "",
      "sm"
    );
    setTimeout(() => document.getElementById("co-mark-box")?.focus(), 30);
  }

  function cancelTileMark() {
    markEdit = null;
    App.closeDetail?.();
  }

  async function saveTileMark(remove) {
    if (!markEdit) return;
    const text = remove ? "" : (document.getElementById("co-mark-box")?.value || "");
    const target = markEdit;
    App.closeDetail?.();
    ctx.showLoading?.();
    try {
      await ctx.api(`/customer-orders/customer/${target.customerId}/marking`, {
        method: "PATCH",
        body: JSON.stringify({ kind: "marking", text, bill_ids: target.billIds || [] }),
      }, 0);
      markEdit = null;
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/freight-agents");
      ctx.toast(remove ? "Marking deleted" : "Marking saved", "success");
      if (currentBucket === "dispatch") await loadDispatch();
      else await loadList(true);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function onlyMark(text) {
    const parts = String(text || "").split("·").map(part => part.trim()).filter(Boolean);
    return parts.length ? parts[parts.length - 1] : "";
  }

  function markStrip(text, customerId, billIds, label) {
    text = onlyMark(text);
    const bills = billIds || "";
    const box = "display:block;width:calc(100% - 28px);margin:8px 14px;padding:10px 12px;background:#fee2e2;border:1px solid #dc2626;border-radius:8px;font-weight:800;font-size:16px;color:#b91c1c;text-align:left;cursor:pointer;";
    const shown = label || (text ? `Marking: ${text}` : "Add marking");
    if (!text) {
      return `<button type="button" class="btn btn-secondary btn-sm" style="margin:8px 14px;" onclick="event.stopPropagation();CustomerOrders.openTileMark('marking',${customerId},'${bills}')">Add marking</button>`;
    }
    return `<button type="button" style="${box}" onclick="event.stopPropagation();CustomerOrders.openTileMark('marking',${customerId},'${bills}')">${ctx.esc(shown)}</button>`;
  }

  function tileMarkHtml(o) {
    const orderMark = markStrip((o && o.marking) || "", o.customer_id, "");
    const bills = (Array.isArray(o && o.bills) ? o.bills : [])
      .filter(b => b && b.narration && b.bill_id)
      .map(b => markStrip(b.narration, o.customer_id, String(b.bill_id), `Bill ${b.bill_number || b.bill_id}: ${onlyMark(b.narration)}`))
      .join("");
    return orderMark + bills;
  }

  function parcelMarkHtml(p) {
    return markStrip((p && p.marking) || "", p.customer_id, String(p.bill_id || ""));
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

  const dispatchDrafts = {};
  let pickedOpenId = null;
  const pickedStories = {};

  function pullDispatchDrafts() {
    for (const id of Object.keys(dispatchDrafts)) {
      const root = document.querySelector(`[data-dispatch="${id}"]`);
      if (!root) continue;
      const d = dispatchDrafts[id];
      const read = (field) => root.querySelector(`[data-field="${field}"]`);
      const mode = read("mode");
      if (mode) d.mode = mode.value;
      const agent = read("agent");
      if (agent) d.agent = agent.value;
      const picked = root.querySelector("[data-field=handler].btn-primary");
      if (picked) d.handler = picked.textContent.trim();
      const freight = read("freight");
      if (freight) d.freight = freight.value;
      const receipt = read("receipt");
      if (receipt) d.receipt = receipt.value;
      const packing = read("packing");
      if (packing) d.packing = packing.value;
      const marking = read("marking");
      if (marking) d.marking = marking.value;
      const pickSay = read("picksay");
      if (pickSay) d.pickNarration = pickSay.value;
      root.querySelectorAll("[data-field=cname]").forEach(el => {
        const row = d.charges[Number(el.dataset.i)];
        if (row) row.name = el.value;
      });
      root.querySelectorAll("[data-field=camt]").forEach(el => {
        const row = d.charges[Number(el.dataset.i)];
        if (row) row.amount = el.value;
      });
    }
  }

  function draftFor(p) {
    const id = String(p.bill_id);
    if (!dispatchDrafts[id]) {
      const charges = (p.additional_charges || []).map(c => ({ name: c.name || "", amount: String(c.amount || "") }));
      dispatchDrafts[id] = {
        mode: p.transport_mode || (p.freight_agent_id ? "bus" : "self_pickup"),
        agent: p.freight_agent_id || "",
        handler: p.freight_handler || "",
        freight: p.freight_charges && Number(p.freight_charges) ? String(p.freight_charges) : "",
        receipt: p.transport_receipt_number || "",
        packing: p.packaging_charges && Number(p.packaging_charges) ? String(p.packaging_charges) : "",
        charges: charges.length ? charges : [{ name: "", amount: "" }],
        marking: p.marking || "",
        pickNarration: "",
      };
    }
    return dispatchDrafts[id];
  }

  function parcelAgentIsVishnu(agentId) {
    const hit = (dispatchAgents || []).find(a => String(a.id) === String(agentId));
    return !!(hit && String(hit.name || "").toLowerCase().includes("vishnu"));
  }

  function setParcelAgent(billId, value) {
    pullDispatchDrafts();
    const d = dispatchDrafts[billId];
    if (!d) return;
    d.agent = value;
    if (!parcelAgentIsVishnu(value)) d.handler = "";
    renderDispatchList();
  }

  function setParcelHandler(billId, name) {
    pullDispatchDrafts();
    const d = dispatchDrafts[billId];
    if (!d) return;
    d.handler = name;
    renderDispatchList();
    ctx.api(`/freight-agents/parcels/${billId}/handler`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }, 0).then(() => {
      const row = dispatchParcels.find(p => String(p.bill_id) === String(billId));
      if (row) row.freight_handler = name;
    }).catch(e => ctx.toast(e.message || "Could not save the person", "error"));
  }

  function setDispatchMode(billId, value) {
    pullDispatchDrafts();
    if (dispatchDrafts[billId]) dispatchDrafts[billId].mode = value;
    renderDispatchList();
  }

  function addDispatchCharge(billId) {
    pullDispatchDrafts();
    dispatchDrafts[billId]?.charges.push({ name: "", amount: "" });
    renderDispatchList();
  }

  async function loadDispatch() {
    ctx.showLoading?.();
    try {
      const q = new URLSearchParams({ status: currentBucket === "picked" ? "picked" : "pending", day: dayParam() });
      if (dispatchAgentId) q.set("agent_id", dispatchAgentId);
      const [parcels, agents] = await Promise.all([
        ctx.api(`/freight-agents/parcels?${q}`, {}, 0),
        ctx.api("/freight-agents", {}, 0).catch(() => dispatchAgents),
      ]);
      dispatchParcels = Array.isArray(parcels) ? parcels : [];
      dispatchAgents = Array.isArray(agents) ? agents : [];
      syncHubChrome();
      renderDispatchList();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function filterDispatchParcels(list) {
    const rows = (list || []).filter(rowMatchesCreators);
    const q = hubSearch.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(p => {
      const hay = [
        p.customer_label, p.bill_number, p.customer_city, p.customer_phone,
        p.freight_agent_name, String(p.bill_id || ""), p.transport_mode, p.transport_receipt_number,
      ].join(" ").toLowerCase();
      return hay.includes(q);
    });
  }

  function dispatchFormHtml(p) {
    const d = draftFor(p);
    const agents = (dispatchAgents || []).map(a =>
      `<option value="${a.id}" ${String(a.id) === String(d.agent) ? "selected" : ""}>${ctx.esc(a.name)}</option>`
    ).join("");
    const modeBits = d.mode === "bus" ? `
      <label class="label">Freight agent</label>
      <select class="input" data-field="agent" onchange="CustomerOrders.setParcelAgent(${p.bill_id}, this.value)"><option value="">—</option>${agents}</select>
      ${parcelAgentIsVishnu(d.agent) ? `<label class="label">Freight person</label>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;">
        ${["Vishnu", "Rahul", "Ganesh"].map(name => `<button type="button" class="btn ${d.handler === name ? "btn-primary" : "btn-secondary"} btn-sm" data-field="handler" onclick="CustomerOrders.setParcelHandler(${p.bill_id}, '${name}')">${name}</button>`).join("")}
      </div>` : ""}
      <label class="label">Freight (₹)</label>
      <input class="input" data-field="freight" value="${ctx.esc(d.freight)}">`
      : d.mode === "transport" ? `
      <label class="label">Transport (₹)</label>
      <input class="input" data-field="freight" value="${ctx.esc(d.freight)}">
      <label class="label">Receipt number</label>
      <input class="input" data-field="receipt" value="${ctx.esc(d.receipt)}">`
      : `<p style="margin:8px 0 0;font-size:13px;color:var(--muted);">Customer picks up.</p>`;
    const charges = d.charges.map((c, i) => `
      <div style="display:flex;gap:8px;margin-bottom:6px;">
        <input class="input" data-field="cname" data-i="${i}" placeholder="Name" value="${ctx.esc(c.name)}">
        <input class="input" data-field="camt" data-i="${i}" placeholder="₹" style="width:110px;" value="${ctx.esc(c.amount)}">
      </div>`).join("");
    return `<div data-dispatch="${p.bill_id}" style="margin-top:12px;padding-top:12px;border-top:1px solid #e2e8f0;">
      <label class="label">Send by</label>
      <select class="input" data-field="mode" onchange="CustomerOrders.setDispatchMode(${p.bill_id}, this.value)">
        <option value="bus" ${d.mode === "bus" ? "selected" : ""}>Bus / freight</option>
        <option value="transport" ${d.mode === "transport" ? "selected" : ""}>Transport</option>
        <option value="self_pickup" ${d.mode === "self_pickup" ? "selected" : ""}>Self-pickup</option>
      </select>
      ${modeBits}
      <label class="label">Packing (₹)</label>
      <input class="input" data-field="packing" value="${ctx.esc(d.packing)}">
      <label class="label">Other charges</label>
      ${charges}
      <button type="button" class="btn btn-secondary btn-sm" onclick="CustomerOrders.addDispatchCharge(${p.bill_id})">+ Charge</button>
      <label class="label">Marking</label>
      <textarea class="input" data-field="marking" rows="2" style="background:#fee2e2;border:1px solid #dc2626;font-weight:800;color:#b91c1c;">${ctx.esc(d.marking)}</textarea>
      <label class="label">Narration for picked</label>
      <textarea class="input" data-field="picksay" rows="2" placeholder="What should show on the picked tile">${ctx.esc(d.pickNarration || "")}</textarea>
      <button type="button" class="btn btn-primary" style="margin-top:12px;" onclick="CustomerOrders.markDispatchPicked(${p.bill_id})">Mark as picked</button>
    </div>`;
  }

  function storyLines(lines) {
    return (lines || []).map(l => `<tr><td>${ctx.esc(l.our_product_id)}</td><td>${l.quantity}</td><td>${fmtPrice(l.rate)}</td></tr>`).join("")
      || `<tr><td colspan="3">—</td></tr>`;
  }

  function storyBlock(title, row) {
    if (!row) return "";
    const when = row.at ? (ctx.fmtDate?.(row.at) || String(row.at).slice(0, 16).replace("T", " ")) : "";
    const bits = [];
    if (row.transport_mode) bits.push(row.transport_mode === "bus" ? "Bus / freight" : row.transport_mode === "transport" ? "Transport" : "Self-pickup");
    if (Number(row.freight_charges) > 0) bits.push(`Charges ${fmtPrice(row.freight_charges)}`);
    if (row.transport_receipt_number) bits.push(`Rcpt ${row.transport_receipt_number}`);
    if (Number(row.packaging_charges) > 0) bits.push(`Packing ${fmtPrice(row.packaging_charges)}`);
    (row.additional_charges || []).forEach(c => { if (Number(c.amount) > 0) bits.push(`${c.name} ${fmtPrice(c.amount)}`); });
    return `<div style="margin-top:10px;padding:10px 12px;border:1px solid #e2e8f0;border-radius:8px;background:#fff;">
      <div style="font-weight:800;">${ctx.esc(title)}</div>
      <div style="font-size:12px;color:var(--muted);margin:2px 0 8px;">${ctx.esc(row.by || "Staff")}${when ? " · " + ctx.esc(when) : ""}</div>
      ${row.marking ? `<div style="color:#b91c1c;font-weight:700;margin-bottom:6px;">Marking: ${ctx.esc(row.marking)}</div>` : ""}
      ${bits.length ? `<div style="font-size:13px;margin-bottom:6px;">${ctx.esc(bits.join(" · "))}</div>` : ""}
      <table class="data"><thead><tr><th>Item</th><th>Qty</th><th>Rate</th></tr></thead><tbody>${storyLines(row.lines)}</tbody></table>
    </div>`;
  }

  function renderDispatchList() {
    const el = document.getElementById("customer-orders-list");
    if (!el) return;
    const canWrite = !!ctx.canWrite?.("customer_orders");
    const list = filterDispatchParcels(dispatchParcels);
    const pickedTab = currentBucket === "picked";
    if (!list.length) {
      el.innerHTML = OrdersUI.emptyState({
        title: pickedTab ? "No picked parcels" : "Nothing waiting to be picked",
        sub: pickedTab ? "Mark a dispatch tile as picked and it lands here." : "After the bill, Dispatch brings the parcel here.",
      });
      return;
    }
    el.innerHTML = list.map(p => {
      const lines = (p.lines || []).map(l => `${ctx.esc(l.our_product_id)} × ${l.quantity}`).join(" · ");
      const meta = [
        p.bill_number ? `Bill ${p.bill_number}` : null,
        p.freight_handler ? `Person ${p.freight_handler}` : null,
        p.customer_city || null,
        `${p.total_pcs || 0} pcs`,
      ].filter(Boolean).join(" · ");
      const noteKey = `dispatch:${p.bill_id}`;
      const open = pickedTab && String(pickedOpenId) === String(p.bill_id);
      const story = pickedStories[p.bill_id];
      const storyHtml = open && story ? [
        storyBlock("Order created", story.created),
        storyBlock("Billed", story.billed),
        storyBlock("Dispatched", story.dispatched),
        storyBlock("Marked as picked", story.picked),
      ].join("") : "";
      return `<div class="ord-card" style="padding:14px 16px;" ${pickedTab ? `onclick="CustomerOrders.togglePickedStory(${p.bill_id})"` : ""}>
        <div style="min-width:0;">
          <strong class="ord-card-title" style="font-size:16px;">${ctx.esc(p.customer_label || "Customer")}</strong>
          ${p.created_by ? `<div style="display:block;margin-top:8px;padding:8px 10px;border-radius:10px;background:#dcfce7;color:#166534;font-weight:800;font-size:16px;">Created by ${ctx.esc(p.created_by)}</div>` : ""}
          ${parcelMarkHtml(p)}
          <div data-tile-note="${noteKey}" onclick="event.stopPropagation()">
            <button type="button" class="btn btn-secondary btn-sm" style="margin-top:6px;" onclick="event.stopPropagation();App.editTileNote('${noteKey}')">Add note</button>
          </div>
          ${p.dispatch_narration ? `<div style="margin-top:8px;padding:8px 10px;border-radius:8px;background:#e0f2fe;color:#0c4a6e;font-weight:700;">Dispatch: ${ctx.esc(p.dispatch_narration)}</div>` : ""}
          ${pickedTab && p.pick_narration ? `<div style="margin-top:8px;padding:8px 10px;border-radius:8px;background:#fef3c7;color:#92400e;font-weight:700;">Picked: ${ctx.esc(p.pick_narration)}</div>` : ""}
          <div class="ord-card-meta" style="margin-top:4px;">${ctx.esc(meta)}</div>
          <div style="font-size:13px;margin-top:8px;">${lines || "—"}</div>
          ${pickedTab ? storyHtml : (canWrite ? dispatchFormHtml(p) : "")}
        </div>
      </div>`;
    }).join("");
  }

  async function togglePickedStory(billId) {
    if (String(pickedOpenId) === String(billId)) {
      pickedOpenId = null;
      renderDispatchList();
      return;
    }
    pickedOpenId = billId;
    if (!pickedStories[billId]) {
      try { pickedStories[billId] = await ctx.api(`/freight-agents/parcels/${billId}/story`, {}, 0); }
      catch (e) { ctx.toast(e.message, "error"); pickedOpenId = null; }
    }
    renderDispatchList();
  }

  function askDispatchNarration(billIds) {
    const ids = String(billIds || "").split(",").filter(Boolean);
    if (!ids.length) return ctx.toast("No bill to dispatch", "error");
    ctx.openDetail?.(
      "Dispatch",
      `<label class="label">Narration</label>
      <textarea id="co-dispatch-say" class="input" rows="3" placeholder="Comment for this dispatch"></textarea>
      <button type="button" class="btn btn-primary" style="margin-top:12px;" onclick="CustomerOrders.saveDispatchNarration('${ids.join(",")}')">Dispatch</button>`,
      "",
      "sm"
    );
    setTimeout(() => document.getElementById("co-dispatch-say")?.focus(), 30);
  }

  async function saveDispatchNarration(ids) {
    const text = (document.getElementById("co-dispatch-say")?.value || "").trim();
    if (!text) return ctx.toast("Enter a narration", "error");
    ctx.showLoading?.();
    try {
      await ctx.api("/freight-agents/parcels/dispatch-note", {
        method: "POST",
        body: JSON.stringify({ bill_ids: String(ids).split(",").map(Number), narration: text }),
      }, 0);
      App.closeDetail?.();
      ctx.toast("Dispatched", "success");
      goToDispatch();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function markDispatchPicked(billId) {
    pullDispatchDrafts();
    const d = dispatchDrafts[String(billId)];
    if (!d) return;
    if (d.mode === "bus" && parcelAgentIsVishnu(d.agent) && !d.handler) return ctx.toast("Select the freight person", "error");
    if (!String(d.pickNarration || "").trim()) return ctx.toast("Enter a narration", "error");
    ctx.showLoading?.();
    try {
      await ctx.api(`/freight-agents/parcels/${billId}/mark-picked`, {
        method: "POST",
        body: JSON.stringify({
          transport_mode: d.mode,
          freight_agent_id: d.mode === "bus" ? Number(d.agent) || null : null,
          freight_charges: d.freight,
          transport_receipt_number: d.receipt,
          packaging_charges: d.packing,
          additional_charges: d.charges,
          narration: d.marking,
          pick_narration: d.pickNarration,
          freight_handler: d.handler || null,
        }),
      }, 0);
      delete dispatchDrafts[String(billId)];
      ctx.toast("Marked as picked", "success");
      ctx.invalidateCache?.("/freight-agents");
      await loadDispatch();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function pickParcel(billId, mode) {
    const msg = mode === "bus"
      ? "Mark picked? Freight amount goes to this agent's dues in Money → Freight."
      : "Mark this parcel as dispatched?";
    if (!confirm(msg)) return;
    ctx.showLoading?.();
    try {
      await ctx.api(`/freight-agents/parcels/${billId}/pick`, { method: "POST", body: "{}" }, 0);
      ctx.toast("Picked — dues updated", "success");
      ctx.invalidateCache?.("/freight-agents");
      await loadDispatch();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function reassignParcel(billId) {
    const parcel = dispatchParcels.find(p => p.bill_id === billId);
    const currentId = parcel?.freight_agent_id || Number(dispatchAgentId) || "";
    const opts = dispatchAgents.map(a =>
      `<option value="${a.id}" ${a.id === currentId ? "selected" : ""}>${ctx.esc(a.name)}</option>`
    ).join("");
    ctx.openDetail?.("Change freight agent", `
      <p style="margin:0 0 12px;color:var(--muted);font-size:13px;">Only for unpicked parcels.</p>
      <label class="label">Agent</label>
      <select class="input" id="co-reassign-agent" style="margin-bottom:12px;">${opts}</select>
      <label class="label">Freight amount (₹) — optional</label>
      <input type="number" step="0.01" min="0" class="input" id="co-reassign-amt" placeholder="Leave blank to keep" />
    `, `
      <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="CustomerOrders.submitParcelReassign(${billId})">Save</button>
    `, "sm");
  }

  async function submitParcelReassign(billId) {
    const agentId = Number(document.getElementById("co-reassign-agent")?.value || 0);
    const amtRaw = (document.getElementById("co-reassign-amt")?.value || "").trim();
    if (!agentId) return ctx.toast("Pick agent", "error");
    const body = { freight_agent_id: agentId };
    if (amtRaw !== "") body.freight_charges = parseFloat(amtRaw);
    ctx.showLoading?.();
    try {
      await ctx.api(`/freight-agents/parcels/${billId}`, { method: "PATCH", body: JSON.stringify(body) }, 0);
      ctx.toast("Agent updated", "success");
      App.closeDetail?.();
      ctx.invalidateCache?.("/freight-agents");
      await loadDispatch();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function loadList(silent) {
    if (isDispatchBucket()) {
      await loadDispatch();
      return;
    }
    if (!silent) ctx.showLoading?.();
    try {
      if (!PAST_BUCKETS.includes(currentBucket) || currentBucket === "dispatch") {
        currentBucket = "open";
      }
      const day = dayParam();
      orders = await ctx.api(`/customer-orders?bucket=${currentBucket}&day=${day}`, {}, 0);
      if (!Array.isArray(orders)) orders = [];
      syncHubChrome();
      renderList();
    } catch (e) { if (!silent) ctx.toast(e.message, "error"); }
    finally { if (!silent) ctx.hideLoading?.(); }
  }

  function showHub() {
    closeSlidePanel();
    hubExpandedCustomerId = null;
    hubExpandCache = {};
    if (!PAST_BUCKETS.includes(currentBucket)) currentBucket = "open";
    ensurePrintDay();
    syncHubChrome();
    loadList();
    App.updateGlobalBack?.();
  }

  function detailBucketFor(o) {
    if (currentBucket === "dispatch" || currentBucket === "summary" || currentBucket === "queue") {
      return (o.total_quantity || 0) > 0 ? "open" : "received";
    }
    if (["received", "open", "billed", "cancelled", "closed"].includes(currentBucket)) {
      return currentBucket;
    }
    return (o.total_quantity || 0) > 0 ? "open" : "received";
  }

  function filterQueueList(list) {
    return list;
  }

  function createdByHtml(o) {
    const raw = o && o.created_by;
    const list = Array.isArray(raw) ? raw : (raw ? [raw] : []);
    const names = list.map(x => String(x || "").trim()).filter(Boolean);
    if (!names.length) return "";
    return `<div style="display:block;margin:0;padding:8px 14px;background:#dcfce7;color:#166534;font-weight:800;font-size:16px;line-height:1.3;">Created by ${ctx.esc(names.join(" · "))}</div>`;
  }

  function sourceMeta(sources) {
    const list = Array.isArray(sources) ? sources : [];
    if (!list.length) return "";
    return list.map(s => {
      if (s === "phone") return "Phone";
      if (s === "portal") return "Portal";
      return String(s);
    }).filter(Boolean).join(" · ");
  }

  function renderHubExpand(detail, canWrite, customerId) {
    const lines = detail?.open_lines || [];
    if (!lines.length) return `<p class="vo-muted" style="margin:0;">Nothing to bill.</p>`;
    return `<table class="data vo-hub-table"><thead><tr>
      <th></th><th>Product</th><th>To bill</th><th>Rate</th>
    </tr></thead><tbody>
      ${lines.map(l => {
        const img = (l.image_urls || [])[0] || "";
        return `<tr>
          <td>${thumb(img)}</td>
          <td><strong>${ctx.esc(l.our_product_id)}</strong>${l.marking ? ` <span class="marking-flag">${ctx.esc(l.marking)}</span>` : ""}</td>
          <td><strong>${l.quantity_open}</strong></td>
          <td>${fmtPrice(l.unit_price)}</td>
        </tr>`;
      }).join("")}
    </tbody></table>
    ${canWrite ? `<div class="vo-hub-expand-actions">
      <button class="btn btn-primary" onclick="CustomerOrders.processFromHub(${customerId}, 'open')">Create Bill</button>
      <button class="btn btn-danger" onclick="CustomerOrders.cancelCustomerOpen(${customerId})">Cancel entire order</button>
    </div>` : ""}`;
  }

  function renderOrderCard(o, canWrite) {
    const openQty = o.total_quantity || 0;
    const bucket = detailBucketFor(o);
    const src = sourceMeta(o.sources);
    const canMoney = !!ctx.isAdmin?.() || !!ctx.canWrite?.("ar") || !!ctx.canWrite?.("finance");
    const viewFn = `CustomerOrders.openDetail(${o.customer_id}, '${bucket}')`;

    // Primary action by bucket
    let primaryLabel = "View";
    let primaryOnclick = viewFn;
    let statText = "";
    if (currentBucket === "open") {
      primaryLabel = "Create Bill";
      primaryOnclick = `CustomerOrders.processFromHub(${o.customer_id}, 'open')`;
      statText = `${o.line_count || 0} lines · ${openQty} to bill`;
    } else if (currentBucket === "received") {
      primaryLabel = canWrite ? "Confirm →" : "View";
      primaryOnclick = canWrite ? `CustomerOrders.confirmOrder(${o.customer_id})` : viewFn;
      statText = `${o.placement_count || 0} placement${(o.placement_count || 0) !== 1 ? "s" : ""} · ${o.total_quantity || 0} pcs`;
    } else if (currentBucket === "billed") {
      const chips = Array.isArray(o.bills) ? o.bills : [];
      const billIds = chips.map(b => b.bill_id).filter(Boolean).join(",");
      primaryLabel = "Dispatch";
      primaryOnclick = `CustomerOrders.askDispatchNarration('${billIds}')`;
      const billBits = chips.map(b => {
        const num = b.bill_number ? `Bill ${ctx.esc(b.bill_number)}` : "";
        const amt = b.grand_total != null && b.grand_total !== "" ? fmtPrice(b.grand_total) : "";
        return [num, amt].filter(Boolean).join(" · ");
      }).filter(Boolean);
      statText = billBits.length
        ? billBits.join("<br>")
        : `${o.bill_count || 0} bill${(o.bill_count || 0) !== 1 ? "s" : ""}`;
    } else if (currentBucket === "cancelled" || currentBucket === "closed") {
      statText = `${o.placement_count || 0} placement${(o.placement_count || 0) !== 1 ? "s" : ""}`;
    }
    if (src) statText += (statText ? " · " : "") + src;

    const markHtml = tileMarkHtml(o);

    // More menu
    const more = [];
    more.push({ label: "Open detail", onclick: viewFn });
    if (canWrite && (currentBucket === "received" || currentBucket === "open")) {
      more.push({ label: "Edit / place more", onclick: `CustomerOrders.openOfflineWizard(${o.customer_id})` });
    }
    if (currentBucket === "billed") {
      if (canMoney) more.push({ label: "Collect payment", onclick: `CustomerOrders.goCollectPayment(${o.customer_id})` });
      const billChips = Array.isArray(o.bills) ? o.bills : [];
      if (canWrite && (ctx.isAdmin?.() || billChips.some(b => billEditableToday(b.created_at)))) more.push({ label: "Edit bill", onclick: `CustomerOrders.editLatestBill(${o.customer_id})` });
      if (canWrite) more.push({ label: "Close order", onclick: `CustomerOrders.openCloseBatch(${o.customer_id})` });
    }
    if (canWrite && openQty > 0 && currentBucket === "open") {
      more.push({ label: "Cancel entire order", onclick: `CustomerOrders.cancelCustomerOpen(${o.customer_id})`, danger: true });
    }
    if (canWrite && currentBucket === "received") {
      more.push({ label: "Cancel entire order", onclick: `CustomerOrders.cancelEntireReceived(${o.customer_id})`, danger: true });
    }

    // Party name HTML
    const _m1Upper = (o.marker_1 || "").toUpperCase();
    const nameHtml = (o.party_number ? `<span style="color:var(--muted);font-size:11px;font-weight:600;">#${o.party_number}</span> ` : "")
      + ctx.esc(o.customer_name)
      + (o.marker_1 ? ` <span class="badge badge-blue" style="font-size:9px;padding:1px 4px;">${ctx.esc(o.marker_1)}</span>` : "")
      + (o.marker_2 ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;">${ctx.esc(o.marker_2)}</span>` : "")
      + (o.payment_type === "CASH" && !_m1Upper.includes("CASH") ? ` <span class="badge badge-amber" style="font-size:9px;padding:1px 4px;">CASH</span>` : "");

    const when = o.display_date || o.updated_at;
    const timeStr = when ? (ctx.fmtDay?.(when) || "") : "";
    const bucketCls = { received: "ord-order-card--received", open: "ord-order-card--open", billed: "ord-order-card--billed", closed: "ord-order-card--closed", cancelled: "ord-order-card--cancelled" }[currentBucket] || "";

    const avatarLetter = ctx.esc((o.customer_name || "?").slice(0, 1).toUpperCase());

    // More menu HTML (inline, no OrdersUI.moreMenu — build simple dropdown)
    const moreHtml = more.length ? `<div class="ord-more-wrap" style="position:relative;">
      <button type="button" class="btn btn-ghost btn-sm" style="min-width:44px;min-height:44px;padding:0 10px;font-size:22px;line-height:1;" onclick="event.preventDefault();event.stopPropagation();CustomerOrders.toggleCardMore(event,${o.customer_id})">⋮</button>
      <div id="co-card-more-${o.customer_id}" class="ord-more-menu" style="display:none;position:fixed;z-index:80;background:#fff;border:1px solid #e2e8f0;border-radius:10px;box-shadow:0 8px 24px rgba(15,23,42,.18);min-width:200px;">
        ${more.map(m => `<button type="button" class="ord-more-item${m.danger ? " ord-more-danger" : ""}" onclick="event.preventDefault();event.stopPropagation();CustomerOrders.closeAllCardMore();${m.onclick}">${ctx.esc(m.label)}</button>`).join("")}
      </div>
    </div>` : "";

    const primaryBtn = (canWrite || currentBucket === "billed" || currentBucket === "cancelled" || currentBucket === "closed")
      ? `<button type="button" class="btn btn-primary btn-sm" onclick="event.stopPropagation();${primaryOnclick}">${ctx.esc(primaryLabel)}</button>`
      : `<button type="button" class="btn btn-secondary btn-sm" onclick="event.stopPropagation();${viewFn}">View</button>`;

    return `<div class="ord-order-card ${bucketCls}" onclick="${viewFn}">
      <div class="ord-order-card-head">
        <div class="ord-order-card-avatar">${avatarLetter}</div>
        <div class="ord-order-card-party">
          <div class="ord-order-card-name">${nameHtml}</div>
          <div class="ord-order-card-city">${o.city_name ? ctx.esc(o.city_name) : ""}${o.city_name && timeStr ? " · " : ""}${timeStr ? `<span class="ord-order-card-time">${ctx.esc(timeStr)}</span>` : ""}</div>
        </div>
      </div>
      ${createdByHtml(o)}
      ${markHtml}
      <div data-tile-note="co:${currentBucket}:${o.customer_id}" onclick="event.stopPropagation()">
        <button type="button" class="btn btn-secondary btn-sm" style="margin:6px 14px;" onclick="event.stopPropagation();App.editTileNote('co:${currentBucket}:${o.customer_id}')">Add note</button>
      </div>
          <div class="ord-order-card-body">
        ${statText ? `<div class="ord-order-card-stat">${statText}</div>` : ""}
      </div>
      <div class="ord-order-card-foot" onclick="event.stopPropagation()">
        ${primaryBtn}
        ${moreHtml}
      </div>
    </div>`;
  }

  function toggleCardMore(e, customerId) {
    if (e) { e.preventDefault(); e.stopPropagation(); }
    const id = `co-card-more-${customerId}`;
    const el = document.getElementById(id);
    if (!el) return;
    const wasOpen = el.style.display !== "none";
    closeAllCardMore();
    if (wasOpen) return;
    const btn = e && (e.currentTarget || e.target);
    const rect = btn && btn.getBoundingClientRect ? btn.getBoundingClientRect() : null;
    if (rect) {
      const menuHeight = 180;
      const top = rect.bottom + 6 + menuHeight > window.innerHeight ? Math.max(8, rect.top - menuHeight) : rect.bottom + 6;
      el.style.top = top + "px";
      el.style.left = Math.max(8, rect.right - 200) + "px";
    }
    el.style.display = "block";
    el.closest(".ord-order-card")?.classList.add("is-menu-open");
  }

  function closeAllCardMore(e) {
    if (e && e.target && e.target.closest && e.target.closest(".ord-more-wrap, .ord-more-menu")) return;
    document.querySelectorAll('[id^="co-card-more-"]').forEach(el => { el.style.display = "none"; });
    document.querySelectorAll(".ord-order-card.is-menu-open").forEach(el => el.classList.remove("is-menu-open"));
  }

  function renderList() {
    const el = document.getElementById("customer-orders-list");
    if (!el) return;
    const canWrite = !!ctx.canWrite?.("customer_orders");
    const list = filterHubOrders(orders);
    const stage = BUCKET_LABELS[currentBucket] || "orders";
    const today = isTodayMode();

    if (!list.length) {
      el.innerHTML = OrdersUI.emptyState({
        title: today ? `No ${stage} today` : `No ${stage}`,
        sub: today
          ? "Switch to Past for older dates. Same stages there."
          : "Try another stage, or place an order.",
        ctaHtml: canWrite
          ? `<button class="btn btn-primary" onclick="CustomerOrders.openOfflineWizard()">+ Place for customer</button>`
          : "",
      });
      return;
    }
    el.innerHTML = list.map(o => renderOrderCard(o, canWrite)).join("");
    // Close card more menus on outside click
    document.removeEventListener("click", closeAllCardMore);
    document.addEventListener("click", closeAllCardMore);
  }

  function openSlidePanel() {
    const panel = document.getElementById("co-slide-panel");
    const backdrop = document.getElementById("co-slide-backdrop");
    panel?.classList.add("is-open");
    backdrop?.classList.add("is-open");
    document.body.style.overflow = "hidden";
    // Escape key handler
    document._coSlideEscHandler = (e) => { if (e.key === "Escape") closeSlidePanel(); };
    document.addEventListener("keydown", document._coSlideEscHandler);
  }

  function closeSlidePanel() {
    const panel = document.getElementById("co-slide-panel");
    const backdrop = document.getElementById("co-slide-backdrop");
    panel?.classList.remove("is-open");
    backdrop?.classList.remove("is-open");
    document.body.style.overflow = "";
    if (document._coSlideEscHandler) {
      document.removeEventListener("keydown", document._coSlideEscHandler);
      document._coSlideEscHandler = null;
    }
    detailCustomerId = null;
    currentOrder = null;
    App.updateGlobalBack?.();
  }

  async function openDetail(customerId, bucket) {
    ctx.showLoading?.();
    try {
      let b = bucket || "open";
      if (b === "summary" || b === "needs_action" || b === "queue") b = "open";
      if (b === "dispatch") b = "billed"; // Dispatch is hub-only (parcels), not customer detail
      const detailBuckets = ["received", "open", "billed", "cancelled", "closed"];
      if (!detailBuckets.includes(b)) b = "open";
      currentBucket = b;
      detailCustomerId = customerId;
      coExpandedId = null;
      currentOrder = await ctx.api(`/customer-orders/customer/${customerId}?bucket=${b}`, {}, 0);
      OrdersUI.syncStageChips("#co-detail-bucket-bar", b);
      renderDetail();
      openSlidePanel();
      App.updateGlobalBack?.();
      return true;
    } catch (e) {
      ctx.toast(e.message, "error");
      return false;
    } finally { ctx.hideLoading?.(); }
  }

  async function switchBucket(bucket) {
    if (!detailCustomerId) return;
    if (bucket === "dispatch") {
      goToDispatch();
      return;
    }
    coExpandedId = null;
    await openDetail(detailCustomerId, bucket);
  }

  function renderDetail() {
    const el = document.getElementById("co-detail-body");
    const title = document.getElementById("co-detail-title");
    const sub = document.getElementById("co-detail-sub");
    if (!el || !currentOrder) return;
    if (title) {
      const o = currentOrder;
      const _m1u = (o.marker_1 || "").toUpperCase();
      const pn = o.party_number ? `<span style="color:var(--muted);font-size:14px;font-weight:600;margin-right:6px;">#${o.party_number}</span>` : "";
      const m1 = o.marker_1 ? ` <span class="badge badge-blue" style="font-size:10px;vertical-align:middle;">${ctx.esc(o.marker_1)}</span>` : "";
      const m2 = o.marker_2 ? ` <span class="badge badge-amber" style="font-size:10px;vertical-align:middle;">${ctx.esc(o.marker_2)}</span>` : "";
      const pt = (o.payment_type === "CASH" && !_m1u.includes("CASH")) ? ` <span class="badge badge-amber" style="font-size:10px;vertical-align:middle;">CASH</span>` : "";
      const city = o.city_name ? ` <span style="color:var(--muted);font-weight:600;">· ${ctx.esc(o.city_name)}</span>` : "";
      title.innerHTML = pn + ctx.esc(o.customer_name) + city + m1 + m2 + pt;
    }
    if (sub) {
      sub.textContent = currentBucket === "received" ? "Review order, edit if needed, then Confirm →"
        : currentBucket === "open" ? "Goods being picked — Create Bill when ready"
          : currentBucket === "billed" ? "Bill created — Dispatch or Collect payment, then Close"
            : currentBucket === "closed" ? "Done"
              : "Cancelled";
    }
    const canWrite = !!ctx.canWrite?.("customer_orders");
    const canMoney = !!ctx.isAdmin?.() || !!ctx.canWrite?.("ar") || !!ctx.canWrite?.("finance");
    const ledgerBack = window.__jcLedgerReturn
      ? `<button type="button" class="btn btn-secondary btn-sm" style="margin:0 0 12px;" onclick="App.returnToLedger()">← Back to ledger</button>`
      : "";

    if (currentBucket === "open") {
      const lines = currentOrder.open_lines || [];
      const waiting = currentOrder.placements || [];
      const waitingHtml = waiting.length ? `<div style="margin-bottom:14px;">
        <div class="label">Orders still to bill</div>
        ${waiting.map(p => {
          const bits = (p.lines || []).map(ln => `${ctx.esc(ln.our_product_id)} × ${ln.quantity} · stock ${ln.stock ?? 0}`).join(", ");
          return `<div style="margin:0 0 8px;padding:8px 10px;border:1px solid #e2e8f0;border-radius:8px;">
            <div style="font-size:13px;">${ctx.fmtWhen ? ctx.fmtWhen(p.placed_at) : (ctx.fmtDay ? ctx.fmtDay(p.placed_at) : "")} · ${bits}</div>
            ${markingBanner(p.customer_notes)}
          </div>`;
        }).join("")}
      </div>` : "";
      const canBill = canWrite && (lines.length || waiting.length);
      el.innerHTML = `
        ${ledgerBack}
        ${cashWarningHtml(currentOrder)}
        ${canBill ? `<div class="ui-toolbar" style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary" onclick="CustomerOrders.processOrder()">Create Bill</button>
          <button class="btn btn-secondary btn-sm" onclick="CustomerOrders.openEditFromOpen()">Edit order</button>
          <button class="btn btn-danger btn-sm" onclick="CustomerOrders.cancelCustomerOpen(${detailCustomerId})">Cancel entire order</button>
        </div>` : ""}
        ${waitingHtml}
        <div class="ord-hub-list">${lines.length ? lines.map(line => HubUI.partyCard({
          title: ctx.esc(line.our_product_id) + (line.marking ? ` <span class="marking-flag">${ctx.esc(line.marking)}</span>` : ""),
          titleIsHtml: true,
          meta: `${thumb((line.image_urls || [])[0])} Recv ${line.quantity_received} · To bill <strong>${line.quantity_open}</strong> · Billed ${line.quantity_billed} · Stock <strong>${line.stock ?? 0}</strong> · ${fmtPrice(line.unit_price)}${addonsUnderHtml(line.addons, line.quantity_open)}${orderMarkingForProduct(waiting, line.catalog_product_id)}`,
          pillHtml: "",
          primaryLabel: canWrite ? "Edit qty" : null,
          primaryOnclick: `CustomerOrders.editOpenLine(${line.id}, ${line.quantity_open})`,
          dangerLabel: canWrite ? "Cancel" : null,
          dangerOnclick: `CustomerOrders.cancelOpenLine(${line.id})`,
          moreItems: canWrite
            ? [
                { label: "Edit order (add/remove)", onclick: "CustomerOrders.openEditFromOpen()" },
                { label: "Cancel line", onclick: `CustomerOrders.cancelOpenLine(${line.id})`, danger: true },
              ]
            : [],
          canWrite,
        })).join("") : HubUI.emptyState({
          title: "Nothing to bill",
          sub: "No open qty for this customer.",
          ctaHtml: canWrite ? `<button class="btn btn-primary" onclick="CustomerOrders.openOfflineWizard()">+ Place for customer</button>` : "",
        })}</div>`;
      return;
    }

    if (currentBucket === "billed" && (currentOrder.bills || []).length) {
      el.innerHTML = `
        ${ledgerBack}
        ${cashWarningHtml(currentOrder)}
        <div class="ui-toolbar" style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap;">
          ${canWrite ? `<button class="btn btn-primary btn-sm" onclick="CustomerOrders.goToDispatch()">Dispatch</button>` : ""}
          ${canMoney ? `<button class="btn btn-primary btn-sm" onclick="CustomerOrders.goCollectPayment(${detailCustomerId})">Collect payment</button>` : ""}
          ${canWrite ? `<button class="btn btn-secondary btn-sm" onclick="CustomerOrders.openCloseBatch(${detailCustomerId})">Close order</button>` : ""}
        </div>
        <div class="ord-hub-list">${(currentOrder.bills || []).map(b => {
        const openKey = `bill-${b.id}`;
        const expanded = coExpandedId === openKey;
        const canEditBill = canWrite && billEditableToday(b.created_at) && (b.lines || []).every(ln => ln.status === "billed");
        const hasFreight = b.transport_mode === "bus" || !!(b.freight_agent_id);
        const modeLbl = b.transport_mode === "bus" ? "Bus" : b.transport_mode === "transport" ? "Transport" : b.transport_mode === "self_pickup" ? "Self-pickup" : (hasFreight ? "Bus" : "");
        const hideDisc = !!b.hide_discount_column;
        const linesHtml = `<table class="data vo-hub-table"><thead><tr><th>Product</th><th>Qty</th><th>Stock</th><th>Rate</th>${hideDisc ? "" : "<th>Disc</th>"}<th>Net</th><th>Total</th><th></th></tr></thead><tbody>
          ${(b.lines || []).map(ln => `<tr>
            <td>${ctx.esc(ln.our_product_id)}${ln.marking ? ` <span class="marking-flag">${ctx.esc(ln.marking)}</span>` : ""}${addonsUnderHtml(ln.addons, ln.quantity_shipped)}</td>
            <td>${ln.quantity_shipped}</td>
            <td>${ln.stock ?? 0}</td>
            <td>${fmtPrice(ln.unit_price)}</td>
            ${hideDisc ? "" : `<td>${ln.discount_percent ? ctx.esc(String(ln.discount_percent)) + "%" : "—"}</td>`}
            <td>${fmtPrice(ln.net_rate)}</td>
            <td>${fmtPrice(ln.line_total)}</td>
            <td style="white-space:nowrap;">${ln.status === "billed" && canWrite
              ? `<button class="btn btn-danger btn-sm" onclick="CustomerOrders.cancelBilledLine(${ln.id})">Cancel</button> <button class="btn btn-secondary btn-sm" onclick="CustomerOrders.closeBillLine(${ln.id})">Close line</button>`
              : `<span class="vo-muted">${ctx.esc(ln.status === "billed" ? "Open" : "Closed")}</span>`}</td>
          </tr>`).join("")}
        </tbody></table>`;
        const more = [
          { label: "Download PDF", onclick: `CustomerOrders.openBillDoc(${b.id}, false)` },
          { label: "WhatsApp", onclick: `CustomerOrders.shareBillWhatsApp(${b.id})` },
        ];
        if (canWrite && billEditableToday(b.created_at)) {
          more.push({ label: "Edit bill number", onclick: `CustomerOrders.promptEditBillNumber(${b.id}, ${JSON.stringify(b.bill_number || "")})` });
        }
        if (canWrite) {
          more.push({ label: "Update payment QR", onclick: `CustomerOrders.uploadBillQr(${b.id})` });
          if (b.has_custom_qr) {
            more.push({ label: "Use default payment QR", onclick: `CustomerOrders.resetBillQr(${b.id})` });
          }
        }
        if (canEditBill) {
          more.push({ label: "Cancel bill", onclick: `CustomerOrders.cancelBill(${b.id})`, danger: true });
        }
        if (ctx.isAdmin?.()) {
          more.push({ label: "Void (recycle bin)", onclick: `CustomerOrders.voidBill(${b.id})`, danger: true });
        }
        if (canWrite) {
          more.unshift({ label: "Dispatch", onclick: "CustomerOrders.goToDispatch()" });
        }
        more.unshift({ label: "Print", onclick: `CustomerOrders.openBillDoc(${b.id}, true)` });
        const chargeBit = Number(b.freight_charges) > 0
          ? (b.transport_mode === "transport" ? ` · Transport ${fmtPrice(b.freight_charges)}` : ` · Freight ${fmtPrice(b.freight_charges)}`)
          : "";
        const receiptBit = b.transport_receipt_number ? ` · Rcpt ${ctx.esc(b.transport_receipt_number)}` : "";
        return HubUI.partyCard({
          title: b.display_name || `Bill ${b.bill_number}`,
          meta: `${fmtPrice(b.grand_total)} · ${ctx.fmtDate(b.created_at || b.display_date || b.bill_date)}${b.created_by_name ? ` · ${ctx.esc(b.created_by_name)}` : ""}${modeLbl ? ` · ${modeLbl}` : ""}${chargeBit}${receiptBit}${(b.additional_charges || []).filter(c => Number(c.amount) > 0).map(c => ` · ${ctx.esc(c.name)} ${fmtPrice(c.amount)}`).join("")}${b.status && b.status !== "open" ? ` · ${ctx.esc(b.status)}` : ""}${b.narration ? `<div style="margin-top:2px;">${ctx.esc(onlyMark(b.narration))}</div>` : ""}`,
          pillHtml: "",
          primaryLabel: canEditBill ? "Edit" : "Print",
          primaryOnclick: canEditBill
            ? `CustomerOrders.openEditBill(${b.id})`
            : `CustomerOrders.openBillDoc(${b.id}, true)`,
          moreItems: more.filter(m => m.label !== (canEditBill ? "Edit" : "Print")),
          open: expanded,
          rowOnclick: `CustomerOrders.toggleDetailExpand('${openKey}')`,
          canWrite: true,
          expandHtml: expanded ? linesHtml : "",
        });
      }).join("")}</div>`;
      return;
    }

    if (currentBucket === "received") {
      const placements = currentOrder.placements || [];
      el.innerHTML = `
        ${ledgerBack}
        ${cashWarningHtml(currentOrder)}
        ${canWrite && placements.length ? `<div class="ui-toolbar" style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary btn-sm" onclick="CustomerOrders.confirmOrder(${detailCustomerId})">✓ Confirm order</button>
          <button class="btn btn-secondary btn-sm" onclick="CustomerOrders.openOfflineWizard(${detailCustomerId})">Edit / add items</button>
          <button class="btn btn-danger btn-sm" onclick="CustomerOrders.cancelEntireReceived(${detailCustomerId})">Cancel entire order</button>
        </div>` : ""}
        <div class="ord-hub-list">${placements.length ? placements.map(p => {
        const active = (p.lines || []).filter(ln => ln.status === "active");
        const canEdit = canWrite && p.status === "received" && active.length > 0;
        const hasUnbilled = active.some(ln => Number(ln.quantity) > Number(ln.quantity_billed || 0));
        const hasBilled = active.some(ln => Number(ln.quantity_billed) > 0);
        const canCancel = canWrite && p.status === "received" && hasUnbilled;
        const cancelLabel = hasBilled ? "Cancel remaining" : "Cancel order";
        const openKey = `recv-${p.id}`;
        const expanded = coExpandedId === openKey;
        const linesHtml = `<table class="data vo-hub-table"><thead><tr><th>Product</th><th>Qty</th><th>Billed</th><th>Stock</th><th>Rate</th><th></th></tr></thead><tbody>
          ${(p.lines || []).map(ln => `<tr>
            <td>${ctx.esc(ln.our_product_id)}${ln.marking ? ` <span class="marking-flag">${ctx.esc(ln.marking)}</span>` : ""}${addonsUnderHtml(ln.addons, ln.quantity)}</td>
            <td>${ln.quantity}</td>
            <td>${ln.quantity_billed}</td>
            <td>${ln.stock ?? 0}</td>
            <td>${fmtPrice(ln.unit_price)}</td>
            <td style="white-space:nowrap;">
              ${ln.status === "active" && canWrite ? `
                <button class="btn btn-secondary btn-sm" onclick="CustomerOrders.editReceivedLine(${ln.id}, ${ln.quantity})">Qty</button>
                ${Number(ln.quantity) > Number(ln.quantity_billed || 0)
                  ? `<button class="btn btn-danger btn-sm" onclick="CustomerOrders.cancelReceivedLine(${ln.id})">Cancel</button>`
                  : ""}
              ` : `<span class="vo-muted">${ctx.esc(ln.status || "")}</span>`}
            </td>
          </tr>`).join("")}
        </tbody></table>`;
        const more = [];
        if (canEdit) more.push({ label: "Edit order", onclick: `CustomerOrders.openEditPlacement(${p.id})` });
        if (canCancel) more.push({ label: cancelLabel, onclick: `CustomerOrders.cancelPlacement(${p.id})`, danger: true });
        if (ctx.isAdmin?.()) more.push({ label: "Void (recycle bin)", onclick: `CustomerOrders.voidPlacement(${p.id})`, danger: true });
        return HubUI.partyCard({
          title: p.display_name || `Order #${p.id}`,
          meta: `${ctx.fmtDay(p.display_date)}${p.customer_notes ? `<div style="margin-top:4px;color:#b91c1c;font-weight:700;">${ctx.esc(p.customer_notes)}</div>` : ""}${p.cancel_reason ? `<div style="color:var(--danger);margin-top:2px;">Cancelled: ${ctx.esc(p.cancel_reason)}</div>` : ""}`,
          pillHtml: p.cancel_reason ? HubUI.pill("Cancelled", "danger") : "",
          primaryLabel: canEdit ? "Edit" : null,
          primaryOnclick: canEdit ? `CustomerOrders.openEditPlacement(${p.id})` : "",
          moreItems: more.filter(m => !(canEdit && m.label === "Edit order")),
          open: expanded,
          rowOnclick: `CustomerOrders.toggleDetailExpand('${openKey}')`,
          canWrite,
          expandHtml: expanded ? linesHtml : "",
        });
      }).join("") : HubUI.emptyState({
        title: "No orders",
        sub: "No placements for this customer yet.",
        ctaHtml: canWrite ? `<button class="btn btn-primary" onclick="CustomerOrders.openOfflineWizard()">+ Place for customer</button>` : "",
      })}</div>`;
      return;
    }

    // cancelled / closed / billed-without-bills fallback
    const placements = currentOrder.placements || [];
    el.innerHTML = `${ledgerBack}<div class="ord-hub-list">${placements.length ? placements.map(p => {
      const openKey = `hist-${p.id}`;
      const expanded = coExpandedId === openKey;
      const linesHtml = `<table class="data vo-hub-table"><thead><tr><th>Product</th><th>Qty</th><th>Billed</th><th>Rate</th></tr></thead><tbody>
        ${(p.lines || []).map(ln => `<tr>
          <td>${ctx.esc(ln.our_product_id)}${addonsUnderHtml(ln.addons, ln.quantity)}</td>
          <td>${ln.quantity}</td>
          <td>${ln.quantity_billed}</td>
          <td>${fmtPrice(ln.unit_price)}</td>
        </tr>`).join("")}
      </tbody></table>`;
      return HubUI.partyCard({
        title: p.display_name || `Placement #${p.id}`,
        meta: `${ctx.fmtDay(p.display_date)}${p.customer_notes ? `<div style="margin-top:4px;color:#b91c1c;font-weight:700;">${ctx.esc(p.customer_notes)}</div>` : ""}${p.cancel_reason ? `<div style="color:var(--danger);margin-top:2px;">Cancelled: ${ctx.esc(p.cancel_reason)}</div>` : ""}`,
        pillHtml: currentBucket === "cancelled" || p.cancel_reason || p.status === "cancelled"
          ? HubUI.pill("Cancelled", "danger")
          : HubUI.pill(currentBucket === "closed" || p.status === "closed" ? "Closed" : "History", "muted"),
        moreItems: ctx.isAdmin?.() ? [{ label: "Void (recycle bin)", onclick: `CustomerOrders.voidPlacement(${p.id})`, danger: true }] : [],
        open: expanded,
        rowOnclick: `CustomerOrders.toggleDetailExpand('${openKey}')`,
        canWrite: true,
        expandHtml: expanded ? linesHtml : "",
      });
    }).join("") : HubUI.emptyState({
      title: "No placements",
      sub: "Nothing in this stage for this customer.",
    })}</div>`;
  }

  function toggleDetailExpand(key) {
    coExpandedId = coExpandedId === key ? null : key;
    renderDetail();
  }

  async function editOpenLine(lineId, currentQty) {
    const raw = prompt("Edit open quantity:", String(currentQty ?? 1));
    if (raw == null) return;
    const qty = parseInt(raw, 10);
    if (!Number.isFinite(qty) || qty < 0) return ctx.toast("Invalid quantity", "error");
    ctx.showLoading?.();
    try {
      await ctx.api(`/customer-orders/open-lines/${lineId}`, {
        method: "PATCH",
        body: JSON.stringify({ quantity: qty }),
      });
      ctx.invalidateCache?.("/customer-orders");
      ctx.toast("Open qty updated", "success");
      if (currentOrder) await openDetail(currentOrder.customer_id, "open");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function editReceivedLine(lineId, currentQty) {
    const raw = prompt("Edit received quantity (0 removes):", String(currentQty ?? 1));
    if (raw == null) return;
    const qty = parseInt(raw, 10);
    if (!Number.isFinite(qty) || qty < 0) return ctx.toast("Invalid quantity", "error");
    ctx.showLoading?.();
    try {
      if (qty === 0) {
        await ctx.api(`/customer-orders/lines/${lineId}`, { method: "DELETE" });
        ctx.toast("Line removed", "success");
      } else {
        await ctx.api(`/customer-orders/lines/${lineId}`, {
          method: "PATCH",
          body: JSON.stringify({ quantity: qty }),
        });
        ctx.toast("Received qty updated", "success");
      }
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/stock");
      if (currentOrder) await openDetail(currentOrder.customer_id, "received");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function deleteReceivedLine(lineId) {
    if (!confirm("Remove unbilled qty for this product?")) return;
    ctx.showLoading?.();
    try {
      // Find billed floor — DELETE only works when billed=0; else shrink to billed.
      let billed = 0;
      for (const p of (currentOrder?.placements || [])) {
        const ln = (p.lines || []).find(x => x.id === lineId);
        if (ln) { billed = Number(ln.quantity_billed) || 0; break; }
      }
      if (billed > 0) {
        await ctx.api(`/customer-orders/lines/${lineId}`, {
          method: "PATCH",
          body: JSON.stringify({ quantity: billed }),
        });
        ctx.toast("Unbilled qty removed — billed kept", "success");
      } else {
        await ctx.api(`/customer-orders/lines/${lineId}`, { method: "DELETE" });
        ctx.toast("Line removed", "success");
      }
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/stock");
      if (currentOrder) await openDetail(currentOrder.customer_id, "received");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openEditFromOpen() {
    if (!detailCustomerId) return;
    ctx.showLoading?.();
    try {
      const detail = await ctx.api(`/customer-orders/customer/${detailCustomerId}?bucket=received`, {}, 0);
      const placements = (detail.placements || []).filter(p => p.status === "received");
      const pick = placements.find(p => (p.lines || []).some(ln => ln.status === "active"
        && Number(ln.quantity) > Number(ln.quantity_billed || 0)))
        || placements.find(p => (p.lines || []).some(ln => ln.status === "active"))
        || placements[0];
      if (!pick) return ctx.toast("No incoming order to edit — place one first", "error");
      currentOrder = detail;
      await openEditPlacement(pick.id);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  async function openEditPlacement(placementId) {
    if (!currentOrder) return;
    const p = (currentOrder.placements || []).find(x => x.id === placementId);
    if (!p) return ctx.toast("Placement not found", "error");
    const active = (p.lines || []).filter(ln => ln.status === "active");
    if (!active.length) return ctx.toast("Nothing editable on this placement", "error");

    offlineEditPlacementId = placementId;
    offlineStep = 2;
    offlineCustomerId = currentOrder.customer_id;
    offlineCustomerName = currentOrder.customer_name || currentOrder.customer_label || "";
    offlineNotes = p.customer_notes || "";
    offlinePreview = null;
    offlineBusy = false;
    offlineSearchQuery = "";
    offlineSearchResults = [];
    if (p.placed_at) offlinePlacedOn = String(p.placed_at).slice(0, 10);
    try {
      await ensureEntryCatalogs();
    } catch (_) {}
    try {
      offlineLines = active.map(ln => {
        const hit = (entryItems || []).find(x => x.catalog_product_id === ln.catalog_product_id);
        const catalog = (hit && (hit.addons || hit.priced_addons)) || [];
        const keptRows = Array.isArray(ln.addons) ? ln.addons : catalog;
        const byId = new Map();
        for (const a of [...catalog, ...keptRows]) {
          if (a && a.addon_product_id != null) byId.set(Number(a.addon_product_id), a);
        }
        const addons = [...byId.values()];
        const keptIds = new Set(keptRows.map(a => Number(a.addon_product_id)));
        const legacy = ln.addons == null;
        return {
          catalog_product_id: ln.catalog_product_id,
          our_product_id: ln.our_product_id,
          quantity: ln.quantity,
          min_qty: Number(ln.quantity_billed) || 0,
          selling_price: ln.unit_price ?? hit?.selling_price,
          quantity_on_hand: hit?.quantity_on_hand,
          addons,
          priced_addons: addons.filter(a => Number(a.selling_price) > 0),
          skip_addon_ids: legacy ? [] : addons.map(a => Number(a.addon_product_id)).filter(id => !keptIds.has(id)),
        };
      });
      document.getElementById("co-offline-wizard")?.classList.remove("hidden");
      renderOfflineWizard();
    } catch (e) { ctx.toast(e.message, "error"); offlineEditPlacementId = null; }
  }

  function promptReason(title, onOk, needKey = true) {
    document.getElementById("modal-title").textContent = title;
    document.getElementById("modal-body").innerHTML = `
      ${needKey ? `<label class="label">Your cancel key</label>
      <input class="input" id="co-cancel-key" type="password" autocomplete="off" placeholder="Your own key" style="width:100%;margin-bottom:12px;" />` : ""}
      <label class="label">Reason (required)</label>
      <textarea class="input" id="co-reason-input" rows="3" style="width:100%;"></textarea>`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" id="co-reason-ok">Confirm</button>`;
    document.getElementById("co-reason-ok").onclick = () => {
      const reason = (document.getElementById("co-reason-input")?.value || "").trim();
      const passKey = (document.getElementById("co-cancel-key")?.value || "").trim();
      if (needKey && !passKey) return ctx.toast("Enter your cancel key", "error");
      if (!reason) return ctx.toast("Enter a reason", "error");
      if (needKey) window.__jcCancelKey = passKey;
      App.closeModal();
      onOk(reason);
    };
    document.getElementById("modal").classList.remove("hidden");
  }

  function cancelReceivedLine(lineId) {
    promptReason("Cancel this item", async (reason) => {
      ctx.showLoading?.();
      try {
        await ctx.api(`/customer-orders/lines/${lineId}/cancel`, {
          method: "POST",
          headers: { "X-Cancel-Key": window.__jcCancelKey || "" },
          body: JSON.stringify({ reason }),
        });
        ctx.toast("Item cancelled. Stock is back.", "success");
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/stock");
        await openDetail(detailCustomerId, currentBucket);
        loadList();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
  }

  function cancelBilledLine(lineId) {
    promptReason("Cancel this item from the bill", async (reason) => {
      ctx.showLoading?.();
      try {
        const result = await ctx.api(`/customer-orders/bill-lines/${lineId}/cancel`, {
          method: "POST",
          headers: { "X-Cancel-Key": window.__jcCancelKey || "" },
          body: JSON.stringify({ reason }),
        });
        ctx.toast(result.bill_cancelled ? "Bill cancelled. Stock is back." : "Item cancelled. Stock is back.", "success");
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/stock");
        ctx.invalidateCache?.("/accounts-receivable");
        await openDetail(detailCustomerId, currentBucket);
        loadList();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
  }

  function cancelOpenLine(lineId) {
    promptReason("Cancel line", async (reason) => {
      ctx.showLoading?.();
      try {
        await ctx.api(`/customer-orders/open-lines/${lineId}/cancel`, { method: "POST", headers: { "X-Cancel-Key": window.__jcCancelKey || "" }, body: JSON.stringify({ reason }) });
        ctx.toast("Line cancelled — billed kept", "success");
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/stock");
        await openDetail(detailCustomerId, currentBucket);
        loadList();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
  }

  function cancelPlacement(placementId) {
    const p = (currentOrder?.placements || []).find(x => x.id === placementId);
    const lines = (p?.lines || []).filter(
      ln => ln.status === "active" && Number(ln.quantity) > Number(ln.quantity_billed || 0)
    );
    if (!lines.length) return ctx.toast("Nothing open to cancel — billed qty stays", "error");
    const hasBilled = (p?.lines || []).some(ln => Number(ln.quantity_billed) > 0);
    promptReason(hasBilled ? "Cancel remaining" : "Cancel Order", async (reason) => {
      ctx.showLoading?.();
      try {
        await ctx.api(`/customer-orders/placements/${placementId}/cancel`, {
          method: "POST",
          headers: { "X-Cancel-Key": window.__jcCancelKey || "" },
          body: JSON.stringify({ reason }),
        });
        ctx.toast(hasBilled ? "Remaining cancelled — billed kept" : "Order cancelled", "success");
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/stock");
        await openDetail(detailCustomerId, hasBilled ? "received" : "cancelled");
        loadList();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
  }

  /** Re-fetch open lines by customer id — never use stale currentOrder from another party. */
  async function confirmOrder(customerId) {
    const cid = customerId || detailCustomerId;
    if (!cid) return ctx.toast("No customer", "error");
    ctx.showLoading?.();
    let detail;
    try {
      detail = await ctx.api(`/customer-orders/customer/${cid}?bucket=received`, {}, 0);
    } catch (e) {
      ctx.toast(e.message, "error");
      return;
    } finally {
      ctx.hideLoading?.();
    }

    // Build a flat list of all active lines across all received placements
    const allLines = [];
    for (const p of (detail.placements || [])) {
      for (const ln of (p.lines || [])) {
        if (ln.status === "active") {
          const existing = allLines.find(x => x.our_product_id === ln.our_product_id);
          if (existing) existing.quantity += Number(ln.quantity || 0);
          else allLines.push({ our_product_id: ln.our_product_id, quantity: Number(ln.quantity || 0), unit_price: ln.unit_price, stock: ln.stock });
        }
      }
    }
    if (!allLines.length) return ctx.toast("No items in this order", "error");
    const row = (orders || []).find(o => Number(o.customer_id) === Number(cid));
    const currentMark = row && row.marking ? row.marking : "";

    const linesHtml = allLines.map(ln =>
      `<tr>
        <td style="padding:6px 0;">${ctx.esc(ln.our_product_id)}</td>
        <td style="padding:6px 8px;text-align:right;font-weight:600;">${ln.quantity}</td>
        <td style="padding:6px 8px;text-align:right;">${ln.stock ?? 0}</td>
        <td style="padding:6px 0;text-align:right;color:var(--muted);font-size:13px;">${fmtPrice(ln.unit_price)}</td>
      </tr>`
    ).join("");

    ctx.openDetail?.(
      `Confirm order — ${ctx.esc(detail.customer_name)}`,
      `<p style="margin:0 0 12px;font-size:13px;color:var(--muted);">Review the items below and confirm.</p>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr>
          <th style="text-align:left;font-size:12px;color:var(--muted);padding-bottom:6px;border-bottom:1px solid var(--border);">Item</th>
          <th style="text-align:right;font-size:12px;color:var(--muted);padding-bottom:6px;border-bottom:1px solid var(--border);">Qty</th>
          <th style="text-align:right;font-size:12px;color:var(--muted);padding-bottom:6px;border-bottom:1px solid var(--border);">Stock</th>
          <th style="text-align:right;font-size:12px;color:var(--muted);padding-bottom:6px;border-bottom:1px solid var(--border);">Rate</th>
        </tr></thead>
        <tbody>${linesHtml}</tbody>
      </table>
      <label class="label" style="margin-top:16px;">Marking</label>
      <textarea id="co-confirm-mark" class="input" rows="3" style="background:#fee2e2;border:1px solid #dc2626;font-weight:800;color:#b91c1c;">${ctx.esc(currentMark)}</textarea>
      <div style="margin-top:16px;display:flex;flex-direction:column;gap:8px;">
        <button class="btn btn-primary" onclick="CustomerOrders._doConfirm(${cid});App.closeDetail?.()">✓ Confirm order</button>
        <button class="btn btn-secondary" onclick="App.closeDetail?.()">Close</button>
      </div>`,
      `<button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail?.()">Cancel</button>`,
      "sm"
    );
  }

  async function _doConfirm(cid) {
    const markBox = document.getElementById("co-confirm-mark");
    const body = markBox ? { marking: markBox.value || "" } : {};
    ctx.showLoading?.();
    try {
      await ctx.api(`/customer-orders/customer/${cid}/confirm`, { method: "POST", body: JSON.stringify(body) }, 0);
      ctx.toast("Order confirmed", "success");
      currentBucket = "open";
      syncHubChrome();
      await loadList();
      await openDetail(cid, "open");
    } catch (e) {
      ctx.toast(e.message, "error");
    } finally {
      ctx.hideLoading?.();
    }
  }

  async function cancelCustomerOpen(customerId) {
    const cid = customerId || detailCustomerId;
    if (!cid) return ctx.toast("No customer", "error");
    ctx.showLoading?.();
    try {
      const detail = await ctx.api(`/customer-orders/customer/${cid}?bucket=open`, {}, 0);
      const lines = (detail.open_lines || []).filter(l => Number(l.quantity_open) > 0);
      if (!lines.length) return ctx.toast("No open lines", "error");
      const hasBilled = lines.some(l => Number(l.quantity_billed) > 0);
      promptReason(hasBilled ? "Cancel remaining" : "Cancel entire order", async (reason) => {
        const cancelKey = window.__jcCancelKey || "";
        ctx.showLoading?.();
        let ok = 0;
        let failed = 0;
        let failMsg = "";
        try {
          for (const line of lines) {
            try {
              await ctx.api(`/customer-orders/open-lines/${line.id}/cancel`, {
                method: "POST",
                headers: { "X-Cancel-Key": cancelKey },
                body: JSON.stringify({ reason }),
              });
              ok += 1;
            } catch (e) {
              failed += 1;
              if (!failMsg) failMsg = e.message || "";
            }
          }
          if (failed) ctx.toast(`Cancelled ${ok}, failed ${failed}${failMsg ? " — " + failMsg : ""}`, "error");
          else ctx.toast(hasBilled ? `Remaining cancelled ${ok} — billed kept` : `Order cancelled (${ok})`, "success");
          ctx.invalidateCache?.("/customer-orders");
          ctx.invalidateCache?.("/stock");
          detailCustomerId = cid;
          currentOrder = detail;
          await openDetail(cid, "open");
          loadList();
        } catch (e) { ctx.toast(e.message, "error"); }
        finally { ctx.hideLoading?.(); }
      });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function cancelAllOpen() {
    return cancelCustomerOpen(detailCustomerId);
  }

  /** New (received) orders: one click cancels every unbilled placement, not line by line. */
  async function cancelEntireReceived(customerId) {
    const cid = customerId || detailCustomerId;
    if (!cid) return ctx.toast("No customer", "error");
    ctx.showLoading?.();
    try {
      const detail = await ctx.api(`/customer-orders/customer/${cid}?bucket=received`, {}, 0);
      const placements = (detail.placements || []).filter(p =>
        (p.lines || []).some(ln => ln.status === "active" && Number(ln.quantity) > Number(ln.quantity_billed || 0))
      );
      if (!placements.length) return ctx.toast("Nothing open to cancel", "error");
      const hasBilled = placements.some(p => (p.lines || []).some(ln => Number(ln.quantity_billed) > 0));
      promptReason(hasBilled ? "Cancel remaining on this order" : "Cancel entire order", async (reason) => {
        const cancelKey = window.__jcCancelKey || "";
        ctx.showLoading?.();
        let ok = 0;
        let failed = 0;
        let failMsg = "";
        try {
          for (const p of placements) {
            try {
              await ctx.api(`/customer-orders/placements/${p.id}/cancel`, {
                method: "POST",
                headers: { "X-Cancel-Key": cancelKey },
                body: JSON.stringify({ reason }),
              });
              ok += 1;
            } catch (e) {
              failed += 1;
              if (!failMsg) failMsg = e.message || "";
            }
          }
          if (failed) ctx.toast(`Cancelled ${ok}, failed ${failed}${failMsg ? " — " + failMsg : ""}`, "error");
          else ctx.toast(hasBilled ? "Remaining cancelled — billed kept" : "Order cancelled", "success");
          ctx.invalidateCache?.("/customer-orders");
          ctx.invalidateCache?.("/stock");
          detailCustomerId = cid;
          await openDetail(cid, hasBilled ? "received" : "cancelled");
          loadList();
        } catch (e) { ctx.toast(e.message, "error"); }
        finally { ctx.hideLoading?.(); }
      });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function closeBillLine(lineId) {
    promptReason("Close billed line", async (reason) => {
      ctx.showLoading?.();
      try {
        await ctx.api(`/customer-orders/bill-lines/${lineId}/close`, { method: "POST", body: JSON.stringify({ reason }) });
        ctx.toast("Line closed", "success");
        await openDetail(detailCustomerId, currentBucket);
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    }, false);
  }

  function cancelBill(billId, fromMoney) {
    document.getElementById("modal-title").textContent = "Cancel this bill";
    document.getElementById("modal-body").innerHTML = `
      <label class="label">Reason (required)</label>
      <textarea class="input" id="co-reason-input" rows="3" style="width:100%;"></textarea>
      <p style="font-size:13px;color:var(--muted);margin:10px 0 0;">Cancel only the bill when the order is right and the bill is wrong, such as transport or charges. The order stays booked. Cancel the complete order when this sale should not stay.</p>`;
    document.getElementById("modal-footer").innerHTML = `
      ${ctx.isOwnerAdmin?.() ? "" : `<input class="input" id="co-cancel-key" type="password" autocomplete="off" placeholder="Your cancel key" style="flex:1;min-width:140px;" />`}
      <button class="btn btn-secondary" onclick="App.closeModal()">Back</button>
      <button class="btn btn-secondary" id="co-cancel-bill-only">Cancel bill, keep order</button>
      <button class="btn btn-danger" id="co-cancel-bill-all">Cancel complete order</button>`;
    const go = (keepOrder) => {
      const reason = (document.getElementById("co-reason-input")?.value || "").trim();
      const passKey = (document.getElementById("co-cancel-key")?.value || "").trim();
      if (!ctx.isOwnerAdmin?.() && !passKey) return ctx.toast("Enter your cancel key", "error");
      if (!reason) return ctx.toast("Enter a reason", "error");
      window.__jcCancelKey = ctx.isOwnerAdmin?.() ? "" : passKey;
      const cancelKey = window.__jcCancelKey || "";
      App.closeModal();
      ctx.showLoading?.();
      ctx.api(`/customer-orders/bills/${billId}/cancel`, {
        method: "POST",
        headers: { "X-Cancel-Key": cancelKey },
        body: JSON.stringify({ reason, keep_order: keepOrder }),
      }).then(async () => {
        ctx.toast(keepOrder ? "Bill cancelled. Order stays booked." : "Bill and order cancelled. Stock released.", "success");
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/freight-agents");
        ctx.invalidateCache?.("/stock");
        ctx.invalidateCache?.("/accounts-receivable");
        if (fromMoney) await Finance.refreshOpenAr?.();
        else if (window.__jcLedgerReturn) await App.returnToLedger?.();
        else if (detailCustomerId) await openDetail(detailCustomerId, "open");
      }).catch(e => ctx.toast(e.message, "error"))
        .finally(() => ctx.hideLoading?.());
    };
    document.getElementById("co-cancel-bill-only").onclick = () => go(true);
    document.getElementById("co-cancel-bill-all").onclick = () => go(false);
    document.getElementById("modal").classList.remove("hidden");
  }

  function voidBill(billId) {
    // The promptReason modal's title already states the consequence and has its own
    // Confirm/Cancel buttons — a second native confirm() after it was a redundant
    // double dialog.
    promptReason("Void bill — Admin-only, moves to recycle bin, restorable later. Cancels first if not already cancelled.", async (reason) => {
      ctx.showLoading?.();
      try {
        await ctx.api(`/customer-orders/bills/${billId}/void`, { method: "POST", body: JSON.stringify({ reason }) });
        ctx.toast("Bill voided — moved to recycle bin", "success");
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/accounts-receivable");
        ctx.invalidateCache?.("/stock");
        await openDetail(detailCustomerId, currentBucket);
        loadList();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
  }

  function voidPlacement(placementId) {
    promptReason("Void order — Admin-only, moves to recycle bin, restorable later. Only releases unbilled qty if this order hasn't been confirmed yet (New bucket) — once confirmed, voiding hides it but leaves its reserved stock/open balance untouched.", async (reason) => {
      ctx.showLoading?.();
      try {
        await ctx.api(`/customer-orders/placements/${placementId}/void`, { method: "POST", body: JSON.stringify({ reason }) });
        ctx.toast("Order voided — moved to recycle bin", "success");
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/stock");
        await openDetail(detailCustomerId, currentBucket);
        loadList();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
  }

  let billConfirmDuplicate = false;

  function buildProcessBody() {
    const discOn = discountEnabled;
    const lines = processLines
      .filter(l => Number(l.quantity_to_ship) > 0)
      .map(l => {
        const row = {
          catalog_product_id: l.catalog_product_id,
          quantity_to_ship: Number(l.quantity_to_ship),
          quantity: Number(l.quantity_to_ship),
        };
        row.skip_addon_ids = (l.skip_addon_ids || []).map(Number);
        if (l.direct) row.direct = true;
        if (discOn && !useOverallDiscount) {
          const hasPct = l.discount_percent !== "" && l.discount_percent != null && Number.isFinite(Number(l.discount_percent));
          const hasNet = l.net_rate !== "" && l.net_rate != null && Number.isFinite(Number(l.net_rate));
          if (l.discSource === "net" && hasNet) {
            row.net_rate = Number(l.net_rate);
          } else if (hasPct) {
            row.discount_percent = Number(l.discount_percent);
          } else if (hasNet) {
            row.net_rate = Number(l.net_rate);
          }
        }
        return row;
      });
    const extra = additionalCharges.filter(c => c.name.trim() && c.amount.trim() && Number(c.amount) > 0)
      .map(c => ({ name: c.name.trim(), amount: String(c.amount) }));
    const catalogs = !editBillId ? Object.entries(pickedCatalogs).map(([id, price]) => ({
      catalog_id: Number(id),
      price: String(price === "" || price == null ? "0" : price),
    })) : [];
    const body = {
      lines,
      gst_enabled: gstEnabled,
      gst_rate_percent: Number(gstRate) || 18,
      narration: narration.trim() || null,
      additional_charges: extra,
      catalogs,
      force_credit_override: !!forceCreditOverride,
      confirm_duplicate: !!billConfirmDuplicate,
    };
    if (!editBillId) body.bill_series_id = Number(billSeriesId);
    if (discOn && useOverallDiscount && overallDiscount.trim()) {
      body.overall_discount_percent = Number(overallDiscount);
    }
    if (!transportMode) {
      /* router rejects missing mode */
    } else {
      body.transport_mode = transportMode;
    }
    if (transportMode === "transport" && transportReceiptNumber.trim()) {
      body.transport_receipt_number = transportReceiptNumber.trim();
    }
    if (transportMode === "bus" && freightAgentId) body.freight_agent_id = Number(freightAgentId);
    if (transportMode === "bus" || transportMode === "transport") {
      if (freightCharges.trim() !== "") body.freight_charges = String(freightCharges);
    }
    if (packagingCharges.trim()) body.packaging_charges = String(packagingCharges);
    if (billDate) body.bill_date = billDate;
    if (!editBillId && selectedPlacementIds.length) body.placement_ids = selectedPlacementIds.map(Number);
    if (!editBillId && processContext?.commission_agent_id) body.on_commission_agent = !!billOnAgent;
    return body;
  }

  function partyMarkerBadgesHtml(pctx) {
    if (!pctx) return "";
    let h = "";
    if (pctx.marker_1) h += ` <span class="badge badge-blue" style="font-size:11px;">${ctx.esc(pctx.marker_1)}</span>`;
    if (pctx.marker_2) h += ` <span class="badge badge-amber" style="font-size:11px;">${ctx.esc(pctx.marker_2)}</span>`;
    if (pctx.payment_type === "CASH") h += ` <span class="badge badge-amber" style="font-size:11px;">CASH</span>`;
    return h;
  }

  function cashWarningHtml(o) {
    if ((o?.payment_type || "").toUpperCase() !== "CASH") return "";
    return `<div style="padding:8px 14px;margin-bottom:10px;background:#fef3c7;border:1px solid #fde68a;border-radius:6px;font-size:13px;">⚠ <strong>CASH customer</strong> — collect payment at time of billing.</div>`;
  }

  function creditBannerHtml(cr, { afterBill = false } = {}) {
    if (!cr) return "";
    const fmtMoney = v => Math.abs(Number(v)).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const colorMoney = v => {
      const n = Number(v);
      const color = n > 0 ? "#dc2626" : n < 0 ? "#16a34a" : "inherit";
      const label = n > 0 ? `₹${fmtMoney(n)} due` : n < 0 ? `₹${fmtMoney(n)} credit` : "₹0";
      return `<span style="color:${color};">${label}</span>`;
    };
    // track_only = credit_limit is 0 (informational, never enforced)
    if (cr.track_only || cr.unlimited) {
      const currentOut = Number(cr.outstanding || cr.used || 0);
      const afterOut = Number(cr.used_after_bill || currentOut);
      const showAfter = afterBill && Math.abs(afterOut - currentOut) > 0.001;
      return `<div class="card" style="padding:10px 14px;margin-bottom:12px;background:#f8fafc;border:1px solid var(--border);display:flex;gap:20px;flex-wrap:wrap;align-items:center;font-size:13px;">
        <span><strong>Outstanding:</strong> ${colorMoney(currentOut)}</span>
        ${showAfter ? `<span><strong>After this bill:</strong> ${colorMoney(afterOut)}</span>` : ""}
        <span style="color:var(--muted);">Credit limit: ${cr.track_only ? "not set — outstanding tracked only, never blocks billing" : "Unlimited"}</span>
      </div>`;
    }
    const left = afterBill ? cr.left_after_bill : cr.left;
    const used = afterBill ? cr.used_after_bill : cr.used;
    // Only show "over limit" warning when a real limit is set and it is truly exceeded
    const over = !cr.track_only && !cr.unlimited && cr.would_exceed;
    const bg = over ? "#fef2f2" : "#f0fdf4";
    const border = over ? "#fecaca" : "#bbf7d0";
    return `<div class="card" style="padding:12px 14px;margin-bottom:12px;background:${bg};border:1px solid ${border};">
      <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;">
        <div><strong>Outstanding</strong> ₹${ctx.esc(used)}</div>
        <div>Credit limit ₹${ctx.esc(cr.credit_limit)} · Available ₹${ctx.esc(left)}</div>
      </div>
      ${over ? `<p style="margin:8px 0 0;font-size:13px;color:#b91c1c;">⚠ This bill will push the customer over their credit limit — you can still proceed.</p>` : ""}
    </div>`;
  }

  async function processFromHub(customerId, bucket) {
    detailCustomerId = customerId;
    currentBucket = bucket || "open";
    await processOrder();
  }

  /** Confirm received order (if any), then open bill wizard. Used by post-place "Bill now". */
  async function billNow(customerId) {
    if (!customerId) return;
    App.closeDetail?.();
    ctx.showLoading?.();
    try {
      try {
        await ctx.api(`/customer-orders/customer/${customerId}/confirm`, { method: "POST", body: "{}" }, 0);
        ctx.invalidateCache?.("/customer-orders");
      } catch (e) {
        const msg = String(e.message || "").toLowerCase();
        if (!msg.includes("no pending") && !msg.includes("nothing to confirm")) throw e;
      }
      detailCustomerId = customerId;
      currentBucket = "open";
      await processOrder();
    } catch (e) {
      ctx.toast(e.message || "Could not bill", "error");
    } finally {
      ctx.hideLoading?.();
    }
  }

  async function processOrder(opts) {
    if (!detailCustomerId) return;
    const quiet = !!(opts && opts.quiet);
    editBillId = null;
    processStep = 1;
    billableOrders = [];
    selectedPlacementIds = [];
    processBusy = false;
    previewTotals = null;
    forceCreditOverride = false;
    if (!quiet) ctx.showLoading?.();
    try {
      try { await ctx.api("/bill-series/ensure-next", { method: "POST" }, 0); } catch (_) {}
      const [pctx, agents, series] = await Promise.all([
        ctx.api(`/customer-orders/customer/${detailCustomerId}/process-context`, {}, 0),
        ctx.api("/freight-agents?names_only=1", {}, 30000),
        ctx.api("/bill-series", {}, 0),
      ]);
      processContext = pctx;
      billOnAgent = true;
      freightAgents = agents || [];
      billSeries = (series || []).filter(s => s.is_active && s.current_num < s.end_num);
      billableOrders = pctx.orders || [];
      selectedPlacementIds = billableOrders.map(o => Number(o.placement_id));
      processLines = (pctx.lines || []).map(l => ({
        ...l,
        quantity_to_ship: l.quantity_open,
        discount_percent: "",
        net_rate: calcNetFromDisc(l.unit_price, 0),
        discSource: "",
        addons: l.addons || [],
        skip_addon_ids: [],
      }));
      if (billableOrders.length) applySelectedOrders();
      if (!processLines.length && billableOrders.length) {
        processLines = billableOrders.flatMap(order => (order.lines || []).map(ln => ({
          catalog_product_id: ln.catalog_product_id,
          our_product_id: ln.our_product_id,
          unit_price: ln.unit_price,
          quantity_open: Number(ln.quantity) || 0,
          quantity_to_ship: Number(ln.quantity) || 0,
          quantity_on_hand: ln.quantity_on_hand,
          discount_percent: "",
          net_rate: calcNetFromDisc(ln.unit_price, 0),
          discSource: "",
          addons: ln.addons || [],
          skip_addon_ids: [],
        }))).filter(l => l.quantity_to_ship > 0);
      }
      discountEnabled = false;
      useOverallDiscount = false;
      overallDiscount = "";
      gstEnabled = false;
      gstRate = "18";
      freightAgentId = "";
      freightHandler = "";
      freightCharges = "";
      transportMode = "self_pickup";
      transportReceiptNumber = "";
      packagingCharges = "";
      additionalCharges = [{ name: "", amount: "" }];
      billSeriesId = defaultBillSeriesId(billSeries);
      customerNotes = pctx.customer_marking || "";
      narration = "";
      dueCatalogs = [];
      pickedCatalogs = {};
      try { dueCatalogs = await ctx.api(`/our-catalogs/for-customer/${detailCustomerId}`, {}, 0) || []; } catch (_) { dueCatalogs = []; }
      billDate = localToday();
      billEditSearch = "";
      processStep = billableOrders.length ? 0 : 1;
      document.getElementById("co-wizard")?.classList.remove("hidden");
      try { await ensureEntryCatalogs(); } catch (_) {}
      renderProcessWizard();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { if (!quiet) ctx.hideLoading?.(); }
  }

  async function editLatestBill(customerId) {
    if (!customerId) return;
    ctx.showLoading?.();
    try {
      const detail = await ctx.api(`/customer-orders/customer/${customerId}?bucket=billed`, {}, 0);
      const bills = detail?.bills || [];
      if (!bills.length) return ctx.toast("No bills to edit", "error");
      const editable = bills.find(b => (b.lines || []).length && (b.lines || []).every(ln => ln.status === "billed") && billEditableToday(b.created_at));
      if (!editable) return ctx.toast("You can edit a bill only on the day it was made", "error");
      const bill = editable;
      detailCustomerId = customerId;
      currentOrder = detail;
      await openEditBill(bill.id);
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function defaultBillSeriesId(rows) {
    const letters = (rows || []).filter(s => /^[A-Za-z]$/.test(String(s.prefix || "").trim()) && Number(s.start_num) === 1 && Number(s.end_num) === 1000);
    letters.sort((a, b) => String(a.prefix).toUpperCase().localeCompare(String(b.prefix).toUpperCase()));
    if (letters.length) return String(letters[letters.length - 1].id);
    const actual = (rows || []).find(s => String(s.name || "").trim().toLowerCase() === "actual");
    return String((actual || (rows || [])[0] || {}).id || "");
  }

  function askEditCancelKey() {
    if (ctx.isOwnerAdmin?.()) {
      window.__jcCancelKey = "";
      return Promise.resolve(true);
    }
    // The bill screen is a full-page layer. A second dialog opens underneath it,
    // so the key has to sit in this screen's own footer.
    return new Promise(resolve => {
      const footer = document.getElementById("co-wizard-footer");
      if (!footer) {
        resolve(false);
        return;
      }
      footer.innerHTML = `
        <input class="input" id="co-edit-cancel-key" type="password" autocomplete="off" placeholder="Your cancel key" style="flex:1;min-width:160px;" />
        <button type="button" class="btn btn-secondary" id="co-edit-key-back">Back</button>
        <button type="button" class="btn btn-primary" id="co-edit-key-ok">Save bill</button>`;
      const input = document.getElementById("co-edit-cancel-key");
      input?.focus();
      const stop = (ok) => resolve(ok);
      document.getElementById("co-edit-key-back").onclick = () => {
        renderProcessWizard();
        stop(false);
      };
      const go = () => {
        const key = (input?.value || "").trim();
        if (!key) return ctx.toast("Enter your cancel key", "error");
        window.__jcCancelKey = key;
        stop(true);
      };
      document.getElementById("co-edit-key-ok").onclick = go;
      input?.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    });
  }

  async function openEditBill(billId) {
    if (!billId) return;
    editBillId = billId;
    processStep = 1;
    processBusy = false;
    previewTotals = null;
    forceCreditOverride = false;
    ctx.showLoading?.();
    try {
      const [bill, agents] = await Promise.all([
        ctx.api(`/customer-orders/bills/${billId}`, {}, 0),
        ctx.api("/freight-agents?names_only=1", {}, 30000),
      ]);
      if (bill.cancelled_at) {
        ctx.toast("Cannot edit — bill cancelled", "error");
        editBillId = null;
        return;
      }
      if (!billEditableToday(bill.created_at)) {
        ctx.toast("You can edit a bill only on the day it was made", "error");
        editBillId = null;
        return;
      }
      if ((bill.lines || []).some(ln => ln.status === "closed")) {
        ctx.toast("Cannot edit — close was done. Cancel close first or edit before Close.", "error");
        editBillId = null;
        return;
      }
      detailCustomerId = bill.customer_id || detailCustomerId;
      processContext = {
        customer_id: bill.customer_id,
        customer_name: currentOrder?.customer_name || "",
        commission_agent_name: bill.commission_agent_name || "",
        commission_agent_id: bill.commission_agent_id || null,
      };
      // City wasn't already on hand here (bill/detail payloads don't carry it) — fetch
      // it separately for the review screen's "Customer / City" line. Best-effort only.
      ctx.api(`/customers/${bill.customer_id}`, {}, 30000).then(c => {
        if (processContext && processContext.customer_id === bill.customer_id) {
          processContext.city_name = c?.city_name || null;
          renderProcessWizard();
        }
      }).catch(() => {});
      freightAgents = agents || [];
      billSeries = [];
      processLines = (bill.lines || []).filter(ln => ln.status === "billed").map(l => ({
        catalog_product_id: l.catalog_product_id,
        our_product_id: l.our_product_id,
        unit_price: l.unit_price,
        quantity_open: 999999,
        bill_line_id: l.id,
        quantity_booked: l.quantity_shipped,
        quantity_on_hand: l.stock ?? "—",
        quantity_to_ship: l.quantity_shipped,
        discount_percent: l.discount_percent || "",
        net_rate: l.net_rate || (l.discount_percent
          ? calcNetFromDisc(l.unit_price, l.discount_percent)
          : calcNetFromDisc(l.unit_price, 0)),
        discSource: l.price_entry === "net" ? "net" : (l.discount_percent ? "pct" : (l.net_rate ? "net" : "")),
        addons: l.addons || [],
      }));
      editBillOriginalQty = {};
      for (const l of processLines) editBillOriginalQty[l.catalog_product_id] = Number(l.quantity_to_ship) || 0;
      if (!processLines.length) {
        ctx.toast("No editable lines on this bill", "error");
        editBillId = null;
        return;
      }
      const hasOverall = bill.discount_percent != null && Number(bill.discount_percent) > 0;
      const hasLineDisc = processLines.some(l => l.discount_percent && Number(l.discount_percent) > 0);
      discountEnabled = hasOverall || hasLineDisc;
      useOverallDiscount = hasOverall;
      overallDiscount = hasOverall ? String(bill.discount_percent) : "";
      gstEnabled = !!bill.gst_enabled;
      gstRate = bill.gst_rate_percent != null ? String(bill.gst_rate_percent) : "18";
      freightAgentId = bill.freight_agent_id != null ? String(bill.freight_agent_id) : "";
      freightHandler = bill.freight_handler || "";
      if ((bill.transport_mode || (bill.freight_agent_id ? "bus" : "")) === "bus" && !freightAgentId) {
        freightAgentId = defaultFreightAgentId();
      }
      freightCharges = bill.freight_charges != null ? String(bill.freight_charges) : "";
      transportMode = bill.transport_mode || (bill.freight_agent_id ? "bus" : (Number(bill.freight_charges) > 0 ? "transport" : "self_pickup"));
      transportReceiptNumber = bill.transport_receipt_number || "";
      packagingCharges = bill.packaging_charges != null ? String(bill.packaging_charges) : "";
      const keptCharges = (bill.additional_charges || []).filter(c => {
        const n = String(c.name || "").trim().toLowerCase().replace(/[_-]/g, " ");
        return !n.includes("name plate") && !n.includes("initial plate");
      });
      additionalCharges = keptCharges.length
        ? keptCharges.map(c => ({ name: c.name || "", amount: String(c.amount || "") }))
        : [{ name: "", amount: "" }];
      billSeriesId = bill.bill_series_id != null ? String(bill.bill_series_id) : "";
      editBillNumber = bill.bill_number || "";
      billDate = bill.bill_date ? String(bill.bill_date).slice(0, 10) : localToday();
      customerNotes = "";
      narration = onlyMark(bill.narration || "");
      billEditSearch = "";
      billEditProducts = [];
      billEditSearchPending = false;
      document.getElementById("co-wizard")?.classList.remove("hidden");
      try { await ensureEntryCatalogs(); } catch (_) {}
      const chargeList = bill.additional_charges || [];
      processLines = processLines.map(l => {
        const hit = (entryItems || []).find(x => x.catalog_product_id === l.catalog_product_id);
        const ready = billLineAddonState(l, (hit && (hit.addons || hit.priced_addons)) || [], chargeList);
        return { ...l, ...ready };
      });
      renderProcessWizard();
    } catch (e) { ctx.toast(e.message, "error"); editBillId = null; }
    finally { ctx.hideLoading?.(); }
  }

  function closeProcessWizard(opts) {
    document.getElementById("co-wizard")?.classList.add("hidden");
    editBillId = null;
    editBillNumber = "";
    editBillOriginalQty = {};
    if (opts && opts.done && window.__jcLedgerReturn) {
      App.returnToLedger?.();
      return;
    }
    if (window.__jcLedgerReturn && window.__jcLedgerReturn.kind === "money") window.__jcLedgerReturn = null;
  }

  /** Lines whose qty on this bill edit dropped below what was originally billed —
   * saving will restore stock and shrink the customer's order for that qty. */
  function _billEditShrinkLines() {
    if (!editBillId) return [];
    const currentByCid = {};
    for (const l of processLines) currentByCid[l.catalog_product_id] = Number(l.quantity_to_ship) || 0;
    const out = [];
    for (const [cidStr, origQty] of Object.entries(editBillOriginalQty)) {
      const cid = Number(cidStr);
      const newQty = currentByCid[cid] || 0; // 0 if the line was removed entirely
      if (newQty < origQty) {
        const line = processLines.find(l => l.catalog_product_id === cid);
        out.push({ our_product_id: line ? line.our_product_id : cid, from: origQty, to: newQty });
      }
    }
    return out;
  }

  function promptEditBillNumber(billId, current) {
    ctx.openDetail?.("Edit bill number", `
      <p style="margin:0 0 12px;color:var(--muted);font-size:13px;">Temporary correction. Must be unique among open bills.</p>
      <label class="label">Bill number</label>
      <input class="input" id="co-edit-bill-num" value="${ctx.esc(current || "")}" />
    `, `
      <button class="btn btn-secondary" style="flex:1;" onclick="App.closeDetail()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="CustomerOrders.saveBillNumber(${billId})">Save</button>
    `, "sm");
  }

  async function saveBillNumber(billId) {
    const num = (document.getElementById("co-edit-bill-num")?.value || "").trim();
    if (!num) return ctx.toast("Bill number required", "error");
    ctx.showLoading?.();
    try {
      const res = await ctx.api(`/customer-orders/bills/${billId}/number`, {
        method: "PATCH",
        body: JSON.stringify({ bill_number: num }),
      }, 0);
      ctx.toast(`Bill number → ${res.bill_number}`, "success");
      App.closeDetail?.();
      ctx.invalidateCache?.("/customer-orders");
      if (detailCustomerId) await openDetail(detailCustomerId, "billed");
      else await loadList();
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function enableDiscount() {
    discountEnabled = true;
    useOverallDiscount = false;
    overallDiscount = "";
    renderProcessWizard();
  }

  function clearDiscount() {
    discountEnabled = false;
    useOverallDiscount = false;
    overallDiscount = "";
    processLines.forEach(l => { l.discount_percent = ""; l.net_rate = ""; l.discSource = ""; });
    renderProcessWizard();
  }

  function addBillEditProduct(catalogProductId) {
    const p = billEditProducts.find(x => x.catalog_product_id === catalogProductId);
    if (!p) return;
    if (processLines.some(l => l.catalog_product_id === catalogProductId)) {
      return ctx.toast("Already on bill", "error");
    }
    const direct = !editBillId;
    if (direct) {
      const booked = (processContext?.lines || []).some(l => Number(l.catalog_product_id) === Number(catalogProductId) && Number(l.quantity_open) > 0);
      if (booked) return ctx.toast("Already booked — tick that order", "error");
      if (p.selling_price == null || p.selling_price === "") return ctx.toast("Sell price not set", "error");
    }
    processLines.push({
      catalog_product_id: p.catalog_product_id,
      our_product_id: p.our_product_id,
      marking: p.marking || "",
      unit_price: p.selling_price,
      quantity_open: direct ? signedStock(p.quantity_on_hand) : 999999,
      quantity_on_hand: signedStock(p.quantity_on_hand),
      quantity_to_ship: "",
      discount_percent: "",
      net_rate: "",
      discSource: "",
      addons: (p.addons && p.addons.length) ? p.addons : (p.priced_addons || []),
      skip_addon_ids: [],
      direct,
    });
    billEditSearch = "";
    const focusIdx = processLines.length - 1;
    renderProcessWizard();
    requestAnimationFrame(() => {
      const qty = document.querySelector(`[data-ship-for="${focusIdx}"]`);
      if (!qty) return;
      qty.focus();
      qty.select();
    });
  }

  async function cancelProcessLine(idx) {
    const ln = processLines[idx];
    if (!ln) return;
    promptReason("Cancel this item", async (reason) => {
      ctx.showLoading?.();
      try {
        const headers = { "X-Cancel-Key": window.__jcCancelKey || "" };
        if (ln.bill_line_id) {
          const result = await ctx.api(`/customer-orders/bill-lines/${ln.bill_line_id}/cancel`, {
            method: "POST", headers, body: JSON.stringify({ reason }),
          });
          ctx.toast(result.bill_cancelled ? "Bill cancelled. Stock is back." : "Item cancelled. Stock is back.", "success");
          ctx.invalidateCache?.("/customer-orders");
          ctx.invalidateCache?.("/stock");
          if (result.bill_cancelled) {
            closeProcessWizard({ done: true });
            if (detailCustomerId) await openDetail(detailCustomerId, "billed");
          } else {
            await openEditBill(editBillId);
          }
        } else if (ln.open_line_id) {
          await ctx.api(`/customer-orders/open-lines/${ln.open_line_id}/cancel`, {
            method: "POST", headers, body: JSON.stringify({ reason }),
          });
          ctx.toast("Item cancelled. Stock is back.", "success");
          ctx.invalidateCache?.("/customer-orders");
          ctx.invalidateCache?.("/stock");
          await processOrder({ quiet: true });
        }
        loadList();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    });
  }

  function removeProcessLine(idx) {
    const ln = processLines[idx];
    if (!ln) return;
    if (!editBillId && !ln.direct) return;
    if (editBillId && processLines.length <= 1) return ctx.toast("Bill needs at least one product", "error");
    processLines.splice(idx, 1);
    renderProcessWizard();
  }

  function setShipQty(idx, val) {
    const ln = processLines[idx];
    if (!ln) return;
    if (val === "" || val == null) {
      ln.quantity_to_ship = "";
      renderWizardTotalsBar();
      return;
    }
    let q = Math.max(0, parseInt(val, 10) || 0);
    ln.quantity_to_ship = q;
    renderWizardTotalsBar();
  }

  function setLineDisc(idx, val) {
    const ln = processLines[idx];
    if (!ln) return;
    ln.discount_percent = val;
    ln.discSource = val === "" || val == null ? "" : "pct";
    ln.net_rate = val === "" || val == null ? "" : calcNetFromDisc(ln.unit_price, val);
    const net = document.querySelector(`[data-net-for="${idx}"]`);
    if (net && document.activeElement !== net) net.value = ln.net_rate ?? "";
    renderWizardTotalsBar();
  }

  function setLineNetRate(idx, val) {
    const ln = processLines[idx];
    if (!ln) return;
    ln.net_rate = val;
    ln.discSource = val === "" || val == null ? "" : "net";
    if (val === "" || val == null) {
      ln.discount_percent = "";
      renderWizardTotalsBar();
      return;
    }
    ln.discount_percent = calcDiscFromNet(ln.unit_price, val);
    discountEnabled = true;
    useOverallDiscount = false;
    const disc = document.querySelector(`[data-disc-for="${idx}"]`);
    if (disc && document.activeElement !== disc) disc.value = ln.discount_percent ?? "";
    renderWizardTotalsBar();
  }

  /** Running qty/amount from the line items alone (pre-GST/pre-freight/pre-charges) —
   * kept visible on every wizard step (not just Review) since staff use it to judge
   * additional charges while still on the Transport/Charges steps. */
  function wizardLinesTotals() {
    let qty = 0, amount = 0;
    for (const ln of processLines) {
      const q = Number(ln.quantity_to_ship) || 0;
      if (q <= 0) continue;
      qty += q;
      const rate = useOverallDiscount && overallDiscount
        ? Number(calcNetFromDisc(ln.unit_price, overallDiscount)) || 0
        : (Number(ln.net_rate) || Number(calcNetFromDisc(ln.unit_price, ln.discount_percent || 0)) || 0);
      amount += q * rate;
      const skipped = new Set((ln.skip_addon_ids || []).map(Number));
      for (const a of ln.addons || []) {
        if (skipped.has(Number(a.addon_product_id))) continue;
        const price = addonEachPrice(a);
        if (!(price > 0)) continue;
        amount += price * (Number(a.quantity) || 1) * q;
      }
    }
    let extra = 0;
    if ((transportMode === "bus" || transportMode === "transport") && String(freightCharges || "").trim() !== "") {
      extra += Number(freightCharges) || 0;
    }
    if (String(packagingCharges || "").trim() !== "") extra += Number(packagingCharges) || 0;
    for (const c of additionalCharges || []) extra += Number(c.amount) || 0;
    for (const price of Object.values(pickedCatalogs)) extra += Number(price) || 0;
    return { qty, amount: amount + extra };
  }

  function reviewChargeRows(tot, chargeLabel) {
    const rows = [];
    const freight = Number(tot.freight_charges) || 0;
    if (freight > 0 && transportMode !== "self_pickup") {
      rows.push([chargeLabel, fmtPrice(freight)]);
    }
    const packaging = Number(tot.packaging_charges) || 0;
    if (packaging > 0) rows.push(["Packaging", fmtPrice(packaging)]);
    for (const c of tot.additional_charges || []) {
      if (!(Number(c.amount) > 0)) continue;
      rows.push([c.name || "Other charges", fmtPrice(c.amount)]);
    }
    rows.push(["Grand total", fmtPrice(tot.rounded_grand_total || tot.grand_total)]);
    return rows.map((row, i) => {
      const last = i === rows.length - 1;
      return `<tr style="${last ? "font-weight:700;border-top:2px solid var(--border);" : ""}">
        <td colspan="5">${ctx.esc(row[0])}</td><td>${row[1]}</td>
      </tr>`;
    }).join("");
  }

  function renderWizardTotalsBar() {
    const bar = document.getElementById("co-wizard-totals");
    if (!bar) return;
    const { qty, amount } = wizardLinesTotals();
    bar.innerHTML = qty > 0
      ? `<span><span class="wtb-muted">Total qty</span>${qty}</span><span><span class="wtb-muted">Total amount</span>${fmtPrice(amount)}</span>`
      : "";
  }

  function transportFieldsHtml() {
    if (transportMode === "bus") {
      return `
        <label class="label">Freight agent</label>
        <select class="input" onchange="CustomerOrders.setFreightAgent(this.value)">
          <option value="">—</option>
          ${freightAgents.map(a => `<option value="${a.id}" ${String(a.id) === String(freightAgentId) ? "selected" : ""}>${ctx.esc(a.name)}</option>`).join("")}
        </select>
        <label class="label">Freight (₹)</label>
        <input id="co-freight-amount" class="input" value="${ctx.esc(freightCharges)}" oninput="CustomerOrders.setFreightCharges(this.value)" />`;
    }
    if (transportMode === "transport") {
      return `
        <label class="label">Transport (₹)</label>
        <input id="co-freight-amount" class="input" value="${ctx.esc(freightCharges)}" oninput="CustomerOrders.setFreightCharges(this.value)" />
        <label class="label">Receipt number</label>
        <input class="input" value="${ctx.esc(transportReceiptNumber)}" oninput="CustomerOrders.setTransportReceipt(this.value)" />`;
    }
    if (transportMode === "self_pickup") return `<p style="margin:8px 0 0;font-size:13px;color:var(--muted);">Customer picks up.</p>`;
    return "";
  }

  function partyHeadingHtml(pctx) {
    if (!pctx) return "";
    const city = pctx.city_name ? ` · ${ctx.esc(pctx.city_name)}` : "";
    const num = pctx.party_number ? "#" + pctx.party_number + " " : "";
    return `<p style="margin:0 0 12px;"><strong>${num}${ctx.esc(pctx.customer_name || "")}${city}</strong>${partyMarkerBadgesHtml(pctx)}</p>`;
  }

  function renderProcessWizard() {
    const stepsEl = document.getElementById("co-wizard-steps");
    const bodyEl = document.getElementById("co-wizard-body");
    const footerEl = document.getElementById("co-wizard-footer");
    if (!stepsEl || !bodyEl || !footerEl) return;
    stepsEl.innerHTML = "";
    renderWizardTotalsBar();
    const title = document.getElementById("co-wizard-title");
    if (title) title.textContent = editBillId ? `Edit ${editBillNumber || "bill"}` : "Bill";
    const lineDiscLocked = !discountEnabled || useOverallDiscount;
    const ro = lineDiscLocked ? "readonly" : "";
    const ordersHtml = (!editBillId && billableOrders.length) ? `
      <label class="label">Orders still to bill</label>
      <p style="margin:0 0 8px;font-size:13px;color:var(--muted);">Already billed orders are not listed. Uncheck a hold if it should not go on this bill.</p>
      <button type="button" class="btn btn-secondary btn-sm" style="margin:0 0 10px;" onclick="CustomerOrders.toggleAllBillOrders(false)">Deselect all</button>
      ${billableOrders.map(order => {
        const on = selectedPlacementIds.includes(Number(order.placement_id));
        const when = ctx.fmtWhen ? ctx.fmtWhen(order.placed_at) : (ctx.fmtDay ? ctx.fmtDay(order.placed_at) : "Order");
        const bits = (order.lines || []).map(ln => `${ctx.esc(ln.our_product_id)} × ${ln.quantity} · stock ${ln.quantity_on_hand ?? 0}`).join(", ");
        return `<div style="margin:0 0 8px;padding:8px 10px;border:1px solid #e2e8f0;border-radius:8px;">
          <label style="display:block;font-size:14px;">
            <input type="checkbox" ${on ? "checked" : ""} onchange="CustomerOrders.toggleBillOrder(${order.placement_id}, this.checked)" />
            ${ctx.esc(when)} · ${bits}
          </label>
          ${markingBanner(order.customer_notes)}
        </div>`;
      }).join("")}` : "";
    const linesHtml = processLines.map((ln, i) => {
      const shownNet = useOverallDiscount && overallDiscount
        ? calcNetFromDisc(ln.unit_price, overallDiscount)
        : (ln.net_rate || calcNetFromDisc(ln.unit_price, ln.discount_percent || 0));
      const shownDisc = useOverallDiscount ? (overallDiscount || "") : (ln.discount_percent || "");
      const stock = signedStock(ln.quantity_on_hand);
      const ship = signedStock(ln.quantity_to_ship);
      const short = ship > stock;
      return `<tr style="${short ? "background:#fef2f2;" : ""}">
        <td><strong>${ctx.esc(ln.our_product_id)}</strong>${ln.marking ? ` <span class="marking-flag">${ctx.esc(ln.marking)}</span>` : ""}${ln.direct ? ` <span style="font-size:12px;color:var(--muted);">direct</span>` : ""}${billAddonHtml(ln)}${short ? `<div style="color:#b91c1c;font-weight:800;font-size:12px;">Only ${stock} in stock</div>` : ""}</td>
        <td style="${short ? "color:#b91c1c;font-weight:800;" : ""}">${stock}</td>
        <td>${fmtPrice(ln.unit_price)}</td>
        <td><input data-ship-for="${i}" type="number" class="input" style="width:72px;${short ? "border-color:#dc2626;background:#fff1f2;" : ""}" min="0" value="${ln.quantity_to_ship ?? ""}" oninput="CustomerOrders.setShipQty(${i}, this.value)" onkeydown="if(event.key==='Enter'){event.preventDefault();CustomerOrders.focusNextBillItem();}" /></td>
        <td><input data-disc-for="${i}" type="number" class="input" style="width:72px;" min="0" max="100" step="0.1" ${ro} value="${ctx.esc(shownDisc)}" oninput="CustomerOrders.setLineDisc(${i}, this.value)" /></td>
        <td><input data-net-for="${i}" type="number" class="input" style="width:88px;" min="0" step="0.01" ${ro} value="${ctx.esc(shownNet || "")}" oninput="CustomerOrders.setLineNetRate(${i}, this.value)" /></td>
        <td style="white-space:nowrap;">
          ${(ln.open_line_id || ln.bill_line_id) ? `<button type="button" class="btn btn-danger btn-sm" onclick="CustomerOrders.cancelProcessLine(${i})">Cancel</button>` : ""}
          ${(editBillId || ln.direct) ? `<button type="button" class="btn btn-ghost btn-sm" onclick="CustomerOrders.removeProcessLine(${i})">Remove</button>` : ""}
        </td>
      </tr>`;
    }).join("");
    const addProd = `
      <label class="label">Add products</label>
      <input id="co-bill-edit-search" class="input" placeholder="Item number" oninput="CustomerOrders.setBillEditSearch(this.value)" />
      <div id="co-bill-edit-matches"></div>`;
    bodyEl.innerHTML = `
      ${partyHeadingHtml(processContext)}
      ${processContext?.commission_agent_name && !editBillId ? `<div style="margin:0 0 12px;padding:12px;background:#fef3c7;border:2px solid #d97706;border-radius:12px;">
        <span style="display:block;font-size:12px;font-weight:700;letter-spacing:.04em;">BILL THIS ON</span>
        <label style="display:block;margin-top:8px;font-size:16px;"><input type="radio" name="co-bill-on" ${billOnAgent ? "checked" : ""} onchange="CustomerOrders.setBillOnAgent(true)" /> ${ctx.esc(processContext.commission_agent_name)} <span style="font-size:13px;color:#92400e;">commission agent · due on the agent · agent name on the bill</span></label>
        <label style="display:block;margin-top:6px;font-size:16px;"><input type="radio" name="co-bill-on" ${billOnAgent ? "" : "checked"} onchange="CustomerOrders.setBillOnAgent(false)" /> ${ctx.esc(processContext.customer_name || "Party")} <span style="font-size:13px;color:#92400e;">direct order · due on the party · no agent on the bill</span></label>
      </div>` : ""}
      ${cashWarningHtml(processContext)}
      ${!editBillId ? creditBannerHtml(processContext?.credit) : ""}
      ${ordersHtml}
      <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin:8px 0 12px;font-size:14px;">
        <label><input type="radio" name="co-disc-mode" ${!discountEnabled ? "checked" : ""} onchange="CustomerOrders.setDiscToggle('off')" /> No discount</label>
        <label><input type="radio" name="co-disc-mode" ${discountEnabled && !useOverallDiscount ? "checked" : ""} onchange="CustomerOrders.setDiscToggle('line')" /> Per item</label>
        <label><input type="radio" name="co-disc-mode" ${discountEnabled && useOverallDiscount ? "checked" : ""} onchange="CustomerOrders.setDiscToggle('overall')" /> Overall %</label>
        ${discountEnabled && useOverallDiscount ? `<input class="input" style="width:80px;" placeholder="%" value="${ctx.esc(overallDiscount)}" oninput="CustomerOrders.setOverallDisc(this.value)" />` : ""}
      </div>
      ${catalogChecksHtml()}
      <table class="data"><thead><tr>
        <th>Item</th><th>Stock</th><th>Rate</th><th>Qty</th><th>Disc %</th><th>Net</th><th></th>
      </tr></thead><tbody>${linesHtml || `<tr><td colspan="7" style="color:var(--muted);">No items. Add a product below.</td></tr>`}</tbody></table>
      ${addProd}
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px;">
        <div>
          <label class="label">Send by</label>
          <select class="input" onchange="CustomerOrders.setTransportMode(this.value)">
            <option value="" ${transportMode ? "" : "selected"}>—</option>
            <option value="bus" ${transportMode === "bus" ? "selected" : ""}>Bus</option>
            <option value="transport" ${transportMode === "transport" ? "selected" : ""}>Transport</option>
            <option value="self_pickup" ${transportMode === "self_pickup" ? "selected" : ""}>Self-pickup</option>
          </select>
          ${transportFieldsHtml()}
        </div>
        <div>
          <label class="label">Packing (₹)</label>
          <input class="input" value="${ctx.esc(packagingCharges)}" oninput="CustomerOrders.setPackagingCharges(this.value)" />
          ${editBillId ? "" : `<label class="label">Bill series</label>
          <select class="input" onchange="CustomerOrders.setBillSeries(this.value)">
            ${billSeries.map(s => `<option value="${s.id}" ${String(s.id) === String(billSeriesId) ? "selected" : ""}>${ctx.esc(s.name)}</option>`).join("")}
          </select>
          <p style="margin:6px 0 0;font-size:13px;">Number <strong id="co-bill-number">${ctx.esc(nextBillNumberFromSeries() || "—")}</strong></p>`}
          <label class="label">Bill date</label>
          <input type="date" class="input" value="${ctx.esc(billDate || localToday())}" onchange="CustomerOrders.setBillDate(this.value)" />
        </div>
      </div>
      <label class="label">Other charges</label>
      ${additionalCharges.map((c, i) => `
        <div style="display:flex;gap:8px;margin-bottom:6px;">
          <input class="input" placeholder="Name" value="${ctx.esc(c.name)}" oninput="CustomerOrders.setAddCharge(${i}, 'name', this.value)" />
          <input class="input" placeholder="₹" style="width:110px;" value="${ctx.esc(c.amount)}" oninput="CustomerOrders.setAddCharge(${i}, 'amount', this.value)" />
        </div>`).join("")}
      <button type="button" class="btn btn-secondary btn-sm" onclick="CustomerOrders.addChargeRow()">+ Charge</button>
      <label style="display:flex;gap:8px;align-items:center;margin:12px 0;">
        <input type="checkbox" ${gstEnabled ? "checked" : ""} onchange="CustomerOrders.setGst(this.checked)" /> GST
        ${gstEnabled ? `<input class="input" style="width:80px;" value="${ctx.esc(gstRate)}" oninput="CustomerOrders.setGstRate(this.value)" />` : ""}
      </label>
      <label class="label">Marking</label>
      <textarea id="co-bill-mark" class="input" rows="3" data-latest="${ctx.esc(processContext?.latest_marking || "")}" style="background:#fee2e2;border:1px solid #dc2626;font-weight:800;color:#b91c1c;" oninput="CustomerOrders.setNarration(this.value)">${ctx.esc(narration)}</textarea>
      <p style="margin:4px 0 0;font-size:12px;color:var(--muted);">Ctrl+R repeats the latest marking.</p>
    `;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="CustomerOrders.closeProcessWizard()">Cancel</button>
      <button class="btn btn-primary" ${processBusy ? "disabled" : ""} onclick="CustomerOrders.submitProcess()">${processBusy ? "Saving…" : "Save bill"}</button>`;
  }

  function signedStock(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }

  function catalogChecksHtml() {
    if (editBillId) return "";
    const rows = dueCatalogs || [];
    if (!rows.length) return "";
    return `<div style="margin:0 0 12px;">
      <label class="label">Catalogues</label>
      ${rows.map(c => {
        const on = Object.prototype.hasOwnProperty.call(pickedCatalogs, c.id);
        const again = Number(c.received) > 0;
        return `<label style="display:flex;gap:8px;align-items:center;margin-top:6px;">
          <input type="checkbox" ${on ? "checked" : ""} onchange="CustomerOrders.toggleBillCatalog(${c.id}, this.checked)" />
          <span style="flex:1;">${ctx.esc(c.name)} · ${c.copies_left} left${again ? ` · already ${c.received}` : ""}</span>
          ${on ? `<input class="input" style="width:90px;" inputmode="decimal" value="${ctx.esc(pickedCatalogs[c.id] || "0")}" oninput="CustomerOrders.setBillCatalogPrice(${c.id}, this.value)" />` : ""}
        </label>`;
      }).join("")}
    </div>`;
  }

  function focusNextBillItem() {
    const box = document.getElementById("co-bill-edit-search");
    if (!box) return;
    box.value = "";
    setBillEditSearch("");
    box.focus();
  }

  function setForceCredit(v) { forceCreditOverride = !!v; renderProcessWizard(); }

  function setDiscToggle(mode) {
    if (mode === "off") {
      discountEnabled = false;
      useOverallDiscount = false;
      overallDiscount = "";
      processLines.forEach(l => { l.discount_percent = ""; l.net_rate = calcNetFromDisc(l.unit_price, 0); l.discSource = ""; });
    } else if (mode === "overall") {
      discountEnabled = true;
      useOverallDiscount = true;
      processLines.forEach(l => { l.discount_percent = overallDiscount; l.net_rate = calcNetFromDisc(l.unit_price, overallDiscount); l.discSource = ""; });
    } else {
      discountEnabled = true;
      useOverallDiscount = false;
      overallDiscount = "";
    }
    renderProcessWizard();
  }
  function setOverallDisc(v) {
    overallDiscount = v;
    processLines.forEach((ln, i) => {
      ln.discount_percent = v;
      ln.net_rate = calcNetFromDisc(ln.unit_price, v);
      const net = document.querySelector(`[data-net-for="${i}"]`);
      if (net) net.value = ln.net_rate ?? "";
      const disc = document.querySelector(`[data-disc-for="${i}"]`);
      if (disc) disc.value = v;
    });
    renderWizardTotalsBar();
  }
  function billEditMatchesHtml() {
    const q = billEditSearch.trim().toLowerCase();
    const matches = q ? billEditProducts.slice(0, 8) : [];
    if (matches.length) {
      return `<div style="display:flex;flex-direction:column;gap:4px;">${matches.map(p => `
        <button type="button" class="btn btn-secondary btn-sm" style="justify-content:flex-start;" onclick="CustomerOrders.addBillEditProduct(${p.catalog_product_id})">
          ${ctx.esc(p.our_product_id)}${p.marking ? ` <span class="marking-flag">${ctx.esc(p.marking)}</span>` : ""}${p.vendor_product_id ? " · " + ctx.esc(p.vendor_product_id) : ""} · ${fmtPrice(p.selling_price)} · stock ${signedStock(p.quantity_on_hand)}
        </button>`).join("")}</div>`;
    }
    if (q) return `<p style="font-size:12px;color:var(--muted);">${billEditSearchPending ? "Searching…" : "No matches"}</p>`;
    return `<p style="font-size:12px;color:var(--muted);">Type a product number</p>`;
  }
  function paintBillEditMatches() {
    const box = document.getElementById("co-bill-edit-matches");
    if (box) box.innerHTML = billEditMatchesHtml();
  }
  function setBillEditSearch(v) {
    billEditSearch = v || "";
    const q = billEditSearch.trim().toLowerCase();
    billEditProducts = q ? filterEntryItems(q).slice(0, 8) : [];
    billEditSearchPending = false;
    paintBillEditMatches();
  }
  function defaultFreightAgentId() {
    const hit = freightAgents.find(a => String(a.name || "").trim().toLowerCase() === "vishnu parcel");
    return hit ? String(hit.id) : "";
  }
  function agentIsVishnu(id) {
    const hit = freightAgents.find(a => String(a.id) === String(id));
    return !!(hit && String(hit.name || "").toLowerCase().includes("vishnu"));
  }
  function setFreightAgent(v) {
    freightAgentId = v;
    if (!agentIsVishnu(v)) freightHandler = "";
    renderProcessWizard();
  }
  function setFreightHandler(name) {
    freightHandler = name;
    renderProcessWizard();
  }
  function setFreightCharges(v) { freightCharges = v; renderWizardTotalsBar(); }
  function setTransportMode(v) {
    transportMode = v;
    if (v === "self_pickup") {
      freightAgentId = "";
      freightHandler = "";
      freightCharges = "";
      transportReceiptNumber = "";
    } else if (v === "transport") {
      freightAgentId = "";
      freightHandler = "";
    } else if (v === "bus") {
      transportReceiptNumber = "";
      if (!freightAgentId) freightAgentId = defaultFreightAgentId();
    }
    renderProcessWizard();
    if (v === "bus" || v === "transport") {
      requestAnimationFrame(() => {
        const el = document.getElementById("co-freight-amount");
        if (el) { el.focus(); el.select(); }
      });
    }
  }
  function setTransportReceipt(v) { transportReceiptNumber = v; }
  function setPackagingCharges(v) { packagingCharges = v; renderWizardTotalsBar(); }
  function setGst(v) { gstEnabled = v; renderProcessWizard(); }
  function setGstRate(v) { gstRate = v; }
  function setBillSeries(v) {
    billSeriesId = v;
    const el = document.getElementById("co-bill-number");
    if (el) el.textContent = nextBillNumberFromSeries() || "—";
  }
  function nextBillNumberFromSeries() {
    const s = billSeries.find(x => String(x.id) === String(billSeriesId));
    if (!s) return "";
    const n = s.current_num + 1 >= s.start_num ? s.current_num + 1 : s.start_num;
    return `${s.prefix}${n}`;
  }
  function billLineAddonState(line, catalogAddons, charges) {
    const onBill = Array.isArray(line.addons) ? line.addons : [];
    const byId = new Map();
    for (const a of [...(catalogAddons || []), ...onBill]) {
      if (a && a.addon_product_id != null) byId.set(Number(a.addon_product_id), a);
    }
    const addons = [...byId.values()];
    const kept = new Set(onBill.map(a => Number(a.addon_product_id)));
    const names = (charges || []).map(c => String(c.name || "").toLowerCase());
    const chargeHas = (kind) => names.some(n => (kind === "name" ? n.includes("name plate") : n.includes("initial plate")));
    const kindOf = (a) => {
      const n = String(a.name || a.our_product_id || "").toLowerCase().replace(/[_-]/g, " ");
      if (n.includes("name plate")) return "name";
      if (n.includes("initial plate")) return "initial";
      return "";
    };
    const snapshot = Array.isArray(line.addons);
    const skip = [];
    for (const a of addons) {
      const id = Number(a.addon_product_id);
      const kind = kindOf(a);
      if (snapshot) {
        if (!kept.has(id)) skip.push(id);
        continue;
      }
      if (kind && chargeHas(kind)) continue;
      if (kind) skip.push(id);
    }
    return { addons, skip_addon_ids: skip };
  }

  function addonEachPrice(a) {
    const price = Number(a && a.selling_price);
    if (price > 0) return price;
    const n = String((a && (a.name || a.our_product_id)) || "").toLowerCase().replace(/[_-]/g, " ");
    if (n.includes("name plate")) return 2;
    if (n.includes("initial plate")) return 3;
    return 0;
  }

  function billAddonHtml(line) {
    const addons = line.addons || [];
    if (!addons.length) return "";
    const skipped = new Set((line.skip_addon_ids || []).map(Number));
    return addons.map(a => {
      const id = Number(a.addon_product_id);
      const name = a.name || a.our_product_id || "Add-on";
      const price = addonEachPrice(a);
      const priceBit = price > 0 ? ` · ₹${price} each` : "";
      if (skipped.has(id)) {
        return `<div class="co-addon-row">${ctx.esc(name)} removed · <button type="button" class="btn btn-ghost btn-sm" onclick="CustomerOrders.skipBillAddon(${line.catalog_product_id}, ${id})">Add</button></div>`;
      }
      return `<div class="co-addon-row">+ ${ctx.esc(name)}${priceBit} <button type="button" class="btn btn-ghost btn-sm" onclick="CustomerOrders.skipBillAddon(${line.catalog_product_id}, ${id})">Remove</button></div>`;
    }).join("");
  }

  function skipBillAddon(catalogProductId, addonId) {
    const ln = processLines.find(l => Number(l.catalog_product_id) === Number(catalogProductId));
    if (!ln) return;
    const skipped = new Set((ln.skip_addon_ids || []).map(Number));
    const id = Number(addonId);
    if (skipped.has(id)) skipped.delete(id);
    else skipped.add(id);
    ln.skip_addon_ids = [...skipped];
    renderProcessWizard();
  }

  function openCatalogPicker() {
    if (!(dueCatalogs || []).length) return ctx.toast("No catalogue is assigned to this party", "error");
    document.getElementById("modal-title").textContent = "Add a catalogue";
    document.getElementById("modal-body").innerHTML = `
      <label class="label">Catalogue</label>
      <select id="co-cat-pick" class="input" style="margin-bottom:12px;">
        <option value="">Choose</option>
        ${(dueCatalogs || []).map(c => {
          const again = Number(c.received) > 0;
          return `<option value="${c.id}">${ctx.esc(c.name)} · ${c.copies_left} left${again ? ` · already ${c.received}` : ""}</option>`;
        }).join("")}
      </select>
      <label class="label">Price (₹) — leave 0 if free</label>
      <input id="co-cat-price" class="input" inputmode="decimal" value="0" />`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Close</button>
      <button class="btn btn-primary" id="co-cat-add">Add</button>`;
    document.getElementById("co-cat-add").onclick = () => addPickedCatalog();
    document.getElementById("modal").classList.remove("hidden");
  }

  function addPickedCatalog() {
    const id = Number(document.getElementById("co-cat-pick")?.value || 0);
    if (!id) return ctx.toast("Choose a catalogue", "error");
    const cat = (dueCatalogs || []).find(row => Number(row.id) === id);
    if (!cat) return;
    if (Object.prototype.hasOwnProperty.call(pickedCatalogs, id)) return ctx.toast("Already on this bill", "error");
    if (Number(cat.received) > 0) {
      const ok = confirm(`${cat.name} was already sent to this party (${cat.received}). Send another copy?`);
      if (!ok) return;
    }
    pickedCatalogs[id] = document.getElementById("co-cat-price")?.value || "0";
    App.closeModal?.();
    renderProcessWizard();
  }

  function toggleBillCatalog(id, on) {
    if (on) {
      const cat = (dueCatalogs || []).find(row => Number(row.id) === Number(id));
      if (cat && Number(cat.received) > 0 && !Object.prototype.hasOwnProperty.call(pickedCatalogs, id)) {
        const ok = confirm(`${cat.name} was already sent to this party (${cat.received}). Send another copy?`);
        if (!ok) { renderProcessWizard(); return; }
      }
      if (!Object.prototype.hasOwnProperty.call(pickedCatalogs, id)) pickedCatalogs[id] = "0";
    } else {
      delete pickedCatalogs[id];
    }
    renderProcessWizard();
  }

  function setBillCatalogPrice(id, value) {
    pickedCatalogs[id] = value;
    renderWizardTotalsBar();
  }

  function setNarration(v) { narration = v; }
  function setEditBillNumber(v) { editBillNumber = v || ""; }
  function setBillDate(v) { billDate = v || localToday(); }
  function setAddCharge(i, field, val) { if (additionalCharges[i]) additionalCharges[i][field] = val; renderWizardTotalsBar(); }
  function addChargeRow() { additionalCharges.push({ name: "", amount: "" }); renderProcessWizard(); }

  function toggleBillOrder(id, checked) {
    const n = Number(id);
    if (checked) {
      if (!selectedPlacementIds.includes(n)) selectedPlacementIds.push(n);
    } else {
      selectedPlacementIds = selectedPlacementIds.filter(x => x !== n);
    }
    if (!editBillId && billableOrders.length) {
      applySelectedOrders();
      renderProcessWizard();
    }
  }

  function toggleAllBillOrders(checked) {
    selectedPlacementIds = checked ? billableOrders.map(o => Number(o.placement_id)) : [];
    if (!editBillId) applySelectedOrders();
    renderProcessWizard();
  }

  function applySelectedOrders() {
    const direct = processLines.filter(l => l.direct);
    const chosen = new Set(selectedPlacementIds.map(Number));
    const byCid = new Map((processContext?.lines || []).map(l => [Number(l.catalog_product_id), l]));
    const seen = [];
    const qty = {};
    for (const order of billableOrders) {
      if (!chosen.has(Number(order.placement_id))) continue;
      for (const ln of order.lines || []) {
        const cid = Number(ln.catalog_product_id);
        if (!seen.includes(cid)) seen.push(cid);
        qty[cid] = (qty[cid] || 0) + Number(ln.quantity || 0);
      }
    }
    const booked = seen.map(cid => {
      const l = byCid.get(cid);
      if (!l || !(qty[cid] > 0)) return null;
      const q = Math.min(Number(l.quantity_open) || 0, qty[cid] || 0);
      return {
        ...l,
        quantity_open: q,
        quantity_to_ship: q,
        discount_percent: "",
        net_rate: calcNetFromDisc(l.unit_price, 0),
        discSource: "",
        addons: l.addons || [],
        skip_addon_ids: l.skip_addon_ids || [],
        direct: false,
      };
    }).filter(l => l && l.quantity_open > 0);
    const bookedIds = new Set(booked.map(l => Number(l.catalog_product_id)));
    processLines = booked.concat(direct.filter(l => !bookedIds.has(Number(l.catalog_product_id))));
    return processLines.length > 0;
  }

  async function processNext() {
    if (processStep === 0) {
      if (!selectedPlacementIds.length) return ctx.toast("Select at least one order", "error");
      if (!applySelectedOrders()) return ctx.toast("Nothing left to bill on the selected orders", "error");
      processStep = 1;
      renderProcessWizard();
      return;
    }
    if (processStep === 1) {
      if (editBillId && processLines.some(l => !(Number(l.quantity_to_ship) > 0))) {
        return ctx.toast("Enter quantity for every item", "error");
      }
      if (!processLines.some(l => Number(l.quantity_to_ship) > 0)) return ctx.toast("Enter qty to ship", "error");
      processStep = 2;
      renderProcessWizard();
      return;
    }
    if (processStep === 2) {
      if (!transportMode) return ctx.toast("Select mode of transport", "error");
      if (transportMode === "bus") {
        if (!freightAgentId) return ctx.toast("Select freight agent", "error");
        if (freightCharges.trim() === "") return ctx.toast("Enter freight charges", "error");
      }
      if (transportMode === "transport" && freightCharges.trim() === "") {
        return ctx.toast("Enter transport charges", "error");
      }
      processStep = 3;
      renderProcessWizard();
      return;
    }
    if (processStep === 3) {
      if (!editBillId && !billSeriesId) return ctx.toast("Select bill series", "error");
      processStep = 4;
      renderProcessWizard();
      return;
    }
    if (processStep === 4) {
      ctx.showLoading?.();
      try {
        // Real server-side totals (GST + additional charges included) for both create
        // and edit — the edit path used to hand-roll a client estimate that silently
        // dropped GST/additional charges, so what staff approved here didn't match what
        // PUT .../bills/{id} actually saved.
        const url = editBillId
          ? `/customer-orders/bills/${editBillId}/edit-preview`
          : `/customer-orders/customer/${detailCustomerId}/process/preview`;
        previewTotals = await ctx.api(url, {
          method: "POST",
          body: JSON.stringify(buildProcessBody()),
        });
        processStep = 5;
        renderProcessWizard();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    }
  }

  function processBack() {
    if (processStep === 1 && !editBillId && billableOrders.length) {
      processStep = 0;
      renderProcessWizard();
      return;
    }
    if (processStep > 1) { processStep -= 1; renderProcessWizard(); }
  }

  async function submitProcess() {
    if (processBusy || !detailCustomerId) return;
    if (!processLines.some(l => Number(l.quantity_to_ship) > 0)) return ctx.toast("Enter a quantity", "error");
    if (!transportMode) return ctx.toast("Select how this is sent", "error");
    if (transportMode === "bus") {
      if (!freightAgentId) return ctx.toast("Select the freight agent", "error");
      if (String(freightCharges || "").trim() === "") return ctx.toast("Enter freight", "error");
    }
    if (transportMode === "transport" && String(freightCharges || "").trim() === "") {
      return ctx.toast("Enter transport charges", "error");
    }
    if (!editBillId && !billSeriesId) return ctx.toast("Select a bill series", "error");
    if (editBillId) {
      const allowed = await askEditCancelKey();
      if (!allowed) return;
    } else {
      window.__jcCancelKey = "";
    }
    processBusy = true;
    showBillReady({ bill_number: "Saving…", grand_total: "", bill_id: 0, pending: true });
    try {
      let res;
      const body = buildProcessBody();
      if (editBillId) {
        res = await ctx.api(`/customer-orders/bills/${editBillId}`, {
          method: "PUT",
          headers: { "X-Cancel-Key": window.__jcCancelKey || "" },
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
      if (edited) ctx.invalidateCache?.("/freight-agents");
      showBillReady(res);
      ctx.toast(`Bill ${res.bill_number} — ${fmtPrice(res.grand_total)}`, "success");
      loadList(true);
    } catch (e) {
      processBusy = false;
      const matches = e.status === 409 && e.detail && e.detail.matches;
      if (matches) {
        showBillDuplicate(e.detail);
        return;
      }
      billConfirmDuplicate = false;
      ctx.toast(e.message, "error");
      renderProcessWizard();
    } finally {
      processBusy = false;
    }
  }

  function showBillDuplicate(detail) {
    const body = document.getElementById("co-wizard-body");
    const footer = document.getElementById("co-wizard-footer");
    const rows = (detail.matches || []).map((m) => {
      const bits = [];
      if (m.same_items && m.same_items.length) bits.push(`same item ${m.same_items.join(", ")}`);
      if (m.same_amount) bits.push(`same amount ₹${m.total}`);
      return `<li>${ctx.esc(m.bill_number || "Bill")}: ${ctx.esc(bits.join(" · "))}</li>`;
    }).join("");
    if (body) {
      body.innerHTML = `<div style="border:2px solid #b45309;background:#fffbeb;border-radius:12px;padding:16px;">
        <strong style="font-size:18px;">This could be a duplicate entry.</strong>
        <p style="margin:8px 0;">Same date, same party. The following are the same:</p>
        <ul style="margin:0 0 8px 18px;">${rows}</ul>
        <p style="margin:0;">Do you want to proceed?</p>
      </div>`;
    }
    if (footer) {
      footer.innerHTML = `
        <button type="button" class="btn btn-secondary" onclick="CustomerOrders.backFromBillDuplicate()">Go back</button>
        <button type="button" class="btn btn-primary" onclick="CustomerOrders.proceedBillDuplicate()">Proceed</button>`;
    }
  }

  function backFromBillDuplicate() {
    billConfirmDuplicate = false;
    processBusy = false;
    renderProcessWizard();
  }

  function proceedBillDuplicate() {
    billConfirmDuplicate = true;
    submitProcess();
  }

  function showBillReady(res) {
    const title = document.getElementById("co-wizard-title");
    const body = document.getElementById("co-wizard-body");
    const footer = document.getElementById("co-wizard-footer");
    const steps = document.getElementById("co-wizard-steps");
    const totals = document.getElementById("co-wizard-totals");
    if (steps) steps.innerHTML = "";
    if (totals) totals.innerHTML = "";
    if (title) title.textContent = `Bill ${res.bill_number || ""}`;
    if (body) {
      body.innerHTML = `
        <p style="margin:0 0 8px;font-size:18px;"><strong>${ctx.esc(res.bill_number || "")}</strong>${res.pending ? "" : " saved"}</p>
        <p style="margin:0 0 20px;color:var(--muted);">${res.pending ? "The bill is being saved. Print and download will be ready in a moment." : fmtPrice(res.grand_total)}</p>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button type="button" class="btn btn-primary" ${res.pending ? "disabled" : ""} onclick="CustomerOrders.openBillDoc(${Number(res.bill_id) || 0}, true)">Print</button>
          <button type="button" class="btn btn-secondary" ${res.pending ? "disabled" : ""} onclick="CustomerOrders.openBillDoc(${Number(res.bill_id) || 0}, false)">Download</button>
        </div>
        <p style="margin:12px 0 0;font-size:13px;color:var(--muted);">Print is the original and the duplicate. Download is the original only.</p>`;
    }
    if (footer) {
      const backLedger = window.__jcLedgerReturn
        ? `<button type="button" class="btn btn-primary" onclick="CustomerOrders.closeProcessWizard({done:true})">Back to ledger</button>`
        : `<button type="button" class="btn btn-secondary" onclick="CustomerOrders.closeProcessWizard()">Done</button>`;
      footer.innerHTML = backLedger;
    }
    document.getElementById("co-wizard")?.classList.remove("hidden");
  }

  function setBillOnAgent(on) {
    billOnAgent = !!on;
  }

  function sayInPrintWindow(win, text) {
    try {
      win.document.open();
      win.document.write(`<!doctype html><title>Invoices</title><body style="font:16px sans-serif;padding:28px;color:#222">${text}</body>`);
      win.document.close();
    } catch (_) {}
  }

  async function printDayDuplicates() {
    const input = document.getElementById("co-print-day");
    const day = input && input.value;
    if (!day) return ctx.toast("Enter the invoice date", "error");
    const win = window.open("", "_blank");
    if (!win) return ctx.toast("Allow pop-ups to print the invoices", "error");
    sayInPrintWindow(win, "Preparing invoices…");
    try {
      const start = await ctx.api(`/share/bills/duplicates/start?day=${encodeURIComponent(day)}`, { method: "POST" });
      const jobId = start.job_id;
      let status = start;
      const started = Date.now();
      while (status.state !== "ready") {
        if (status.state === "error") throw new Error(status.error || "Could not print the invoices");
        if (Date.now() - started > 180000) throw new Error("Preparing the invoices took too long");
        sayInPrintWindow(win, `Preparing invoices… ${status.done || 0} of ${status.total || ""}`);
        await new Promise(resolve => setTimeout(resolve, 800));
        status = await ctx.api(`/share/bills/duplicates/jobs/${jobId}`);
      }
      const headers = { ...(ctx.headers?.() || {}) };
      delete headers["Content-Type"];
      const res = await fetch(`${(ctx.apiBase?.() || "").replace(/\/$/, "")}/share/bills/duplicates/jobs/${jobId}/file`, { headers });
      if (!res.ok) throw new Error("Could not open the invoices");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      win.location = url;
      setTimeout(() => {
        try { win.focus(); win.print(); } catch (_) {}
      }, 900);
      const skipped = (status.failed || []).length;
      if (skipped) ctx.toast(`Printed the invoices. ${skipped} could not be included.`, "error");
    } catch (e) {
      sayInPrintWindow(win, ctx.esc ? ctx.esc(e.message || "Could not print the invoices") : "Could not print the invoices");
      ctx.toast(e.message || "Could not print the invoices", "error");
    }
  }

  async function fetchStoredBill(billId) {
    const headers = { ...(ctx.headers?.() || {}) };
    delete headers["Content-Type"];
    const base = (ctx.apiBase?.() || "").replace(/\/$/, "");
    const res = await fetch(`${base}/customer-orders/bills/${billId}/stored-pdf`, { headers });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error("Could not open the saved bill");
    return res.blob();
  }

  function printPdfHere(url) {
    if (window.DocShare && DocShare.printPdfUrl) DocShare.printPdfUrl(url);
  }

  async function printStoredBill(billId) {
    ctx.showLoading?.();
    try {
      const blob = await fetchStoredBill(billId);
      if (!blob) return ctx.toast("Saved bill is not ready yet", "error");
      printPdfHere(URL.createObjectURL(blob));
    } catch (e) {
      ctx.toast(e.message || "Could not print", "error");
    } finally { ctx.hideLoading?.(); }
  }

  async function downloadStoredBill(billId) {
    ctx.showLoading?.();
    try {
      const blob = await fetchStoredBill(billId);
      if (!blob) return ctx.toast("Saved bill is not ready yet", "error");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "bill.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (e) {
      ctx.toast(e.message || "Could not download", "error");
    } finally { ctx.hideLoading?.(); }
  }

  async function openBillDoc(billId, print) {
    ctx.showLoading?.();
    try {
      await DocShare.openPdf(`/share/bills/${billId}/pdf?layout=${print ? "print" : "file"}`, {
        print: !!print,
        filename: "bill.pdf",
      });
    } catch (e) {
      try {
        const d = await ctx.api(`/customer-orders/bills/${billId}/document`, {}, 0);
        if (!d.document_url) throw e;
        if (print) printPdfHere(d.document_url);
        else window.open(d.document_url, "_blank");
      } catch (e2) { ctx.toast(e2.message || e.message, "error"); }
    } finally {
      ctx.hideLoading?.();
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

  function billApiBase() {
    const host = location.hostname;
    const local = host === "127.0.0.1" || host === "localhost";
    const here = local ? "http://127.0.0.1:8003/api/v1" : `${location.origin}/api/v1`;
    const saved = localStorage.getItem("jc_api");
    if (!saved) return here;
    if (local) return saved;
    try {
      if (new URL(saved, location.origin).origin === location.origin) return saved.replace(/\/$/, "");
    } catch (_) {}
    localStorage.removeItem("jc_api");
    return here;
  }

  function billAuthHeaders() {
    const h = {};
    if (sessionStorage.getItem("jc_auth_mode") === "admin") h["X-Admin-Key"] = sessionStorage.getItem("jc_admin_key") || "";
    else h.Authorization = `Bearer ${sessionStorage.getItem("jc_staff_token") || ""}`;
    return h;
  }

  function uploadBillQr(billId) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/jpeg,image/png,image/webp";
    input.onchange = async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      ctx.showLoading?.();
      try {
        const res = await fetch(`${billApiBase()}/customer-orders/bills/${billId}/payment-qr`, {
          method: "POST",
          headers: billAuthHeaders(),
          body: fd,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(typeof err.detail === "string" ? err.detail : "QR upload failed");
        }
        ctx.toast("Payment QR updated", "success");
        if (detailCustomerId) openDetail(detailCustomerId, "billed");
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    };
    input.click();
  }

  async function resetBillQr(billId) {
    ctx.showLoading?.();
    try {
      const res = await fetch(`${billApiBase()}/customer-orders/bills/${billId}/payment-qr`, {
        method: "DELETE",
        headers: billAuthHeaders(),
      });
      if (!res.ok) throw new Error("Could not restore the default QR");
      ctx.toast("Default payment QR restored", "success");
      if (detailCustomerId) openDetail(detailCustomerId, "billed");
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  function showCreateMenuFromCustomer(customerId) {
    openOfflineWizard(customerId);
  }

  function showCreateMenu() {
    openOfflineWizard();
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

  let entryParties = null;
  let entryItems = null;

  async function ensureEntryCatalogs() {
    if (entryParties && entryItems) return;
    const [parties, items] = await Promise.all([
      ctx.api("/customers/entry-parties", {}, 0),
      ctx.api("/stock/entry-items", {}, 0),
    ]);
    entryParties = parties || [];
    entryItems = items || [];
  }

  function filterEntryParties(q) {
    const needle = String(q || "").trim().toLowerCase();
    if (!needle) return [];
    const scored = [];
    for (const c of entryParties || []) {
      const name = String(c.business_name || "").toLowerCase();
      const alias = String(c.alias || "").toLowerCase();
      const city = String(c.city_name || "").toLowerCase();
      const phone = String(c.phone || "");
      const num = String(c.party_number || "");
      let score = 0;
      if (name === needle || num === needle) score = 100;
      else if (name.startsWith(needle) || alias.startsWith(needle) || num.startsWith(needle)) score = 80;
      else if (name.includes(needle) || alias.includes(needle) || city.includes(needle) || phone.includes(needle)) score = 40;
      else continue;
      scored.push({ c, score, name });
    }
    scored.sort((a, b) => b.score - a.score || a.name.localeCompare(b.name));
    return scored.slice(0, 12).map(x => x.c);
  }

  function filterEntryItems(q) {
    const needle = String(q || "").trim().toLowerCase();
    if (!needle) return [];
    const scored = [];
    for (const p of entryItems || []) {
      const id = String(p.our_product_id || "").toLowerCase();
      const alias = String(p.vendor_product_id || "").toLowerCase();
      const number = id.split(" ")[0];
      let score = 0;
      if (id === needle || number === needle) score = 300;
      else if (alias && alias === needle) score = 100;
      else if (id.startsWith(needle)) score = 80;
      else if (alias && alias.startsWith(needle)) score = 60;
      else if (id.includes(needle) || (alias && alias.includes(needle))) score = 40;
      else continue;
      scored.push({ p, score, id });
    }
    scored.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
    return scored.slice(0, 12).map(x => x.p);
  }

  async function openOfflineWizard(presetCustomerId, presetProductId) {
    const hasPreset = arguments.length > 0 && presetCustomerId != null && presetCustomerId !== "";
    const cid = hasPreset ? presetCustomerId : null;
    const productId = presetProductId != null && presetProductId !== "" ? Number(presetProductId) : 0;
    offlineEditPlacementId = null;
    offlineStep = 1;
    offlineCustomerId = null;
    offlineCustomerName = "";
    offlineCustomerSearch = "";
    offlineSelectedDetail = null;
    offlineLines = [];
    offlineSearchQuery = "";
    offlineSearchResults = [];
    offlinePicked = null;
    offlineNotes = "";
    offlinePlacedOn = localToday();
    offlinePreview = null;
    offlineReview = false;
    offlineBusy = false;
    offlineCustomers = [];
    document.getElementById("co-offline-wizard")?.classList.remove("hidden");
    const body = document.getElementById("co-offline-body");
    if (body) body.innerHTML = `<p style="color:var(--muted);">Loading…</p>`;
    try {
      await ensureEntryCatalogs();
    } catch (e) { ctx.toast(e.message || "Could not load the lists", "error"); }
    if (cid) {
      const c = (entryParties || []).find(x => Number(x.id) === Number(cid));
      if (c) {
        offlineCustomerId = c.id;
        offlineCustomerName = c.business_name || "";
        offlinePicked = c;
      } else {
        offlineCustomerId = cid;
      }
    }
    if (productId) {
      const p = (entryItems || []).find(x => Number(x.catalog_product_id) === productId);
      if (!p) ctx.toast("That item is not on the order list", "error");
      else if (!offlineLines.some(l => l.catalog_product_id === p.catalog_product_id)) {
        offlineLines.push({
          catalog_product_id: p.catalog_product_id,
          our_product_id: p.our_product_id,
          quantity: 1,
          min_qty: 0,
          selling_price: p.selling_price,
          quantity_on_hand: p.quantity_on_hand,
          addons: (p.addons && p.addons.length) ? p.addons : (p.priced_addons || []),
          priced_addons: p.priced_addons || [],
          skip_addon_ids: [],
        });
      }
    }
    renderOfflineWizard();
  }

  function onOfflineCustomerSearch(val) {
    offlineCustomerSearch = val || "";
    const box = document.getElementById("co-order-customer-matches");
    if (!box) return;
    const rows = filterEntryParties(offlineCustomerSearch);
    box.innerHTML = rows.map(c =>
      `<button type="button" class="btn btn-secondary btn-sm" style="display:block;width:100%;text-align:left;margin-top:4px;" onclick="CustomerOrders.pickOfflineCustomer(${c.id})">${ctx.esc(c.business_name || "")}${c.city_name ? " · " + ctx.esc(c.city_name) : ""}${c.party_number ? " · #" + c.party_number : ""}</button>`
    ).join("") || (String(offlineCustomerSearch || "").trim() ? `<p style="font-size:13px;color:var(--muted);margin:6px 0 0;">No match</p>` : "");
  }

  function pickOfflineCustomer(id) {
    const c = (entryParties || []).find(x => Number(x.id) === Number(id));
    if (!c) return;
    offlineCustomerId = c.id;
    offlineCustomerName = c.business_name || "";
    offlinePicked = c;
    offlineCustomerSearch = "";
    const picked = document.getElementById("co-order-customer-picked");
    if (picked) picked.textContent = `${c.business_name || ""}${c.city_name ? " · " + c.city_name : ""}`;
    const input = document.getElementById("co-order-customer");
    if (input) input.value = "";
    const box = document.getElementById("co-order-customer-matches");
    if (box) box.innerHTML = "";
    loadBookedOrders();
    document.getElementById("co-order-item")?.focus();
  }

  function previewOrder() {
    const notesEl = document.getElementById("co-order-note");
    if (notesEl) offlineNotes = notesEl.value || "";
    const dateEl = document.getElementById("co-order-date");
    if (dateEl && dateEl.value) offlinePlacedOn = dateEl.value;
    if (!offlineCustomerId) return ctx.toast("Select a customer", "error");
    if (!offlineLines.some(l => Number(l.quantity) > 0)) return ctx.toast("Add at least one item", "error");
    offlineReview = true;
    renderOfflineWizard();
  }

  function backFromOrderPreview() {
    offlineReview = false;
    renderOfflineWizard();
  }

  function renderOrderReview(bodyEl, footerEl) {
    const lines = offlineLines.filter(l => Number(l.quantity) > 0);
    const total = lines.reduce((s, l) => s + (Number(l.selling_price) || 0) * (Number(l.quantity) || 0), 0);
    bodyEl.innerHTML = `
      <p style="margin:0 0 8px;font-size:13px;color:var(--muted);">Check this order, then save.</p>
      <p style="margin:0 0 12px;"><strong>${ctx.esc(offlineCustomerName || "")}</strong></p>
      <p style="margin:0 0 12px;font-size:13px;">${ctx.esc(offlinePlacedOn || "")}</p>
      ${offlineNotes ? `<p style="margin:0 0 12px;color:#b91c1c;font-weight:700;">${ctx.esc(offlineNotes)}</p>` : ""}
      <table class="data"><thead><tr><th>Item</th><th>Qty</th><th>Rate</th></tr></thead><tbody>
        ${lines.map(l => `<tr><td>${ctx.esc(l.our_product_id)}</td><td>${l.quantity}</td><td>${fmtPrice(l.selling_price)}</td></tr>`).join("")}
      </tbody></table>
      <p style="margin:8px 0 0;font-weight:700;">${fmtPrice(total)}</p>`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="CustomerOrders.backFromOrderPreview()">Go back</button>
      <button class="btn btn-primary" ${offlineBusy ? "disabled" : ""} onclick="CustomerOrders.submitOffline()">${offlineBusy ? "Saving…" : "Save order"}</button>`;
  }

  function closeOfflineWizard() {
    offlineReview = false;
    offlineConfirmDuplicate = false;
    document.getElementById("co-offline-wizard")?.classList.add("hidden");
    offlineEditPlacementId = null;
  }

  function buildOfflineBody() {
    return {
      lines: offlineLines.filter(l => Number(l.quantity) > 0).map(l => ({
        catalog_product_id: l.catalog_product_id,
        quantity: Number(l.quantity),
        skip_addon_ids: l.skip_addon_ids || [],
      })),
      narration: (offlineNotes || "").trim() || null,
      placed_on: offlinePlacedOn || localToday(),
      confirm_duplicate: !!offlineConfirmDuplicate,
    };
  }

  function filterOfflineProducts() {
    const q = offlineSearchQuery.trim().toLowerCase();
    const all = offlineSearchResults || [];
    if (!q) return [];
    const scored = [];
    for (const p of all) {
      const id = String(p.our_product_id || "").toLowerCase();
      const cat = String(p.category || "").toLowerCase();
      const vendor = String(p.vendor_name || "").toLowerCase();
      let score = 0;
      if (id === q) score = 100;
      else if (id.startsWith(q)) score = 80;
      else if (id.includes(q)) score = 40;
      else if (cat.startsWith(q)) score = 30;
      else if (cat.includes(q) || vendor.includes(q)) score = 10;
      else continue;
      scored.push({ p, score, id });
    }
    scored.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
    return scored.map(x => x.p).slice(0, 40);
  }

  function offlineCartQty() {
    return offlineLines.reduce((s, l) => s + (Number(l.quantity) || 0), 0);
  }

  function offlineCartTotal() {
    return offlineLines.reduce((s, l) => {
      let n = (Number(l.selling_price) || 0) * (Number(l.quantity) || 0);
      const skipped = new Set(l.skip_addon_ids || []);
      const extras = (l.addons && l.addons.length) ? l.addons : (l.priced_addons || []);
      for (const a of extras) {
        if (skipped.has(a.addon_product_id)) continue;
        if (!(Number(a.selling_price) > 0)) continue;
        n += (Number(a.selling_price) || 0) * (Number(a.quantity) || 1) * (Number(l.quantity) || 0);
      }
      return s + n;
    }, 0);
  }

  function lineAddons(p, line) {
    if (line && Array.isArray(line.addons) && line.addons.length) return line.addons;
    if (p && Array.isArray(p.addons) && p.addons.length) return p.addons;
    return (line && line.priced_addons) || (p && p.priced_addons) || [];
  }

  function pricedAddonHtml(p, line) {
    const addons = lineAddons(p, line);
    if (!addons.length || !line) return "";
    const skipped = new Set(line.skip_addon_ids || []);
    return addons.map(a => {
      const id = a.addon_product_id;
      const name = a.name || a.our_product_id || "Add-on";
      const price = Number(a.selling_price) || 0;
      const priceBit = price > 0 ? ` · ₹${price} each` : "";
      if (skipped.has(id)) {
        return `<div class="co-addon-row" onclick="event.stopPropagation()">${ctx.esc(name)} removed · <button type="button" class="btn btn-ghost btn-sm" onclick="event.stopPropagation();CustomerOrders.skipOfflineAddon(${p.catalog_product_id}, ${id})">Add back</button></div>`;
      }
      return `<div class="co-addon-row" onclick="event.stopPropagation()">+ ${ctx.esc(name)}${priceBit} <button type="button" class="btn btn-ghost btn-sm" onclick="event.stopPropagation();CustomerOrders.skipOfflineAddon(${p.catalog_product_id}, ${id})">Remove</button></div>`;
    }).join("");
  }

  let offlineReview = false;

  function renderOfflineWizard() {
    const bodyEl = document.getElementById("co-offline-body");
    const footerEl = document.getElementById("co-offline-footer");
    const stepsEl = document.getElementById("co-offline-steps");
    if (!bodyEl || !footerEl) return;
    if (offlineReview) {
      renderOrderReview(bodyEl, footerEl);
      return;
    }
    if (stepsEl) stepsEl.innerHTML = "";
    const editing = !!offlineEditPlacementId;
    const picked = offlinePicked;
    bodyEl.innerHTML = `
      <label class="label">Customer</label>
      ${editing ? `<p style="margin:0 0 12px;"><strong>${ctx.esc(offlineCustomerName || "")}</strong></p>` : `
        <input id="co-order-customer" class="input" type="text" placeholder="Name, city, or number" autocomplete="off" oninput="CustomerOrders.onOfflineCustomerSearch(this.value)" />
        <div id="co-order-customer-picked" style="margin:6px 0;font-weight:600;">${picked ? ctx.esc((picked.business_name || "") + (picked.city_name ? " · " + picked.city_name : "")) : ""}</div>
        <div id="co-order-customer-matches"></div>`}
      <div id="co-order-booked"></div>
      <label class="label">Item number</label>
      <input id="co-order-item" class="input" type="text" placeholder="Type the item number" autocomplete="off" oninput="CustomerOrders.onOfflineSearchInput(this.value)" onkeydown="CustomerOrders.onOfflineSearchKey(event)" />
      <div id="co-order-item-matches"></div>
      <div id="co-order-lines" style="margin-top:12px;"></div>
      <div style="display:grid;grid-template-columns:160px 1fr;gap:12px;margin-top:16px;">
        <div>
          <label class="label">Date</label>
          <input id="co-order-date" type="date" class="input" value="${ctx.esc(offlinePlacedOn || localToday())}" onchange="CustomerOrders.setOfflinePlacedOn(this.value)" />
        </div>
        <div>
          <label class="label">Marking</label>
          <input id="co-order-note" class="input" style="border:2px solid #dc2626;background:#fef2f2;font-weight:700;color:#b91c1c;" placeholder="Hold. Do not bill. Bill after 5 days." value="${ctx.esc(offlineNotes || "")}" oninput="CustomerOrders.setOfflineNotes(this.value)" />
          <p style="margin:4px 0 0;font-size:12px;color:#b91c1c;">Shown in red on the bill. Use it when the quantity should stay reserved.</p>
        </div>
      </div>`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" onclick="CustomerOrders.closeOfflineWizard()">Cancel</button>
      <button class="btn btn-primary" ${offlineBusy ? "disabled" : ""} onclick="CustomerOrders.submitOffline()">${offlineBusy ? "Saving…" : "Save order"}</button>`;
    paintOrderLines();
    loadBookedOrders();
    const focusId = editing || offlineCustomerId ? "co-order-item" : "co-order-customer";
    document.getElementById(focusId)?.focus();
  }

  function bookedOrdersHtml(detail) {
    const lines = detail?.open_lines || [];
    const notes = (detail?.placements || []).map(p => p.customer_notes).filter(Boolean);
    if (!lines.length && !notes.length) {
      return `<p style="font-size:13px;color:var(--muted);margin:6px 0 10px;">No confirmed order waiting for this customer.</p>`;
    }
    const rows = lines.map(ln => `<div style="display:flex;justify-content:space-between;gap:8px;font-size:13px;padding:4px 0;border-bottom:1px solid #fecaca;"><strong>${ctx.esc(ln.our_product_id)}</strong><span>${ln.quantity_open} booked</span></div>`).join("");
    return `<div style="margin:8px 0 12px;padding:8px 10px;background:#fef2f2;border:1px solid #dc2626;border-radius:8px;">
      <strong style="color:#b91c1c;">Already booked. Bill this. Do not make a new order if they only want part of it billed.</strong>
      ${notes.length ? `<div style="color:#b91c1c;font-weight:700;margin-top:4px;">${ctx.esc(notes.join(" · "))}</div>` : ""}
      ${rows}
      <button type="button" class="btn btn-primary" style="margin-top:10px;width:100%;" onclick="CustomerOrders.billBookedOrder()">Bill this order</button>
    </div>`;
  }

  function billBookedOrder() {
    const id = offlineCustomerId;
    if (!id) return;
    closeOfflineWizard();
    processFromHub(id, "open");
  }

  async function loadBookedOrders() {
    const box = document.getElementById("co-order-booked");
    if (!box) return;
    if (!offlineCustomerId) { box.innerHTML = ""; return; }
    box.innerHTML = `<p style="font-size:13px;color:var(--muted);margin:6px 0 10px;">Checking booked orders…</p>`;
    try {
      const detail = await ctx.api(`/customer-orders/customer/${offlineCustomerId}?bucket=open`, {}, 0);
      const still = document.getElementById("co-order-booked");
      if (still) still.innerHTML = bookedOrdersHtml(detail);
    } catch (_) {
      const still = document.getElementById("co-order-booked");
      if (still) still.innerHTML = "";
    }
  }

  function paintOrderLines() {
    const box = document.getElementById("co-order-lines");
    if (!box) return;
    if (!offlineLines.length) {
      box.innerHTML = `<p style="font-size:13px;color:var(--muted);margin:0;">No items yet.</p>`;
      return;
    }
    box.innerHTML = `<table class="data"><thead><tr><th>Item</th><th>Stock</th><th>Rate</th><th>Qty</th><th></th></tr></thead><tbody>
      ${offlineLines.map(l => {
        const stock = signedStock(l.quantity_on_hand);
        const qty = signedStock(l.quantity);
        const short = qty > stock;
        return `<tr style="${short ? "background:#fef2f2;" : ""}">
        <td><strong>${ctx.esc(l.our_product_id)}</strong>${pricedAddonHtml({ catalog_product_id: l.catalog_product_id }, l)}${short ? `<div style="color:#b91c1c;font-weight:800;font-size:12px;">Only ${stock} in stock</div>` : ""}</td>
        <td style="${short ? "color:#b91c1c;font-weight:800;" : ""}">${l.quantity_on_hand ?? "—"}${!short && stock <= 0 ? ` <span style="color:#b45309;">in transit</span>` : ""}</td>
        <td>${fmtPrice(l.selling_price)}</td>
        <td><input data-qty-for="${l.catalog_product_id}" type="number" class="input" style="width:72px;${short ? "border-color:#dc2626;background:#fff1f2;" : ""}" min="${Number(l.min_qty) || 1}" value="${l.quantity}" oninput="CustomerOrders.setOfflineQty(${l.catalog_product_id}, this.value)" onkeydown="CustomerOrders.onOfflineQtyKey(event)" /></td>
        <td><button type="button" class="btn btn-ghost btn-sm" onclick="CustomerOrders.removeOfflineLine(${l.catalog_product_id})">Remove</button></td>
      </tr>`;
      }).join("")}
    </tbody></table>
    <p style="margin:8px 0 0;font-size:13px;">${offlineLines.length} item(s) · ${fmtPrice(offlineCartTotal())}</p>`;
  }

  function setOfflineNotes(v) { offlineNotes = v || ""; }
  function setOfflinePlacedOn(v) { offlinePlacedOn = v || localToday(); }

  function onOfflineSearchInput(val) {
    offlineSearchQuery = val || "";
    const box = document.getElementById("co-order-item-matches");
    if (!box) return;
    const rows = filterEntryItems(offlineSearchQuery);
    offlineSearchResults = rows;
    box.innerHTML = rows.map(p =>
      `<button type="button" class="btn btn-secondary btn-sm" style="display:block;width:100%;text-align:left;margin-top:4px;" onclick="CustomerOrders.pickOfflineProduct(${p.catalog_product_id})">${ctx.esc(p.our_product_id)}${p.vendor_product_id ? " · " + ctx.esc(p.vendor_product_id) : ""} · stock ${p.quantity_on_hand ?? 0}${p.selling_price ? " · " + fmtPrice(p.selling_price) : ""}</button>`
    ).join("") || (String(offlineSearchQuery || "").trim() ? `<p style="font-size:13px;color:var(--muted);margin:6px 0 0;">No match</p>` : "");
  }

  async function loadOfflineProductSearch(q) {
    try {
      const rows = await ctx.api(`/stock/products?lite=1&limit=40&search=${encodeURIComponent(q)}`, {}, 0) || [];
      if ((offlineSearchQuery || "").trim() !== q) return;
      offlineSearchResults = rows;
    } catch (e) {
      offlineSearchResults = [];
      ctx.toast(e.message, "error");
    }
    offlineSearchPending = false;
    renderOfflineWizard();
  }

  function focusPendingQty(searchId) {
    if (focusQtyProductId != null) {
      const id = focusQtyProductId;
      focusQtyProductId = null;
      const el = document.querySelector(`[data-qty-for="${id}"]`);
      if (el) { el.disabled = false; el.focus(); el.select(); return; }
    }
    const inp = document.getElementById(searchId);
    if (!inp || document.activeElement === inp) return;
    inp.focus();
    try { const n = (offlineSearchQuery || "").length; inp.setSelectionRange(n, n); } catch (_) {}
  }

  async   function onOfflineSearchKey(e) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const q = offlineSearchQuery.trim().toLowerCase();
    if (!q) return;
    const matches = filterEntryItems(q);
    const exact = matches.find(p => String(p.our_product_id || "").toLowerCase() === q);
    const best = exact || matches[0];
    if (!best) return ctx.toast("No product match", "error");
    pickOfflineProduct(best.catalog_product_id);
  }

  function onOfflineQtyKey(e) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    offlineSearchQuery = "";
    focusQtyProductId = null;
    const item = document.getElementById("co-order-item");
    if (item) { item.value = ""; item.focus(); }
  }

  function pickOfflineProduct(catalogProductId) {
    if (offlineLines.some(l => l.catalog_product_id === catalogProductId)) {
      const el = document.querySelector(`[data-qty-for="${catalogProductId}"]`);
      if (el) { el.disabled = false; el.focus(); el.select(); }
      return;
    }
    toggleOfflineProduct(catalogProductId, true);
  }

  async function ensureOfflineProductsLoaded() {
    return;
  }

  function toggleOfflineProduct(catalogProductId, checked) {
    const p = (entryItems || []).find(x => x.catalog_product_id === catalogProductId)
      || offlineSearchResults.find(x => x.catalog_product_id === catalogProductId);
    if (!p) return;
    if (checked) {
      if (!offlineLines.find(l => l.catalog_product_id === catalogProductId)) {
        offlineLines.push({
          catalog_product_id: p.catalog_product_id,
          our_product_id: p.our_product_id,
          quantity: 1,
          min_qty: 0,
          selling_price: p.selling_price,
          quantity_on_hand: p.quantity_on_hand,
          addons: (p.addons && p.addons.length) ? p.addons : (p.priced_addons || []),
          priced_addons: p.priced_addons || [],
          skip_addon_ids: [],
        });
      }
    } else {
      const existing = offlineLines.find(l => l.catalog_product_id === catalogProductId);
      if (existing && Number(existing.min_qty) > 0) {
        existing.quantity = Number(existing.min_qty);
        return ctx.toast(`Keep billed qty (${existing.min_qty}) — cannot remove billed product`, "error");
      }
      offlineLines = offlineLines.filter(l => l.catalog_product_id !== catalogProductId);
    }
    if (checked) focusQtyProductId = catalogProductId;
    const itemInput = document.getElementById("co-order-item");
    if (itemInput) itemInput.value = "";
    offlineSearchQuery = "";
    const matches = document.getElementById("co-order-item-matches");
    if (matches) matches.innerHTML = "";
    paintOrderLines();
    if (checked) {
      const el = document.querySelector(`[data-qty-for="${catalogProductId}"]`);
      if (el) { el.focus(); el.select(); }
    }
  }

  function skipOfflineAddon(catalogProductId, addonId) {
    const line = offlineLines.find(l => l.catalog_product_id === catalogProductId);
    if (!line) return;
    const id = Number(addonId);
    const skipped = new Set(line.skip_addon_ids || []);
    if (skipped.has(id)) skipped.delete(id);
    else skipped.add(id);
    line.skip_addon_ids = [...skipped];
    paintOrderLines();
  }

  function removeOfflineLine(catalogProductId) {
    toggleOfflineProduct(catalogProductId, false);
  }

  function setOfflineQty(cid, raw) {
    const line = offlineLines.find(l => l.catalog_product_id === cid);
    const minQ = line ? (Number(line.min_qty) || 0) : 0;
    const qty = Math.max(minQ || 1, parseInt(String(raw || "1"), 10) || 1);
    if (line) line.quantity = qty;
    else {
      const p = (entryItems || []).find(x => x.catalog_product_id === cid)
        || offlineSearchResults.find(x => x.catalog_product_id === cid);
      if (p) offlineLines.push({
        catalog_product_id: p.catalog_product_id,
        our_product_id: p.our_product_id,
        quantity: qty,
        min_qty: 0,
        selling_price: p.selling_price,
        quantity_on_hand: p.quantity_on_hand,
        addons: (p.addons && p.addons.length) ? p.addons : (p.priced_addons || []),
        priced_addons: p.priced_addons || [],
        skip_addon_ids: [],
      });
    }
    const mid = document.querySelector("#co-offline-footer .vo-wiz-footer-mid");
    if (mid && offlineLines.length) mid.textContent = `${offlineLines.length} item(s) · est. ${fmtPrice(offlineCartTotal())}`;
  }

  function bumpOfflineQty(cid, delta) {
    const line = offlineLines.find(l => l.catalog_product_id === cid);
    if (!line) {
      if (delta > 0) toggleOfflineProduct(cid, true);
      return;
    }
    const minQ = Number(line.min_qty) || 0;
    line.quantity = Math.max(minQ || 1, (Number(line.quantity) || 1) + delta);
    paintOrderLines();
  }

  async function offlineNext() {
    if (offlineStep === 1) {
      if (!offlineCustomerId) return ctx.toast("Select a customer", "error");
      offlineStep = 2;
      renderOfflineWizard();
      return;
    }
    if (offlineStep === 2) {
      if (!offlineLines.length) return ctx.toast("Add at least one product", "error");
      ctx.showLoading?.();
      try {
        offlinePreview = await ctx.api(`/customer-orders/customer/${offlineCustomerId}/offline/preview`, {
          method: "POST",
          body: JSON.stringify(buildOfflineBody()),
        });
        offlineStep = 3;
        renderOfflineWizard();
      } catch (e) { ctx.toast(e.message, "error"); }
      finally { ctx.hideLoading?.(); }
    }
  }

  function offlineBack() {
    if (offlineEditPlacementId) {
      if (offlineStep > 2) { offlineStep -= 1; renderOfflineWizard(); }
      return;
    }
    if (offlineStep > 1) { offlineStep -= 1; renderOfflineWizard(); }
  }

  async function submitOffline() {
    if (offlineBusy || !offlineCustomerId) return;
    const notesEl = document.getElementById("co-offline-notes");
    if (notesEl) offlineNotes = notesEl.value || "";
    const body = buildOfflineBody();
    if (!body.lines || !body.lines.length) {
      return ctx.toast("Add at least one product before placing the order", "error");
    }
    offlineBusy = true;
    if (!offlineConfirmDuplicate) showOrderPlaced();
    try {
      if (offlineEditPlacementId) {
        const pid = offlineEditPlacementId;
        const cid = offlineCustomerId;
        await ctx.api(`/customer-orders/placements/${pid}`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
        ctx.invalidateCache?.("/customer-orders");
        ctx.invalidateCache?.("/stock");
        closeOfflineWizard();
        ctx.toast("Order updated", "success");
        await openDetail(cid, "received");
        loadList(true);
        return;
      }
      const res = await ctx.api(`/customer-orders/customer/${offlineCustomerId}/offline`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      ctx.invalidateCache?.("/customer-orders");
      ctx.invalidateCache?.("/stock");
      const cid = offlineCustomerId;
      ctx.toast("Order placed", "success");
      detailCustomerId = cid;
      currentBucket = "open";
      closeOfflineWizard();
      await processOrder({ quiet: true });
      loadList(true);
    } catch (e) {
      const matches = e.status === 409 && e.detail && e.detail.matches;
      if (matches) {
        showDuplicateWarning(e.detail);
        return;
      }
      offlineConfirmDuplicate = false;
      ctx.toast(e.message || "Could not place order", "error");
      renderOfflineWizard();
    } finally {
      offlineBusy = false;
    }
  }

  function showDuplicateWarning(detail) {
    const body = document.getElementById("co-offline-body");
    const footer = document.getElementById("co-offline-footer");
    const rows = (detail.matches || []).map((m) => {
      const bits = [];
      if (m.same_items && m.same_items.length) bits.push(`same item ${m.same_items.join(", ")}`);
      if (m.same_amount) bits.push(`same amount ₹${m.total}`);
      return `<li>Order #${m.placement_id}: ${bits.join(" · ")}</li>`;
    }).join("");
    if (body) {
      body.innerHTML = `<div style="border:2px solid #b45309;background:#fffbeb;border-radius:12px;padding:16px;">
        <strong style="font-size:18px;">This could be a duplicate entry.</strong>
        <p style="margin:8px 0;">Same date, same party. The following are the same:</p>
        <ul style="margin:0 0 8px 18px;">${rows}</ul>
        <p style="margin:0;">Do you want to proceed?</p>
      </div>`;
    }
    if (footer) {
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="CustomerOrders.backFromDuplicate()">Go back</button>
        <button class="btn btn-primary" onclick="CustomerOrders.proceedDuplicate()">Proceed</button>`;
    }
  }

  function backFromDuplicate() {
    offlineConfirmDuplicate = false;
    offlineBusy = false;
    renderOfflineWizard();
  }

  function proceedDuplicate() {
    offlineConfirmDuplicate = true;
    submitOffline();
  }

  function showOrderPlaced() {
    const body = document.getElementById("co-offline-body");
    const footer = document.getElementById("co-offline-footer");
    if (body) body.innerHTML = `<p style="margin:0;font-size:18px;"><strong>Order placed.</strong> Opening the bill…</p>`;
    if (footer) footer.innerHTML = "";
  }

  function _detailCustomerId() { return detailCustomerId; }

  function openCustomer(customerId, bucket) {
    return openDetail(customerId, bucket || "open");
  }

  return {
    init, loadList, setBucket, setHubMode, setPrintDay, setQueueFilter, setHubSearch, setHubPrice, setHubSort, toggleCreatedBy, showHub, openDetail, openCustomer, switchBucket, toggleDetailExpand,
    openSlidePanel, closeSlidePanel, toggleCardMore, closeAllCardMore,
    goToDispatch, goCollectPayment, setDispatchStatus, setDispatchAgent, setParcelAgent, setParcelHandler, pickParcel, askDispatchNarration, saveDispatchNarration, markDispatchPicked, setDispatchMode, addDispatchCharge, togglePickedStory, reassignParcel, submitParcelReassign,
    showCreateMenu, showCreateMenuFromCustomer, openCloseBatch,
    processOrder, processFromHub, billNow, billBookedOrder, closeProcessWizard, renderProcessWizard,
    openEditBill, editLatestBill, promptEditBillNumber, saveBillNumber, enableDiscount, clearDiscount, setBillEditSearch, addBillEditProduct, removeProcessLine, cancelProcessLine,
    openEditFromOpen,
    _detailCustomerId,
    setShipQty, setLineDisc, setLineNetRate, setDiscToggle, setOverallDisc, skipBillAddon,
    setFreightAgent, setFreightHandler, setFreightCharges, setTransportMode, setTransportReceipt, setPackagingCharges,
    setGst, setGstRate, setBillSeries, setNarration, setEditBillNumber, setBillDate, setAddCharge, addChargeRow, openCatalogPicker, addPickedCatalog, toggleBillCatalog, setBillCatalogPrice, focusNextBillItem,
    setOfflinePlacedOn,
    setForceCredit, setBillOnAgent, printDayDuplicates,
    processNext, processBack, submitProcess, backFromBillDuplicate, proceedBillDuplicate, toggleBillOrder, toggleAllBillOrders,
    confirmOrder, _doConfirm, openTileMark, cancelTileMark, saveTileMark, cancelOpenLine, cancelReceivedLine, cancelBilledLine, cancelPlacement, cancelCustomerOpen, cancelEntireReceived, cancelAllOpen, editOpenLine, editReceivedLine, deleteReceivedLine, openEditPlacement, closeBillLine, cancelBill, voidBill, voidPlacement, openBillDoc, printStoredBill, downloadStoredBill, shareBillWhatsApp, uploadBillQr, resetBillQr,
    openOfflineWizard, closeOfflineWizard, renderOfflineWizard,
    pickOfflineCustomer, onOfflineCustomerSearch, setOfflineNotes, previewOrder, backFromOrderPreview,
    onOfflineSearchInput, onOfflineSearchKey, onOfflineQtyKey, toggleOfflineProduct, pickOfflineProduct, removeOfflineLine, skipOfflineAddon,
    setOfflineQty, bumpOfflineQty, offlineNext, offlineBack, submitOffline, backFromDuplicate, proceedDuplicate,
  };
})();
