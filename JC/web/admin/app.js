const App = (() => {
  const API = (() => {
    const saved = localStorage.getItem("jc_api");
    if (saved) return saved;
    const host = location.hostname;
    if (host === "127.0.0.1" || host === "localhost") return "http://127.0.0.1:8003/api/v1";
    return `${location.origin}/api/v1`;
  })();
  let authMode = sessionStorage.getItem("jc_auth_mode") || "";
  let adminKey = sessionStorage.getItem("jc_admin_key") || "";
  let staffToken = sessionStorage.getItem("jc_staff_token") || "";
  let staffUser = null;
  try { staffUser = JSON.parse(sessionStorage.getItem("jc_staff_user") || "null"); } catch (_) { staffUser = null; }
  let permissions = new Set((staffUser && staffUser.permissions) || []);
  let routes = [], cities = [], customers = [], vendors = [], lookups = [];
  let peopleTab = null;
  let ordersType = "vendor";
  let setupTab = null;
  let recycleData = { routes: [], cities: [], customers: [], total: 0 };
  let recycleTab = "all";
  let wizardStep = 1, wizardForm = {};
  let detailMode = null;
  let detailId = null;
  let detailStack = [];
  let activityItemsById = {};
  let activityItemsCache = [];
  let editingCustomerId = null;

  function headers() {
    const h = { "Content-Type": "application/json" };
    if (authMode === "admin" && adminKey) h["X-Admin-Key"] = adminKey;
    else if (authMode === "staff" && staffToken) h["Authorization"] = `Bearer ${staffToken}`;
    return h;
  }

  function isAdmin() { return authMode === "admin"; }
  function can(perm) { return isAdmin() || permissions.has(perm); }
  function canWrite(resource) { return can(resource + ".write"); }
  function canRead(resource) { return can(resource + ".read"); }

  function applyNavPermissions() {
    const showPeople = canRead("customers") || canRead("vendors");
    const showProducts = canRead("catalog") || canRead("addons");
    document.getElementById("nav-people")?.classList.toggle("hidden", !showPeople);
    document.getElementById("nav-products")?.classList.toggle("hidden", !showProducts);
    document.getElementById("nav-orders")?.classList.toggle("hidden", !canRead("vendor_orders"));
    document.getElementById("nav-finance")?.classList.toggle("hidden", !isAdmin());
    document.getElementById("nav-setup")?.classList.toggle("hidden", !canRead("setup"));
    document.getElementById("nav-recycle")?.classList.toggle("hidden", !canRead("recycle"));
    document.getElementById("nav-activity")?.classList.toggle("hidden", !isAdmin());
    document.getElementById("setup-tile-staff")?.classList.toggle("hidden", !isAdmin());
    document.getElementById("setup-tile-activity")?.classList.toggle("hidden", !isAdmin());
    document.getElementById("setup-tile-documents")?.classList.toggle("hidden", !isAdmin());
    document.getElementById("setup-tile-billseries")?.classList.toggle("hidden", !isAdmin());
    document.getElementById("staff-new-btn")?.classList.toggle("hidden", !isAdmin());
    document.querySelector(".big-tile-customers")?.classList.toggle("hidden", !canRead("customers"));
    document.querySelector(".big-tile-vendors")?.classList.toggle("hidden", !canRead("vendors"));
    document.getElementById("products-catalog-tile")?.classList.add("hidden");
    document.getElementById("products-addons-tile")?.classList.add("hidden");
    const badge = document.getElementById("user-badge");
    if (badge) {
      if (isAdmin()) badge.textContent = "Admin";
      else if (staffUser) badge.textContent = staffUser.name;
      else badge.textContent = "";
    }
    document.querySelectorAll("[data-require-write]").forEach(el => {
      const res = el.getAttribute("data-require-write");
      el.classList.toggle("hidden", !canWrite(res));
    });
  }

  function setLoginTab(tab) {
    document.getElementById("login-admin-panel").classList.toggle("hidden", tab !== "admin");
    document.getElementById("login-staff-panel").classList.toggle("hidden", tab !== "staff");
    document.getElementById("login-tab-admin").classList.toggle("btn-primary", tab === "admin");
    document.getElementById("login-tab-admin").classList.toggle("btn-secondary", tab !== "admin");
    document.getElementById("login-tab-staff").classList.toggle("btn-primary", tab === "staff");
    document.getElementById("login-tab-staff").classList.toggle("btn-secondary", tab !== "staff");
  }

  function showLoading() {
    document.getElementById("loading")?.classList.remove("hidden");
  }

  function hideLoading() {
    document.getElementById("loading")?.classList.add("hidden");
  }

  function debounce(fn, ms = 350) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  }

  const debouncedLoadCustomers = debounce(() => loadCustomers(), 350);
  const debouncedVendorSearch = debounce(() => Vendors.load(), 350);
  const debouncedCatalogSearch = debounce(() => Catalog.load(), 350);
  const debouncedAddonSearch = debounce(() => AddonProducts.load(), 350);
  const debouncedStockSearch = debounce(() => Stock.load(), 350);

  async function api(path, opts = {}, cacheTtl = 0) {
    const isGet = !opts.method || opts.method === "GET";
    if (isGet && cacheTtl > 0) {
      const cached = Cache.get(path);
      if (cached !== null) return cached;
    }
    const doFetch = async () => {
      const res = await fetch(`${API}${path}`, { ...opts, headers: { ...headers(), ...(opts.headers || {}) } });
      if (res.status === 401) {
        logout();
        throw new Error("Session expired — please sign in again");
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const msg = typeof err.detail === "string" ? err.detail : Array.isArray(err.detail) ? err.detail.map(d => d.msg).join(", ") : `HTTP ${res.status}`;
        throw new Error(msg);
      }
      if (res.status === 204) return null;
      return res.json();
    };
    let data;
    try {
      data = await doFetch();
    } catch (e) {
      throw e;
    }
    if (isGet && cacheTtl > 0) Cache.set(path, data, null, cacheTtl);
    return data;
  }

  async function checkBackend() {
    try {
      const base = API.replace(/\/api\/v1\/?$/, "");
      const res = await fetch(`${base}/api/v1/ping`, { method: "GET" });
      return res.ok;
    } catch (_) { return false; }
  }

  function invalidateCache(prefix) {
    if (prefix) Cache.invalidate(prefix);
    else Cache.clear();
  }

  async function updateHubCounts() {
    const apply = (s) => {
      const hubCust = document.getElementById("hub-customers-count");
      const hubVend = document.getElementById("hub-vendors-count");
      const hubCat = document.getElementById("hub-catalog-count");
      const hubAddon = document.getElementById("hub-addons-count");
      if (hubCust) hubCust.textContent = `${s.customers} active`;
      if (hubVend) hubVend.textContent = `${s.vendors} active`;
      if (hubCat) hubCat.textContent = `${s.catalog_products} products`;
      if (hubAddon) hubAddon.textContent = `${s.addons} add-ons`;
      const hubStock = document.getElementById("hub-stock-count");
      if (hubStock && s.stock_on_hand != null) hubStock.textContent = `${s.stock_on_hand} items`;
    };
    try {
      const s = await api("/stats", {}, 30000);
      apply(s);
    } catch (_) {
      apply({
        customers: customers.length,
        vendors: vendors.length,
        routes: routes.length,
        cities: cities.length,
        catalog_products: 0,
        addons: 0,
      });
    }
  }

  function toast(msg, type = "info") {
    const el = document.createElement("div");
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    document.getElementById("toasts").appendChild(el);
    setTimeout(() => el.remove(), 4500);
  }

  function esc(s) {
    if (s == null) return "";
    const d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function fmtDate(d) {
    if (!d) return "—";
    return new Date(d).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
  }

  function attrEsc(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  function updateDetailNav() {
    const back = document.getElementById("detail-back-btn");
    if (back) back.classList.toggle("hidden", detailStack.length === 0);
  }

  function pushDetailView() {
    if (document.getElementById("detail").classList.contains("hidden")) return;
    detailStack.push({
      title: document.getElementById("detail-title").textContent,
      body: document.getElementById("detail-body").innerHTML,
      footer: document.getElementById("detail-footer").innerHTML,
      size: (document.getElementById("detail-panel").className.match(/\b(sm|md|lg)\b/) || ["", "md"])[1],
    });
    updateDetailNav();
  }

  function openDetail(title, bodyHtml, footerHtml, size = "md", opts = {}) {
    if (opts.push) pushDetailView();
    document.getElementById("detail-title").textContent = title;
    document.getElementById("detail-body").innerHTML = bodyHtml;
    document.getElementById("detail-footer").innerHTML = footerHtml;
    document.getElementById("detail-panel").className = `detail-panel ${size}`;
    document.getElementById("detail").classList.remove("hidden");
    updateDetailNav();
  }

  function detailBack() {
    const prev = detailStack.pop();
    if (!prev) { closeDetail(); return; }
    document.getElementById("detail-title").textContent = prev.title;
    document.getElementById("detail-body").innerHTML = prev.body;
    document.getElementById("detail-footer").innerHTML = prev.footer;
    document.getElementById("detail-panel").className = `detail-panel ${prev.size}`;
    document.getElementById("detail").classList.remove("hidden");
    updateDetailNav();
  }

  function closeDetail() {
    detailStack = [];
    document.getElementById("detail").classList.add("hidden");
    detailMode = null;
    detailId = null;
    updateDetailNav();
  }

  function detailFooterChild() {
    return `<button class="btn btn-secondary" onclick="App.detailBack()">← Back</button>`;
  }

  function ledgerDetailCard(title, metaHtml, tableHtml, extraHtml = "") {
    return `<div class="ledger-detail-card">
      <h4 style="margin:0 0 12px;font-size:15px;">${esc(title)}</h4>
      <div class="ledger-detail-meta">${metaHtml}</div>
      ${extraHtml}
      ${tableHtml ? `<div class="table-wrap" style="margin-top:12px;">${tableHtml}</div>` : ""}
    </div>`;
  }

  // ── Auth ──────────────────────────────────────────────────────────
  async function enterApp() {
    document.getElementById("login-screen").classList.add("hidden");
    document.getElementById("app").classList.remove("hidden");
    Vendors.init(sharedCtx());
    Catalog.init(sharedCtx());
    AddonProducts.init(sharedCtx());
    Products.init(sharedCtx());
    StaffMgmt.init(sharedCtx());
    VendorOrders.init(sharedCtx());
    CustomerOrders.init(sharedCtx());
    Stock.init(sharedCtx());
    try { DebitNotes.init(sharedCtx()); } catch (e) { console.error("DebitNotes init failed", e); }
    try { Finance.init(sharedCtx()); } catch (e) { console.error("Finance init failed", e); }
    try { Documents.init(sharedCtx()); } catch (e) { console.error("Documents init failed", e); }
    try { BillSeries.init(sharedCtx()); } catch (e) { console.error("BillSeries init failed", e); }
    try { FreightAgentsSetup.init(sharedCtx()); } catch (e) { console.error("FreightAgentsSetup init failed", e); }
    applyNavPermissions();
    const first = canRead("customers") || canRead("vendors") ? "people"
      : canRead("catalog") || canRead("addons") ? "products"
      : canRead("vendor_orders") ? "orders"
      : canRead("setup") ? "setup"
      : canRead("recycle") ? "recycle"
      : isAdmin() ? "setup" : "products";
    showView(first);
    try { await refreshAll(); } catch (_) {}
    if (isAdmin()) {
      try {
        const s = await api("/staff");
        const hubStaff = document.getElementById("hub-staff-count");
        if (hubStaff) hubStaff.textContent = `${s.length} staff`;
      } catch (_) {}
    }
  }

  async function login() {
    const key = document.getElementById("admin-key-input").value.trim();
    if (!key) return;
    adminKey = key;
    authMode = "admin";
    staffToken = "";
    staffUser = null;
    permissions = new Set();
    try {
      const h = { "Content-Type": "application/json", "X-Admin-Key": key };
      const res = await fetch(`${API}/routes`, { headers: h });
      if (!res.ok) throw new Error("Invalid admin key");
      sessionStorage.setItem("jc_auth_mode", "admin");
      sessionStorage.setItem("jc_admin_key", key);
      sessionStorage.removeItem("jc_staff_token");
      sessionStorage.removeItem("jc_staff_user");
      await enterApp();
    } catch (e) {
      const el = document.getElementById("login-error");
      el.textContent = e.message;
      el.classList.remove("hidden");
    }
  }

  async function staffLogin() {
    const phone = (document.getElementById("staff-phone-input").value || "").replace(/\D/g, "");
    const password = document.getElementById("staff-password-input").value.trim();
    if (phone.length !== 10) return toast("Phone must be 10 digits", "error");
    try {
      const res = await fetch(`${API}/auth/staff/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, password }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(typeof err.detail === "string" ? err.detail : "Login failed");
      }
      const data = await res.json();
      authMode = "staff";
      staffToken = data.access_token;
      staffUser = data.staff;
      permissions = new Set(data.staff.permissions || []);
      adminKey = "";
      sessionStorage.setItem("jc_auth_mode", "staff");
      sessionStorage.setItem("jc_staff_token", staffToken);
      sessionStorage.setItem("jc_staff_user", JSON.stringify(staffUser));
      sessionStorage.removeItem("jc_admin_key");
      await enterApp();
    } catch (e) {
      const el = document.getElementById("login-error");
      el.textContent = e.message;
      el.classList.remove("hidden");
    }
  }

  function logout() {
    sessionStorage.removeItem("jc_admin_key");
    sessionStorage.removeItem("jc_staff_token");
    sessionStorage.removeItem("jc_staff_user");
    sessionStorage.removeItem("jc_auth_mode");
    location.reload();
  }

  function toggleSidebar() {
    const sb = document.getElementById("sidebar");
    const main = document.getElementById("main");
    const collapsed = sb.classList.toggle("collapsed");
    sb.classList.toggle("expanded", !collapsed);
    main.classList.toggle("shift-collapsed", collapsed);
    main.classList.toggle("shift-expanded", !collapsed);
    document.getElementById("brand-block").classList.toggle("hidden", collapsed);
    document.querySelectorAll(".nav-text").forEach(el => el.classList.toggle("hidden", collapsed));
  }

  function showView(name) {
    document.querySelectorAll(".view").forEach(v => v.classList.add("hidden"));
    document.getElementById(`view-${name}`).classList.remove("hidden");
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    if (name === "people") {
      document.getElementById("nav-people").classList.add("active");
      if (peopleTab) showPeopleTab(peopleTab);
      else showPeopleHub();
    } else if (name === "products") {
      document.getElementById("nav-products").classList.add("active");
      Products.showHub();
      updateHubCounts();
    } else if (name === "orders") {
      document.getElementById("nav-orders").classList.add("active");
      setOrdersType(ordersType || "vendor");
    } else if (name === "finance") {
      if (!isAdmin()) {
        showView("products");
        return;
      }
      document.getElementById("nav-finance").classList.add("active");
      Finance.showHub();
    } else {
      document.getElementById(`nav-${name}`)?.classList.add("active");
    }
    if (name === "setup") {
      if (setupTab) showSetupTab(setupTab);
      else showSetupHub();
    }
    if (name === "recycle") loadRecycleBin();
    if (name === "activity") loadActivity({ initPerson: true });
  }

  function showSetupHub() {
    setupTab = null;
    document.getElementById("setup-hub").classList.remove("hidden");
    document.getElementById("setup-products").classList.add("hidden");
    document.getElementById("setup-routes-cities").classList.add("hidden");
    document.getElementById("setup-staff").classList.add("hidden");
    document.getElementById("setup-activity")?.classList.add("hidden");
    document.getElementById("setup-documents")?.classList.add("hidden");
    document.getElementById("setup-billseries")?.classList.add("hidden");
    document.getElementById("setup-freight")?.classList.add("hidden");
    const grid = document.getElementById("setup-grid");
    if (grid) {
      grid.style.display = "grid";
      grid.style.gridTemplateColumns = "1fr 1fr 1fr";
      grid.style.gap = "20px";
      grid.style.width = "100%";
    }
    updateSetupHubCounts();
  }

  function showSetupTab(tab) {
    setupTab = tab;
    document.getElementById("setup-hub").classList.add("hidden");
    document.getElementById("setup-products").classList.toggle("hidden", tab !== "products");
    document.getElementById("setup-routes-cities").classList.toggle("hidden", tab !== "routes");
    document.getElementById("setup-staff").classList.toggle("hidden", tab !== "staff");
    document.getElementById("setup-activity")?.classList.toggle("hidden", tab !== "activity");
    document.getElementById("setup-documents")?.classList.toggle("hidden", tab !== "documents");
    document.getElementById("setup-billseries")?.classList.toggle("hidden", tab !== "billseries");
    document.getElementById("setup-freight")?.classList.toggle("hidden", tab !== "freight");
    if (tab === "products") renderLookupSections();
    if (tab === "routes") { renderRoutesTable(); renderCitiesTable(); }
    if (tab === "staff") StaffMgmt.load();
    if (tab === "activity") loadActivity({ tableId: "setup-activity-table", personId: "setup-activity-person-filter", actionId: "setup-activity-action-filter", whatId: "setup-activity-what-filter", whereId: "setup-activity-where-filter", dateId: "setup-activity-date-filter", initPerson: true });
    if (tab === "documents") Documents.load();
    if (tab === "billseries") BillSeries.load();
    if (tab === "freight") FreightAgentsSetup.load();
  }

  function updateSetupHubCounts() {
    const hubLookups = document.getElementById("hub-lookups-count");
    const hubRoutesCities = document.getElementById("hub-routes-cities-count");
    if (hubLookups) hubLookups.textContent = `${lookups.length} options`;
    if (hubRoutesCities) hubRoutesCities.textContent = `${routes.length} routes · ${cities.length} cities`;
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
    if (!items.length) return '<div class="empty-state"><p>No activity yet.</p></div>';
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
        showView("orders");
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
    const tableId = opts.tableId || "activity-table";
    const personId = opts.personId || "activity-person-filter";
    const actionId = opts.actionId || "activity-action-filter";
    const whatId = opts.whatId || "activity-what-filter";
    const whereId = opts.whereId || "activity-where-filter";
    const dateId = opts.dateId || "activity-date-filter";
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
    if (tab === "vendors") Vendors.load();
  }

  // ── Data ──────────────────────────────────────────────────────────
  async function refreshAll() {
    showLoading();
    try {
      ["/routes", "/cities", "/customers", "/vendors", "/lookups", "/stats", "/catalog"].forEach(p => invalidateCache(p));
      const [r, c, cust, vend, lu, stats] = await Promise.all([
        api("/routes", {}, 120000).catch(() => []),
        api("/cities", {}, 120000).catch(() => []),
        api("/customers", {}, 60000).catch(() => []),
        api("/vendors", {}, 60000).catch(() => []),
        api("/lookups", {}, 300000).catch(() => []),
        api("/stats", {}, 30000).catch(() => null),
      ]);
      routes = r; cities = c; customers = cust; vendors = vend; lookups = lu;
      if (typeof Catalog !== "undefined" && Catalog.setVendors) Catalog.setVendors(vend);
      if (stats) {
        const hubCat = document.getElementById("hub-catalog-count");
        const hubAddon = document.getElementById("hub-addons-count");
        if (hubCat) hubCat.textContent = `${stats.catalog_products} products`;
        if (hubAddon) hubAddon.textContent = `${stats.addons} add-ons`;
      }
      await updateHubCounts();
      updateSetupHubCounts();
      if (isAdmin()) {
        api("/bill-series", {}, 120000).then(bs => {
          const el = document.getElementById("hub-billseries-count");
          if (el) el.textContent = `${(bs || []).length} series`;
        }).catch(() => {});
        api("/freight-agents", {}, 120000).then(fa => {
          const el = document.getElementById("hub-freight-count");
          if (el) el.textContent = `${(fa || []).length} agent${(fa || []).length === 1 ? "" : "s"}`;
        }).catch(() => {});
      }
      renderRoutesTable();
      renderCitiesTable();
      renderLookupSections();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      hideLoading();
    }
  }

  async function loadCustomers() {
    const q = document.getElementById("search-input")?.value.trim() || "";
    customers = await api(`/customers${q ? "?search=" + encodeURIComponent(q) : ""}`, {}, 0);
    renderCustomersTable();
  }

  async function reloadCustomers() {
    invalidateCache("/customers");
    invalidateCache("/stats");
    showLoading();
    try {
      await loadCustomers();
      await updateHubCounts();
      toast("Customer list refreshed", "success");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      hideLoading();
    }
  }

  // ── Routes ────────────────────────────────────────────────────────
  const ROUTE_COLS = [
    { key: "name", label: "Name", get: r => r.name },
    { key: "cities", label: "Cities", get: r => String(r.city_count) },
    { key: "customers", label: "Customers", get: r => String(r.customer_count || 0) },
    { key: "notes", label: "Notes", get: r => r.notes || "" },
    { key: "_actions", label: "", filterable: false, sortable: false },
  ];

  function renderRoutesTable() {
    const el = document.getElementById("routes-table");
    if (!routes.length) {
      el.innerHTML = '<div class="empty-state"><p>No routes yet.</p></div>';
      return;
    }
    const rows = TableUtils.apply(routes, "routes", ROUTE_COLS);
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("routes", ROUTE_COLS)}<tbody>
      ${rows.map(r => `<tr class="clickable" onclick="App.openRouteDetail(${r.id})">
        <td><strong>${esc(r.name)}</strong></td>
        <td><span class="badge badge-blue">${r.city_count} cities</span></td>
        <td><span class="badge badge-gray">${r.customer_count || 0} customers</span></td>
        <td style="color:var(--muted);font-size:13px;">${esc(r.notes || "—")}</td>
        <td onclick="event.stopPropagation()">${canWrite("setup") ? `<div class="actions">
          <button class="btn btn-ghost btn-sm" onclick="App.openRouteModal(${r.id})">Edit</button>
          <button class="btn btn-danger btn-sm" onclick="App.deleteRoute(${r.id},${JSON.stringify(r.name)})">Delete</button>
        </div>` : ""}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  async function openRouteDetail(id) {
    const r = await api(`/routes/${id}`);
    detailMode = "route"; detailId = id;
    openDetail("Route Details", `
      <div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("Name", r.name)}
        ${reviewRow("Notes", r.notes)}
        ${reviewRow("Cities", r.city_count)}
        ${reviewRow("Customers", r.customer_count)}
        ${reviewRow("Created", fmtDate(r.created_at))}
      </div>
      <div class="detail-section">
        <h4>Cities on this route (${r.cities.length})</h4>
        ${r.cities.length ? `<table class="data"><thead><tr><th>City</th><th>Customers</th></tr></thead><tbody>
          ${r.cities.map(c => `<tr class="clickable" onclick="App.closeDetail();App.openCityDetail(${c.id})"><td>${esc(c.name)}</td><td>${c.customer_count}</td></tr>`).join("")}
        </tbody></table>` : '<p style="color:var(--muted);font-size:14px;">No cities assigned yet.</p>'}
      </div>`,
      `${canWrite("setup") ? `<button class="btn btn-danger btn-sm" onclick="App.deleteRoute(${id},${JSON.stringify(r.name)})">Delete</button>
       <button class="btn btn-secondary" onclick="App.closeDetail();App.openRouteModal(${id})">Edit</button>` : ""}
       <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "lg"
    );
  }

  function openRouteModal(id) {
    const editing = id ? routes.find(r => r.id === id) : null;
    document.getElementById("modal-title").textContent = editing ? "Edit Route" : "Add Route";
    document.getElementById("modal-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Route Name *</label><input id="m-route-name" class="input" value="${esc(editing?.name || "")}" /></div>
        <div><label class="label">Notes</label><input id="m-route-notes" class="input" value="${esc(editing?.notes || "")}" /></div>
      </div>`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="App.saveRoute(${id || "null"})">${editing ? "Save" : "Create"}</button>`;
    document.getElementById("modal").classList.remove("hidden");
  }

  async function saveRoute(id) {
    const name = document.getElementById("m-route-name").value.trim();
    if (!name) return toast("Route name required", "error");
    const notes = document.getElementById("m-route-notes").value.trim() || null;
    try {
      if (id) await api(`/routes/${id}`, { method: "PATCH", body: JSON.stringify({ name, notes }) });
      else await api("/routes", { method: "POST", body: JSON.stringify({ name, notes }) });
      closeModal(); closeDetail();
      await refreshAll();
      toast(id ? "Route updated" : "Route created", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  async function deleteRoute(id, name) {
    if (!confirm(`Move route "${name}" to recycle bin?`)) return;
    try {
      await api(`/routes/${id}`, { method: "DELETE" });
      closeDetail(); closeModal();
      await refreshAll();
      toast("Route moved to recycle bin", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  // ── Cities ────────────────────────────────────────────────────────
  const CITY_COLS = [
    { key: "name", label: "City", get: c => c.name },
    { key: "route", label: "Route", get: c => c.route_name || "Unassigned" },
    { key: "customers", label: "Customers", get: c => String(c.customer_count || 0) },
    { key: "_actions", label: "", filterable: false, sortable: false },
  ];

  function renderCitiesTable() {
    const el = document.getElementById("cities-table");
    if (!cities.length) {
      el.innerHTML = '<div class="empty-state"><p>No cities yet.</p></div>';
      return;
    }
    const rows = TableUtils.apply(cities, "cities", CITY_COLS);
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("cities", CITY_COLS)}<tbody>
      ${rows.map(c => `<tr class="clickable" onclick="App.openCityDetail(${c.id})">
        <td><strong>${esc(c.name)}</strong></td>
        <td>${c.route_name ? `<span class="badge badge-green">${esc(c.route_name)}</span>` : '<span class="badge badge-amber">Unassigned</span>'}</td>
        <td>${c.customer_count || 0}</td>
        <td onclick="event.stopPropagation()">${canWrite("setup") ? `<div class="actions">
          <button type="button" class="btn btn-ghost btn-sm" onclick="event.stopPropagation();App.openCityModal(${c.id})">Edit</button>
          <button type="button" class="btn btn-danger btn-sm" onclick="event.stopPropagation();App.deleteCity(${c.id})">Delete</button>
        </div>` : ""}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  async function openCityDetail(id) {
    const c = await api(`/cities/${id}`);
    detailMode = "city"; detailId = id;
    openDetail("City Details", `
      <div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("City", c.name)}
        ${reviewRow("Route", c.route_name || "Unassigned")}
        ${reviewRow("Customers", c.customer_count)}
        ${reviewRow("Created", fmtDate(c.created_at))}
      </div>
      <div class="detail-section">
        <h4>Customers in this city (${c.customers.length})</h4>
        ${c.customers.length ? `<table class="data"><thead><tr><th>Business</th><th>Phone</th></tr></thead><tbody>
          ${c.customers.map(cu => `<tr class="clickable" onclick="App.closeDetail();App.openCustomerDetail(${cu.id})"><td>${esc(cu.business_name)}</td><td>${esc(cu.phone)}</td></tr>`).join("")}
        </tbody></table>` : '<p style="color:var(--muted);font-size:14px;">No customers in this city.</p>'}
      </div>`,
      `${canWrite("setup") ? `<button type="button" class="btn btn-danger btn-sm" onclick="App.deleteCity(${id})">Delete</button>
       <button type="button" class="btn btn-secondary" onclick="App.closeDetail();App.openCityModal(${id})">Edit</button>` : ""}
       <button type="button" class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "lg"
    );
  }

  function openCityModal(id) {
    const editing = id ? cities.find(c => c.id === id) : null;
    const routeOpts = routes.map(r => `<option value="${r.id}" ${editing?.route_id === r.id ? "selected" : ""}>${esc(r.name)}</option>`).join("");
    document.getElementById("modal-title").textContent = editing ? "Edit City" : "Add City";
    document.getElementById("modal-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">City Name *</label><input id="m-city-name" class="input" value="${esc(editing?.name || "")}" /></div>
        <div><label class="label">Route</label>
          <select id="m-city-route" class="input">
            <option value="" ${!editing?.route_id ? "selected" : ""}>— No route —</option>
            ${routeOpts}
          </select>
          <p style="margin:6px 0 0;font-size:12px;color:var(--muted);">Clear route to leave city unassigned.</p>
        </div>
      </div>`;
    document.getElementById("modal-footer").innerHTML = `
      <button type="button" class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button type="button" class="btn btn-primary" onclick="App.saveCity(${id || "null"})">${editing ? "Save" : "Create"}</button>`;
    document.getElementById("modal").classList.remove("hidden");
  }

  async function saveCity(id) {
    const name = document.getElementById("m-city-name").value.trim();
    const rawRoute = document.getElementById("m-city-route").value;
    const route_id = rawRoute ? parseInt(rawRoute, 10) : null;
    if (!name) return toast("City name required", "error");
    try {
      if (id) await api(`/cities/${id}`, { method: "PATCH", body: JSON.stringify({ name, route_id }) });
      else await api("/cities", { method: "POST", body: JSON.stringify({ name, route_id }) });
      closeModal(); closeDetail();
      await refreshAll();
      toast(id ? "City updated" : "City created", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  async function deleteCity(id) {
    const city = cities.find(c => c.id === id);
    const label = city?.name || `#${id}`;
    if (!confirm(`Move city "${label}" to recycle bin?`)) return;
    try {
      await api(`/cities/${id}`, { method: "DELETE" });
      closeDetail(); closeModal();
      await refreshAll();
      toast("City moved to recycle bin", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  // ── Customers ─────────────────────────────────────────────────────
  const CUSTOMER_COLS = [
    { key: "business", label: "Business", get: c => `${c.business_name} ${c.person_name || ""}` },
    { key: "phone", label: "Phone", get: c => c.phone },
    { key: "alias", label: "Alias", get: c => c.alias || "" },
    { key: "city", label: "City / Route", get: c => `${c.city_name || ""} ${c.route_name || ""}` },
    { key: "credit", label: "Credit", get: c => c.credit_limit ? String(c.credit_limit) : "" },
    { key: "_actions", label: "", filterable: false, sortable: false },
  ];

  function renderCustomersTable() {
    const el = document.getElementById("customers-table");
    if (!customers.length) {
      el.innerHTML = '<div class="empty-state"><p>No customers yet.</p><button class="btn btn-primary btn-lg" style="margin-top:16px;" onclick="App.openCustomerWizard()">+ Create First Customer</button></div>';
      return;
    }
    const rows = TableUtils.apply(customers, "customers", CUSTOMER_COLS);
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("customers", CUSTOMER_COLS)}<tbody>
      ${rows.map(c => `<tr class="clickable" onclick="App.openCustomerDetail(${c.id})">
        <td><strong>${esc(c.business_name)}</strong>${c.person_name ? `<br><span style="font-size:12px;color:var(--muted);">${esc(c.person_name)}</span>` : ""}</td>
        <td>${esc(c.phone)}</td>
        <td>${c.alias ? esc(c.alias) : "—"}</td>
        <td>${esc(c.city_name || "—")}${c.route_name ? `<br><span style="font-size:12px;color:var(--muted);">${esc(c.route_name)}</span>` : ""}</td>
        <td>${c.credit_limit ? "₹" + esc(c.credit_limit) : "—"}${c.credit_override ? ' <span class="badge badge-amber">override</span>' : ""}</td>
        <td onclick="event.stopPropagation()"></td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  async function openCustomerDetail(id) {
    const c = await api(`/customers/${id}`);
    detailMode = "customer"; detailId = id;
    const body = `
      <div class="profile-hero" style="margin:-24px -24px 24px;border-radius:0;">
        <h2>${esc(c.business_name)}</h2>
        <p>${esc(c.person_name || "No contact person")}</p>
        <div class="profile-meta">
          <span class="badge badge-blue">${esc(c.phone)}</span>
          ${c.alias ? `<span class="badge badge-gray">${esc(c.alias)}</span>` : ""}
          ${c.city_name ? `<span class="badge badge-green">${esc(c.city_name)}</span>` : ""}
          ${c.route_name ? `<span class="badge badge-gray">${esc(c.route_name)}</span>` : ""}
        </div>
      </div>
      <div class="review-grid">
        ${reviewRow("Secondary Phone", c.secondary_phone)}
        ${reviewRow("GST Number", c.gst_number)}
        ${reviewRow("Address", c.address)}
        ${reviewRow("Credit Limit", c.credit_limit ? "₹" + c.credit_limit : null)}
        ${reviewRow("Credit Override", c.credit_override ? "Allowed" : "Not allowed")}
        ${reviewRow("Password", "Last 4 digits of phone")}
        ${reviewRow("Created", fmtDate(c.created_at))}
        ${reviewRow("Last Updated", fmtDate(c.updated_at))}
      </div>
      ${changeHistoryTable(c.change_history)}
      <div class="detail-section">
        <h4>Customer Ledger</h4>
        <p style="color:var(--muted);font-size:13px;margin:0 0 12px;">Orders and sales will appear here.</p>
        <div id="customer-ledger-wrap">Loading…</div>
      </div>`;
    openDetail("Customer Profile", body,
      `${canWrite("customers") ? `<button class="btn btn-danger btn-sm" onclick="App.deleteCustomer(${c.id})">Delete</button>
       <button class="btn btn-secondary btn-sm" onclick="App.openCustomerEdit(${c.id})">Edit</button>
       <button class="btn btn-secondary" onclick="App.sendCredentials(${c.id})">Send Credentials</button>
       <button class="btn btn-secondary btn-sm" onclick="App.createCustomerOrder(${c.id})">Create Order</button>` : ""}
       <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "md"
    );
    api(`/customers/${id}/ledger`, {}, 0).then(res => {
      const wrap = document.getElementById("customer-ledger-wrap");
      if (!wrap) return;
      wrap.innerHTML = entityLedgerTableHtml(res.items || [], "customer", { showWho: isAdmin() });
    }).catch(() => {
      const wrap = document.getElementById("customer-ledger-wrap");
      if (wrap) wrap.innerHTML = '<p style="color:var(--muted);font-size:13px;">Could not load ledger.</p>';
    });
  }

  function openCustomerLedgerEntry() {
    showView("orders");
    setOrdersType("customer");
  }

  function createCustomerOrder(customerId) {
    closeDetail();
    showView("orders");
    setOrdersType("customer");
    CustomerOrders.openOfflineWizard(customerId);
  }

  async function openCustomerEdit(id) {
    const c = await api(`/customers/${id}`);
    editingCustomerId = id;
    document.getElementById("edit-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Business Name *</label><input id="ed-business_name" class="input" value="${esc(c.business_name)}" /></div>
        <div><label class="label">Person Name</label><input id="ed-person_name" class="input" value="${esc(c.person_name || "")}" /></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Primary Phone *</label><input id="ed-phone" class="input" value="${esc(c.phone)}" /></div>
          <div><label class="label">Secondary Phone</label><input id="ed-secondary_phone" class="input" value="${esc(c.secondary_phone || "")}" /></div>
        </div>
        <div><label class="label">Alias</label><input id="ed-alias" class="input" value="${esc(c.alias || "")}" /></div>
        <div><label class="label">City</label>
          <select id="ed-city_id" class="input"><option value="">—</option>
            ${cities.map(ct => `<option value="${ct.id}" ${c.city_id == ct.id ? "selected" : ""}>${esc(ct.name)}</option>`).join("")}
          </select>
          <p style="margin:4px 0 0;font-size:12px;color:var(--muted);">Route auto-assigned from city</p>
        </div>
        <div><label class="label">GST Number</label><input id="ed-gst_number" class="input" value="${esc(c.gst_number || "")}" /></div>
        <div><label class="label">Address</label><textarea id="ed-address" class="input" rows="2">${esc(c.address || "")}</textarea></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Credit Limit (₹)</label><input id="ed-credit_limit" class="input" type="number" value="${esc(c.credit_limit || "")}" /></div>
          <div style="display:flex;align-items:end;"><label style="display:flex;align-items:center;gap:8px;font-size:14px;">
            <input type="checkbox" id="ed-credit_override" ${c.credit_override ? "checked" : ""} /> Allow credit override
          </label></div>
        </div>
      </div>`;
    document.getElementById("edit-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeEditModal()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="App.saveCustomer()">Save Changes</button>`;
    document.getElementById("edit-modal").classList.remove("hidden");
  }

  function closeEditModal() {
    document.getElementById("edit-modal").classList.add("hidden");
    editingCustomerId = null;
  }

  async function saveCustomer() {
    if (!editingCustomerId) return;
    try {
      await api(`/customers/${editingCustomerId}`, { method: "PATCH", body: JSON.stringify({
        business_name: document.getElementById("ed-business_name").value.trim(),
        person_name: document.getElementById("ed-person_name").value.trim() || null,
        phone: document.getElementById("ed-phone").value.trim(),
        secondary_phone: document.getElementById("ed-secondary_phone").value.trim() || null,
        alias: document.getElementById("ed-alias").value.trim() || null,
        city_id: document.getElementById("ed-city_id").value ? parseInt(document.getElementById("ed-city_id").value) : null,
        gst_number: document.getElementById("ed-gst_number").value.trim() || null,
        address: document.getElementById("ed-address").value.trim() || null,
        credit_limit: document.getElementById("ed-credit_limit").value ? parseFloat(document.getElementById("ed-credit_limit").value) : null,
        credit_override: document.getElementById("ed-credit_override").checked,
      })});
      const id = editingCustomerId;
      closeEditModal();
      invalidateCache("/customers");
      invalidateCache("/stats");
      await loadCustomers();
      toast("Customer updated", "success");
      openCustomerDetail(id);
    } catch (e) { toast(e.message, "error"); }
  }

  async function deleteCustomer(id) {
    if (!confirm("Move customer to recycle bin? They cannot login until restored.")) return;
    try {
      await api(`/customers/${id}`, { method: "DELETE" });
      closeDetail(); closeEditModal();
      invalidateCache();
      await refreshAll();
      toast("Customer moved to recycle bin", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  async function sendCredentials(id) {
    if (!confirm("Reset password to last 4 digits and send via WhatsApp?")) return;
    try {
      const r = await api(`/customers/${id}/reset-password`, { method: "POST" });
      toast(r.message, r.whatsapp_sent ? "success" : "error");
    } catch (e) { toast(e.message, "error"); }
  }

  // ── Recycle Bin ───────────────────────────────────────────────────
  async function loadRecycleBin() {
    recycleData = await api("/recycle-bin");
    const rs = TableUtils.state("recycle");
    rs.sort = "deleted";
    rs.dir = "desc";
    renderRecycleTabs();
    renderRecycleTable();
  }

  function setRecycleTab(tab) {
    recycleTab = tab;
    renderRecycleTabs();
    renderRecycleTable();
  }

  function renderRecycleTabs() {
    const tabs = [
      ["all", `All (${recycleData.total})`],
      ["routes", `Routes (${recycleData.routes.length})`],
      ["cities", `Cities (${recycleData.cities.length})`],
      ["customers", `Customers (${recycleData.customers.length})`],
      ["vendors", `Vendors (${recycleData.vendors?.length || 0})`],
      ["catalog", `Catalog (${recycleData.catalog_products?.length || 0})`],
      ["addons", `Add-ons (${recycleData.addons?.length || 0})`],
      ...(isAdmin() ? [["staff", `Staff (${recycleData.staff?.length || 0})`]] : []),
    ];
    document.getElementById("recycle-tabs").innerHTML = tabs.map(([k, label]) =>
      `<button class="tab-btn ${recycleTab === k ? "active" : ""}" onclick="App.setRecycleTab('${k}')">${label}</button>`
    ).join("");
  }

  const RECYCLE_COLS = [
    { key: "type", label: "Type", get: i => i.type },
    { key: "name", label: "Name", get: i => i.name },
    { key: "details", label: "Details", get: i => i.subtitle || "" },
    { key: "deleted", label: "Deleted", get: i => i.deleted_at || "" },
    { key: "_actions", label: "", filterable: false, sortable: false },
  ];

  function renderRecycleTable() {
    const el = document.getElementById("recycle-table");
    let items = [];
    if (recycleTab === "all" || recycleTab === "routes") items = items.concat(recycleData.routes.map(i => ({ ...i, type: "route" })));
    if (recycleTab === "all" || recycleTab === "cities") items = items.concat(recycleData.cities.map(i => ({ ...i, type: "city" })));
    if (recycleTab === "all" || recycleTab === "customers") items = items.concat(recycleData.customers.map(i => ({ ...i, type: "customer" })));
    if (recycleTab === "all" || recycleTab === "vendors") items = items.concat((recycleData.vendors || []).map(i => ({ ...i, type: "vendor" })));
    if (recycleTab === "all" || recycleTab === "catalog") items = items.concat((recycleData.catalog_products || []).map(i => ({ ...i, type: "catalog_product" })));
    if (recycleTab === "all" || recycleTab === "addons") items = items.concat((recycleData.addons || []).map(i => ({ ...i, type: "addon" })));
    if (isAdmin() && (recycleTab === "all" || recycleTab === "staff")) items = items.concat((recycleData.staff || []).map(i => ({ ...i, type: "staff" })));

    if (!items.length) {
      el.innerHTML = '<div class="empty-state"><p>Recycle bin is empty.</p></div>';
      return;
    }
    const rows = TableUtils.apply(items, "recycle", RECYCLE_COLS);
    const typeBadge = t => ({ route: "badge-blue", city: "badge-green", customer: "badge-gray", vendor: "badge-amber", catalog_product: "badge-blue", addon: "badge-gray", staff: "badge-blue" }[t] || "badge-gray");
    const canRecycleWrite = canWrite("recycle");
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("recycle", RECYCLE_COLS)}<tbody>
      ${rows.map(i => `<tr class="clickable" onclick="App.openRecycleDetail('${i.type}',${i.id})">
        <td><span class="badge ${typeBadge(i.type)}">${i.type}</span></td>
        <td><strong>${esc(i.name)}</strong></td>
        <td style="color:var(--muted);font-size:13px;">${esc(i.subtitle || "—")}</td>
        <td style="font-size:13px;">${fmtDate(i.deleted_at)}</td>
        <td onclick="event.stopPropagation()">
          ${canRecycleWrite ? `<button class="btn btn-primary btn-sm" onclick="App.restoreItem('${i.type}',${i.id})">Restore</button>
          <button class="btn btn-danger btn-sm" onclick="App.purgeItem('${i.type}',${i.id})">Delete Forever</button>` : "—"}
        </td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  async function openRecycleDetail(type, id) {
    detailMode = `recycle-${type}`; detailId = id;
    let body = "";

    if (type === "route") {
      const r = await api(`/recycle-bin/routes/${id}`);
      body = `<div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("Name", r.name)}${reviewRow("Notes", r.notes)}
        ${reviewRow("Cities", r.city_count)}${reviewRow("Customers", r.customer_count)}
        ${reviewRow("Deleted", fmtDate(r.deleted_at))}
      </div>
      <div class="detail-section"><h4>Cities (${r.cities.length})</h4>
        ${r.cities.length ? r.cities.map(c => `<div class="review-row"><span>${esc(c.name)}</span><span>${c.is_active ? "active" : "deleted"}</span></div>`).join("") : "<p style='color:var(--muted)'>None</p>"}
      </div>`;
    } else if (type === "city") {
      const c = await api(`/recycle-bin/cities/${id}`);
      body = `<div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("City", c.name)}${reviewRow("Route", c.route_name)}
        ${reviewRow("Customers", c.customer_count)}${reviewRow("Deleted", fmtDate(c.deleted_at))}
      </div>
      <div class="detail-section"><h4>Customers (${c.customers.length})</h4>
        ${c.customers.length ? c.customers.map(cu => `<div class="review-row"><span>${esc(cu.business_name)}</span><span>${esc(cu.phone)}</span></div>`).join("") : "<p style='color:var(--muted)'>None</p>"}
      </div>`;
    } else if (type === "customer") {
      const c = await api(`/recycle-bin/customers/${id}`);
      body = `<div class="profile-hero" style="margin:-24px -24px 24px;border-radius:0;">
        <h2>${esc(c.business_name)}</h2>
        <p>${esc(c.person_name || "No contact person")}</p>
        <div class="profile-meta"><span class="badge badge-blue">${esc(c.phone)}</span></div>
      </div>
      <div class="review-grid">
        ${reviewRow("Alias", c.alias)}${reviewRow("City", c.city_name)}
        ${reviewRow("Route", c.route_name)}${reviewRow("GST", c.gst_number)}
        ${reviewRow("Address", c.address)}${reviewRow("Deleted", fmtDate(c.deleted_at))}
      </div>`;
    } else if (type === "vendor") {
      const v = await api(`/recycle-bin/vendors/${id}`);
      body = `<div class="profile-hero" style="margin:-24px -24px 24px;border-radius:0;">
        <h2>${esc(v.business_name)}</h2>
        <p>${esc(v.person_name || "No contact")}</p>
        <div class="profile-meta"><span class="badge badge-blue">${esc(v.phone)}</span></div>
      </div>
      <div class="review-grid">
        ${reviewRow("City", v.city_name)}${reviewRow("GST", v.gst_number)}
        ${reviewRow("Address", v.address)}${reviewRow("Deleted", fmtDate(v.deleted_at))}
      </div>`;
    } else if (type === "catalog_product") {
      const p = await api(`/recycle-bin/catalog-products/${id}`);
      body = `<div class="review-grid">
        ${reviewRow("Product ID", p.our_product_id)}${reviewRow("Vendor", p.vendor_name)}
        ${reviewRow("Buy Price", "₹" + p.buying_price)}${reviewRow("Deleted", fmtDate(p.deleted_at))}
      </div>`;
    } else if (type === "addon") {
      const a = await api(`/recycle-bin/addons/${id}`);
      body = `<div class="review-grid">
        ${reviewRow("Add-on ID", a.our_product_id)}${reviewRow("Vendor", a.vendor_name)}
        ${reviewRow("Unit", a.unit)}${reviewRow("Buy Price", "₹" + a.buying_price)}
        ${reviewRow("Deleted", fmtDate(a.deleted_at))}
      </div>`;
    }

    openDetail(`Deleted ${type}`, body,
      `${canWrite("recycle") ? `<button class="btn btn-primary" style="flex:1;" onclick="App.restoreItem('${type}',${id})">Restore</button>
       <button class="btn btn-danger" onclick="App.purgeItem('${type}',${id})">Delete Forever</button>` : ""}
       <button class="btn btn-secondary" onclick="App.closeDetail()">Close</button>`,
      "md"
    );
  }

  const RESTORE_PATHS = { route: "routes", city: "cities", customer: "customers", vendor: "vendors", catalog_product: "catalog-products", addon: "addons", staff: "staff" };

  async function restoreItem(type, id) {
    if (!confirm(`Restore this ${type}?`)) return;
    const path = RESTORE_PATHS[type] || `${type}s`;
    try {
      await api(`/recycle-bin/${path}/${id}/restore`, { method: "POST" });
      closeDetail();
      invalidateCache();
      await refreshAll();
      if (peopleTab === "vendors") await Vendors.load();
      if (document.getElementById("view-people") && !document.getElementById("view-people").classList.contains("hidden") && peopleTab === "customers") {
        await loadCustomers();
      }
      if (document.getElementById("view-recycle") && !document.getElementById("view-recycle").classList.contains("hidden")) {
        await loadRecycleBin();
      }
      toast(`${type} restored`, "success");
    } catch (e) { toast(e.message, "error"); }
  }

  async function purgeItem(type, id) {
    if (!confirm("Permanently delete? This cannot be undone.")) return;
    const path = RESTORE_PATHS[type] || `${type}s`;
    try {
      await api(`/recycle-bin/${path}/${id}`, { method: "DELETE" });
      closeDetail();
      invalidateCache();
      await loadRecycleBin();
      await updateHubCounts();
      toast("Permanently deleted", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  function renderLookupSections() {
    const el = document.getElementById("lookup-sections");
    if (!el) return;
    const types = [
      ["category", "Categories", "category", "C", "e.g. Wedding, Birthday, Festival"],
      ["series", "Series", "series", "S", "e.g. Premium, Economy, Gold"],
      ["unit", "Units", "unit", "U", "e.g. pcs, pack, box"],
      ["year_group", "Year Groups", "year group", "Y", "e.g. 2025, 2026"],
    ];
    const canSetupWrite = canWrite("setup");
    el.innerHTML = types.map(([t, label, singular, letter, hint]) => {
      const items = lookups.filter(l => l.lookup_type === t);
      const chips = items.length
        ? items.map(i => `<span class="lookup-chip">
            <span class="lookup-chip-text">${esc(i.value)}</span>
            ${canSetupWrite ? `<button type="button" class="lookup-chip-x" title="Remove" onclick="App.deleteLookup(${i.id})">×</button>` : ""}
          </span>`).join("")
        : `<p class="lookup-empty">No ${label.toLowerCase()} yet. Add the first one below.</p>`;
      return `<section class="lookup-card">
        <div class="lookup-card-head">
          <span class="lookup-card-letter">${letter}</span>
          <div>
            <h3 class="lookup-card-title">${label}</h3>
            <p class="lookup-card-hint">${hint}</p>
          </div>
          <span class="lookup-card-count">${items.length}</span>
        </div>
        <div class="lookup-chip-list">${chips}</div>
        ${canSetupWrite ? `<form class="lookup-add-row" onsubmit="event.preventDefault();App.submitLookup('${t}');">
          <input id="lookup-input-${t}" class="input lookup-add-input" type="text" maxlength="80" placeholder="Type new ${singular}…" autocomplete="off" />
          <button type="submit" class="btn btn-primary">Add</button>
        </form>` : ""}
      </section>`;
    }).join("");
  }

  async function submitLookup(type) {
    const input = document.getElementById(`lookup-input-${type}`);
    const val = (input?.value || "").trim();
    if (!val) {
      toast("Enter a name first", "error");
      input?.focus();
      return;
    }
    try {
      await api("/lookups", { method: "POST", body: JSON.stringify({ lookup_type: type, value: val }) });
      invalidateCache("/lookups");
      lookups = await api("/lookups", {}, 0);
      renderLookupSections();
      updateSetupHubCounts();
      toast("Added", "success");
      const next = document.getElementById(`lookup-input-${type}`);
      next?.focus();
    } catch (e) { toast(e.message, "error"); }
  }

  async function addLookup(type) {
    return submitLookup(type);
  }

  async function deleteLookup(id) {
    const row = lookups.find(l => l.id === id);
    const label = row ? row.value : "this option";
    if (!confirm(`Remove “${label}”? Products already using it keep the old value.`)) return;
    try {
      await api(`/lookups/${id}`, { method: "DELETE" });
      invalidateCache("/lookups");
      lookups = await api("/lookups", {}, 0);
      renderLookupSections();
      updateSetupHubCounts();
      toast("Removed", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  function getVendors() { return vendors; }
  function getLookups() { return lookups; }

  function setVendors(list) { vendors = list || []; }

  const sharedCtx = () => ({
    api, toast, esc, fmtDate, reviewRow, changeHistoryTable, openDetail,
    closeDetail: () => closeDetail(), detailBack, detailFooterChild, ledgerDetailCard, bindLedgerRowClicks,
    entityLedgerTableHtml, activityTableHtml, loadActivity,
    getCities: () => cities,
    getVendors: () => vendors,
    setVendors,
    getLookups: () => lookups,
    refreshStats: refreshAll,
    invalidateCache,
    showLoading, hideLoading,
    uploadImage,
    apiBase: () => API,
    checkBackend,
    can, canWrite, canRead, isAdmin,
    showView,
  });

  function openCustomerWizard() { wizardStep = 1; wizardForm = {}; document.getElementById("wizard").classList.remove("hidden"); renderWizard(); }
  function closeWizard() { document.getElementById("wizard").classList.add("hidden"); }

  function renderWizard() {
    const steps = document.getElementById("wizard-steps");
    steps.innerHTML = ["Business Info", "Contact & Credit", "Review & Create"].map((label, i) => {
      const n = i + 1;
      const cls = n < wizardStep ? "done" : n === wizardStep ? "active" : "";
      return `<div class="step ${cls}"><div class="step-num">${n < wizardStep ? "✓" : n}</div>${label}</div>`;
    }).join("");
    const body = document.getElementById("wizard-body");
    const footer = document.getElementById("wizard-footer");

    if (wizardStep === 1) {
      body.innerHTML = `<div style="display:grid;gap:16px;">
        <div><label class="label">Business Name *</label><input id="wf-business_name" class="input" value="${esc(wizardForm.business_name)}" /></div>
        <div><label class="label">Person Name</label><input id="wf-person_name" class="input" value="${esc(wizardForm.person_name)}" /></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Primary Phone *</label><input id="wf-phone" class="input" type="tel" maxlength="10" value="${esc(wizardForm.phone)}" /></div>
          <div><label class="label">Secondary Phone</label><input id="wf-secondary_phone" class="input" type="tel" maxlength="10" value="${esc(wizardForm.secondary_phone)}" /></div>
        </div>
        <div><label class="label">Alias</label><input id="wf-alias" class="input" value="${esc(wizardForm.alias)}" /></div>
        <div><label class="label">City</label><select id="wf-city_id" class="input"><option value="">— Select —</option>
          ${cities.map(c => `<option value="${c.id}" ${wizardForm.city_id == c.id ? "selected" : ""}>${esc(c.name)} (${esc(c.route_name || "")})</option>`).join("")}
        </select></div>
        <div><label class="label">GST</label><input id="wf-gst_number" class="input" value="${esc(wizardForm.gst_number)}" /></div>
      </div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="App.closeWizard()">Cancel</button><button class="btn btn-primary" style="flex:1;" onclick="App.wizardNext()">Continue →</button>`;
    } else if (wizardStep === 2) {
      body.innerHTML = `<div style="display:grid;gap:16px;">
        <div><label class="label">Address</label><textarea id="wf-address" class="input" rows="2">${esc(wizardForm.address)}</textarea></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Credit Limit (₹)</label><input id="wf-credit_limit" class="input" type="number" value="${esc(wizardForm.credit_limit)}" /></div>
          <div style="display:flex;align-items:end;"><label style="display:flex;gap:8px;font-size:14px;"><input type="checkbox" id="wf-credit_override" ${wizardForm.credit_override ? "checked" : ""} /> Allow override</label></div>
        </div>
        <div class="card" style="padding:16px;background:#f8fafc;"><p style="margin:0;font-size:13px;color:var(--muted);">Password = last 4 digits of phone → WhatsApp</p></div>
      </div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="App.wizardBack()">← Back</button><button class="btn btn-primary" style="flex:1;" onclick="App.wizardNext()">Review →</button>`;
    } else if (wizardStep === 3) {
      const city = cities.find(c => c.id == wizardForm.city_id);
      body.innerHTML = `<div class="review-grid">
        ${reviewRow("Business", wizardForm.business_name)}${reviewRow("Person", wizardForm.person_name)}
        ${reviewRow("Phone", wizardForm.phone)}${reviewRow("Alias", wizardForm.alias)}
        ${reviewRow("City", city?.name)}${reviewRow("Route", city?.route_name)}
        ${reviewRow("GST", wizardForm.gst_number)}${reviewRow("Address", wizardForm.address)}
        ${reviewRow("Credit", wizardForm.credit_limit ? "₹"+wizardForm.credit_limit : null)}
        ${reviewRow("Password", "Last 4 digits → WhatsApp")}
      </div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="App.wizardBack()">← Back</button><button class="btn btn-primary" style="flex:1;" id="wizard-create-btn" onclick="App.createCustomer()">Create Customer</button>`;
    } else if (wizardStep === 4) {
      body.innerHTML = `<div style="text-align:center;padding:24px 0;">
        <div class="success-icon">✓</div><h3 style="margin:0 0 8px;">Customer Created!</h3>
        <p style="color:var(--muted);margin:0 0 24px;">${esc(wizardForm._result?.business_name)}</p>
        <div class="review-grid" style="text-align:left;">
          ${reviewRow("Phone", wizardForm._result?.phone)}${reviewRow("Password", wizardForm._result?.phone?.slice(-4))}
          ${reviewRow("WhatsApp", wizardForm._result?.whatsapp_sent ? "✅ Sent" : "❌ " + (wizardForm._result?.whatsapp_error || ""))}
        </div></div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="App.openCustomerWizard()">+ Another</button><button class="btn btn-primary" style="flex:1;" onclick="App.closeWizard();App.showPeopleTab('customers')">View Customers</button>`;
    }
  }

  function reviewRow(label, val, rawHtml = false) {
    const empty = val == null || val === "";
    if (empty && !rawHtml) {
      return `<div class="review-row"><span class="review-label">${label}</span><span class="review-value review-empty">—</span></div>`;
    }
    const content = rawHtml ? val : esc(String(val));
    return `<div class="review-row"><span class="review-label">${label}</span><span class="review-value">${content}</span></div>`;
  }

  function changeHistoryTable(history) {
    if (!history?.length) return "";
    const rows = [];
    history.forEach(h => {
      const summary = h.change_summary || "Updated";
      const parts = summary === "updated" ? ["Updated"] : summary.split("; ").map(p => p.trim()).filter(Boolean);
      parts.forEach((part, i) => {
        const m = part.match(/^([^:]+):\s*(.*?)\s*→\s*(.*)$/);
        rows.push({
          field: m ? m[1].trim().replace(/_/g, " ") : "—",
          from: m ? m[2].trim() : "—",
          to: m ? m[3].trim() : part,
          at: h.valid_from,
          showDate: i === 0,
        });
      });
    });
    return `<div class="detail-section"><h4>Change History</h4>
      <table class="data history-table"><thead><tr>
        <th>Field</th><th>Previous</th><th>New</th><th>Changed</th>
      </tr></thead><tbody>${rows.map(r => `<tr>
        <td><span class="history-field">${esc(r.field)}</span></td>
        <td class="history-old">${esc(r.from)}</td>
        <td class="history-new"><strong>${esc(r.to)}</strong></td>
        <td class="history-date">${r.showDate ? fmtDate(r.at) : ""}</td>
      </tr>`).join("")}</tbody></table></div>`;
  }

  async function uploadImage(vendorId, ourProductId, file, imageIndex = 1) {
    const fd = new FormData();
    fd.append("vendor_id", String(vendorId));
    fd.append("our_product_id", ourProductId);
    fd.append("image_index", String(imageIndex));
    fd.append("file", file);
    const h = {};
    if (authMode === "admin" && adminKey) h["X-Admin-Key"] = adminKey;
    else if (authMode === "staff" && staffToken) h["Authorization"] = `Bearer ${staffToken}`;
    let res;
    try {
      res = await fetch(`${API}/catalog/upload-image`, { method: "POST", headers: h, body: fd });
    } catch (e) {
      throw new Error("Network error uploading image — is the backend running?");
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const msg = typeof err.detail === "string" ? err.detail : `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return res.json();
  }

  function collectWizard() {
    ["business_name","person_name","phone","secondary_phone","alias","gst_number","address","credit_limit"].forEach(k => {
      const el = document.getElementById(`wf-${k}`); if (el) wizardForm[k] = el.value.trim();
    });
    const cityEl = document.getElementById("wf-city_id");
    if (cityEl) wizardForm.city_id = cityEl.value ? parseInt(cityEl.value) : null;
    const ov = document.getElementById("wf-credit_override");
    if (ov) wizardForm.credit_override = ov.checked;
  }

  function wizardBack() { collectWizard(); wizardStep = Math.max(1, wizardStep - 1); renderWizard(); }
  function wizardNext() {
    collectWizard();
    if (wizardStep === 1) {
      if (!wizardForm.business_name) return toast("Business name required", "error");
      const phone = (wizardForm.phone || "").replace(/\D/g, "");
      if (phone.length !== 10) return toast("Phone must be 10 digits", "error");
      wizardForm.phone = phone;
    }
    wizardStep++; renderWizard();
  }

  async function createCustomer() {
    collectWizard();
    const btn = document.getElementById("wizard-create-btn");
    if (btn) btn.disabled = true;
    try {
      const result = await api("/customers", { method: "POST", body: JSON.stringify({
        business_name: wizardForm.business_name, person_name: wizardForm.person_name || null,
        phone: wizardForm.phone, secondary_phone: wizardForm.secondary_phone || null,
        alias: wizardForm.alias || null, city_id: wizardForm.city_id,
        gst_number: wizardForm.gst_number || null, address: wizardForm.address || null,
        credit_limit: wizardForm.credit_limit ? parseFloat(wizardForm.credit_limit) : null,
        credit_override: wizardForm.credit_override,
      })});
      wizardForm._result = result; wizardStep = 4; renderWizard();
      invalidateCache("/customers");
      invalidateCache("/stats");
      await refreshAll();
      if (peopleTab === "customers") await loadCustomers();
      toast(result.whatsapp_sent ? "Created & WhatsApp sent!" : "Created (WA failed)", result.whatsapp_sent ? "success" : "error");
    } catch (e) { toast(e.message, "error"); if (btn) btn.disabled = false; }
  }

  function closeModal() { document.getElementById("modal").classList.add("hidden"); }

  async function init() {
    authMode = sessionStorage.getItem("jc_auth_mode") || "";
    adminKey = sessionStorage.getItem("jc_admin_key") || "";
    staffToken = sessionStorage.getItem("jc_staff_token") || "";
    try { staffUser = JSON.parse(sessionStorage.getItem("jc_staff_user") || "null"); } catch (_) { staffUser = null; }
    permissions = new Set((staffUser && staffUser.permissions) || []);
    setLoginTab("admin");
    TableUtils.register("routes", renderRoutesTable);
    TableUtils.register("cities", renderCitiesTable);
    TableUtils.register("customers", renderCustomersTable);
    TableUtils.register("recycle", renderRecycleTable);
    if ((authMode === "admin" && adminKey) || (authMode === "staff" && staffToken)) {
      try { await enterApp(); } catch (_) {}
    }
  }

  function setOrdersType(type) {
    ordersType = type === "customer" ? "customer" : "vendor";
    document.getElementById("orders-type-vendor")?.classList.toggle("btn-primary", ordersType === "vendor");
    document.getElementById("orders-type-vendor")?.classList.toggle("btn-secondary", ordersType !== "vendor");
    document.getElementById("orders-type-customer")?.classList.toggle("btn-primary", ordersType === "customer");
    document.getElementById("orders-type-customer")?.classList.toggle("btn-secondary", ordersType !== "customer");
    document.getElementById("orders-vendor-panel")?.classList.toggle("hidden", ordersType !== "vendor");
    document.getElementById("orders-customer-panel")?.classList.toggle("hidden", ordersType !== "customer");
    if (ordersType === "vendor") VendorOrders.showHub();
    else CustomerOrders.showHub();
  }

  return {
    login, staffLogin, setLoginTab, logout, toggleSidebar, showView, showPeopleHub, showPeopleTab, showSetupHub, showSetupTab,
    setOrdersType,
    refreshAll, loadCustomers, reloadCustomers, loadActivity, openActivityItem, detailBack,
    openRouteDetail, openRouteModal, saveRoute, deleteRoute,
    openCityDetail, openCityModal, saveCity, deleteCity,
    openCustomerWizard, closeWizard, wizardBack, wizardNext, createCustomer,
    openCustomerDetail, closeDetail, openCustomerEdit, closeEditModal, saveCustomer, deleteCustomer, sendCredentials,
    loadRecycleBin, setRecycleTab, openRecycleDetail, restoreItem, purgeItem,
    addLookup, submitLookup, deleteLookup, openCustomerLedgerEntry, createCustomerOrder,
    closeModal, init,
    debouncedLoadCustomers, debouncedVendorSearch, debouncedCatalogSearch, debouncedAddonSearch, debouncedStockSearch,
    setVendors,
  };
})();

App.init();
