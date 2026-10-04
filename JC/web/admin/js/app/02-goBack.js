  function goBack() {
    // Modal detail panel first
    if (!document.getElementById("detail")?.classList.contains("hidden")) {
      if (detailStack.length) detailBack();
      else closeDetail();
      updateGlobalBack();
      return;
    }
    // Nested hubs inside a view
    if (currentViewName === "selling" && document.getElementById("co-slide-panel")?.classList.contains("is-open")) {
      CustomerOrders.closeSlidePanel?.();
      updateGlobalBack();
      return;
    }
    if (currentViewName === "buying" && !document.getElementById("orders-detail")?.classList.contains("hidden")) {
      VendorOrders.showHub?.();
      updateGlobalBack();
      return;
    }
    if (currentViewName === "returns" && !document.getElementById("returns-detail")?.classList.contains("hidden")) {
      Returns.showHub?.();
      updateGlobalBack();
      return;
    }
    if (currentViewName === "reports" && !document.getElementById("reports-ledger-detail")?.classList.contains("hidden")) {
      Reports.backFromLedger?.();
      updateGlobalBack();
      return;
    }
    if (currentViewName === "money") {
      const ap = document.getElementById("finance-ap-detail");
      const ar = document.getElementById("finance-ar-detail");
      const fr = document.getElementById("finance-freight-detail");
      const rt = document.getElementById("finance-routes-detail");
      if (ap && !ap.classList.contains("hidden")
        || ar && !ar.classList.contains("hidden")
        || fr && !fr.classList.contains("hidden")
        || rt && !rt.classList.contains("hidden")) {
        Finance.showHub?.();
        updateGlobalBack();
        return;
      }
    }
    if (currentViewName === "setup" && setupTab) {
      showSetupHub();
      updateGlobalBack();
      return;
    }
    if (currentViewName === "more" && !document.getElementById("more-safety")?.classList.contains("hidden")) {
      showMoreHub();
      updateGlobalBack();
      return;
    }
    if (currentViewName === "people" && peopleTab) {
      showPeopleHub();
      updateGlobalBack();
      return;
    }
    const prev = viewStack.pop();
    if (prev) showView(prev, { replace: true });
    else showView("today", { replace: true });
  }

  function showView(name, opts = {}) {
    if (name === "activity") {
      showView("setup", opts);
      showSetupTab("activity");
      return;
    }
    const resolved = resolveViewName(name);
    if (!opts.replace && currentViewName && currentViewName !== resolved) {
      viewStack.push(currentViewName);
      if (viewStack.length > 40) viewStack.shift();
    }
    currentViewName = resolved;
    name = resolved;

    document.querySelectorAll(".view").forEach(v => v.classList.add("hidden"));
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));

    const markMore = () => document.getElementById("nav-more")?.classList.add("active");

    if (name === "today") {
      document.getElementById("view-today")?.classList.remove("hidden");
      document.getElementById("nav-today")?.classList.add("active");
      Dashboard?.showHub?.();
    } else if (name === "people") {
      document.getElementById("view-people")?.classList.remove("hidden");
      document.getElementById("nav-people")?.classList.add("active");
      if (peopleTab) showPeopleTab(peopleTab);
      else showPeopleHub();
    } else if (name === "products") {
      document.getElementById("view-products")?.classList.remove("hidden");
      document.getElementById("nav-products")?.classList.add("active");
      Products.showHub();
      updateHubCounts();
    } else if (name === "money") {
      if (!isAdmin() && !can("finance.write") && !canRead("ar") && !canRead("ap")) {
        showView("today", { replace: true });
        return;
      }
      document.getElementById("view-finance")?.classList.remove("hidden");
      document.getElementById("nav-money")?.classList.add("active");
      Finance.showHub();
    } else if (name === "more") {
      document.getElementById("view-more")?.classList.remove("hidden");
      document.getElementById("nav-more")?.classList.add("active");
      showMoreHub();
    } else if (name === "buying" || name === "selling") {
      markMore();
      if (name === "selling") {
        ordersType = "customer";
        document.getElementById("view-selling")?.classList.remove("hidden");
        document.getElementById("view-buying")?.classList.add("hidden");
        CustomerOrders.showHub();
      } else {
        ordersType = "vendor";
        document.getElementById("view-buying")?.classList.remove("hidden");
        document.getElementById("view-selling")?.classList.add("hidden");
        VendorOrders.showHub();
      }
    } else if (name === "returns") {
      markMore();
      document.getElementById("view-returns")?.classList.remove("hidden");
      Returns.showHub();
    } else if (name === "reports") {
      if (!isAdmin()) {
        showView("today", { replace: true });
        return;
      }
      markMore();
      document.getElementById("view-reports")?.classList.remove("hidden");
      Reports.showHub();
    } else if (name === "setup") {
      markMore();
      document.getElementById("view-setup")?.classList.remove("hidden");
      if (setupTab) showSetupTab(setupTab);
      else showSetupHub();
    } else if (name === "recycle") {
      markMore();
      document.getElementById("view-recycle")?.classList.remove("hidden");
      loadRecycleBin();
    } else {
      const el = document.getElementById(`view-${name}`);
      if (!el) {
        toast(`Unknown screen: ${name}`, "error");
        showView("today", { replace: true });
        return;
      }
      el.classList.remove("hidden");
      document.getElementById(`nav-${name}`)?.classList.add("active");
    }
    updateGlobalBack();
  }

  function showMoreHub() {
    document.getElementById("more-hub")?.classList.remove("hidden");
    document.getElementById("more-safety")?.classList.add("hidden");
  }

  function showMoreSafety() {
    document.getElementById("more-hub")?.classList.add("hidden");
    document.getElementById("more-safety")?.classList.remove("hidden");
  }

  function showSetupHub() {
    setupTab = null;
    document.getElementById("setup-hub").classList.remove("hidden");
    document.getElementById("setup-routes-cities").classList.add("hidden");
    document.getElementById("setup-staff").classList.add("hidden");
    document.getElementById("setup-activity")?.classList.add("hidden");
    document.getElementById("setup-documents")?.classList.add("hidden");
    document.getElementById("setup-billseries")?.classList.add("hidden");
    document.getElementById("setup-paymodes")?.classList.add("hidden");
    document.getElementById("setup-freight")?.classList.add("hidden");
    document.getElementById("setup-export")?.classList.add("hidden");
    updateSetupHubCounts();
  }

  function showSetupTab(tab) {
    setupTab = tab;
    document.getElementById("setup-hub").classList.add("hidden");
    document.getElementById("setup-routes-cities").classList.toggle("hidden", tab !== "routes");
    document.getElementById("setup-staff").classList.toggle("hidden", tab !== "staff");
    document.getElementById("setup-activity")?.classList.toggle("hidden", tab !== "activity");
    document.getElementById("setup-documents")?.classList.toggle("hidden", tab !== "documents");
    document.getElementById("setup-billseries")?.classList.toggle("hidden", tab !== "billseries");
    document.getElementById("setup-paymodes")?.classList.toggle("hidden", tab !== "paymodes");
    document.getElementById("setup-freight")?.classList.toggle("hidden", tab !== "freight");
    document.getElementById("setup-export")?.classList.toggle("hidden", tab !== "export");
    if (tab === "routes") { renderRoutesTable(); renderCitiesTable(); }
    if (tab === "staff") StaffMgmt.load();
    if (tab === "activity") loadActivity({ tableId: "setup-activity-table", personId: "setup-activity-person-filter", actionId: "setup-activity-action-filter", whatId: "setup-activity-what-filter", whereId: "setup-activity-where-filter", dateId: "setup-activity-date-filter", initPerson: true });
    if (tab === "documents") Documents.load();
    if (tab === "billseries") BillSeries.load();
    if (tab === "paymodes") PaymentModes.load();
    if (tab === "freight") FreightAgentsSetup.load();
  }

  async function downloadExportKind(kind) {
    showLoading?.();
    try {
      await DocShare.downloadExport(kind);
      toast("Excel downloaded", "success");
    } catch (e) { toast(e.message, "error"); }
    finally { hideLoading?.(); }
  }

  async function downloadBackupZip() {
    showLoading?.();
    try {
      await DocShare.downloadExport("backup");
      toast("Full backup ready — every table in Excel zip", "success");
    } catch (e) { toast(e.message, "error"); }
    finally { hideLoading?.(); }
  }

  function updateSetupHubCounts() {
    const hubRoutesCities = document.getElementById("hub-routes-cities-count");
    if (hubRoutesCities) hubRoutesCities.textContent = `${routes.length} routes · ${cities.length} cities`;

    const slot = document.getElementById("setup-stats-slot");
    if (slot) {
      slot.innerHTML = `
        <div class="setup-stat"><span class="setup-stat-num">${routes.length}</span><span class="setup-stat-label">Routes</span></div>
        <div class="setup-stat"><span class="setup-stat-num">${cities.length}</span><span class="setup-stat-label">Cities</span></div>
        <div class="setup-stat" id="setup-stat-staff"><span class="setup-stat-num">—</span><span class="setup-stat-label">Staff</span></div>`;
    }

    if (isAdmin()) {
      api("/staff", {}, 120000).then(s => {
        const n = (s || []).length;
        const hubStaff = document.getElementById("hub-staff-count");
        if (hubStaff) hubStaff.textContent = `${n} staff`;
        const stat = document.querySelector("#setup-stat-staff .setup-stat-num");
        if (stat) stat.textContent = String(n);
      }).catch(() => {});
      api("/bill-series", {}, 120000).then(bs => {
        const el = document.getElementById("hub-billseries-count");
        if (el) el.textContent = `${(bs || []).length} series`;
      }).catch(() => {});
      api("/freight-agents", {}, 120000).then(fa => {
        const n = (fa || []).length;
        const el = document.getElementById("hub-freight-count");
        if (el) el.textContent = `${n} agent${n === 1 ? "" : "s"}`;
      }).catch(() => {});
      const act = document.getElementById("hub-activity-count");
      if (act) act.textContent = "Log";
      const docs = document.getElementById("hub-documents-count");
      if (docs && !docs.dataset.live) docs.textContent = "Files";
    }
  }

  function formatActivityAction(action) {
    const map = {
      create: "Created", update: "Updated", delete: "Deleted",
      place: "Placed order", receive: "Received stock", cancel: "Cancelled placement",
      debit_note: "Debit note", ap_payment: "AP payment",
      update_line: "Updated order line", delete_line: "Removed order line",
    };
    return map[action] || action;
  }

  function formatActivityEntity(i) {
    const labels = {
      vendor: "Vendor", customer: "Customer", catalog: "Product", staff: "Staff",
      vendor_order: "Vendor order", stock_receipt: "Stock receipt",
    };
    const type = labels[i.entity_type] || i.entity_type;
    return i.entity_label ? `${type} — ${i.entity_label}` : type;
  }

  function activityTableHtml(items, { showWho = true, clickable = false } = {}) {
    if (!items.length) {
      return (typeof HubUI !== "undefined" ? HubUI.emptyState : OrdersUI.emptyState)({
        title: "No activity matches",
        sub: "Try clearing filters or refresh the log.",
      });
    }
    items.forEach(i => { activityItemsById[i.id] = i; });
    return `<table class="data"><thead><tr>
      <th>When</th>${showWho ? "<th>Who</th>" : ""}<th>What</th><th>Where</th><th>Details</th>
    </tr></thead><tbody>${items.map(i => `<tr class="${clickable ? "clickable" : ""}" ${clickable ? `onclick="App.openActivityItem(${i.id})"` : ""}>
      <td style="font-size:12px;white-space:nowrap;">${fmtDate(i.created_at)}</td>
      ${showWho ? `<td><strong>${esc(i.actor_name)}</strong></td>` : ""}
      <td>${esc(formatActivityAction(i.action))}</td>
      <td style="font-size:13px;">${esc(formatActivityEntity(i))}</td>
      <td style="font-size:12px;color:var(--muted);max-width:320px;">${esc(i.detail || "—")}</td>
    </tr>`).join("")}</tbody></table>`;
  }

  function entityLedgerTableHtml(items, handlerKey, { showWho = true } = {}) {
    if (!items.length) {
      return `<div class="detail-section"><h4>Ledger</h4><p style="color:var(--muted);font-size:13px;">No entries yet.</p></div>`;
    }
    return `<div class="detail-section"><h4>Ledger</h4>
      <table class="data history-table"><thead><tr>
        <th>When</th>${showWho ? "<th>Who</th>" : ""}<th>What</th><th>Summary</th>
      </tr></thead><tbody>${items.map(e => `<tr class="clickable ledger-row" data-handler="${attrEsc(handlerKey)}" data-entry-id="${attrEsc(e.id)}">
        <td style="font-size:12px;white-space:nowrap;">${fmtDate(e.occurred_at)}</td>
        ${showWho ? `<td>${e.actor_name ? esc(e.actor_name) : "—"}</td>` : ""}
        <td>${esc(e.title)}</td>
        <td style="font-size:12px;color:var(--muted);">${esc(e.summary)}</td>
      </tr>`).join("")}</tbody></table></div>`;
  }

  function bindLedgerRowClicks() {
    document.getElementById("detail-body")?.querySelectorAll(".ledger-row").forEach(row => {
      row.onclick = () => {
        const handler = row.getAttribute("data-handler");
        const id = row.getAttribute("data-entry-id");
        if (handler === "vendor" && typeof Vendors !== "undefined") Vendors.openLedgerEntry(id);
        else if (handler === "stock" && typeof Stock !== "undefined") Stock.openLedgerDetail(parseInt(id, 10));
      };
    });
  }

  function filterActivityItems(items, opts = {}) {
    const what = (opts.whatFilter || "").toLowerCase();
    const where = (opts.whereFilter || "").toLowerCase();
    const date = opts.dateFilter || "";
    return items.filter(i => {
      if (what && !formatActivityAction(i.action).toLowerCase().includes(what) && !(i.action || "").toLowerCase().includes(what)) return false;
      if (where && !formatActivityEntity(i).toLowerCase().includes(where) && !(i.detail || "").toLowerCase().includes(where)) return false;
      if (date && !(i.created_at || "").startsWith(date)) return false;
      return true;
    });
  }

  async function openActivityItem(id) {
    const item = activityItemsById[id];
    if (!item) return;
    const maybePush = () => {
      if (!document.getElementById("detail").classList.contains("hidden")) pushDetailView();
    };
    showLoading();
    try {
      if (item.entity_type === "vendor_order" && item.entity_id) {
        closeDetail();
        showView("buying");
        let bucket = "placed";
        if (item.action === "receive" || item.detail?.includes("recv") || item.detail?.includes("Bill")) bucket = "billed";
        else if (item.action === "cancel" || item.detail?.includes("cancel")) bucket = "cancelled";
        else if (item.action === "close" || item.detail?.includes("closed")) bucket = "closed";
        else if (item.action === "place" || item.action === "create") bucket = "placed";
        // openDetail resolves vendor_id from order when third arg omitted
        await VendorOrders.openDetail(item.entity_id, bucket);
        return;
      }
      if (item.entity_type === "debit_note" && item.entity_id) {
        maybePush();
        await DebitNotes.openEdit(item.entity_id);
        return;
      }
      if (item.entity_type === "accounts_payable" && item.entity_id && isAdmin()) {
        closeDetail();
        showView("finance");
        await Finance.openVendorAp(item.entity_id);
        return;
      }
      if (item.entity_type === "stock_receipt" && item.entity_id) {
        maybePush();
        await Stock.openReceiptDetail(item.entity_id);
        return;
      }
      if (item.entity_type === "catalog") {
        let pid = item.entity_id;
        if (!pid && item.detail) {
          const sku = (item.detail || "").split(",")[0].trim();
          const prods = await api(`/catalog/products?search=${encodeURIComponent(sku)}&limit=20`, {}, 0).catch(() => ({ items: [] }));
          const list = prods.items || (Array.isArray(prods) ? prods : []);
          const match = list.find(p => p.our_product_id === sku) || list[0];
          pid = match?.id;
        }
        if (pid) { maybePush(); await Catalog.openDetail(pid); return; }
      }
      if (item.entity_type === "vendor" && item.entity_id) {
        maybePush();
        await Vendors.openDetail(item.entity_id);
        return;
      }
      if (item.entity_type === "customer" && item.entity_id) {
        maybePush();
        await openCustomerDetail(item.entity_id);
        return;
      }
      if (item.entity_type === "staff" && item.entity_id) {
        maybePush();
        await StaffMgmt.openDetail(item.entity_id);
        return;
      }
      if (item.action === "ap_payment" && item.entity_id && isAdmin()) {
        closeDetail();
        showView("finance");
        await Finance.openVendorAp(item.entity_id);
        return;
      }
      maybePush();
      openDetail(formatActivityAction(item.action), ledgerDetailCard(
        formatActivityEntity(item),
        `${reviewRow("When", fmtDate(item.created_at))}${reviewRow("Who", item.actor_name)}${reviewRow("Details", item.detail)}`,
        "", ""
      ), detailFooterChild(), "md");
    } catch (e) { toast(e.message, "error"); }
    finally { hideLoading(); }
  }

  async function loadActivityPersonFilter(selectId) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    try {
      const staffList = await api("/staff", {}, 60000).catch(() => []);
      sel.innerHTML = `<option value="">All people</option><option value="admin">Admin</option>` +
        staffList.map(s => `<option value="staff:${s.id}">${esc(s.name)}</option>`).join("");
    } catch (_) {}
  }

  async function loadActivity(opts = {}) {
    if (!isAdmin()) return;
    // Defaults = Setup → Activity (orphan #view-activity removed)
    const tableId = opts.tableId || "setup-activity-table";
    const personId = opts.personId || "setup-activity-person-filter";
    const actionId = opts.actionId || "setup-activity-action-filter";
    const whatId = opts.whatId || "setup-activity-what-filter";
    const whereId = opts.whereId || "setup-activity-where-filter";
    const dateId = opts.dateId || "setup-activity-date-filter";
    if (opts.initPerson) await loadActivityPersonFilter(personId);
    const person = document.getElementById(personId)?.value || "";
    const action = document.getElementById(actionId)?.value || "";
    const whatFilter = document.getElementById(whatId)?.value.trim() || "";
    const whereFilter = document.getElementById(whereId)?.value.trim() || "";
    const dateFilter = document.getElementById(dateId)?.value || "";
    const params = new URLSearchParams({ limit: String(opts.limit || 200), offset: "0" });
    if (action) params.set("action", action);
    if (person === "admin") params.set("actor_name", "Admin");
    else if (person.startsWith("staff:")) params.set("actor_id", person.split(":")[1]);
    else if (opts.actorId) params.set("actor_id", String(opts.actorId));
    showLoading();
    try {
      const res = await api(`/activity?${params}`);
      activityItemsCache = res.items || [];
      const filtered = filterActivityItems(activityItemsCache, { whatFilter, whereFilter, dateFilter });
      const el = document.getElementById(tableId);
      if (!el) return;
      el.innerHTML = activityTableHtml(filtered, { showWho: true, clickable: opts.clickable !== false });
    } catch (e) { toast(e.message, "error"); }
    finally { hideLoading(); }
  }

  function showPeopleHub() {
    peopleTab = null;
    document.querySelectorAll(".view").forEach(v => v.classList.add("hidden"));
    document.getElementById("view-people").classList.remove("hidden");
    document.getElementById("people-hub").classList.remove("hidden");
    document.getElementById("people-customers").classList.add("hidden");
    document.getElementById("people-vendors").classList.add("hidden");
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    document.getElementById("nav-people").classList.add("active");
    updateHubCounts();
  }

  function showPeopleTab(tab) {
    peopleTab = tab;
    document.querySelectorAll(".view").forEach(v => v.classList.add("hidden"));
    document.getElementById("view-people").classList.remove("hidden");
    document.getElementById("people-hub").classList.add("hidden");
    document.getElementById("people-customers").classList.toggle("hidden", tab !== "customers");
    document.getElementById("people-vendors").classList.toggle("hidden", tab !== "vendors");
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    document.getElementById("nav-people").classList.add("active");
    if (tab === "customers") loadCustomers();
    if (tab === "vendors") {
      renderPeopleVendorSearch();
      Vendors.load();
    }
  }

  // ── Data ──────────────────────────────────────────────────────────
