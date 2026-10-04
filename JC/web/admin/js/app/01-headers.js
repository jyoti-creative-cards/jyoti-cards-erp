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
    // Viewing series/bills only needs vendor_orders.read/customer_orders.read
    // server-side (require_any_permission in bill_series.py) — only create/delete
    // are actually admin-only, and BillSeries.js's own canWrite() already gates
    // those separately. Hiding the whole tile behind isAdmin() blocked e.g. a
    // "Sell" staffer from checking "what's the next bill number" even though the
    // backend was fine with them seeing it.
    document.getElementById("setup-tile-billseries")?.classList.toggle("hidden",
      !(isAdmin() || canRead("vendor_orders") || canRead("customer_orders")));
    // These three were missing from this list entirely — any setup.read-only staffer
    // (e.g. the built-in "Setup" role preset in staff.js) saw all three tiles and got
    // a 403 on every one, since each needs a real permission (or admin) the Setup
    // preset alone doesn't grant.
    document.getElementById("setup-tile-freight")?.classList.toggle("hidden",
      !(isAdmin() || canRead("vendor_orders") || canRead("customer_orders")));
    document.getElementById("setup-tile-paymodes")?.classList.toggle("hidden",
      !(isAdmin() || can("finance.write") || can("ap.write") || can("ar.write")));
    document.getElementById("setup-tile-export")?.classList.toggle("hidden", !isAdmin());
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
          logout("Session expired — please sign in again");
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
      let res;
      try {
        res = await fetch(`${API}/routes`, { headers: h });
      } catch (netErr) {
        // fetch() itself throws (TypeError) for network-level failures — backend
        // down, DNS failure, offline — before res even exists. This used to fall
        // through to the generic catch below and get reported as "Invalid admin
        // key", telling an admin debugging an outage that their key was wrong when
        // the server was actually unreachable.
        throw new Error("Could not reach server — check your connection");
      }
      if (!res.ok) {
        // 401/403 from this endpoint always means a bad key (it has no other
        // precondition) — anything else (500, etc.) is a real backend problem, not
        // a wrong key, so don't tell the admin their password is wrong when the
        // server is actually broken.
        if (res.status === 401 || res.status === 403) throw new Error("Invalid admin key");
        throw new Error(`Server error (${res.status}) — try again in a moment`);
      }
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

  function logout(msg) {
    sessionStorage.removeItem("jc_admin_key");
    sessionStorage.removeItem("jc_staff_token");
    sessionStorage.removeItem("jc_staff_user");
    sessionStorage.removeItem("jc_auth_mode");
    // location.reload() only schedules a navigation — it doesn't halt this script,
    // so a plain thrown Error after logout() used to get destroyed by the reload
    // before any toast could paint. Stash the reason so init() can show it on the
    // fresh login screen instead of silently dropping the user with no explanation.
    if (msg) sessionStorage.setItem("jc_logout_msg", msg);
    else sessionStorage.removeItem("jc_logout_msg");
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

