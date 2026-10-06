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
  let customerRealOnly = true;
  let customerAr = null;
  let viewStack = [];
  let currentViewName = null;

