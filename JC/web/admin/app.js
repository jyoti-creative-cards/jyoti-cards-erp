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
  let showInactiveCustomers = false; // toggle switch: expose inactive parties
  let customerStatusTab = "active";  // "active" | "inactive" — only relevant when showInactiveCustomers=true
  let customerMissingPhone = false;  // filter: only show placeholder-phone customers
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
  let customerLedger = [];
  let customerLedgerExpanded = null;
  let customerAr = null;
  let viewStack = [];
  let currentViewName = null;

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
    const showBuying = canRead("vendor_orders");
    const showSelling = canRead("customer_orders");
    const showReturns = canRead("returns");
    document.getElementById("nav-today")?.classList.toggle("hidden", false);
    document.getElementById("nav-people")?.classList.toggle("hidden", !showPeople);
    document.getElementById("nav-products")?.classList.toggle("hidden", !showProducts);
    document.getElementById("nav-money")?.classList.toggle("hidden", !(isAdmin() || can("finance.write") || canRead("ar") || canRead("ap")));
    document.getElementById("nav-more")?.classList.toggle("hidden", false);
    document.getElementById("more-tile-buying")?.classList.toggle("hidden", !showBuying);
    document.getElementById("more-tile-selling")?.classList.toggle("hidden", !showSelling);
    document.getElementById("more-tile-returns")?.classList.toggle("hidden", !showReturns);
    document.getElementById("more-tile-reports")?.classList.toggle("hidden", !isAdmin());
    document.getElementById("more-tile-setup")?.classList.toggle("hidden", !canRead("setup"));
    document.getElementById("more-tile-safety")?.classList.toggle("hidden", !(canRead("recycle") || isAdmin()));
    document.getElementById("more-safety-recycle")?.classList.toggle("hidden", !canRead("recycle"));
    document.getElementById("more-safety-backup")?.classList.toggle("hidden", !isAdmin());
    // Legacy hidden nav ids — keep in sync for any leftover callers
    document.getElementById("nav-buying")?.classList.add("hidden");
    document.getElementById("nav-selling")?.classList.add("hidden");
    document.getElementById("nav-returns")?.classList.add("hidden");
    document.getElementById("nav-finance")?.classList.add("hidden");
    document.getElementById("nav-reports")?.classList.add("hidden");
    document.getElementById("nav-setup")?.classList.add("hidden");
    document.getElementById("nav-recycle")?.classList.add("hidden");
    document.getElementById("nav-home")?.classList.add("hidden");
    document.getElementById("setup-tile-staff")?.classList.toggle("hidden", !isAdmin());
    document.getElementById("setup-tile-activity")?.classList.toggle("hidden", !isAdmin());
    document.getElementById("setup-tile-documents")?.classList.toggle("hidden", !isAdmin());
    document.getElementById("setup-tile-billseries")?.classList.toggle("hidden", !isAdmin());
    document.getElementById("staff-new-btn")?.classList.toggle("hidden", !isAdmin());
    document.querySelector(".big-tile-customers")?.classList.toggle("hidden", !canRead("customers"));
    document.querySelector(".big-tile-vendors")?.classList.toggle("hidden", !canRead("vendors"));
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

  let loadingCount = 0;

  function showLoading() {
    loadingCount += 1;
    document.getElementById("loading")?.classList.remove("hidden");
  }

  function hideLoading() {
    loadingCount = Math.max(0, loadingCount - 1);
    if (loadingCount === 0) {
      document.getElementById("loading")?.classList.add("hidden");
    }
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
  const debouncedCatalogSearch = debounce(() => Products?.refreshHub?.() || Catalog.load(), 350);
  const debouncedAddonSearch = debounce(() => Products?.refreshHub?.() || AddonProducts.load(), 350);
  const debouncedStockSearch = debounce(() => Products?.refreshHub?.() || Stock.load(), 350);

  async function api(path, opts = {}, cacheTtl = 0) {
    const isGet = !opts.method || opts.method === "GET";
    if (isGet && cacheTtl > 0) {
      const cached = Cache.get(path);
      if (cached !== null) return cached;
    }
    const timeoutMs = typeof opts.timeoutMs === "number" ? opts.timeoutMs : (isGet ? 45000 : 90000);
    const { timeoutMs: _tm, ...fetchOpts } = opts;
    const doFetch = async () => {
      const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
      const timer = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : null;
      try {
        const res = await fetch(`${API}${path}`, {
          ...fetchOpts,
          signal: ctrl?.signal,
          headers: { ...headers(), ...(fetchOpts.headers || {}) },
        });
        if (res.status === 401) {
          logout();
          throw new Error("Session expired — please sign in again");
        }
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          let msg = `HTTP ${res.status}`;
          if (typeof err.detail === "string") msg = err.detail;
          else if (Array.isArray(err.detail)) msg = err.detail.map(d => d.msg || d.message || JSON.stringify(d)).join(", ");
          else if (err.detail && typeof err.detail === "object") msg = err.detail.message || err.detail.error || JSON.stringify(err.detail);
          else if (typeof err.message === "string") msg = err.message;
          const e = new Error(msg);
          e.detail = err.detail;
          e.status = res.status;
          throw e;
        }
        if (res.status === 204) return null;
        return res.json();
      } catch (e) {
        if (e?.name === "AbortError") throw new Error(`Request timed out (${path})`);
        throw e;
      } finally {
        if (timer) clearTimeout(timer);
      }
    };
    const data = await doFetch();
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

  function peekCache(path) {
    return Cache.get(path);
  }

  async function updateHubCounts() {
    const apply = (s) => {
      const hubCust = document.getElementById("hub-customers-count");
      const hubVend = document.getElementById("hub-vendors-count");
      if (hubCust) hubCust.textContent = `${s.customers} active`;
      if (hubVend) hubVend.textContent = `${s.vendors} active`;
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
    const dt = d instanceof Date ? d : new Date(d);
    if (Number.isNaN(dt.getTime())) return "—";
    return dt.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" });
  }

  function timeAgo(d) {
    if (!d) return "";
    const dt = d instanceof Date ? d : new Date(d);
    if (Number.isNaN(dt.getTime())) return "";
    const secs = Math.floor((Date.now() - dt.getTime()) / 1000);
    if (secs < 60) return "just now";
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
    if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
    if (secs < 172800) return "yesterday";
    return fmtDay(dt);
  }

  function fmtDay(d) {
    if (!d) return "—";
    if (typeof d === "string" && /^\d{4}-\d{2}-\d{2}$/.test(d)) {
      const [y, m, day] = d.split("-").map(Number);
      return new Date(y, m - 1, day).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
    }
    const dt = d instanceof Date ? d : new Date(d);
    if (Number.isNaN(dt.getTime())) return "—";
    return dt.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" });
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
    updateGlobalBack();
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
    updateGlobalBack();
  }

  function closeDetail() {
    detailStack = [];
    document.getElementById("detail").classList.add("hidden");
    detailMode = null;
    detailId = null;
    updateDetailNav();
    updateGlobalBack();
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
  function showLoginShell(msg) {
    document.getElementById("app")?.classList.add("hidden");
    document.getElementById("login-screen")?.classList.remove("hidden");
    loadingCount = 0;
    document.getElementById("loading")?.classList.add("hidden");
    if (msg) {
      const el = document.getElementById("login-error");
      if (el) {
        el.textContent = msg;
        el.classList.remove("hidden");
      }
    }
  }

  async function enterApp() {
    document.getElementById("login-screen").classList.add("hidden");
    document.getElementById("app").classList.remove("hidden");
    try {
      Vendors.init(sharedCtx());
      Catalog.init(sharedCtx());
      AddonProducts.init(sharedCtx());
      Products.init(sharedCtx());
      StaffMgmt.init(sharedCtx());
      VendorOrders.init(sharedCtx());
      CustomerOrders.init(sharedCtx());
      try { Returns.init(sharedCtx()); } catch (e) { console.error("Returns init failed", e); }
      Stock.init(sharedCtx());
      try { DebitNotes.init(sharedCtx()); } catch (e) { console.error("DebitNotes init failed", e); }
      try { Finance.init(sharedCtx()); } catch (e) { console.error("Finance init failed", e); }
      try { Reports.init(sharedCtx()); } catch (e) { console.error("Reports init failed", e); }
      try { Dashboard.init(sharedCtx()); } catch (e) { console.error("Dashboard init failed", e); }
      try { Documents.init(sharedCtx()); } catch (e) { console.error("Documents init failed", e); }
      try { BillSeries.init(sharedCtx()); } catch (e) { console.error("BillSeries init failed", e); }
      try { PaymentModes.init(sharedCtx()); } catch (e) { console.error("PaymentModes init failed", e); }
      try { FreightAgentsSetup.init(sharedCtx()); } catch (e) { console.error("FreightAgentsSetup init failed", e); }
      try { DocShare.init(sharedCtx()); } catch (e) { console.error("DocShare init failed", e); }
      applyNavPermissions();
      showView("today");
      try {
        await refreshAll();
      } catch (e) {
        toast(e?.message || "Failed to load data — try hard refresh", "error");
      }
      if (isAdmin()) {
        try {
          const s = await api("/staff");
          const hubStaff = document.getElementById("hub-staff-count");
          if (hubStaff) hubStaff.textContent = `${s.length} staff`;
        } catch (e) {
          console.warn("staff count failed", e);
        }
      }
    } catch (e) {
      showLoginShell(e?.message || "Could not open app");
      throw e;
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
      showLoginShell(e.message);
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
      showLoginShell(e.message);
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

  function resolveViewName(name) {
    if (name === "home") return "today";
    if (name === "finance") return "money";
    if (name === "catalog" || name === "stock" || name === "addons") return "products";
    if (name === "orders") return ordersType === "customer" ? "selling" : "buying";
    return name;
  }

  function updateGlobalBack() {
    const bar = document.getElementById("global-back-bar");
    if (!bar) return;
    const detailOpen = !document.getElementById("detail")?.classList.contains("hidden");
    const sellingDetail = currentViewName === "selling" && document.getElementById("co-slide-panel")?.classList.contains("is-open");
    const buyingDetail = currentViewName === "buying" && !document.getElementById("orders-detail")?.classList.contains("hidden");
    const returnsDetail = currentViewName === "returns" && !document.getElementById("returns-detail")?.classList.contains("hidden");
    const reportsLedger = currentViewName === "reports" && !document.getElementById("reports-ledger-detail")?.classList.contains("hidden");
    const financeDetail = currentViewName === "money" && (
      !document.getElementById("finance-ap-detail")?.classList.contains("hidden")
      || !document.getElementById("finance-ar-detail")?.classList.contains("hidden")
      || !document.getElementById("finance-freight-detail")?.classList.contains("hidden")
      || !document.getElementById("finance-routes-detail")?.classList.contains("hidden")
    );
    const canBack = detailOpen || sellingDetail || buyingDetail || returnsDetail || reportsLedger || financeDetail
      || viewStack.length > 0
      || (currentViewName && currentViewName !== "today");
    bar.classList.toggle("hidden", !canBack);
  }

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
    document.getElementById("setup-products").classList.add("hidden");
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
    document.getElementById("setup-products").classList.toggle("hidden", tab !== "products");
    document.getElementById("setup-routes-cities").classList.toggle("hidden", tab !== "routes");
    document.getElementById("setup-staff").classList.toggle("hidden", tab !== "staff");
    document.getElementById("setup-activity")?.classList.toggle("hidden", tab !== "activity");
    document.getElementById("setup-documents")?.classList.toggle("hidden", tab !== "documents");
    document.getElementById("setup-billseries")?.classList.toggle("hidden", tab !== "billseries");
    document.getElementById("setup-paymodes")?.classList.toggle("hidden", tab !== "paymodes");
    document.getElementById("setup-freight")?.classList.toggle("hidden", tab !== "freight");
    document.getElementById("setup-export")?.classList.toggle("hidden", tab !== "export");
    if (tab === "products") renderLookupSections();
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
    const hubLookups = document.getElementById("hub-lookups-count");
    const hubRoutesCities = document.getElementById("hub-routes-cities-count");
    if (hubLookups) hubLookups.textContent = `${lookups.length} options`;
    if (hubRoutesCities) hubRoutesCities.textContent = `${routes.length} routes · ${cities.length} cities`;

    const slot = document.getElementById("setup-stats-slot");
    if (slot) {
      slot.innerHTML = `
        <div class="setup-stat"><span class="setup-stat-num">${routes.length}</span><span class="setup-stat-label">Routes</span></div>
        <div class="setup-stat"><span class="setup-stat-num">${cities.length}</span><span class="setup-stat-label">Cities</span></div>
        <div class="setup-stat"><span class="setup-stat-num">${lookups.length}</span><span class="setup-stat-label">Options</span></div>
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
  async function refreshAll() {
    showLoading();
    try {
      // Boot path: skip full /customers (1.4k rows / ~700KB) — load when People opens.
      ["/routes", "/cities", "/vendors", "/lookups", "/stats"].forEach(p => invalidateCache(p));
      const [r, c, vend, lu, stats] = await Promise.all([
        api("/routes", {}, 120000).catch(() => []),
        api("/cities", {}, 120000).catch(() => []),
        api("/vendors", {}, 120000).catch(() => []),
        api("/lookups", {}, 300000).catch(() => []),
        api("/stats", {}, 30000).catch(() => null),
      ]);
      routes = r; cities = c; vendors = vend; lookups = lu;
      if (typeof Catalog !== "undefined" && Catalog.setVendors) Catalog.setVendors(vend);
      // Keep any cached customers; otherwise prefetch in background after paint.
      const cachedCust = peekCache("/customers");
      if (Array.isArray(cachedCust) && cachedCust.length) {
        customers = cachedCust;
      } else {
        api("/customers", {}, 120000)
          .then((cust) => { customers = cust || []; })
          .catch(() => {});
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

  function renderPeopleCustomerSearch() {
    const slot = document.getElementById("people-customers-search-slot");
    if (!slot) return;
    // Only render once — re-rendering on every keystroke destroys the focused input
    if (document.getElementById("search-input")) return;
    slot.innerHTML = HubUI.searchBar({
      id: "search-input",
      value: "",
      placeholder: "Search name, phone, #number…",
      oninput: "App.debouncedLoadCustomers()",
    });
  }

  function renderPeopleVendorSearch() {
    const slot = document.getElementById("people-vendors-search-slot");
    if (!slot) return;
    if (document.getElementById("vendor-search-input")) return;
    slot.innerHTML = HubUI.searchBar({
      id: "vendor-search-input",
      value: "",
      placeholder: "Search name, phone, alias…",
      oninput: "App.debouncedVendorSearch()",
    });
  }

  function toggleInactiveCustomers() {
    showInactiveCustomers = !showInactiveCustomers;
    if (!showInactiveCustomers) customerStatusTab = "active"; // reset to active when hiding
    // Update toggle switch visuals
    document.getElementById("cst-inactive-track")?.classList.toggle("is-on", showInactiveCustomers);
    // Show/hide Active/Inactive tabs
    const tabsEl = document.getElementById("customer-status-tabs");
    if (tabsEl) tabsEl.style.display = showInactiveCustomers ? "" : "none";
    invalidateCache("/customers");
    loadCustomers();
  }

  function setCustomerStatusTab(tab) {
    customerStatusTab = tab;
    customerMissingPhone = false;
    document.getElementById("cst-tab-active")?.classList.toggle("active", tab === "active");
    document.getElementById("cst-tab-inactive")?.classList.toggle("active", tab === "inactive");
    document.getElementById("cst-tab-missing")?.classList.toggle("active", false);
    invalidateCache("/customers");
    loadCustomers();
  }

  function toggleMissingPhoneFilter() {
    customerMissingPhone = !customerMissingPhone;
    document.getElementById("cst-tab-missing")?.classList.toggle("active", customerMissingPhone);
    renderCustomersTable();
  }

  async function loadCustomers() {
    renderPeopleCustomerSearch(); // no-op if input already exists
    const q = document.getElementById("search-input")?.value.trim() || "";
    // When toggle is off: only active customers (search still works across active only)
    // When toggle is on: use the active/inactive tab selection
    let statusParam;
    if (!showInactiveCustomers) {
      statusParam = "status=active";
    } else {
      statusParam = `status=${customerStatusTab}`;
    }
    const searchParam = q ? `&search=${encodeURIComponent(q)}` : "";
    customers = await api(`/customers?${statusParam}${searchParam}`, {}, q ? 0 : 120000);
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
      el.innerHTML = HubUI.emptyState({
        title: "No routes yet",
        sub: "Add a delivery route, then link cities.",
        ctaHtml: canWrite("setup")
          ? `<button class="btn btn-primary" onclick="App.openRouteModal()">+ Add Route</button>`
          : "",
      });
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
      el.innerHTML = HubUI.emptyState({
        title: "No cities yet",
        sub: "Each city maps to one delivery route.",
        ctaHtml: canWrite("setup")
          ? `<button class="btn btn-primary" onclick="App.openCityModal()">+ Add City</button>`
          : "",
      });
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
    { key: "party_number", label: "#", get: c => c.party_number || 0 },
    { key: "business", label: "Business", get: c => `${c.business_name} ${c.person_name || ""}` },
    { key: "city", label: "City / Route", get: c => `${c.city_name || ""} ${c.route_name || ""}` },
    { key: "financials", label: "Financials", filterable: false, sortable: false },
    { key: "phone", label: "Phone", get: c => c.phone },
    { key: "alias", label: "Alias", get: c => c.alias || "" },
    { key: "_actions", label: "", filterable: false, sortable: false },
  ];

  function renderFinancialsCell(c) {
    const limit = c.credit_limit !== null && c.credit_limit !== undefined ? Number(c.credit_limit) : null;
    const outstanding = c.outstanding_balance !== null && c.outstanding_balance !== undefined ? Number(c.outstanding_balance) : null;
    const available = c.available_credit !== null && c.available_credit !== undefined ? Number(c.available_credit) : null;
    const trackOnly = limit !== null && limit === 0;
    const hasLimit = limit !== null && limit > 0;
    const fmt = n => "₹" + Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });

    if (outstanding === null && !hasLimit) return '<span style="color:var(--muted);">—</span>';

    if (trackOnly) {
      if (outstanding === null) return '<span style="color:var(--muted);">—</span>';
      const outColor = outstanding > 0 ? "var(--red,#dc2626)" : outstanding < 0 ? "var(--green,#16a34a)" : "var(--muted)";
      return `<span style="font-size:12px;color:var(--muted);">Due</span>
        <span style="font-weight:600;color:${outColor};margin-left:4px;">${fmt(outstanding)}</span>`;
    }

    const parts = [];
    if (hasLimit) {
      parts.push(`<span style="font-size:11px;color:var(--muted);">Limit</span> <span style="font-size:12px;">₹${limit.toLocaleString("en-IN", { maximumFractionDigits: 0 })}${c.credit_override ? ' <span class="badge badge-amber" style="font-size:10px;">OVR</span>' : ""}</span>`);
    }
    if (outstanding !== null) {
      const outColor = outstanding > 0 ? "var(--red,#dc2626)" : outstanding < 0 ? "var(--green,#16a34a)" : "var(--muted)";
      parts.push(`<span style="font-size:11px;color:var(--muted);">Due</span> <span style="font-size:12px;font-weight:600;color:${outColor};">${fmt(outstanding)}</span>`);
    }
    if (available !== null) {
      const avColor = available >= 0 ? "var(--green,#16a34a)" : "var(--red,#dc2626)";
      parts.push(`<span style="font-size:11px;color:var(--muted);">Avail</span> <span style="font-size:12px;color:${avColor};">${fmt(available)}</span>`);
    }
    return parts.join('<br>');
  }

  // Extract "other notes" from notes field — stored before " | Bills:" separator
  function getOtherNotes(c) {
    if (!c.notes) return "";
    const first = c.notes.split(" | ")[0] || "";
    return first.startsWith("Bills:") ? "" : first;
  }

  // Party badges: marker_1 + marker_2 + other_notes + payment_type(CASH only if not already in markers)
  function partyBadgesHtml(c, opts) {
    const parts = [];
    if (c.marker_1) {
      parts.push(`<span class="badge badge-blue" style="font-size:10px;padding:2px 5px;">${esc(c.marker_1)}</span>`);
    }
    if (c.marker_2) {
      parts.push(`<span class="badge badge-amber" style="font-size:10px;padding:2px 5px;">${esc(c.marker_2)}</span>`);
    }
    const otherNotes = getOtherNotes(c);
    if (otherNotes) {
      parts.push(`<span class="badge badge-green" style="font-size:10px;padding:2px 5px;">${esc(otherNotes)}</span>`);
    }
    const allMarkers = [(c.marker_1 || ""), (c.marker_2 || ""), otherNotes].join(" ").toUpperCase();
    if (c.payment_type === "CASH" && !allMarkers.includes("CASH")) {
      parts.push(`<span class="badge badge-amber" style="font-size:10px;padding:2px 5px;">CASH</span>`);
    }
    return parts.join(" ");
  }

  function renderCustomersTable() {
    const el = document.getElementById("customers-table");
    if (!customers.length) {
      el.innerHTML = (typeof HubUI !== "undefined" ? HubUI.emptyState : OrdersUI.emptyState)({
        title: "No customers yet",
        sub: "Add dealers you sell to.",
        ctaHtml: canWrite("customers")
          ? `<button class="btn btn-primary btn-lg" onclick="App.openCustomerWizard()">+ Create First Customer</button>`
          : "",
      });
      return;
    }
    const visibleCustomers = customerMissingPhone
      ? customers.filter(c => c.phone && c.phone.startsWith("000"))
      : customers;
    const rows = TableUtils.apply(visibleCustomers, "customers", CUSTOMER_COLS);
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("customers", CUSTOMER_COLS)}<tbody>
      ${rows.map(c => {
        const missingPh = c.phone && c.phone.startsWith("000");
        const badges = partyBadgesHtml(c);
        return `<tr class="clickable" onclick="App.openCustomerDetail(${c.id})">
        <td style="text-align:center;color:var(--muted);font-size:12px;font-weight:700;white-space:nowrap;padding-right:4px;">${c.party_number ? `#${c.party_number}` : "—"}</td>
        <td><div style="display:flex;align-items:baseline;gap:6px;flex-wrap:wrap;">
            <strong>${esc(c.business_name)}</strong>
            ${badges ? `<span style="display:inline-flex;gap:3px;align-items:center;flex-wrap:wrap;">${badges}</span>` : ""}
          </div>
          ${c.person_name ? `<span style="font-size:12px;color:var(--muted);">${esc(c.person_name)}</span>` : ""}
          ${!c.is_active && !c.deleted_at ? '<span class="badge badge-amber" style="margin-left:4px;">Inactive</span>' : ""}
          ${missingPh ? '<span class="badge badge-red" style="margin-left:4px;">No phone</span>' : ""}</td>
        <td>${esc(c.city_name || "—")}${c.route_name ? `<br><span style="font-size:12px;color:var(--muted);">${esc(c.route_name)}</span>` : ""}</td>
        <td style="white-space:nowrap;">${renderFinancialsCell(c)}</td>
        <td>${missingPh ? '<span style="color:var(--muted);font-style:italic;">—</span>' : esc(c.phone)}</td>
        <td>${c.alias ? esc(c.alias) : "—"}</td>
        <td onclick="event.stopPropagation()"></td>
      </tr>`}).join("")}
    </tbody></table>`;
  }

  function fmtPersonMoney(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return esc(String(val));
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });
  }

  async function openCustomerDetail(id, opts = {}) {
    const c = await api(`/customers/${id}`);
    detailMode = "customer"; detailId = id;
    customerLedgerExpanded = null;
    customerAr = null;
    customerLedger = [];
    let tab = opts.tab || "activity";
    if (tab === "orders" || tab === "money" || tab === "returns") tab = "activity";
    const body = `
      <div class="profile-hero" style="margin:-24px -24px 16px;border-radius:0;">
        <h2>${c.party_number ? `<span style="color:var(--muted);font-size:16px;font-weight:600;margin-right:6px;">#${c.party_number}</span>` : ""}${esc(c.business_name)}${!c.is_active && !c.deleted_at ? ' <span class="badge badge-amber" style="font-size:13px;vertical-align:middle;">Inactive</span>' : ""}${c.deleted_at ? ' <span class="badge badge-red" style="font-size:13px;vertical-align:middle;">Deleted</span>' : ""}</h2>
        <p>${esc(c.person_name || "No contact person")}</p>
        <div class="profile-meta">
          <span class="badge badge-blue">${esc(c.phone)}</span>
          ${c.alias ? `<span class="badge badge-gray">${esc(c.alias)}</span>` : ""}
          ${c.city_name ? `<span class="badge badge-green">${esc(c.city_name)}</span>` : ""}
          ${c.route_name ? `<span class="badge badge-gray">${esc(c.route_name)}</span>` : ""}
          ${c.marker_1 ? `<span class="badge badge-blue">${esc(c.marker_1)}</span>` : ""}
          ${c.marker_2 ? `<span class="badge badge-amber">${esc(c.marker_2)}</span>` : ""}
          ${getOtherNotes(c) ? `<span class="badge badge-green">${esc(getOtherNotes(c))}</span>` : ""}
          ${c.payment_type === "CASH" && ![(c.marker_1||""),(c.marker_2||""),getOtherNotes(c)].join(" ").toUpperCase().includes("CASH") ? `<span class="badge badge-amber">CASH</span>` : ""}
        </div>
        ${(c.outstanding_balance !== null && c.outstanding_balance !== undefined) ? `
        <div class="credit-summary" style="margin-top:12px;display:flex;gap:16px;flex-wrap:wrap;">
          <div class="credit-stat"><span class="credit-label">Outstanding</span><span class="credit-val ${Number(c.outstanding_balance)>0?'text-danger':Number(c.outstanding_balance)<0?'text-success':''}">${fmtPersonMoney(c.outstanding_balance)}</span></div>
          <div class="credit-stat"><span class="credit-label">Credit Limit</span><span class="credit-val">${c.credit_limit !== null && c.credit_limit !== undefined ? "₹" + Number(c.credit_limit).toLocaleString("en-IN") : "₹0"}</span></div>
          <div class="credit-stat"><span class="credit-label">Available</span><span class="credit-val ${Number(c.available_credit)<0?'text-danger':'text-success'}">${fmtPersonMoney(c.available_credit)}</span></div>
        </div>` : ""}
      </div>
      <div class="ord-mode-toggle" role="tablist" style="margin-bottom:16px;">
        <button type="button" class="ord-mode-btn ${tab === "activity" ? "active" : ""}" onclick="App.openCustomerDetail(${c.id},{tab:'activity'})">Activity</button>
        <button type="button" class="ord-mode-btn ${tab === "profile" ? "active" : ""}" onclick="App.openCustomerDetail(${c.id},{tab:'profile'})">Profile</button>
      </div>
      <div id="customer-workspace">
        ${tab === "activity" ? `
          <div id="customer-summary-wrap" class="person-summary"></div>
          <div id="customer-actions-wrap" class="person-actions"></div>
          <div id="customer-ledger-wrap"><p style="color:var(--muted);font-size:13px;">Loading activity…</p></div>
        ` : ""}
        ${tab === "profile" ? `
          <div class="review-grid">
            ${reviewRow("Secondary Phone", c.secondary_phone)}
            ${reviewRow("GST Number", c.gst_number)}
            ${reviewRow("Address", c.address)}
            ${reviewRow("Additional details", c.additional_details)}
            ${reviewRow("Credit Limit", c.credit_limit !== null && c.credit_limit !== undefined ? "₹" + Number(c.credit_limit).toLocaleString("en-IN") : "₹0")}
            ${reviewRow("Available Credit", c.available_credit !== null && c.available_credit !== undefined ? fmtPersonMoney(c.available_credit) : "—")}
            ${reviewRow("Outstanding (AR)", c.outstanding_balance !== null && c.outstanding_balance !== undefined ? fmtPersonMoney(c.outstanding_balance) : "—")}
            ${reviewRow("Credit Override", c.credit_override ? "Allowed" : "Not allowed")}
            ${reviewRow("Opening", c.opening_balance_due ? fmtPersonMoney(c.opening_balance_due) : "—")}
            ${reviewRow("Opening as on", c.opening_balance_as_on || "—")}
            ${reviewRow("Status", c.deleted_at ? "Deleted" : c.is_active ? "Active" : "Inactive")}
            ${reviewRow("Password", "Unique — sent on WhatsApp")}
            ${reviewRow("Created", fmtDate(c.created_at))}
            ${reviewRow("Last Updated", fmtDate(c.updated_at))}
          </div>
          ${changeHistoryTable(c.change_history)}
        ` : ""}
      </div>`;
    const footerBtns = [];
    if (canWrite("customers")) {
      if (c.deleted_at) {
        // In recycle bin → restore only
        footerBtns.push(`<button class="btn btn-primary btn-sm" onclick="App.restoreCustomer(${c.id})">Restore</button>`);
      } else if (!c.is_active) {
        // Inactive → edit + restore to active + delete
        footerBtns.push(`<button class="btn btn-secondary btn-sm" onclick="App.openCustomerEdit(${c.id})">Edit</button>`);
        footerBtns.push(`<button class="btn btn-primary btn-sm" onclick="App.toggleCustomerActive(${c.id}, true)">Make Active</button>`);
        footerBtns.push(`<button class="btn btn-danger btn-sm" onclick="App.deleteCustomer(${c.id})">Delete</button>`);
      } else {
        // Active → mark inactive + delete + edit
        footerBtns.push(`<button class="btn btn-secondary btn-sm" onclick="App.toggleCustomerActive(${c.id}, false)">Mark Inactive</button>`);
        footerBtns.push(`<button class="btn btn-danger btn-sm" onclick="App.deleteCustomer(${c.id})">Delete</button>`);
        footerBtns.push(`<button class="btn btn-secondary btn-sm" onclick="App.openCustomerEdit(${c.id})">Edit</button>`);
        footerBtns.push(`<button class="btn btn-secondary" onclick="App.sendCredentials(${c.id})">Send login</button>`);
      }
    }
    footerBtns.push(`<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`);
    openDetail(c.business_name, body, footerBtns.join(""), "lg");
    if (tab === "activity") await refreshCustomerLedger(id);
  }

  function renderCustomerActions(id, openingDue, openingAsOn) {
    const el = document.getElementById("customer-actions-wrap");
    if (!el) return;
    const canSell = canWrite("customer_orders");
    const canSeeAr = isAdmin() || can("ar.read");
    const canCollectAr = isAdmin() || can("ar.write");
    const due = canSeeAr && customerAr && Number(customerAr.outstanding) > 0;
    const bits = [];
    // Everyday jobs: phone/offline order + bill + their order list.
    if (canSell) {
      bits.push(`<button class="btn btn-primary btn-sm" onclick="App.createCustomerOrder(${id})">Order</button>`);
      bits.push(`<button class="btn btn-secondary btn-sm" onclick="App.billCustomer(${id})">Bill</button>`);
      bits.push(`<button class="btn btn-secondary btn-sm" onclick="App.openSelling(${id})">Orders</button>`);
    }
    if (due && canCollectAr) {
      bits.push(`<button class="btn btn-secondary btn-sm" onclick="App.collectCustomer(${id})">Collect</button>`);
    }
    const more = [];
    if (canSell) {
      more.push(`<button type="button" onclick="App.closeDetail();App.showView('returns');Returns.openCreate?.(${id})">Return</button>`);
    }
    if (canCollectAr && !due) more.push(`<button type="button" onclick="App.collectCustomer(${id})">Collect</button>`);
    if (canSeeAr) more.push(`<button type="button" onclick="App.openCustomerMoney(${id})">Money statement</button>`);
    if (isAdmin()) {
      more.push(`<button type="button" onclick="App.setCustomerOpeningBalance(${id}, '${esc(openingDue || "")}', '${esc(openingAsOn || "")}')">Opening</button>`);
    }
    if (more.length) {
      bits.push(`<details class="person-more"><summary>More</summary><div class="person-more-menu">${more.join("")}</div></details>`);
    }
    el.innerHTML = bits.join("") || "";
  }

  async function refreshCustomerLedger(id) {
    const wrap = document.getElementById("customer-ledger-wrap");
    const sumWrap = document.getElementById("customer-summary-wrap");
    try {
      const [ledgerRes, ar, cust] = await Promise.all([
        api(`/customers/${id}/ledger`, {}, 0),
        (isAdmin() || can("ar.read")) ? api(`/accounts-receivable/customer/${id}`, {}, 0).catch(() => null) : Promise.resolve(null),
        api(`/customers/${id}`, {}, 0).catch(() => null),
      ]);
      customerLedger = ledgerRes.items || [];
      customerAr = ar;
      if (sumWrap) {
        if (ar) {
          sumWrap.innerHTML = `<div class="person-summary-grid">
            <div><span class="person-summary-label">Due</span><strong>${fmtPersonMoney(ar.outstanding)}</strong></div>
            <div><span class="person-summary-label">Opening</span><strong>${fmtPersonMoney(ar.opening_total || "0")}</strong></div>
            <div><span class="person-summary-label">Bills</span><strong>${fmtPersonMoney(ar.bill_total)}</strong></div>
            <div><span class="person-summary-label">Collected</span><strong>${fmtPersonMoney(ar.payment_total)}</strong></div>
          </div>`;
        } else {
          sumWrap.innerHTML = "";
        }
      }
      renderCustomerActions(id, cust?.opening_balance_due, cust?.opening_balance_as_on);
      if (wrap) wrap.innerHTML = renderCustomerStatement(id);
    } catch (e) {
      if (wrap) wrap.innerHTML = `<p style="color:var(--danger);font-size:13px;">${esc(e.message)}</p>`;
    }
  }

  function renderCustomerStatement(customerId) {
    const orders = customerLedger.filter(e => e.event_type === "order_placed" || e.event_type === "order_cancelled");
    const bills = customerLedger.filter(e => e.event_type === "customer_bill");
    const payments = customerLedger.filter(e => e.event_type === "ar_payment");
    const returns = customerLedger.filter(e => e.event_type === "customer_return");
    const openings = customerLedger.filter(e => e.event_type === "ar_opening");
    const sections = [];

    const group = (title, items, rowFn) => {
      if (!items.length) return;
      sections.push(`<div class="vled-group"><div class="vled-group-title">${esc(title)}</div>${items.map(rowFn).join("")}</div>`);
    };

    group("Orders", orders, (e) => {
      const d = e.details || {};
      const open = customerLedgerExpanded === e.id;
      const lines = d.lines || [];
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="App.toggleCustomerLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">${e.event_type === "order_cancelled" ? "Cancelled" : "Placed"} · #${d.placement_id || "—"}</div>
            <div class="vled-meta">${fmtDate(e.occurred_at)} · ${lines.length} lines · ${esc(e.summary || "")}</div>
          </div>
          <span class="vled-chevron">${open ? "▾" : "▸"}</span>
        </button>
        ${open ? `<div class="vled-body">
          <table class="data fin-mini"><thead><tr><th>Product</th><th>Qty</th><th>Rate</th></tr></thead><tbody>
            ${lines.map(l => `<tr><td>${esc(l.our_product_id)}</td><td>${l.quantity ?? "—"}</td><td>${fmtPersonMoney(l.unit_price ?? l.selling_price ?? l.buying_price)}</td></tr>`).join("") || "<tr><td colspan=3>—</td></tr>"}
          </tbody></table>
          <div class="vled-actions">
            <button class="btn btn-secondary btn-sm" onclick="App.openSelling(${customerId})">Open orders</button>
          </div>
        </div>` : ""}
      </div>`;
    });

    group("Bills / sold", bills, (e) => {
      const d = e.details || {};
      const open = customerLedgerExpanded === e.id;
      const lines = d.lines || [];
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="App.toggleCustomerLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">Bill ${esc(d.bill_number || "")}</div>
            <div class="vled-meta">${fmtDate(e.occurred_at)} · ${fmtPersonMoney(d.grand_total)} · ${lines.length} lines</div>
          </div>
          <span class="vled-chevron">${open ? "▾" : "▸"}</span>
        </button>
        ${open ? `<div class="vled-body">
          <table class="data fin-mini"><thead><tr><th>Product</th><th>Qty</th><th>Amount</th></tr></thead><tbody>
            ${lines.map(l => `<tr><td>${esc(l.our_product_id)}</td><td>${l.quantity ?? "—"}</td><td>${fmtPersonMoney(l.billed_amount)}</td></tr>`).join("") || "<tr><td colspan=3>—</td></tr>"}
          </tbody></table>
          <div class="vled-actions">
            ${d.bill_id ? `<button class="btn btn-primary btn-sm" onclick="CustomerOrders.openBillDoc(${d.bill_id}, false)">Bill PDF</button>` : ""}
            <button class="btn btn-secondary btn-sm" onclick="App.openSelling(${customerId}, 'billed')">Open bills</button>
          </div>
        </div>` : ""}
      </div>`;
    });

    group("Payments", payments, (e) => {
      const d = e.details || {};
      const open = customerLedgerExpanded === e.id;
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="App.toggleCustomerLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">Collected ${esc(d.payment_ref || "")}</div>
            <div class="vled-meta">${fmtDate(e.occurred_at)} · ${fmtPersonMoney(d.amount)}${d.comment ? ` · ${esc(d.comment)}` : ""}</div>
          </div>
          <span class="vled-chevron">${open ? "▾" : "▸"}</span>
        </button>
        ${open ? `<div class="vled-body">
          <div class="vled-actions">
            ${isAdmin() && d.ledger_entry_id && !d.reversed ? `
              <button class="btn btn-secondary btn-sm" onclick="Finance.undoArPayment(${d.ledger_entry_id},'reverse',${customerId})">Reverse</button>
              <button class="btn btn-ghost btn-sm" onclick="Finance.undoArPayment(${d.ledger_entry_id},'void',${customerId})">Void</button>
            ` : ""}
            ${d.reversed ? `<span class="badge badge-amber">Reversed</span>` : ""}
            ${(isAdmin() || can("ar.write")) ? `<button class="btn btn-secondary btn-sm" onclick="App.collectCustomer(${customerId})">Collect again</button>` : ""}
            ${(isAdmin() || can("ar.read")) ? `<button class="btn btn-secondary btn-sm" onclick="Finance.showArFromCustomer(${customerId})">Open AR</button>` : ""}
          </div>
        </div>` : ""}
      </div>`;
    });

    group("Returns", returns, (e) => {
      const d = e.details || {};
      const open = customerLedgerExpanded === e.id;
      const lines = d.lines || [];
      return `<div class="vled-card ${open ? "is-open" : ""}">
        <button type="button" class="vled-head" onclick="App.toggleCustomerLedgerRow('${e.id}')">
          <div>
            <div class="vled-title">Return ${esc(d.return_number || "")}</div>
            <div class="vled-meta">${fmtDate(e.occurred_at)} · Credit ${fmtPersonMoney(d.credit_amount)}</div>
          </div>
          <span class="vled-chevron">${open ? "▾" : "▸"}</span>
        </button>
        ${open ? `<div class="vled-body">
          <table class="data fin-mini"><thead><tr><th>Product</th><th>Qty</th><th>Amount</th></tr></thead><tbody>
            ${lines.map(l => `<tr><td>${esc(l.our_product_id)}</td><td>${l.quantity ?? "—"}</td><td>${fmtPersonMoney(l.billed_amount)}</td></tr>`).join("") || "<tr><td colspan=3>—</td></tr>"}
          </tbody></table>
        </div>` : ""}
      </div>`;
    });

    group("Opening", openings, (e) => {
      const d = e.details || {};
      return `<div class="vled-card">
        <div class="vled-head" style="cursor:default;">
          <div>
            <div class="vled-title">Opening</div>
            <div class="vled-meta">${fmtDate(e.occurred_at)} · ${fmtPersonMoney(d.amount)}${d.as_on ? ` · as on ${esc(d.as_on)}` : ""}</div>
          </div>
        </div>
      </div>`;
    });

    if (!sections.length) {
      return `<div class="detail-section"><h4>Activity</h4><p style="color:var(--muted);font-size:13px;">Nothing yet. Place an order or bill this customer.</p></div>`;
    }
    return `<div class="detail-section"><h4>Activity</h4>${sections.join("")}</div>`;
  }

  function toggleCustomerLedgerRow(entryId) {
    customerLedgerExpanded = customerLedgerExpanded === entryId ? null : entryId;
    const wrap = document.getElementById("customer-ledger-wrap");
    if (wrap && detailId) wrap.innerHTML = renderCustomerStatement(detailId);
  }

  function openSelling(customerId, bucket = "open") {
    closeDetail();
    showView("selling");
    CustomerOrders.setHubMode?.("past");
    const p = CustomerOrders.openDetail?.(customerId, bucket || "open");
    if (p && typeof p.then === "function") p.then(() => updateGlobalBack());
    else updateGlobalBack();
  }

  async function billCustomer(customerId) {
    closeDetail();
    showView("selling");
    await CustomerOrders.openDetail?.(customerId, "open");
    CustomerOrders.processOrder?.();
  }

  function collectCustomer(customerId) {
    if (!isAdmin() && !can("ar.write")) return toast("Not permitted", "error");
    closeDetail();
    showView("money");
    Finance.openCustomerAr?.(customerId, { settle: true });
  }

  function openCustomerMoney(customerId) {
    if (!isAdmin() && !can("ar.read")) return toast("Not permitted", "error");
    closeDetail();
    showView("money");
    Finance.openCustomerAr?.(customerId);
  }

  async function setCustomerOpeningBalance(id, currentAmt, currentAsOn) {
    const today = new Date().toISOString().slice(0, 10);
    openDetail("Opening", `
      <p style="color:var(--muted);font-size:13px;margin:0 0 16px;">Tally start they owed. Use 0 to clear. Not Due (Due = opening + bills − collected).</p>
      <label class="label">Opening (₹)</label>
      <input type="number" step="0.01" min="0" class="input" id="ob-amt" value="${esc(currentAmt || "0")}" style="margin-bottom:12px;" />
      <label class="label">As on date</label>
      <input type="date" class="input" id="ob-as-on" value="${esc(currentAsOn || today)}" />
    `, `
      <button class="btn btn-secondary" onclick="App.closeDetail();App.openCustomerDetail(${id},{tab:'activity'})">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="App.saveCustomerOpeningBalance(${id})">Save</button>
    `, "sm");
  }

  async function saveCustomerOpeningBalance(id) {
    const amount = parseFloat(document.getElementById("ob-amt")?.value || "0");
    const asOn = (document.getElementById("ob-as-on")?.value || "").trim();
    if (!Number.isFinite(amount) || amount < 0) return toast("Enter a valid amount", "error");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(asOn)) return toast("Pick a valid date", "error");
    showLoading?.();
    try {
      await api(`/accounts-receivable/customer/${id}/opening-balance`, {
        method: "POST",
        body: JSON.stringify({ amount, as_on: asOn }),
      });
      invalidateCache("/customers");
      invalidateCache("/accounts-receivable");
      toast("Opening saved", "success");
      openCustomerDetail(id, { tab: "activity" });
    } catch (e) { toast(e.message, "error"); }
    finally { hideLoading?.(); }
  }

  function openCustomerLedgerEntry(customerId) {
    closeDetail();
    showView("selling");
    if (customerId) CustomerOrders.openCustomer?.(customerId, "open");
  }

  function createCustomerOrder(customerId) {
    closeDetail();
    showView("selling");
    CustomerOrders.openOfflineWizard(customerId);
  }

  function customerCityHint(cityId) {
    const city = cities.find(c => c.id == cityId);
    if (!city) return `<p class="people-field-hint">City sets delivery route. Required for route collection.</p>`;
    return `<p class="people-field-hint">Route: <strong>${esc(city.route_name || "Unassigned")}</strong> · from city <strong>${esc(city.name)}</strong></p>`;
  }

  function normalizePhoneDigits(raw) {
    return String(raw || "").replace(/\D/g, "");
  }

  function normalizeGstin(raw) {
    return String(raw || "").replace(/\s+/g, "").toUpperCase();
  }

  function validateGstin(raw) {
    const gst = normalizeGstin(raw);
    if (!gst) return { ok: true, value: null };
    const re = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
    if (!re.test(gst)) return { ok: false, value: gst };
    return { ok: true, value: gst };
  }

  function validateOptionalPhone(raw) {
    const p = normalizePhoneDigits(raw);
    if (!p) return { ok: true, value: null };
    if (p.length !== 10) return { ok: false, value: p };
    return { ok: true, value: p };
  }

  async function openCustomerEdit(id) {
    const c = await api(`/customers/${id}`);
    editingCustomerId = id;
    document.getElementById("edit-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Business Name *</label><input id="ed-business_name" class="input" value="${esc(c.business_name)}" /></div>
        <div><label class="label">Person Name</label><input id="ed-person_name" class="input" value="${esc(c.person_name || "")}" /></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><label class="label">Primary Phone *</label><input id="ed-phone" class="input" type="tel" maxlength="10" value="${esc(c.phone)}" /></div>
          <div><label class="label">Secondary Phone</label><input id="ed-secondary_phone" class="input" type="tel" maxlength="10" value="${esc(c.secondary_phone || "")}" placeholder="10 digits or blank" /></div>
        </div>
        <div><label class="label">Alias</label><input id="ed-alias" class="input" value="${esc(c.alias || "")}" /></div>
        <div><label class="label">City *</label>
          <select id="ed-city_id" class="input" onchange="App.onCustomerEditCityChange(this.value)">
            <option value="">— Select city —</option>
            ${cities.map(ct => `<option value="${ct.id}" ${c.city_id == ct.id ? "selected" : ""}>${esc(ct.name)} (${esc(ct.route_name || "No route")})</option>`).join("")}
          </select>
          <div id="ed-city-hint">${customerCityHint(c.city_id)}</div>
        </div>
        <div><label class="label">GST Number</label><input id="ed-gst_number" class="input" value="${esc(c.gst_number || "")}" placeholder="22AAAAA0000A1Z5" maxlength="15" style="text-transform:uppercase;" /></div>
        <div><label class="label">Address</label><textarea id="ed-address" class="input" rows="2">${esc(c.address || "")}</textarea></div>
        <div><label class="label">Additional details</label><textarea id="ed-additional_details" class="input" rows="2">${esc(c.additional_details || "")}</textarea></div>
        <div>
          <label class="label">Payment type *</label>
          <div style="display:flex;gap:8px;margin-top:4px;">
            <label id="ed-label-cash" style="display:flex;align-items:center;gap:6px;font-size:14px;cursor:pointer;padding:8px 14px;border:1px solid var(--border);border-radius:8px;flex:1;justify-content:center;${(c.payment_type||'CREDIT')==='CASH'?'background:#fef3c7;border-color:#f59e0b;font-weight:600;':''}">
              <input type="radio" name="ed-payment_type" value="CASH" ${(c.payment_type||'CREDIT')==='CASH'?'checked':''} onchange="App.onEditPaymentTypeChange('CASH')" /> CASH
            </label>
            <label id="ed-label-credit" style="display:flex;align-items:center;gap:6px;font-size:14px;cursor:pointer;padding:8px 14px;border:1px solid var(--border);border-radius:8px;flex:1;justify-content:center;${(c.payment_type||'CREDIT')==='CREDIT'?'background:#eff6ff;border-color:#3b82f6;font-weight:600;':''}">
              <input type="radio" name="ed-payment_type" value="CREDIT" ${(c.payment_type||'CREDIT')==='CREDIT'?'checked':''} onchange="App.onEditPaymentTypeChange('CREDIT')" /> CREDIT
            </label>
          </div>
        </div>
        <div id="ed-credit-limit-wrap" style="grid-template-columns:1fr 1fr;gap:12px;display:${(c.payment_type||'CREDIT')==='CASH'?'none':'grid'};">
          <div><label class="label">Credit Limit (₹)</label><input id="ed-credit_limit" class="input" type="number" value="${esc(c.credit_limit || "")}" /></div>
          <div style="display:flex;align-items:end;"><label style="display:flex;align-items:center;gap:8px;font-size:14px;">
            <input type="checkbox" id="ed-credit_override" ${c.credit_override ? "checked" : ""} /> Allow credit override
          </label></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px;border:1px dashed var(--border);border-radius:10px;background:#fffbeb;">
          <div><label class="label">Opening (₹)</label><input id="ed-opening_due" class="input" type="number" min="0" step="0.01" value="${esc(c.opening_balance_due || "0")}" /></div>
          <div><label class="label">As on</label><input id="ed-opening_as_on" class="input" type="date" value="${esc(c.opening_balance_as_on || new Date().toISOString().slice(0, 10))}" /></div>
          <p style="grid-column:1/-1;margin:0;font-size:12px;color:var(--muted);">Tally start they owed. Not Due (Due = opening + bills − collected).</p>
        </div>
      </div>`;
    document.getElementById("edit-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeEditModal()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="App.saveCustomer()">Save Changes</button>`;
    document.getElementById("edit-modal").classList.remove("hidden");
  }

  function onCustomerEditCityChange(val) {
    const hint = document.getElementById("ed-city-hint");
    if (hint) hint.innerHTML = customerCityHint(val ? parseInt(val, 10) : null);
  }

  function onEditPaymentTypeChange(val) {
    const wrap = document.getElementById("ed-credit-limit-wrap");
    if (wrap) wrap.style.display = val === "CASH" ? "none" : "grid";
    if (val === "CASH") {
      const el = document.getElementById("ed-credit_limit");
      if (el) el.value = "";
    }
    const cashLabel = document.getElementById("ed-label-cash");
    const creditLabel = document.getElementById("ed-label-credit");
    if (cashLabel) {
      cashLabel.style.background = val === "CASH" ? "#fef3c7" : "";
      cashLabel.style.borderColor = val === "CASH" ? "#f59e0b" : "";
      cashLabel.style.fontWeight = val === "CASH" ? "600" : "";
    }
    if (creditLabel) {
      creditLabel.style.background = val === "CREDIT" ? "#eff6ff" : "";
      creditLabel.style.borderColor = val === "CREDIT" ? "#3b82f6" : "";
      creditLabel.style.fontWeight = val === "CREDIT" ? "600" : "";
    }
  }

  function closeEditModal() {
    document.getElementById("edit-modal").classList.add("hidden");
    editingCustomerId = null;
  }

  async function saveCustomer() {
    if (!editingCustomerId) return;
    const business = document.getElementById("ed-business_name").value.trim();
    const phone = normalizePhoneDigits(document.getElementById("ed-phone").value);
    const cityVal = document.getElementById("ed-city_id").value;
    const cityId = cityVal ? parseInt(cityVal, 10) : null;
    if (!business) return toast("Business name required", "error");
    if (phone.length !== 10) return toast("Phone must be 10 digits", "error");
    if (!cityId) return toast("Please select a city", "error");
    const sec = validateOptionalPhone(document.getElementById("ed-secondary_phone").value);
    if (!sec.ok) return toast("Secondary phone must be 10 digits or blank", "error");
    const gst = validateGstin(document.getElementById("ed-gst_number").value);
    if (!gst.ok) return toast("GST looks invalid — use 15-char GSTIN or leave blank", "error");
    try {
      await api(`/customers/${editingCustomerId}`, { method: "PATCH", body: JSON.stringify({
        business_name: business,
        person_name: document.getElementById("ed-person_name").value.trim() || null,
        phone,
        secondary_phone: sec.value,
        alias: document.getElementById("ed-alias").value.trim() || null,
        city_id: cityId,
        gst_number: gst.value,
        address: document.getElementById("ed-address").value.trim() || null,
        additional_details: document.getElementById("ed-additional_details")?.value.trim() || null,
        payment_type: (document.querySelector('input[name="ed-payment_type"]:checked')?.value) || "CREDIT",
        credit_limit: (() => {
          const pt = document.querySelector('input[name="ed-payment_type"]:checked')?.value;
          if (pt === "CASH") return 0;
          const v = document.getElementById("ed-credit_limit")?.value;
          return v ? parseFloat(v) : null;
        })(),
        credit_override: document.getElementById("ed-credit_override")?.checked || false,
        opening_balance_due: parseFloat(document.getElementById("ed-opening_due")?.value || "0") || 0,
        opening_balance_as_on: document.getElementById("ed-opening_as_on")?.value || null,
      })});
      const id = editingCustomerId;
      closeEditModal();
      invalidateCache("/customers");
      invalidateCache("/accounts-receivable");
      invalidateCache("/stats");
      await loadCustomers();
      toast("Customer updated", "success");
      openCustomerDetail(id);
    } catch (e) { toast(e.message, "error"); }
  }

  async function toggleCustomerActive(id, makeActive) {
    const label = makeActive ? "restore to active" : "mark as inactive";
    if (!confirm(`${makeActive ? "Restore" : "Mark inactive"} this customer?`)) return;
    try {
      await api(`/customers/${id}`, { method: "PATCH", body: JSON.stringify({ is_active: makeActive }) });
      closeDetail();
      invalidateCache("/customers");
      invalidateCache("/stats");
      await loadCustomers();
      toast(`Customer ${makeActive ? "restored to active" : "marked inactive"}`, "success");
    } catch (e) { toast(e.message, "error"); }
  }

  async function restoreCustomer(id) {
    if (!confirm("Restore customer from recycle bin?")) return;
    try {
      await api(`/customers/${id}/restore`, { method: "POST" });
      closeDetail();
      invalidateCache("/customers");
      invalidateCache("/stats");
      await loadCustomers();
      toast("Customer restored", "success");
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
    if (!confirm("Generate a new unique password and send via WhatsApp?")) return;
    try {
      const r = await api(`/customers/${id}/reset-password`, { method: "POST" });
      const msg = r.whatsapp_sent
        ? `New password sent${r.portal_password ? `: ${r.portal_password}` : ""}`
        : (r.message || "Password reset — WhatsApp failed");
      toast(msg, r.whatsapp_sent ? "success" : "error");
    } catch (e) { toast(e.message, "error"); }
  }

  async function resendWhatsApp(id) {
    try {
      const r = await api(`/customers/${id}/resend-whatsapp`, { method: "POST" });
      if (wizardForm?._result?.id === id) {
        wizardForm._result.whatsapp_sent = !!r.whatsapp_sent;
        wizardForm._result.whatsapp_error = r.whatsapp_error || null;
        if (r.portal_password) wizardForm._result.portal_password = r.portal_password;
        if (wizardStep === 4) renderWizard();
      }
      toast(r.whatsapp_sent ? "WhatsApp sent (new password)" : (r.whatsapp_error || "WhatsApp failed"), r.whatsapp_sent ? "success" : "error");
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
    const items = [
      { id: "all", label: "All", count: recycleData.total },
      { id: "routes", label: "Routes", count: recycleData.routes.length },
      { id: "cities", label: "Cities", count: recycleData.cities.length },
      { id: "customers", label: "Customers", count: recycleData.customers.length },
      { id: "vendors", label: "Vendors", count: recycleData.vendors?.length || 0 },
      { id: "catalog", label: "Catalog", count: recycleData.catalog_products?.length || 0 },
      { id: "addons", label: "Add-ons", count: recycleData.addons?.length || 0 },
      { id: "receipts", label: "Receipts/Bills", count: recycleData.receipts?.length || 0 },
      { id: "debit_notes", label: "Debit Notes", count: recycleData.debit_notes?.length || 0 },
      { id: "customer_bills", label: "Customer Bills", count: recycleData.customer_bills?.length || 0 },
      { id: "customer_placements", label: "Customer Orders", count: recycleData.customer_placements?.length || 0 },
      { id: "customer_returns", label: "Customer Returns", count: recycleData.customer_returns?.length || 0 },
      ...(isAdmin() ? [{ id: "staff", label: "Staff", count: recycleData.staff?.length || 0 }] : []),
    ];
    if (typeof OrdersUI !== "undefined") {
      OrdersUI.actionChips({
        hostId: "recycle-tabs",
        items,
        active: recycleTab,
        onclickFn: "App.setRecycleTab",
      });
    } else {
      document.getElementById("recycle-tabs").innerHTML = items.map(it =>
        `<button class="ord-action-chip${recycleTab === it.id ? " active" : ""}" onclick="App.setRecycleTab('${it.id}')">${esc(it.label)} <span class="ord-action-count">${it.count}</span></button>`
      ).join("");
    }
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
    if (recycleTab === "all" || recycleTab === "receipts") items = items.concat((recycleData.receipts || []).map(i => ({ ...i, type: "receipt" })));
    if (recycleTab === "all" || recycleTab === "debit_notes") items = items.concat((recycleData.debit_notes || []).map(i => ({ ...i, type: "debit_note" })));
    if (recycleTab === "all" || recycleTab === "customer_bills") items = items.concat((recycleData.customer_bills || []).map(i => ({ ...i, type: "customer_bill" })));
    if (recycleTab === "all" || recycleTab === "customer_placements") items = items.concat((recycleData.customer_placements || []).map(i => ({ ...i, type: "customer_placement" })));
    if (recycleTab === "all" || recycleTab === "customer_returns") items = items.concat((recycleData.customer_returns || []).map(i => ({ ...i, type: "customer_return" })));
    if (isAdmin() && (recycleTab === "all" || recycleTab === "staff")) items = items.concat((recycleData.staff || []).map(i => ({ ...i, type: "staff" })));

    if (!items.length) {
      el.innerHTML = (typeof HubUI !== "undefined" ? HubUI.emptyState : OrdersUI.emptyState)({
        title: "Recycle bin is empty",
        sub: "Deleted routes, cities, people, and products show up here.",
      });
      return;
    }
    const rows = TableUtils.apply(items, "recycle", RECYCLE_COLS);
    const typeBadge = t => ({ route: "badge-blue", city: "badge-green", customer: "badge-gray", vendor: "badge-amber", catalog_product: "badge-blue", addon: "badge-gray", staff: "badge-blue", receipt: "badge-amber", debit_note: "badge-red", customer_bill: "badge-amber", customer_placement: "badge-blue", customer_return: "badge-red" }[t] || "badge-gray");
    const canRecycleWrite = canWrite("recycle");
    const ADMIN_ONLY_TYPES = ["receipt", "debit_note", "customer_bill", "customer_placement", "customer_return"];
    const canAct = i => ADMIN_ONLY_TYPES.includes(i.type) ? isAdmin() : canRecycleWrite;
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("recycle", RECYCLE_COLS)}<tbody>
      ${rows.map(i => `<tr class="clickable" onclick="App.openRecycleDetail('${i.type}',${i.id})">
        <td><span class="badge ${typeBadge(i.type)}">${i.type}</span></td>
        <td><strong>${esc(i.name)}</strong></td>
        <td style="color:var(--muted);font-size:13px;">${esc(i.subtitle || "—")}</td>
        <td style="font-size:13px;">${fmtDate(i.deleted_at)}</td>
        <td onclick="event.stopPropagation()">
          ${canAct(i) ? `<button class="btn btn-primary btn-sm" onclick="App.restoreItem('${i.type}',${i.id})">Restore</button>
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
    } else if (type === "receipt") {
      const r = await api(`/stock/receipts/${id}`);
      body = `<div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("Type", r.bill_status === "billed" ? "Bill" : "Receipt")}
        ${reviewRow("Order receipt #", r.order_receipt_number)}${reviewRow("Bill number", r.bill_number)}
        ${reviewRow("Bill amount", r.bill_amount != null ? "₹" + r.bill_amount : "—")}
        ${reviewRow("Net payable", r.net_payable != null ? "₹" + r.net_payable : "—")}
        ${reviewRow("Deleted", fmtDate(r.deleted_at))}${reviewRow("Reason", r.deleted_reason || "—")}
      </div>
      <div class="detail-section"><h4>Lines (${(r.lines || []).length})</h4>
        ${(r.lines || []).length ? r.lines.map(l => `<div class="review-row"><span>${esc(l.our_product_id)}</span><span>recv ${l.quantity_received} / bill ${l.quantity_billed || 0}</span></div>`).join("") : "<p style='color:var(--muted)'>None</p>"}
      </div>`;
    } else if (type === "debit_note") {
      const d = await api(`/debit-notes/${id}`);
      body = `<div class="review-grid">
        ${reviewRow("Vendor", d.vendor_label)}${reviewRow("Bill number", d.bill_number)}
        ${reviewRow("Type", d.note_type)}${reviewRow("Direction", d.direction)}
        ${reviewRow("Amount", "₹" + d.amount)}${reviewRow("Note", d.notes || "—")}
        ${reviewRow("Deleted", fmtDate(d.deleted_at))}${reviewRow("Reason", d.deleted_reason || "—")}
      </div>`;
    } else if (type === "customer_bill") {
      const b = await api(`/customer-orders/bills/${id}`);
      body = `<div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("Bill number", b.bill_number)}${reviewRow("Grand total", "₹" + b.grand_total)}
        ${reviewRow("Cancelled", b.cancelled_at ? fmtDate(b.cancelled_at) : "—")}${reviewRow("Cancel reason", b.cancel_reason || "—")}
        ${reviewRow("Deleted", fmtDate(b.deleted_at))}${reviewRow("Reason", b.deleted_reason || "—")}
      </div>
      <div class="detail-section"><h4>Lines (${(b.lines || []).length})</h4>
        ${(b.lines || []).length ? b.lines.map(l => `<div class="review-row"><span>${esc(l.our_product_id)}</span><span>qty ${l.quantity_shipped} · ₹${l.line_total}</span></div>`).join("") : "<p style='color:var(--muted)'>None</p>"}
      </div>
      <p style="margin-top:12px;font-size:12px;color:var(--muted);">Restoring un-hides the bill only — it stays cancelled if it already was.</p>`;
    } else if (type === "customer_placement") {
      const p = await api(`/customer-orders/placements/${id}`);
      body = `<div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("Status", p.status)}${reviewRow("Cancel reason", p.cancel_reason || "—")}
        ${reviewRow("Deleted", fmtDate(p.deleted_at))}${reviewRow("Reason", p.deleted_reason || "—")}
      </div>
      <div class="detail-section"><h4>Lines (${(p.lines || []).length})</h4>
        ${(p.lines || []).length ? p.lines.map(l => `<div class="review-row"><span>${esc(l.our_product_id)}</span><span>qty ${l.quantity} · billed ${l.quantity_billed || 0}</span></div>`).join("") : "<p style='color:var(--muted)'>None</p>"}
      </div>
      <p style="margin-top:12px;font-size:12px;color:var(--muted);">Restoring un-hides the order only — it stays cancelled if it already was.</p>`;
    } else if (type === "customer_return") {
      const r = await api(`/customer-returns/${id}`);
      body = `<div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("Return number", r.return_number)}${reviewRow("Credit amount", "₹" + r.credit_amount)}
        ${reviewRow("Customer", r.customer_label)}${reviewRow("Notes", r.notes || "—")}
        ${reviewRow("Deleted", fmtDate(r.deleted_at))}${reviewRow("Reason", r.deleted_reason || "—")}
      </div>
      <div class="detail-section"><h4>Lines (${(r.lines || []).length})</h4>
        ${(r.lines || []).length ? r.lines.map(l => `<div class="review-row"><span>${esc(l.our_product_id)}</span><span>qty ${l.quantity_returned} · ₹${l.line_calculated}</span></div>`).join("") : "<p style='color:var(--muted)'>None</p>"}
      </div>`;
    }

    const adminOnlyType = ["receipt", "debit_note", "customer_bill", "customer_placement", "customer_return"].includes(type);
    const canActOnThis = adminOnlyType ? isAdmin() : canWrite("recycle");
    openDetail(`Deleted ${type}`, body,
      `${canActOnThis ? `<button class="btn btn-primary" style="flex:1;" onclick="App.restoreItem('${type}',${id})">Restore</button>
       <button class="btn btn-danger" onclick="App.purgeItem('${type}',${id})">Delete Forever</button>` : ""}
       <button class="btn btn-secondary" onclick="App.closeDetail()">Close</button>`,
      "md"
    );
  }

  const RESTORE_PATHS = { route: "routes", city: "cities", customer: "customers", vendor: "vendors", catalog_product: "catalog-products", addon: "addons", staff: "staff", receipt: "receipts", debit_note: "debit-notes", customer_bill: "customer-bills", customer_placement: "customer-placements", customer_return: "customer-returns" };

  async function restoreItem(type, id) {
    if (!confirm(`Restore this ${type}?`)) return;
    const path = RESTORE_PATHS[type] || `${type}s`;
    try {
      await api(`/recycle-bin/${path}/${id}/restore`, { method: "POST" });
      closeDetail();
      invalidateCache();
      if (["receipt", "debit_note"].includes(type)) {
        invalidateCache("/vendor-orders");
        invalidateCache("/accounts-payable");
      }
      if (["customer_bill", "customer_placement", "customer_return"].includes(type)) {
        invalidateCache("/customer-orders");
        invalidateCache("/accounts-receivable");
        invalidateCache("/customer-returns");
      }
      await refreshAll();
      if (peopleTab === "vendors") await Vendors.load();
      if (document.getElementById("view-people") && !document.getElementById("view-people").classList.contains("hidden") && peopleTab === "customers") {
        await loadCustomers();
      }
      if (document.getElementById("view-recycle") && !document.getElementById("view-recycle").classList.contains("hidden")) {
        await loadRecycleBin();
      }
      const LABELS = { receipt: "Receipt/bill", debit_note: "Debit note", customer_bill: "Bill", customer_placement: "Order", customer_return: "Return" };
      toast(`${LABELS[type] || type} restored`, "success");
    } catch (e) { toast(e.message, "error"); }
  }

  async function purgeItem(type, id) {
    if (!confirm("Permanently delete? This cannot be undone.")) return;
    const path = RESTORE_PATHS[type] || `${type}s`;
    try {
      await api(`/recycle-bin/${path}/${id}`, { method: "DELETE" });
      closeDetail();
      invalidateCache();
      if (["receipt", "debit_note"].includes(type)) {
        invalidateCache("/vendor-orders");
        invalidateCache("/accounts-payable");
      }
      if (["customer_bill", "customer_placement", "customer_return"].includes(type)) {
        invalidateCache("/customer-orders");
        invalidateCache("/accounts-receivable");
        invalidateCache("/customer-returns");
      }
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
            ${canSetupWrite ? `<button type="button" class="lookup-chip-edit" title="Edit" onclick="App.editLookup(${i.id})">Edit</button>
            <button type="button" class="lookup-chip-x" title="Remove" onclick="App.deleteLookup(${i.id})">×</button>` : ""}
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

  async function editLookup(id) {
    const row = lookups.find(l => l.id === id);
    if (!row) return;
    const next = prompt(`Rename “${row.value}”`, row.value);
    if (next == null) return;
    const val = next.trim();
    if (!val) return toast("Name required", "error");
    if (val === row.value) return;
    try {
      await api(`/lookups/${id}`, { method: "PATCH", body: JSON.stringify({ value: val }) });
      invalidateCache("/lookups");
      invalidateCache("/catalog");
      invalidateCache("/stock");
      lookups = await api("/lookups", {}, 0);
      renderLookupSections();
      updateSetupHubCounts();
      toast("Updated", "success");
    } catch (e) { toast(e.message, "error"); }
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
    api, toast, esc, fmtDate, fmtDay, timeAgo, reviewRow, productIdLabel, changeHistoryTable, openDetail,
    closeDetail: () => closeDetail(), detailBack, detailFooterChild, ledgerDetailCard, bindLedgerRowClicks,
    entityLedgerTableHtml, activityTableHtml, loadActivity,
    getCities: () => cities,
    getVendors: () => vendors,
    setVendors,
    getLookups: () => lookups,
    refreshStats: refreshAll,
    invalidateCache,
    peekCache,
    showLoading, hideLoading,
    uploadImage,
    apiBase: () => API,
    headers,
    checkBackend,
    can, canWrite, canRead, isAdmin,
    get staffUser() { return staffUser; },
    showView,
    showPeopleTab,
  });

  function openCustomerWizard() {
    if (!cities.length) {
      toast("Add cities in Setup first", "error");
      return;
    }
    wizardStep = 1;
    wizardForm = {};
    document.getElementById("wizard").classList.remove("hidden");
    renderWizard();
  }
  function closeWizard() { document.getElementById("wizard").classList.add("hidden"); }

  function renderWizard() {
    const steps = document.getElementById("wizard-steps");
    if (steps) { steps.innerHTML = ""; steps.classList.add("hidden"); }
    const body = document.getElementById("wizard-body");
    const footer = document.getElementById("wizard-footer");
    const today = new Date().toISOString().slice(0, 10);

    if (wizardStep === 1) {
      body.innerHTML = `<div class="create-form">
        <div><label class="label">Business name *</label><input id="wf-business_name" class="input" value="${esc(wizardForm.business_name || "")}" autofocus /></div>
        <div class="create-field-row">
          <div><label class="label">Phone *</label><input id="wf-phone" class="input" type="tel" maxlength="10" value="${esc(wizardForm.phone || "")}" /></div>
          <div><label class="label">City *</label>
            <select id="wf-city_id" class="input">
              <option value="">— Select —</option>
              ${cities.map(c => `<option value="${c.id}" ${wizardForm.city_id == c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}
            </select>
          </div>
        </div>
        <div class="create-field-row">
          <div>
            <label class="label">Payment type *</label>
            <div style="display:flex;gap:8px;margin-top:4px;">
              <label id="wf-label-cash" style="display:flex;align-items:center;gap:6px;font-size:14px;cursor:pointer;padding:8px 14px;border:1px solid var(--border);border-radius:8px;flex:1;justify-content:center;${(wizardForm.payment_type||'CREDIT')==='CASH'?'background:#fef3c7;border-color:#f59e0b;font-weight:600;':''}">
                <input type="radio" name="wf-payment_type" value="CASH" ${(wizardForm.payment_type||'CREDIT')==='CASH'?'checked':''} onchange="App.onWizardPaymentTypeChange('CASH')" /> CASH
              </label>
              <label id="wf-label-credit" style="display:flex;align-items:center;gap:6px;font-size:14px;cursor:pointer;padding:8px 14px;border:1px solid var(--border);border-radius:8px;flex:1;justify-content:center;${(wizardForm.payment_type||'CREDIT')==='CREDIT'?'background:#eff6ff;border-color:#3b82f6;font-weight:600;':''}">
                <input type="radio" name="wf-payment_type" value="CREDIT" ${(wizardForm.payment_type||'CREDIT')==='CREDIT'?'checked':''} onchange="App.onWizardPaymentTypeChange('CREDIT')" /> CREDIT
              </label>
            </div>
          </div>
          <div id="wf-credit-limit-wrap" style="${(wizardForm.payment_type||'CREDIT')==='CASH'?'display:none':''}">
            <label class="label">Credit limit (₹)</label>
            <input id="wf-credit_limit" class="input" type="number" min="0" step="0.01" value="${esc(wizardForm.credit_limit || "")}" />
          </div>
        </div>
        <div class="create-field-row">
          <div><label class="label">Opening (₹)</label><input id="wf-opening_due" class="input" type="number" min="0" step="0.01" value="${esc(wizardForm.opening_balance_due || "")}" /></div>
          <div><label class="label">As on</label><input id="wf-opening_as_on" class="input" type="date" value="${esc(wizardForm.opening_balance_as_on || today)}" /></div>
        </div>
        <details class="create-details">
          <summary>More</summary>
          <div class="create-details-body">
            <div><label class="label">Person</label><input id="wf-person_name" class="input" value="${esc(wizardForm.person_name || "")}" /></div>
            <div class="create-field-row">
              <div><label class="label">Secondary phone</label><input id="wf-secondary_phone" class="input" type="tel" maxlength="10" value="${esc(wizardForm.secondary_phone || "")}" /></div>
              <div><label class="label">Alias</label><input id="wf-alias" class="input" value="${esc(wizardForm.alias || "")}" /></div>
            </div>
            <div><label class="label">GST</label><input id="wf-gst_number" class="input" value="${esc(wizardForm.gst_number || "")}" maxlength="15" style="text-transform:uppercase;" /></div>
            <div><label class="label">Address</label><textarea id="wf-address" class="input" rows="2">${esc(wizardForm.address || "")}</textarea></div>
            <div><label class="label">Notes</label><textarea id="wf-additional_details" class="input" rows="2">${esc(wizardForm.additional_details || "")}</textarea></div>
          </div>
        </details>
      </div>`;
      footer.innerHTML = `<button class="btn btn-secondary" onclick="App.closeWizard()">Cancel</button>
        <button class="btn btn-primary" style="flex:1;" id="wizard-create-btn" onclick="App.createCustomer()">Create</button>`;
    } else {
      const id = wizardForm._result?.id;
      const waOk = !!wizardForm._result?.whatsapp_sent;
      body.innerHTML = `<div style="text-align:center;padding:20px 0 8px;">
        <div class="success-icon">✓</div><h3 style="margin:0 0 8px;">Customer created</h3>
        <p style="color:var(--muted);margin:0 0 16px;">${esc(wizardForm._result?.business_name || "")}</p>
        <div class="review-grid" style="text-align:left;">
          ${reviewRow("Phone", wizardForm._result?.phone)}
          ${reviewRow("Password", wizardForm._result?.portal_password || "— (check WhatsApp)")}
          ${reviewRow("WhatsApp", waOk ? "Sent" : ("Not sent — " + (wizardForm._result?.whatsapp_error || "try again")))}
        </div>
        ${!waOk && id ? `<p class="people-field-hint" style="margin:12px 0 0;">Customer saved. Retry WhatsApp issues a new password.</p>` : ""}
      </div>`;
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="App.openCustomerWizard()">+ Another</button>
        ${!waOk && id ? `<button class="btn btn-secondary" onclick="App.resendWhatsApp(${id})">Retry WhatsApp</button>` : ""}
        ${id ? `<button class="btn btn-secondary" onclick="App.finishCustomerOpen(${id})">Open profile</button>
        <button class="btn btn-primary" style="flex:1;" onclick="App.finishCustomerPlace(${id})">Place order →</button>`
          : `<button class="btn btn-primary" style="flex:1;" onclick="App.closeWizard();App.showPeopleTab('customers')">View Customers</button>`}`;
    }
  }

  function onCustomerWizardCityChange(val) {
    wizardForm.city_id = val ? parseInt(val, 10) : null;
    const hint = document.getElementById("wf-city-hint");
    if (hint) hint.innerHTML = customerCityHint(wizardForm.city_id);
  }

  function onWizardPaymentTypeChange(val) {
    wizardForm.payment_type = val;
    // Show/hide credit limit — do NOT re-render the form (would wipe user input)
    const wrap = document.getElementById("wf-credit-limit-wrap");
    if (wrap) wrap.style.display = val === "CASH" ? "none" : "";
    if (val === "CASH") {
      const el = document.getElementById("wf-credit_limit");
      if (el) el.value = "";
      wizardForm.credit_limit = "";
    }
    // Update label highlight styles in place
    const cashLabel = document.getElementById("wf-label-cash");
    const creditLabel = document.getElementById("wf-label-credit");
    if (cashLabel) {
      cashLabel.style.background = val === "CASH" ? "#fef3c7" : "";
      cashLabel.style.borderColor = val === "CASH" ? "#f59e0b" : "";
      cashLabel.style.fontWeight = val === "CASH" ? "600" : "";
    }
    if (creditLabel) {
      creditLabel.style.background = val === "CREDIT" ? "#eff6ff" : "";
      creditLabel.style.borderColor = val === "CREDIT" ? "#3b82f6" : "";
      creditLabel.style.fontWeight = val === "CREDIT" ? "600" : "";
    }
  }

  function finishCustomerOpen(id) {
    closeWizard();
    openCustomerDetail(id);
  }

  function finishCustomerPlace(id) {
    closeWizard();
    createCustomerOrder(id);
  }

  function reviewRow(label, val, rawHtml = false) {
    const empty = val == null || val === "";
    if (empty && !rawHtml) {
      return `<div class="review-row"><span class="review-label">${label}</span><span class="review-value review-empty">—</span></div>`;
    }
    const content = rawHtml ? val : esc(String(val));
    return `<div class="review-row"><span class="review-label">${label}</span><span class="review-value">${content}</span></div>`;
  }

  // Vendor bills using their own product id, we track ours — show both so nothing gets
  // mismatched. Returns a plain (unescaped) string; wrap with esc()/ctx.esc() at the call site.
  function productIdLabel(p) {
    const our = p?.our_product_id || "";
    const year = p?.year_group ? ` [${p.year_group}]` : "";
    const vid = p?.vendor_product_id;
    return vid ? `${our}${year} / (${vid})` : `${our}${year}`;
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

  async function uploadImage(vendorId, ourProductId, file, imageIndex = 1, yearGroup = null) {
    const fd = new FormData();
    fd.append("vendor_id", String(vendorId));
    fd.append("our_product_id", ourProductId);
    fd.append("image_index", String(imageIndex));
    if (yearGroup) fd.append("year_group", yearGroup);
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
    ["business_name","person_name","phone","secondary_phone","alias","gst_number","address","additional_details","credit_limit"].forEach(k => {
      const el = document.getElementById(`wf-${k}`); if (el) wizardForm[k] = el.value.trim();
    });
    const cityEl = document.getElementById("wf-city_id");
    if (cityEl) wizardForm.city_id = cityEl.value ? parseInt(cityEl.value) : null;
    const ov = document.getElementById("wf-credit_override");
    if (ov) wizardForm.credit_override = ov.checked;
    const ptEl = document.querySelector('input[name="wf-payment_type"]:checked');
    if (ptEl) wizardForm.payment_type = ptEl.value;
    const od = document.getElementById("wf-opening_due");
    if (od) wizardForm.opening_balance_due = od.value.trim();
    const oa = document.getElementById("wf-opening_as_on");
    if (oa) wizardForm.opening_balance_as_on = oa.value;
  }

  function wizardBack() { collectWizard(); wizardStep = 1; renderWizard(); }
  function wizardNext() { createCustomer(); }

  async function createCustomer() {
    collectWizard();
    if (!wizardForm.business_name) return toast("Business name required", "error");
    const phone = normalizePhoneDigits(wizardForm.phone);
    if (phone.length !== 10) return toast("Phone must be 10 digits", "error");
    wizardForm.phone = phone;
    if (!wizardForm.city_id) return toast("Please select a city", "error");
    const sec = validateOptionalPhone(wizardForm.secondary_phone);
    if (!sec.ok) return toast("Secondary phone must be 10 digits or blank", "error");
    const gst = validateGstin(wizardForm.gst_number);
    if (!gst.ok) return toast("GST looks invalid — use 15-char GSTIN or leave blank", "error");
    const btn = document.getElementById("wizard-create-btn");
    if (btn) btn.disabled = true;
    try {
      const openingDue = wizardForm.opening_balance_due ? parseFloat(wizardForm.opening_balance_due) : 0;
      const result = await api("/customers", { method: "POST", body: JSON.stringify({
        business_name: wizardForm.business_name, person_name: wizardForm.person_name || null,
        phone: wizardForm.phone, secondary_phone: sec.value,
        alias: wizardForm.alias || null, city_id: wizardForm.city_id,
        gst_number: gst.value, address: wizardForm.address || null,
        additional_details: wizardForm.additional_details || null,
        payment_type: wizardForm.payment_type || "CREDIT",
        credit_limit: (wizardForm.payment_type === "CASH") ? 0 : (wizardForm.credit_limit ? parseFloat(wizardForm.credit_limit) : null),
        credit_override: !!wizardForm.credit_override,
        opening_balance_due: openingDue > 0 ? openingDue : null,
        opening_balance_as_on: openingDue > 0 ? (wizardForm.opening_balance_as_on || null) : null,
      })});
      wizardForm._result = result; wizardStep = 2; renderWizard();
      invalidateCache("/customers");
      invalidateCache("/stats");
      await refreshAll();
      if (peopleTab === "customers") await loadCustomers();
      toast("Customer created", "success");
      if (!result.whatsapp_sent) toast(result.whatsapp_error || "WhatsApp not sent — use Retry", "error");
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
      try {
        await enterApp();
      } catch (e) {
        showLoginShell(e?.message || "Could not open app — check login / network");
      }
    }
  }

  /** @deprecated use showView('buying'|'selling') — kept for older deep-links */
  function setOrdersType(type) {
    ordersType = type === "customer" ? "customer" : "vendor";
    showView(ordersType === "customer" ? "selling" : "buying");
  }

  return {
    login, staffLogin, setLoginTab, logout, toggleSidebar, showView, goBack, updateGlobalBack,
    showPeopleHub, showPeopleTab, renderPeopleCustomerSearch, renderPeopleVendorSearch, showSetupHub, showSetupTab,
    showMoreHub, showMoreSafety,
    setOrdersType,
    refreshAll, loadCustomers, reloadCustomers, loadActivity, openActivityItem, detailBack,
    openRouteDetail, openRouteModal, saveRoute, deleteRoute,
    openCityDetail, openCityModal, saveCity, deleteCity,
    openCustomerWizard, closeWizard, wizardBack, wizardNext, createCustomer,
    onCustomerWizardCityChange, onCustomerEditCityChange, onWizardPaymentTypeChange, onEditPaymentTypeChange, finishCustomerOpen, finishCustomerPlace, resendWhatsApp,
    openCustomerDetail, closeDetail, openCustomerEdit, closeEditModal, saveCustomer,
    deleteCustomer, toggleCustomerActive, restoreCustomer, sendCredentials,
    setCustomerStatusTab, toggleInactiveCustomers, toggleMissingPhoneFilter, setCustomerOpeningBalance, saveCustomerOpeningBalance,
    toggleCustomerLedgerRow, openSelling, billCustomer, collectCustomer, openCustomerMoney,
    loadRecycleBin, setRecycleTab, openRecycleDetail, restoreItem, purgeItem,
    addLookup, submitLookup, editLookup, deleteLookup, openCustomerLedgerEntry, createCustomerOrder,
    closeModal, init,
    downloadExportKind, downloadBackupZip,
    debouncedLoadCustomers, debouncedVendorSearch, debouncedCatalogSearch, debouncedAddonSearch, debouncedStockSearch,
    setVendors,
  };
})();

App.init();
