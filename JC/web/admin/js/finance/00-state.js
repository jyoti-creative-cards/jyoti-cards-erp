/** Finance — money hub (Due / Collect / Pay / Freight / …) */
const Finance = (() => {
  let ctx = {};
  let vendors = [];
  let customers = [];
  let needsActionLoadFailed = false;
  let expenses = [];
  let overview = null;
  let currentVendor = null;
  let currentCustomer = null;
  let apDetail = null;
  let arDetail = null;
  let apTab = "statement";
  let arTab = "statement";
  let expandedBillId = null;
  let freightAgents = [];
  let freightAgentId = null;
  let freightLedger = [];
  let routeCollections = [];
  let routeDetail = null;
  let routeCustomerDetail = null;
  let activeChip = "due";
  let hubMode = "needs_action";
  let browseSection = "ap";
  let reportTab = "revenue";
  let hubSearch = "";
  let showSettled = false;
  let expenseFilters = { from_date: "", to_date: "", category: "" };
  let journals = [];
  let journalHits = { from: [], to: [], line: [] };
  let journalTimer = null;
  let journalForm = null;
  let settleFile = null;
  let freightSettleFile = null;
  let freightPayMode = "settle"; // settle | advance
  let paymentModes = [];
  let chipCounts = { due: 0, ar: 0, ap: 0, freight: 0 };
  let dues = null; // from GET /finance/dues — single money API

  const CHART_LABELS = {
    revenue: "Cash in",
    expenses: "Expenses",
    ap_paid: "Paid vendors",
    cost: "Cash out",
    profit: "Net cash",
    net_cash: "Net cash",
  };

  const CHIP_SUB = {
    due: "Who needs money action",
    ar: "Money to collect from customers",
    ap: "Money to pay vendors",
    freight: "Freight agent dues",
    expenses: "Rent, salary, misc",
    journal: "Move stock or record sample catalogues",
    routes: "Collect by route",
    reports: "Quick cash snapshot — full books under More → Reports",
  };

